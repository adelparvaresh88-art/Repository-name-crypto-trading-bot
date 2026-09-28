import os
import time
import json
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V39.6.7
# AUTO TOP 10 + CLEAN EARLY ENTRY + CONFIRMED BREAKOUT
# ============================================================

VERSION = "V39.6.7"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 180
MAX_MARKETS = 1000

# ------------------------------------------------------------
# IMPORTANT:
# All USDT markets are ranked first.
# Only TOP_SCAN_MARKETS are deeply analyzed.
# ------------------------------------------------------------

TOP_SCAN_MARKETS = 10

REQUEST_TIMEOUT = 10
MAX_WORKERS = 20

TOP_CONFIRMED = 3
TOP_EARLY = 5
TOP_WATCH = 5

CONFIRMED_MIN_SCORE = 11
EARLY_MIN_SCORE = 7
WATCH_MIN_SCORE = 6

BREAKOUT_BUFFER = 0.05

PAPER_TRACKING = True
MAX_HISTORY = 500
STATE_FILE = "paper_trades.json"

# Real orders intentionally disabled
LIVE_TRADING = False


# ============================================================
# ENV
# ============================================================

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

GH_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GH_REPO = os.getenv("GITHUB_REPOSITORY", "").strip()


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/39.6.7"
    }
)


# ============================================================
# TIME
# ============================================================

def now_text():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram(text):

    if not TG_TOKEN or not TG_CHAT_ID:
        print("Telegram credentials are missing.")
        return False

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"

    try:
        response = session.post(
            url,
            json={
                "chat_id": TG_CHAT_ID,
                "text": text
            },
            timeout=REQUEST_TIMEOUT
        )

        print("Telegram:", response.status_code)

        return response.ok

    except Exception as e:

        print("Telegram error:", e)

        return False


# ============================================================
# TABDEAL API
# ============================================================

def api_get(path, params=None):

    url = BASE_URL + path

    try:

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        print(
            "API",
            path,
            response.status_code
        )

        if not response.ok:

            print(
                response.text[:500]
            )

            return None

        return response.json()

    except Exception as e:

        print(
            "API error:",
            path,
            e
        )

        return None


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def normalize_symbol(value):

    if not isinstance(value, str):
        return ""

    symbol = (
        value
        .strip()
        .upper()
        .replace("_", "")
        .replace("-", "")
        .replace("/", "")
    )

    if (
        symbol.endswith("USDT")
        and len(symbol) >= 7
        and symbol.isalnum()
    ):
        return symbol

    return ""


# ============================================================
# EXCHANGE INFO PARSER
# ============================================================

def extract_exchange_symbols(data):

    if isinstance(data, list):

        items = data

    elif isinstance(data, dict):

        items = None

        for key in (
            "symbols",
            "data",
            "result",
            "markets",
            "items"
        ):

            value = data.get(key)

            if isinstance(value, list):

                items = value
                break

        if items is None:
            items = [data]

    else:

        return []

    output = []
    seen = set()

    for item in items:

        symbol = ""

        if isinstance(item, str):

            symbol = normalize_symbol(item)

        elif isinstance(item, dict):

            for key in (
                "symbol",
                "tabdealSymbol",
                "market",
                "pair",
                "name"
            ):

                symbol = normalize_symbol(
                    item.get(key)
                )

                if symbol:
                    break

            status = str(
                item.get("status", "")
            ).upper()

            if status:

                allowed = {
                    "TRADING",
                    "ACTIVE",
                    "ENABLED",
                    "OPEN"
                }

                if status not in allowed:
                    continue

        else:

            continue

        if symbol and symbol not in seen:

            seen.add(symbol)

            output.append(symbol)

    return output


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_markets():

    data = api_get(
        "/r/api/v1/exchangeInfo"
    )

    markets = extract_exchange_symbols(
        data
    )

    print(
        "ExchangeInfo type:",
        type(data).__name__
    )

    print(
        "USDT markets:",
        len(markets)
    )

    print(
        "First markets:",
        markets[:10]
    )

    return markets[:MAX_MARKETS]


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if isinstance(
        item,
        (list, tuple)
    ):

        if len(item) < 2:
            return None

        try:

            price = float(item[0])
            quantity = float(item[1])

            if len(item) > 2:

                timestamp = int(
                    float(item[2])
                )

            else:

                timestamp = int(
                    time.time() * 1000
                )

            return (
                timestamp,
                price,
                quantity
            )

        except Exception:

            return None

    if isinstance(item, dict):

        try:

            raw_price = item.get(
                "price",
                item.get("p")
            )

            raw_quantity = item.get(
                "qty",
                item.get(
                    "quantity",
                    item.get("q")
                )
            )

            price = float(raw_price)
            quantity = float(raw_quantity)

            timestamp = int(
                float(
                    item.get(
                        "time",
                        item.get(
                            "timestamp",
                            item.get(
                                "T",
                                time.time() * 1000
                            )
                        )
                    )
                )
            )

            return (
                timestamp,
                price,
                quantity
            )

        except Exception:

            return None

    return None


