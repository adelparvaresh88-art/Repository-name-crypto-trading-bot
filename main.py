import os
import time
import json
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.45-REAL
# TABDEAL SPOT
# TELEGRAM + BALANCE-AWARE REAL TRADING
# ============================================================

VERSION = "V40.2.45-REAL"

BASE = "https://api1.tabdeal.org"

PUBLIC_ROOT = f"{BASE}/r/api/v1"
SIGNED_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 20
RECV_WINDOW = 10000

STATE_FILE = "ati_state.json"


# ============================================================
# API KEYS
# ============================================================

API_KEY = (
    os.getenv("TABDIL_API_KEY", "").strip()
    or os.getenv("TABDEAL_API_KEY", "").strip()
)

API_SECRET = (
    os.getenv("TABDIL_API_SECRET", "").strip()
    or os.getenv("TABDEAL_API_SECRET", "").strip()
)


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# REAL TRADING
# ============================================================

REAL_TRADING = (
    os.getenv(
        "LIVE_TRADING",
        os.getenv(
            "REAL_TRADING",
            "false"
        )
    ).strip().lower()
    in ("1", "true", "yes", "on")
)


# ============================================================
# ORDER SETTINGS
# ============================================================

try:
    ORDER_USDT = Decimal(
        os.getenv(
            "ORDER_USDT",
            os.getenv(
                "ORDER_QTY",
                "2"
            )
        ).strip()
    )
except Exception:
    ORDER_USDT = Decimal("2")

if ORDER_USDT <= 0:
    ORDER_USDT = Decimal("2")


# ============================================================
# BALANCE RESERVE
# ============================================================

try:
    BALANCE_RESERVE_USDT = Decimal(
        os.getenv(
            "BALANCE_RESERVE_USDT",
            "0.02"
        ).strip()
    )
except Exception:
    BALANCE_RESERVE_USDT = Decimal("0.02")

if BALANCE_RESERVE_USDT < 0:
    BALANCE_RESERVE_USDT = Decimal("0")


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": f"ATI-Crypto-Bot/{VERSION}",
    "Accept": "application/json",
})


# ============================================================
# LOG
# ============================================================

def log(message):
    print(str(message), flush=True)


def utc_now():
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# DECIMAL
# ============================================================

def dec(value, default="0"):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def decimal_text(value):

    value = dec(value)

    text = format(
        value,
        "f"
    )

    if "." in text:
        text = (
            text
            .rstrip("0")
            .rstrip(".")
        )

    return text or "0"


def floor_step(value, step):

    value = dec(value)
    step = dec(step)

    if step <= 0:
        return value

    units = (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    )

    return units * step


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):

    if not TELEGRAM_TOKEN:
        log("TELEGRAM ERROR: TELEGRAM_BOT_TOKEN IS EMPTY")
        return False

    if not TELEGRAM_CHAT_ID:
        log("TELEGRAM ERROR: TELEGRAM_CHAT_ID IS EMPTY")
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": str(message),
    }

    try:

        response = SESSION.post(
            url,
            json=payload,
            timeout=15
        )

        log(
            f"TELEGRAM HTTP: {response.status_code}"
        )

        if response.status_code != 200:

            log(
                "TELEGRAM ERROR: "
                f"{response.text[:500]}"
            )

            return False

        data = response_json(response)

        if isinstance(data, dict):
            if data.get("ok") is False:
                log(
                    "TELEGRAM API ERROR: "
                    f"{json.dumps(data, ensure_ascii=False)}"
                )
                return False

        return True

    except Exception as exc:

        log(
            f"TELEGRAM EXCEPTION: {exc}"
        )

        return False


def telegram_test():

    log("TELEGRAM TEST: STARTING")

    ok = telegram(
        "🟢 ATI TELEGRAM TEST\n"
        f"⚡ {VERSION}\n"
        f"🕐 {utc_now()}\n"
        "✅ Telegram connection is working."
    )

    if ok:
        log("TELEGRAM TEST: SUCCESS")
    else:
        log("TELEGRAM TEST: FAILED")

    return ok


