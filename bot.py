#!/usr/bin/env python3
"""
Multi-User Telegram Channel Cloner Bot
Main entry point for Render.com background worker.
"""

import os
import sys
import logging
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram.ext import ApplicationBuilder

from config import BOT_TOKEN, LOG_LEVEL, AUTO_FORWARD_INTERVAL
from database import init_db, close_db
from user_client import shutdown_all
from clone_engine import AutoForwardEngine
from handlers import register_handlers

# ── Logging Setup ───────────────────────────────────────

log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format=log_format,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("Bot")

# ── Health check server (so Render knows it's alive) ──
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    
    def log_message(self, format, *args):
        return  # Suppress HTTP log noise

def run_health_server():
    # Bind to PORT env var (set by Render) or default to 10000
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    log.info(f"Health server running on port {port}")
    server.serve_forever()

# ── Startup ─────────────────────────────────────────────

async def main():
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    log.info("=" * 50)
    log.info("Telegram Channel Cloner Bot starting up...")
    log.info("=" * 50)
    
    # Validate required environment variables
    if not BOT_TOKEN:
        log.error("❌ BOT_TOKEN not set! Please configure it in Render environment.")
        sys.exit(1)

    # ── Start health check server in a background thread ──
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    log.info("Health check server thread started")

    # 1. Initialize database
    try:
        await init_db()
    except Exception as e:
        log.error(f"❌ Database initialization failed: {e}")
        sys.exit(1)

    # 2. Build bot
    try:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
    except Exception as e:
        log.error(f"❌ Failed to build bot application: {e}")
        sys.exit(1)
    
    # 3. Register handlers
    try:
        register_handlers(app)
    except Exception as e:
        log.error(f"❌ Failed to register handlers: {e}")
        sys.exit(1)
    
    # 4. Start auto-forward engine
    try:
        auto_engine = AutoForwardEngine(check_interval=AUTO_FORWARD_INTERVAL)
        await auto_engine.start()
    except Exception as e:
        log.error(f"❌ Failed to start auto-forward engine: {e}")
        sys.exit(1)
    
    # 5. Start bot
    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
    except Exception as e:
        log.error(f"❌ Failed to start bot: {e}")
        sys.exit(1)
    
    log.info("✅ Bot is LIVE! (Render will not sleep — UptimeRobot pings every 5 min)")
    
    try:
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await auto_engine.stop()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await shutdown_all()
        await close_db()

# ── Entry Point ─────────────────────────────────────────

if __name__ == "__main__":
    # Create event loop for Python 3.10+ compatibility with Pyrogram
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        log.info("Exiting...")
    except RuntimeError as e:
        log.error(f"Runtime error: {e}")
        sys.exit(1)
    finally:
        loop.close()