# ============================================================
# GET TRADES
# ============================================================

def get_trades(symbol):

    data = api_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000
        }
    )

    if isinstance(data, dict):

        for key in (
            "data",
            "trades",
            "result",
            "items"
        ):

            if isinstance(
                data.get(key),
                list
            ):

                data = data[key]
                break

    if not isinstance(data, list):
        return []

    output = []

    for item in data:

        parsed = parse_trade(item)

        if parsed:
            output.append(parsed)

    return sorted(output)


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_5m_candles(trades):

    if not trades:
        return []

    buckets = {}

    for timestamp, price, quantity in trades:

        bucket = (
            timestamp // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = [
                price,
                price,
                price,
                price,
                0.0
            ]

        candle = buckets[bucket]

        candle[1] = max(
            candle[1],
            price
        )

        candle[2] = min(
            candle[2],
            price
        )

        candle[3] = price

        candle[4] += quantity

    output = []

    for timestamp in sorted(buckets):

        open_price, high, low, close, volume = (
            buckets[timestamp]
        )

        output.append(
            {
                "t": timestamp,
                "o": open_price,
                "h": high,
                "l": low,
                "c": close,
                "v": volume
            }
        )

    return output[-CANDLE_LIMIT:]


# ============================================================
# AGGREGATE CANDLES
# ============================================================

def aggregate(candles, minutes):

    step = minutes // 5

    if len(candles) < step:
        return []

    output = []

    for i in range(
        0,
        len(candles) - step + 1,
        step
    ):

        group = candles[
            i:i + step
        ]

        output.append(
            {
                "t": group[0]["t"],
                "o": group[0]["o"],
                "h": max(
                    x["h"] for x in group
                ),
                "l": min(
                    x["l"] for x in group
                ),
                "c": group[-1]["c"],
                "v": sum(
                    x["v"] for x in group
                )
            }
        )

    return output


# ============================================================
# PERCENT CHANGE
# ============================================================

def pct(old, new):

    if not old:
        return 0.0

    return (
        (new - old) / old
    ) * 100.0


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(candles, n=20):

    if len(candles) < n + 1:
        return 0.0

    average = (
        sum(
            x["v"]
            for x in candles[-n - 1:-1]
        ) / n
    )

    if average <= 0:
        return 0.0

    return candles[-1]["v"] / average


# ============================================================
# RESISTANCE
# ============================================================

def resistance(candles, n=24):

    if len(candles) < n + 1:
        return 0.0

    return max(
        x["h"]
        for x in candles[-n - 1:-1]
    )


# ============================================================
# AVERAGE RANGE
# ============================================================

def average_range(candles, n=20):

    part = candles[-n:]

    if not part:
        return 0.0

    return (
        sum(
            x["h"] - x["l"]
            for x in part
        )
        / len(part)
    )


# ============================================================
# STRONG BULLISH CANDLE
# ============================================================

def strong_bullish_candle(candle):

    candle_range = (
        candle["h"] - candle["l"]
    )

    if candle_range <= 0:
        return False

    body = (
        candle["c"] - candle["o"]
    )

    return (
        body > 0
        and body / candle_range >= 0.45
        and candle["c"]
        >= candle["l"]
        + candle_range * 0.65
    )


# ============================================================
# QUICK RANKING
#
# This function is used to choose the automatic TOP 10.
# It does NOT require