# ============================================================
# JSON
# ============================================================

def response_json(response):

    try:
        return response.json()

    except Exception:

        return {
            "raw": response.text
        }


# ============================================================
# HMAC
# ============================================================

def create_signed_parameters(parameters=None):

    params_object = {}

    if parameters:

        for key, value in parameters.items():

            if key in (
                "signature",
                "timestamp",
                "recvWindow"
            ):
                continue

            if value is None:
                continue

            value = str(value)

            if not value.strip():
                continue

            params_object[key] = value

    timestamp = int(
        time.time() * 1000
    )

    params_object[
        "timestamp"
    ] = timestamp

    params_object[
        "recvWindow"
    ] = RECV_WINDOW

    query_string = "&".join(
        f"{key}={value}"
        for key, value in params_object.items()
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return (
        params_object,
        signature,
        query_string
    )


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(
    method,
    path,
    params=None,
    order=False
):

    if not API_KEY:
        raise RuntimeError(
            "TABDIL/TABDEAL API KEY IS MISSING"
        )

    if not API_SECRET:
        raise RuntimeError(
            "TABDIL/TABDEAL API SECRET IS MISSING"
        )

    method = method.upper()

    (
        signed_params,
        signature,
        query_string
    ) = create_signed_parameters(params)

    request_params = dict(
        signed_params
    )

    request_params[
        "signature"
    ] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Accept": "application/json",
        "User-Agent": f"ATI-Crypto-Bot/{VERSION}",
    }

    root = (
        ORDER_ROOT
        if order
        else SIGNED_ROOT
    )

    url = f"{root}{path}"

    log(
        f"REQUEST: {method} {url}"
    )

    log(
        "SIGN DEBUG: "
        f"timestamp={signed_params['timestamp']}"
    )

    log(
        "SIGN DEBUG: "
        f"recvWindow={signed_params['recvWindow']}"
    )

    try:

        if method == "GET":

            response = SESSION.get(
                url,
                params=request_params,
                headers=headers,
                timeout=TIMEOUT
            )

        elif method == "POST":

            headers[
                "Content-Type"
            ] = "application/x-www-form-urlencoded"

            response = SESSION.post(
                url,
                data=request_params,
                headers=headers,
                timeout=TIMEOUT
            )

        elif method == "DELETE":

            response = SESSION.delete(
                url,
                params=request_params,
                headers=headers,
                timeout=TIMEOUT
            )

        elif method == "PUT":

            headers[
                "Content-Type"
            ] = "application/x-www-form-urlencoded"

            response = SESSION.put(
                url,
                data=request_params,
                headers=headers,
                timeout=TIMEOUT
            )

        else:

            response = SESSION.request(
                method,
                url,
                params=request_params,
                headers=headers,
                timeout=TIMEOUT
            )

    except requests.RequestException as exc:

        raise RuntimeError(
            f"NETWORK ERROR: {exc}"
        )

    data = response_json(response)

    if (
        response.status_code < 200
        or response.status_code >= 300
    ):

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{json.dumps(data, ensure_ascii=False)}"
        )

    if isinstance(data, dict):

        code = data.get("code")

        if str(code) == "1103":

            raise RuntimeError(
                "HTTP 401: Invalid Signature"
            )

    return data


# ============================================================
# AUTH
# ============================================================

def auth_test():

    log("AUTH TEST: STARTING")

    account = signed_request(
        "GET",
        "/account"
    )

    log("AUTH TEST: SUCCESS")

    return account


# ============================================================
# PUBLIC API
# ============================================================

def public_request(
    path,
    params=None
):

    url = f"{PUBLIC_ROOT}{path}"

    try:

        response = SESSION.get(
            url,
            params=params or {},
            timeout=TIMEOUT
        )

    except requests.RequestException as exc:

        raise RuntimeError(
            f"PUBLIC API ERROR: {exc}"
        )

    data = response_json(response)

    if response.status_code != 200:

        raise RuntimeError(
            f"PUBLIC HTTP "
            f"{response.status_code}: "
            f"{json.dumps(data, ensure_ascii=False)}"
        )

    return data


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    return public_request(
        "/exchangeInfo"
    )


