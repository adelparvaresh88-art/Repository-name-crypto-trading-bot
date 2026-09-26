import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V38.1.1
# BREAKOUT + RETEST + MOMENTUM
# UPWARD COIN SCANNER
# TELEGRAM DIAGNOSTIC EDITION
# ============================================================

VERSION = "V38.1.1"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

MAX_MARKETS = 1000
TOP_BUYS = 3
TOP_WATCH = 3

TRADE_LIMIT = 1000
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_MARKETS = 0.02

# ------------------------------------------------------------
# SCORE SETTINGS
# ------------------------------------------------------------

BUY_MIN_SCORE = 11
WATCH_MIN_SCORE = 8

MAX_5M_CHASE = 7.0

MIN_15M_MOMENTUM = 1.0
MIN_1H_MOMENTUM = 1.0

MIN_CANDLES = 20

# ------------------------------------------------------------
# RISK
# ------------------------------------------------------------

SL_PERCENT = 0.50
TP1_PERCENT = 0.80
TP2_PERCENT = 1.50

# ------------------------------------------------------------
# TELEGRAM
# ------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/38.1.1",
        "Accept": "application/json",
    }
)


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def safe_float(
    value,
    default=0.0
):
    try:
        return float(value)
    except Exception:
        return default


def api_get(
    path,
    params=None
):
    url = BASE_URL + path

    response = SESSION.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print(
            "❌ TELEGRAM_BOT_TOKEN NOT FOUND"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "❌ TELEGRAM_CHAT_ID NOT FOUND"
        )
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:

        response = SESSION.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        print(
            f"📨 TELEGRAM HTTP: "
            f"{response.status_code}"
        )

        if response.ok:

            try:
                data = response.json()
            except Exception:
                data = {}

            if data.get("ok") is True:

                print(
                    "✅ TELEGRAM SENT"
                )

                return True

            print(
                "❌ TELEGRAM API REJECTED:",
                str(data)[:500]
            )

            return False

        print(
            "❌ TELEGRAM ERROR:",
            response.status_code,
            response.text[:500],
        )

    except Exception as e:

        print(
            "❌ TELEGRAM EXCEPTION:",
            e
        )

    return False


# ============================================================
# TELEGRAM STARTUP TEST
# ============================================================

def telegram_startup_test():

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🟢 BOT STARTED\n"
        f"📡 Telegram connection: OK\n"
        f"🔒 REAL TRADING: DISABLED\n"
        f"🧪 SCANNER MODE ONLY\n\n"
        f"🕐 {now_utc()}"
    )

    return send_telegram(message)


# ============================================================
# MARKET LIST
# ============================================================

def load_usdt_markets():

    try:

        data = api_get(
            "/r/api/v1/exchangeInfo"
        )

    except Exception as e:

        print(
            "❌ TABDEAL MARKET ERROR:",
            e
        )

        return []

    markets = []

    # --------------------------------------------------------
    # Handle different possible response structures
    # --------------------------------------------------------

    raw = data

    if isinstance(data, dict):

        for key in (
            "symbols",
            "data",
            "markets",
            "result",
            "list",
        ):

            if key in data:

                raw = data[key]
                break

    if isinstance(raw, dict):

        for key in (
            "symbols",
            "data",
            "markets",
            "result",
            "list",
        ):

            if key in raw:

                raw = raw[key]
                break

    # --------------------------------------------------------
    # String symbol list
    # --------------------------------------------------------

    if isinstance(raw, list):

        for item in raw:

            if isinstance(item, str):

                symbol = item.upper()

                if symbol.endswith("USDT"):

                    markets.append(symbol)

                continue

            if not isinstance(item, dict):

                continue

            symbol = str(
                item.get("symbol")
                or item.get("name")
                or item.get("market")
                or ""
            ).upper()

            if not symbol:

                continue

            quote = str(
                item.get("quoteAsset")
                or item.get("quote")
                or ""
            ).upper()

            status = str(
                item.get("status")
                or ""
            ).upper()

            if status in (
                "BREAK",
                "BREAKING",
                "HALT",
                "HALTED",
                "CLOSED",
            ):

                continue

            if (
                symbol.endswith("USDT")
                or quote == "USDT"
            ):

                markets.append(symbol)

    markets = sorted(
        set(markets)
    )

    if len(markets) > MAX_MARKETS:

        markets = markets[:MAX_MARKETS]

    return markets


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(item, dict):

        return None

    price = (
        item.get("price")
        or item.get("p")
    )

    qty = (
        item.get("qty")
        or item.get("quantity")
        or item.get("q")
    )

    timestamp = (
        item.get("time")
        or item.get("timestamp")
        or item.get("T")
    )

    price = safe_float(price)
    qty = safe_float(qty)
    timestamp = safe_float(timestamp)

    if price <= 0:

        return None

    if timestamp <= 0:

        return None

    # milliseconds → seconds
    if timestamp > 100000000000:

        timestamp = timestamp / 1000.0

    return {
        "price": price,
        "qty": qty,
        "time": timestamp,
    }


