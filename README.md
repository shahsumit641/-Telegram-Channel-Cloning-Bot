# 🤖 Multi-User Telegram Channel Cloner Bot

Clone Telegram channels cleanly — no "Forwarded from" tags. Multiple users supported.

## 🚀 Features
- ✅ Clean `copy_message()` clones — no forwarding attribution
- ✅ Historical clone (oldest or newest first) with configurable delay
- ✅ Auto-forward new posts to destination in real-time
- ✅ Multi-user — each user registers their own API credentials
- ✅ Persistent PostgreSQL storage via Supabase
- ✅ Interactive setup via inline keyboards
- ✅ Runs 24/7 on Render.com Background Worker

## 📋 Prerequisites
1. **Supabase** account — free tier (500MB PostgreSQL)
2. **Render.com** account — free tier (512MB RAM, 24/7 worker)
3. **Telegram API credentials** from https://my.telegram.org/apps
4. **Bot token** from @BotFather on Telegram

## 🛠 Quick Start

### 1. Supabase Setup
1. Go to https://supabase.com → Create a new project
2. Wait for database to provision (~2 min)
3. Go to **Project Settings → Database**
4. Copy the **Connection string** (Session pooler, port 6543)
5. Go to **Project Settings → API** and copy:
   - `Project URL`
   - `anon public key`

### 2. Deploy on Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

**Manual setup:**
1. Fork this repo to GitHub
2. Go to https://dashboard.render.com → **New → Background Worker**
3. Connect your repo
4. Configure:
   - **Name:** `telegram-cloner-bot`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
   - **Instance Type:** Free
5. Add Environment Variables:
   
   | Key | Value |
   |-----|-------|
   | `BOT_TOKEN` | Your bot token from @BotFather |
   | `DATABASE_URL` | Supabase connection string (`postgresql://...`) |
   | `SUPABASE_URL` | Supabase Project URL |
   | `SUPABASE_KEY` | Supabase anon public key |
   | `AUTO_FORWARD_INTERVAL` | `10` (seconds between checks) |
   | `LOG_LEVEL` | `INFO` |

6. Click **Create Background Worker**

### 3. Using the Bot

Send `/start` to your bot on Telegram:
1. **Setup** → Enter your API ID and Hash
2. **New Clone Job** → Follow the interactive prompts
3. Add the bot to both channels (Admin in destination)
4. Watch it clone!

## ⚙️ Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ | Telegram Bot Token |
| `DATABASE_URL` | ✅ | Supabase PostgreSQL connection string |
| `SUPABASE_URL` | ✅ | Supabase project URL |
| `SUPABASE_KEY` | ✅ | Supabase anon key |
| `AUTO_FORWARD_INTERVAL` | ❌ | Poll interval in seconds (default: 10) |
| `LOG_LEVEL` | ❌ | DEBUG, INFO, WARNING, ERROR (default: INFO) |

## 🏗 Commands

| Command | Description |
|---------|-------------|
| `/start` | Main interactive menu |
| `/setup` | Enter Telegram API ID + Hash |
| `/clone` | Create a new clone job |
| `/jobs` | View your clone jobs |
| `/forwards` | View auto-forward configs |
| `/delete_job <id>` | Remove a clone job |
| `/delete_forward <id>` | Remove an auto-forward |
| `/cancel` | Cancel current operation |
| `/help` | Detailed instructions |

## 🔐 Security
- API credentials stored encrypted in Supabase
- Pyrogram string sessions stored for persistent login
- Each user's account isolated
- No plain-text passwords
- Source code fully auditable