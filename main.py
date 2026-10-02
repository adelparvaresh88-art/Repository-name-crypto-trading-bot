import os
import time
import json
import hmac
import hashlib
import math
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.20
# TABDEAL SPOT
# OFFICIAL POSTMAN SIGNATURE METHOD
# ============================================================

VERSION = "V40.2.20"

BASE_URL = "https://api1.tabdeal.org"

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").strip().lower() == "true"

# Fixed USDT amount
ORDER_USDT = Decimal(os.getenv("ORDER_USDT", "2"))

# Backward compatibility with old secret
if not API_KEY:
    API_KEY = os.getenv("TABDIL_API_KEY", "").strip()

if not API_SECRET:
    API_SECRET = os.getenv("TABDIL_API_SECRET", "").strip()

RECV_WINDOW = "5000"

TIMEOUT = 20

MAX_MARKETS = 15

HEARTBEAT_MINUTES = 5

REAL_BUY_LOCKED = True

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/" + VERSION,
        "Accept": "application/json",
    }
)


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = (
            "https://api.telegram.org/bot"
            + TELEGRAM_BOT_TOKEN
            + "/sendMessage"
        )

        r = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )

        return r.ok

    except Exception:
        return False


# ============================================================
# HTTP
# ============================================================

def public_get(path, params=None):
    url = BASE_URL + path

    r = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT,
    )

    r.raise_for_status()

    return r.json()


# ============================================================
# OFFICIAL TABDEAL SIGNATURE
#
# IMPORTANT:
# Postman official:
#
# paramsObject:
#     original parameters
#     timestamp
#     recvWindow
#
# queryString:
#     key=value&key=value
#
# signature:
#     HMAC-SHA256(queryString, api_secret)
#
# NO urlencode()
# NO sorting()
# NO signature inside signed string
# ============================================================

