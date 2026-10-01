import os
import time
import json
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.19
# TABDEAL SPOT
# AUTH / SIGNATURE SAFE VERSION
# ============================================================

VERSION = "V40.2.19"

BASE_URL = "https://api1.tabdeal.org"
API_BASE = f"{BASE_URL}/r/api/v1"

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

LIVE_TRADING = os.getenv(
    "LIVE_TRADING", "false"
).strip().lower() in {
    "1", "true", "yes", "on"
}

try:
    ORDER_USDT = Decimal(os.getenv("ORDER_QTY", "2").strip())
except Exception:
    ORDER_USDT = Decimal("2")

RECV_WINDOW = 10000
MAX_REAL_BUYS_PER_RUN = 1
DEEP_SCAN_LIMIT = 15
TRADE_LIMIT = 100
REQUEST_TIMEOUT = 15

AUTH_OK = False
REAL_BUYS_THIS_RUN = 0
SERVER_OFFSET_MS = 0

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": f"ATI/{VERSION}"
})


# ============================================================
# BASIC
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def log(text):
    print(text, flush=True)


def tg(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        r = SESSION.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text
            },
            timeout=REQUEST_TIMEOUT
        )
        return r.ok
    except Exception:
        return False


# ============================================================
# HTTP
# ============================================================

def api_json(method, path, **kwargs):

    url = f"{API_BASE}{path}"

    try:
        r = SESSION.request(
            method,
            url,
            timeout=REQUEST_TIMEOUT,
            **kwargs
        )

        try:
            body = r.json()
        except Exception:
            body = {}

        return r, body

    except requests.RequestException as e:

        return None, {
            "code": -1,
            "msg": str(e)
        }


# ============================================================
# SERVER TIME
# ============================================================

def server_time_sync():

    global SERVER_OFFSET_MS

    r, body = api_json(
        "GET",
        "/time"
    )

    if not r or r.status_code != 200:
        SERVER_OFFSET_MS = 0
        log("⚠️ SERVER TIME SYNC FAILED")
        return False

    server_ms = None

    if isinstance(body, dict):

        for key in (
            "serverTime",
            "timestamp",
            "time"
        ):

            if body.get(key) is not None:

                try:
                    server_ms = int(body[key])
                    break
                except Exception:
                    pass

    if server_ms is None:
        SERVER_OFFSET_MS = 0
        return False

    local_ms = int(time.time() * 1000)

    SERVER_OFFSET_MS = (
        server_ms - local_ms
    )

    log(
        f"🕐 SERVER OFFSET: "
        f"{SERVER_OFFSET_MS} ms"
    )

    return True


# ============================================================
# SIGNATURE
# ============================================================

def build_signature_params(extra=None):

    """
    Tabdeal private API signing.

    Order:
        supplied parameters
        timestamp
        recvWindow

    Signature:
        HMAC-SHA256
        RAW key=value query string

    IMPORTANT:
        No urlencode() is used for the signature.
    """

    params = []

    if extra:

        for key, value in extra.items():

            if key in {
                "signature",
                "timestamp",
                "recvWindow"
            }:
                continue

            if value is None:
                continue

            if isinstance(value, str):
                if value.strip() == "":
                    continue

            params.append(
                (
                    str(key),
                    str(value)
                )
            )

    timestamp = (
        int(time.time() * 1000)
        + int(SERVER_OFFSET_MS)
    )

    params.append(
        ("timestamp", str(timestamp))
    )

    params.append(
        ("recvWindow", str(RECV_WINDOW))
    )

    raw_query = "&".join(
        f"{key}={value}"
        for key, value in params
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        raw_query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return params, raw_query, signature


def private_get(path, extra=None):

    params_list, raw_query, signature = (
        build_signature_params(extra)
    )

    request_params = dict(params_list)

    request_params["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    r, body = api_json(
        "GET",
        path,
        params=request_params,
        headers=headers
    )

    return (
        r,
        body,
        raw_query,
        signature
    )


def private_post(path, extra=None):

    params_list, raw_query, signature = (
        build_signature_params(extra)
    )

    # IMPORTANT:
    # Keep the exact same parameter order that was signed.
    body_parts = [
        f"{key}={value}"
        for key, value in params_list
    ]

    body_parts.append(
        f"signature={signature}"
    )

    request_body = "&".join(body_parts)

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type":
            "application/x-www-form-urlencoded"
    }

    r, body = api_json(
        "POST",
        path,
        data=request_body,
        headers=headers
    )

    return (
        r,
        body,
        raw_query,
        signature
    )


