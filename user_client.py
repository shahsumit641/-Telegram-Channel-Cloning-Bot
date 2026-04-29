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

async def get_user_client(user_id: int) -> Client:
    """Get or create a Pyrogram client for a user."""
    from pyrogram import Client
    
    if user_id in _active_clients:
        client = _active_clients[user_id]
        try:
            me = await client.get_me()
            if me:
                return client
        except Exception:
            # Session expired, remove and recreate
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
    
    session_name = f"user_{user_id}"
    
    if string_session:
        client = Client(
            session_name,
            api_id=api_id,
            api_hash=api_hash,
            session_string=string_session,
            in_memory=True
        )
        log.info(f"User {user_id}: restoring from saved string session")
    else:
        client = Client(
            session_name,
            api_id=api_id,
            api_hash=api_hash,
            in_memory=True
        )
        log.info(f"User {user_id}: first-time session creation")
    
    await client.start()
    
    # Save string session on first login
    if not string_session:
        try:
            new_session = await client.export_session_string()
            await update_string_session(user_id, new_session)
            log.info(f"User {user_id}: string session saved to database")
        except Exception as e:
            log.warning(f"User {user_id}: could not export session string: {e}")
    
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
