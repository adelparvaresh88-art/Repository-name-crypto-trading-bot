import os
import time
import json
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.18
#
# TABDEAL SPOT AUTH FIX
#
# IMPORTANT:
#   timestamp = INTEGER milliseconds
#   parameter order:
#       user params -> timestamp -> recvWindow
#   signature:
#       HMAC-SHA256(secret, EXACT QUERY STRING)
#
# REAL BUY:
#   disabled until authentication succeeds
#   maximum 1 BUY per workflow run
# ============================================================

VERSION = "V40.2.18"

BASE_URL = "https://api1.tabdeal.org"

SPOT_PUBLIC = BASE_URL + "/r/api/v1"
SPOT_PRIVATE = BASE_URL + "/r/api/v1"

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "false")
    .strip()
    .lower()
    == "true"
)

try:
    ORDER_USDT = Decimal(
        os.getenv("ORDER_QTY", "2").strip()
    )
except Exception:
    ORDER_USDT = Decimal("2")

RECV_WINDOW = 10000
REQUEST_TIMEOUT = 20

MAX_REAL_BUYS_PER_RUN = 1

session = requests.Session()

MARKET_RULES = {}

AUTH_OK = False
REAL_BUY_UNLOCKED = False

REAL_BUYS_THIS_RUN = 0


# ============================================================
# HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def log(message):
    print(message, flush=True)


def notify(message):
    log(message)

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )
    except Exception as e:
        log("TELEGRAM ERROR: " + str(e))


def D(value, default=Decimal("0")):
    try:
        return Decimal(str(value))
    except Exception:
        return default


