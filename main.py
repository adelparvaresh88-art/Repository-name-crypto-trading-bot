import os
import time
import hmac
import hashlib
import math
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.54-REAL
# TABDEAL SPOT
# AUTH-HARDENED
# ============================================================

VERSION = "V40.2.54-REAL"

BASE = "https://api1.tabdeal.org"
PUBLIC_ROOT = f"{BASE}/r/api/v1"
SIGNED_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 12
RECV_WINDOW = 5000

LIVE_TRADING = os.getenv("LIVE_TRADING", "true").strip().lower() == "true"
ORDER_USDT = Decimal(os.getenv("ORDER_USDT", "2"))

SCAN_LIMIT = int(os.getenv("SCAN_LIMIT", "40"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "12"))

MIN_SCORE = int(os.getenv("MIN_SCORE", "11"))

# Price action
MIN_CANDLES = 30
REAL_BOS_MIN = Decimal("0.05")
NEAR_BOS_MIN = Decimal("-0.25")
PULLBACK_TOLERANCE = Decimal("0.80")
CHASE_LIMIT = Decimal("2.20")
MIN_CONFIRM_CLOSE_POSITION = Decimal("0.55")

# Risk
STOP_LOSS_PCT = Decimal("0.60")
TAKE_PROFIT_PCT = Decimal("1.20")

# Safety
MAX_BUYS_PER_RUN = 1


# ============================================================
# ENV
# ============================================================

API_KEY = (
    os.getenv("TABDIL_API_KEY", "").strip()
    or os.getenv("TABDEAL_API_KEY", "").strip()
)

API_SECRET = (
    os.getenv("TABDIL_API_SECRET", "").strip()
    or os.getenv("TABDEAL_API_SECRET", "").strip()
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

AUTH_PAIR = (
    "TABDIL"
    if os.getenv("TABDIL_API_KEY", "").strip()
    and os.getenv("TABDIL_API_SECRET", "").strip()
    else "TABDEAL"
)


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

SERVER_OFFSET_MS = 0


# ============================================================
# TIME / TEXT
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_decimal(value, default=Decimal("0")):
    try:
        return Decimal(str(value))
    except Exception:
        return default


def fmt_decimal(value, places=12):
    d = safe_decimal(value)

    if d == 0:
        return "0"

    text = format(d, "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text


def log(message):
    print(message, flush=True)


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = (
            f"https://api.telegram.org/bot"
            f"{TELEGRAM_TOKEN}/sendMessage"
        )

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
        }

        r = session.post(
            url,
            json=payload,
            timeout=10,
        )

        return r.ok

    except Exception as e:
        log(f"TELEGRAM ERROR: {e}")
        return False


def notify(message):
    log(message)
    telegram(message)


# ============================================================
# SERVER TIME
# ============================================================

def sync_server_time():
    global SERVER_OFFSET_MS

    local_before = int(time.time() * 1000)

    r = session.get(
        f"{PUBLIC_ROOT}/time",
        timeout=TIMEOUT,
    )

    r.raise_for_status()

    local_after = int(time.time() * 1000)

    data = r.json()

    server_time = int(
        data.get("serverTime")
        or data.get("server_time")
        or data.get("time")
    )

    midpoint = (local_before + local_after) // 2

    SERVER_OFFSET_MS = server_time - midpoint

    return server_time, SERVER_OFFSET_MS


def signed_timestamp():
    return int(time.time() * 1000) + SERVER_OFFSET_MS


# ============================================================
# HMAC
# ============================================================

def make_signature(params):
    """
    IMPORTANT:
    The exact query string generated here is the string that
    gets HMAC-SHA256 signed.
    """

    query_string = urlencode(params)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return query_string, signature


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(
    method,
    path,
    params=None,
    retry_auth=True,
):
    params = dict(params or {})

    # Timestamp is always generated immediately before signing.
    params["timestamp"] = signed_timestamp()
    params["recvWindow"] = RECV_WINDOW

    query_string, signature = make_signature(params)

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Accept": "application/json",
        "User-Agent": f"ATI/{VERSION}",
    }

    url = f"{path}?{query_string}&signature={signature}"

    method = method.upper()

    if method == "GET":
        response = session.get(
            url,
            headers=headers,
            timeout=TIMEOUT,
        )

    elif method == "POST":
        response = session.post(
            url,
            headers=headers,
            timeout=TIMEOUT,
        )

    elif method == "DELETE":
        response = session.delete(
            url,
            headers=headers,
            timeout=TIMEOUT,
        )

    else:
        raise RuntimeError(f"Unsupported method: {method}")

    # --------------------------------------------------------
    # AUTH RETRY
    # --------------------------------------------------------

    if response.status_code == 401 and retry_auth:
        log("AUTH 401 -> RESYNC SERVER TIME -> RETRY")

        try:
            sync_server_time()
        except Exception as e:
            log(f"TIME RESYNC FAILED: {e}")

        params["timestamp"] = signed_timestamp()

        query_string, signature = make_signature(params)

        url = (
            f"{path}?{query_string}"
            f"&signature={signature}"
        )

        if method == "GET":
            response = session.get(
                url,
                headers=headers,
                timeout=TIMEOUT,
            )
        elif method == "POST":
            response = session.post(
                url,
                headers=headers,
                timeout=TIMEOUT,
            )
        elif method == "DELETE":
            response = session.delete(
                url,
                headers=headers,
                timeout=TIMEOUT,
            )

    return response


