"""
Core cloning engine.
Handles historical clone and auto-forward with no 'Forwarded from' tag.
"""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from pyrogram import Client

from database import (
    update_job_state, get_user_job, create_auto_forward,
    update_auto_forward_last_msg, get_active_auto_forwards,
    get_user, get_auto_forward
)
from user_client import get_user_client

log = logging.getLogger("CloneEngine")


async def resolve_chat(client, chat_input):
    """
    Resolve chat from:
    - @username
    - -100chat_id (private/public)
    """

    # 1. Try direct resolution (works for usernames)
    try:
        return await client.get_chat(chat_input)
    except Exception:
        pass

    # 2. Fallback: scan dialogs (required for private IDs)
    async for dialog in client.get_dialogs():
        if str(dialog.chat.id) == str(chat_input):
            return dialog.chat

    raise ValueError(f"Cannot resolve chat: {chat_input}")

# ── Rate-limited copy helpers ───────────────────────────

async def _safe_copy(client: Client, from_chat, to_chat, msg_id, dest_thread_id=None, retries=3):
    from pyrogram.errors import FloodWait, ChatWriteForbidden, ChannelPrivate, PeerIdInvalid
    
    for attempt in range(retries):
        try:
            kwargs = {}
            if dest_thread_id:
                kwargs["message_thread_id"] = dest_thread_id

            return await client.copy_message(
                chat_id=to_chat,
                from_chat_id=from_chat,
                message_id=msg_id,
                **kwargs
            )

        except FloodWait as e:
            await asyncio.sleep(e.value + 1)

        except ChatWriteForbidden:
            log.error(f"Cannot write to {to_chat}")
            return None

        except (ChannelPrivate, PeerIdInvalid) as e:
            log.error(f"Channel error: {e}")
            return None

        except Exception as e:
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                log.error(f"Copy failed {msg_id}: {e}")
                return None

async def _safe_copy_media_group(client: Client, from_chat, to_chat, msg_id, dest_thread_id=None, retries=3):
    from pyrogram.errors import FloodWait, ChatWriteForbidden, ChannelPrivate, PeerIdInvalid
    
    for attempt in range(retries):
        try:
            kwargs = {}
            if dest_thread_id:
                kwargs["message_thread_id"] = dest_thread_id

            return await client.copy_media_group(
                chat_id=to_chat,
                from_chat_id=from_chat,
                message_id=msg_id,
                **kwargs
            )

        except FloodWait as e:
            await asyncio.sleep(e.value + 1)

        except ChatWriteForbidden:
            log.error(f"Cannot write to {to_chat}")
            return None

        except (ChannelPrivate, PeerIdInvalid) as e:
            log.error(f"Channel error: {e}")
            return None

        except Exception as e:
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                log.error(f"Media group failed {msg_id}: {e}")
                return None

# ── Historical Clone ────────────────────────────────────

