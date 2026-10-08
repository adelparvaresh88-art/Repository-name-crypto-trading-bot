import os
import json
import time
import math
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# =========================================================
# ATI FUTURES V9.1 REAL
#
# NO tabdeal package
# NO fake klines endpoint
# NO aggTrades endpoint
#
# Market:
#   /r/fapi/v1/exchangeInfo
#   /r/fapi/v1/depth
#
# Trading:
#   /fapi/v1/order
#   /fapi/v1/leverage
#   /r/fapi/v1/position
#
# Strategy:
#   5M candles built from persistent MID prices
#   Ichimoku 9 / 26 / 52
#
# REAL ORDERS: ON
# MAX ONE NEW ORDER PER CYCLE
# MAX ONE ACTIVE POSITION
# =========================================================

BASE = "https://api1.tabdeal.org"

API_KEY = os.getenv("TABDEAL_API_KEY", "")
API_SECRET = os.getenv("TABDEAL_API_SECRET", "")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

REAL_TRADING = (
    os.getenv("REAL_TRADING", "true").lower() == "true"
)

SCAN_UNIVERSE = int(os.getenv("SCAN_UNIVERSE", "75"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "20"))

ORDER_USDT = float(os.getenv("ORDER_USDT", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

MIN_SCORE = int(os.getenv("MIN_SCORE", "6"))

TP_PCT = float(os.getenv("TP_PCT", "0.02"))
SL_PCT = float(os.getenv("SL_PCT", "0.01"))

RECV_WINDOW = int(os.getenv("RECV_WINDOW", "5000"))

STATE_FILE = "ati_futures_state.json"

TIMEOUT = 10

CANDLE_MS = 5 * 60 * 1000

TENKAN = 9
KIJUN = 26
SENKOU_B = 52

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-FUTURES-V9.1",
    "Accept": "application/json",
})


# =========================================================
# TELEGRAM
# =========================================================

def telegram(text):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        r = session.post(
            f"https://api.telegram.org/"
            f"bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
            },
            timeout=10,
        )

        return r.ok

    except Exception as e:
        print("Telegram:", e)
        return False


# =========================================================
# PUBLIC API
# =========================================================

def public_get(path, params=None):

    r = session.get(
        BASE + path,
        params=params or {},
        timeout=TIMEOUT,
    )

    if r.status_code != 200:
        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:200]}"
        )

    data = r.json()

    if isinstance(data, dict):
        code = data.get("code")

        if code not in (None, 0):
            raise RuntimeError(
                f"API {code}: "
                f"{data.get('msg', '')}"
            )

    return data


# =========================================================
# SIGNED FUTURES API
# =========================================================

def signed_request(
    method,
    path,
    params=None,
):

    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDEAL_API_KEY / "
            "TABDEAL_API_SECRET missing"
        )

    data = dict(params or {})

    data["timestamp"] = int(
        time.time() * 1000
    )

    data["recvWindow"] = RECV_WINDOW

    query = urlencode(data)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    data["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "User-Agent": "ATI-FUTURES-V9.1",
    }

    if method == "GET":

        r = session.get(
            BASE + path,
            params=data,
            headers=headers,
            timeout=TIMEOUT,
        )

    elif method == "POST":

        r = session.post(
            BASE + path,
            data=data,
            headers=headers,
            timeout=TIMEOUT,
        )

    elif method == "DELETE":

        r = session.delete(
            BASE + path,
            params=data,
            headers=headers,
            timeout=TIMEOUT,
        )

    else:
        raise RuntimeError(
            f"Unsupported method: {method}"
        )

    if r.status_code >= 400:

        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:500]}"
        )

    try:
        return r.json()
    except Exception:
        return {
            "raw": r.text
        }


# =========================================================
# EXCHANGE INFO
# =========================================================