def build_signed_params(params=None):
    if not API_KEY or not API_SECRET:
        raise RuntimeError("API credentials are missing")

    params = params.copy() if params else {}

    # Remove anything that must be generated again
    params.pop("signature", None)
    params.pop("timestamp", None)
    params.pop("recvWindow", None)

    # Exact order:
    # existing parameters -> timestamp -> recvWindow
    timestamp = int(time.time() * 1000)

    params["timestamp"] = timestamp
    params["recvWindow"] = RECV_WINDOW

    # EXACT RAW QUERY STRING
    query_string = "&".join(
        f"{key}={value}"
        for key, value in params.items()
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    params["signature"] = signature

    return params, query_string


# ============================================================
# SIGNED GET
# ============================================================

def signed_get(path, params=None):
    signed_params, raw_query = build_signed_params(params)

    headers = {
        "X-MBX-APIKEY": API_KEY,
    }

    url = BASE_URL + path

    r = session.get(
        url,
        params=signed_params,
        headers=headers,
        timeout=TIMEOUT,
    )

    return r, raw_query


# ============================================================
# SIGNED POST
# ============================================================

def signed_post(path, params=None):
    signed_params, raw_query = build_signed_params(params)

    headers = {
        "X-MBX-APIKEY": API_KEY,
    }

    url = BASE_URL + path

    # Tabdeal Postman uses form-data for spot order
    r = session.post(
        url,
        data=signed_params,
        headers=headers,
        timeout=TIMEOUT,
    )

    return r, raw_query


# ============================================================
# API ERROR
# ============================================================

def api_error_text(response):
    try:
        data = response.json()

        if isinstance(data, dict):
            code = data.get("code", "")
            msg = data.get("msg", data.get("message", ""))

            return f"CODE: {code}\nMSG: {msg}"

        return str(data)

    except Exception:
        return response.text[:500]


# ============================================================
# AUTHENTICATION TEST
# ============================================================

def authenticate():
    telegram(
        f"🔐 ATI API AUTH TEST {VERSION}\n"
        f"📡 Tabdeal private endpoint\n"
        f"🕐 {utc_now()}"
    )

    try:
        response, raw_query = signed_get(
            "/r/api/v1/account"
        )

    except Exception as e:
        telegram(
            f"🚨 ATI API CONNECTION FAILED {VERSION}\n\n"
            f"❌ {type(e).__name__}\n"
            f"❌ {e}\n\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🕐 {utc_now()}"
        )

        return False

    if response.status_code == 200:

        try:
            data = response.json()
        except Exception:
            data = {}

        telegram(
            f"✅ ATI API AUTH OK {VERSION}\n\n"
            f"🔐 HMAC-SHA256: OK\n"
            f"🔢 INTEGER TIMESTAMP: OK\n"
            f"🔐 RAW QUERY: OK\n"
            f"🔐 timestamp → recvWindow: OK\n"
            f"📡 PRIVATE ACCOUNT: HTTP 200\n"
            f"🟢 API AUTHENTICATED\n"
            f"🕐 {utc_now()}"
        )

        return True

    error = api_error_text(response)

    if response.status_code == 401 or "1103" in error:
        telegram(
            f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
            f"❌ HTTP {response.status_code}\n"
            f"❌ {error}\n\n"
            f"🔐 HMAC-SHA256\n"
            f"🔢 INTEGER TIMESTAMP\n"
            f"🔐 RAW QUERY\n"
            f"🔐 timestamp → recvWindow\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return False

    telegram(
        f"🚨 ATI PRIVATE API ERROR {VERSION}\n\n"
        f"❌ HTTP {response.status_code}\n"
        f"❌ {error}\n\n"
        f"🛑 REAL BUY LOCKED\n"
        f"🕐 {utc_now()}"
    )

    return False


# ============================================================
# EXCHANGE INFO
# ============================================================

def exchange_info():
    return public_get("/r/api/v1/exchangeInfo")


# ============================================================
# USDT MARKETS
# ============================================================

def get_usdt_markets():
    data = exchange_info()

    symbols = data.get("symbols", [])

    result = []

    for item in symbols:

        if not isinstance(item, dict):
            continue

        symbol = str(
            item.get("symbol")
            or item.get("tabdealSymbol")
            or ""
        ).upper()

        status = str(
            item.get("status", "TRADING")
        ).upper()

        if not symbol.endswith("USDT"):
            continue

        if status not in ("TRADING", "1", "ACTIVE"):
            continue

        result.append(item)

    return result


# ============================================================
# SYMBOL HELPERS
# ============================================================

def symbol_name(item):
    return str(
        item.get("symbol")
        or item.get("tabdealSymbol")
        or ""
    ).upper()


def get_filter(item, names):
    filters = item.get("filters", [])

    for f in filters:

        if not isinstance(f, dict):
            continue

        ftype = str(f.get("filterType", "")).upper()

        if ftype in names:
            return f

    return {}


def get_step_size(item):
    f = get_filter(
        item,
        {"LOT_SIZE", "MARKET_LOT_SIZE"},
    )

    value = (
        f.get("stepSize")
        or f.get("step")
        or item.get("stepSize")
        or "0.00000001"
    )

    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0.00000001")


def get_min_qty(item):
    f = get_filter(
        item,
        {"LOT_SIZE", "MARKET_LOT_SIZE"},
    )

    value = (
        f.get("minQty")
        or item.get("minQty")
        or "0"
    )

    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def get_min_notional(item):
    f = get_filter(
        item,
        {"MIN_NOTIONAL", "NOTIONAL"},
    )

    value = (
        f.get("minNotional")
        or f.get("notional")
        or item.get("minNotional")
        or "0"
    )

    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


# ============================================================
# DECIMAL ROUNDING
# ============================================================

def floor_step(value, step):

    if step <= 0:
        return value

    try:
        units = (value / step).to_integral_value(
            rounding=ROUND_DOWN
        )

        return units * step

    except Exception:
        return value


def decimal_string(value):

    s = format(
        value,
        "f"
    )

    if "." in s:
        s = s.rstrip("0").rstrip(".")

    return s or "0"


# ============================================================
# TRADES
# ============================================================

def get_recent_trades(symbol):

    try:
        data = public_get(
            "/r/api/v1/trades",
            {
                "symbol": symbol,
                "limit": 1000,
            },
        )

        if isinstance(data, list):
            return data

        if isinstance(data, dict):

            for key in (
                "data",
                "trades",
                "result",
            ):

                if isinstance(data.get(key), list):
                    return data[key]

    except Exception:
        pass

    return []


# ============================================================
# PRICE FROM TRADES
# ============================================================

def trade_price(t):

    if not isinstance(t, dict):
        return None

    for key in (
        "price",
        "p",
    ):

        if key in t:

            try:
                return float(t[key])
            except Exception:
                return None

    return None


# ============================================================
# BASIC 5M MOMENTUM
# ============================================================

def analyze_symbol(item):

    symbol = symbol_name(item)

    if not symbol:
        return None

    trades = get_recent_trades(symbol)

    prices = []

    for t in trades:

        p = trade_price(t)

        if p is not None and p > 0:
            prices.append(p)

    if len(prices) < 20:
        return None

    # Keep chronological-ish order from API response.
    # If API returns newest first, reverse it.
    if prices[0] > prices[-1]:
        prices.reverse()

    last = prices[-1]

    lookback = min(60, len(prices))

    old = prices[-lookback]

    if old <= 0:
        return None

    move = ((last - old) / old) * 100.0

    # Recent momentum
    short_n = min(20, len(prices))

    short_old = prices[-short_n]

    if short_old <= 0:
        return None

    short_move = (
        (last - short_old)
        / short_old
        * 100.0
    )

    # Simple pressure proxy
    up = 0
    down = 0

    for i in range(
        max(1, len(prices) - 30),
        len(prices)
    ):

        if prices[i] > prices[i - 1]:
            up += 1

        elif prices[i] < prices[i - 1]:
            down += 1

    total = up + down

    pressure = (
        (up / total) * 100
        if total
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
        "price": last,
        "move": move,
        "short_move": short_move,
        "pressure": pressure,
        "score": score,
    }


# ============================================================
# SCAN
# ============================================================

def scan():

    telegram(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED CANDLE: YES\n"
        f"💵 ORDER MODE: FIXED USDT AMOUNT\n"
        f"💰 ORDER AMOUNT: {ORDER_USDT} USDT\n"
        f"🔧 REAL ORDERS: "
        f"{'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"
        f"🕐 {utc_now()}"
    )

    try:
        markets = get_usdt_markets()

    except Exception as e:

        telegram(
            f"🚨 EXCHANGE INFO ERROR {VERSION}\n\n"
            f"❌ {type(e).__name__}: {e}\n"
            f"🕐 {utc_now()}"
        )

        return []

    telegram(
        f"📊 ATI MARKET SCAN {VERSION}\n\n"
        f"🟢 USDT MARKETS: {len(markets)}\n"
        f"🔎 REQUESTED: {MAX_MARKETS}\n"
        f"🕐 {utc_now()}"
    )

    results = []

    # Prioritize a limited number to keep GitHub Actions
    # runtime reasonable.
    markets = markets[:MAX_MARKETS]

    for item in markets:

        try:

            result = analyze_symbol(item)

            if result:
                results.append(result)

        except Exception:
            continue

    results.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    return results


# ============================================================
# ORDER PREPARATION
# ============================================================

def prepare_quantity(item, price):

    if price <= 0:
        return None, "INVALID PRICE"

    try:

        price_d = Decimal(str(price))

        quantity = (
            ORDER_USDT
            / price_d
        )

        step = get_step_size(item)

        min_qty = get_min_qty(item)

        min_notional = get_min_notional(item)

        quantity = floor_step(
            quantity,
            step,
        )

        if quantity < min_qty:
            return (
                None,
                f"quantity {quantity} < minQty {min_qty}"
            )

        notional = quantity * price_d

        if min_notional > 0 and notional < min_notional:

            return (
                None,
                f"order value {notional} < "
                f"MIN_NOTIONAL {min_notional}"
            )

        if quantity <= 0:
            return None, "QUANTITY ZERO"

        return quantity, None

    except (InvalidOperation, ValueError, TypeError) as e:

        return None, str(e)


# ============================================================
# REAL BUY
# ============================================================

def real_buy(item, signal):

    global REAL_BUY_LOCKED

    symbol = symbol_name(item)

    price = Decimal(
        str(signal["price"])
    )

    quantity, error = prepare_quantity(
        item,
        price,
    )

    if error:

        telegram(
            f"⚠️ BUY SKIPPED\n\n"
            f"🪙 {symbol}\n"
            f"❌ {error}\n"
            f"🛑 NO ORDER SENT\n"
            f"🕐 {utc_now()}"
        )

        return False

    if REAL_BUY_LOCKED:

        telegram(
            f"🛑 REAL BUY LOCKED\n\n"
            f"🪙 {symbol}\n"
            f"💰 VALUE: {ORDER_USDT} USDT\n"
            f"🔢 QTY: {decimal_string(quantity)}\n"
            f"🛑 NO ORDER SENT\n"
            f"🕐 {utc_now()}"
        )

        return False

    if not LIVE_TRADING:

        telegram(
            f"🟡 PAPER BUY\n\n"
            f"🪙 {symbol}\n"
            f"💰 VALUE: {ORDER_USDT} USDT\n"
            f"🔢 QTY: {decimal_string(quantity)}\n"
            f"💵 PRICE: {price}\n"
            f"🕐 {utc_now()}"
        )

        return False

    params = {
        "tabdealSymbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quantity": decimal_string(quantity),
    }

    try:

        response, raw_query = signed_post(
            "/api/v1/order",
            params,
        )

    except Exception as e:

        telegram(
            f"🚨 REAL BUY CONNECTION ERROR\n\n"
            f"🪙 {symbol}\n"
            f"❌ {e}\n"
            f"🛑 ORDER STATUS UNKNOWN\n"
            f"🕐 {utc_now()}"
        )

        return False

    if response.status_code in (200, 201):

        try:
            data = response.json()
        except Exception:
            data = {}

        telegram(
            f"🚨 REAL BUY SENT\n\n"
            f"🪙 {symbol}\n"
            f"💰 VALUE: {ORDER_USDT} USDT\n"
            f"🔢 QTY: {decimal_string(quantity)}\n"
            f"📡 HTTP: {response.status_code}\n"
            f"📋 ORDER ID: {data.get('orderId', 'N/A')}\n"
            f"🕐 {utc_now()}"
        )

        return True

    error = api_error_text(response)

    telegram(
        f"🚨 REAL BUY ERROR\n\n"
        f"🪙 {symbol}\n"
        f"❌ HTTP {response.status_code}\n"
        f"❌ {error}\n"
        f"🛑 ORDER NOT CONFIRMED\n"
        f"🕐 {utc_now()}"
    )

    return False


# ============================================================
# MAIN
# ============================================================

def main():

    telegram(
        f"🚀 ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"🔐 AUTH TEST: STARTING\n"
        f"🛡 REAL BUY LOCK: ON\n"
        f"🕐 {utc_now()}"
    )

    if not API_KEY or not API_SECRET:

        telegram(
            f"🚨 ATI CONFIG ERROR {VERSION}\n\n"
            f"❌ API KEY OR API SECRET MISSING\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # AUTHENTICATION MUST PASS FIRST
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

    # Auth succeeded
    REAL_BUY_LOCKED = False

    # --------------------------------------------------------
    # PUBLIC SCAN
    # --------------------------------------------------------

    results = scan()

    if not results:

        telegram(
            f"📭 ATI NO SIGNALS {VERSION}\n\n"
            f"❌ No valid candidates\n"
            f"📊 SCAN COMPLETE\n"
            f"🕐 {utc_now()}"
        )

        return

    top = results[:10]

    lines = [
        f"🔥 ATI TOP SIGNALS {VERSION}",
        "",
    ]

    for i, r in enumerate(top, 1):

        lines.append(
            f"{i}. {r['symbol']} "
            f"| SCORE {r['score']} "
            f"| MOVE {r['move']:.2f}% "
            f"| PRESSURE {r['pressure']:.1f}%"
        )

    lines.append("")
    lines.append(f"📊 CANDIDATES: {len(results)}")
    lines.append(f"🕐 {utc_now()}")

    telegram(
        "\n".join(lines)
    )

    # --------------------------------------------------------
    # BUY ONLY TOP SIGNAL
    # --------------------------------------------------------

    best = results[0]

    if best["score"] < 10:

        telegram(
            f"👀 ATI WATCH ONLY {VERSION}\n\n"
            f"🪙 {best['symbol']}\n"
            f"📊 SCORE: {best['score']}\n"
            f"📈 MOVE: {best['move']:.2f}%\n"
            f"💪 PRESSURE: {best['pressure']:.1f}%\n"
            f"🛑 BUY NOT CONFIRMED\n"
            f"🕐 {utc_now()}"
        )

        return

    # Find original exchange info
    selected_item = None

    try:

        markets = get_usdt_markets()

        for item in markets:

            if symbol_name(item) == best["symbol"]:

                selected_item = item
                break

    except Exception:
        selected_item = None

    if selected_item is None:

        telegram(
            f"⚠️ ATI ORDER SKIPPED {VERSION}\n\n"
            f"🪙 {best['symbol']}\n"
            f"❌ MARKET INFO NOT FOUND\n"
            f"🛑 NO ORDER SENT\n"
            f"🕐 {utc_now()}"
        )

        return

    real_buy(
        selected_item,
        best,
    )


if __name__ == "__main__":
    main()
