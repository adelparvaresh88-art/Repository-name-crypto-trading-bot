import os
import time
import json
import base64
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V39.4
# CLEAN EARLY ENTRY + CONFIRMED BREAKOUT
# + PAPER TRADE RESULT TRACKER
# ============================================================

VERSION = "V39.4"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 180
MAX_MARKETS = 1000

REQUEST_TIMEOUT = 10
MAX_WORKERS = 20

TOP_CONFIRMED = 3
TOP_EARLY = 4
TOP_WATCH = 5

# ============================================================
# SCORE
# ============================================================

CONFIRMED_MIN_SCORE = 12
EARLY_MIN_SCORE = 10
WATCH_MIN_SCORE = 10

# ============================================================
# EARLY
# ============================================================

EARLY_MIN_VOLUME = 0.80
EARLY_MAX_VOLUME = 6.00
EARLY_MAX_5M_MOVE = 2.50
EARLY_MIN_15M = 0.50
EARLY_MIN_1H = 1.00
EARLY_MAX_DISTANCE = 1.20

# ============================================================
# CONFIRMED
# ============================================================

CONFIRMED_MIN_VOLUME = 1.20
CONFIRMED_MAX_VOLUME = 8.00
CONFIRMED_MAX_5M_MOVE = 4.00
CONFIRMED_MIN_15M = 0.50
CONFIRMED_MIN_1H = 1.00

# ============================================================
# WATCH
# ============================================================

WATCH_MIN_VOLUME = 0.80
WATCH_MAX_VOLUME = 6.00
WATCH_MAX_5M_MOVE = 2.50
WATCH_MIN_15M = 0.50
WATCH_MIN_1H = 1.00
WATCH_MAX_DISTANCE = 1.50

# ============================================================
# PAPER TRACKER
# ============================================================

PAPER_TRACKING = True
MAX_HISTORY = 500

STATE_FILE = "paper_trades.json"

# GitHub Actions token
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()

# ============================================================
# REAL ORDERS
# ============================================================

LIVE_TRADING = False

# ============================================================
# HTTP
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/39.4",
        "Accept": "application/json",
    }
)

# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()


def telegram_send(message):

    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN NOT FOUND")
        return False

    if not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM_CHAT_ID NOT FOUND")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    try:

        response = SESSION.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            return True

        print(
            "TELEGRAM ERROR:",
            response.status_code,
            response.text[:500],
        )

    except Exception as e:

        print("TELEGRAM EXCEPTION:", str(e))

    return False


# ============================================================
# TIME
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# API
# ============================================================

def api_get(path, params=None):

    try:

        response = SESSION.get(
            BASE_URL + path,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if not response.ok:
            return None

        return response.json()

    except Exception:

        return None


# ============================================================
# LIST EXTRACTION
# ============================================================

def extract_list(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in [
        "data",
        "result",
        "results",
        "items",
        "symbols",
        "markets",
        "tickers",
        "rows",
    ]:

        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):

            nested = extract_list(value)

            if nested:
                return nested

    return []


# ============================================================
# SYMBOL
# ============================================================

def normalize_symbol(value):

    if value is None:
        return ""

    return (
        str(value)
        .upper()
        .strip()
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
    )


def extract_symbol(item):

    if isinstance(item, str):
        return normalize_symbol(item)

    if not isinstance(item, dict):
        return ""

    for key in [
        "symbol",
        "market",
        "pair",
        "code",
        "name",
        "instrument",
    ]:

        value = item.get(key)

        if isinstance(value, str):

            symbol = normalize_symbol(value)

            if symbol:
                return symbol

    return ""


# ============================================================
# MARKETS
# ============================================================

def get_usdt_markets():

    endpoints = [
        "/r/api/v1/ticker/24hr",
        "/r/api/v1/tickers",
        "/r/api/v1/ticker",
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
        "/r/api/v1/exchangeInfo",
        "/r/api/v1/exchange/info",
    ]

    for endpoint in endpoints:

        print("🔎 MARKET DISCOVERY:", endpoint)

        data = api_get(endpoint)

        if data is None:
            continue

        items = extract_list(data)

        if not items:
            continue

        symbols = []

        for item in items:

            symbol = extract_symbol(item)

            if symbol.endswith("USDT"):
                symbols.append(symbol)

        symbols = sorted(set(symbols))

        if len(symbols) >= 10:

            print(
                "✅ MARKET DISCOVERY OK:",
                len(symbols),
                "USDT markets",
            )

            return symbols[:MAX_MARKETS]

    for endpoint in [
        "/r/api/v1/ticker/24hr",
        "/r/api/v1/tickers",
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
    ]:

        data = api_get(endpoint)

        if not isinstance(data, dict):
            continue

        container = None

        for key in [
            "data",
            "result",
            "markets",
            "symbols",
            "tickers",
        ]:

            value = data.get(key)

            if isinstance(value, dict):
                container = value
                break

        if container is None:
            container = data

        symbols = []

        for key, value in container.items():

            symbol = normalize_symbol(key)

            if symbol.endswith("USDT"):
                symbols.append(symbol)

            if isinstance(value, dict):

                symbol2 = extract_symbol(value)

                if symbol2.endswith("USDT"):
                    symbols.append(symbol2)

        symbols = sorted(set(symbols))

        if len(symbols) >= 10:

            print(
                "✅ MARKET DISCOVERY OK:",
                len(symbols),
                "USDT markets",
            )

            return symbols[:MAX_MARKETS]

    return []


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):

    data = api_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if data is None:
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        return extract_list(data)

    return []


def parse_trade(item):

    if not isinstance(item, dict):
        return None

    price = None
    quantity = None
    timestamp = None

    for key in [
        "price",
        "p",
        "lastPrice",
    ]:

        if key in item:
            price = item.get(key)
            break

    for key in [
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
    ]:

        if key in item:
            quantity = item.get(key)
            break

    for key in [
        "time",
        "timestamp",
        "T",
        "createdAt",
    ]:

        if key in item:
            timestamp = item.get(key)
            break

    try:

        price = float(price)
        quantity = float(quantity)

    except Exception:

        return None

    if timestamp is None:
        timestamp = int(time.time() * 1000)

    try:
        timestamp = float(timestamp)
    except Exception:
        timestamp = int(time.time() * 1000)

    if timestamp < 10000000000:
        timestamp *= 1000

    return {
        "price": price,
        "qty": quantity,
        "time": timestamp,
    }


# ============================================================
# CANDLES
# ============================================================

def build_5m_candles(trades):

    parsed = []

    for item in trades:

        trade = parse_trade(item)

        if trade:
            parsed.append(trade)

    if len(parsed) < 20:
        return []

    parsed.sort(
        key=lambda x: x["time"]
    )

    buckets = {}

    for trade in parsed:

        bucket = (
            int(trade["time"] // 300000)
            * 300000
        )

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
            }

        candle = buckets[bucket]

        price = trade["price"]

        candle["high"] = max(
            candle["high"],
            price,
        )

        candle["low"] = min(
            candle["low"],
            price,
        )

        candle["close"] = price

        candle["volume"] += trade["qty"]

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles[-CANDLE_LIMIT:]


def aggregate_candles(
    candles,
    factor,
):

    if len(candles) < factor:
        return []

    usable = (
        len(candles)
        - len(candles) % factor
    )

    candles = candles[-usable:]

    result = []

    for i in range(
        0,
        len(candles),
        factor,
    ):

        group = candles[
            i:i +
