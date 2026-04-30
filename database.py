"""
Supabase + asyncpg database layer.
Uses Supabase PostgreSQL via connection pooling for 24/7 operation.
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from supabase import create_client, Client

from config import  SUPABASE_URL, SUPABASE_KEY

log = logging.getLogger("Database")

# Connection pool
_supabase: Optional[Client] = None

# ── Initialization ─────────────────────────────────

async def init_db():
    """Initialize Supabase client."""
    global _supabase

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY are required")

    _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    log.info("✅ Supabase REST client initialized")

async def close_db():
    """No-op for Supabase REST."""
    log.info("Supabase REST client closed (no action needed)")

def get_supabase() -> Client:
    if not _supabase:
        raise RuntimeError("Supabase client not initialized.")
    return _supabase


# ── User operations ─────────────────────────────────

async def save_user(user_id: int, api_id: int, api_hash: str, string_session: str = None):
    supabase = get_supabase()

    data = {
        "user_id": user_id,
        "api_id": api_id,
        "api_hash": api_hash,
        "string_session": string_session
    }

    supabase.table("users").upsert(data).execute()
    log.info(f"User {user_id} saved/updated")

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    supabase = get_supabase()

    res = supabase.table("users").select("*").eq("user_id", user_id).execute()
    return res.data[0] if res.data else None

async def update_string_session(user_id: int, string_session: str):
    supabase = get_supabase()

    supabase.table("users").update({
        "string_session": string_session
    }).eq("user_id", user_id).execute()

async def delete_user(user_id: int):
    supabase = get_supabase()

    supabase.table("users").delete().eq("user_id", user_id).execute()
    log.info(f"User {user_id} deleted")

# ── Clone job operations ────────────────────────────

async def create_clone_job(
    user_id: int,
    source: str,
    dest: str,
    direction: str = "oldest",
    delay: float = 1.0,
    only_media: bool = False,
    auto_forward: bool = False,
    source_thread_id: int = None,
    dest_thread_id: int = None
) -> int:
    supabase = get_supabase()

    data = {
        "user_id": user_id,
        "source_channel": source,
        "dest_channel": dest,
        "direction": direction,
        "delay": delay,
        "only_media": int(only_media),
        "auto_forward": int(auto_forward),
        "status": "idle",
        "source_thread_id": source_thread_id,
        "dest_thread_id": dest_thread_id
    }

    res = supabase.table("clone_jobs").insert(data).execute()

    job_id = res.data[0]["id"]
    log.info(f"Clone job #{job_id} created")
    return job_id

async def get_user_jobs(user_id: int) -> List[Dict[str, Any]]:
    supabase = get_supabase()

    res = supabase.table("clone_jobs") \
        .select("*") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .execute()

    return res.data

async def get_user_job(user_id: int, job_id: int) -> Optional[Dict[str, Any]]:
    supabase = get_supabase()

    res = supabase.table("clone_jobs") \
        .select("*") \
        .eq("id", job_id) \
        .eq("user_id", user_id) \
        .execute()

    return res.data[0] if res.data else None

async def update_job_state(
    job_id: int, last_msg_id: int = None,
    total_cloned: int = None, status: str = None
):
    supabase = get_supabase()

    update_data = {}

    if last_msg_id is not None:
        update_data["last_cloned_msg_id"] = last_msg_id
    if total_cloned is not None:
        update_data["total_cloned"] = total_cloned
    if status is not None:
        update_data["status"] = status

    supabase.table("clone_jobs").update(update_data).eq("id", job_id).execute()

async def delete_job(job_id: int, user_id: int):
    supabase = get_supabase()

    supabase.table("clone_jobs") \
        .delete() \
        .eq("id", job_id) \
        .eq("user_id", user_id) \
        .execute()

    log.info(f"Job #{job_id} deleted")

# ── Auto-forward operations ─────────────────────────

async def create_auto_forward(
    user_id: int,
    source: str,
    dest: str,
    source_thread_id: int = None,
    dest_thread_id: int = None
):
    supabase = get_supabase()

    supabase.table("auto_forwards").upsert({
        "user_id": user_id,
        "source_channel": source,
        "dest_channel": dest,
        "source_thread_id": source_thread_id,
        "dest_thread_id": dest_thread_id,
        "active": 1,
        "last_msg_id": 0
    }).execute()

async def get_active_auto_forwards() -> List[Dict[str, Any]]:
    supabase = get_supabase()

    res = supabase.table("auto_forwards") \
        .select("*") \
        .eq("active", 1) \
        .execute()

    return res.data

async def update_auto_forward_last_msg(auto_fwd_id: int, msg_id: int):
    supabase = get_supabase()

    supabase.table("auto_forwards") \
        .update({"last_msg_id": msg_id}) \
        .eq("id", auto_fwd_id) \
        .execute()

async def get_user_auto_forwards(user_id: int) -> List[Dict[str, Any]]:
    supabase = get_supabase()

    res = supabase.table("auto_forwards") \
        .select("*") \
        .eq("user_id", user_id) \
        .execute()

    return res.data

async def delete_auto_forward(auto_fwd_id: int, user_id: int):
    supabase = get_supabase()

    supabase.table("auto_forwards") \
        .delete() \
        .eq("id", auto_fwd_id) \
        .eq("user_id", user_id) \
        .execute()

async def get_auto_forward(auto_fwd_id: int) -> Optional[Dict[str, Any]]:
    supabase = get_supabase()

    res = supabase.table("auto_forwards") \
        .select("*") \
        .eq("id", auto_fwd_id) \
        .execute()

    return res.data[0] if res.data else None
