import os
import time
import json
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.43
# TABDEAL SPOT
# REAL TRADING
# ============================================================

VERSION = "V40.2.43"

BASE = "https://api1.tabdeal.org"

PUBLIC_ROOT = f"{BASE}/r/api/v1"
SIGNED_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 20
RECV_WINDOW = 10000

API_KEY = os.getenv(
    "TABDEAL_API_KEY",
    ""
).strip()

API_SECRET = os.getenv(
    "TABDEAL_API_SECRET",
    ""
).strip()

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# REAL TRADING SWITCH
# LIVE_TRADING HAS PRIORITY
# REAL_TRADING KEPT FOR COMPATIBILITY
# ============================================================

REAL_TRADING = (
    os.getenv(
        "LIVE_TRADING",
        os.getenv(
            "REAL_TRADING",
            "false"
        )
    ).strip().lower()
    in (
        "1",
        "true",
        "yes",
        "on"
    )
)


# ============================================================
# ORDER QTY
# ============================================================

try:

    ORDER_QTY = Decimal(
        os.getenv(
            "ORDER_QTY",
            "0.001"
        ).strip()
    )

except Exception:

    ORDER_QTY = Decimal(
        "0.001"
    )


SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent":
        "ATI-Crypto-Bot/"
        + VERSION,

    "Accept":
        "application/json",
})


# ============================================================
# LOGGING
# ============================================================

def log(message):

    print(
        str(message),
        flush=True
    )


def utc_now():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# DECIMAL
# ============================================================

def dec(
    value,
    default="0"
):

    try:

        return Decimal(
            str(value)
        )

    except Exception:

        return Decimal(
            default
        )


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


def floor_step(
    value,
    step
):

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

    if (
        not TELEGRAM_TOKEN
        or not TELEGRAM_CHAT_ID
    ):

        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id":
            TELEGRAM_CHAT_ID,

        "text":
            str(message),
    }

    try:

        response = SESSION.post(
            url,
            json=payload,
            timeout=15
        )

        if response.status_code != 200:

            log(
                "TELEGRAM ERROR "
                f"{response.status_code}: "
                f"{response.text[:300]}"
            )

            return False

        return True

    except Exception as exc:

        log(
            f"TELEGRAM EXCEPTION: {exc}"
        )

        return False


# ============================================================
# JSON
# ============================================================

def response_json(response):

    try:

        return response.json()

    except Exception:

        return {
            "raw":
                response.text
        }


# ============================================================
# TABDEAL HMAC
# ============================================================

def create_signed_parameters(
    parameters=None
):

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

            params_object[
                key
            ] = value

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
        for key, value
        in params_object.items()
    )

    signature = hmac.new(
        API_SECRET.encode(
            "utf-8"
        ),

        query_string.encode(
            "utf-8"
        ),

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
            "TABDEAL_API_KEY is missing"
        )

    if not API_SECRET:

        raise RuntimeError(
            "TABDEAL_API_SECRET is missing"
        )

    method = method.upper()

    (
        signed_params,
        signature,
        query_string
    ) = create_signed_parameters(
        params
    )

    request_params = dict(
        signed_params
    )

    request_params[
        "signature"
    ] = signature

    headers = {

        "X-MBX-APIKEY":
            API_KEY,

        "Accept":
            "application/json",

        "User-Agent":
            "ATI-Crypto-Bot/"
            + VERSION,
    }

    root = (
        ORDER_ROOT
        if order
        else SIGNED_ROOT
    )

    url = (
        f"{root}{path}"
    )

    log(
        f"REQUEST: {method} {url}"
    )

    log(
        "SIGN DEBUG: "
        f"timestamp="
        f"{signed_params['timestamp']}"
    )

    log(
        "SIGN DEBUG: "
        f"recvWindow="
        f"{signed_params['recvWindow']}"
    )

    log(
        "SIGN DEBUG: keys="
        f"{','.join(signed_params.keys())}"
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
            ] = (
                "application/"
                "x-www-form-urlencoded"
            )

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
            ] = (
                "application/"
                "x-www-form-urlencoded"
            )

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

    data = response_json(
        response
    )

    if (
        response.status_code < 200
        or response.status_code >= 300
    ):

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{json.dumps(data, ensure_ascii=False)}"
        )

    if isinstance(
        data,
        dict
    ):

        code = data.get(
            "code"
        )

        if str(code) == "1103":

            raise RuntimeError(
                "HTTP 401: "
                '{"code":1103,'
                '"msg":"Invalid Signature."}'
            )

    return data