def get_markets():

    data = public_get(
        "/r/fapi/v1/exchangeInfo"
    )

    symbols = data.get(
        "symbols",
        []
    )

    result = []

    for item in symbols:

        symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).upper()

        status = str(
            item.get(
                "status",
                ""
            )
        ).upper()

        quote = str(
            item.get(
                "quoteAsset",
                ""
            )
        ).upper()

        if not symbol:
            continue

        if status not in (
            "TRADING",
            "ENABLED",
        ):
            continue

        if quote != "USDT":
            continue

        result.append(item)

    return result[:SCAN_UNIVERSE]


# =========================================================
# DEPTH
# =========================================================

def get_price(symbol):

    data = public_get(
        "/r/fapi/v1/depth",
        {
            "symbol": symbol,
            "limit": 5,
        },
    )

    bids = data.get(
        "bids",
        []
    )

    asks = data.get(
        "asks",
        []
    )

    if not bids or not asks:
        raise RuntimeError(
            "Empty order book"
        )

    bid = float(bids[0][0])
    ask = float(asks[0][0])

    if bid <= 0 or ask <= 0:
        raise RuntimeError(
            "Invalid bid/ask"
        )

    return {
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2.0,
    }


# =========================================================
# STATE
# =========================================================

def load_state():

    if not os.path.exists(
        STATE_FILE
    ):

        return {
            "candles": {},
            "last_order": None,
            "last_signal": {},
        }

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            state = json.load(f)

        state.setdefault(
            "candles",
            {}
        )

        state.setdefault(
            "last_order",
            None
        )

        state.setdefault(
            "last_signal",
            {}
        )

        return state

    except Exception as e:

        print(
            "State reset:",
            e
        )

        return {
            "candles": {},
            "last_order": None,
            "last_signal": {},
        }


def save_state(state):

    temp = STATE_FILE + ".tmp"

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    os.replace(
        temp,
        STATE_FILE
    )


# =========================================================
# 5M CANDLE FROM MID PRICE
# =========================================================

def add_price_to_candle(
    state,
    symbol,
    price,
    timestamp_ms,
):

    bucket = (
        timestamp_ms // CANDLE_MS
    ) * CANDLE_MS

    candles = state[
        "candles"
    ].setdefault(
        symbol,
        []
    )

    # Existing bucket
    for candle in candles:

        if candle["time"] == bucket:

            candle["high"] = max(
                candle["high"],
                price
            )

            candle["low"] = min(
                candle["low"],
                price
            )

            candle["close"] = price

            return candle

    # New bucket
    candle = {
        "time": bucket,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": 0.0,
    }

    candles.append(
        candle
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    # Keep 120 candles
    state[
        "candles"
    ][symbol] = candles[-120:]

    return candle


# =========================================================
# ICHIMOKU
# =========================================================

def midpoint(
    candles,
    index,
    period
):

    start = (
        index - period + 1
    )

    if start < 0:
        return None

    section = candles[
        start:index + 1
    ]

    highs = [
        float(x["high"])
        for x in section
    ]

    lows = [
        float(x["low"])
        for x in section
    ]

    return (
        max(highs)
        + min(lows)
    ) / 2.0


def get_ichimoku(candles):

    if len(candles) < SENKOU_B:
        return None

    i = len(candles) - 1

    tenkan = midpoint(
        candles,
        i,
        TENKAN
    )

    kijun = midpoint(
        candles,
        i,
        KIJUN
    )

    span_b = midpoint(
        candles,
        i,
        SENKOU_B
    )

    if (
        tenkan is None
        or kijun is None
        or span_b is None
    ):
        return None

    span_a = (
        tenkan + kijun
    ) / 2.0

    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "span_a": span_a,
        "span_b": span_b,
    }


# =========================================================
# SIGNAL
# =========================================================

