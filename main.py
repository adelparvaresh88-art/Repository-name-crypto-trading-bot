import os
import time
import hmac
import hashlib
import json
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.62-OFFICIAL-API
# TABDEAL SPOT
#
# OFFICIAL API PATHS:
#
# PUBLIC:
#   GET  /r/api/v1/exchangeInfo
#   GET  /r/api/v1/trades
#
# TRADE:
#   GET  /r/api/v1/account
#   POST /api/v1/order
#   GET  /r/api/v1/order
#
# STRATEGY:
#   REAL BOS
#   NEAR BOS
#   PULLBACK / RECLAIM
#   CLOSED 5M CANDLE
#   STRONG CLOSE
#   MOMENTUM
#
# EMA: OFF
#
# IMPORTANT:
#   This version NEVER reports "FILLED" unless the exchange
#   actually returns FILLED for the order.
# ============================================================


VERSION = "V40.2.62-OFFICIAL-API"

BASE = "https://api1.tabdeal.org"

API_ROOT = f"{BASE}/r/api/v1"
TRADE_ROOT = f"{BASE}/api/v1"

TIMEOUT = 15
RECV_WINDOW = 5000

# ------------------------------------------------------------
# SCAN
# ------------------------------------------------------------

SCAN_UNIVERSE = int(
    os.getenv("SCAN_UNIVERSE", "80")
)

TRADE_LIMIT = min(
    int(os.getenv("TRADE_LIMIT", "1000")),
    1000
)

MIN_CANDLES = int(
    os.getenv("MIN_CANDLES", "8")
)

MAX_WORKERS = int(
    os.getenv("MAX_WORKERS", "8")
)

# ------------------------------------------------------------
# STRATEGY
# ------------------------------------------------------------

REAL_BOS_MIN = Decimal("0.0002")
NEAR_BOS_MIN = Decimal("-0.0050")

PULLBACK_TOLERANCE = Decimal("0.0120")

CHASE_LIMIT = Decimal("0.0300")

MIN_CONFIRM_CLOSE_POSITION = Decimal("0.50")

MIN_SCORE = Decimal(
    os.getenv("MIN_SCORE", "8")
)

# ------------------------------------------------------------
# ORDER
# ------------------------------------------------------------

ORDER_VALUE = Decimal(
    os.getenv("ORDER_QTY", "2")
)

LIVE_TRADING = os.getenv(
    "LIVE_TRADING",
    "false"
).strip().lower() in (
    "1",
    "true",
    "yes",
    "on"
)

# فقط یک سفارش واقعی در هر اجرای ربات
MAX_REAL_ORDERS_PER_RUN = 1

# ------------------------------------------------------------
# API KEYS
# ------------------------------------------------------------

API_KEY = (
    os.getenv("TABDIL_API_KEY")
    or os.getenv("TABDEAL_API_KEY")
    or ""
).strip()

API_SECRET = (
    os.getenv("TABDIL_API_SECRET")
    or os.getenv("TABDEAL_API_SECRET")
    or ""
).strip()

if not API_SECRET:

    API_SECRET = (
        os.getenv("TABDIL_SECRET")
        or os.getenv("TABDEAL_SECRET")
        or ""
    ).strip()

# ------------------------------------------------------------
# TELEGRAM
# ------------------------------------------------------------

TG_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TG_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# GLOBALS
# ============================================================

session = requests.Session()

SERVER_TIME_OFFSET = 0

TRADE_OK = 0
TRADE_ERROR = 0

REAL_ORDERS_SENT = 0


# ============================================================
# TIME
# ============================================================

def now_utc():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def local_ms():

    return int(
        time.time() * 1000
    )


def now_ms():

    return (
        local_ms()
        + SERVER_TIME_OFFSET
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):

    if not TG_TOKEN or not TG_CHAT_ID:

        print(
            "TELEGRAM CONFIG MISSING"
        )

        print(message)

        return

    try:

        url = (
            "https://api.telegram.org/bot"
            f"{TG_TOKEN}/sendMessage"
        )

        payload = {
            "chat_id": TG_CHAT_ID,
            "text": str(message)
        }

        response = requests.post(
            url,
            json=payload,
            timeout=10
        )

        if response.status_code != 200:

            print(
                "TELEGRAM ERROR:",
                response.status_code,
                response.text[:500]
            )

    except Exception as e:

        print(
            "TELEGRAM EXCEPTION:",
            e
        )


# ============================================================
# SAFE DECIMAL
# ============================================================

def D(value):

    try:

        if value is None:
            return Decimal("0")

        return Decimal(
            str(value)
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError
    ):

        return Decimal("0")


# ============================================================
# PUBLIC GET
# ============================================================

def public_get(
    path,
    params=None
):

    url = (
        f"{BASE}{path}"
    )

    response = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:800]}"
        )

    try:

        return response.json()

    except Exception:

        raise RuntimeError(
            "INVALID JSON: "
            f"{response.text[:800]}"
        )