# ============================================================
# AUTHENTICATION
# ============================================================

def authenticate():

    global AUTH_OK

    AUTH_OK = False

    if not API_KEY or not API_SECRET:

        msg = (
            f"🚨 ATI API AUTH FAILED {VERSION}\n"
            "❌ API KEY OR SECRET MISSING\n"
            "🛑 REAL BUY LOCKED\n"
            "🛑 NO ORDER WAS SENT"
        )

        log(msg)
        tg(msg)

        return False

    log(
        "🔐 AUTH: "
        "PRIVATE ACCOUNT TEST..."
    )

    r, body, raw_query, signature = (
        private_get("/account")
    )

    status = (
        r.status_code
        if r is not None
        else 0
    )

    code = None

    if isinstance(body, dict):
        code = body.get("code")

    message = ""

    if isinstance(body, dict):

        message = (
            body.get("msg")
            or body.get("message")
            or ""
        )

    # ========================================================
    # SUCCESS
    # ========================================================

    if (
        r is not None
        and status == 200
        and (
            code is None
            or str(code) == "0"
        )
    ):

        AUTH_OK = True

        msg = (
            f"✅ ATI API AUTH OK {VERSION}\n"
            "🔐 HMAC-SHA256\n"
            "🔢 INTEGER TIMESTAMP\n"
            "🔐 RAW QUERY SIGNATURE\n"
            "🟢 REAL BUY AUTHORIZED\n"
            f"🕐 {now_utc()}"
        )

        log(msg)
        tg(msg)

        return True

    # ========================================================
    # FAILURE
    # ========================================================

    if not message:
        message = "Authentication failed"

    msg = (
        f"🚨 ATI API AUTH FAILED {VERSION}\n"
        f"❌ HTTP {status}\n"
        f"❌ CODE: {code if code is not None else 'UNKNOWN'}\n"
        f"❌ {message}\n\n"
        "🔐 HMAC-SHA256\n"
        "🔢 INTEGER TIMESTAMP\n"
        "🔐 RAW QUERY\n"
        "🔐 timestamp → recvWindow\n"
        "🛑 REAL BUY LOCKED\n"
        "🛑 NO ORDER WAS SENT"
    )

    log(msg)
    tg(msg)

    # Never print API secret.
    # Only print the signed parameter structure.
    log(
        "🔎 SIGNED PARAMS: "
        + raw_query
    )

    return False


# ============================================================
# EXCHANGE INFO
# ============================================================

def exchange_info():

    r, body = api_json(
        "GET",
        "/exchangeInfo"
    )

    if not r or r.status_code != 200:

        log(
            "❌ EXCHANGE INFO FAILED "
            f"HTTP {r.status_code if r else 0}"
        )

        return []

    items = []

    if isinstance(body, dict):

        for key in (
            "symbols",
            "data",
            "result"
        ):

            value = body.get(key)

            if isinstance(value, list):
                items = value
                break

        if (
            not items
            and isinstance(
                body.get("data"),
                dict
            )
        ):

            data = body["data"]

            for key in (
                "symbols",
                "result"
            ):

                if isinstance(
                    data.get(key),
                    list
                ):

                    items = data[key]
                    break

    elif isinstance(body, list):

        items = body

    markets = []
    seen = set()

    for item in items:

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("name")
            or item.get("market")
            or item.get("tabdealSymbol")
        )

        tabdeal_symbol = (
            item.get("tabdealSymbol")
            or item.get("tabdeal_symbol")
        )

        base = (
            item.get("baseAsset")
            or item.get("base")
        )

        quote = (
            item.get("quoteAsset")
            or item.get("quote")
        )

        if not symbol and tabdeal_symbol:

            symbol = str(
                tabdeal_symbol
            ).replace("_", "")

        if not symbol:
            continue

        raw_symbol = (
            str(symbol)
            .upper()
            .replace("-", "")
            .replace("/", "")
        )

        td = (
            str(tabdeal_symbol).upper()
            if tabdeal_symbol
            else ""
        )

        if not td:

            if "_" in str(symbol):
                td = str(symbol).upper()

            elif quote and base:

                td = (
                    f"{str(base).upper()}_"
                    f"{str(quote).upper()}"
                )

            elif raw_symbol.endswith("USDT"):

                td = (
                    raw_symbol[:-4]
                    + "_USDT"
                )

        if (
            "USDT" not in raw_symbol
            and "_USDT" not in td
        ):
            continue

        compact = raw_symbol.replace(
            "_",
            ""
        )

        if not compact.endswith("USDT"):
            continue

        if compact in seen:
            continue

        seen.add(compact)

        markets.append({
            "symbol": compact,
            "tabdealSymbol": (
                td
                or compact[:-4] + "_USDT"
            ),
            "raw": item
        })

    return markets