async def run_historical_clone(
    user_id: int, job_id: int,
    on_progress=None, on_complete=None
):
    """
    Clone all historical messages from source to destination.
    Runs in the background as an asyncio task.
    
    Callback signatures:
      on_progress(user_id, job_id, current, total, percent)
      on_complete(user_id, job_id, total_cloned, error_message)
    """
    from pyrogram.errors import FloodWait, ChatWriteForbidden, ChannelPrivate, PeerIdInvalid
    
    log.info(f"[User {user_id}] Starting historical clone job #{job_id}")
    
    # Get the Pyrogram client for this user
    try:
        client = await get_user_client(user_id)
    except ValueError as e:
        log.error(f"[User {user_id}] {e}")
        if on_complete:
            await on_complete(user_id, job_id, 0, str(e))
        return
    
    # Get job details from database
    job = await get_user_job(user_id, job_id)
    if not job:
        log.error(f"[User {user_id}] Job #{job_id} not found in database")
        if on_complete:
            await on_complete(user_id, job_id, 0, "Job not found")
        return
    
    source = job["source_channel"]
    dest = job["dest_channel"]
    source_thread_id = job.get("source_thread_id")
    dest_thread_id = job.get("dest_thread_id")
    direction = job["direction"]
    delay = job["delay"]
    only_media = bool(job["only_media"])
    last_cloned = job["last_cloned_msg_id"]
    total_cloned = job["total_cloned"]
    
    # Resolve channels
    # Resolve channels (supports username + private ID)
    try:
        # 🔥 load dialogs FIRST (IMPORTANT)
        async for _ in client.get_dialogs(limit=50):
            break
        
        # 🔥 resolve
        source_chat = await resolve_chat(client, source)
        dest_chat = await resolve_chat(client, dest)
        
        # 🔥 convert to usable ID
        source = source_chat.id
        dest = dest_chat.id

        label = f"{source_chat.title or source} → {dest_chat.title or dest}"
    except ChannelPrivate:
        msg = f"Source channel '{source}' is private or bot cannot access it"
        log.error(f"[User {user_id}] {msg}")
        await update_job_state(job_id, status="failed")
        if on_complete:
            await on_complete(user_id, job_id, 0, msg)
        return
    except PeerIdInvalid:
        msg = f"Cannot find channel '{source}'. Check the username/ID."
        log.error(f"[User {user_id}] {msg}")
        await update_job_state(job_id, status="failed")
        if on_complete:
            await on_complete(user_id, job_id, 0, msg)
        return
    except Exception as e:
        msg = f"Error accessing channels: {e}"
        log.error(f"[User {user_id}] {msg}")
        await update_job_state(job_id, status="failed")
        if on_complete:
            await on_complete(user_id, job_id, 0, msg)
        return    
    
    await update_job_state(job_id, status="running")
    
    # Get message range
    try:
        first_msg = await client.get_messages(source, 1)

        latest_msg = None
        async for m in client.get_chat_history(source, limit=1):
            latest_msg = m
            break

        first_id = first_msg.id if first_msg else 1
        latest_id = latest_msg.id if latest_msg else 0
        
        if latest_id == 0:
            log.info(f"[User {user_id}] {label} — channel appears empty")
            await update_job_state(job_id, status="complete", total_cloned=0)
            if on_complete:
                await on_complete(user_id, job_id, 0)
            return
    except Exception as e:
        log.error(f"[User {user_id}] Range fetch failed: {e}")
        await update_job_state(job_id, status="failed")
        if on_complete:
            await on_complete(user_id, job_id, total_cloned, str(e))
        return
    
    log.info(f"[User {user_id}] {label}: range {first_id} → {latest_id}, resuming from {last_cloned}")
    
    processed = 0
    seen_media_groups = set()
    
    if direction == "oldest":
        current_id = last_cloned + 1 if last_cloned > 0 else first_id
        
        while current_id <= latest_id:

            job = await get_user_job(user_id, job_id)
            if not job or job.get("status") in ["deleted", "failed", "complete"]:
                log.info(f"Job {job_id} stopped")
                return
            batch_end = min(current_id + 99, latest_id)
            msg_ids = list(range(current_id, batch_end + 1))
            
            try:
                messages = await client.get_messages(source, msg_ids)
            except FloodWait as e:
                await asyncio.sleep(e.value + 2)
                continue
            except Exception as e:
                log.error(f"[User {user_id}] Batch fetch error: {e}")
                current_id = batch_end + 1
                continue
            
            for msg in messages:
                if not msg or msg.empty:
                    continue
                
                if getattr(msg, "service", False):
                    continue
                
                # 🔥 TOPIC FILTER
                if source_thread_id:
                    msg_thread = getattr(msg, "message_thread_id", None)

                    if msg_thread is not None and msg_thread != source_thread_id:
                        continue

                
                if only_media and not msg.media and not msg.media_group_id:
                    continue
                
                try:
                    if msg.media_group_id:
                        if msg.media_group_id in seen_media_groups:
                            continue
                        seen_media_groups.add(msg.media_group_id)
                        await _safe_copy_media_group(client, source, dest, msg.id, dest_thread_id)
                    else:
                        await _safe_copy(client, source, dest, msg.id, dest_thread_id)
                    
                    processed += 1
                    
                    # Save state periodically
                    if processed % 10 == 0:
                        await update_job_state(
                            job_id,
                            last_msg_id=msg.id,
                            total_cloned=total_cloned + processed
                        )
                    
                    if on_progress and processed % 50 == 0:
                        total_msgs = latest_id - first_id
                        pct = (msg.id - first_id) / total_msgs * 100 if total_msgs > 0 else 0
                        await on_progress(user_id, job_id, total_cloned + processed, total_msgs, pct)
                    
                    await asyncio.sleep(delay)
                    
                except Exception as e:
                    log.error(f"[User {user_id}] Error processing msg {msg.id}: {e}")
                    continue
            
            current_id = batch_end + 1
    
    else:  # newest direction
        offset_id = 0
        while True:
            try:
                batch_count = 0
                async for msg in client.get_chat_history(source, limit=100, offset_id=offset_id):

                    if not msg or msg.empty:
                        continue
                    
                    if getattr(msg, "service", False):
                        continue

                    if source_thread_id:
                        msg_thread = getattr(msg, "message_thread_id", None)

                        # STRICT filtering ONLY when thread exists
                        if msg_thread is not None:
                            if msg_thread != source_thread_id:
                                continue

                    # 🔥 ADD HERE
                    job = await get_user_job(user_id, job_id)
                    if not job or job.get("status") == "deleted":
                        log.info(f"Job {job_id} stopped")
                        return
                    if msg.id <= last_cloned:
                        log.info(f"[User {user_id}] Reached already-cloned msg {msg.id}, stopping")
                        return
                    
                    if only_media and not msg.media and not msg.media_group_id:
                        continue
                    
                    try:
                        if msg.media_group_id:
                            if msg.media_group_id in seen_media_groups:
                                continue
                            seen_media_groups.add(msg.media_group_id)
                            await _safe_copy_media_group(client, source, dest, msg.id, dest_thread_id)
                        else:
                            await _safe_copy(client, source, dest, msg.id, dest_thread_id)
                        
                        processed += 1
                        batch_count += 1
                        
                        if processed % 10 == 0:
                            await update_job_state(
                                job_id,
                                last_msg_id=msg.id,
                                total_cloned=total_cloned + processed
                            )
                        
                        await asyncio.sleep(delay)
                        offset_id = msg.id
                        
                    except Exception as e:
                        log.error(f"[User {user_id}] Error processing msg {msg.id}: {e}")
                        continue
                
                if batch_count == 0:
                    break  # No more messages
                    
            except FloodWait as e:
                await asyncio.sleep(e.value + 2)
            except Exception as e:
                log.error(f"[User {user_id}] History fetch error: {e}")
                break
    
    # Mark complete
    final_total = total_cloned + processed
    await update_job_state(job_id, status="complete", total_cloned=final_total)
    log.info(f"[User {user_id}] {label} — COMPLETE: {final_total} messages cloned")
    
    # If auto-forward was requested, register it
    if job["auto_forward"]:
        await create_auto_forward(
            user_id,
            source,
            dest,
            source_thread_id=source_thread_id,
            dest_thread_id=dest_thread_id
        )
        log.info(f"[User {user_id}] Auto-forward enabled: {source} → {dest}")
    
    if on_complete:
        await on_complete(user_id, job_id, final_total, None)