# ============================================================
# SERVER TIME
#
# The exchange's API time endpoint may differ between
# deployments. Failure to sync does NOT prevent the bot from
# continuing; local time is used.
# ============================================================

def sync_server_time():

    global SERVER_TIME_OFFSET

    candidate_paths = (
        f"{API_ROOT}/time",
        "/api/v1/time",
        "/r/api/v1/time",
    )

    for path in candidate_paths:

        try:

            data = public_get(
                path
            )

            if isinstance(data, dict):

                server_time = (
                    data.get("serverTime")
                    or data.get("timestamp")
                    or data.get("time")
                )

            else:

                server_time = None

            if server_time is None:
                continue

            SERVER_TIME_OFFSET = (
                int(server_time)
                - local_ms()
            )

            print(
                f"🕐 SERVER OFFSET: "
                f"{SERVER_TIME_OFFSET} ms"
            )

            return True

        except Exception as e:

            print(
                f"TIME ENDPOINT FAILED "
                f"{path}: {e}"
            )

    SERVER_TIME_OFFSET = 0

    print(
        "⚠️ SERVER TIME SYNC "
        "NOT AVAILABLE"
    )

    print(
        "ℹ️ USING LOCAL CLOCK"
    )

    return False


# ============================================================
# SIGNATURE
#
# Official documentation:
# Query string is signed using API secret and HMAC-SHA256.
# ============================================================