def extract_markets(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in (
        "symbols",
        "data",
        "markets",
        "result"
    ):

        value = data.get(key)

        if isinstance(value, list):
            return value

    return []


def get_usdt_markets():

    data = get_exchange_info()

    raw_markets = extract_markets(data)

    markets = []

    for item in raw_markets:

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("market")
            or ""
        )

        symbol = str(
            symbol
        ).upper()

        if not symbol.endswith("USDT"):
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
            "ENABLED"
        ):
            continue

        markets.append(item)

    return markets


# ============================================================
# MARKET RULES
# ============================================================

def market_rules(item):

    filters = item.get(
        "filters",
        []
    )

    step_size = Decimal(
        "0.000001"
    )

    min_qty = Decimal("0")

    min_notional = Decimal("0")

    tick_size = Decimal(
        "0.00000001"
    )

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

        if filter_type in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE"
        ):

            step_size = dec(
                item_filter.get(
                    "stepSize",
                    step_size
                ),
                str(step_size)
            )

            min_qty = dec(
                item_filter.get(
                    "minQty",
                    min_qty
                ),
                str(min_qty)
            )

        elif filter_type in (
            "MIN_NOTIONAL",
            "NOTIONAL"
        ):

            min_notional = dec(
                item_filter.get(
                    "minNotional",
                    min_notional
                ),
                str(min_notional)
            )

        elif filter_type == "PRICE_FILTER":

            tick_size = dec(
                item_filter.get(
                    "tickSize",
                    tick_size
                ),
                str(tick_size)
            )

    return {
        "step_size": step_size,
        "min_qty": min_qty,
        "min_notional": min_notional,
        "tick_size": tick_size,
    }


# ============================================================
# RECENT TRADES
# ============================================================

def get_recent_trades(
    symbol,
    limit=300
):

    data = public_request(
        "/trades",
        {
            "symbol": symbol,
            "limit": limit
        }
    )

    if isinstance(data, dict):

        for key in (
            "data",
            "trades",
            "results"
        ):

            if isinstance(
                data.get(key),
                list
            ):

                data = data[key]
                break

    if not isinstance(
        data,
        list
    ):
        return []

    return data


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(
        item,
        dict
    ):
        return None

    price = (
        item.get("price")
        or item.get("p")
    )

    quantity = (
        item.get("qty")
        or item.get("quantity")
        or item.get("q")
        or "0"
    )

    timestamp = (
        item.get("time")
        or item.get("timestamp")
        or item.get("T")
    )

    if price is None:
        return None

    try:

        price = Decimal(
            str(price)
        )

        quantity = Decimal(
            str(quantity)
        )

        timestamp = int(
            timestamp
        )

    except Exception:

        return None

    return (
        timestamp,
        price,
        quantity
    )


# ============================================================
# 5M CLOSED CANDLES
# ============================================================

def make_5m_candles(trades):

    buckets = {}

    for item in trades:

        parsed = parse_trade(item)

        if not parsed:
            continue

        (
            timestamp,
            price,
            quantity
        ) = parsed

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
            }

        else:

            candle = buckets[bucket]

            candle["high"] = max(
                candle["high"],
                price
            )

            candle["low"] = min(
                candle["low"],
                price
            )

            candle["close"] = price

            candle["volume"] += quantity

    candles = [
        buckets[key]
        for key in sorted(
            buckets.keys()
        )
    ]

    current_bucket = (
        int(time.time() * 1000)
        // 300000
    ) * 300000

    if candles:

        if candles[-1]["time"] >= current_bucket:
            candles.pop()

    return candles


# ============================================================
# PRICE ACTION
# ============================================================

def candle_range(candle):

    return (
        candle["high"]
        - candle["low"]
    )