# ============================================================
# AUTH
# ============================================================

def auth_test():

    log(
        "AUTH TEST: STARTING"
    )

    account = signed_request(
        "GET",
        "/account"
    )

    log(
        "AUTH TEST: SUCCESS"
    )

    return account


# ============================================================
# PUBLIC API
# ============================================================

def public_request(
    path,
    params=None
):

    url = (
        f"{PUBLIC_ROOT}{path}"
    )

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

    data = response_json(
        response
    )

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

    if isinstance(
        data,
        list
    ):

        return data

    if not isinstance(
        data,
        dict
    ):

        return []

    for key in (
        "symbols",
        "data",
        "markets",
        "result"
    ):

        value = data.get(
            key
        )

        if isinstance(
            value,
            list
        ):

            return value

    return []


def get_usdt_markets():

    data = get_exchange_info()

    raw_markets = extract_markets(
        data
    )

    markets = []

    for item in raw_markets:

        if not isinstance(
            item,
            dict
        ):

            continue

        symbol = (
            item.get("symbol")
            or item.get("market")
            or ""
        )

        symbol = str(
            symbol
        ).upper()

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
            "ENABLED"
        ):

            continue

        markets.append(
            item
        )

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

    min_qty = Decimal(
        "0"
    )

    min_notional = Decimal(
        "0"
    )

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

        elif filter_type == (
            "PRICE_FILTER"
        ):

            tick_size = dec(
                item_filter.get(
                    "tickSize",
                    tick_size
                ),
                str(tick_size)
            )

    return {
        "step_size":
            step_size,

        "min_qty":
            min_qty,

        "min_notional":
            min_notional,

        "tick_size":
            tick_size,
    }


# ============================================================
# TRADES
# ============================================================

def get_recent_trades(
    symbol,
    limit=300
):

    data = public_request(
        "/trades",
        {
            "symbol":
                symbol,

            "limit":
                limit
        }
    )

    if isinstance(
        data,
        dict
    ):

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
# 5M CANDLES
# ============================================================

def make_5m_candles(
    trades
):

    buckets = {}

    for item in trades:

        parsed = parse_trade(
            item
        )

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

                "time":
                    bucket,

                "open":
                    price,

                "high":
                    price,

                "low":
                    price,

                "close":
                    price,

                "volume":
                    quantity,
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

    candles = [
        buckets[key]
        for key in sorted(
            buckets.keys()
        )
    ]

    current_bucket = (
        int(
            time.time() * 1000
        )
        // 300000
    ) * 300000

    if candles:

        if (
            candles[-1]["time"]
            >= current_bucket
        ):

            candles.pop()

    return candles


# ============================================================
# PRICE ACTION
# ============================================================

def candle_range(
    candle
):

    return (
        candle["high"]
        - candle["low"]
    )


def candle_body(
    candle
):

    return abs(
        candle["close"]
        - candle["open"]
    )


def is_bull(
    candle
):

    return (
        candle["close"]
        > candle["open"]
    )