# ============================================================
# TRADE DATA
# ============================================================

def extract_price(trade):

    if not isinstance(trade, dict):
        return None

    for key in (
        "price",
        "p",
        "lastPrice"
    ):

        try:

            value = Decimal(
                str(trade[key])
            )

            if value > 0:
                return value

        except Exception:
            pass

    return None


def extract_qty(trade):

    if not isinstance(trade, dict):
        return Decimal("0")

    for key in (
        "qty",
        "quantity",
        "q",
        "amount"
    ):

        try:

            value = Decimal(
                str(trade[key])
            )

            if value >= 0:
                return value

        except Exception:
            pass

    return Decimal("0")


def recent_trades(tabdeal_symbol):

    r, body = api_json(
        "GET",
        "/trades",
        params={
            "tabdealSymbol":
                tabdeal_symbol,
            "limit":
                TRADE_LIMIT
        }
    )

    if not r or r.status_code != 200:
        return []

    if isinstance(body, list):
        return body

    if isinstance(body, dict):

        for key in (
            "data",
            "trades",
            "result"
        ):

            if isinstance(
                body.get(key),
                list
            ):

                return body[key]

    return []


# ============================================================
# MARKET SCORE
# ============================================================

def score_market(market):

    trades = recent_trades(
        market["tabdealSymbol"]
    )

    prices = [
        extract_price(t)
        for t in trades
    ]

    prices = [
        p for p in prices
        if p is not None
    ]

    if len(prices) < 12:
        return None

    first = prices[0]
    last = prices[-1]

    if first <= 0:
        return None

    move = (
        (last - first)
        / first
        * Decimal("100")
    )

    buy_qty = Decimal("0")
    sell_qty = Decimal("0")

    for t in trades:

        q = extract_qty(t)

        maker = (
            t.get("isBuyerMaker")
            if isinstance(t, dict)
            else None
        )

        if (
            maker is True
            or str(maker).lower()
            == "true"
        ):

            sell_qty += q

        else:

            buy_qty += q

    total = buy_qty + sell_qty

    if total > 0:

        pressure = (
            buy_qty
            / total
            * Decimal("100")
        )

    else:

        pressure = Decimal("0")

    score = 0

    if move >= Decimal("0.50"):
        score += 4

    elif move >= Decimal("0.20"):
        score += 2

    if pressure >= Decimal("60"):
        score += 4

    elif pressure >= Decimal("55"):
        score += 2

    if last >= (
        max(prices)
        * Decimal("0.995")
    ):
        score += 2

    return {
        "symbol":
            market["symbol"],

        "tabdealSymbol":
            market["tabdealSymbol"],

        "price":
            last,

        "move":
            move,

        "pressure":
            pressure,

        "score":
            score
    }


# ============================================================
# ORDER FILTERS
# ============================================================

