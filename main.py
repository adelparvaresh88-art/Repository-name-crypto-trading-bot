import os
import time
import json
import hmac
import hashlib
import math
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.21
# TABDEAL SPOT
#
# AUTHENTICATION FIX:
# EXACTLY MIRRORS OFFICIAL TABDEAL PYTHON SDK
#
# timestamp = time.time() * 1000
# recvWindow = optional
# query = urlencode(data)
# signature = HMAC-SHA256(query, API_SECRET)
#
# IMPORTANT:
# REAL BUY IS LOCKED UNTIL AUTHENTICATION PASSES
# ============================================================

VERSION = "V40.2.21"

BASE_URL = "https://api1.tabdeal.org"

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

# Backward compatibility
if not API_KEY:
    API_KEY = os.getenv("TABDIL_API_KEY", "").strip()

if not API_SECRET:
    API_SECRET = os.getenv("TABDIL_API_SECRET", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "false")
    .strip()
    .lower()
    == "true"
)

ORDER_USDT = Decimal(
    os.getenv("ORDER_USDT", "2")
)

RECV_WINDOW = os.getenv(
    "RECV_WINDOW", ""
).strip()

TIMEOUT = 20

MAX_SCAN_MARKETS = 15

AUTH_ENDPOINT = "/api/v1/account"

REAL_BUY_LOCKED = True

session = requests.Session()

session.headers.update(
    {
        "User-Agent": (
            "ATI-Crypto-Bot/"
            + VERSION
        ),
        "Accept": "application/json",
    }
)


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
# TELEGRAM
# ============================================================

def telegram(message):

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):
        return False

    try:

        url = (
            "https://api.telegram.org/bot"
            + TELEGRAM_BOT_TOKEN
            + "/sendMessage"
        )

        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )

        return response.ok

    except Exception:

        return False


# ============================================================
# PUBLIC GET
# ============================================================