# ============================================================
# AUTH TEST
# ============================================================

def auth_test():
    notify(
        f"🔐 ATI AUTH TEST\n"
        f"🔑 PAIR: {AUTH_PAIR}\n"
        f"🧪 V40.2.54 HARDENED AUTH\n"
        f"🕐 {utc_now()}"
    )

    if not API_KEY:
        notify(
            "❌ AUTH CONFIG ERROR\n"
            "API KEY NOT FOUND\n"
            "Expected TABDIL_API_KEY"
        )
        return None

    if not API_SECRET:
        notify(
            "❌ AUTH CONFIG ERROR\n"
            "API SECRET NOT FOUND\n"
            "Expected TABDIL_API_SECRET"
        )
        return None

    # --------------------------------------------------------
    # SERVER TIME
    # --------------------------------------------------------

    try:
        server_time, offset = sync_server_time()

        notify(
            f"🕐 SERVER TIME OK\n"
            f"🌐 SERVER: {server_time}\n"
            f"⏱ OFFSET: {offset} ms\n"
            f"🔐 SIGNING: READY"
        )

    except Exception as e:
        notify(
            f"❌ SERVER TIME FAILED\n"
            f"⚠️ {str(e)[:300]}"
        )
        return None

    # --------------------------------------------------------
    # ACCOUNT
    # --------------------------------------------------------

    try:
        notify(
            "🔑 ACCOUNT REQUEST\n"
            "📡 /r/api/v1/account\n"
            "🧾 HMAC-SHA256\n"
            "⏳ WAITING..."
        )

        response = signed_request(
            "GET",
            f"{SIGNED_ROOT}/account",
        )

        if response.status_code != 200:

            body = response.text[:600]

            notify(
                f"❌ AUTH FAILED\n"
                f"🔑 PAIR: {AUTH_PAIR}\n"
                f"🌐 HTTP: {response.status_code}\n"
                f"⚠️ {body}\n"
                f"🕐 {utc_now()}"
            )

            return None

        data = response.json()

        can_trade = data.get("canTrade", False)

        balances = data.get("balances", [])

        usdt_free = Decimal("0")

        for item in balances:
            if str(item.get("asset", "")).upper() == "USDT":
                usdt_free = safe_decimal(
                    item.get("free", "0")
                )
                break

        notify(
            f"✅ AUTH SUCCESS\n"
            f"🔑 PAIR: {AUTH_PAIR}\n"
            f"🔓 canTrade={can_trade}\n"
            f"💰 USDT FREE: {fmt_decimal(usdt_free)}\n"
            f"🕐 {utc_now()}"
        )

        if not can_trade:
            notify(
                "🛑 ACCOUNT CANNOT TRADE\n"
                "REAL ORDER BLOCKED"
            )
            return None

        return data

    except Exception as e:

        notify(
            f"❌ AUTH EXCEPTION\n"
            f"⚠️ {str(e)[:500]}\n"
            f"🕐 {utc_now()}"
        )

        return None