def DS(value):
    value = D(value)

    text = format(value, "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def floor_step(value, step):
    value = D(value)
    step = D(step)

    if step <= 0:
        return value

    units = (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    )

    return units * step


def percentage(a, b):
    a = D(a)
    b = D(b)

    if b == 0:
        return Decimal("0")

    return (
        (a - b)
        / b
        * Decimal("100")
    )


# ============================================================
# PUBLIC REQUEST
# ============================================================

def public_get(path, params=None):
    try:
        return session.get(
            SPOT_PUBLIC + path,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as e:
        log(
            "PUBLIC REQUEST ERROR "
            + path
            + ": "
            + str(e)
        )

        return None


# ============================================================
# TABDEAL SIGNATURE
# ============================================================

def make_signed_params(extra=None):
    """
    Exact signing model:

        existing parameters
        timestamp
        recvWindow

    timestamp is INTEGER milliseconds.

    The query string used for HMAC is constructed once.
    The same values are then sent in the request.
    """

    params = {}

    if extra:
        for key, value in extra.items():
            if value is None:
                continue

            params[str(key)] = str(value)

    # IMPORTANT:
    # integer milliseconds, not float.
    params["timestamp"] = str(
        int(time.time() * 1000)
    )

    params["recvWindow"] = str(
        RECV_WINDOW
    )

    # Do not sort.
    # Preserve insertion order.
    query_string = urlencode(
        params,
        doseq=False,
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    params["signature"] = signature

    return params, query_string, signature


def private_get(path, extra=None):
    params, query_string, signature = (
        make_signed_params(extra)
    )

    log(
        "🔐 SIGNED GET "
        + path
        + " | "
        + query_string
    )

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Accept": "application/json",
    }

    return session.get(
        SPOT_PRIVATE + path,
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )


def private_post(path, extra=None):
    params, query_string, signature = (
        make_signed_params(extra)
    )

    log(
        "🔐 SIGNED POST "
        + path
        + " | "
        + query_string
    )

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Accept": "application/json",
    }

    # Tabdeal Postman collection uses form parameters.
    return session.post(
        SPOT_PRIVATE + path,
        data=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():
    response = public_get(
        "/exchangeInfo"
    )

    if response is None:
        return None

    if not response.ok:
        log(
            "EXCHANGE INFO ERROR "
            + str(response.status_code)
            + " "
            + response.text[:500]
        )

        return None

    try:
        return response.json()
    except Exception as e:
        log(
            "EXCHANGE INFO JSON ERROR: "
            + str(e)
        )

        return None


def find_symbols(data):
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    if isinstance(
        data.get("symbols"),
        list,
    ):
        return data["symbols"]

    for key in (
        "data",
        "result",
    ):
        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            if isinstance(
                value.get("symbols"),
                list,
            ):
                return value["symbols"]

            if isinstance(
                value.get("data"),
                list,
            ):
                return value["data"]

    return []


def clean_symbol(value):
    value = str(
        value or ""
    ).upper()

    return (
        value
        .replace("/", "")
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )


def parse_exchange_info(data):
    global MARKET_RULES

    MARKET_RULES = {}

    symbols = find_symbols(data)

    for item in symbols:
        if not isinstance(item, dict):
            continue

        raw_symbol = (
            item.get("symbol")
            or item.get("market")
            or item.get("name")
            or item.get("tabdealSymbol")
            or ""
        )

        symbol = clean_symbol(
            raw_symbol
        )

        base = clean_symbol(
            item.get("baseAsset")
            or item.get("base")
            or ""
        )

        quote = clean_symbol(
            item.get("quoteAsset")
            or item.get("quote")
            or ""
        )

        if (
            quote == "USDT"
            and base
        ):
            symbol = base + "USDT"

        if not symbol.endswith("USDT"):
            continue

        status = str(
            item.get(
                "status",
                "TRADING",
            )
        ).upper()

        if status not in (
            "",
            "TRADING",
            "ENABLED",
            "ACTIVE",
        ):
            continue

        min_qty = Decimal("0")
        max_qty = Decimal("0")
        step_size = Decimal("0")
        min_notional = Decimal("0")

        filters = item.get(
            "filters",
            [],
        )

        if isinstance(
            filters,
            list,
        ):
            for f in filters:
                if not isinstance(
                    f,
                    dict,
                ):
                    continue

                filter_type = str(
                    f.get(
                        "filterType",
                        "",
                    )
                ).upper()

                if filter_type in (
                    "LOT_SIZE",
                    "MARKET_LOT_SIZE",
                ):
                    min_qty = max(
                        min_qty,
                        D(
                            f.get(
                                "minQty"
                            )
                        ),
                    )

                    max_qty = D(
                        f.get(
                            "maxQty"
                        )
                    )

                    candidate_step = D(
                        f.get(
                            "stepSize"
                        )
                    )

                    if (
                        candidate_step > 0
                        and step_size == 0
                    ):
                        step_size = (
                            candidate_step
                        )

                elif filter_type in (
                    "MIN_NOTIONAL",
                    "NOTIONAL",
                ):
                    min_notional = max(
                        min_notional,
                        D(
                            f.get(
                                "minNotional"
                            )
                        ),
                    )

        if step_size <= 0:
            step_size = D(
                item.get(
                    "stepSize"
                )
                or item.get(
                    "quantityStep"
                )
            )

        if min_qty <= 0:
            min_qty = D(
                item.get(
                    "minQty"
                )
                or item.get(
                    "minQuantity"
                )
            )

        if min_notional <= 0:
            min_notional = D(
                item.get(
                    "minNotional"
                )
                or item.get(
                    "minOrderValue"
                )
            )

        MARKET_RULES[symbol] = {
            "minQty": min_qty,
            "maxQty": max_qty,
            "stepSize": step_size,
            "minNotional": min_notional,
            "raw": item,
        }


# ============================================================
# API AUTHENTICATION
# ============================================================

def authenticate():
    global AUTH_OK

    AUTH_OK = False

    if not API_KEY:
        notify(
            f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
            "❌ TABDEAL_API_KEY IS EMPTY\n"
            "🛑 REAL BUY LOCKED"
        )

        return False

    if not API_SECRET:
        notify(
            f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
            "❌ TABDEAL_API_SECRET IS EMPTY\n"
            "🛑 REAL BUY LOCKED"
        )

        return False

    try:
        response = private_get(
            "/account"
        )

        if response is None:
            notify(
                f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
                "❌ NO RESPONSE\n"
                "🛑 REAL BUY LOCKED"
            )

            return False

        try:
            body = response.json()
        except Exception:
            body = {}

        code = (
            body.get("code")
            if isinstance(body, dict)
            else None
        )

        message = (
            body.get("msg")
            or body.get("message")
            or ""
            if isinstance(body, dict)
            else ""
        )

        if (
            response.status_code == 200
            and code in (
                None,
                0,
                "0",
            )
        ):
            AUTH_OK = True

            notify(
                f"🔐 ATI API AUTH OK {VERSION}\n\n"
                "✅ HTTP 200\n"
                "✅ HMAC-SHA256\n"
                "✅ INTEGER TIMESTAMP MS\n"
                "✅ EXACT SIGNED PARAMETERS\n"
                "✅ ACCOUNT ACCESS OK"
            )

            return True

        if (
            response.status_code == 401
            or str(code) == "1103"
        ):
            notify(
                f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
                f"❌ HTTP {response.status_code}\n"
                f"❌ CODE: {code}\n"
                "❌ Invalid Signature\n\n"
                "🔐 HMAC-SHA256\n"
                "🔐 INTEGER timestamp\n"
                "🔐 timestamp → recvWindow\n"
                "🔐 EXACT QUERY SIGNED/SENT\n\n"
                "🛑 REAL BUY LOCKED\n"
                "🛑 NO ORDER WAS SENT"
            )

            return False

        notify(
            f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
            f"❌ HTTP {response.status_code}\n"
            f"❌ CODE: {code}\n"
            f"❌ {message or response.text[:500]}\n\n"
            "🛑 REAL BUY LOCKED"
        )

        return False

    except Exception as e:
        notify(
            f"🚨 ATI API AUTH EXCEPTION {VERSION}\n\n"
            f"❌ {e}\n"
            "🛑 REAL BUY LOCKED"
        )

        return False


# ============================================================
# BALANCE
# ============================================================

def get_usdt_balance():
    if not AUTH_OK:
        return Decimal("0")

    try:
        response = private_get(
            "/account"
        )

        if (
            response is None
            or response.status_code != 200
        ):
            return Decimal("0")

        data = response.json()

        if not isinstance(
            data,
            dict,
        ):
            return Decimal("0")

        balances = data.get(
            "balances"
        )

        if not isinstance(
            balances,
            list,
        ):
            nested = data.get(
                "data"
            )

            if isinstance(
                nested,
                dict,
            ):
                balances = nested.get(
                    "balances"
                )

        if not isinstance(
            balances,
            list,
        ):
            return Decimal("0")

        for balance in balances:
            if not isinstance(
                balance,
                dict,
            ):
                continue

            asset = str(
                balance.get(
                    "asset"
                )
                or balance.get(
                    "currency"
                )
                or ""
            ).upper()

            if asset != "USDT":
                continue

            return D(
                balance.get(
                    "free"
                )
                or balance.get(
                    "available"
                )
                or balance.get(
                    "availableBalance"
                )
                or "0"
            )

    except Exception as e:
        log(
            "BALANCE ERROR: "
            + str(e)
        )

    return Decimal("0")


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):
    try:
        response = public_get(
            "/trades",
            {
                "symbol": symbol,
                "limit": 1000,
            },
        )

        if (
            response is None
            or not response.ok
        ):
            return []

        data = response.json()

        if isinstance(
            data,
            list,
        ):
            return data

        if isinstance(
            data,
            dict,
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
                    list,
                ):
                    return value

    except Exception:
        pass

    return []


def trade_price(trade):
    if not isinstance(
        trade,
        dict,
    ):
        return Decimal("0")

    return D(
        trade.get("price")
        or trade.get("p")
        or "0"
    )


def trade_quantity(trade):
    if not isinstance(
        trade,
        dict,
    ):
        return Decimal("0")

    return D(
        trade.get("qty")
        or trade.get("quantity")
        or trade.get("q")
        or trade.get("amount")
        or "0"
    )


def trade_time(trade):
    if not isinstance(
        trade,
        dict,
    ):
        return 0

    try:
        return int(
            trade.get("time")
            or trade.get("timestamp")
            or trade.get("T")
            or 0
        )
    except Exception:
        return 0


# ============================================================
# 5M CANDLES
# ============================================================

def make_5m_candles(trades):
    buckets = {}

    for trade in trades:
        price = trade_price(
            trade
        )

        quantity = trade_quantity(
            trade
        )

        timestamp = trade_time(
            trade
        )

        if (
            price <= 0
            or timestamp <= 0
        ):
            continue

        if timestamp < 100000000000:
            timestamp *= 1000

        bucket = (
            timestamp // 300000
        ) * 300000

        if bucket not in buckets:
            buckets[bucket] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": Decimal("0"),
            }

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

        candle["volume"] += quantity

    result = []

    for timestamp in sorted(
        buckets.keys()
    ):
        candle = dict(
            buckets[timestamp]
        )

        candle["time"] = timestamp

        result.append(
            candle
        )

    return result


