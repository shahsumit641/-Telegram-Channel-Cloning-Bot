"""
Manages per-user Pyrogram clients using string sessions stored in Supabase.
Each user gets their own in-memory client.
"""

from __future__ import annotations
import logging
from database import get_user, update_string_session

log = logging.getLogger("UserClient")

# Pool of active Pyrogram clients: {user_id: Client}
_active_clients = {}

async def get_user_client(user_id: int):
    from pyrogram import Client

    if user_id in _active_clients:
        client = _active_clients[user_id]
        try:
            await client.get_me()
            return client
        except Exception:
            del _active_clients[user_id]
            log.info(f"User {user_id} session expired, reconnecting...")

    user_data = await get_user(user_id)
    if not user_data:
        raise ValueError(
            f"User {user_id} has not registered API credentials. Use /setup first."
        )

    api_id = user_data["api_id"]
    api_hash = user_data["api_hash"]
    string_session = user_data.get("string_session")

    if not string_session:
        raise ValueError(
            "Session not found. You must complete login (phone + OTP) first."
        )

    # ✅ FINAL CORRECT CLIENT
    client = Client(
        name=f"user_{user_id}",
        api_id=api_id,
        api_hash=api_hash,
        session_string=string_session,
        no_updates=True  # ⚠️ important for background worker stability
    )

    await client.start()

    log.info(f"User {user_id}: connected using saved session")

    _active_clients[user_id] = client
    return client

async def remove_user_client(user_id: int):
    """Stop and remove a user's Pyrogram client."""
    if user_id in _active_clients:
        try:
            await _active_clients[user_id].stop()
        except Exception:
            pass
        del _active_clients[user_id]
        log.info(f"User {user_id} client removed")

async def shutdown_all():
    """Shutdown all active Pyrogram clients."""
    for user_id in list(_active_clients.keys()):
        await remove_user_client(user_id)
    log.info("All user clients shut down")
