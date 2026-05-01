"""
Interactive Telegram bot command handlers with inline keyboards.
ConversationHandler for multi-step flows (setup, clone creation).
"""

import logging
import asyncio
import re
from datetime import datetime
from telegram import Update

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, ContextTypes
)

from database import (
    save_user, get_user, get_user_jobs, get_user_job,
    create_clone_job, delete_job, update_job_state,
    get_user_auto_forwards, delete_auto_forward
)
from clone_engine import run_historical_clone
from user_client import get_user_client, remove_user_client

from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded
from database import update_string_session

log = logging.getLogger("Handlers")

# ── Conversation States ─────────────────────────────────
(SETUP_API_ID, SETUP_API_HASH, ASK_PHONE, ASK_OTP, ASK_PASSWORD,
 CLONE_SOURCE, CLONE_DEST, CLONE_DIRECTION, CLONE_DELAY, 
 CLONE_MEDIA_ONLY, CLONE_AUTO_FORWARD,
 CONFIRM_CLONE) = range(12)

# ── Helper Functions ────────────────────────────────────

def parse_t_me_c_link(link: str):
    match = re.search(r"t\.me/c/(\d+)/(\d+)", link)
    if not match:
        return None, None

    internal_id = match.group(1)
    message_id = int(match.group(2))

    chat_id = int(f"-100{internal_id}")

    return chat_id, message_id


async def extract_thread_id(client, chat_id: int, message_id: int):
    msg = await client.get_messages(chat_id, message_id)
    return getattr(msg, "message_thread_id", None)