# ============================================================
# SIGNAL
# ============================================================

def build_signal(
    symbol,
    candles,
):
    if len(candles) < 8:
        return None

    # Only CLOSED candles.
    closed = candles[:-1]

    if len(closed) < 7:
        return None

    last = closed[-1]
    previous = closed[-2]

    lookback = closed[-7:-1]

    resistance = max(
        candle["high"]
        for candle in lookback
    )

    recent_low = min(
        candle["low"]
        for candle in lookback
    )

    price = last["close"]

    if (
        price <= 0
        or resistance <= 0
    ):
        return None

    candle_range = (
        last["high"]
        - last["low"]
    )

    if candle_range <= 0:
        return None

    body_ratio = (
        abs(
            last["close"]
            - last["open"]
        )
        / candle_range
    )

    breakout = (
        price > resistance
        and previous["close"]
        <= resistance
    )

    hold = (
        price
        >= resistance
        * Decimal("0.998")
    )

    momentum = (
        price
        > previous["close"]
    )

    move = percentage(
        price,
        recent_low,
    )

    breakout_move = percentage(
        price,
        resistance,
    )

    # Anti-chase.
    if breakout_move > Decimal("8"):
        return None

    if move > Decimal("15"):
        return None

    if body_ratio < Decimal("0.45"):
        return None

    if not breakout and not (
        hold and momentum
    ):
        return None

    score = 0

    if breakout:
        score += 6

    if hold:
        score += 3

    if momentum:
        score += 2

    if body_ratio >= Decimal("0.60"):
        score += 2

    if breakout_move >= Decimal("0.20"):
        score += 1

    if score < 9:
        return None

    sl = (
        resistance
        * Decimal("0.985")
    )

    if sl >= price:
        sl = (
            price
            * Decimal("0.985")
        )

    risk = price - sl

    if risk <= 0:
        return None

    tp1 = (
        price
        + risk * Decimal("1.5")
    )

    tp2 = (
        price
        + risk * Decimal("2.5")
    )

    return {
        "symbol": symbol,
        "price": price,
        "score": score,
        "move": move,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


# ============================================================
# QUANTITY
# ============================================================

def calculate_quantity(
    symbol,
    price,
):
    rules = MARKET_RULES.get(
        symbol
    )

    if not rules:
        return (
            None,
            "NO MARKET RULES",
        )

    if price <= 0:
        return (
            None,
            "INVALID PRICE",
        )

    if ORDER_USDT <= 0:
        return (
            None,
            "ORDER_USDT <= 0",
        )

    raw_quantity = (
        ORDER_USDT / price
    )

    step = rules[
        "stepSize"
    ]

    min_qty = rules[
        "minQty"
    ]

    max_qty = rules[
        "maxQty"
    ]

    min_notional = rules[
        "minNotional"
    ]

    if step > 0:
        quantity = floor_step(
            raw_quantity,
            step,
        )
    else:
        quantity = raw_quantity

    if quantity <= 0:
        return (
            None,
            "quantity <= 0",
        )

    if (
        min_qty > 0
        and quantity < min_qty
    ):
        return (
            None,
            "quantity "
            + DS(quantity)
            + " < minQty "
            + DS(min_qty),
        )

    if (
        max_qty > 0
        and quantity > max_qty
    ):
        quantity = floor_step(
            max_qty,
            step,
        )

    order_value = (
        quantity * price
    )

    if (
        min_notional > 0
        and order_value
        < min_notional
    ):
        return (
            None,
            "order value "
            + DS(order_value)
            + " < MIN_NOTIONAL "
            + DS(min_notional),
        )

    return (
        quantity,
        None,
    )


# ============================================================
# REAL BUY
# ============================================================

def place_real_buy(
    symbol,
    price,
):
    global REAL_BUYS_THIS_RUN
    global REAL_BUY_UNLOCKED

    if not LIVE_TRADING:
        return (
            False,
            "LIVE_TRADING=false",
        )

    if not AUTH_OK:
        return (
            False,
            "AUTH NOT OK",
        )

    if not REAL_BUY_UNLOCKED:
        return (
            False,
            "REAL BUY LOCKED",
        )

    if (
        REAL_BUYS_THIS_RUN
        >= MAX_REAL_BUYS_PER_RUN
    ):
        return (
            False,
            "MAX BUY PER RUN REACHED",
        )

    quantity, error = (
        calculate_quantity(
            symbol,
            price,
        )
    )

    if quantity is None:
        return (
            False,
            error,
        )

    balance = get_usdt_balance()

    if balance < ORDER_USDT:
        return (
            False,
            "USDT balance "
            + DS(balance)
            + " < order "
            + DS(ORDER_USDT),
        )

    notify(
        f"🚨 REAL BUY START {VERSION}\n\n"
        f"🪙 {symbol}\n"
        f"💰 PRICE: {DS(price)}\n"
        f"💵 USDT: {DS(ORDER_USDT)}\n"
        f"📦 QTY: {DS(quantity)}\n"
        "🛡 MAX BUY/RUN: 1"
    )

    # Spot order fields.
    #
    # We use tabdealSymbol because Tabdeal's official
    # Spot API documentation uses this field on private
    # Spot order endpoints.
    #
    # First try the normalized USDT symbol.
    order_params = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quantity": DS(quantity),
    }

    try:
        response = private_post(
            "/order",
            order_params,
        )

        try:
            body = response.json()
        except Exception:
            body = {}

        code = (
            body.get("code")
            if isinstance(
                body,
                dict,
            )
            else None
        )

        if (
            response.status_code == 401
            or str(code) == "1103"
        ):
            REAL_BUY_UNLOCKED = False

            notify(
                f"🚨 REAL BUY AUTH ERROR {VERSION}\n\n"
                f"🪙 {symbol}\n"
                f"❌ HTTP {response.status_code}\n"
                f"❌ CODE: {code}\n"
                "❌ Invalid Signature\n\n"
                "🛑 REAL BUY LOCKED\n"
                "🛑 NO RETRY THIS RUN"
            )

            return (
                False,
                "INVALID SIGNATURE",
            )

        if (
            response.status_code >= 400
            or (
                isinstance(
                    body,
                    dict,
                )
                and code not in (
                    None,
                    0,
                    "0",
                )
            )
        ):
            notify(
                f"🚨 REAL TRADE ERROR {VERSION}\n\n"
                f"🪙 {symbol}\n"
                f"❌ HTTP {response.status_code}\n"
                f"❌ CODE: {code}\n"
                f"❌ {body or response.text[:700]}"
            )

            return (
                False,
                str(body),
            )

        REAL_BUYS_THIS_RUN += 1

        order_id = ""

        if isinstance(
            body,
            dict,
        ):
            order_id = str(
                body.get(
                    "orderId"
                )
                or body.get(
                    "id"
                )
                or ""
            )

        notify(
            f"✅ REAL BUY SUCCESS {VERSION}\n\n"
            f"🟢 {symbol}\n"
            f"💵 USDT: {DS(ORDER_USDT)}\n"
            f"📦 QTY: {DS(quantity)}\n"
            f"🆔 ORDER: {order_id}\n"
            "🛒 BUY COUNT: 1/1"
        )

        return (
            True,
            order_id,
        )

    except Exception as e:
        notify(
            f"🚨 REAL ORDER EXCEPTION {VERSION}\n\n"
            f"🪙 {symbol}\n"
            f"❌ {e}\n"
            "🛑 NO RETRY"
        )

        return (
            False,
            str(e),
        )


