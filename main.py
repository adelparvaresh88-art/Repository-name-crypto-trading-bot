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
# ATI CRYPTO BOT V40.2.42
# TABDEAL SPOT - FROM ZERO
# ============================================================
#
# FEATURES
# ------------------------------------------------------------
# - Tabdeal Spot API
# - HMAC-SHA256 authentication
# - Account authentication test BEFORE trading
# - 5-minute scan
# - CLOSED candle logic
# - Price-action based momentum / breakout
# - No EMA
# - Telegram heartbeat
# - Duplicate-order protection
# - Minimum quantity / step-size handling
# - REAL_TRADING is OFF by default
#
# IMPORTANT
# ------------------------------------------------------------
# GitHub Secrets:
#
# TABDEAL_API_KEY
# TABDEAL_API_SECRET
# TELEGRAM_BOT_TOKEN
# TELEGRAM_CHAT_ID
# REAL_TRADING
# ORDER_QTY
#
# REAL_TRADING:
#   false = scan only
#   true  = real market BUY
#
# ============================================================


VERSION = "V40.2.42"

BASE = "https://api1.tabdeal.org"
API_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 20
RECV_WINDOW = 10000

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

REAL_TRADING = (
    os.getenv("REAL_TRADING", "false").strip().lower()
    in ("1", "true", "yes", "on")
)

try:
    ORDER_QTY = Decimal(os.getenv("ORDER_QTY", "0.001").strip())
except Exception:
    ORDER_QTY = Decimal("0.001")


SESSION = requests.Session()

HEADERS = {
    "User-Agent": "ATI-Crypto-Bot-V40.2.42",
    "Accept": "application/json",
}


# ============================================================
# BASIC HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def log(msg):
    print(msg, flush=True)


def d(value, default="0"):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def fmt_decimal(value):
    value = d(value)
    return format(value, "f").rstrip("0").rstrip(".") or "0"


def floor_step(value, step):
    value = d(value)
    step = d(step)

    if step <= 0:
        return value

    units = (value / step).to_integral_value(
        rounding=ROUND_DOWN
    )

    return units * step


def safe_json(response):
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:
        r = SESSION.post(
            url,
            json=payload,
            timeout=15
        )

        if r.status_code != 200:
            log(
                f"TELEGRAM ERROR {r.status_code}: "
                f"{r.text[:300]}"
            )
            return False

        return True

    except Exception as e:
        log(f"TELEGRAM EXCEPTION: {e}")
        return False


# ============================================================
# API SIGNING
# ============================================================

def make_signature(params):
    """
    Tabdeal signed request.

    The exact parameters sent to the API are first converted
    into the query/form string. HMAC-SHA256 is calculated using
    TABDEAL_API_SECRET.
    """

    parts = []

    for key, value in params.items():

        if value is None:
            continue

        if isinstance(value, bool):
            value = "true" if value else "false"

        value = str(value)

        parts.append(
            f"{key}={value}"
        )

    query_string = "&".join(parts)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return signature


def signed_request(
    method,
    path,
    params=None,
    order_endpoint=False
):
    """
    Signed Tabdeal request.

    IMPORTANT:
    The SAME parameter dictionary is used both for:
      1. signature calculation
      2. actual HTTP request

    This prevents the common 1103 mismatch where the signed
    string differs from the transmitted parameters.
    """

    if not API_KEY:
        raise RuntimeError(
            "TABDEAL_API_KEY is missing"
        )

    if not API_SECRET:
        raise RuntimeError(
            "TABDEAL_API_SECRET is missing"
        )

    method = method.upper()

    request_params = {}

    if params:
        for key, value in params.items():
            if value is not None:
                request_params[key] = value

    # Server timestamp
    timestamp = int(time.time() * 1000)

    request_params["timestamp"] = timestamp
    request_params["recvWindow"] = RECV_WINDOW

    # SIGN EXACTLY WHAT WE SEND
    signature = make_signature(request_params)

    request_params["signature"] = signature

    headers = dict(HEADERS)

    headers["X-MBX-APIKEY"] = API_KEY
    headers["Content-Type"] = (
        "application/x-www-form-urlencoded"
    )

    root = ORDER_ROOT if order_endpoint else API_ROOT
    url = f"{root}{path}"

    log(
        f"AUTH REQUEST: {method} {path}"
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

        else:

            response = SESSION.request(
                method,
                url,
                params=request_params,
                headers=headers,
                timeout=TIMEOUT
            )

    except requests.RequestException as e:

        raise RuntimeError(
            f"NETWORK ERROR: {e}"
        )

    data = safe_json(response)

    if response.status_code < 200 or response.status_code >= 300:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{json.dumps(data, ensure_ascii=False)}"
        )

    if isinstance(data, dict):

        code = data.get("code")

        if code in (1103, "1103"):

            raise RuntimeError(
                "HTTP 401: Invalid Signature "
                "(code 1103)"
            )

    return data