def candle_body(candle):

    return abs(
        candle["close"]
        - candle["open"]
    )


def is_bull(candle):

    return (
        candle["close"]
        > candle["open"]
    )


def build_signal(candles):

    if len(candles) < 25:
        return None

    c0 = candles[-1]
    c1 = candles[-2]
    c2 = candles[-3]
    c3 = candles[-4]

    entry = c0["close"]

    if entry <= 0:
        return None

    previous_high = max(
        candle["high"]
        for candle in candles[-11:-1]
    )

    breakout = (
        c0["close"]
        > previous_high
    )

    rng = candle_range(c0)

    if rng <= 0:
        return None

    body = candle_body(c0)

    body_ratio = body / rng

    strong_bull = (
        is_bull(c0)
        and body_ratio >= Decimal("0.55")
    )

    continuation = (
        c0["close"] > c1["close"]
        and c1["close"] >= c2["close"]
    )

    higher_low = (
        c0["low"] > c2["low"]
        or c1["low"] >= c2["low"]
    )

    move_5 = (
        entry
        / candles[-6]["close"]
        - Decimal("1")
    )

    if move_5 > Decimal("0.025"):
        return None

    score = 0

    if breakout:
        score += 4

    if strong_bull:
        score += 3

    if continuation:
        score += 2

    if higher_low:
        score += 2

    if c0["close"] > c1["high"]:
        score += 2

    if not breakout:
        return None

    if not strong_bull:
        return None

    if score < 9:
        return None

    structure_low = min(
        c0["low"],
        c1["low"],
        c2["low"],
        c3["low"]
    )

    risk = entry - structure_low

    if risk <= 0:
        return None

    minimum_risk = (
        entry * Decimal("0.003")
    )

    if risk < minimum_risk:
        risk = minimum_risk

    sl = entry - risk

    tp = entry + (
        risk * Decimal("2")
    )

    return {
        "symbol": None,
        "signal": "BUY",
        "score": score,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "candle_time": c0["time"],
    }


# ============================================================
# ACCOUNT
# ============================================================

def get_account():

    return signed_request(
        "GET",
        "/account"
    )


def get_usdt_balance(account):

    if not isinstance(account, dict):
        return Decimal("0")

    balances = (
        account.get("balances")
        or account.get("data")
        or []
    )

    if isinstance(balances, dict):

        balances = (
            balances.get("balances")
            or []
        )

    if not isinstance(balances, list):
        return Decimal("0")

    for balance in balances:

        if not isinstance(balance, dict):
            continue

        asset = str(
            balance.get(
                "asset",
                ""
            )
        ).upper()

        if asset != "USDT":
            continue

        free = (
            balance.get("free")
            or balance.get("available")
            or balance.get("balance")
            or "0"
        )

        return dec(free)

    return Decimal("0")


# ============================================================
# EFFECTIVE ORDER VALUE
# ============================================================

def calculate_effective_order_value(balance):

    balance = dec(balance)

    if balance <= BALANCE_RESERVE_USDT:
        return Decimal("0")

    usable_balance = (
        balance
        - BALANCE_RESERVE_USDT
    )

    return min(
        ORDER_USDT,
        usable_balance
    )


# ============================================================
# STATE
# ============================================================

def load_state():

    try:

        if not os.path.exists(STATE_FILE):
            return {}

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

            if isinstance(data, dict):
                return data

    except Exception as exc:

        log(
            f"STATE LOAD ERROR: {exc}"
        )

    return {}


def save_state(state):

    temporary = (
        STATE_FILE
        + ".tmp"
    )

    with open(
        temporary,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        temporary,
        STATE_FILE
    )


def state_key(
    symbol,
    candle_time
):

    return (
        f"{symbol}:"
        f"{candle_time}"
    )


def was_processed(
    state,
    symbol,
    candle_time
):

    trades = state.get(
        "processed",
        {}
    )

    return (
        state_key(
            symbol,
            candle_time
        )
        in trades
    )