def analyze(
    symbol,
    candles
):

    if len(candles) < 53:
        return None

    candles = sorted(
        candles,
        key=lambda x: x["time"]
    )

    current = get_ichimoku(
        candles
    )

    previous = get_ichimoku(
        candles[:-1]
    )

    if not current or not previous:
        return None

    last = candles[-1]
    prev = candles[-2]

    close = float(
        last["close"]
    )

    prev_close = float(
        prev["close"]
    )

    cloud_top = max(
        current["span_a"],
        current["span_b"]
    )

    cloud_bottom = min(
        current["span_a"],
        current["span_b"]
    )

    buy = 0
    sell = 0

    buy_reasons = []
    sell_reasons = []

    # BUY
    if close > cloud_top:
        buy += 2
        buy_reasons.append(
            "PRICE_ABOVE_CLOUD"
        )

    if current["tenkan"] > current["kijun"]:
        buy += 2
        buy_reasons.append(
            "TENKAN_GT_KIJUN"
        )

    if current["span_a"] > current["span_b"]:
        buy += 1
        buy_reasons.append(
            "BULLISH_CLOUD"
        )

    if close > prev_close:
        buy += 1
        buy_reasons.append(
            "MOMENTUM_UP"
        )

    if current["kijun"] > previous["kijun"]:
        buy += 1
        buy_reasons.append(
            "KIJUN_RISING"
        )

    # SELL
    if close < cloud_bottom:
        sell += 2
        sell_reasons.append(
            "PRICE_BELOW_CLOUD"
        )

    if current["tenkan"] < current["kijun"]:
        sell += 2
        sell_reasons.append(
            "TENKAN_LT_KIJUN"
        )

    if current["span_a"] < current["span_b"]:
        sell += 1
        sell_reasons.append(
            "BEARISH_CLOUD"
        )

    if close < prev_close:
        sell += 1
        sell_reasons.append(
            "MOMENTUM_DOWN"
        )

    if current["kijun"] < previous["kijun"]:
        sell += 1
        sell_reasons.append(
            "KIJUN_FALLING"
        )

    if (
        buy >= MIN_SCORE
        and buy > sell
    ):

        return {
            "symbol": symbol,
            "signal": "BUY",
            "score": buy,
            "price": close,
            "reasons": buy_reasons,
        }

    if (
        sell >= MIN_SCORE
        and sell > buy
    ):

        return {
            "symbol": symbol,
            "signal": "SELL",
            "score": sell,
            "price": close,
            "reasons": sell_reasons,
        }

    return None


# =========================================================
# POSITION
# =========================================================

def get_positions():

    return signed_request(
        "GET",
        "/r/fapi/v1/position",
        {
            "isActive": 1,
        },
    )


def has_active_position():

    data = get_positions()

    if isinstance(data, dict):

        positions = data.get(
            "positions",
            [data]
        )

    else:

        positions = data

    for p in positions or []:

        try:

            qty = float(
                p.get(
                    "positionAmt",
                    p.get(
                        "quantity",
                        0
                    )
                )
            )

            if abs(qty) > 0:
                return True

        except Exception:
            pass

    return False


# =========================================================
# MARKET RULES
# =========================================================

def get_rules(market):

    filters = market.get(
        "filters",
        []
    )

    result = {
        "step": 0.0,
        "min_qty": 0.0,
        "max_qty": 0.0,
    }

    for f in filters:

        typ = str(
            f.get(
                "filterType",
                ""
            )
        )

        if typ in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE",
        ):

            result["step"] = float(
                f.get(
                    "stepSize",
                    0
                )
            )

            result["min_qty"] = float(
                f.get(
                    "minQty",
                    0
                )
            )

            result["max_qty"] = float(
                f.get(
                    "maxQty",
                    0
                )
            )

            break

    return result


def floor_step(
    value,
    step
):

    if step <= 0:
        return value

    return (
        math.floor(
            value / step
        ) * step
    )


def calculate_quantity(
    market,
    price
):

    rules = get_rules(
        market
    )

    # ORDER_USDT = margin
    # leverage = notional multiplier
    notional = (
        ORDER_USDT
        * LEVERAGE
    )

    raw = (
        notional / price
    )

    qty = floor_step(
        raw,
        rules["step"]
    )

    if (
        rules["min_qty"] > 0
        and qty < rules["min_qty"]
    ):
        qty = rules["min_qty"]

    if (
        rules["max_qty"] > 0
        and qty > rules["max_qty"]
    ):
        qty = rules["max_qty"]

    if qty <= 0:
        raise RuntimeError(
            "Invalid order quantity"
        )

    return (
        f"{qty:.12f}"
        .rstrip("0")
        .rstrip(".")
    )