# ── Auto-Forward Engine ─────────────────────────────────

class AutoForwardEngine:
    """
    Background polling engine that checks all active auto-forward
    configurations for new messages and copies them.
    """
    
    def __init__(self, check_interval: int = 10):
        self.check_interval = check_interval
        self._running = False
        self._task = None
    
    async def start(self):
        """Start the auto-forward polling loop."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        log.info(f"Auto-forward engine started (check interval: {self.check_interval}s)")
    
    async def stop(self):
        """Stop the auto-forward polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Auto-forward engine stopped")
    
    async def _poll_loop(self):
        """Main polling loop — runs forever."""
        while self._running:
            try:
                await self._check_all()
            except Exception as e:
                log.error(f"Auto-forward poll error: {e}", exc_info=True)
            await asyncio.sleep(max(self.check_interval, 3))
    
    async def _check_all(self):
        """Check all active auto-forward configs for new messages."""
        try:
            configs = await get_active_auto_forwards()
        except Exception as e:
            log.error(f"Failed to fetch auto-forwards from database: {e}")
            return
        
        for cfg in configs:
            try:
                try:
                    await self._check_single(cfg)
                except Exception as e:
                    log.error(f"Auto-forward crash protected: {e}")
            except Exception as e:
                log.error(f"Auto-forward check failed for config #{cfg['id']}: {e}")
    
    async def _check_single(self, cfg: dict):
        """Check a single auto-forward config for new messages."""
        from pyrogram.errors import ChatWriteForbidden, ChannelPrivate
        from pyrogram.types import Message

        user_id = cfg["user_id"]
        source = cfg["source_channel"]
        dest = cfg["dest_channel"]
        last_msg_id = cfg["last_msg_id"]
        af_id = cfg["id"]
        source_thread_id = cfg.get("source_thread_id")
        dest_thread_id = cfg.get("dest_thread_id")

        # Get the user's Pyrogram client
        try:
            client = await get_user_client(user_id)
        except ValueError:
            log.debug(f"Auto-forward #{af_id}: user {user_id} not ready, skipping")
            return
        except Exception as e:
            log.error(f"Auto-forward #{af_id}: failed to get client: {e}")
            return

        try:
            # 🔥 CRITICAL FIX: resolve chats (works for private channels + IDs)
            async for _ in client.get_dialogs(limit=50):
                break

            source_chat = await resolve_chat(client, source)
            dest_chat = await resolve_chat(client, dest)

            source = source_chat.id
            dest = dest_chat.id

            # 🔍 Get latest message
            latest = None
            async for m in client.get_chat_history(source, limit=1):
                latest = m
                break
            
            if latest is None or latest.empty:
                return

            # 🚀 New messages found
            if latest.id > last_msg_id:
                log.info(
                    f"Auto-forward #{af_id}: new messages ({last_msg_id+1} → {latest.id})"
                )

                current = last_msg_id + 1

                while current <= latest.id:
                    batch_end = min(current + 50, latest.id)
                    msg_ids = list(range(current, batch_end + 1))

                    try:
                        messages = await client.get_messages(source, msg_ids)
                    except Exception:
                        current = batch_end + 1
                        continue

                    seen_media = set()

                    for msg in messages:
                        if not msg or msg.empty:
                            continue
                        
                        if getattr(msg, "service", False):
                            continue
                        
                        # 🔥 TOPIC FILTER
                        if source_thread_id:
                            msg_thread = getattr(msg, "message_thread_id", None)

                            if msg_thread is not None and msg_thread != source_thread_id:
                                continue
                                

                        try:
                            if msg.media_group_id:
                                if msg.media_group_id in seen_media:
                                    continue
                                seen_media.add(msg.media_group_id)

                                await _safe_copy_media_group(client, source, dest, msg.id, dest_thread_id)
                            else:
                                await _safe_copy(client, source, dest, msg.id, dest_thread_id)

                        except ChatWriteForbidden:
                            log.error(
                                f"Auto-forward #{af_id}: bot cannot write to destination {dest}"
                            )
                            return

                        except Exception as e:
                            log.error(
                                f"Auto-forward #{af_id}: copy error msg {msg.id}: {e}"
                            )
                            continue

                    # ✅ update only after successful batch
                    if batch_end > last_msg_id:
                        await update_auto_forward_last_msg(af_id, batch_end)
                        last_msg_id = batch_end
                    current = batch_end + 1

                    await asyncio.sleep(1)

        except ChannelPrivate:
            log.warning(
                f"Auto-forward #{af_id}: source '{source}' not accessible (left or banned)"
            )

        except Exception as e:
            log.error(f"Auto-forward #{af_id}: check error: {e}")
