import os
import time
import hmac
import hashlib
import math
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.16
# SERVER TIME AUTH + ORDERED HMAC
# CAN TRADE + BALANCE CHECK
# REAL SPOT BUY - MAX 1 BUY PER RUN
# ============================================================

VERSION = "V40.2.16"

BASE_URL = "https://api1.tabdeal.org"

EXCHANGE_INFO_PATH = "/r/api/v1/exchangeInfo"
TRADES_PATH = "/r/api/v1/trades"
ACCOUNT_PATH = "/r/api/v1/account"
SERVER_TIME_PATH = "/r/api/v1/time"

# Tabdeal order endpoint
ORDER_PATH = "/api/v1/order"

TELEGRAM_SEND_PATH = "https://api.telegram.org/bot{}/sendMessage"

REQUEST_TIMEOUT = 20

ORDER_USDT_MIN = Decimal("0.50")
MAX_BUYS_PER_RUN = 1

# Safety locks
API_AUTH_OK = False
CAN_TRADE = False
SPOT_PERMISSION = False
REAL_BUY_UNLOCKED = False

SERVER_TIME_OFFSET_MS = 0

BUY_COUNT_THIS_RUN = 0


# ============================================================
# ENV
# ============================================================

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()

LIVE_TRADING_RAW = os.getenv(
    "LIVE_TRADING",
    "false"
).strip().lower()

LIVE_TRADING = LIVE_TRADING_RAW in (
    "1",
    "true",
    "yes",
    "on",
)

ORDER_QTY_RAW = os.getenv(
    "ORDER_QTY",
    "2"
).strip()


# ============================================================
# BASIC HELPERS
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def log(message):
    print(message, flush=True)


def safe_decimal(value, default="0"):
    try:
        return Decimal(str(value))
    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ):
        return Decimal(default)


def get_order_usdt():
    amount = safe_decimal(
        ORDER_QTY_RAW,
        "2"
    )

    if amount < ORDER_USDT_MIN:
        return ORDER_USDT_MIN

    return amount


ORDER_USDT = get_order_usdt()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):
        log("⚠️ TELEGRAM CONFIG MISSING")
        return False

    url = TELEGRAM_SEND_PATH.format(
        TELEGRAM_BOT_TOKEN
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            return True

        log(
            f"⚠️ TELEGRAM ERROR "
            f"HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )

    except Exception as exc:
        log(
            f"⚠️ TELEGRAM EXCEPTION: {exc}"
        )

    return False


# ============================================================
# PUBLIC REQUEST
# ============================================================

def public_get(path, params=None):
    url = BASE_URL + path

    response = requests.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    return response.json()


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time_ms():
    global SERVER_TIME_OFFSET_MS

    local_before = int(
        time.time() * 1000
    )

    data = public_get(
        SERVER_TIME_PATH
    )

    local_after = int(
        time.time() * 1000
    )

    server_time = None

    if isinstance(data, dict):
        for key in (
            "serverTime",
            "server_time",
            "time",
            "timestamp",
        ):
            if key in data:
                server_time = data[key]
                break

    elif isinstance(
        data,
        (int, float, str)
    ):
        server_time = data

    if server_time is None:
        raise RuntimeError(
            "SERVER TIME FORMAT UNKNOWN: "
            f"{str(data)[:500]}"
        )

    server_time = int(server_time)

    local_mid = (
        local_before + local_after
    ) // 2

    SERVER_TIME_OFFSET_MS = (
        server_time - local_mid
    )

    log(
        f"🕐 SERVER TIME: {server_time}"
    )

    log(
        f"🕐 TIME OFFSET: "
        f"{SERVER_TIME_OFFSET_MS} ms"
    )

    return server_time


def signed_timestamp():
    local_ms = int(
        time.time() * 1000
    )

    return (
        local_ms
        + SERVER_TIME_OFFSET_MS
    )


# ============================================================
# HMAC SIGNATURE
# ============================================================

def make_signature(params):
    """
    Tabdeal HMAC-SHA256 signature.

    IMPORTANT:
    Parameter insertion order is preserved.

    DO NOT use sorted() here.

    The private request builds:
        timestamp
        recvWindow

    The signature is calculated over exactly
    that insertion order.
    """

    query_parts = []

    for key, value in params.items():

        if key == "signature":
            continue

        query_parts.append(
            f"{key}={value}"
        )

    query = "&".join(
        query_parts
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return signature


# ============================================================
# PRIVATE GET
# ============================================================

def private_get(path, params=None):

    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDEAL API KEY/SECRET MISSING"
        )

    params = dict(
        params or {}
    )

    # IMPORTANT:
    # timestamp MUST be inserted first.
    params["timestamp"] = (
        signed_timestamp()
    )

    # IMPORTANT:
    # recvWindow MUST be inserted second.
    params["recvWindow"] = 10000

    signature = make_signature(
        params
    )

    request_params = dict(
        params
    )

    request_params["signature"] = (
        signature
    )

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type": (
            "application/json"
        ),
    }

    url = BASE_URL + path

    response = requests.get(
        url,
        params=request_params,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:800]}"
        )

    return response.json()


