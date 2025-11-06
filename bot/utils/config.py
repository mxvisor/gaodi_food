# config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in environment variables")

WEBAPP_URL = os.getenv("WEBAPP_URL")
# WEBAPP_URL is optional; when missing, UI should work without WebApp button

BOT_OWNER_RAW = os.getenv("BOT_OWNER")
if not BOT_OWNER_RAW or not BOT_OWNER_RAW.strip():
    raise ValueError("BOT_OWNER is not set in environment variables")

# Parse BOT_OWNER: support single ID or comma-separated list of IDs
parts = [p.strip() for p in BOT_OWNER_RAW.split(',')]
owners: list[int] = []
for p in parts:
    if not p:
        continue
    try:
        owners.append(int(p))
    except ValueError:
        raise ValueError(f"BOT_OWNER contains non-integer value: '{p}'")

if not owners:
    raise ValueError("BOT_OWNER must contain at least one integer user id")

# If single value, keep int; else keep list[int]
BOT_OWNER = owners[0] if len(owners) == 1 else owners

# Optional: warn if recommended variables are missing (BOT_OWNER is required above)
if not WEBAPP_URL:
    print("Warning: WEBAPP_URL is not set. WebApp button will be hidden.")
