import os
import time
import hmac
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.41
# AL BROOKS PRICE ACTION - LOOSER ENTRY
# ============================================================
#
# V40.2.41 CHANGES:
#
# CORE:
#   Trend + REAL BOS
#
# OPTIONAL:
#   Pullback
#   Continuation
#   Signal Bar
#   Closed Confirmation
#
# BLOCKERS:
#   Failed Breakout
#   Excessive Chase
#   DOWN Trend
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

VERSION = "V40.2.41"

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
# CLOSED CONFIRM
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


def fmt_pct(value):
    return f"{value:+.2f}%"


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:

        print("TELEGRAM: credentials missing")

        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:

        response = SESSION.post(
            url,
            json=payload,
            timeout=TELEGRAM_TIMEOUT,
        )

        if response.status_code == 200:

            return True

        print(
            "TELEGRAM ERROR:",
            response.status_code,
            response.text[:300],
        )

        return False

    except Exception as exc:

        print(
            "TELEGRAM EXCEPTION:",
            str(exc),
        )

        return False


# ============================================================
# PUBLIC API
# ============================================================

def public_get(path, params=None):

    url = f"{BASE_URL}{path}"

    try:

        response = SESSION.get(
            url,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:

            return (
                None,
                f"HTTP {response.status_code}: "
                f"{response.text[:200]}",
            )

        try:

            return response.json(), None

        except Exception:

            return None, "Invalid JSON"

    except Exception as exc:

        return None, str(exc)


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():

    data, error = public_get(
        "/r/api/v1/time"
    )

    if error:

        return int(
            time.time() * 1000
        )

    if isinstance(data, dict):

        for key in (
            "serverTime",
            "timestamp",
            "time",
            "data",
        ):

            if key not in data:
                continue

            value = data[key]

            if isinstance(value, dict):

                for subkey in (
                    "serverTime",
                    "timestamp",
                    "time",
                ):

                    if subkey in value:

                        value = value[subkey]

                        break

            try:

                return int(value)

            except Exception:

                pass

    return int(
        time.time() * 1000
    )


# ============================================================
# HMAC AUTH
# ============================================================

def signed_get(path, extra_params=None):

    if not API_KEY or not API_SECRET:

        return None, "API credentials missing"

    timestamp = get_server_time()

    recv_window = 5000

    params = {
        "timestamp": int(timestamp),
        "recvWindow": recv_window,
    }

    if extra_params:

        params.update(
            extra_params
        )

    sign_query = (
        f"timestamp={int(timestamp)}"
        f"&recvWindow={int(recv_window)}"
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        sign_query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    params["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY,
    }

    url = f"{BASE_URL}{path}"

    try:

        response = SESSION.get(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:

            return (
                None,
                f"HTTP {response.status_code}: "
                f"{response.text[:300]}",
            )

        try:

            return response.json(), None

        except Exception:

            return None, "Invalid JSON response"

    except Exception as exc:

        return None, str(exc)


# ============================================================
# AUTH TEST
# ============================================================

def auth_test():

    print("AUTH TEST: STARTING")

    data, error = signed_get(
        "/r/api/v1/account"
    )

    if error:

        print(
            "AUTH FAILED:",
            error,
        )

        send_telegram(
            f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
            f"❌ {error}\n\n"
            f"🔐 HMAC-SHA256\n"
            f"🔢 SERVER TIMESTAMP\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🕐 {now_utc()}"
        )

        return False

    if data is None:

        return False

    print("AUTH TEST: OK")

    return True


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    data, error = public_get(
        "/r/api/v1/exchangeInfo"
    )

    if error:

        print(
            "EXCHANGE INFO ERROR:",
            error,
        )

        return []

    if isinstance(data, list):

        raw = data

    elif isinstance(data, dict):

        raw = (
            data.get("symbols")
            or data.get("data")
            or data.get("markets")
            or []
        )

        if isinstance(raw, dict):

            raw = (
                raw.get("symbols")
                or raw.get("markets")
                or []
            )

    else:

        raw = []

    markets = []

    for item in raw:

        if not isinstance(item, dict):

            continue

        symbol = (
            item.get("symbol")
            or item.get("market")
            or item.get("name")
            or item.get("tabdealSymbol")
            or item.get("tabdeal_symbol")
        )

        if not symbol:

            continue

        symbol = str(
            symbol
        ).upper()

        if not symbol.endswith("USDT"):

            continue

        if any(
            x in symbol
            for x in (
                "UPUSDT",
                "DOWNUSDT",
                "BULLUSDT",
                "BEARUSDT",
            )
        ):

            continue

        markets.append({
            "symbol": symbol,
            "raw": item,
        })

    unique = {}

    for market in markets:

        unique[
            market["symbol"]
        ] = market

    return list(
        unique.values()
    )


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(item, dict):

        return None

    price = None
    quantity = None
    timestamp = None

    for key in (
        "price",
        "p",
        "tradePrice",
        "lastPrice",
    ):

        if key in item:

            price = safe_float(
                item[key]
            )

            break

    for key in (
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
        "baseQty",
    ):

        if key in item:

            quantity = safe_float(
                item[key]
            )

            break

    for key in (
        "time",
        "timestamp",
        "T",
        "tradeTime",
        "createdAt",
    ):

        if key in item:

            try:

                timestamp = int(
                    float(item[key])
                )

            except Exception:

                timestamp = None

            break

    if price is None or price <= 0:

        return None

    if quantity is None or quantity <= 0:

        quantity = 1.0

    if timestamp is None:

        return None

    if timestamp < 10_000_000_000:

        timestamp *= 1000

    return {
        "price": price,
        "qty": quantity,
        "time": timestamp,
    }


# ============================================================
# GET TRADES
# ============================================================

def get_trades(symbol):

    attempts = [
        {
            "tabdealSymbol": symbol,
            "limit": TRADE_LIMIT,
        },
        {
            "symbol": symbol,
            "limit": TRADE_LIMIT,
        },
        {
            "market": symbol,
            "limit": TRADE_LIMIT,
        },
        {
            "tabdeal_symbol": symbol,
            "limit": TRADE_LIMIT,
        },
    ]

    for params in attempts:

        data, error = public_get(
            "/r/api/v1/trades",
            params,
        )

        if error:

            continue

        raw = data

        if isinstance(data, dict):

            raw = (
                data.get("data")
                or data.get("trades")
                or data.get("result")
                or []
            )

        if not isinstance(raw, list):

            continue

        trades = []

        for item in raw:

            parsed = parse_trade(
                item
            )

            if parsed:

                trades.append(
                    parsed
                )

        if trades:

            trades.sort(
                key=lambda x: x["time"]
            )

            return trades

    return []


# ============================================================
# BUILD CLOSED 5M CANDLES
# ============================================================

def build_5m_candles(trades):

    buckets = {}

    for trade in trades:

        timestamp = trade["time"]

        bucket = (
            timestamp // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
                "trades": 0,
            }

        candle = buckets[bucket]

        candle["high"] = max(
            candle["high"],
            trade["price"],
        )

        candle["low"] = min(
            candle["low"],
            trade["price"],
        )

        candle["close"] = trade["price"]

        candle["volume"] += (
            trade["qty"]
            * trade["price"]
        )

        candle["trades"] += 1

    candles = sorted(
        buckets.values(),
        key=lambda x: x["time"],
    )

    if candles:

        current_bucket = (
            int(time.time() * 1000)
            // 300000
        ) * 300000

        candles = [
            candle
            for candle in candles
            if candle["time"]
            < current_bucket
        ]

    return candles


# ============================================================
# CANDLE / PRICE ACTION
# ============================================================

def candle_range(candle):

    return max(
        candle["high"]
        - candle["low"],
        1e-12,
    )


def candle_position(candle):

    rng = candle_range(
        candle
    )

    return (
        (
            candle["close"]
            - candle["low"]
        )
        / rng
    )


# ============================================================
# BROOKS SIGNAL BAR
# ============================================================

def is_bull_signal_bar(candle):

    rng = candle_range(
        candle
    )

    close_from_high = (
        candle["high"]
        - candle["close"]
    ) / rng

    close_position = candle_position(
        candle
    )

    return (
        close_position >= 0.65
        and close_from_high <= 0.35
    )


# ============================================================
# CLOSED CANDLE CONFIRMATION
# ============================================================

def closed_candle_confirmation(
    current,
    previous,
):

    current_position = candle_position(
        current
    )

   
