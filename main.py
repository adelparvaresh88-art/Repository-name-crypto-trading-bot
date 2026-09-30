import os
import json
import time
import math
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.9
# REAL SPOT BUY -> FILLED CHECK -> OCO TP/SL
# ============================================================

VERSION = "V40.2.9"

BASE_URL = "https://api1.tabdeal.org"

EXCHANGE_INFO_PATH = "/r/api/v1/exchangeInfo"
TRADES_PATH = "/r/api/v1/trades"

ORDER_PATH = "/api/v1/order"
ORDER_QUERY_PATH = "/r/api/v1/order"
OCO_PATH = "/api/v1/order/oco"

REQUEST_TIMEOUT = 15
TELEGRAM_TIMEOUT = 15
TELEGRAM_RETRIES = 4

MAX_SYMBOLS = 529
MAX_REAL_BUYS_PER_RUN = 1

MIN_CANDLES = 12
MAX_HISTORY = 500

CONFIRMED_SCORE = 10
EARLY_SCORE = 9
WATCH_SCORE = 6

MAX_RISK_PCT = 1.20

TP1_R = 1.67
TP2_R = 2.67

RECV_WINDOW = 10000

HISTORY_FILE = "paper_history.json"


# ============================================================
# ENV
# ============================================================

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

ORDER_QTY_RAW = os.getenv("ORDER_QTY", "0.001").strip()

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").strip().lower() == "true"

REAL_TRADING_CONFIRM = (
    os.getenv("REAL_TRADING_CONFIRM", "").strip().upper() == "YES"
)

# Real trading requires BOTH flags.
REAL_ORDERS = LIVE_TRADING and REAL_TRADING_CONFIRM


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/40.2.9",
        "Accept": "application/json",
    }
)


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send_once(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        r = session.post(
            url,
            json=payload,
            timeout=TELEGRAM_TIMEOUT,
        )

        if r.status_code != 200:
            return False

        data = r.json()

        return bool(data.get("ok"))

    except Exception:
        return False


def telegram_send(message):
    if not message:
        return False

    chunks = []

    max_len = 3500

    for i in range(0, len(message), max_len):
        chunks.append(message[i:i + max_len])

    all_ok = True

    for chunk in chunks:

        sent = False

        for attempt in range(TELEGRAM_RETRIES):

            if telegram_send_once(chunk):
                sent = True
                break

            time.sleep(2 + attempt * 2)

        if not sent:
            all_ok = False

    return all_ok


def heartbeat(text):
    telegram_send(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"{text}\n\n"
        f"🕐 {utc_now()}"
    )


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def now_ms():
    return int(time.time() * 1000)


# ============================================================
# NUMBER HELPERS
# ============================================================

def D(value):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def fmt(value, digits=12):
    try:
        x = D(value)

        s = f"{x:.{digits}f}".rstrip("0").rstrip(".")

        if s == "-0":
            s = "0"

        return s

    except Exception:
        return str(value)


def floor_step(value, step):
    value = D(value)
    step = D(step)

    if step <= 0:
        return value

    return (value / step).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


def floor_to_tick(value, tick):
    return floor_step(value, tick)


# ============================================================
# SIGNATURE
# ============================================================

def make_signature(params):
    query = "&".join(
        f"{key}={params[key]}"
        for key in params
        if params[key] is not None
    )

    return hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def signed_params(params=None):
    params = dict(params or {})

    params["timestamp"] = now_ms()
    params["recvWindow"] = RECV_WINDOW

    params["signature"] = make_signature(params)

    return params


# ============================================================
# API
# ============================================================

def public_get(path, params=None):
    url = BASE_URL + path

    r = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    r.raise_for_status()

    return r.json()


def signed_get(path, params=None):
    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDEAL_API_KEY / TABDEAL_API_SECRET missing"
        )

    payload = signed_params(params)

    r = session.get(
        BASE_URL + path,
        params=payload,
        headers={"X-MBX-APIKEY": API_KEY},
        timeout=REQUEST_TIMEOUT,
    )

    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}

    if r.status_code >= 400:
        raise RuntimeError(
            f"GET {path} HTTP {r.status_code}: {data}"
        )

    return data