def public_get(path, params=None):

    response = session.get(
        BASE_URL + path,
        params=params or {},
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# OFFICIAL TABDEAL AUTHENTICATION
#
# This is intentionally copied in structure from the official
# Tabdeal Python SDK.
#
# Official SDK:
#
# timestamp = time.time() * 1000
# data.update({"timestamp": timestamp})
# data_query = urlencode(data)
# signature = hmac.new(
#     secret,
#     data_query,
#     hashlib.sha256
# ).hexdigest()
# data.update({"signature": signature})
#
# ============================================================

def build_signed_data(params=None):

    if not API_KEY:
        raise RuntimeError(
            "TABDEAL API KEY IS MISSING"
        )

    if not API_SECRET:
        raise RuntimeError(
            "TABDEAL API SECRET IS MISSING"
        )

    data = {}

    if params:
        data.update(params)

    # Never reuse authentication fields
    data.pop("signature", None)
    data.pop("timestamp", None)
    data.pop("recvWindow", None)

    # IMPORTANT:
    # Do NOT convert to int.
    # Official SDK uses time.time() * 1000.
    timestamp = time.time() * 1000

    data.update(
        {
            "timestamp": timestamp
        }
    )

    if RECV_WINDOW:
        try:
            data.update(
                {
                    "recvWindow": int(
                        RECV_WINDOW
                    )
                }
            )
        except ValueError:
            data.update(
                {
                    "recvWindow": RECV_WINDOW
                }
            )

    # EXACT OFFICIAL METHOD
    data_query = urlencode(data)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        data_query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    data.update(
        {
            "signature": signature
        }
    )

    return data, data_query


# ============================================================
# SIGNED GET
# ============================================================

def signed_get(path, params=None):

    data, signed_query = (
        build_signed_data(params)
    )

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    response = session.get(
        BASE_URL + path,
        params=data,
        headers=headers,
        timeout=TIMEOUT,
    )

    return response, signed_query


# ============================================================
# SIGNED POST
# ============================================================

def signed_post(path, params=None):

    data, signed_query = (
        build_signed_data(params)
    )

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    response = session.post(
        BASE_URL + path,
        data=data,
        headers=headers,
        timeout=TIMEOUT,
    )

    return response, signed_query


# ============================================================
# API ERROR
# ============================================================

def get_api_error(response):

    try:

        data = response.json()

        if isinstance(data, dict):

            code = data.get(
                "code",
                ""
            )

            message = data.get(
                "msg",
                data.get(
                    "message",
                    ""
                ),
            )

            return (
                f"CODE: {code}\n"
                f"MSG: {message}"
            )

        return str(data)

    except Exception:

        text = (
            response.text
            if response.text
            else ""
        )

        return text[:1000]


# ============================================================
# AUTHENTICATION TEST
#
# Uses the SAME private account endpoint that the official
# Tabdeal Spot SDK exposes.
# ============================================================

def authenticate():

    telegram(
        f"🔐 ATI API AUTH TEST {VERSION}\n\n"
        f"📡 PRIVATE ENDPOINT: account\n"
        f"🔐 HMAC-SHA256\n"
        f"🔢 TIMESTAMP: time.time()*1000\n"
        f"🔐 urlencode(data)\n"
        f"🕐 {utc_now()}"
    )

    try:

        response, signed_query = signed_get(
            AUTH_ENDPOINT
        )

    except Exception as error:

        telegram(
            f"🚨 ATI API CONNECTION FAILED "
            f"{VERSION}\n\n"
            f"❌ {type(error).__name__}\n"
            f"❌ {error}\n\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return False

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    if response.status_code < 400:

        telegram(
            f"✅ ATI API AUTH OK {VERSION}\n\n"
            f"🔐 HMAC-SHA256: OK\n"
            f"🔢 TIMESTAMP: OK\n"
            f"🔐 URLENCODE: OK\n"
            f"🔑 API KEY: ACCEPTED\n"
            f"📡 PRIVATE ACCOUNT: HTTP "
            f"{response.status_code}\n"
            f"🟢 AUTHENTICATED\n\n"
            f"🛑 REAL BUY STILL LOCKED\n"
            f"🕐 {utc_now()}"
        )

        return True

    # --------------------------------------------------------
    # 401 / 1103
    # --------------------------------------------------------

    error = get_api_error(
        response
    )

    if (
        response.status_code == 401
        or "1103" in error
    ):

        telegram(
            f"🚨 ATI API AUTH FAILED "
            f"{VERSION}\n\n"
            f"❌ HTTP {response.status_code}\n"
            f"❌ {error}\n\n"
            f"🔐 METHOD: HMAC-SHA256\n"
            f"🔢 TIMESTAMP: time.time()*1000\n"
            f"🔐 QUERY: urlencode(data)\n"
            f"🔑 HEADER: X-MBX-APIKEY\n\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return False

    # --------------------------------------------------------
    # OTHER PRIVATE API ERROR
    # --------------------------------------------------------

    telegram(
        f"🚨 ATI PRIVATE API ERROR "
        f"{VERSION}\n\n"
        f"❌ HTTP {response.status_code}\n"
        f"❌ {error}\n\n"
        f"🛑 REAL BUY LOCKED\n"
        f"🛑 NO ORDER WAS SENT\n"
        f"🕐 {utc_now()}"
    )

    return False


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    return public_get(
        "/r/api/v1/exchangeInfo"
    )


# ============================================================
# MARKET LIST
# ============================================================

def get_usdt_markets():

    data = get_exchange_info()

    if not isinstance(
        data,
        dict
    ):
        return []

    symbols = data.get(
        "symbols",
        []
    )

    if not isinstance(
        symbols,
        list
    ):
        return []

    markets = []

    for item in symbols:

        if not isinstance(
            item,
            dict
        ):
            continue

        symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).upper()

        if not symbol:
            continue

        if not symbol.endswith(
            "USDT"
        ):
            continue

        status = str(
            item.get(
                "status",
                "TRADING"
            )
        ).upper()

        if status not in (
            "TRADING",
            "ACTIVE",
            "1",
        ):
            continue

        markets.append(item)

    return markets


# ============================================================
# SYMBOL
# ============================================================

def get_symbol(item):

    return str(
        item.get(
            "symbol",
            ""
        )
    ).upper()


# ============================================================
# FILTER
# ============================================================

def find_filter(
    item,
    filter_names
):

    filters = item.get(
        "filters",
        []
    )

    if not isinstance(
        filters,
        list
    ):
        return {}

    for item_filter in filters:

        if not isinstance(
            item_filter,
            dict
        ):
            continue

        filter_type = str(
            item_filter.get(
                "filterType",
                ""
            )
        ).upper()

        if (
            filter_type
            in filter_names
        ):
            return item_filter

    return {}


# ============================================================
# STEP SIZE
# ============================================================

def get_step_size(item):

    f = find_filter(
        item,
        {
            "LOT_SIZE",
            "MARKET_LOT_SIZE",
        },
    )

    value = (
        f.get("stepSize")
        or item.get("stepSize")
        or "0.00000001"
    )

    try:

        return Decimal(
            str(value)
        )

    except Exception:

        return Decimal(
            "0.00000001"
        )


# ============================================================
# MIN QTY
# ============================================================

def get_min_qty(item):

    f = find_filter(
        item,
        {
            "LOT_SIZE",
            "MARKET_LOT_SIZE",
        },
    )

    value = (
        f.get("minQty")
        or item.get("minQty")
        or "0"
    )

    try:

        return Decimal(
            str(value)
        )

    except Exception:

        return Decimal("0")


# ============================================================
# MIN NOTIONAL
# ============================================================

def get_min_notional(item):

    f = find_filter(
        item,
        {
            "MIN_NOTIONAL",
            "NOTIONAL",
        },
    )

    value = (
        f.get("minNotional")
        or f.get("notional")
        or item.get("minNotional")
        or "0"
    )

    try:

        return Decimal(
            str(value)
        )

    except Exception:

        return Decimal("0")


# ============================================================
# DECIMAL FLOOR
# ============================================================

def floor_to_step(
    value,
    step
):

    if step <= 0:
        return value

    try:

        units = (
            value / step
        ).to_integral_value(
            rounding=ROUND_DOWN
        )

        return units * step

    except Exception:

        return value


# ============================================================
# DECIMAL FORMAT
# ============================================================

def decimal_string(value):

    result = format(
        value,
        "f"
    )

    if "." in result:

        result = (
            result
            .rstrip("0")
            .rstrip(".")
        )

    return result or "0"


# ============================================================
# RECENT TRADES
# ============================================================

def get_recent_trades(
    symbol
):

    try:

        data = public_get(
            "/r/api/v1/trades",
            {
                "symbol": symbol,
                "limit": 1000,
            },
        )

        if isinstance(
            data,
            list
        ):
            return data

        if isinstance(
            data,
            dict
        ):

            for key in (
                "data",
                "trades",
                "result",
            ):

                value = data.get(
                    key
                )

                if isinstance(
                    value,
                    list
                ):
                    return value

    except Exception:

        return []

    return []


# ============================================================
# TRADE PRICE
# ============================================================

def extract_price(trade):

    if not isinstance(
        trade,
        dict
    ):
        return None

    for key in (
        "price",
        "p",
    ):

        if key in trade:

            try:

                value = float(
                    trade[key]
                )

                if value > 0:
                    return value

            except Exception:
                pass

    return None


# ============================================================
# SIMPLE MOMENTUM ANALYSIS
# ============================================================

def analyze_market(
    item
):

    symbol = get_symbol(
        item
    )

    if not symbol:
        return None

    trades = get_recent_trades(
        symbol
    )

    prices = []

    for trade in trades:

        price = extract_price(
            trade
        )

        if (
            price is not None
            and price > 0
        ):
            prices.append(
                price
            )

    if len(prices) < 20:
        return None

    # API can return newest -> oldest
    if prices[0] > prices[-1]:

        prices.reverse()

    current = prices[-1]

    lookback = min(
        60,
        len(prices)
    )

    old_price = prices[
        -lookback
    ]

    if old_price <= 0:
        return None

    move = (
        (
            current
            - old_price
        )
        / old_price
        * 100
    )

    short_n = min(
        20,
        len(prices)
    )

    short_old = prices[
        -short_n
    ]

    if short_old <= 0:
        return None

    short_move = (
        (
            current
            - short_old
        )
        / short_old
        * 100
    )

    up = 0
    down = 0

    start = max(
        1,
        len(prices) - 30
    )

    for i in range(
        start,
        len(prices)
    ):

        if (
            prices[i]
            > prices[i - 1]
        ):
            up += 1

        elif (
            prices[i]
            < prices[i - 1]
        ):
            down += 1

    total = up + down

    pressure = (
        up / total * 100
        if total > 0
        else 50
    )

    score = 0

    if move > 0:
        score += 4

    if move >= 1:
        score += 2

    if move >= 2:
        score += 2

    if short_move > 0:
        score += 2

    if short_move >= 0.5:
        score += 2

    if pressure >= 55:
        score += 2

    if pressure >= 65:
        score += 2

    # Anti-chase
    if short_move >= 8:
        score -= 5

    if move <= -2:
        score -= 3

    return {
        "symbol": symbol,
        "price": current,
        "move": move,
        "short_move": short_move,
        "pressure": pressure,
        "score": score,
    }


# ============================================================
# SCAN
# ============================================================

def scan_markets():

    telegram(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: OK\n"
        f"🔐 PRIVATE AUTH: PASSED\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED CANDLE: YES\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"🛡 REAL BUY: LOCKED\n"
        f"🕐 {utc_now()}"
    )

    try:

        markets = get_usdt_markets()

    except Exception as error:

        telegram(
            f"🚨 EXCHANGE INFO ERROR "
            f"{VERSION}\n\n"
            f"❌ {type(error).__name__}\n"
            f"❌ {error}\n"
            f"🕐 {utc_now()}"
        )

        return []

    telegram(
        f"📊 ATI MARKET SCAN "
        f"{VERSION}\n\n"
        f"🟢 USDT MARKETS: "
        f"{len(markets)}\n"
        f"🔎 DEEP SCAN: "
        f"{MAX_SCAN_MARKETS}\n"
        f"🕐 {utc_now()}"
    )

    results = []

    # Keep GitHub Actions runtime controlled.
    selected = markets[
        :MAX_SCAN_MARKETS
    ]

    for item in selected:

        try:

            result = analyze_market(
                item
            )

            if result:
                results.append(
                    result
                )

        except Exception:

            continue

    results.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    return results


# ============================================================
# ORDER QUANTITY
# ============================================================

def prepare_quantity(
    item,
    price
):

    try:

        price_decimal = Decimal(
            str(price)
        )

        if price_decimal <= 0:

            return (
                None,
                "INVALID PRICE"
            )

        quantity = (
            ORDER_USDT
            / price_decimal
        )

        step = get_step_size(
            item
        )

        min_qty = get_min_qty(
            item
        )

        min_notional = (
            get_min_notional(
                item
            )
        )

        quantity = floor_to_step(
            quantity,
            step
        )

        if quantity <= 0:

            return (
                None,
                "QUANTITY ZERO"
            )

        if (
            min_qty > 0
            and quantity < min_qty
        ):

            return (
                None,
                (
                    f"quantity "
                    f"{quantity} < "
                    f"minQty "
                    f"{min_qty}"
                ),
            )

        notional = (
            quantity
            * price_decimal
        )

        if (
            min_notional > 0
            and notional < min_notional
        ):

            return (
                None,
                (
                    f"order value "
                    f"{notional} < "
                    f"MIN_NOTIONAL "
                    f"{min_notional}"
                ),
            )

        return (
            quantity,
            None
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ) as error:

        return (
            None,
            str(error)
        )


# ============================================================
# REAL BUY
#
# STILL LOCKED IN THIS VERSION.
# Authentication must first be confirmed.
# ============================================================

def real_buy(
    item,
    signal
):

    symbol = get_symbol(
        item
    )

    price = Decimal(
        str(signal["price"])
    )

    quantity, error = (
        prepare_quantity(
            item,
            price
        )
    )

    if error:

        telegram(
            f"⚠️ BUY SKIPPED "
            f"{VERSION}\n\n"
            f"🪙 {symbol}\n"
            f"❌ {error}\n"
            f"🛑 NO ORDER SENT\n"
            f"🕐 {utc_now()}"
        )

        return False

    # --------------------------------------------------------
    # SAFETY LOCK
    # --------------------------------------------------------

    if REAL_BUY_LOCKED:

        telegram(
            f"🛑 REAL BUY LOCKED "
            f"{VERSION}\n\n"
            f"🪙 {symbol}\n"
            f"💰 VALUE: "
            f"{ORDER_USDT} USDT\n"
            f"🔢 QTY: "
            f"{decimal_string(quantity)}\n"
            f"🛑 NO ORDER SENT\n"
            f"🕐 {utc_now()}"
        )

        return False

    if not LIVE_TRADING:

        telegram(
            f"🟡 PAPER BUY "
            f"{VERSION}\n\n"
            f"🪙 {symbol}\n"
            f"💰 VALUE: "
            f"{ORDER_USDT} USDT\n"
            f"🔢 QTY: "
            f"{decimal_string(quantity)}\n"
            f"💵 PRICE: "
            f"{price}\n"
            f"🕐 {utc_now()}"
        )

        return False

    # --------------------------------------------------------
    # OFFICIAL SDK ORDER DATA STRUCTURE
    #
    # side
    # type
    # quantity
    # price
    # stopPrice
    # symbol
    #
    # --------------------------------------------------------

    order_data = {
        "side": "BUY",
        "type": "MARKET",
        "quantity": decimal_string(
            quantity
        ),
        "price": "0",
        "stopPrice": "0",
        "symbol": symbol,
    }

    try:

        response, signed_query = (
            signed_post(
                "/api/v1/order",
                order_data
            )
        )

    except Exception as error:

        telegram(
            f"🚨 REAL BUY CONNECTION ERROR "
            f"{VERSION}\n\n"
            f"🪙 {symbol}\n"
            f"❌ {type(error).__name__}\n"
            f"❌ {error}\n"
            f"🛑 ORDER NOT CONFIRMED\n"
            f"🕐 {utc_now()}"
        )

        return False

    if response.status_code < 400:

        try:

            result = response.json()

        except Exception:

            result = {}

        telegram(
            f"🚨 REAL BUY RESPONSE "
            f"{VERSION}\n\n"
            f"🪙 {symbol}\n"
            f"💰 VALUE: "
            f"{ORDER_USDT} USDT\n"
            f"🔢 QTY: "
            f"{decimal_string(quantity)}\n"
            f"📡 HTTP: "
            f"{response.status_code}\n"
            f"📋 RESPONSE:\n"
            f"{json.dumps(result, ensure_ascii=False)[:1200]}\n"
            f"🕐 {utc_now()}"
        )

        return True

    error = get_api_error(
        response
    )

    telegram(
        f"🚨 REAL BUY ERROR "
        f"{VERSION}\n\n"
        f"🪙 {symbol}\n"
        f"❌ HTTP "
        f"{response.status_code}\n"
        f"❌ {error}\n"
        f"🛑 ORDER NOT CONFIRMED\n"
        f"🕐 {utc_now()}"
    )

    return False


# ============================================================
# MAIN
# ============================================================

def main():

    # --------------------------------------------------------
    # STARTUP
    # --------------------------------------------------------

    telegram(
        f"🚀 ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"🔐 AUTHENTICATION: STARTING\n"
        f"🛡 REAL BUY LOCK: ON\n"
        f"💰 ORDER AMOUNT: "
        f"{ORDER_USDT} USDT\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # CREDENTIAL CHECK
    # --------------------------------------------------------

    if not API_KEY:

        telegram(
            f"🚨 ATI CONFIG ERROR "
            f"{VERSION}\n\n"
            f"❌ TABDEAL API KEY MISSING\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return

    if not API_SECRET:

        telegram(
            f"🚨 ATI CONFIG ERROR "
            f"{VERSION}\n\n"
            f"❌ TABDEAL API SECRET MISSING\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # AUTHENTICATION FIRST
    # --------------------------------------------------------

    authenticated = authenticate()

    if not authenticated:

        telegram(
            f"🛑 ATI SAFE STOP {VERSION}\n\n"
            f"🚫 PRIVATE API AUTH FAILED\n"
            f"🚫 REAL BUY DISABLED\n"
            f"❌ NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # IMPORTANT:
    # Keep real BUY locked even after auth.
    # This version is for authentication verification.
    # --------------------------------------------------------

    REAL_BUY_LOCKED = True

    telegram(
        f"🟢 ATI AUTHENTICATION PASSED "
        f"{VERSION}\n\n"
        f"🔐 PRIVATE API: OK\n"
        f"📊 SCAN CAN START\n"
        f"🛑 REAL BUY: LOCKED\n"
        f"🛑 NO REAL ORDER WILL BE SENT\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    results = scan_markets()

    if not results:

        telegram(
            f"📭 ATI NO VALID CANDIDATES "
            f"{VERSION}\n\n"
            f"📊 SCAN COMPLETE\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # TOP 10
    # --------------------------------------------------------

    top = results[:10]

    lines = [
        f"🔥 ATI TOP SIGNALS {VERSION}",
        "",
    ]

    for index, result in enumerate(
        top,
        1
    ):

        lines.append(
            f"{index}. "
            f"{result['symbol']} "
            f"| SCORE "
            f"{result['score']} "
            f"| MOVE "
            f"{result['move']:.2f}% "
            f"| PRESSURE "
            f"{result['pressure']:.1f}%"
        )

    lines.append("")
    lines.append(
        f"📊 CANDIDATES: "
        f"{len(results)}"
    )
    lines.append(
        "🛑 REAL BUY: LOCKED"
    )
    lines.append(
        f"🕐 {utc_now()}"
    )

    telegram(
        "\n".join(lines)
    )

    # --------------------------------------------------------
    # BEST SIGNAL INFORMATION
    # --------------------------------------------------------

    best = results[0]

    if best["score"] < 10:

        telegram(
            f"👀 ATI WATCH ONLY "
            f"{VERSION}\n\n"
            f"🪙 {best['symbol']}\n"
            f"📊 SCORE: "
            f"{best['score']}\n"
            f"📈 MOVE: "
            f"{best['move']:.2f}%\n"
            f"💪 PRESSURE: "
            f"{best['pressure']:.1f}%\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🕐 {utc_now()}"
        )

        return

    telegram(
        f"🟢 ATI SIGNAL DETECTED "
        f"{VERSION}\n\n"
        f"🪙 {best['symbol']}\n"
        f"📊 SCORE: "
        f"{best['score']}\n"
        f"📈 MOVE: "
        f"{best['move']:.2f}%\n"
        f"💪 PRESSURE: "
        f"{best['pressure']:.1f}%\n"
        f"💵 PRICE: "
        f"{best['price']}\n\n"
        f"🛑 REAL BUY LOCKED\n"
        f"❌ NO ORDER SENT\n"
        f"🕐 {utc_now()}"
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    main()