def decimal_step(value, step):

    try:

        value = Decimal(str(value))
        step = Decimal(str(step))

        if step <= 0:
            return value

        return (
            value / step
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * step

    except Exception:

        return value


def find_filter(raw, names):

    filters = (
        raw.get("filters")
        if isinstance(raw, dict)
        else None
    )

    if not isinstance(filters, list):
        return {}

    for f in filters:

        if (
            isinstance(f, dict)
            and f.get("filterType")
            in names
        ):

            return f

    return {}


def order_quantity(market, price):

    raw = market.get("raw", {})

    lot = find_filter(
        raw,
        {
            "LOT_SIZE",
            "MARKET_LOT_SIZE"
        }
    )

    notional_filter = find_filter(
        raw,
        {
            "MIN_NOTIONAL",
            "NOTIONAL"
        }
    )

    step = lot.get(
        "stepSize",
        "0"
    )

    min_qty = Decimal(
        str(
            lot.get(
                "minQty",
                "0"
            ) or "0"
        )
    )

    min_notional = Decimal(
        str(
            notional_filter.get(
                "minNotional"
            )
            or notional_filter.get(
                "notional"
            )
            or "0"
        )
    )

    if price <= 0:
        return None, "invalid price"

    if ORDER_USDT <= 0:
        return None, "invalid order amount"

    if (
        min_notional > 0
        and min_notional > ORDER_USDT
    ):

        return (
            None,
            f"MIN_NOTIONAL "
            f"{min_notional} > "
            f"{ORDER_USDT} USDT"
        )

    qty = (
        ORDER_USDT / price
    )

    qty = decimal_step(
        qty,
        step
    )

    if qty <= 0:
        return (
            None,
            "quantity rounds to zero"
        )

    if qty < min_qty:

        return (
            None,
            f"quantity {qty} "
            f"< minimum {min_qty}"
        )

    order_value = qty * price

    if (
        min_notional > 0
        and order_value < min_notional
    ):

        return (
            None,
            f"order value "
            f"{order_value} < "
            f"MIN_NOTIONAL "
            f"{min_notional}"
        )

    return (
        format(qty, "f"),
        None
    )


# ============================================================
# REAL BUY
# ============================================================

def place_real_buy(candidate, market):

    global REAL_BUYS_THIS_RUN
    global AUTH_OK

    if not LIVE_TRADING:
        return False, "LIVE_TRADING is OFF"

    if not AUTH_OK:
        return False, "API AUTH not OK"

    if (
        REAL_BUYS_THIS_RUN
        >= MAX_REAL_BUYS_PER_RUN
    ):

        return (
            False,
            "MAX_REAL_BUYS_PER_RUN reached"
        )

    price = candidate["price"]

    qty, reason = order_quantity(
        market,
        price
    )

    if not qty:
        return False, reason

    params = {
        "tabdealSymbol":
            market["tabdealSymbol"],

        "side":
            "BUY",

        "type":
            "MARKET",

        "quantity":
            qty
    }

    r, body, raw_query, signature = (
        private_post(
            "/order",
            params
        )
    )

    code = (
        body.get("code")
        if isinstance(body, dict)
        else None
    )

    status = (
        r.status_code
        if r is not None
        else 0
    )

    # ========================================================
    # SUCCESS
    # ========================================================

    if (
        status == 200
        and (
            code is None
            or str(code) == "0"
        )
    ):

        REAL_BUYS_THIS_RUN += 1

        order_id = (
            body.get("orderId")
            if isinstance(body, dict)
            else "?"
        )

        text = (
            "🚨 ATI REAL BUY\n"
            f"🪙 {market['symbol']}\n"
            f"💵 AMOUNT: {ORDER_USDT} USDT\n"
            f"🔢 QTY: {qty}\n"
            f"💰 PRICE: {price}\n"
            f"🆔 ORDER ID: {order_id}\n"
            f"🕐 {now_utc()}"
        )

        log(text)
        tg(text)

        return True, "ORDER ACCEPTED"

    # ========================================================
    # AUTH ERROR
    # ========================================================

    message = "order failed"

    if isinstance(body, dict):

        message = (
            body.get("msg")
            or body.get("message")
            or message
        )

    if (
        code in (1103, "1103")
        or status == 401
    ):

        AUTH_OK = False

        lock = (
            "🚨 ATI ORDER AUTH FAILED\n"
            f"🪙 {market['symbol']}\n"
            f"❌ HTTP {status}\n"
            f"❌ CODE: {code}\n"
            f"❌ {message}\n"
            "🛑 REAL BUY LOCKED\n"
            "🛑 NO FURTHER ORDER WILL BE SENT"
        )

        log(lock)
        tg(lock)

        return False, "AUTH LOCKED"

    return False, str(message)


# ============================================================
# MAIN
# ============================================================

def main():

    log("=" * 60)

    log(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )

    log(
        "📡 TABDEAL API: CONNECTING..."
    )

    log(
        "📊 SCAN: STARTING"
    )

    log(
        "⏱ TIMEFRAME: 5m"
    )

    log(
        "🕯 CLOSED CANDLE: YES"
    )

    log(
        "💵 ORDER MODE: FIXED USDT AMOUNT"
    )

    log(
        f"💰 ORDER AMOUNT: "
        f"{ORDER_USDT} USDT"
    )

    log(
        "🟢 REAL ORDERS: "
        + (
            "ENABLED"
            if LIVE_TRADING
            else "DISABLED"
        )
    )

    log(
        "🔐 AUTH: RAW HMAC-SHA256"
    )

    log(
        f"🕐 {now_utc()}"
    )

    tg(
        f"⚡ ATI CRYPTO BOT {VERSION}\n"
        "📡 TABDEAL API: CONNECTING...\n"
        "📊 SCAN: STARTING\n"
        f"💰 ORDER AMOUNT: {ORDER_USDT} USDT\n"
        "🔐 RAW HMAC-SHA256\n"
        "🕐 "
        + now_utc()
    )

    # ========================================================
    # CREDENTIAL CHECK
    # ========================================================

    if not API_KEY or not API_SECRET:

        authenticate()
        return

    # ========================================================
    # SERVER TIME
    # ========================================================

    log(
        "📡 TABDEAL API: "
        "CHECKING SERVER TIME..."
    )

    server_time_sync()

    # ========================================================
    # EXCHANGE INFO
    # ========================================================

    log(
        "📡 TABDEAL API: "
        "CHECKING EXCHANGE INFO..."
    )

    markets = exchange_info()

    if not markets:

        text = (
            f"🚨 ATI EXCHANGE INFO FAILED "
            f"{VERSION}\n"
            "🛑 SCAN STOPPED\n"
            "🛑 NO ORDER WAS SENT"
        )

        log(text)
        tg(text)

        return

    log(
        f"✅ EXCHANGE INFO OK {VERSION}"
    )

    log(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
    )

    tg(
        f"✅ EXCHANGE INFO OK {VERSION}\n"
        f"📊 USDT MARKETS: {len(markets)}\n"
        "🔐 NOW TESTING PRIVATE API AUTH..."
    )

    # ========================================================
    # AUTH BEFORE REAL ORDER
    # ========================================================

    if not authenticate():
        return

    # ========================================================
    # DEEP SCAN
    # ========================================================

    scan_markets = markets[
        :DEEP_SCAN_LIMIT
    ]

    log(
        f"🔎 DEEP SCAN: "
        f"{len(scan_markets)} markets"
    )

    candidates = []

    for market in scan_markets:

        try:

            result = score_market(
                market
            )

            if (
                result
                and result["score"] >= 6
                and result["move"] > 0
            ):

                candidates.append(
                    result
                )

        except Exception as e:

            log(
                f"⚠️ "
                f"{market['symbol']}: "
                f"{e}"
            )

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["pressure"],
            x["move"]
        ),
        reverse=True
    )

    # ========================================================
    # NO CANDIDATES
    # ========================================================

    if not candidates:

        text = (
            f"✅ ATI SCAN FINISHED "
            f"{VERSION}\n"
            f"📊 MARKETS: {len(markets)}\n"
            f"🔎 DEEP SCAN: "
            f"{len(scan_markets)}\n"
            "🟢 CANDIDATES: 0\n"
            f"🟢 AUTH: "
            f"{'OK' if AUTH_OK else 'LOCKED'}\n"
            f"🚨 REAL BUY THIS RUN: "
            f"{REAL_BUYS_THIS_RUN}\n"
            f"🕐 {now_utc()}"
        )

        log(text)
        tg(text)

        return

    # ========================================================
    # TOP 10
    # ========================================================

    top = candidates[:10]

    lines = [
        f"🚨 ATI BUY CANDIDATES {VERSION}",
        f"📊 MARKETS: {len(markets)}",
        f"🟢 CANDIDATES: {len(candidates)}"
    ]

    for c in top:

        lines.append(
            f"🟢 {c['symbol']} | "
            f"SCORE {c['score']} | "
            f"MOVE {c['move']:.2f}% | "
            f"PRESSURE "
            f"{c['pressure']:.1f}%"
        )

    tg(
        "\n".join(lines)
    )

    # ========================================================
    # ONE REAL BUY MAXIMUM
    # ========================================================

    selected = candidates[0]

    selected_market = next(
        (
            m for m in markets
            if m["symbol"]
            == selected["symbol"]
        ),
        None
    )

    if selected_market:

        ok, reason = place_real_buy(
            selected,
            selected_market
        )

        log(
            f"🚨 REAL BUY RESULT: "
            f"{ok} | {reason}"
        )

    tg(
        f"📊 BUY RESULT SUMMARY "
        f"{VERSION}\n"
        f"📌 TOTAL BUY: "
        f"{REAL_BUYS_THIS_RUN}\n"
        f"🟢 AUTH: "
        f"{'OK' if AUTH_OK else 'LOCKED'}\n"
        f"🕐 {now_utc()}"
    )


if __name__ == "__main__":
    main()
