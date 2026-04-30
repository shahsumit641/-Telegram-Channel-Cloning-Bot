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

# Ensure unbuffered output for Render
sys.stdout.reconfigure(line_buffering=False) if hasattr(sys.stdout, 'reconfigure') else None
sys.stderr.reconfigure(line_buffering=False) if hasattr(sys.stderr, 'reconfigure') else None

# Setup basic logging immediately
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True
)

print("🔧 Bot initializing...", flush=True)

try:
    from telegram.ext import ApplicationBuilder
    from config import BOT_TOKEN, LOG_LEVEL, AUTO_FORWARD_INTERVAL
    from database import init_db, close_db
    from user_client import shutdown_all
    from clone_engine import AutoForwardEngine
    from handlers import register_handlers
    print("✓ All modules imported successfully", flush=True)
except Exception as e:
    print(f"❌ Failed to import modules: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

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
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        return  # suppress logs

def run_health_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

# ── Startup ─────────────────────────────────────────────

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    log.info("Health check server thread started")

    log.info("=" * 50)
    log.info("Telegram Channel Cloner Bot starting up...")
    log.info("=" * 50)

    if not BOT_TOKEN:
        log.error("❌ BOT_TOKEN not set!")
        sys.exit(1)

    # DB (fixed)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())

    auto_engine = AutoForwardEngine(check_interval=AUTO_FORWARD_INTERVAL)

    async def post_init(application):
        await auto_engine.start()

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    register_handlers(app)

    try:
        app.run_polling()
    finally:
        asyncio.run(auto_engine.stop())
        asyncio.run(shutdown_all())
        asyncio.run(close_db())


# ── Entry Point ─────────────────────────────────────────

if __name__ == "__main__":
    print("🚀 Starting bot entry point...", flush=True)
    main()
