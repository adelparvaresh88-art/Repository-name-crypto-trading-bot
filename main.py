import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V37.1
# UPWARD COIN SCANNER
# ============================================================

VERSION = "V37.1"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 720
MAX_MARKETS = 1000
TOP_RESULTS = 5

REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_MARKETS = 0.03

MIN_SCORE = 6

# ============================================================
# SAFETY
# ============================================================

REAL_TRADING = False
ORDER_EXECUTION = False


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-CRYPTO-BOT/37.1",
        "Accept": "application/json",
    }
)


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "",
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    "",
).strip()


def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = (
            "https://api.telegram.org/bot"
            + TELEGRAM_BOT_TOKEN
            + "/sendMessage"
        )

        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT,
        )

        return response.ok

    except Exception:
        return False


# ============================================================
# SAFE JSON
# ============================================================

def get_json(url, params=None):
    try:
        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            return None

        try:
            return response.json()
        except Exception:
            return None

    except Exception:
        return None


# ============================================================
# GENERIC HELPERS
# ============================================================

def as_list(value):

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, dict):

        for key in (
            "data",
            "result",
            "results",
            "items",
            "symbols",
            "markets",
            "ticker",
            "tickers",
        ):

            item = value.get(key)

            if isinstance(item, list):
                return item

        return []

    return []


def safe_float(value, default=None):

    try:

        if value is None:
            return default

        if isinstance(value, bool):
            return default

        return float(value)

    except Exception:

        return default


def safe_int(value, default=None):

    try:
        return int(float(value))

    except Exception:

        return default


def now_utc():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def pct_change(old, new):

    if old is None or new is None:
        return 0.0

    if old == 0:
        return 0.0

    return (
        (new - old)
        / old
    ) * 100.0


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def normalize_symbol(value):

    if value is None:
        return None

    text = str(value).upper().strip()

    text = text.replace("-", "")
    text = text.replace("_", "")
    text = text.replace("/", "")

    if text.endswith("USDT"):
        return text

    return None


def extract_symbol(item):

    if isinstance(item, str):
        return normalize_symbol(item)

    if not isinstance(item, dict):
        return None

    for key in (
        "symbol",
        "pair",
        "market",
        "instrument",
        "code",
        "name",
    ):

        value = item.get(key)

        symbol = normalize_symbol(value)

        if symbol:
            return symbol

    return None


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_markets():

    endpoints = [
        "/r/api/v1/exchangeInfo",
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
        "/r/api/v1/tickers",
    ]

    symbols = set()

    for endpoint in endpoints:

        data = get_json(
            BASE_URL + endpoint
        )

        if data is None:
            continue

        items = as_list(data)

        for item in items:

            symbol = extract_symbol(item)

            if symbol and symbol.endswith("USDT"):
                symbols.add(symbol)

        if symbols:
            break

    symbols = {
        s
        for s in symbols
        if (
            s
            and s.endswith("USDT")
            and len(s) > 4
            and len(s) < 30
        )
    }

    symbols = sorted(symbols)

    if MAX_MARKETS:
        symbols = symbols[:MAX_MARKETS]

    return symbols


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):

    data = get_json(
        BASE_URL + "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if data is None:
        return []

    return as_list(data)


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if isinstance(item, list):

        if len(item) < 2:
            return None

        price = safe_float(item[0])
        qty = safe_float(item[1])

        timestamp = None

        if len(item) >= 3:
            timestamp = safe_int(item[2])

        if price is None or qty is None:
            return None

        return {
            "price": price,
            "qty": abs(qty),
            "timestamp": timestamp,
        }

    if not isinstance(item, dict):
        return None

    price = None
    qty = None
    timestamp = None

    for key in (
        "price",
        "p",
        "trade_price",
        "rate",
    ):

        if key in item:

            price = safe_float(
                item.get(key)
            )

            if price is not None:
                break

    for key in (
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
    ):

        if key in item:

            qty = safe_float(
                item.get(key)
            )

            if qty is not None:
                break

    for key in (
        "timestamp",
        "time",
        "T",
        "created_at",
        "createdAt",
    ):

        if key in item:

            timestamp = safe_int(
                item.get(key)
            )

            if timestamp is not None:
                break

    if price is None or qty is None:
        return None

    return {
        "price": price,
        "qty": abs(qty),
        "timestamp": timestamp,
    }


# ============================================================
# TIMESTAMP
# ============================================================

def normalize_timestamp(ts):

    if ts is None:
        return None

    if ts > 10_000_000_000:
        return ts / 1000.0

    return float(ts)


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_candles(trades):

    parsed = []

    for item in trades:

        trade = parse_trade(item)

        if trade is None:
            continue

        ts = normalize_timestamp(
            trade["timestamp"]
        )

        if ts is None:
            continue

        trade["timestamp"] = ts

        parsed.append(trade)

    if not parsed:
        return []

    parsed.sort(
        key=lambda x: x["timestamp"]
    )

    buckets = {}

    for trade in parsed:

        bucket = (
            int(
                trade["timestamp"] // 300
            )
            * 300
        )

        if bucket not in buckets:

            buckets[bucket] = {
                "timestamp": bucket,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
                "trades": 0,
            }

        candle = buckets[bucket]

        price = trade["price"]
        qty = trade["qty"]

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
        candle["trades"] += 1

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["timestamp"]
    )

    # --------------------------------------------------------
    # REMOVE CURRENT UNFINISHED 5M CANDLE
    # --------------------------------------------------------

    current_bucket = (
        int(time.time() // 300)
        * 300
    )

    candles = [
        c
        for c in candles
        if c["timestamp"] < current_bucket
    ]

    return candles[-CANDLE_LIMIT:]


# ============================================================
# CANDLE CONTINUITY
# ============================================================

def has_continuous_candles(
    candles,
    required_bars,
):
    """
    Checks that the latest 5m candles are
    actually consecutive.

    This prevents calling a sparse collection
    of trades a real 15m or 1h momentum.
    """

    if len(candles) < required_bars:
        return False

    recent = candles[
        -required_bars:
    ]

    for i in range(1, len(recent)):

        previous_ts = recent[
            i - 1
        ]["timestamp"]

        current_ts = recent[
            i
        ]["timestamp"]

        if (
            current_ts
            - previous_ts
            != 300
        ):
            return False

    return True


# ============================================================
# REAL 5M / 15M / 1H MOMENTUM
# ============================================================

def timeframe_momentum(
    candles,
    minutes,
):
    """
    Calculates momentum directly from completed
    5m candles.

    5m  = 1 candle
    15m = 3 candles
    1h  = 12 candles

    This avoids the old V37 issue where the
    higher timeframe could be misleading.
    """

    bars = minutes // 5

    required = bars + 1

    if not has_continuous_candles(
        candles,
        required,
    ):
        return None

    old = candles[
        -bars - 1
    ]["close"]

    new = candles[
        -1
    ]["close"]

    return pct_change(
        old