# ============================================================
# PRIVATE POST
# ============================================================

def private_post(path, params=None):

    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDEAL API KEY/SECRET MISSING"
        )

    params = dict(
        params or {}
    )

    # IMPORTANT:
    # timestamp MUST be inserted first.
    params["timestamp"] = (
        signed_timestamp()
    )

    # IMPORTANT:
    # recvWindow MUST be inserted second.
    params["recvWindow"] = 10000

    signature = make_signature(
        params
    )

    request_params = dict(
        params
    )

    request_params["signature"] = (
        signature
    )

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type": (
            "application/x-www-form-urlencoded"
        ),
    }

    url = BASE_URL + path

    response = requests.post(
        url,
        data=request_params,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:800]}"
        )

    return response.json()


# ============================================================
# API AUTH + CAN TRADE + SPOT
# ============================================================

def check_api_auth_and_trading():

    global API_AUTH_OK
    global CAN_TRADE
    global SPOT_PERMISSION
    global REAL_BUY_UNLOCKED

    API_AUTH_OK = False
    CAN_TRADE = False
    SPOT_PERMISSION = False
    REAL_BUY_UNLOCKED = False

    log("")
    log("=" * 60)
    log("🔐 API AUTH CHECK")
    log("=" * 60)

    # --------------------------------------------------------
    # KEY CHECK
    # --------------------------------------------------------

    if not API_KEY:

        reason = (
            "TABDEAL_API_KEY IS EMPTY"
        )

        send_telegram(
            f"🚨 ATI API AUTH FAILED "
            f"{VERSION}\n\n"
            f"❌ {reason}\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        return False

    if not API_SECRET:

        reason = (
            "TABDEAL_API_SECRET IS EMPTY"
        )

        send_telegram(
            f"🚨 ATI API AUTH FAILED "
            f"{VERSION}\n\n"
            f"❌ {reason}\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        return False

    # --------------------------------------------------------
    # AUTH START MESSAGE
    # --------------------------------------------------------

    send_telegram(
        f"🔑 ATI AUTH START {VERSION}\n\n"
        f"✅ API KEY: LOADED\n"
        f"✅ API SECRET: LOADED\n"
        f"🕐 SERVER TIME SYNC: STARTING\n"
        f"🔐 SIGN METHOD: HMAC-SHA256\n"
        f"🔐 PARAM ORDER: "
        f"timestamp → recvWindow\n\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # SERVER TIME
    # --------------------------------------------------------

    try:

        get_server_time_ms()

    except Exception as exc:

        error = str(exc)

        log(
            f"❌ SERVER TIME FAILED: "
            f"{error}"
        )

        send_telegram(
            f"🚨 ATI SERVER TIME FAILED "
            f"{VERSION}\n\n"
            f"❌ {error[:700]}\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        return False

    # --------------------------------------------------------
    # SERVER TIME SYNC OK
    # --------------------------------------------------------

    send_telegram(
        f"🔑 ATI AUTH START {VERSION}\n\n"
        f"✅ API KEY: LOADED\n"
        f"✅ API SECRET: LOADED\n"
        f"✅ SERVER TIME SYNC: OK\n"
        f"🔐 SIGN METHOD: HMAC-SHA256\n"
        f"🔐 PARAM ORDER: "
        f"timestamp → recvWindow\n\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # ACCOUNT AUTH
    # --------------------------------------------------------

    try:

        account = private_get(
            ACCOUNT_PATH
        )

    except Exception as exc:

        error = str(exc)

        log(
            f"❌ ACCOUNT AUTH FAILED: "
            f"{error}"
        )

        # Explicit 1103 handling
        if (
            "1103" in error
            or "Invalid Signature" in error
        ):

            send_telegram(
                f"🚨 ATI API AUTH FAILED "
                f"{VERSION}\n\n"
                f"❌ HTTP 401\n"
                f"❌ CODE: 1103\n"
                f"❌ Invalid Signature\n\n"
                f"🔐 SIGN METHOD: HMAC-SHA256\n"
                f"🔐 PARAM ORDER: "
                f"timestamp → recvWindow\n\n"
                f"🛑 REAL BUY LOCKED\n"
                f"🛑 NO ORDER WAS SENT\n\n"
                f"🕐 {utc_now()}"
            )

        else:

            send_telegram(
                f"🚨 ATI API AUTH FAILED "
                f"{VERSION}\n\n"
                f"❌ ACCOUNT REQUEST FAILED\n"
                f"❌ {error[:700]}\n\n"
                f"🛑 REAL BUY LOCKED\n"
                f"🛑 NO ORDER WAS SENT\n\n"
                f"💰 FIXED ORDER: "
                f"{ORDER_USDT} USDT\n"
                f"🔧 REAL MODE: ON\n"
                f"🕐 {utc_now()}"
            )

        return False

    # --------------------------------------------------------
    # ACCOUNT RESPONSE
    # --------------------------------------------------------

    if not isinstance(
        account,
        dict
    ):

        error = (
            "ACCOUNT RESPONSE IS "
            "NOT JSON OBJECT"
        )

        send_telegram(
            f"🚨 ATI ACCOUNT CHECK FAILED "
            f"{VERSION}\n\n"
            f"❌ {error}\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        return False

    # --------------------------------------------------------
    # AUTH SUCCESS
    # --------------------------------------------------------

    API_AUTH_OK = True

    CAN_TRADE = bool(
        account.get(
            "canTrade",
            False
        )
    )

    account_type = str(
        account.get(
            "accountType",
            ""
        )
    ).upper()

    permissions = account.get(
        "permissions",
        []
    )

    if isinstance(
        permissions,
        str
    ):
        permissions = [
            permissions
        ]

    permission_text = " ".join(
        str(x).upper()
        for x in permissions
    )

    SPOT_PERMISSION = (
        "SPOT" in permission_text
        or "TRADING" in permission_text
        or account_type == "SPOT"
    )

    log("✅ API AUTH: OK")
    log(
        f"🔧 CAN TRADE: "
        f"{CAN_TRADE}"
    )
    log(
        f"📊 ACCOUNT TYPE: "
        f"{account_type}"
    )
    log(
        f"📊 PERMISSIONS: "
        f"{permissions}"
    )

    # --------------------------------------------------------
    # AUTH SUCCESS TELEGRAM
    # --------------------------------------------------------

    send_telegram(
        f"✅ ATI AUTH SUCCESS {VERSION}\n\n"
        f"✅ ACCOUNT REQUEST: OK\n"
        f"✅ API AUTH: OK\n"
        f"🔧 CAN TRADE: "
        f"{CAN_TRADE}\n"
        f"📊 ACCOUNT TYPE: "
        f"{account_type or 'UNKNOWN'}\n"
        f"📊 PERMISSIONS: "
        f"{permissions}\n\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # CAN TRADE CHECK
    # --------------------------------------------------------

    if not CAN_TRADE:

        send_telegram(
            f"🛑 ATI SAFE STOP {VERSION}\n\n"
            f"✅ API AUTH: OK\n"
            f"❌ CAN TRADE: FALSE\n"
            f"📊 ACCOUNT TYPE: "
            f"{account_type or 'UNKNOWN'}\n"
            f"📊 PERMISSIONS: "
            f"{permissions}\n\n"
            f"🚫 REAL BUY IS LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        return False

    # --------------------------------------------------------
    # SPOT CHECK
    # --------------------------------------------------------

    if not SPOT_PERMISSION:

        send_telegram(
            f"🛑 ATI SAFE STOP {VERSION}\n\n"
            f"✅ API AUTH: OK\n"
            f"✅ CAN TRADE: TRUE\n"
            f"❌ SPOT PERMISSION NOT CONFIRMED\n"
            f"📊 ACCOUNT TYPE: "
            f"{account_type or 'UNKNOWN'}\n"
            f"📊 PERMISSIONS: "
            f"{permissions}\n\n"
            f"🚫 REAL BUY IS LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        return False

    # --------------------------------------------------------
    # FINAL UNLOCK
    # --------------------------------------------------------

    REAL_BUY_UNLOCKED = True

    send_telegram(
        f"🔓 ATI REAL BUY UNLOCKED "
        f"{VERSION}\n\n"
        f"✅ API AUTH: OK\n"
        f"✅ CAN TRADE: TRUE\n"
        f"✅ SPOT PERMISSION: OK\n"
        f"📊 ACCOUNT TYPE: "
        f"{account_type or 'UNKNOWN'}\n"
        f"💰 FIXED ORDER: "
        f"{ORDER_USDT} USDT\n"
        f"🔓 REAL BUY UNLOCKED\n\n"
        f"🕐 {utc_now()}"
    )

    return True


# ============================================================
# BALANCE
# ============================================================

def get_free_usdt():

    try:

        account = private_get(
            ACCOUNT_PATH
        )

    except Exception as exc:

        log(
            f"❌ BALANCE CHECK FAILED: "
            f"{exc}"
        )

        return None

    balances = account.get(
        "balances",
        []
    )

    if not isinstance(
        balances,
        list
    ):
        return None

    for item in balances:

        if not isinstance(
            item,
            dict
        ):
            continue

        asset = str(
            item.get(
                "asset",
                item.get(
                    "currency",
                    ""
                )
            )
        ).upper()

        if asset == "USDT":

            free = safe_decimal(
                item.get(
                    "free",
                    item.get(
                        "available",
                        "0"
                    )
                )
            )

            return free

    return Decimal("0")


def check_balance_before_buy():

    free_usdt = get_free_usdt()

    if free_usdt is None:

        send_telegram(
            f"🛑 ATI SAFE STOP {VERSION}\n\n"
            f"❌ USDT BALANCE CHECK FAILED\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        return False

    log(
        f"💰 FREE USDT: "
        f"{free_usdt}"
    )

    log(
        f"💰 REQUIRED: "
        f"{ORDER_USDT}"
    )

    required = (
        ORDER_USDT
        * Decimal("1.01")
    )

    if free_usdt < required:

        send_telegram(
            f"🛑 ATI SAFE STOP {VERSION}\n\n"
            f"❌ INSUFFICIENT FREE USDT\n"
            f"💰 FREE USDT: "
            f"{free_usdt}\n"
            f"💰 REQUIRED: "
            f"~{required:.8f}\n\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return False

    send_telegram(
        f"💰 ATI BALANCE CHECK "
        f"{VERSION}\n\n"
        f"✅ FREE USDT: "
        f"{free_usdt}\n"
        f"✅ REQUIRED: "
        f"{ORDER_USDT} USDT\n"
        f"✅ BALANCE OK\n\n"
        f"🕐 {utc_now()}"
    )

    return True


# ============================================================
# EXCHANGE INFO
# ============================================================

def load_markets():

    data = public_get(
        EXCHANGE_INFO_PATH
    )

    symbols = data.get(
        "symbols",
        []
    )

    if not isinstance(
        symbols,
        list
    ):
        raise RuntimeError(
            "EXCHANGE INFO SYMBOLS INVALID"
        )

    result = []

    for symbol in symbols:

        if not isinstance(
            symbol,
            dict
        ):
            continue

        name = str(
            symbol.get(
                "symbol",
                ""
            )
        ).upper()

        status = str(
            symbol.get(
                "status",
                "TRADING"
            )
        ).upper()

        quote = str(
            symbol.get(
                "quoteAsset",
                ""
            )
        ).upper()

        base = str(
            symbol.get(
                "baseAsset",
                ""
            )
        ).upper()

        if not name.endswith(
            "USDT"
        ):
            continue

        if quote != "USDT":
            continue

        if status not in (
            "TRADING",
            "ENABLED",
            "",
        ):
            continue

        symbol["_baseAsset"] = base

        result.append(
            symbol
        )

    return result


# ============================================================
# SYMBOL FILTERS
# ============================================================

def get_symbol_filters(
    symbol_info
):

    min_qty = Decimal("0")
    step_size = Decimal("0")
    min_notional = Decimal("1")

    filters = symbol_info.get(
        "filters",
        []
    )

    if not isinstance(
        filters,
        list
    ):
        return (
            min_qty,
            step_size,
            min_notional
        )

    for f in filters:

        if not isinstance(
            f,
            dict
        ):
            continue

        filter_type = str(
            f.get(
                "filterType",
                ""
            )
        ).upper()

        if filter_type == "LOT_SIZE":

            min_qty = safe_decimal(
                f.get(
                    "minQty",
                    "0"
                )
            )

            step_size = safe_decimal(
                f.get(
                    "stepSize",
                    "0"
                )
            )

        elif filter_type in (
            "MIN_NOTIONAL",
            "NOTIONAL",
        ):

            min_notional = safe_decimal(
                f.get(
                    "minNotional",
                    "1"
                )
            )

    return (
        min_qty,
        step_size,
        min_notional
    )


def floor_to_step(
    value,
    step
):

    if step <= 0:
        return value

    units = (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    )

    return units * step


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):

    data = public_get(
        TRADES_PATH,
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if not isinstance(
        data,
        list
    ):
        return []

    return data


# ============================================================
# BUILD 5M CLOSED CANDLES
# ============================================================

def build_5m_candles(
    trades
):

    buckets = {}

    for trade in trades:

        if not isinstance(
            trade,
            dict
        ):
            continue

        price = safe_decimal(
            trade.get(
                "price",
                trade.get(
                    "p",
                    "0"
                )
            )
        )

        qty = safe_decimal(
            trade.get(
                "qty",
                trade.get(
                    "quantity",
                    trade.get(
                        "q",
                        "0"
                    )
                )
            )
        )

        timestamp = trade.get(
            "time",
            trade.get(
                "timestamp",
                trade.get(
                    "T"
                )
            )
        )

        if (
            price <= 0
            or qty <= 0
            or timestamp is None
        ):
            continue

        try:
            ts = int(timestamp)
        except Exception:
            continue

        bucket = (
            ts // 300000
        )

        if bucket not in buckets:

            buckets[bucket] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": Decimal("0"),
            }

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

        candle["volume"] += qty

    if not buckets:
        return []

    ordered = sorted(
        buckets.items()
    )

    now_bucket = (
        int(time.time() * 1000)
        // 300000
    )

    closed = []

    for bucket, candle in ordered:

        if bucket < now_bucket:
            closed.append(
                candle
            )

    return closed


# ============================================================
# STRATEGY
# ============================================================

def percent_change(
    old,
    new
):

    if old <= 0:
        return Decimal("0")

    return (
        (new - old)
        / old
    ) * Decimal("100")


def score_symbol(
    candles
):

    if len(candles) < 20:
        return None

    closes = [
        safe_decimal(
            c["close"]
        )
        for c in candles
    ]

    highs = [
        safe_decimal(
            c["high"]
        )
        for c in candles
    ]

    lows = [
        safe_decimal(
            c["low"]
        )
        for c in candles
    ]

    volumes = [
        safe_decimal(
            c["volume"]
        )
        for c in candles
    ]

    price = closes[-1]

    if price <= 0:
        return None

    move_5m = percent_change(
        closes[-2],
        closes[-1]
    )

    move_15m = percent_change(
        closes[-4],
        closes[-1]
    )

    move_1h = percent_change(
        closes[-13],
        closes[-1]
    )

    recent_high = max(
        highs[-13:-1]
    )

    recent_low = min(
        lows[-13:-1]
    )

    breakout = (
        price > recent_high
        if recent_high > 0
        else False
    )

    volume_recent = (
        volumes[-1]
    )

    volume_old = (
        sum(volumes[-6:-1])
        / Decimal("5")
    )

    volume_boost = (
        volume_recent
        / volume_old
        if volume_old > 0
        else Decimal("0")
    )

    score = 0

    if move_5m > Decimal("0.20"):
        score += 2

    if move_5m > Decimal("0.50"):
        score += 1

    if move_15m > Decimal("0.50"):
        score += 2

    if move_15m > Decimal("1.00"):
        score += 1

    if move_1h > Decimal("1.00"):
        score += 2

    if move_1h > Decimal("2.00"):
        score += 1

    if breakout:
        score += 4

    if volume_boost > Decimal("1.20"):
        score += 2

    if volume_boost > Decimal("1.50"):
        score += 1

    # Anti-chase
    if move_5m > Decimal("7"):
        score -= 4

    if move_5m > Decimal("12"):
        score -= 6

    # Higher-low structure
    if (
        lows[-1] > lows[-4]
        and lows[-4] > lows[-7]
    ):
        score += 2

    return {
        "price": price,
        "score": score,
        "move_5m": move_5m,
        "move_15m": move_15m,
        "move_1h": move_1h,
        "breakout": breakout,
        "volume_boost": volume_boost,
        "recent_high": recent_high,
        "recent_low": recent_low,
    }


# ============================================================
# SL / TP
# ============================================================

def calculate_sl_tp(
    price,
    recent_low
):

    if recent_low <= 0:

        recent_low = (
            price
            * Decimal("0.985")
        )

    risk = (
        price - recent_low
    )

    if risk <= 0:

        risk = (
            price
            * Decimal("0.01")
        )

    sl = recent_low

    if sl >= price:

        sl = (
            price
            * Decimal("0.99")
        )

    tp1 = (
        price
        + risk * Decimal("1.5")
    )

    tp2 = (
        price
        + risk * Decimal("2.5")
    )

    return (
        sl,
        tp1,
        tp2
    )


# ============================================================
# ORDER QUANTITY
# ============================================================

def calculate_order_quantity(
    symbol_info,
    price
):

    if price <= 0:
        return (
            None,
            "INVALID PRICE"
        )

    (
        min_qty,
        step_size,
        min_notional,
    ) = get_symbol_filters(
        symbol_info
    )

    if ORDER_USDT < min_notional:

        return (
            None,
            f"ORDER VALUE "
            f"{ORDER_USDT} < "
            f"MIN_NOTIONAL "
            f"{min_notional}"
        )

    raw_qty = (
        ORDER_USDT / price
    )

    if step_size > 0:

        quantity = floor_to_step(
            raw_qty,
            step_size
        )

    else:

        quantity = raw_qty

    if quantity <= 0:

        return (
            None,
            "QUANTITY IS ZERO"
        )

    if (
        min_qty > 0
        and quantity < min_qty
    ):

        return (
            None,
            f"QUANTITY {quantity} < "
            f"MIN_QTY {min_qty}"
        )

    order_value = (
        quantity * price
    )

    if order_value < min_notional:

        return (
            None,
            f"ORDER VALUE "
            f"{order_value} < "
            f"MIN_NOTIONAL "
            f"{min_notional}"
        )

    return (
        quantity,
        None
    )


# ============================================================
# REAL MARKET BUY
# ============================================================

def buy_market(
    symbol,
    quantity
):

    global BUY_COUNT_THIS_RUN
    global REAL_BUY_UNLOCKED

    if not LIVE_TRADING:

        return (
            False,
            "REAL MODE OFF"
        )

    if not REAL_BUY_UNLOCKED:

        return (
            False,
            "REAL BUY LOCKED"
        )

    if (
        BUY_COUNT_THIS_RUN
        >= MAX_BUYS_PER_RUN
    ):

        return (
            False,
            "MAX BUY PER RUN REACHED"
        )

    params = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quantity": format(
            quantity,
            "f"
        ),
    }

    log("")
    log("=" * 60)
    log("🚨 REAL BUY")
    log("=" * 60)
    log(
        f"🪙 SYMBOL: {symbol}"
    )
    log(
        f"📦 QUANTITY: {quantity}"
    )
    log(
        f"💰 ORDER: "
        f"{ORDER_USDT} USDT"
    )

    try:

        result = private_post(
            ORDER_PATH,
            params
        )

        BUY_COUNT_THIS_RUN += 1

        send_telegram(
            f"🟢 REAL BUY SUCCESS "
            f"{VERSION}\n\n"
            f"🪙 {symbol}\n"
            f"📦 QUANTITY: {quantity}\n"
            f"💰 FIXED ORDER: "
            f"{ORDER_USDT} USDT\n"
            f"🆔 ORDER ID: "
            f"{result.get('orderId', 'N/A')}\n\n"
            f"🕐 {utc_now()}"
        )

        return (
            True,
            result
        )

    except Exception as exc:

        error = str(exc)

        # Authentication errors lock
        # real trading immediately.
        if (
            "401" in error
            or "1100" in error
            or "1101" in error
            or "1103" in error
            or "Invalid Signature"
            in error
            or "Access denied"
            in error
        ):

            REAL_BUY_UNLOCKED = False

            send_telegram(
                f"🛑 ATI REAL BUY LOCKED "
                f"{VERSION}\n\n"
                f"🪙 {symbol}\n"
                f"❌ AUTHENTICATION ERROR\n"
                f"❌ {error[:700]}\n\n"
                f"🛑 NO MORE ORDERS THIS RUN\n"
                f"🕐 {utc_now()}"
            )

            return (
                False,
                error
            )

        send_telegram(
            f"🚨 REAL TRADE ERROR "
            f"{VERSION}\n\n"
            f"🪙 {symbol}\n"
            f"❌ {error[:700]}\n\n"
            f"🕐 {utc_now()}"
        )

        return (
            False,
            error
        )


# ============================================================
# SCAN
# ============================================================

def scan_markets(
    markets
):

    candidates = []

    total = len(
        markets
    )

    log("")
    log("=" * 60)
    log("📊 SCAN STARTING")
    log(
        f"📊 USDT MARKETS: {total}"
    )
    log("=" * 60)

    for index, symbol_info in enumerate(
        markets,
        1
    ):

        symbol = str(
            symbol_info.get(
                "symbol",
                ""
            )
        ).upper()

        if not symbol:
            continue

        try:

            trades = get_trades(
                symbol
            )

            candles = build_5m_candles(
                trades
            )

            result = score_symbol(
                candles
            )

            if result is None:
                continue

            result["symbol"] = (
                symbol
            )

            result["symbol_info"] = (
                symbol_info
            )

            candidates.append(
                result
            )

        except Exception as exc:

            log(
                f"⚠️ {symbol}: "
                f"{str(exc)[:160]}"
            )

        if index % 50 == 0:

            log(
                f"📊 PROGRESS: "
                f"{index}/{total}"
            )

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["move_1h"],
            x["move_15m"],
        ),
        reverse=True,
    )

    return candidates


# ============================================================
# CANDIDATE MESSAGE
# ============================================================

def send_top_candidates(
    candidates
):

    if not candidates:

        send_telegram(
            f"📊 ATI SCAN {VERSION}\n\n"
            f"❌ NO VALID CANDIDATES\n\n"
            f"💰 FIXED ORDER: "
            f"{ORDER_USDT} USDT\n"
            f"🔧 REAL MODE: "
            f"{'ON' if LIVE_TRADING else 'OFF'}\n"
            f"🕐 {utc_now()}"
        )

        return

    lines = [
        f"📊 ATI TOP CANDIDATES "
        f"{VERSION}",
        "",
    ]

    for index, item in enumerate(
        candidates[:10],
        1
    ):

        lines.append(
            f"{index}. "
            f"{item['symbol']} "
            f"| SCORE "
            f"{item['score']} "
            f"| 5m "
            f"{item['move_5m']:.2f}% "
            f"| 15m "
            f"{item['move_15m']:.2f}% "
            f"| 1h "
            f"{item['move_1h']:.2f}%"
        )

    lines.extend(
        [
            "",
            f"💰 FIXED ORDER: "
            f"{ORDER_USDT} USDT",
            f"🔧 REAL MODE: "
            f"{'ON' if LIVE_TRADING else 'OFF'}",
            f"🕐 {utc_now()}",
        ]
    )

    send_telegram(
        "\n".join(lines)
    )


# ============================================================
# EXECUTE BEST BUY
# ============================================================

def execute_best_buy(
    candidates
):

    if not candidates:
        return

    if not LIVE_TRADING:

        log(
            "ℹ️ REAL MODE OFF - "
            "NO REAL BUY"
        )

        return

    if not REAL_BUY_UNLOCKED:

        log(
            "🛑 REAL BUY LOCKED"
        )

        return

    if (
        BUY_COUNT_THIS_RUN
        >= MAX_BUYS_PER_RUN
    ):
        return

    for item in candidates:

        if item["score"] < 8:
            continue

        symbol = item[
            "symbol"
        ]

        symbol_info = item[
            "symbol_info"
        ]

        price = item[
            "price"
        ]

        quantity, error = (
            calculate_order_quantity(
                symbol_info,
                price
            )
        )

        if quantity is None:

            send_telegram(
                f"⚠️ ORDER SKIPPED "
                f"{VERSION}\n\n"
                f"🪙 {symbol}\n"
                f"💰 FIXED AMOUNT: "
                f"{ORDER_USDT} USDT\n"
                f"❌ {error}\n"
                f"ℹ️ No order was sent.\n\n"
                f"🕐 {utc_now()}"
            )

            continue

        sl, tp1, tp2 = (
            calculate_sl_tp(
                price,
                item["recent_low"]
            )
        )

        send_telegram(
            f"🚨 NEW ATI BUY SIGNAL "
            f"{VERSION}\n\n"
            f"🟢 CONFIRMED BUY\n"
            f"🪙 {symbol}\n"
            f"💰 PRICE: {price}\n"
            f"📊 SCORE: "
            f"{item['score']}\n"
            f"📈 5m: "
            f"{item['move_5m']:.2f}%\n"
            f"📈 15m: "
            f"{item['move_15m']:.2f}%\n"
            f"📈 1h: "
            f"{item['move_1h']:.2f}%\n"
            f"📦 QUANTITY: "
            f"{quantity}\n"
            f"💵 ORDER: "
            f"{ORDER_USDT} USDT\n"
            f"🛑 SL: {sl}\n"
            f"🎯 TP1: {tp1}\n"
            f"🎯 TP2: {tp2}\n\n"
            f"🔧 REAL MODE: ON\n"
            f"🕐 {utc_now()}"
        )

        buy_market(
            symbol,
            quantity
        )

        # Maximum one attempt.
        break


# ============================================================
# FINAL HEARTBEAT
# ============================================================

def send_final_status(
    candidates,
    scan_seconds
):

    send_telegram(
        f"⚡ ATI HEARTBEAT "
        f"{VERSION}\n\n"
        f"📊 CANDIDATES: "
        f"{len(candidates)}\n"
        f"🚨 BUY THIS RUN: "
        f"{BUY_COUNT_THIS_RUN}\n"
        f"🔐 API AUTH: "
        f"{'OK' if API_AUTH_OK else 'FAILED'}\n"
        f"🔧 CAN TRADE: "
        f"{'TRUE' if CAN_TRADE else 'FALSE'}\n"
        f"📊 SPOT: "
        f"{'OK' if SPOT_PERMISSION else 'NO'}\n"
        f"🔓 REAL BUY: "
        f"{'UNLOCKED' if REAL_BUY_UNLOCKED else 'LOCKED'}\n"
        f"💰 ORDER: "
        f"{ORDER_USDT} USDT\n"
        f"🔧 REAL MODE: "
        f"{'ON' if LIVE_TRADING else 'OFF'}\n"
        f"⏱ SCAN TIME: "
        f"{scan_seconds:.1f}s\n"
        f"🕐 {utc_now()}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    global REAL_BUY_UNLOCKED

    REAL_BUY_UNLOCKED = False

    log("")
    log("=" * 70)
    log(
        f"⚡ ATI CRYPTO BOT "
        f"{VERSION}"
    )
    log("=" * 70)

    send_telegram(
        f"⚡ ATI CRYPTO BOT "
        f"{VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED CANDLE: YES\n"
        f"💰 FIXED ORDER: "
        f"{ORDER_USDT} USDT\n"
        f"🔧 REAL MODE: "
        f"{'ON' if LIVE_TRADING else 'OFF'}\n"
        f"🔐 SIGN: "
        f"HMAC-SHA256\n"
        f"🔐 PARAM ORDER: "
        f"timestamp → recvWindow\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # REAL MODE PRECHECK
    # --------------------------------------------------------

    if LIVE_TRADING:

        if not check_api_auth_and_trading():

            log(
                "🛑 SAFE STOP - "
                "AUTH/TRADING CHECK FAILED"
            )

            send_telegram(
                f"🛑 ATI SAFE STOP "
                f"{VERSION}\n\n"
                f"🚫 REAL BUY IS LOCKED\n"
                f"❌ API AUTH / "
                f"TRADING CHECK FAILED\n"
                f"🛑 NO ORDER WAS SENT\n\n"
                f"💰 FIXED ORDER: "
                f"{ORDER_USDT} USDT\n"
                f"🔧 REAL MODE: ON\n"
                f"🕐 {utc_now()}"
            )

            return

        if not check_balance_before_buy():

            log(
                "🛑 SAFE STOP - "
                "BALANCE CHECK FAILED"
            )

            return

    # --------------------------------------------------------
    # MARKET LOAD
    # --------------------------------------------------------

    try:

        markets = load_markets()

    except Exception as exc:

        error = str(exc)

        log(
            f"❌ EXCHANGE INFO FAILED: "
            f"{error}"
        )

        send_telegram(
            f"🚨 ATI EXCHANGE INFO ERROR "
            f"{VERSION}\n\n"
            f"❌ {error[:700]}\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        return

    log(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    start = time.time()

    candidates = scan_markets(
        markets
    )

    elapsed = (
        time.time() - start
    )

    log("")
    log("=" * 60)
    log("✅ SCAN FINISHED")
    log(
        f"📊 MARKETS: "
        f"{len(markets)}"
    )
    log(
        f"📊 CANDIDATES: "
        f"{len(candidates)}"
    )
    log(
        f"⏱ TIME: "
        f"{elapsed:.1f}s"
    )
    log("=" * 60)

    send_top_candidates(
        candidates
    )

    # --------------------------------------------------------
    # REAL BUY
    # --------------------------------------------------------

    execute_best_buy(
        candidates
    )

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    send_final_status(
        candidates,
        elapsed
    )

    log("")
    log("=" * 70)
    log(
        f"✅ ATI {VERSION} FINISHED"
    )
    log(
        f"🚨 REAL BUY THIS RUN: "
        f"{BUY_COUNT_THIS_RUN}"
    )
    log("=" * 70)


if __name__ == "__main__":
    main()