# =========================================================
# LEVERAGE
# =========================================================

def set_leverage(symbol):

    return signed_request(
        "POST",
        "/fapi/v1/leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE,
        },
    )


# =========================================================
# REAL MARKET ORDER
# =========================================================

def real_order(
    market,
    signal
):

    symbol = signal["symbol"]

    price = float(
        signal["price"]
    )

    set_leverage(
        symbol
    )

    quantity = calculate_quantity(
        market,
        price
    )

    side = (
        "BUY"
        if signal["signal"] == "BUY"
        else "SELL"
    )

    result = signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
            "reduceOnly": "false",
        },
    )

    return {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "response": result,
    }


# =========================================================
# SL / TP
# =========================================================

def set_sl_tp(
    signal
):

    symbol = signal["symbol"]

    position = signed_request(
        "GET",
        "/r/fapi/v1/position",
        {
            "symbol": symbol,
            "isActive": 1,
        },
    )

    if isinstance(
        position,
        dict
    ):

        positions = position.get(
            "positions",
            [position]
        )

    else:

        positions = position

    position_id = None

    for p in positions or []:

        try:

            qty = float(
                p.get(
                    "positionAmt",
                    p.get(
                        "quantity",
                        0
                    )
                )
            )

            if abs(qty) > 0:

                position_id = (
                    p.get(
                        "positionId"
                    )
                )

                break

        except Exception:
            pass

    if position_id is None:
        return None

    entry = float(
        signal["price"]
    )

    if signal["signal"] == "BUY":

        sl = entry * (
            1 - SL_PCT
        )

        tp = entry * (
            1 + TP_PCT
        )

    else:

        sl = entry * (
            1 + SL_PCT
        )

        tp = entry * (
            1 - TP_PCT
        )

    result = signed_request(
        "POST",
        "/fapi/v1/positionSlTp",
        {
            "positionId": position_id,
            "symbol": symbol,
            "slPrice": str(sl),
            "tpPrice": str(tp),
        },
    )

    return {
        "sl": sl,
        "tp": tp,
        "response": result,
    }


# =========================================================
# ONE SYMBOL
# =========================================================

def scan_symbol(
    market,
    state
):

    symbol = market["symbol"]

    try:

        price_data = get_price(
            symbol
        )

        now = int(
            time.time() * 1000
        )

        candle = add_price_to_candle(
            state,
            symbol,
            price_data["mid"],
            now,
        )

        candles = state[
            "candles"
        ][symbol]

        signal = analyze(
            symbol,
            candles
        )

        return {
            "ok": True,
            "symbol": symbol,
            "price": price_data["mid"],
            "candle": candle,
            "count": len(candles),
            "signal": signal,
            "error": None,
        }

    except Exception as e:

        return {
            "ok": False,
            "symbol": symbol,
            "price": None,
            "candle": None,
            "count": 0,
            "signal": None,
            "error": str(e)[:180],
        }


# =========================================================
# MAIN
# =========================================================