# ============================================================
# AUTH TEST
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

def public_get(path, params=None):

    url = f"{API_ROOT}{path}"

    try:

        r = SESSION.get(
            url,
            params=params or {},
            headers=HEADERS,
            timeout=TIMEOUT
        )

    except requests.RequestException as e:

        raise RuntimeError(
            f"PUBLIC API ERROR: {e}"
        )

    if r.status_code != 200:

        raise RuntimeError(
            f"PUBLIC HTTP {r.status_code}: "
            f"{r.text[:500]}"
        )

    return safe_json(r)


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    return public_get(
        "/exchangeInfo"
    )


def get_usdt_symbols():

    data = get_exchange_info()

    symbols = []

    raw_symbols = []

    if isinstance(data, dict):

        raw_symbols = (
            data.get("symbols")
            or data.get("data")
            or []
        )

    elif isinstance(data, list):

        raw_symbols = data

    for item in raw_symbols:

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("market")
        )

        if not symbol:
            continue

        symbol = str(symbol).upper()

        status = str(
            item.get("status", "TRADING")
        ).upper()

        if status not in (
            "TRADING",
            "ACTIVE",
            "ENABLED"
        ):
            continue

        if symbol.endswith("USDT"):

            symbols.append(item)

    return symbols


# ============================================================
# CANDLE DATA
# ============================================================