def mark_processed(
    state,
    symbol,
    candle_time
):

    if "processed" not in state:
        state["processed"] = {}

    key = state_key(
        symbol,
        candle_time
    )

    state["processed"][key] = {
        "processed_at": utc_now()
    }

    keys = list(
        state["processed"].keys()
    )

    if len(keys) > 300:

        for old_key in keys[:-300]:

            del state[
                "processed"
            ][old_key]


# ============================================================
# QUANTITY
# ============================================================

def calculate_order_quantity(
    order_value,
    entry_price,
    rules
):

    order_value = dec(order_value)
    entry_price = dec(entry_price)

    if order_value <= 0:
        raise RuntimeError(
            "ORDER VALUE IS ZERO"
        )

    if entry_price <= 0:
        raise RuntimeError(
            "INVALID ENTRY PRICE"
        )

    quantity = (
        order_value
        / entry_price
    )

    quantity = floor_step(
        quantity,
        rules["step_size"]
    )

    if quantity <= 0:
        raise RuntimeError(
            "CALCULATED ORDER QUANTITY IS ZERO"
        )

    if (
        rules["min_qty"] > 0
        and quantity < rules["min_qty"]
    ):

        raise RuntimeError(
            "ORDER BELOW MINIMUM QUANTITY: "
            f"{decimal_text(rules['min_qty'])}"
        )

    actual_value = (
        quantity
        * entry_price
    )

    if (
        rules["min_notional"] > 0
        and actual_value < rules["min_notional"]
    ):

        raise RuntimeError(
            "ORDER BELOW MINIMUM NOTIONAL: "
            f"{decimal_text(rules['min_notional'])} USDT"
        )

    return quantity


# ============================================================
# REAL MARKET BUY
# ============================================================

def real_market_buy(
    symbol,
    quantity
):

    log(
        f"REAL BUY: {symbol}"
    )

    log(
        f"QUANTITY: {decimal_text(quantity)}"
    )

    result = signed_request(
        "POST",
        "/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": decimal_text(quantity),
        },
        order=True
    )

    return result


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def signal_message(
    signal,
    symbol,
    quantity,
    order_value
):

    return (
        "🟢 ATI BUY SIGNAL\n"
        f"⚡ {VERSION}\n"
        f"🪙 {symbol}\n"
        f"⭐ SCORE: {signal['score']}\n"
        f"💰 ENTRY: {decimal_text(signal['entry'])}\n"
        f"🛑 SL: {decimal_text(signal['sl'])}\n"
        f"🎯 TP: {decimal_text(signal['tp'])}\n"
        f"📦 QTY: {decimal_text(quantity)}\n"
        f"💵 VALUE: {decimal_text(order_value)} USDT\n"
        f"🕐 {utc_now()}"
    )


# ============================================================
# PROCESS ONE SIGNAL
# ============================================================