def signed_post(path, params=None):
    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDEAL_API_KEY / TABDEAL_API_SECRET missing"
        )

    payload = signed_params(params)

    r = session.post(
        BASE_URL + path,
        data=payload,
        headers={"X-MBX-APIKEY": API_KEY},
        timeout=REQUEST_TIMEOUT,
    )

    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}

    if r.status_code >= 400:
        raise RuntimeError(
            f"POST {path} HTTP {r.status_code}: {data}"
        )

    return data


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():
    return public_get(EXCHANGE_INFO_PATH)


def extract_symbols(exchange):
    if isinstance(exchange, dict):

        symbols = exchange.get("symbols")

        if isinstance(symbols, list):
            return symbols

        # Some responses can be a single market object.
        if exchange.get("symbol"):
            return [exchange]

    if isinstance(exchange, list):
        return exchange

    return []


def is_usdt_market(item):
    symbol = str(item.get("symbol", "")).upper()
    tabdeal_symbol = str(
        item.get("tabdealSymbol", "")
    ).upper()

    quote = str(
        item.get("quoteAsset", "")
    ).upper()

    return (
        quote == "USDT"
        or symbol.endswith("USDT")
        or tabdeal_symbol.endswith("_USDT")
    )


def market_symbol(item):
    return str(
        item.get("symbol")
        or item.get("market")
        or ""
    ).upper()


def tabdeal_symbol(item):
    value = item.get("tabdealSymbol")

    if value:
        return str(value).upper()

    symbol = market_symbol(item)

    if symbol.endswith("USDT"):
        return symbol[:-4] + "_USDT"

    return symbol


def market_filters(item):
    filters = item.get("filters", [])

    result = {
        "tickSize": Decimal("0"),
        "stepSize": Decimal("0"),
        "minQty": Decimal("0"),
        "maxQty": Decimal("0"),
        "minNotional": Decimal("0"),
        "ocoAllowed": bool(item.get("ocoAllowed", False)),
    }

    for f in filters:

        ftype = str(
            f.get("filterType", "")
        ).upper()

        if ftype == "PRICE_FILTER":
            result["tickSize"] = D(
                f.get("tickSize", "0")
            )

        elif ftype == "LOT_SIZE":
            result["stepSize"] = D(
                f.get("stepSize", "0")
            )

            result["minQty"] = D(
                f.get("minQty", "0")
            )

            result["maxQty"] = D(
                f.get("maxQty", "0")
            )

        elif ftype == "MARKET_LOT_SIZE":

            # Prefer market lot size for market BUY.
            step = D(f.get("stepSize", "0"))

            if step > 0:
                result["marketStepSize"] = step

            result["marketMinQty"] = D(
                f.get("minQty", "0")
            )

            result["marketMaxQty"] = D(
                f.get("maxQty", "0")
            )

        elif ftype == "MIN_NOTIONAL":

            result["minNotional"] = D(
                f.get("minNotional", "0")
            )

    if "marketStepSize" not in result:
        result["marketStepSize"] = result["stepSize"]

    return result


# ============================================================
# TRADES -> 5M CANDLES
# ============================================================

def get_trades(symbol):
    return public_get(
        TRADES_PATH,
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )


def trade_price(t):
    for key in ("price", "p"):
        if key in t:
            return D(t[key])

    return Decimal("0")


def trade_qty(t):
    for key in ("qty", "quantity", "q"):
        if key in t:
            return D(t[key])

    return Decimal("0")


def trade_time(t):
    for key in ("time", "timestamp", "T"):
        if key in t:
            try:
                return int(t[key])
            except Exception:
                pass

    return 0


def trade_side(t):
    for key in ("isBuyerMaker",):

        if key in t:
            return "SELL" if bool(t[key]) else "BUY"

    side = str(t.get("side", "")).upper()

    if side in ("BUY", "SELL"):
        return side

    return ""


