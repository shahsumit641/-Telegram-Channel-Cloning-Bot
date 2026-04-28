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
    server = HTTPServer(("0.0.0.0", 10000), HealthHandler)
    log.info("Health server running on port 10000")
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

    # ── Start health check server in a background thread ──
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    log.info("Health check server thread started")

    # 1. Initialize database
    await init_db()

    # 2. Build bot
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # 3. Register handlers
    register_handlers(app)
    
    # 4. Start auto-forward engine
    auto_engine = AutoForwardEngine(check_interval=AUTO_FORWARD_INTERVAL)
    await auto_engine.start()
    
    # 5. Start bot
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
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
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Exiting...")
    except RuntimeError as e:
        log.error(f"Runtime error: {e}")
        sys.exit(1)