# ============================================================
# PUBLIC API
# ============================================================

def get_exchange_info():
    r = session.get(
        f"{PUBLIC_ROOT}/exchangeInfo",
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def get_trades(symbol, limit=1000):
    r = session.get(
        f"{PUBLIC_ROOT}/trades",
        params={
            "symbol": symbol,
            "limit": limit,
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()

    data = r.json()

    if isinstance(data, dict):
        return data.get("data", [])

    return data


# ============================================================
# MARKET PARSING
# ============================================================

def extract_markets(exchange_info):

    if isinstance(exchange_info, dict):

        markets = (
            exchange_info.get("symbols")
            or exchange_info.get("data")
            or []
        )

    elif isinstance(exchange_info, list):
        markets = exchange_info

    else:
        markets = []

    result = []

    for m in markets:

        symbol = str(
            m.get("symbol")
            or m.get("s")
            or ""
        ).upper()

        if not symbol:
            continue

        if not symbol.endswith("USDT"):
            continue

        status = str(
            m.get("status")
            or "TRADING"
        ).upper()

        if status not in (
            "TRADING",
            "ENABLED",
            "ACTIVE",
            "",
        ):
            continue

        result.append(m)

    return result


def symbol_from_market(m):
    return str(
        m.get("symbol")
        or m.get("s")
        or ""
    ).upper()


def get_filter(market, filter_type):
    filters = market.get("filters") or []

    for f in filters:
        if (
            f.get("filterType")
            == filter_type
        ):
            return f

    return {}


def market_rules(market):

    lot = get_filter(
        market,
        "LOT_SIZE",
    )

    min_notional = get_filter(
        market,
        "MIN_NOTIONAL",
    )

    min_qty = safe_decimal(
        lot.get("minQty", "0")
    )

    step_size = safe_decimal(
        lot.get("stepSize", "0")
    )

    notional = (
        min_notional.get("minNotional")
        or min_notional.get("notional")
        or "0"
    )

    return {
        "min_qty": safe_decimal(min_qty),
        "step_size": safe_decimal(step_size),
        "min_notional": safe_decimal(notional),
    }


# ============================================================
# TRADES -> 5M CANDLES
# ============================================================

def build_candles(trades):

    candles = {}

    for t in trades:

        try:
            ts = int(
                t.get("time")
                or t.get("timestamp")
            )

            price = safe_decimal(
                t.get("price")
            )

            qty = safe_decimal(
                t.get("qty")
            )

            if price <= 0:
                continue

            bucket = (
                ts // 300000
            ) * 300000

            if bucket not in candles:

                candles[bucket] = {
                    "time": bucket,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": qty,
                }

            else:

                c = candles[bucket]

                c["high"] = max(
                    c["high"],
                    price,
                )

                c["low"] = min(
                    c["low"],
                    price,
                )

                c["close"] = price
                c["volume"] += qty

        except Exception:
            continue

    result = list(
        candles.values()
    )

    result.sort(
        key=lambda x: x["time"]
    )

    return result


# ============================================================
# PRICE ACTION
# ============================================================

def analyze_market(market):

    symbol = symbol_from_market(market)

    if not symbol:
        return None

    try:

        trades = get_trades(
            symbol,
            limit=1000,
        )

        candles = build_candles(
            trades
        )

        if len(candles) < MIN_CANDLES:
            return None

        # Closed candles only.
        closed = candles[:-1]

        if len(closed) < MIN_CANDLES:
            return None

        last = closed[-1]
        prev = closed[-2]

        recent = closed[-8:]

        swing_high = max(
            c["high"]
            for c in closed[-10:-2]
        )

        swing_low = min(
            c["low"]
            for c in closed[-10:-2]
        )

        close = last["close"]

        # ----------------------------------------------------
        # TREND
        # ----------------------------------------------------

        trend_up = (
            last["close"] > last["open"]
            and prev["close"] >= prev["open"]
        )

        # ----------------------------------------------------
        # BOS
        # ----------------------------------------------------

        bos_distance = (
            (close - swing_high)
            / swing_high
            * Decimal("100")
            if swing_high > 0
            else Decimal("-999")
        )

        near_distance = (
            (close - swing_high)
            / swing_high
            * Decimal("100")
            if swing_high > 0
            else Decimal("-999")
        )

        real_bos = (
            close > swing_high
            and bos_distance >= REAL_BOS_MIN
        )

        near_bos = (
            close >= swing_high
            and near_distance >= NEAR_BOS_MIN
        )

        if not real_bos and not near_bos:
            return None

        # ----------------------------------------------------
        # PULLBACK
        # ----------------------------------------------------

        bos_reference = swing_high

        pullback_low = min(
            c["low"]
            for c in recent
        )

        pullback_distance = (
            abs(
                bos_reference
                - pullback_low
            )
            / bos_reference
            * Decimal("100")
            if bos_reference > 0
            else Decimal("999")
        )

        pullback_ok = (
            pullback_distance
            <= PULLBACK_TOLERANCE
        )

        if not pullback_ok:
            return None

        # ----------------------------------------------------
        # CLOSED CONFIRMATION
        # ----------------------------------------------------

        candle_range = (
            last["high"]
            - last["low"]
        )

        if candle_range <= 0:
            return None

        close_position = (
            last["close"]
            - last["low"]
        ) / candle_range

        confirmation = (
            close_position
            >= MIN_CONFIRM_CLOSE_POSITION
        )

        if not confirmation:
            return None

        # ----------------------------------------------------
        # CHASE FILTER
        # ----------------------------------------------------

        chase = (
            (close - swing_high)
            / swing_high
            * Decimal("100")
            if swing_high > 0
            else Decimal("999")
        )

        if chase > CHASE_LIMIT:
            return None

        # ----------------------------------------------------
        # SCORE
        # ----------------------------------------------------

        score = 0

        if trend_up:
            score += 3

        if real_bos:
            score += 4
        elif near_bos:
            score += 2

        if pullback_ok:
            score += 2

        if confirmation:
            score += 3

        if close > prev["close"]:
            score += 1

        if score < MIN_SCORE:
            return None

        return {
            "symbol": symbol,
            "price": close,
            "score": score,
            "real_bos": real_bos,
            "near_bos": near_bos,
            "pullback": pullback_distance,
            "close_position": close_position,
            "chase": chase,
            "high": last["high"],
            "low": last["low"],
        }

    except Exception:
        return None


# ============================================================
# QUANTITY
# ============================================================

def floor_step(value, step):

    if step <= 0:
        return value

    try:

        return (
            value
            / step
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * step

    except Exception:
        return value


def calculate_quantity(
    market,
    price,
):

    rules = market_rules(
        market
    )

    min_qty = rules["min_qty"]
    step = rules["step_size"]
    min_notional = rules["min_notional"]

    if price <= 0:
        return Decimal("0")

    quantity = (
        ORDER_USDT
        / price
    )

    quantity = floor_step(
        quantity,
        step,
    )

    if quantity < min_qty:
        return Decimal("0")

    if (
        min_notional > 0
        and quantity * price < min_notional
    ):
        return Decimal("0")

    return quantity


# ============================================================
# REAL BUY
# ============================================================

def market_buy(
    symbol,
    quantity,
):

    if not LIVE_TRADING:

        notify(
            f"🟡 PAPER MODE\n"
            f"❌ REAL BUY BLOCKED\n"
            f"📊 {symbol}"
        )

        return None

    params = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quantity": fmt_decimal(
            quantity
        ),
    }

    notify(
        f"🚨 REAL BUY STARTING\n"
        f"📊 {symbol}\n"
        f"💵 TARGET: {ORDER_USDT} USDT\n"
        f"📦 QTY: {fmt_decimal(quantity)}\n"
        f"⏳ SENDING ORDER..."
    )

    try:

        response = signed_request(
            "POST",
            f"{ORDER_ROOT}/order",
            params,
        )

        if response.status_code not in (
            200,
            201,
        ):

            notify(
                f"❌ REAL BUY FAILED\n"
                f"📊 {symbol}\n"
                f"🌐 HTTP: {response.status_code}\n"
                f"⚠️ {response.text[:500]}"
            )

            return None

        data = response.json()

        notify(
            f"✅ REAL BUY ACCEPTED\n"
            f"📊 {symbol}\n"
            f"🆔 ORDER: "
            f"{data.get('orderId')}\n"
            f"📦 QTY: "
            f"{data.get('executedQty') or data.get('origQty')}\n"
            f"📌 STATUS: "
            f"{data.get('status')}"
        )

        return data

    except Exception as e:

        notify(
            f"❌ REAL BUY EXCEPTION\n"
            f"📊 {symbol}\n"
            f"⚠️ {str(e)[:500]}"
        )

        return None


# ============================================================
# OCO
# ============================================================

def place_oco(
    symbol,
    quantity,
    entry_price,
):

    if not LIVE_TRADING:
        return None

    if entry_price <= 0:
        return None

    stop_price = (
        entry_price
        * (
            Decimal("1")
            - STOP_LOSS_PCT
            / Decimal("100")
        )
    )

    take_price = (
        entry_price
        * (
            Decimal("1")
            + TAKE_PROFIT_PCT
            / Decimal("100")
        )
    )

    stop_limit = (
        stop_price
        * Decimal("0.999")
    )

    params = {
        "symbol": symbol,
        "side": "SELL",
        "quantity": fmt_decimal(quantity),
        "price": fmt_decimal(take_price),
        "stopPrice": fmt_decimal(stop_price),
        "stopLimitPrice": fmt_decimal(stop_limit),
    }

    notify(
        f"🛡️ OCO STARTING\n"
        f"📊 {symbol}\n"
        f"🟢 ENTRY: {fmt_decimal(entry_price)}\n"
        f"🔴 SL: {fmt_decimal(stop_price)}\n"
        f"🎯 TP: {fmt_decimal(take_price)}"
    )

    try:

        response = signed_request(
            "POST",
            f"{ORDER_ROOT}/order/oco",
            params,
        )

        if response.status_code not in (
            200,
            201,
        ):

            notify(
                f"⚠️ OCO FAILED\n"
                f"📊 {symbol}\n"
                f"🌐 HTTP: {response.status_code}\n"
                f"⚠️ {response.text[:500]}\n"
                f"‼️ CHECK OPEN ORDERS"
            )

            return None

        data = response.json()

        notify(
            f"✅ OCO ACTIVE\n"
            f"📊 {symbol}\n"
            f"🛡️ SL/TP PROTECTION ACTIVE\n"
            f"🆔 OCO: "
            f"{data.get('orderListId')}"
        )

        return data

    except Exception as e:

        notify(
            f"⚠️ OCO EXCEPTION\n"
            f"📊 {symbol}\n"
            f"⚠️ {str(e)[:500]}\n"
            f"‼️ CHECK OPEN ORDERS"
        )

        return None


# ============================================================
# MAIN SCAN
# ============================================================

def scan_markets(markets):

    selected = markets[:SCAN_LIMIT]

    notify(
        f"📡 SCAN STARTING\n"
        f"📊 USDT MARKETS: {len(markets)}\n"
        f"🔎 SCANNING: {len(selected)}\n"
        f"⏱ TIMEFRAME: 5m CLOSED\n"
        f"🧠 BOS → PULLBACK → CONTINUATION"
    )

    candidates = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_market,
                m
            ): m
            for m in selected
        }

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:
                    candidates.append(result)

            except Exception:
                pass

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["real_bos"],
            -float(x["chase"]),
        ),
        reverse=True,
    )

    return candidates


