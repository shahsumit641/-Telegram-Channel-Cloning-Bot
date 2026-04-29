"""
Supabase + asyncpg database layer.
Uses Supabase PostgreSQL via connection pooling for 24/7 operation.
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

import asyncpg
from supabase import create_client, Client

from config import DATABASE_URL, SUPABASE_URL, SUPABASE_KEY

log = logging.getLogger("Database")

# Connection pool
_pool: Optional[asyncpg.Pool] = None
_supabase: Optional[Client] = None

# ── Initialization ─────────────────────────────────

async def init_db():
    """Initialize database connection pool and create tables."""
    global _pool, _supabase
    
    # Initialize Supabase REST client (for simple operations)
    if SUPABASE_URL and SUPABASE_KEY:
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        log.info("Supabase client initialized")
    
    # Initialize asyncpg connection pool for direct PostgreSQL access
    if not DATABASE_URL:
        log.error("❌ DATABASE_URL not set! Please configure it in Render environment.")
        raise ValueError("DATABASE_URL is required. Set it in your Render service environment variables.")
    
    log.info(f"Connecting to database: {DATABASE_URL[:50]}...")  # Log first 50 chars (safe)
    
    # Use prepared_statements=False for Supabase's PgBouncer transaction mode
    try:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=60,
            # Supabase PgBouncer transaction mode doesn't support prepared statements
            # We'll use raw SQL without prepared statements
        )
    except Exception as e:
        log.error(f"❌ Failed to connect to database: {e}")
        log.error("This usually means:")
        log.error("  1. DATABASE_URL is not set or is invalid")
        log.error("  2. Network cannot reach the database server")
        log.error("  3. Database credentials are incorrect")
        raise
    
    log.info("Database connection pool created")
    
    # Create tables
    async with _pool.acquire() as conn:
        # Users table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                api_id INTEGER NOT NULL,
                api_hash TEXT NOT NULL,
                string_session TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        
        # Clone jobs table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS clone_jobs (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                source_channel TEXT NOT NULL,
                dest_channel TEXT NOT NULL,
                direction TEXT DEFAULT 'oldest',
                delay REAL DEFAULT 1.0,
                only_media INTEGER DEFAULT 0,
                auto_forward INTEGER DEFAULT 0,
                last_cloned_msg_id INTEGER DEFAULT 0,
                total_cloned INTEGER DEFAULT 0,
                status TEXT DEFAULT 'idle',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        
        # Auto-forwards table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS auto_forwards (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                source_channel TEXT NOT NULL,
                dest_channel TEXT NOT NULL,
                active INTEGER DEFAULT 1,
                last_msg_id INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        
        # Indexes
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_clone_jobs_user_id ON clone_jobs(user_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_auto_forwards_active ON auto_forwards(active)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_auto_forwards_user_id ON auto_forwards(user_id)
        """)
    
    log.info("Database tables created/verified")

async def close_db():
    """Close the database connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        log.info("Database pool closed")

def get_pool() -> asyncpg.Pool:
    """Get the asyncpg connection pool."""
    if not _pool:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _pool

def get_supabase() -> Client:
    """Get the Supabase REST client."""
    if not _supabase:
        raise RuntimeError("Supabase client not initialized.")
    return _supabase

# ── Helper: execute raw SQL with params ────────────

async def _execute(sql: str, *args):
    """Execute a SQL query and return the result."""
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(sql, *args)

async def _fetch(sql: str, *args) -> List[Dict[str, Any]]:
    """Fetch rows as dictionaries."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Use JSON-style row factory
        rows = await conn.fetch(sql, *args)
        return [dict(row) for row in rows]

async def _fetchrow(sql: str, *args) -> Optional[Dict[str, Any]]:
    """Fetch a single row as dictionary."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *args)
        return dict(row) if row else None

async def _execute_with_returning(sql: str, *args) -> int:
    """Execute INSERT and return the id."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *args)
        return row["id"] if row else 0

# ── User operations ─────────────────────────────────

async def save_user(user_id: int, api_id: int, api_hash: str, string_session: str = None):
    """Register or update a user's API credentials."""
    now = datetime.utcnow()
    await _execute("""
        INSERT INTO users (user_id, api_id, api_hash, string_session, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $5)
        ON CONFLICT (user_id) DO UPDATE SET
            api_id = EXCLUDED.api_id,
            api_hash = EXCLUDED.api_hash,
            string_session = COALESCE(EXCLUDED.string_session, users.string_session),
            updated_at = EXCLUDED.updated_at
    """, user_id, api_id, api_hash, string_session, now)
    log.info(f"User {user_id} saved/updated")

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Get a user's credentials."""
    return await _fetchrow(
        "SELECT * FROM users WHERE user_id = $1", user_id
    )

