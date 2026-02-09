import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env reliably both locally and on server (regardless of current working directory)
BASE_DIR = Path(__file__).resolve().parents[2]  # .../giveaway_bot
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH if ENV_PATH.exists() else None)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# ADMIN_IDS=123,456 у .env
ADMIN_IDS = set(
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
)