def get_trades(symbol, limit=1000):

    data = public_get(
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

            if isinstance(data.get(key), list):
                data = data[key]
                break

    if not isinstance(data, list):
        return []

    return data


def trade_to_price_time(item):

    if not isinstance(item, dict):
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
        price = Decimal(str(price))
        quantity = Decimal(str(quantity))
    except Exception:
        return None

    if timestamp is None:
        timestamp = int(
            time.time() * 1000
        )

    try:
        timestamp = int(timestamp)
    except Exception:
        return None

    return (
        timestamp,
        price,
        quantity
    )


def build_5m_candles(trades):

    buckets = {}

    for item in trades:

        parsed = trade_to_price_time(item)

        if not parsed:
            continue

        ts, price, qty = parsed

        # 5-minute bucket
        bucket = (
            ts // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
                "time": bucket,
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

            candle["volume"] += qty

    candles = [
        buckets[k]
        for k in sorted(buckets)
    ]

    # The current bucket may still be open.
    # We remove it because strategy uses CLOSED candles.
    if candles:

        current_bucket = (
            int(time.time() * 1000)
            // 300000
        ) * 300000

        if candles[-1]["time"] >= current_bucket:

            candles = candles[:-1]

    return candles


# ============================================================
# PRICE ACTION SIGNAL
# ============================================================

def candle_body(c):
    return abs(
        c["close"] - c["open"]
    )


def candle_range(c):
    return (
        c["high"] - c["low"]
    )


def bullish(c):
    return c["close"] > c["open"]


def bearish(c):
    return c["close"] < c["open"]


def calculate_signal(candles):

    if len(candles) < 25:
        return None

    # Last CLOSED candle
    c0 = candles[-1]

    c1 = candles[-2]
    c2 = candles[-3]
    c3 = candles[-4]

    close = c0["close"]

    if close <= 0:
        return None

    # --------------------------------------------------------
    # 1. Momentum
    # --------------------------------------------------------

    recent_high = max(
        c["high"]
        for c in candles[-11:-1]
    )

    recent_low = min(
        c["low"]
        for c in candles[-11:-1]
    )

    # --------------------------------------------------------
    # 2. Breakout
    # --------------------------------------------------------

    breakout = (
        c0["close"] > recent_high
    )

    # --------------------------------------------------------
    # 3. Strong bullish candle
    # --------------------------------------------------------

    rng = candle_range(c0)
    body = candle_body(c0)

    if rng <= 0:
        return None

    body_ratio = body / rng

    strong_bull = (
        bullish(c0)
        and body_ratio >= Decimal("0.55")
    )

    # --------------------------------------------------------
    # 4. Continuation
    # --------------------------------------------------------

    continuation = (
        c0["close"] > c1["close"]
        and c1["close"] >= c2["close"]
    )

    # --------------------------------------------------------
    # 5. Higher-low style pullback
    # --------------------------------------------------------

    higher_low = (
        c1["low"] >= c2["low"]
        or c0["low"] > c2["low"]
    )

    # --------------------------------------------------------
    # 6. Avoid extreme chase
    # --------------------------------------------------------

    move_5 = (
        close / candles[-6]["close"]
        - Decimal("1")
    )

    if move_5 > Decimal("0.025"):
        return None

    # --------------------------------------------------------
    # Score
    # --------------------------------------------------------

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

    # Require actual structure
    if not breakout:
        return None

    if not strong_bull:
        return None

    if score < 9:
        return None

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    entry = close

    structure_low = min(
        c0["low"],
        c1["low"],
        c2["low"],
        c3["low"]
    )

    risk = (
        entry - structure_low
    )

    if risk <= 0:
        return None

    # Protect against an absurdly tight SL
    minimum_risk = (
        entry * Decimal("0.003")
    )

    if risk < minimum_risk:
        risk = minimum_risk

    sl = entry - risk

    # 2R TP
    tp = entry + (
        risk * Decimal("2")
    )

    return {
        "signal": "BUY",
        "score": score,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "time": c0["time"],
        "body_ratio": body_ratio,
        "breakout": breakout,
    }


# ============================================================
# SYMBOL FILTERS
# ============================================================

def symbol_info(item):

    symbol = str(
        item.get("symbol")
        or ""
    ).upper()

    filters = (
        item.get("filters")
        or []
    )

    step_size = Decimal("0.000001")
    min_qty = Decimal("0")
    min_notional = Decimal("0")
    tick_size = Decimal("0.00000001")

    for f in filters:

        if not isinstance(f, dict):
            continue

        ftype = str(
            f.get("filterType")
            or ""
        ).upper()

        if ftype in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE"
        ):

            step_size = d(
                f.get("stepSize"),
                "0.000001"
            )

            min_qty = d(
                f.get("minQty"),
                "0"
            )

        elif ftype in (
            "MIN_NOTIONAL",
            "NOTIONAL"
        ):

            min_notional = d(
                f.get("minNotional"),
                "0"
            )

        elif ftype == "PRICE_FILTER":

            tick_size = d(
                f.get("tickSize"),
                "0.00000001"
            )

    return {
        "symbol": symbol,
        "step_size": step_size,
        "min_qty": min_qty,
        "min_notional": min_notional,
        "tick_size": tick_size,
    }


# ============================================================
# ACCOUNT BALANCE
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

    for item in balances:

        if not isinstance(item, dict):
            continue

        asset = str(
            item.get("asset")
            or ""
        ).upper()

        if asset != "USDT":
            continue

        free = (
            item.get("free")
            or item.get("available")
            or item.get("balance")
            or "0"
        )

        return d(free)

    return Decimal("0")


# ============================================================
# REAL ORDER
# ============================================================

def place_market_buy(
    symbol,
    quantity
):

    quantity = d(quantity)

    if quantity <= 0:
        raise RuntimeError(
            "ORDER_QTY must be greater than zero"
        )

    params = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quantity": fmt_decimal(quantity),
    }

    log(
        f"REAL ORDER REQUEST: "
        f"BUY {symbol} QTY={fmt_decimal(quantity)}"
    )

    result = signed_request(
        "POST",
        "/order",
        params=params,
        order_endpoint=True
    )

    return result