def main():

    start = time.time()

    print(
        "💓 ATI FUTURES V9.1 REAL"
    )

    print(
        "⚡ DEPTH → PERSISTENT 5M"
    )

    print(
        "☁️ ICHIMOKU 9 / 26 / 52"
    )

    print(
        f"🔒 REAL TRADING: "
        f"{REAL_TRADING}"
    )

    if REAL_TRADING:

        if not API_KEY or not API_SECRET:

            text = (
                "❌ ATI FUTURES V9.1\n\n"
                "REAL_TRADING=true\n"
                "ولی API credentials وجود ندارد."
            )

            print(text)
            telegram(text)
            return

    # -----------------------------------------------------
    # Markets
    # -----------------------------------------------------

    try:

        markets = get_markets()

    except Exception as e:

        text = (
            "❌ ATI FUTURES ERROR\n\n"
            f"ExchangeInfo:\n{e}"
        )

        print(text)
        telegram(text)
        return

    # -----------------------------------------------------
    # State
    # -----------------------------------------------------

    state = load_state()

    # -----------------------------------------------------
    # Scan
    # -----------------------------------------------------

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                scan_symbol,
                market,
                state
            )
            for market in markets
        ]

        for f in as_completed(
            futures
        ):

            results.append(
                f.result()
            )

    ok = sum(
        1
        for r in results
        if r["ok"]
    )

    errors = (
        len(results) - ok
    )

    ready = [
        r
        for r in results
        if r["ok"]
        and r["count"] >= 53
    ]

    signals = []

    for r in ready:

        if r["signal"]:
            signals.append(
                r["signal"]
            )

    signals.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    # Save before trading
    save_state(
        state
    )

    # -----------------------------------------------------
    # REAL TRADING
    # -----------------------------------------------------

    order_result = None
    sltp_result = None

    if REAL_TRADING and signals:

        try:

            if has_active_position():

                print(
                    "🔒 ACTIVE POSITION"
                )

            else:

                selected = signals[0]

                market = next(
                    (
                        m
                        for m in markets
                        if m["symbol"]
                        == selected["symbol"]
                    ),
                    None
                )

                if market:

                    order_result = real_order(
                        market,
                        selected
                    )

                    sltp_result = set_sl_tp(
                        selected
                    )

                    state[
                        "last_order"
                    ] = {
                        "time": int(
                            time.time()
                        ),
                        "signal": selected,
                        "order": order_result,
                        "sltp": sltp_result,
                    }

                    state[
                        "last_signal"
                    ][
                        selected["symbol"]
                    ] = selected

                    save_state(
                        state
                    )

        except Exception as e:

            order_result = {
                "error": str(e)
            }

            print(
                "REAL ORDER ERROR:",
                e
            )

    elapsed = (
        time.time()
        - start
    )

    # -----------------------------------------------------
    # REPORT
    # -----------------------------------------------------

    text = (
        "💓 ATI FUTURES V9.1 REAL\n\n"
        "⚡ DEPTH → PERSISTENT 5M\n"
        "☁️ ICHIMOKU 9 / 26 / 52\n\n"
        f"📊 Markets: {len(markets)}\n"
        f"📈 5M OK: {ok}\n"
        f"🧠 Ichimoku Ready: "
        f"{len(ready)}\n"
        f"🔥 Signals: {len(signals)}\n"
        f"❌ Errors: {errors}\n"
        f"⏱️ Scan: {elapsed:.2f}s\n\n"
    )

    if signals:

        text += (
            "🔥 TOP SIGNALS\n\n"
        )

        for s in signals[:5]:

            emoji = (
                "🟢"
                if s["signal"] == "BUY"
                else "🔴"
            )

            text += (
                f"{emoji} "
                f"{s['signal']} "
                f"{s['symbol']}\n"
                f"💰 {s['price']:.10g}\n"
                f"⭐ Score: {s['score']}\n"
                f"📋 "
                f"{', '.join(s['reasons'])}\n\n"
            )

    else:

        text += (
            "☁️ NO SIGNAL THIS CYCLE\n\n"
        )

    if order_result:

        if "error" in order_result:

            text += (
                "❌ REAL ORDER FAILED\n"
                f"{order_result['error']}\n\n"
            )

        else:

            text += (
                "🚨 REAL ORDER EXECUTED\n\n"
                f"💎 "
                f"{order_result['symbol']}\n"
                f"📌 "
                f"{order_result['side']}\n"
                f"📦 Qty: "
                f"{order_result['quantity']}\n"
            )

            if sltp_result:

                text += (
                    f"🛑 SL: "
                    f"{sltp_result['sl']:.10g}\n"
                    f"🎯 TP: "
                    f"{sltp_result['tp']:.10g}\n"
                )

            text += "\n"

    text += (
        f"🔒 REAL TRADING: "
        f"{REAL_TRADING}\n"
        "🕐 "
        + datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    print(text)
    telegram(text)


if __name__ == "__main__":
    main()