def sign_params(params):

    query_string = urlencode(
        params,
        doseq=True
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return signature


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(
    method,
    path,
    params=None
):

    if not API_KEY:

        raise RuntimeError(
            "API KEY MISSING"
        )

    if not API_SECRET:

        raise RuntimeError(
            "API SECRET MISSING"
        )

    payload = dict(
        params or {}
    )

    # timestamp must be part of the signed query
    payload["timestamp"] = now_ms()

    # recvWindow is signed as well
    payload["recvWindow"] = RECV_WINDOW

    signature = sign_params(
        payload
    )

    payload["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Accept": "application/json",
    }

    url = (
        f"{BASE}{path}"
    )

    method = method.upper()

    if method == "GET":

        response = session.get(
            url,
            params=payload,
            headers=headers,
            timeout=TIMEOUT
        )

    elif method == "POST":

        response = session.post(
            url,
            params=payload,
            headers=headers,
            timeout=TIMEOUT
        )

    elif method == "DELETE":

        response = session.delete(
            url,
            params=payload,
            headers=headers,
            timeout=TIMEOUT
        )

    else:

        raise RuntimeError(
            f"UNSUPPORTED METHOD: {method}"
        )

    if response.status_code < 200 or response.status_code >= 300:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    try:

        return response.json()

    except Exception:

        raise RuntimeError(
            "INVALID JSON: "
            f"{response.text[:1000]}"
        )


# ============================================================
# AUTH CHECK
# ============================================================

def auth_check():

    print(
        "🔐 AUTH CHECK"
    )

    try:

        account = signed_request(
            "GET",
            f"{API_ROOT}/account"
        )

        can_trade = bool(
            account.get(
                "canTrade",
                False
            )
        )

        print(
            "✅ AUTH SUCCESS"
        )

        print(
            f"🔑 API KEY: "
            f"{API_KEY[:6]}..."
        )

        print(
            f"🔓 canTrade={can_trade}"
        )

        if not can_trade:

            telegram(
                "⚠️ ATI AUTH OK\n\n"
                "❌ canTrade=false\n"
                "🛑 REAL ORDER BLOCKED"
            )

            return False

        return True

    except Exception as e:

        print(
            "🚨 AUTH FAILED:",
            e
        )

        telegram(
            "🚨 ATI AUTH FAILED\n\n"
            f"{e}"
        )

        return False


# ============================================================
# ACCOUNT BALANCE
# ============================================================

def get_usdt_balance():

    try:

        account = signed_request(
            "GET",
            f"{API_ROOT}/account"
        )

        balances = account.get(
            "balances",
            []
        )

        for balance in balances:

            if not isinstance(
                balance,
                dict
            ):
                continue

            asset = str(
                balance.get("asset")
                or ""
            ).upper()

            if asset == "USDT":

                free = D(
                    balance.get("free")
                )

                return free

        return Decimal("0")

    except Exception as e:

        print(
            "BALANCE ERROR:",
            e
        )

        return Decimal("0")


# ============================================================
# MARKETS
# ============================================================

def get_markets():

    data = public_get(
        f"{API_ROOT}/exchangeInfo"
    )

    if isinstance(
        data,
        dict
    ):

        markets = (
            data.get("symbols")
            or data.get("markets")
            or data.get("data")
            or []
        )

    elif isinstance(
        data,
        list
    ):

        markets = data

    else:

        markets = []

    result = []

    for market in markets:

        if not isinstance(
            market,
            dict
        ):
            continue

        symbol = str(
            market.get("symbol")
            or ""
        ).upper().strip()

        tabdeal_symbol = str(
            market.get(
                "tabdealSymbol"
            )
            or ""
        ).upper().strip()

        status = str(
            market.get("status")
            or ""
        ).upper()

        quote = str(
            market.get("quoteAsset")
            or ""
        ).upper()

        is_usdt = (
            symbol.endswith("USDT")
            or tabdeal_symbol.endswith(
                "_USDT"
            )
            or quote == "USDT"
        )

        if not is_usdt:
            continue

        if (
            status
            and status != "TRADING"
        ):
            continue

        if not symbol:
            symbol = (
                tabdeal_symbol
                .replace("_", "")
            )

        if not symbol:
            continue

        result.append(
            market
        )

    unique = {}

    for market in result:

        symbol = get_trade_symbol(
            market
        )

        if symbol:

            unique[symbol] = market

    markets = list(
        unique.values()
    )

    markets.sort(
        key=lambda x:
        get_trade_symbol(x)
    )

    return markets[
        :SCAN_UNIVERSE
    ]


# ============================================================
# SYMBOL
# ============================================================

def get_trade_symbol(
    market
):

    symbol = str(
        market.get("symbol")
        or ""
    ).strip().upper()

    if symbol:
        return symbol

    tabdeal_symbol = str(
        market.get(
            "tabdealSymbol"
        )
        or ""
    ).strip().upper()

    if tabdeal_symbol:

        return (
            tabdeal_symbol
            .replace("_", "")
        )

    return ""


def get_tabdeal_symbol(
    market
):

    tabdeal_symbol = str(
        market.get(
            "tabdealSymbol"
        )
        or ""
    ).strip().upper()

    if tabdeal_symbol:
        return tabdeal_symbol

    symbol = get_trade_symbol(
        market
    )

    if symbol.endswith(
        "USDT"
    ):

        return (
            symbol[:-4]
            + "_USDT"
        )

    return symbol


# ============================================================
# RECENT TRADES
# ============================================================

def get_trades(
    market
):

    symbol = get_trade_symbol(
        market
    )

    tabdeal_symbol = (
        get_tabdeal_symbol(
            market
        )
    )

    if not symbol:

        raise RuntimeError(
            "EMPTY SYMBOL"
        )

    # Official endpoint supports symbol
    # or tabdealSymbol.
    #
    # Use standard symbol first.
    params = {
        "symbol": symbol,
        "limit": TRADE_LIMIT,
    }

    try:

        data = public_get(
            f"{API_ROOT}/trades",
            params
        )

    except Exception as first_error:

        # Fallback to official tabdealSymbol format.
        params = {
            "tabdealSymbol":
                tabdeal_symbol,
            "limit": TRADE_LIMIT,
        }

        try:

            data = public_get(
                f"{API_ROOT}/trades",
                params
            )

        except Exception as second_error:

            raise RuntimeError(
                f"TRADES FAILED | "
                f"symbol={first_error} | "
                f"tabdealSymbol={second_error}"
            )

    if isinstance(
        data,
        dict
    ):

        data = (
            data.get("data")
            or data.get("trades")
            or data.get("results")
            or []
        )

    if not isinstance(
        data,
        list
    ):

        raise RuntimeError(
            "UNEXPECTED TRADES RESPONSE: "
            f"{str(data)[:500]}"
        )

    return data


# ============================================================
# TRADES -> 5M CLOSED CANDLES
# ============================================================

def trades_to_5m(
    trades
):

    buckets = {}

    for trade in trades:

        if not isinstance(
            trade,
            dict
        ):
            continue

        price = D(
            trade.get("price")
        )

        quantity = D(
            trade.get("qty")
        )

        timestamp = (
            trade.get("time")
            or trade.get("timestamp")
        )

        if price <= 0:
            continue

        if quantity < 0:
            quantity = Decimal("0")

        if timestamp is None:
            continue

        try:

            timestamp = int(
                timestamp
            )

        except Exception:

            continue

        bucket = (
            timestamp // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": quantity,
                "trades": 1,
            }

        else:

            candle = buckets[
                bucket
            ]

            candle["high"] = max(
                candle["high"],
                price
            )

            candle["low"] = min(
                candle["low"],
                price
            )

            candle["close"] = price

            candle["volume"] += (
                quantity
            )

            candle["trades"] += 1

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x:
        x["time"]
    )

    if not candles:
        return []

    # Current 5m bucket must not be used.
    current_bucket = (
        local_ms() // 300000
    ) * 300000

    if (
        candles[-1]["time"]
        >= current_bucket
    ):

        candles = candles[:-1]

    return candles


# ============================================================
# SCAN MARKET
# ============================================================

def