def build_5m_candles(trades):
    buckets = {}

    for t in trades:

        p = trade_price(t)
        q = trade_qty(t)
        ts = trade_time(t)

        if p <= 0 or q <= 0 or ts <= 0:
            continue

        bucket = (ts // 300000) * 300000

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": p,
                "high": p,
                "low": p,
                "close": p,
                "volume": q,
                "buy_volume": Decimal("0"),
                "sell_volume": Decimal("0"),
                "trades": 1,
            }

        else:

            c = buckets[bucket]

            c["high"] = max(c["high"], p)
            c["low"] = min(c["low"], p)
            c["close"] = p
            c["volume"] += q
            c["trades"] += 1

        side = trade_side(t)

        if side == "BUY":
            buckets[bucket]["buy_volume"] += q

        elif side == "SELL":
            buckets[bucket]["sell_volume"] += q

    candles = list(
        sorted(
            buckets.values(),
            key=lambda x: x["time"],
        )
    )

    return candles[-MAX_HISTORY:]


# ============================================================
# INDICATOR-LITE PRICE ACTION
# ============================================================

def candle_body(c):
    return abs(c["close"] - c["open"])


def candle_range(c):
    return max(
        c["high"] - c["low"],
        Decimal("0.0000000001"),
    )


def bullish(c):
    return c["close"] > c["open"]


def pressure_value(candles):
    recent = candles[-5:]

    total_buy = sum(
        c["buy_volume"]
        for c in recent
    )

    total_sell = sum(
        c["sell_volume"]
        for c in recent
    )

    total = total_buy + total_sell

    if total > 0:
        return float(
            total_buy / total * Decimal("100")
        )

    score = Decimal("0")

    for c in recent:

        r = candle_range(c)

        body = c["close"] - c["open"]

        score += body / r

    avg = score / Decimal(
        max(len(recent), 1)
    )

    return float(
        max(
            Decimal("0"),
            min(
                Decimal("100"),
                Decimal("50") + avg * Decimal("50"),
            ),
        )
    )


def average_volume(candles, n=5):
    data = candles[-n:]

    if not data:
        return Decimal("0")

    return sum(
        c["volume"] for c in data
    ) / Decimal(len(data))


def recent_low(candles, n=8):
    return min(
        c["low"]
        for c in candles[-n:]
    )


def recent_high(candles, n=8):
    return max(
        c["high"]
        for c in candles[-n:]
    )


# ============================================================
# STRATEGY
# ============================================================