def process_signal(
    market,
    signal,
    state,
    balance
):

    symbol = str(
        market.get("symbol")
        or market.get("market")
        or ""
    ).upper()

    if not symbol:
        return False

    signal["symbol"] = symbol

    candle_time = signal["candle_time"]

    if was_processed(
        state,
        symbol,
        candle_time
    ):

        log(
            f"SKIP DUPLICATE: {symbol}"
        )

        return False

    effective_value = (
        calculate_effective_order_value(
            balance
        )
    )

    if effective_value <= 0:

        telegram(
            "⚠️ ORDER BLOCKED\n"
            f"🪙 {symbol}\n"
            "💰 USDT BALANCE TOO LOW\n"
            f"AVAILABLE: {decimal_text(balance)} USDT\n"
            f"🕐 {utc_now()}"
        )

        return False

    rules = market_rules(market)

    quantity = calculate_order_quantity(
        effective_value,
        signal["entry"],
        rules
    )

    actual_value = (
        quantity
        * signal["entry"]
    )

    telegram(
        signal_message(
            signal,
            symbol,
            quantity,
            actual_value
        )
    )

    if not REAL_TRADING:

        telegram(
            "🟡 PAPER MODE\n"
            f"🪙 {symbol}\n"
            "🚫 REAL ORDER NOT SENT\n"
            f"🕐 {utc_now()}"
        )

        mark_processed(
            state,
            symbol,
            candle_time
        )

        save_state(state)

        return False

    telegram(
        "🔓 REAL BUY STARTING\n"
        f"🪙 {symbol}\n"
        f"💵 VALUE: {decimal_text(actual_value)} USDT\n"
        f"📦 QTY: {decimal_text(quantity)}\n"
        f"🕐 {utc_now()}"
    )

    try:

        result = real_market_buy(
            symbol,
            quantity
        )

        order_id = (
            result.get("orderId")
            or result.get("id")
            or "N/A"
        ) if isinstance(result, dict) else "N/A"

        status = (
            result.get("status")
            or "UNKNOWN"
        ) if isinstance(result, dict) else "UNKNOWN"

        executed_qty = (
            result.get("executedQty")
            or result.get("executed_quantity")
            or "N/A"
        ) if isinstance(result, dict) else "N/A"

        quote_qty = (
            result.get("cummulativeQuoteQty")
            or result.get("quoteOrderQty")
            or result.get("executedQuoteQty")
            or "N/A"
        ) if isinstance(result, dict) else "N/A"

        mark_processed(
            state,
            symbol,
            candle_time
        )

        save_state(state)

        telegram(
            "✅ REAL BUY SENT\n"
            f"🪙 {symbol}\n"
            f"🆔 ORDER ID: {order_id}\n"
            f"📊 STATUS: {status}\n"
            f"📦 EXECUTED QTY: {executed_qty}\n"
            f"💵 EXECUTED VALUE: {quote_qty}\n"
            f"🕐 {utc_now()}"
        )

        return True

    except Exception as exc:

        log(
            f"REAL BUY ERROR: {exc}"
        )

        telegram(
            "❌ REAL BUY FAILED\n"
            f"🪙 {symbol}\n"
            f"❗ {str(exc)[:700]}\n"
            f"🕐 {utc_now()}"
        )

        return False


# ============================================================
# SCAN
# ============================================================