# ============================================================
# SCAN
# ============================================================

def scan_markets():
    symbols = [
        symbol
        for symbol in MARKET_RULES
        if symbol.endswith("USDT")
    ]

    candidates = []

    for symbol in symbols:
        try:
            trades = get_trades(
                symbol
            )

            if len(trades) < 100:
                continue

            candles = make_5m_candles(
                trades
            )

            candidate = build_signal(
                symbol,
                candles,
            )

            if candidate:
                candidates.append(
                    candidate
                )

        except Exception as e:
            log(
                "SCAN ERROR "
                + symbol
                + ": "
                + str(e)
            )

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["move"],
        ),
        reverse=True,
    )

    return candidates[:10]


# ============================================================
# MAIN
# ============================================================

def main():
    global REAL_BUY_UNLOCKED

    notify(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        "📡 TABDEAL API: CONNECTING...\n"
        "📊 SCAN: STARTING\n"
        "⏱ TIMEFRAME: 5m\n"
        "🕯 CLOSED CANDLE: YES\n"
        "💵 ORDER MODE: FIXED USDT AMOUNT\n"
        f"💰 ORDER AMOUNT: {DS(ORDER_USDT)} USDT\n"
        + (
            "🟢 REAL ORDERS: ENABLED\n"
            if LIVE_TRADING
            else "🟡 REAL ORDERS: DISABLED\n"
        )
        + "🔐 AUTH: TABDEAL SPOT HMAC FIX\n"
        + f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # ENVIRONMENT
    # --------------------------------------------------------

    if not API_KEY or not API_SECRET:
        notify(
            f"🛑 ATI SAFE STOP {VERSION}\n\n"
            "❌ TABDEAL API CREDENTIALS MISSING\n"
            "🛑 REAL BUY LOCKED"
        )
        return

    # --------------------------------------------------------
    # EXCHANGE INFO
    # --------------------------------------------------------

    notify(
        "📡 TABDEAL API: CHECKING EXCHANGE INFO..."
    )

    exchange_info = (
        get_exchange_info()
    )

    if exchange_info is None:
        notify(
            f"🛑 ATI SAFE STOP {VERSION}\n\n"
            "❌ EXCHANGE INFO FAILED\n"
            "🛑 REAL BUY LOCKED"
        )
        return

    parse_exchange_info(
        exchange_info
    )

    notify(
        f"✅ EXCHANGE INFO OK {VERSION}\n\n"
        f"📊 USDT MARKETS: "
        f"{len(MARKET_RULES)}"
    )

    # --------------------------------------------------------
    # PRIVATE AUTH
    # --------------------------------------------------------

    if not authenticate():
        return

    # Authentication passed.
    REAL_BUY_UNLOCKED = (
        LIVE_TRADING
    )

    # --------------------------------------------------------
    # BALANCE
    # --------------------------------------------------------

    balance = get_usdt_balance()

    notify(
        f"💰 USDT BALANCE {VERSION}\n\n"
        f"💵 AVAILABLE: {DS(balance)} USDT\n"
        f"🧾 ORDER: {DS(ORDER_USDT)} USDT"
    )

    if (
        LIVE_TRADING
        and balance < ORDER_USDT
    ):
        REAL_BUY_UNLOCKED = False

        notify(
            f"🛑 ATI SAFE STOP {VERSION}\n\n"
            "❌ INSUFFICIENT USDT BALANCE\n"
            f"💰 AVAILABLE: {DS(balance)}\n"
            f"💵 REQUIRED: {DS(ORDER_USDT)}\n"
            "🛑 REAL BUY LOCKED"
        )

        return

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    candidates = (
        scan_markets()
    )

    notify(
        f"📊 ATI SCAN FINISHED {VERSION}\n\n"
        f"📊 MARKETS: {len(MARKET_RULES)}\n"
        f"🟢 CANDIDATES: {len(candidates)}\n"
        "🎯 TOP 10\n"
        f"🚨 REAL BUY THIS RUN: "
        f"{REAL_BUYS_THIS_RUN}"
    )

    if not candidates:
        notify(
            f"📭 ATI NO BUY CANDIDATE {VERSION}\n\n"
            "No confirmed 5m breakout candidate.\n"
            "🛑 No order sent."
        )

        return

    # --------------------------------------------------------
    # TOP CANDIDATES
    # --------------------------------------------------------

    lines = [
        f"🎯 ATI TOP CANDIDATES {VERSION}",
        "",
    ]

    for index, candidate in enumerate(
        candidates,
        1,
    ):
        lines.append(
            f"{index}. "
            f"{candidate['symbol']} | "
            f"SCORE {candidate['score']} | "
            f"PRICE {DS(candidate['price'])}"
        )

    notify(
        "\n".join(lines)
    )

    # --------------------------------------------------------
    # PAPER MODE
    # --------------------------------------------------------

    if not LIVE_TRADING:
        notify(
            f"🟡 PAPER MODE {VERSION}\n\n"
            "🛑 REAL BUY DISABLED\n"
            "📌 No order was sent."
        )

        return

    # --------------------------------------------------------
    # ONE REAL BUY
    # --------------------------------------------------------

    if not REAL_BUY_UNLOCKED:
        notify(
            f"🛑 ATI SAFE STOP {VERSION}\n\n"
            "❌ REAL BUY IS LOCKED\n"
            "🛑 NO ORDER WAS SENT"
        )

        return

    candidate = candidates[0]

    notify(
        f"🚨 ATI BUY CANDIDATE {VERSION}\n\n"
        f"🪙 {candidate['symbol']}\n"
        f"💰 PRICE: {DS(candidate['price'])}\n"
        f"📊 SCORE: {candidate['score']}\n"
        f"📈 MOVE: {DS(candidate['move'])}%\n"
        f"🛑 SL: {DS(candidate['sl'])}\n"
        f"🎯 TP1: {DS(candidate['tp1'])}\n"
        f"🎯 TP2: {DS(candidate['tp2'])}"
    )

    success, result = (
        place_real_buy(
            candidate["symbol"],
            candidate["price"],
        )
    )

    if not success:
        notify(
            f"🛑 ATI BUY NOT EXECUTED {VERSION}\n\n"
            f"🪙 {candidate['symbol']}\n"
            f"❌ {result}\n"
            "🛑 NO RETRY THIS RUN"
        )

        return

    notify(
        f"🏁 ATI RUN COMPLETE {VERSION}\n\n"
        "✅ REAL BUY COMPLETED\n"
        f"🪙 {candidate['symbol']}\n"
        f"💵 {DS(ORDER_USDT)} USDT\n"
        "🛒 BUY COUNT: 1/1\n"
        f"🕐 {utc_now()}"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        REAL_BUY_UNLOCKED = False

        notify(
            f"🛑 ATI STOPPED {VERSION}"
        )

    except Exception as e:
        REAL_BUY_UNLOCKED = False

        notify(
            f"🚨 ATI FATAL ERROR {VERSION}\n\n"
            f"❌ {e}\n"
            "🛑 REAL BUY LOCKED"
        )

        raise