def analyze(symbol, candles):

    if len(candles) < MIN_CANDLES:
        return None

    closed = candles[:-1]

    if len(closed) < MIN_CANDLES:
        return None

    last = closed[-1]
    prev = closed[-2]

    price = last["close"]

    if price <= 0:
        return None

    score = 0
    reasons = []

    # --------------------------------------------------------
    # Momentum
    # --------------------------------------------------------

    if last["close"] > prev["close"]:
        score += 1
        reasons.append("MOMENTUM")

    if (
        closed[-3]["close"]
        < closed[-2]["close"]
        < closed[-1]["close"]
    ):
        score += 2
        reasons.append("3C-UP")

    # --------------------------------------------------------
    # Breakout
    # --------------------------------------------------------

    prior_high = max(
        c["high"]
        for c in closed[-7:-1]
    )

    breakout = last["close"] > prior_high

    if breakout:
        score += 3
        reasons.append("BREAKOUT")

    # --------------------------------------------------------
    # Candle quality
    # --------------------------------------------------------

    rng = candle_range(last)
    body = candle_body(last)

    body_ratio = body / rng

    if bullish(last):
        score += 1
        reasons.append("BULLISH")

    if body_ratio >= Decimal("0.55"):
        score += 1
        reasons.append("STRONG-BODY")

    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------

    avg_vol = average_volume(
        closed[:-1],
        5,
    )

    if avg_vol > 0 and last["volume"] > avg_vol * Decimal("1.15"):
        score += 1
        reasons.append("VOL-BREAK")

    # --------------------------------------------------------
    # Pressure
    # --------------------------------------------------------

    pressure = pressure_value(closed)

    if pressure >= 58:
        score += 1
        reasons.append("BUY-PRESSURE")

    # --------------------------------------------------------
    # Higher structure
    # --------------------------------------------------------

    highs = [
        c["high"]
        for c in closed[-5:]
    ]

    lows = [
        c["low"]
        for c in closed[-5:]
    ]

    higher_highs = highs[-1] > highs[-2]
    higher_lows = lows[-1] > lows[-2]

    if higher_highs and higher_lows:
        score += 1
        reasons.append("HH-HL")

    # --------------------------------------------------------
    # Move
    # --------------------------------------------------------

    move = float(
        (price - closed[-4]["close"])
        / closed[-4]["close"]
        * Decimal("100")
    )

    # --------------------------------------------------------
    # Signal class
    # --------------------------------------------------------

    confirmed = (
        breakout
        and score >= CONFIRMED_SCORE
        and pressure >= 58
    )

    early = (
        score >= EARLY_SCORE
        and pressure >= 60
        and move > 0.15
    )

    watch = score >= WATCH_SCORE

    if confirmed:
        signal_type = "CONFIRMED BUY"

    elif early:
        signal_type = "EARLY BUY"

    elif watch:
        signal_type = "WATCH"

    else:
        return None

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    structural_low = recent_low(
        closed,
        8,
    )

    max_allowed_sl = price * (
        Decimal("1")
        - Decimal(str(MAX_RISK_PCT)) / Decimal("100")
    )

    sl = structural_low

    if sl <= 0 or sl >= price:
        sl = max_allowed_sl

    if sl < max_allowed_sl:
        sl = max_allowed_sl

    risk = price - sl

    if risk <= 0:
        return None

    tp1 = price + risk * Decimal(str(TP1_R))
    tp2 = price + risk * Decimal(str(TP2_R))

    return {
        "symbol": symbol,
        "price": price,
        "score": score,
        "pressure": pressure,
        "move": move,
        "signal": signal_type,
        "breakout": breakout,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "reasons": reasons,
    }


# ============================================================
# HISTORY
# ============================================================

def load_history():

    if not os.path.exists(HISTORY_FILE):
        return {
            "signals": {},
            "real_trades": {},
        }

    try:
        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError()

        data.setdefault("signals", {})
        data.setdefault("real_trades", {})

        return data

    except Exception:
        return {
            "signals": {},
            "real_trades": {},
        }