def scan():

    started = time.time()

    telegram(
        "🔎 SCAN STARTING\n"
        f"⚡ {VERSION}\n"
        "⏱ 5m CLOSED CANDLES\n"
        f"🕐 {utc_now()}"
    )

    markets = get_usdt_markets()

    log(
        f"USDT MARKETS: {len(markets)}"
    )

    state = load_state()

    # محدودیت برای جلوگیری از اجرای بیش از حد طولانی
    # بازارها بر اساس لیست صرافی بررسی می‌شوند.
    checked = 0
    signals = 0

    account = get_account()

    balance = get_usdt_balance(
        account
    )

    log(
        "USDT BALANCE: "
        f"{decimal_text(balance)}"
    )

    telegram(
        "💰 BALANCE\n"
        f"USDT FREE: {decimal_text(balance)}\n"
        f"🎯 ORDER TARGET: {decimal_text(ORDER_USDT)} USDT\n"
        f"🕐 {utc_now()}"
    )

    if balance <= 0:

        telegram(
            "⚠️ NO FREE USDT\n"
            "REAL ORDER CANNOT BE SENT."
        )

        return

    for market in markets:

        symbol = str(
            market.get("symbol")
            or market.get("market")
            or ""
        ).upper()

        if not symbol:
            continue

        checked += 1

        try:

            trades = get_recent_trades(
                symbol,
                300
            )

            candles = make_5m_candles(
                trades
            )

            signal = build_signal(
                candles
            )

            if signal:

                signals += 1

                log(
                    f"SIGNAL FOUND: {symbol}"
                )

                success = process_signal(
                    market,
                    signal,
                    state,
                    balance
                )

                if success:

                    log(
                        f"ORDER SUCCESS: {symbol}"
                    )

                    # یک معامله موفق در هر اجرای ربات
                    break

        except Exception as exc:

            log(
                f"SCAN ERROR {symbol}: "
                f"{exc}"
            )

        # heartbeat داخلی
        if checked % 25 == 0:

            telegram(
                "📡 SCAN HEARTBEAT\n"
                f"🔎 CHECKED: {checked}\n"
                f"🟢 SIGNALS: {signals}\n"
                f"💰 USDT: {decimal_text(balance)}\n"
                f"🕐 {utc_now()}"
            )

    elapsed = (
        time.time()
        - started
    )

    telegram(
        "🏁 SCAN FINISHED\n"
        f"🔎 CHECKED: {checked}\n"
        f"🟢 SIGNALS: {signals}\n"
        f"⏱ {elapsed:.1f}s\n"
        f"🕐 {utc_now()}"
    )

    log(
        f"SCAN FINISHED: checked={checked} "
        f"signals={signals} "
        f"time={elapsed:.1f}s"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    log("=" * 60)

    log(
        f"⚡ ATI BOT {VERSION}"
    )

    log(
        "🧠 AL BROOKS PRICE ACTION"
    )

    log(
        "📐 Trend → BOS → Pullback → Continuation"
    )

    log(
        "⏱ TIMEFRAME: 5m CLOSED CANDLES"
    )

    log(
        "🚫 EMA: OFF"
    )

    log(
        "🔓 REAL TRADING: "
        f"{'ENABLED' if REAL_TRADING else 'DISABLED'}"
    )

    log(
        "💵 ORDER TARGET: "
        f"{decimal_text(ORDER_USDT)} USDT"
    )

    log(
        f"🕐 {utc_now()}"
    )

    log("=" * 60)

    # --------------------------------------------------------
    # TELEGRAM TEST FIRST
    # --------------------------------------------------------

    telegram_ok = telegram_test()

    if not telegram_ok:

        log(
            "❌ TELEGRAM TEST FAILED"
        )

    # --------------------------------------------------------
    # START MESSAGE
    # --------------------------------------------------------

    telegram(
        "⚡ ATI BOT STARTED\n"
        f"🔥 {VERSION}\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"🔓 REAL TRADING: "
        f"{'ENABLED' if REAL_TRADING else 'DISABLED'}\n"
        f"💵 ORDER TARGET: {decimal_text(ORDER_USDT)} USDT\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # API KEY CHECK
    # --------------------------------------------------------

    if not API_KEY:

        error = (
            "❌ API KEY MISSING\n"
            "TABDIL_API_KEY / TABDEAL_API_KEY"
        )

        log(error)
        telegram(error)
        return

    if not API_SECRET:

        error = (
            "❌ API SECRET MISSING\n"
            "TABDIL_API_SECRET / TABDEAL_API_SECRET"
        )

        log(error)
        telegram(error)
        return

    log(
        "🔐 API KEY FOUND"
    )

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    try:

        account = auth_test()

        balance = get_usdt_balance(
            account
        )

        telegram(
            "✅ AUTH SUCCESS\n"
            f"💰 USDT BALANCE: "
            f"{decimal_text(balance)}\n"
            f"💵 ORDER TARGET: "
            f"{decimal_text(ORDER_USDT)} USDT\n"
            f"🔓 REAL TRADING: "
            f"{'ENABLED' if REAL_TRADING else 'DISABLED'}\n"
            f"🕐 {utc_now()}"
        )

    except Exception as exc:

        log(
            f"❌ AUTH FAILED: {exc}"
        )

        telegram(
            "❌ AUTH FAILED\n"
            f"❗ {str(exc)[:700]}\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    try:

        scan()

    except Exception as exc:

        log(
            f"❌ FATAL ERROR: {exc}"
        )

        telegram(
            "🚨 ATI BOT FATAL ERROR\n"
            f"❗ {str(exc)[:900]}\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # END
    # --------------------------------------------------------

    telegram(
        "✅ ATI BOT RUN COMPLETED\n"
        f"⚡ {VERSION}\n"
        f"🕐 {utc_now()}"
    )

    log(
        "BOT FINISHED"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