# ============================================================
# LOAD TRADES
# ============================================================

def load_trades(symbol):

    try:

        data = api_get(
            "/r/api/v1/trades",
            params={
                "symbol": symbol,
                "limit": TRADE_LIMIT,
            },
        )

    except Exception as e:

        print(
            f"⚠️ {symbol} TRADE ERROR: {e}"
        )

        return []

    raw = data

    if isinstance(data, dict):

        for key in (
            "data",
            "trades",
            "result",
            "list",
        ):

            if key in data:

                raw = data[key]
                break

    if not isinstance(raw, list):

        return []

    trades = []

    for item in raw:

        trade = parse_trade(item)

        if trade:

            trades.append(trade)

    trades.sort(
        key=lambda x: x["time"]
    )

    return trades


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_candles(trades):

    buckets = {}

    for trade in trades:

        ts = int(
            trade["time"]
        )

        bucket = ts - (
            ts % 300
        )

        price = trade["price"]
        qty = trade["qty"]

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
            }

        else:

            candle = buckets[bucket]

            candle["high"] = max(
                candle["high"],
                price,
            )

            candle["low"] = min(
                candle["low"],
                price,
            )

            candle["close"] = price

            candle["volume"] += qty

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


# ============================================================
# PERCENT CHANGE
# ============================================================

def percent_change(
    old,
    new
):

    if old <= 0:

        return 0.0

    return (
        (new - old)
        / old
        * 100.0
    )


# ============================================================
# MOMENTUM
# ============================================================

def calculate_momentum(
    candles
):

    if len(candles) < 13:

        return (
            0.0,
            0.0,
            0.0
        )

    current = candles[-1]["close"]

    close_5m = candles[-2]["close"]

    close_15m = candles[-4]["close"]

    close_1h = candles[-13]["close"]

    m5 = percent_change(
        close_5m,
        current,
    )

    m15 = percent_change(
        close_15m,
        current,
    )

    m1h = percent_change(
        close_1h,
        current,
    )

    return (
        m5,
        m15,
        m1h
    )


# ============================================================
# STRUCTURE
# ============================================================

def calculate_structure(
    candles
):

    if len(candles) < 8:

        return (
            False,
            False
        )

    current = candles[-1]

    previous = candles[-2]

    lookback = candles[-7:-2]

    if not lookback:

        return (
            False,
            False
        )

    previous_high = max(
        c["high"]
        for c in lookback
    )

    previous_low = min(
        c["low"]
        for c in lookback
    )

    breakout = (
        current["close"]
        > previous_high
    )

    higher_high = (
        current["high"]
        > previous["high"]
        and current["close"]
        >= previous["close"]
    )

    return (
        breakout,
        higher_high
    )


# ============================================================
# BREAKOUT LEVEL
# ============================================================

def get_breakout_level(
    candles
):

    if len(candles) < 8:

        return 0.0

    lookback = candles[-7:-2]

    return max(
        c["high"]
       