# ============================================================
# RUN
# ============================================================

def main():

    notify(
        f"💓 ATI ALIVE\n"
        f"⚡ {VERSION}\n"
        f"🟢 NEW RUN STARTED\n"
        f"🕐 {utc_now()}"
    )

    notify(
        f"⚡ ATI BOT {VERSION}\n"
        f"🧠 REAL BOS / NEAR BOS → PULLBACK → "
        f"CONTINUATION → CLOSED\n"
        f"🚫 EMA: OFF\n"
        f"🔓 REAL TRADING: "
        f"{'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"
        f"💵 ORDER TARGET: {ORDER_USDT} USDT\n"
        f"🔑 AUTH PAIR: {AUTH_PAIR}\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    account = auth_test()

    if not account:

        notify(
            f"🛑 BOT STOPPED\n"
            f"❌ AUTH FAILED\n"
            f"🔐 NO ORDER SENT\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # EXCHANGE INFO
    # --------------------------------------------------------

    try:

        notify(
            "📚 EXCHANGE INFO\n"
            "⏳ LOADING MARKETS..."
        )

        exchange_info = get_exchange_info()

        markets = extract_markets(
            exchange_info
        )

        notify(
            f"✅ MARKET INFO OK\n"
            f"📊 USDT MARKETS: {len(markets)}"
        )

    except Exception as e:

        notify(
            f"❌ MARKET INFO FAILED\n"
            f"⚠️ {str(e)[:500]}"
        )

        return

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    candidates = scan_markets(
        markets
    )

    if not candidates:

        notify(
            f"💓 ATI RUN ALIVE\n"
            f"📡 SCAN FINISHED\n"
            f"👀 NO BUY\n"
            f"🕐 {utc_now()}"
        )

        return

    best = candidates[0]

    notify(
        f"🔥 BUY CANDIDATE\n"
        f"📊 {best['symbol']}\n"
        f"💰 PRICE: {fmt_decimal(best['price'])}\n"
        f"⭐ SCORE: {best['score']}\n"
        f"🧠 REAL BOS: "
        f"{best['real_bos']}\n"
        f"📐 PULLBACK: "
        f"{best['pullback']:.3f}%\n"
        f"🔒 CLOSED CONFIRM: YES"
    )

    # --------------------------------------------------------
    # MAX ONE BUY
    # --------------------------------------------------------

    if MAX_BUYS_PER_RUN < 1:
        return

    market = None

    for m in markets:
        if (
            symbol_from_market(m)
            == best["symbol"]
        ):
            market = m
            break

    if not market:

        notify(
            "🛑 BUY CANCELLED\n"
            "MARKET RULES NOT FOUND"
        )

        return

    quantity = calculate_quantity(
        market,
        best["price"],
    )

    if quantity <= 0:

        rules = market_rules(
            market
        )

        notify(
            f"🛑 BUY SKIPPED\n"
            f"📊 {best['symbol']}\n"
            f"💵 ORDER TARGET: {ORDER_USDT}\n"
            f"📦 MIN QTY: "
            f"{fmt_decimal(rules['min_qty'])}\n"
            f"📏 STEP: "
            f"{fmt_decimal(rules['step_size'])}\n"
            f"💰 MIN NOTIONAL: "
            f"{fmt_decimal(rules['min_notional'])}"
        )

        return

    # --------------------------------------------------------
    # REAL BUY
    # --------------------------------------------------------

    order = market_buy(
        best["symbol"],
        quantity,
    )

    if not order:
        return

    # --------------------------------------------------------
    # EXECUTED PRICE / QTY
    # --------------------------------------------------------

    executed_qty = safe_decimal(
        order.get("executedQty")
        or order.get("origQty")
        or quantity
    )

    executed_quote = safe_decimal(
        order.get(
            "cummulativeQuoteQty"
        )
        or order.get(
            "cumulativeQuoteQty"
        )
        or "0"
    )

    if (
        executed_qty > 0
        and executed_quote > 0
    ):
        entry_price = (
            executed_quote
            / executed_qty
        )
    else:
        entry_price = best["price"]

    # --------------------------------------------------------
    # PROTECTION
    # --------------------------------------------------------

    place_oco(
        best["symbol"],
        executed_qty,
        entry_price,
    )

    notify(
        f"🏁 ATI RUN COMPLETED\n"
        f"⚡ {VERSION}\n"
        f"📊 {best['symbol']}\n"
        f"🟢 ENTRY: {fmt_decimal(entry_price)}\n"
        f"📦 QTY: {fmt_decimal(executed_qty)}\n"
        f"🕐 {utc_now()}"
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:
        main()

    except Exception as e:

        notify(
            f"💥 ATI FATAL ERROR\n"
            f"⚡ {VERSION}\n"
            f"⚠️ {str(e)[:700]}\n"
            f"🕐 {utc_now()}"
        )

        raise