def build_signal(
    candles
):

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

    rng = candle_range(
        c0
    )

    if rng <= 0:

        return None

    body = candle_body(
        c0
    )

    body_ratio = (
        body / rng
    )

    strong_bull = (
        is_bull(c0)
        and body_ratio
        >= Decimal("0.55")
    )

    continuation = (
        c0["close"]
        > c1["close"]
        and c1["close"]
        >= c2["close"]
    )

    higher_low = (
        c0["low"]
        > c2["low"]
        or c1["low"]
        >= c2["low"]
    )

    move_5 = (
        entry
        / candles[-6]["close"]
        - Decimal("1")
    )

    if move_5 > Decimal(
        "0.025"
    ):

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

    if (
        c0["close"]
        > c1["high"]
    ):

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

    risk = (
        entry
        - structure_low
    )

    if risk <= 0:

        return None

    minimum_risk = (
        entry
        * Decimal("0.003")
    )

    if risk < minimum_risk:

        risk = minimum_risk

    sl = entry - risk

    tp = entry + (
        risk * Decimal("2")
    )

    return {

        "symbol":
            None,

        "signal":
            "BUY",

        "score":
            score,

        "entry":
            entry,

        "sl":
            sl,

        "tp":
            tp,

        "candle_time":
            c0["time"],
    }


# ============================================================
# ACCOUNT
# ============================================================

def get_account():

    return signed_request(
        "GET",
        "/account"
    )


def get_usdt_balance(
    account
):

    if not isinstance(
        account,
        dict
    ):

        return Decimal("0")

    balances = (
        account.get(
            "balances"
        )
        or account.get(
            "data"
        )
        or []
    )

    if isinstance(
        balances,
        dict
    ):

        balances = (
            balances.get(
                "balances"
            )
            or []
        )

    if not isinstance(
        balances,
        list
    ):

        return Decimal("0")

    for balance in balances:

        if not isinstance(
            balance,
            dict
        ):

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

        return dec(
            free
        )

    return Decimal("0")


# ============================================================
# STATE
# ============================================================

STATE_FILE = (
    "ati_state.json"
)


def load_state():

    try:

        if not os.path.exists(
            STATE_FILE
        ):

            return {}

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(
                file
            )

            if isinstance(
                data,
                dict
            ):

                return data

    except Exception as exc:

        log(
            f"STATE LOAD ERROR: {exc}"
        )

    return {}


def save_state(
    state
):

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

        state[
            "processed"
        ] = {}

    key = state_key(
        symbol,
        candle_time
    )

    state[
        "processed"
    ][key] = {

        "processed_at":
            utc_now()
    }

    keys = list(
        state[
            "processed"
        ].keys()
    )

    if len(keys) > 300:

        for old_key in keys[:-300]:

            del state[
                "processed"
            ][old_key]


# ============================================================
# REAL MARKET BUY
# ============================================================

def place_market_buy(
    symbol,
    quantity
):

    params = {

        "symbol":
            symbol,

        "side":
            "BUY",

        "type":
            "MARKET",

        "quantity":
            decimal_text(
                quantity
            ),
    }

    return signed_request(
        "POST",
        "/order",
        params=params,
        order=True
    )


# ============================================================
# SCAN
# ============================================================

