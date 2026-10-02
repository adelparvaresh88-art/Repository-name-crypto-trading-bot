import os
import time
import hmac
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.40
# AL BROOKS PRICE ACTION - FINAL
# ============================================================
#
# FINAL LOGIC:
#
# Trend
#   ↓
# REAL BOS
#   ↓
# Pullback
#   ↓
# Continuation
#   ↓
# CLOSED 5M CONFIRMATION
#   ↓
# BUY READY
#
# Signal Bar is still used as an extra confirmation,
# but EARLY no longer waits for a perfect Signal Bar.
#
# NO EMA
# NO RSI
# NO MACD
# NO OPEN-CANDLE SIGNAL
#
# REAL ORDERS DISABLED
# BUY LOCK ACTIVE
#
# ============================================================

VERSION = "V40.2.40"

BASE_URL = "https://api1.tabdeal.org"

REAL_ORDERS = False
BUY_LOCK = True

SCAN_UNIVERSE = 40
TOP_RESULTS = 10

TRADE_LIMIT = 1000
MIN_CANDLES = 30

REQUEST_TIMEOUT = 12
MAX_WORKERS = 8

TREND_LOOKBACK = 12
RESISTANCE_LOOKBACK = 12
PULLBACK_LOOKBACK = 5

# ============================================================
# BREAKOUT
# ============================================================

REAL_BOS_MIN = 0.05

NEAR_BOS_MIN = -0.25

PULLBACK_TOLERANCE = 0.80

CHASE_LIMIT = 2.20

# ============================================================
# FINAL CLOSED-CANDLE CONFIRMATION
# ============================================================
#
# This is intentionally lighter than a perfect Signal Bar.
#
# It requires:
# - closed candle
# - positive 5m movement
# - close above previous close
# - reasonable close position
#
# This prevents waiting too long for a textbook signal bar.
# ============================================================

MIN_CONFIRM_CLOSE_POSITION = 0.55

TELEGRAM_TIMEOUT = 15


# ============================================================
# ENV
# ============================================================

API_KEY = (
    os.getenv("TABDIL_API_KEY", "").strip()
    or os.getenv("TABDEAL_API_KEY", "").strip()
)

API_SECRET = (
    os.getenv("TABDIL_API_SECRET", "").strip()
    or os.getenv("TABDEAL_API_SECRET", "").strip()
)

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": f"ATI-Crypto-Bot-{VERSION}",
    "Accept": "application/json",
})


# ============================================================
# BASIC HELPERS
# ============================================================

def now_utc():
    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def pct(a, b):
    if not b:
        return 0.0

    return ((a - b) / b) * 100.0