# ============================================================
# DUPLICATE PROTECTION
# ============================================================

STATE_FILE = "ati_state.json"


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
        ) as f:

            data = json.load(f)

            if isinstance(data, dict):
                return data

    except Exception:
        pass

    return {}


def save_state(state):

    tmp = STATE_FILE + ".tmp"

    with open(
        tmp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        tmp,
        STATE_FILE
    )


def already_traded(
    state,
    symbol,
    candle_time
):

    trades = state.get(
        "trades",
        {}
    )

    key = (
        f"{symbol}:{candle_time}"
    )

    return key in trades


def mark_traded(
    state,
    symbol,
    candle_time
):

    if "trades" not in state:
        state["trades"] = {}

    key = (
        f"{symbol}:{candle_time}"
    )

    state["trades"][key] = {
        "time": now_utc()
    }

    # Keep state small
    keys = list(
        state["trades"].keys()
    )

    if len(keys) > 200:

        for old in keys[:-200]:
            del state["trades"][old]


# ============================================================
# SCAN
# ============================================================

def scan_markets():

    markets = get_usdt_symbols()

    log(
        f"USDT MARKETS: {len(markets)}"
    )

    candidates = []

    for item in markets:

        info = symbol_info(item)

        symbol = info["symbol"]

        try:

            trades = get_trades(
                symbol,
                300
            )

            candles = build_5m_candles(
                trades
            )

            signal = calculate_signal(
                candles
            )

            if not signal:
                continue

            signal["symbol"] = symbol
            signal["info"] = info

            candidates.append(
                signal
            )

        except Exception as e:

            log(
                f"SCAN ERROR {symbol}: "
                f"{e}"
            )

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return candidates


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        f"⚡ ATI CRYPTO BOT {VERSION}-REAL",
        flush=True
    )

    print(
        "🧠 AL BROOKS PRICE ACTION",
        flush=True
    )

    print(
        "📐 Trend → BOS → Pullback → "
        "Continuation → CLOSED CONFIRM",
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
        f"🔓 REAL ORDERS: "
        f"{'ENABLED' if REAL_TRADING else 'DISABLED'}",
        flush=True
    )

    print(
        f"📦 ORDER_QTY: "
        f"{fmt_decimal(ORDER_QTY)}",
        flush=True
    )

    print(
        f"🕐 {now_utc()}",
        flush=True
    )

    # --------------------------------------------------------
    # CONFIG CHECK
    # --------------------------------------------------------

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
        f"🕐 {now_utc()}"
    )

    # --------------------------------------------------------
    # AUTH TEST
    # --------------------------------------------------------

    try:

        account = auth_test()

    except Exception as e:

        telegram(
            f"❌ ATI AUTH FAILED\n"
            f"V{VERSION}\n\n"
            f"{str(e)[:700]}"
        )

        raise

    usdt_balance = get_usdt_balance(
        account
    )

    log(
        f"USDT BALANCE: "
        f"{fmt_decimal(usdt_balance)}"
    )

    telegram(
        f"✅ AUTH SUCCESS\n"
        f"💰 USDT BALANCE: "
        f"{fmt_decimal(usdt_balance)}\n"
        f"📡 SCAN STARTING..."
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    started = time.time()

    candidates = scan_markets()

    elapsed = (
        time.time() - started
    )

    if not candidates:

        msg = (
            f"⚪ ATI {VERSION}\n"
            f"📊 NO VALID BUY SIGNAL\n"
            f"⏱ Scan: {elapsed:.1f}s\n"
            f"🕐 {now_utc()}"
        )

        log(msg)
        telegram(msg)
        return

    # --------------------------------------------------------
    # TOP CANDIDATE
    # --------------------------------------------------------

    top = candidates[0]

    symbol = top["symbol"]
    score = top["score"]

    entry = top["entry"]
    sl = top["sl"]
    tp = top["tp"]

    info = top["info"]

    quantity = floor_step(
        ORDER_QTY,
        info["step_size"]
    )

    if quantity < info["min_qty"]:

        quantity = info["min_qty"]

    estimated_value = (
        quantity * entry
    )

    message = (
        f"🟢 ATI BUY SIGNAL\n"
        f"⚡ {VERSION}\n\n"
        f"🪙 {symbol}\n"
        f"⭐ SCORE: {score}\n"
        f"💰 ENTRY: {fmt_decimal(entry)}\n"
        f"🛑 SL: {fmt_decimal(sl)}\n"
        f"🎯 TP: {fmt_decimal(tp)}\n"
        f"📦 QTY: {fmt_decimal(quantity)}\n"
        f"💵 VALUE: {fmt_decimal(estimated_value)} USDT\n"
        f"⏱ Scan: {elapsed:.1f}s\n"
        f"🕐 {now_utc()}"
    )

    log(message)
    telegram(message)

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    state = load_state()

    candle_time = top["time"]

    if already_traded(
        state,
        symbol,
        candle_time
    ):

        telegram(
            f"🔒 DUPLICATE LOCK\n"
            f"{symbol}\n"
            f"This closed candle was already processed."
        )

        return

    # --------------------------------------------------------
    # PAPER MODE
    # --------------------------------------------------------

    if not REAL_TRADING:

        telegram(
            f"📝 PAPER MODE\n"
            f"{symbol}\n"
            f"No real order was sent."
        )

        return

    # --------------------------------------------------------
    # REAL TRADING
    # --------------------------------------------------------

    if quantity <= 0:

        raise RuntimeError(
            "Calculated quantity is zero"
        )

    if usdt_balance <= 0:

        raise RuntimeError(
            "USDT balance is zero"
        )

    if estimated_value > usdt_balance:

        telegram(
            f"⚠️ ORDER BLOCKED\n"
            f"{symbol}\n"
            f"Required ≈ "
            f"{fmt_decimal(estimated_value)} USDT\n"
            f"Available = "
            f"{fmt_decimal(usdt_balance)} USDT"
        )

        return

    # Mark BEFORE order to prevent a second execution
    # during the same workflow invocation.
    mark_traded(
        state,
        symbol,
        candle_time
    )

    save_state(state)

    telegram(
        f"🔓 REAL ORDER STARTING\n"
        f"🪙 {symbol}\n"
        f"📦 QTY: {fmt_decimal(quantity)}"
    )

    try:

        result = place_market_buy(
            symbol,
            quantity
        )

        order_id = (
            result.get("orderId")
            if isinstance(result, dict)
            else None
        )

        telegram(
            f"✅ REAL BUY SENT\n"
            f"🪙 {symbol}\n"
            f"📦 QTY: {fmt_decimal(quantity)}\n"
            f"🆔 ORDER ID: "
            f"{order_id or 'N/A'}\n\n"
            f"⚠️ SL/TP باید پس از تأیید "
            f"اجرای سفارش مدیریت شود."
        )

        log(
            "REAL ORDER RESULT:"
        )

        log(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2
            )
        )

    except Exception as e:

        telegram(
            f"❌ REAL ORDER FAILED\n"
            f"{symbol}\n\n"
            f"{str(e)[:700]}"
        )

        raise


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        print(
            f"FATAL: {repr(e)}",
            flush=True
        )

        telegram(
            f"🚨 ATI FATAL ERROR\n"
            f"{VERSION}\n\n"
            f"{str(e)[:800]}"
        )

        raise
