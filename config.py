import os
from dotenv import load_dotenv

load_dotenv()

# Required
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Optional
AUTO_FORWARD_INTERVAL = int(os.getenv("AUTO_FORWARD_INTERVAL", "10"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
