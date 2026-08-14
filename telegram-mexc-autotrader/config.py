"""
Configuration module for telegram-mexc-autotrader.
Loads environment variables and defines constants.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory
BASE_DIR = Path(__file__).parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

# Telegram API credentials
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
PHONE = os.getenv("PHONE", "")
CHANNEL = os.getenv("CHANNEL", "")

# MEXC API credentials
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_SECRET = os.getenv("MEXC_SECRET", "")

# Trading settings from .env
TARGETS_TIMEOUT_SEC = int(os.getenv("TARGETS_TIMEOUT_SEC", "120"))
DEFAULT_STOP_PCT = float(os.getenv("DEFAULT_STOP_PCT", "0"))
POLL_SEC = int(os.getenv("POLL_SEC", "2"))
CATCH_UP_ON_START = os.getenv("CATCH_UP_ON_START", "false").lower() == "true"

# Fixed leverage (always x25)
LEVERAGE = 25

# TP split ratios (50%, 25%, 25%)
TP_SPLIT = (0.50, 0.25, 0.25)

# MEXC API base URL
MEXC_BASE_URL = "https://contract.mexc.com"

# Session and state files
SESSION_FILE = BASE_DIR / "mexc_trader.session"
STATE_FILE = BASE_DIR / "state.json"
SETTINGS_FILE = BASE_DIR / "settings.json"
LOG_FILE = BASE_DIR / "logs" / "trader.log"