def main_menu_keyboard():
    """Build the interactive main menu."""
    keyboard = [
        [InlineKeyboardButton("🔧 Setup API Credentials", callback_data="setup")],
        [InlineKeyboardButton("📋 My Clone Jobs", callback_data="my_jobs")],
        [InlineKeyboardButton("➕ New Clone Job", callback_data="new_clone")],
        [InlineKeyboardButton("🔄 Auto-Forwards", callback_data="auto_forwards")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def progress_callback(user_id, job_id, current, total, percent):
    """Progress update during cloning — state already saved."""
    pass

async def complete_callback(user_id, job_id, total, error=None):
    """Called when cloning finishes."""
    if error:
        log.warning(f"Job #{job_id} for user {user_id} failed: {error}")
    else:
        log.info(f"Job #{job_id} for user {user_id} complete: {total} messages")

# ── Core Commands ───────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message with interactive menu."""
    user = update.effective_user
    user_data = await get_user(user.id)
    
    welcome = (
        f"👋 Welcome, {user.first_name}!\n\n"
        f"🤖 **Multi-Channel Telegram Cloner**\n\n"
        f"Clone any Telegram channel to your own channels.\n"
        f"✅ No 'Forwarded from' tag — clean copies\n"
        f"✅ Auto-forward new posts in real-time\n"
        f"✅ Multiple users can use this bot\n\n"
    )
    
    if user_data:
        masked_id = str(user_data["api_id"])[:4] + "****"
        welcome += f"✅ **Registered** (API ID: `{masked_id}`)\n"
    else:
        welcome += "⚠️ **Not registered** — tap Setup below.\n"
    
    await update.message.reply_text(
        welcome,
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detailed help."""
    text = (
        "📖 **How to Use This Bot**\n\n"
        "**Step 1:** `/setup` — Provide your Telegram API ID and Hash\n"
        "   Get them at https://my.telegram.org/apps\n\n"
        "**Step 2:** Add this bot to your channels:\n"
        "   • Add to SOURCE channel (as member)\n"
        "   • Add to DESTINATION channel (as Admin, with\n"
        "     'Post Messages' permission)\n\n"
        "**Step 3:** `/clone` — Create a clone job\n"
        "   • Source: channel to copy FROM\n"
        "   • Destination: channel to copy TO\n"
        "   • Auto-forward: YES = live forwarding\n\n"
        "**Commands:**\n"
        "`/start` — Main menu\n"
        "`/setup` — Set API credentials\n"
        "`/clone` — New clone job\n"
        "`/jobs` — View your jobs\n"
        "`/forwards` — Manage auto-forwards\n"
        "`/delete_job <id>` — Delete a job\n"
        "`/delete_forward <id>` — Delete auto-forward\n"
        "`/cancel` — Cancel current operation\n"
        "`/help` — This message\n\n"
        "🔒 Your credentials are stored securely in Supabase."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any ongoing conversation."""
    await update.message.reply_text(
        "❌ Operation cancelled. Use /start for the menu."
    )
    return ConversationHandler.END

# ── Setup: API Credentials ──────────────────────────────

async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Begin API setup."""
    query = update.callback_query
    if query:
        await query.answer()
    
    text = (
        "🔧 **API Credentials Setup**\n\n"
        "I need your Telegram **API ID** and **API Hash**.\n"
        "These are NOT your bot token.\n\n"
        "1️⃣ Go to https://my.telegram.org/apps\n"
        "2️⃣ Log in with your phone number\n"
        "3️⃣ Create an app if you haven't\n"
        "4️⃣ Copy your **API ID** and **API Hash**\n\n"
        "📤 **Send me your API ID** (just the number):\n"
        "_(or type /cancel)_"
    )
    
    if query:
        await query.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")
    
    return SETUP_API_ID

async def setup_api_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive API ID."""
    try:
        api_id = int(update.message.text.strip())
        context.user_data["setup_api_id"] = api_id
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid. API ID is a number (e.g., `123456`).\nTry again:"
        )
        return SETUP_API_ID
    
    await update.message.reply_text(
        "✅ API ID received!\n\n"
        "📤 **Now send your API Hash:**\n"
        "_(a long hex string like `1a2b3c4d5e6f...`)_\n"
        "_(or type /cancel)_"
    )
    return SETUP_API_HASH

async def setup_api_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive API Hash and complete setup."""
    api_hash = update.message.text.strip()
    api_id = context.user_data["setup_api_id"]
    
    if len(api_hash) < 10:
        await update.message.reply_text(
            "❌ That looks too short for an API Hash.\nPlease try again:"
        )
        return SETUP_API_HASH
    
    await save_user(update.effective_user.id, api_id, api_hash)

    await update.message.reply_text(
        "📱 Send your phone number (with country code)\nExample: +97798XXXXXXXX"
    )

    return ASK_PHONE


async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    phone = update.message.text.strip()

    user_data = await get_user(user_id)

    client = Client(
        name=f"user_{user_id}",
        api_id=user_data["api_id"],
        api_hash=user_data["api_hash"],
        in_memory=True
    )

    await client.connect()

    sent_code = await client.send_code(phone)

    context.user_data["temp_client"] = client
    context.user_data["phone_data"] = (phone, sent_code.phone_code_hash)

    await update.message.reply_text("📩 Enter the OTP sent to your Telegram")

    return ASK_OTP


async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = update.message.text.strip()

    client = context.user_data.get("temp_client")
    phone_data = context.user_data.get("phone_data")

    if not client or not phone_data:
        await update.message.reply_text("❌ Session expired. Run /setup again.")
        return ConversationHandler.END

    phone, phone_code_hash = phone_data

    try:
        await client.sign_in(phone, phone_code_hash, code)
    except SessionPasswordNeeded:
        context.user_data["awaiting_password"] = True
        await update.message.reply_text("🔐 Enter your 2FA password")
        return ASK_PASSWORD

    session_string = await client.export_session_string()

    await update_string_session(user_id, session_string)

    await client.disconnect()

    context.user_data.pop("temp_client", None)
    context.user_data.pop("phone_data", None)

    await update.message.reply_text("✅ Login successful! Setup complete.")

    return ConversationHandler.END

async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    password = update.message.text.strip()

    client = context.user_data.get("temp_client")

    if not client:
        await update.message.reply_text("❌ Session expired. Run /setup again.")
        return ConversationHandler.END

    try:
        await client.check_password(password)
    except Exception:
        await update.message.reply_text("❌ Wrong password. Try again.")
        return ASK_PASSWORD

    session_string = await client.export_session_string()
    await update_string_session(user_id, session_string)

    await client.disconnect()

    context.user_data.clear()

    await update.message.reply_text("✅ Login successful! Setup complete.")

    return ConversationHandler.END

# ── New Clone Job ───────────────────────────────────────

async def new_clone_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Begin clone job creation."""
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    user_data = await get_user(user_id)
    
    if not user_data:
        text = "⚠️ **Setup required first!**\nUse /setup to provide your API credentials."
        if query:
            await query.message.reply_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, parse_mode="Markdown")
        return ConversationHandler.END
    
    text = (
        "📋 **New Clone Job — Step 1/7**\n\n"
        "What is the **source channel**?\n"
        "(Channel to clone FROM)\n\n"
        "Send the username (`@channel`) or chat ID:\n"
        "_(or type /cancel)_"
    )
    
    if query:
        await query.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")
    
    return CLONE_SOURCE

async def clone_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    chat_id, message_id = parse_t_me_c_link(text)

    thread_id = None
    source = text

    if chat_id and message_id:
        try:
            client = await get_user_client(user_id)

            thread_id = await extract_thread_id(client, chat_id, message_id)

            source = chat_id

            await update.message.reply_text(
                f"✅ Topic detected\nChat ID: `{chat_id}`\nThread ID: `{thread_id}`",
                parse_mode="Markdown"
            )

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return CLONE_SOURCE

    context.user_data["clone_source"] = source
    context.user_data["source_thread_id"] = thread_id

    await update.message.reply_text(
        f"✅ Source: `{source}`\n\nSend destination channel or topic link:",
        parse_mode="Markdown"
    )

    return CLONE_DEST

async def clone_dest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    chat_id, message_id = parse_t_me_c_link(text)

    thread_id = None
    dest = text

    if chat_id and message_id:
        try:
            client = await get_user_client(user_id)

            thread_id = await extract_thread_id(client, chat_id, message_id)

            dest = chat_id

            await update.message.reply_text(
                f"✅ Destination topic detected\nChat ID: `{chat_id}`\nThread ID: `{thread_id}`",
                parse_mode="Markdown"
            )

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return CLONE_DEST

    context.user_data["clone_dest"] = dest
    context.user_data["dest_thread_id"] = thread_id

    keyboard = [
        [InlineKeyboardButton("📅 Oldest", callback_data="dir_oldest")],
        [InlineKeyboardButton("🕐 Newest", callback_data="dir_newest")],
    ]

    await update.message.reply_text(
        f"✅ Destination: `{dest}`\n\nChoose direction:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

    return CLONE_DIRECTION

async def clone_direction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive direction."""
    query = update.callback_query
    await query.answer()
    
    direction = "oldest" if "oldest" in query.data else "newest"
    context.user_data["clone_direction"] = direction
    
    await query.message.reply_text(
        f"✅ Direction: `{direction.upper()}`\n\n"
        "**Step 4/7** — **Delay** between messages (seconds)?\n\n"
        "Recommended: `1.0` (safe)\n"
        "Fast: `0.5` (risk of rate limits)\n"
        "Slow: `2.0` (very safe)\n\n"
        "Send a number (e.g., `1.0`):\n"
        "_(or /cancel)_",
        parse_mode="Markdown"
    )
    return CLONE_DELAY

async def clone_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive delay value."""
    try:
        delay = float(update.message.text.strip())
        if delay < 0.3:
            await update.message.reply_text("❌ Minimum 0.3s. Enter a higher value:")
            return CLONE_DELAY
        context.user_data["clone_delay"] = delay
    except ValueError:
        await update.message.reply_text("❌ Invalid. Enter a number like `1.0`:", parse_mode="Markdown")
        return CLONE_DELAY
    
    keyboard = [
        [InlineKeyboardButton("✅ All content (text + media)", callback_data="media_all")],
        [InlineKeyboardButton("📷 Media only (photos/videos)", callback_data="media_only")],
    ]
    
    await update.message.reply_text(
        f"✅ Delay: `{delay}s`\n\n"
        "**Step 5/7** — **Content filter?**\n\n"
        "• **All content** — Text, photos, videos, files\n"
        "• **Media only** — Just photos and videos",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CLONE_MEDIA_ONLY

async def clone_media_only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive media-only preference."""
    query = update.callback_query
    await query.answer()
    
    only_media = query.data == "media_only"
    context.user_data["clone_media_only"] = only_media
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes — auto-forward new posts", callback_data="af_yes")],
        [InlineKeyboardButton("❌ No — clone history only", callback_data="af_no")],
    ]
    
    await query.message.reply_text(
        f"✅ Media only: `{'Yes' if only_media else 'No'}`\n\n"
        "**Step 6/7** — **Auto-Forward?**\n\n"
        "• **Yes** — After cloning history, new source\n"
        "  posts auto-forward to destination.\n"
        "• **No** — Clone history only.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CLONE_AUTO_FORWARD

async def clone_auto_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive auto-forward preference & show summary."""
    query = update.callback_query
    await query.answer()
    
    auto_forward = query.data == "af_yes"
    context.user_data["clone_auto_forward"] = auto_forward
    
    s = context.user_data
    summary = (
        "📋 **Clone Job Summary**\n\n"
        f"**Source:** `{s.get('clone_source', '?')}`\n"
        f"**Destination:** `{s.get('clone_dest', '?')}`\n"
        f"**Direction:** `{s.get('clone_direction', 'oldest').upper()}`\n"
        f"**Delay:** `{s.get('clone_delay', 1.0)}s`\n"
        f"**Media only:** `{'Yes' if s.get('clone_media_only') else 'No'}`\n"
        f"**Auto-forward:** `{'Yes' if auto_forward else 'No'}`\n\n"
        "Start this clone job?"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 Start Clone!", callback_data="confirm_clone")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_clone")],
    ]
    
    await query.message.reply_text(
        summary,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CONFIRM_CLONE

async def clone_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create and start the clone job."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_clone":
        await query.message.reply_text("❌ Clone cancelled.")
        for k in ["clone_source", "clone_dest", "clone_direction", "clone_delay", "clone_media_only", "clone_auto_forward"]:
            context.user_data.pop(k, None)
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    s = context.user_data
    source = s.get("clone_source")
    dest = s.get("clone_dest")
    direction = s.get("clone_direction", "oldest")
    delay = s.get("clone_delay", 1.0)
    only_media = s.get("clone_media_only", False)
    auto_forward = s.get("clone_auto_forward", False)
    
    job_id = await create_clone_job(
        user_id,
        source,
        dest,
        direction,
        delay,
        only_media,
        auto_forward,
        source_thread_id=context.user_data.get("source_thread_id"),
        dest_thread_id=context.user_data.get("dest_thread_id"),
    )
    
    await query.message.reply_text(
        f"🚀 **Clone job #{job_id} started!**\n\n"
        f"FROM: `{source}` → TO: `{dest}`\n\n"
        f"⏳ This may take a while depending on channel size.\n"
        f"Use `/jobs` to check progress.",
        parse_mode="Markdown"
    )
    
    asyncio.create_task(run_historical_clone(
        user_id, job_id,
        on_progress=progress_callback,
        on_complete=complete_callback
    ))
    
    for k in ["clone_source", "clone_dest", "clone_direction", "clone_delay", "clone_media_only", "clone_auto_forward"]:
        context.user_data.pop(k, None)
    
    return ConversationHandler.END

# ── List Jobs ───────────────────────────────────────────

async def my_jobs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all clone jobs."""
    query = update.callback_query
    if query:
        await query.answer()
    
    jobs = await get_user_jobs(update.effective_user.id)

    if not jobs:
        text = "📋 **No clone jobs found.**\n\nTap 'New Clone Job' to start one."
        if query:
            await query.message.reply_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, parse_mode="Markdown")
        return
    
    msg = "📋 **Your Clone Jobs**\n\n"
    for j in jobs[:10]:
        status_emoji = {
            "idle": "⏸️", "running": "🔄", "complete": "✅", "failed": "❌"
        }.get(j["status"], "❓")
        msg += (
            f"{status_emoji} **#{j['id']}** `{j['source_channel']}` → `{j['dest_channel']}`\n"
            f"   Status: `{j['status']}` | Cloned: `{j['total_cloned']}`\n"
            f"   Auto-fwd: `{'Yes' if j['auto_forward'] else 'No'}`\n\n"
        )
    
    keyboard = [[InlineKeyboardButton("➕ New Clone Job", callback_data="new_clone")]]
    if query:
        await query.message.reply_text(
            msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )

async def jobs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/jobs command handler."""
    await my_jobs_command(update, context)

async def delete_job_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a clone job: /delete_job <id>"""
    if not context.args:
        await update.message.reply_text("Usage: `/delete_job <job_id>`", parse_mode="Markdown")
        return
    
    try:
        job_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Job ID must be a number.")
        return
    
    await delete_job(job_id, update.effective_user.id)
    await update.message.reply_text(f"✅ Job #{job_id} deleted.")

# ── Auto-Forwards ───────────────────────────────────────

async def auto_forwards_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all auto-forwards."""
    query = update.callback_query
    if query:
        await query.answer()
    
    forwards = await get_user_auto_forwards(update.effective_user.id)
    
    if not forwards:
        text = "🔄 **No active auto-forwards.**\n\nCreate a clone job with 'Auto-Forward' enabled."
        if query:
            await query.message.reply_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, parse_mode="Markdown")
        return
    
    msg = "🔄 **Active Auto-Forwards**\n\n"
    for f in forwards:
        msg += (
            f"**#{f['id']}** `{f['source_channel']}` → `{f['dest_channel']}`\n"
            f"   Last msg: `{f['last_msg_id']}`\n\n"
        )
    
    msg += "Use `/delete_forward <id>` to stop one."
    if query:
        await query.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")

async def forwards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/forwards command handler."""
    await auto_forwards_menu(update, context)

async def delete_forward_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete an auto-forward: /delete_forward <id>"""
    if not context.args:
        await update.message.reply_text("Usage: `/delete_forward <forward_id>`", parse_mode="Markdown")
        return
    
    try:
        fwd_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID must be a number.")
        return
    
    await delete_auto_forward(fwd_id, update.effective_user.id)
    await update.message.reply_text(f"✅ Auto-forward #{fwd_id} deleted.")

# ── Button Callbacks ────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu button clicks."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "setup":
        return await setup_start(update, context)
    elif data == "my_jobs":
        await my_jobs_command(update, context)
    elif data == "new_clone":
        return await new_clone_start(update, context)
    elif data == "auto_forwards":
        await auto_forwards_menu(update, context)
    elif data == "help":
        await help_command(update, context)
    
    return ConversationHandler.END

# ── Register Handlers ───────────────────────────────────

def register_handlers(app: Application):
    """Register all handlers with the application."""
    
    # Single commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("jobs", jobs_command))
    app.add_handler(CommandHandler("forwards", forwards_command))
    app.add_handler(CommandHandler("delete_job", delete_job_command))
    app.add_handler(CommandHandler("delete_forward", delete_forward_command))
    
    # Setup conversation
    setup_conv = ConversationHandler(
        entry_points=[
            CommandHandler("setup", setup_start),
            CallbackQueryHandler(setup_start, pattern="^setup$"),
        ],
        states={
            SETUP_API_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_api_id)],
            SETUP_API_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_api_hash)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
            ASK_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_otp)],
            ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )
    app.add_handler(setup_conv)
    
    # Clone conversation
    clone_conv = ConversationHandler(
        entry_points=[
            CommandHandler("clone", new_clone_start),
            CallbackQueryHandler(new_clone_start, pattern="^new_clone$"),
        ],
        states={
            CLONE_SOURCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_source)],
            CLONE_DEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_dest)],
            CLONE_DIRECTION: [CallbackQueryHandler(clone_direction, pattern="^dir_")],
            CLONE_DELAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_delay)],
            CLONE_MEDIA_ONLY: [CallbackQueryHandler(clone_media_only, pattern="^media_")],
            CLONE_AUTO_FORWARD: [CallbackQueryHandler(clone_auto_forward, pattern="^af_")],
            CONFIRM_CLONE: [CallbackQueryHandler(clone_confirm, pattern="^(confirm_clone|cancel_clone)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )
    app.add_handler(clone_conv)
    
    # Generic button handler (non-conversation fallback)
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(setup|my_jobs|new_clone|auto_forwards|help)$"))
    
    log.info("All handlers registered")