async def update_string_session(user_id: int, string_session: str):
    """Update a user's Pyrogram string session."""
    now = datetime.utcnow()
    await _execute(
        "UPDATE users SET string_session = $1, updated_at = $2 WHERE user_id = $3",
        string_session, now, user_id
    )

async def delete_user(user_id: int):
    """Delete a user and all their data."""
    await _execute("DELETE FROM users WHERE user_id = $1", user_id)
    log.info(f"User {user_id} and all data deleted")

# ── Clone job operations ────────────────────────────

async def create_clone_job(
    user_id: int, source: str, dest: str,
    direction: str = "oldest", delay: float = 1.0,
    only_media: bool = False, auto_forward: bool = False
) -> int:
    """Create a new clone job. Returns the job ID."""
    job_id = await _execute_with_returning("""
        INSERT INTO clone_jobs 
        (user_id, source_channel, dest_channel, direction, delay, 
         only_media, auto_forward, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'idle')
        RETURNING id
    """, user_id, source, dest, direction, delay, 
        int(only_media), int(auto_forward))
    log.info(f"Clone job #{job_id} created for user {user_id}")
    return job_id

async def get_user_jobs(user_id: int) -> List[Dict[str, Any]]:
    """Get all clone jobs for a user."""
    return await _fetch(
        "SELECT * FROM clone_jobs WHERE user_id = $1 ORDER BY created_at DESC",
        user_id
    )

async def get_user_job(user_id: int, job_id: int) -> Optional[Dict[str, Any]]:
    """Get a specific clone job."""
    return await _fetchrow(
        "SELECT * FROM clone_jobs WHERE id = $1 AND user_id = $2",
        job_id, user_id
    )

async def update_job_state(
    job_id: int, last_msg_id: int = None,
    total_cloned: int = None, status: str = None
):
    """Update a job's clone state."""
    now = datetime.utcnow()
    
    set_parts = ["updated_at = $2"]
    values = [job_id, now]
    idx = 3
    
    if last_msg_id is not None:
        set_parts.append(f"last_cloned_msg_id = ${idx}")
        values.append(last_msg_id)
        idx += 1
    if total_cloned is not None:
        set_parts.append(f"total_cloned = ${idx}")
        values.append(total_cloned)
        idx += 1
    if status is not None:
        set_parts.append(f"status = ${idx}")
        values.append(status)
    
    set_clause = ", ".join(set_parts)
    await _execute(
        f"UPDATE clone_jobs SET {set_clause} WHERE id = $1",
        *values
    )

async def delete_job(job_id: int, user_id: int):
    """Delete a clone job."""
    await _execute(
        "DELETE FROM clone_jobs WHERE id = $1 AND user_id = $2",
        job_id, user_id
    )
    log.info(f"Job #{job_id} deleted for user {user_id}")

# ── Auto-forward operations ─────────────────────────

async def create_auto_forward(user_id: int, source: str, dest: str):
    """Register an auto-forward listener."""
    await _execute("""
        INSERT INTO auto_forwards (user_id, source_channel, dest_channel)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id, source_channel, dest_channel) 
        DO UPDATE SET active = 1, last_msg_id = 0
    """, user_id, source, dest)
    log.info(f"Auto-forward created for user {user_id}: {source} → {dest}")

async def get_active_auto_forwards() -> List[Dict[str, Any]]:
    """Get all active auto-forward configurations."""
    return await _fetch(
        "SELECT * FROM auto_forwards WHERE active = 1"
    )

async def update_auto_forward_last_msg(auto_fwd_id: int, msg_id: int):
    """Update the last seen message ID for an auto-forward."""
    await _execute(
        "UPDATE auto_forwards SET last_msg_id = $1 WHERE id = $2",
        msg_id, auto_fwd_id
    )

async def get_user_auto_forwards(user_id: int) -> List[Dict[str, Any]]:
    """Get all auto-forwards for a user."""
    return await _fetch(
        "SELECT * FROM auto_forwards WHERE user_id = $1",
        user_id
    )

async def delete_auto_forward(auto_fwd_id: int, user_id: int):
    """Delete an auto-forward configuration."""
    await _execute(
        "DELETE FROM auto_forwards WHERE id = $1 AND user_id = $2",
        auto_fwd_id, user_id
    )
    log.info(f"Auto-forward #{auto_fwd_id} deleted")

async def get_auto_forward(auto_fwd_id: int) -> Optional[Dict[str, Any]]:
    """Get a specific auto-forward config."""
    return await _fetchrow(
        "SELECT * FROM auto_forwards WHERE id = $1",
        auto_fwd_id
    )