def scan_markets(
    markets
):

    candidates = []

    for market in markets:

        symbol = str(
            market.get(
                "symbol",
                ""
            )
        ).upper()

        if not symbol:

            continue

        try:

            trades = (
                get_recent_trades(
                    symbol,
                    300
                )
            )

            candles = (
                make_5m_candles(
                    trades
                )
            )

            signal = (
                build_signal(
                    candles
                )
            )

            if signal:

                signal[
                    "symbol"
                ] = symbol

                signal[
                    "market"
                ] = market

                candidates.append(
                    signal
                )

        except Exception as exc:

            log(
                f"SCAN ERROR "
                f"{symbol}: {exc}"
            )

    candidates.sort(
        key=lambda item:
            item["score"],
        reverse=True
    )

    return candidates


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        f"⚡ ATI CRYPTO BOT "
        f"{VERSION}-REAL",
        flush=True
    )

    print(
        "🧠 AL BROOKS PRICE ACTION",
        flush=True
    )

    print(
        "📐 Trend → BOS → Pullback "
        "→ Continuation → CLOSED CONFIRM",
        flush=True
    )

    print(
        "⏱ TIMEFRAME: 5m CLOSED CANDLES",
        flush=True
    )

    print(
        "🚫 EMA: OFF",
        flush=True
    )

    print(
        "🔓 REAL ORDERS: "
        + (
            "ENABLED"
            if REAL_TRADING
            else "DISABLED"
        ),
        flush=True
    )

    print(
        "📦 ORDER_QTY: "
        + decimal_text(
            ORDER_QTY
        ),
        flush=True
    )

    print(
        "🕐 "
        + utc_now(),
        flush=True
    )

    if not API_KEY:

        raise RuntimeError(
            "TABDEAL_API_KEY is missing"
        )

    if not API_SECRET:

        raise RuntimeError(
            "TABDEAL_API_SECRET is missing"
        )

    telegram(
        f"⚡ ATI BOT {VERSION}\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"🔐 AUTH TEST: STARTING\n"
        f"🔓 REAL ORDERS: "
        f"{'ENABLED' if REAL_TRADING else 'DISABLED'}\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    try:

        account = auth_test()

    except Exception as exc:

        telegram(
            f"❌ AUTH FAILED\n"
            f"ATI {VERSION}\n\n"
            f"{str(exc)[:700]}"
        )

        raise

    balance = get_usdt_balance(
        account
    )

    log(
        "USDT BALANCE: "
        + decimal_text(
            balance
        )
    )

    telegram(
        f"✅ AUTH SUCCESS\n"
        f"💰 USDT BALANCE: "
        f"{decimal_text(balance)}\n"
        f"📡 SCAN STARTING..."
    )

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    markets = get_usdt_markets()

    log(
        "USDT MARKETS: "
        + str(
            len(markets)
        )
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    start = time.time()

    candidates = scan_markets(
        markets
    )

    elapsed = (
        time.time()
        - start
    )

    log(
        f"SCAN TIME: "
        f"{elapsed:.1f}s"
    )

    if not candidates:

        message = (
            f"⚪ ATI {VERSION}\n"
            f"📊 NO VALID BUY SIGNAL\n"
            f"📈 MARKETS: {len(markets)}\n"
            f"⏱ {elapsed:.1f}s\n"
            f"🕐 {utc_now()}"
        )

        log(message)

        telegram(
            message
        )

        return

    # --------------------------------------------------------
    # TOP SIGNAL
    # --------------------------------------------------------

    top = candidates[0]

    symbol = top[
        "symbol"
    ]

    score = top[
        "score"
    ]

    entry = top[
        "entry"
    ]

    sl = top[
        "sl"
    ]

    tp = top[
        "tp"
    ]

    candle_time = top[
        "candle_time"
    ]

    rules = market_rules(
        top["market"]
    )

    quantity = floor_step(
        ORDER_QTY,
        rules["step_size"]
    )

    if quantity < rules["min_qty"]:

        quantity = rules[
            "min_qty"
        ]

    estimated_value = (
        quantity * entry
    )

    signal_message = (
        f"🟢 ATI BUY SIGNAL\n"
        f"⚡ {VERSION}\n\n"
        f"🪙 {symbol}\n"
        f"⭐ SCORE: {score}\n"
        f"💰 ENTRY: "
        f"{decimal_text(entry)}\n"
        f"🛑 SL: "
        f"{decimal_text(sl)}\n"
        f"🎯 TP: "
        f"{decimal_text(tp)}\n"
        f"📦 QTY: "
        f"{decimal_text(quantity)}\n"
        f"💵 VALUE: "
        f"{decimal_text(estimated_value)} USDT\n"
        f"⏱ SCAN: "
        f"{elapsed:.1f}s\n"
        f"🕐 {utc_now()}"
    )

    log(
        signal_message
    )

    telegram(
        signal_message
    )

    # --------------------------------------------------------
    # DUPLICATE LOCK
    # --------------------------------------------------------

    state = load_state()

    if was_processed(
        state,
        symbol,
        candle_time
    ):

        message = (
            f"🔒 DUPLICATE LOCK\n"
            f"{symbol}\n"
            f"CLOSED CANDLE ALREADY PROCESSED"
        )

        log(message)

        telegram(
            message
        )

        return

    # --------------------------------------------------------
    # PAPER MODE
    # --------------------------------------------------------

    if not REAL_TRADING:

        telegram(
            f"📝 PAPER MODE\n"
            f"{symbol}\n"
            f"NO REAL ORDER SENT"
        )

        return

    # --------------------------------------------------------
    # REAL MODE SAFETY
    # --------------------------------------------------------

    if quantity <= 0:

        raise RuntimeError(
            "ORDER_QTY is zero"
        )

    if balance <= 0:

        telegram(
            f"⚠️ ORDER BLOCKED\n"
            f"{symbol}\n"
            f"USDT BALANCE = 0"
        )

        return

    if (
        rules["min_notional"] > 0
        and estimated_value
        < rules["min_notional"]
    ):

        telegram(
            f"⚠️ ORDER BLOCKED\n"
            f"{symbol}\n"
            f"ORDER VALUE "
            f"{decimal_text(estimated_value)} "
            f"USDT\n"
            f"MIN NOTIONAL "
            f"{decimal_text(rules['min_notional'])}"
        )

        return

    if estimated_value > balance:

        telegram(
            f"⚠️ ORDER BLOCKED\n"
            f"{symbol}\n"
            f"REQUIRED: "
            f"{decimal_text(estimated_value)} USDT\n"
            f"AVAILABLE: "
            f"{decimal_text(balance)} USDT"
        )

        return

    # --------------------------------------------------------
    # LOCK BEFORE ORDER
    # --------------------------------------------------------

    mark_processed(
        state,
        symbol,
        candle_time
    )

    save_state(
        state
    )

    telegram(
        f"🔓 REAL BUY STARTING\n"
        f"🪙 {symbol}\n"
        f"📦 QTY: "
        f"{decimal_text(quantity)}"
    )

    # --------------------------------------------------------
    # ORDER
    # --------------------------------------------------------

    try:

        result = place_market_buy(
            symbol,
            quantity
        )

        order_id = None

        if isinstance(
            result,
            dict
        ):

            order_id = (
                result.get(
                    "orderId"
                )
            )

        telegram(
            f"✅ REAL BUY SENT\n"
            f"🪙 {symbol}\n"
            f"📦 QTY: "
            f"{decimal_text(quantity)}\n"
            f"🆔 ORDER ID: "
            f"{order_id or 'N/A'}"
        )

        log(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2
            )
        )

    except Exception as exc:

        telegram(
            f"❌ REAL ORDER FAILED\n"
            f"{symbol}\n\n"
            f"{str(exc)[:700]}"
        )

        raise


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        print(
            f"FATAL: {repr(exc)}",
            flush=True
        )

        telegram(
            f"🚨 ATI FATAL ERROR\n"
            f"{VERSION}\n\n"
            f"{str(exc)[:800]}"
        )

        raise

نکته: این نسخه فقط اختلاف نام "LIVE_TRADING"/"REAL_TRADING" را اصلاح می‌کند؛ یعنی اگر "LIVE_TRADING=true" باشد، بخش سفارش واقعی فعال می‌شود. اما خود من نمی‌توانم از داخل چت سفارش واقعی را روی حساب صرافی‌ات اجرا کنم؛ اجرای سفارش به کلید API و اجرای GitHub Actions تو وابسته است.

برای "main.yml" هم باید "LIVE_TRADING" به محیط اجرای Python منتقل شده باشد.