def save_history(data):

    tmp = HISTORY_FILE + ".tmp"

    with open(
        tmp,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

    os.replace(
        tmp,
        HISTORY_FILE,
    )


# ============================================================
# SIGNAL ID
# ============================================================

def signal_id(signal):
    return (
        f"{signal['symbol']}_"
        f"{fmt(signal['price'], 8)}"
    )


# ============================================================
# REAL ORDER
# ============================================================

def order_status_filled(status):
    return str(status).upper() in (
        "FILLED",
    )


def place_real_market_buy(
    symbol,
    tab_symbol,
    quantity,
):
    params = {
        "symbol": symbol,
        "tabdealSymbol": tab_symbol,
        "side": "BUY",
        "type": "MARKET",
        "quantity": fmt(quantity),
    }

    return signed_post(
        ORDER_PATH,
        params,
    )


def query_real_order(
    symbol,
    tab_symbol,
    order_id,
):
    params = {
        "tabdealSymbol": tab_symbol,
        "orderId": order_id,
    }

    return signed_get(
        ORDER_QUERY_PATH,
        params,
    )


def extract_executed_qty(order):
    return D(
        order.get(
            "executedQty",
            order.get("origQty", "0"),
        )
    )


def extract_average_price(order):

    qty = extract_executed_qty(order)

    quote = D(
        order.get(
            "cummulativeQuoteQty",
            order.get(
                "cumulativeQuoteQty",
                "0",
            ),
        )
    )

    if qty > 0 and quote > 0:
        return quote / qty

    price = D(
        order.get(
            "price",
            "0",
        )
    )

    return price


def wait_until_filled(
    symbol,
    tab_symbol,
    order,
):

    status = str(
        order.get("status", "")
    ).upper()

    if order_status_filled(status):
        return order

    order_id = order.get("orderId")

    if not order_id:
        return order

    for _ in range(4):

        time.sleep(2)

        current = query_real_order(
            symbol,
            tab_symbol,
            order_id,
        )

        status = str(
            current.get("status", "")
        ).upper()

        if order_status_filled(status):
            return current

        if status in (
            "CANCELED",
            "REJECTED",
            "EXPIRED",
        ):
            return current

    return order


# ============================================================
# OCO
# ============================================================

def place_real_oco(
    symbol,
    tab_symbol,
    quantity,
    tp_price,
    stop_price,
    stop_limit_price,
    client_tag,
):

    list_client_id = f"oco_{client_tag}"
    limit_client_id = f"tp_{client_tag}"
    stop_client_id = f"sl_{client_tag}"

    params = {
        "symbol": symbol,
        "tabdealSymbol": tab_symbol,
        "listClientOrderId": list_client_id,
        "limitClientOrderId": limit_client_id,
        "stopClientOrderId": stop_client_id,
        "side": "SELL",
        "quantity": fmt(quantity),
        "price": fmt(tp_price),
        "stopPrice": fmt(stop_price),
        "stopLimitPrice": fmt(stop_limit_price),
    }

    return signed_post(
        OCO_PATH,
        params,
    )


# ============================================================
# REAL TRADE EXECUTION
# ============================================================

def execute_real_trade(
    market,
    signal,
):

    if not REAL_ORDERS:
        return {
            "ok": False,
            "disabled": True,
        }

    symbol = market_symbol(market)
    tab_symbol = tabdeal_symbol(market)

    filters = market_filters(market)

    if not filters["ocoAllowed"]:
        raise RuntimeError(
            f"{symbol}: OCO_NOT_ALLOWED"
        )

    try:
        requested_qty = D(
            ORDER_QTY_RAW
        )
    except Exception:
        raise RuntimeError(
            "ORDER_QTY invalid"
        )

    if requested_qty <= 0:
        raise RuntimeError(
            "ORDER_QTY must be > 0"
        )

    step = filters["marketStepSize"]

    if step <= 0:
        step = filters["stepSize"]

    quantity = floor_step(
        requested_qty,
        step,
    )

    min_qty = max(
        filters["marketMinQty"],
        filters["minQty"],
    )

    max_qty = max(
        filters["marketMaxQty"],
        filters["maxQty"],
    )

    if quantity < min_qty:
        raise RuntimeError(
            f"{symbol}: quantity {quantity} "
            f"< minimum {min_qty}"
        )

    if max_qty > 0 and quantity > max_qty:
        quantity = floor_step(
            max_qty,
            step,
        )

    # --------------------------------------------------------
    # Step 1: REAL MARKET BUY
    # --------------------------------------------------------

    telegram_send(
        f"🚨 REAL BUY STARTING\n\n"
        f"🪙 {symbol}\n"
        f"📦 QTY: {fmt(quantity)}\n"
        f"📊 SCORE: {signal['score']}\n"
        f"💪 PRESSURE: {signal['pressure']:.1f}%\n"
        f"🧠 {signal['signal']}\n\n"
        f"⚠️ REAL ORDER"
    )

    buy_order = place_real_market_buy(
        symbol,
        tab_symbol,
        quantity,
    )

    buy_order = wait_until_filled(
        symbol,
        tab_symbol,
        buy_order,
    )

    status = str(
        buy_order.get("status", "")
    ).upper()

    if not order_status_filled(status):

        telegram_send(
            f"❌ REAL BUY NOT FILLED\n\n"
            f"🪙 {symbol}\n"
            f"STATUS: {status}\n"
            f"ORDER ID: "
            f"{buy_order.get('orderId', '-')}"
        )

        return {
            "ok": False,
            "status": status,
            "buy_order": buy_order,
        }

    executed_qty = extract_executed_qty(
        buy_order
    )

    entry = extract_average_price(
        buy_order
    )

    if executed_qty <= 0:
        raise RuntimeError(
            f"{symbol}: filled but executedQty=0"
        )

    if entry <= 0:
        entry = signal["price"]

    # --------------------------------------------------------
    # Recalculate TP / SL from actual filled price
    # --------------------------------------------------------

    structural_sl = D(
        signal["sl"]
    )

    if structural_sl >= entry:
        structural_sl = entry * Decimal("0.99")

    risk = entry - structural_sl

    if risk <= 0:
        raise RuntimeError(
            f"{symbol}: invalid real SL"
        )

    tp1 = entry + risk * Decimal(
        str(TP1_R)
    )

    tp2 = entry + risk * Decimal(
        str(TP2_R)
    )

    tick = filters["tickSize"]

    if tick > 0:

        tp1 = floor_to_tick(
            tp1,
            tick,
        )

        tp2 = floor_to_tick(
            tp2,
            tick,
        )

        structural_sl = floor_to_tick(
            structural_sl,
            tick,
        )

    # OCO uses one TP + one SL.
    # TP1 is used as the OCO take-profit.
    # TP2 remains a paper/reference target.

    tp_price = tp1

    # Stop-limit execution price is slightly below trigger.
    stop_price = structural_sl

    stop_limit_price = structural_sl

    if tick > 0:
        stop_limit_price = (
            structural_sl - tick
        )

        if stop_limit_price <= 0:
            stop_limit_price = structural_sl

    # --------------------------------------------------------
    # Step 2: REAL OCO
    # --------------------------------------------------------

    telegram_send(
        f"✅ REAL BUY FILLED\n\n"
        f"🪙 {symbol}\n"
        f"📦 FILLED: {fmt(executed_qty)}\n"
        f"💰 ENTRY: {fmt(entry)}\n\n"
        f"➡️ OCO STARTING\n"
        f"🎯 TP1: {fmt(tp_price)}\n"
        f"🛑 SL: {fmt(stop_price)}\n"
        f"🎯 TP2 REF: {fmt(tp2)}"
    )

    client_tag = str(
        buy_order.get(
            "orderId",
            int(time.time()),
        )
    )

    oco = place_real_oco(
        symbol=symbol,
        tab_symbol=tab_symbol,
        quantity=executed_qty,
        tp_price=tp_price,
        stop_price=stop_price,
        stop_limit_price=stop_limit_price,
        client_tag=client_tag,
    )

    telegram_send(
        f"🛡 REAL OCO ACTIVE\n\n"
        f"🪙 {symbol}\n"
        f"📦 QTY: {fmt(executed_qty)}\n"
        f"💰 ENTRY: {fmt(entry)}\n"
        f"🎯 TP1: {fmt(tp_price)}\n"
        f"🛑 SL: {fmt(stop_price)}\n\n"
        f"📋 OCO ID: "
        f"{oco.get('orderListId', '-')}"
    )

    return {
        "ok": True,
        "symbol": symbol,
        "tabdealSymbol": tab_symbol,
        "buy_order": buy_order,
        "oco": oco,
        "quantity": str(executed_qty),
        "entry": str(entry),
        "tp1": str(tp_price),
        "tp2": str(tp2),
        "sl": str(stop_price),
    }


# ============================================================
# PAPER SUMMARY
# ============================================================

def summary(history):

    trades = history.get(
        "signals",
        {},
    )

    total = len(trades)

    tp1 = 0
    tp2 = 0
    sl = 0
    open_count = 0
    ambiguous = 0

    for item in trades.values():

        status = str(
            item.get("status", "OPEN")
        ).upper()

        if status == "TP1":
            tp1 += 1

        elif status == "TP2":
            tp2 += 1

        elif status == "SL":
            sl += 1

        elif status == "AMBIGUOUS":
            ambiguous += 1

        else:
            open_count += 1

    closed = tp2 + sl

    win_rate = (
        (tp2 / closed * 100)
        if closed > 0
        else 0
    )

    return {
        "total": total,
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "open": open_count,
        "ambiguous": ambiguous,
        "win_rate": win_rate,
    }


# ============================================================
# REPORT
# ============================================================

def signal_text(signal):

    return (
        f"🟢 {signal['signal']}\n"
        f"🪙 {signal['symbol']}\n"
        f"💰 PRICE: {fmt(signal['price'])}\n"
        f"📊 SCORE: {signal['score']}\n"
        f"💪 PRESSURE: {signal['pressure']:.1f}%\n"
        f"📈 MOVE: {signal['move']:.2f}%\n"
        f"🛑 SL: {fmt(signal['sl'])}\n"
        f"🎯 TP1: {fmt(signal['tp1'])}\n"
        f"🎯 TP2: {fmt(signal['tp2'])}\n"
        f"🧠 {', '.join(signal['reasons'])}\n"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    heartbeat(
        "📡 TABDEAL API: CONNECTING...\n"
        "📊 SCAN: STARTING\n"
        "⏱ TIMEFRAME: 5m\n"
        "🕯 CLOSED CANDLE: YES\n"
        f"📊 REAL ORDERS: "
        f"{'ENABLED' if REAL_ORDERS else 'DISABLED'}"
    )

    if not API_KEY or not API_SECRET:

        heartbeat(
            "❌ TABDEAL PRIVATE API KEYS MISSING\n"
            "Paper scanning can continue, "
            "but real trading is disabled."
        )

    exchange = get_exchange_info()

    heartbeat(
        "📡 TABDEAL API: OK\n"
        "📊 EXCHANGE INFO: OK"
    )

    all_markets = extract_symbols(
        exchange
    )

    markets = [
        m
        for m in all_markets
        if is_usdt_market(m)
        and str(
            m.get("status", "TRADING")
        ).upper() == "TRADING"
    ]

    markets = markets[:MAX_SYMBOLS]

    heartbeat(
        f"📊 USDT MARKETS: {len(markets)}\n"
        f"📡 REQUESTED: {len(markets)}\n"
        f"🟢 REAL MODE: "
        f"{'ON' if REAL_ORDERS else 'OFF'}"
    )

    candidates = []

    valid = 0
    insufficient = 0
    errors = 0

    for market in markets:

        symbol = market_symbol(market)

        if not symbol:
            continue

        try:

            trades = get_trades(symbol)

            candles = build_5m_candles(
                trades
            )

            if len(candles) < MIN_CANDLES:
                insufficient += 1
                continue

            valid += 1

            signal = analyze(
                symbol,
                candles,
            )

            if signal:
                signal["market"] = market
                candidates.append(signal)

        except Exception:
            errors += 1
            continue

    # --------------------------------------------------------
    # Ranking
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["pressure"],
            x["move"],
        ),
        reverse=True,
    )

    top = candidates[:10]

    history = load_history()

    # --------------------------------------------------------
    # Telegram scan report
    # --------------------------------------------------------

    report = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n"
        f"🧠 OPPORTUNITY ENGINE\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n"
        f"📊 VALID TRADES: {valid}\n"
        f"⚠️ INSUFFICIENT DATA: {insufficient}\n"
        f"⚠️ API/SCAN ERRORS: {errors}\n\n"
        f"🔧 REAL ORDERS: "
        f"{'ENABLED' if REAL_ORDERS else 'DISABLED'}\n"
        f"🕐 {utc_now()}\n"
        f"\n━━━━━━━━━━━━━━━━━━\n"
    )

    if not top:

        report += (
            "🟢 BUY CANDIDATES\n"
            "NONE\n"
        )

    else:

        report += (
            f"🟢 TOP BUY/WATCH CANDIDATES: "
            f"{len(top)}\n\n"
        )

        for i, signal in enumerate(
            top,
            start=1,
        ):

            report += (
                f"{i}. "
                f"{signal['symbol']} | "
                f"{signal['signal']} | "
                f"SCORE {signal['score']} | "
                f"P {signal['pressure']:.0f}%\n"
            )

    stats = summary(history)

    report += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "📊 BUY RESULT SUMMARY\n\n"
        f"📌 TOTAL BUY: {stats['total']}\n"
        f"🎯 TP1 HIT: {stats['tp1']}\n"
        f"🏆 TP2: {stats['tp2']}\n"
        f"❌ SL: {stats['sl']}\n"
        f"⏳ OPEN: {stats['open']}\n"
        f"⚠️ AMBIGUOUS: {stats['ambiguous']}\n"
        f"📈 WIN RATE: {stats['win_rate']:.1f}%\n"
    )

    telegram_send(report)

    # --------------------------------------------------------
    # New signals
    # --------------------------------------------------------

    real_buy_done = 0

    for signal in top:

        sid = signal_id(signal)

        if sid in history["signals"]:
            continue

        history["signals"][sid] = {
            "symbol": signal["symbol"],
            "entry": str(
                signal["price"]
            ),
            "sl": str(
                signal["sl"]
            ),
            "tp1": str(
                signal["tp1"]
            ),
            "tp2": str(
                signal["tp2"]
            ),
            "score": signal["score"],
            "pressure": signal["pressure"],
            "signal": signal["signal"],
            "status": "OPEN",
            "created_at": utc_now(),
        }

        telegram_send(
            "🚨 NEW ATI BUY SIGNAL\n\n"
            + signal_text(signal)
        )

        # ----------------------------------------------------
        # REAL TRADING
        # ----------------------------------------------------

        if (
            REAL_ORDERS
            and real_buy_done
            < MAX_REAL_BUYS_PER_RUN
            and signal["signal"]
            in (
                "CONFIRMED BUY",
                "EARLY BUY",
            )
        ):

            try:

                result = execute_real_trade(
                    signal["market"],
                    signal,
                )

                if result.get("ok"):

                    real_buy_done += 1

                    history[
                        "real_trades"
                    ][sid] = {
                        "symbol": signal[
                            "symbol"
                        ],
                        "buy_order_id":
                            result[
                                "buy_order"
                            ].get(
                                "orderId"
                            ),
                        "oco_order_list_id":
                            result[
                                "oco"
                            ].get(
                                "orderListId"
                            ),
                        "quantity":
                            result[
                                "quantity"
                            ],
                        "entry":
                            result[
                                "entry"
                            ],
                        "tp1":
                            result[
                                "tp1"
                            ],
                        "tp2":
                            result[
                                "tp2"
                            ],
                        "sl":
                            result[
                                "sl"
                            ],
                        "created_at":
                            utc_now(),
                    }

                else:

                    telegram_send(
                        f"⚠️ REAL ORDER FAILED\n\n"
                        f"🪙 {signal['symbol']}\n"
                        f"STATUS: "
                        f"{result.get('status', '-')}"
                    )

            except Exception as e:

                telegram_send(
                    f"🚨 REAL TRADE ERROR\n\n"
                    f"🪙 {signal['symbol']}\n"
                    f"❌ {str(e)[:900]}"
                )

            # Never place a second real BUY in same run.
            break

    save_history(history)

    # --------------------------------------------------------
    # Final heartbeat
    # --------------------------------------------------------

    stats = summary(history)

    heartbeat(
        "✅ SCAN FINISHED\n"
        f"📊 MARKETS: {len(markets)}\n"
        f"📥 VALID: {valid}\n"
        f"🟢 CANDIDATES: {len(candidates)}\n"
        f"🚨 REAL BUY THIS RUN: {real_buy_done}\n"
        f"📌 TOTAL BUY: {stats['total']}\n"
        f"⏳ OPEN: {stats['open']}\n"
        f"🕐 NEXT RUN: ABOUT 5 MINUTES"
    )


# ============================================================
# GLOBAL ERROR HANDLER
# ============================================================

if __name__ == "__main__":

    try:
        main()

    except Exception as e:

        error_text = (
            f"🚨 ATI BOT GLOBAL ERROR\n\n"
            f"VERSION: {VERSION}\n"
            f"ERROR:\n"
            f"{str(e)[:2500]}\n\n"
            f"🕐 {utc_now()}"
        )

        telegram_send(
            error_text
        )

        raise
