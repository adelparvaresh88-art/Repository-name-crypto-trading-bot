import os
import json
import time
import math
import hmac
import hashlib
import threading
from datetime import datetime, timezone

import requests
import websocket


# ============================================================
# ATI FUTURES V1
# TABDEAL FUTURES
#
# STRATEGY:
# MACD 12 / 26 / 9
# TIMEFRAME: 5 MINUTES
#
# REAL TRADING:
# Controlled ONLY by GitHub Secret REAL_TRADING
#
# IMPORTANT:
# Symbol is always taken from Tabdeal exchangeInfo and carried
# through the entire trade flow into Telegram.
# ============================================================

VERSION = "ATI FUTURES V1"

BASE_URL = "https://api1.tabdeal.org"
WS_URL = "wss://api1.tabdeal.org/special_margin/stream/"

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

REAL_TRADING = os.getenv("REAL_TRADING", "false").strip().lower() == "true"

LEVERAGE = int(os.getenv("LEVERAGE", "3"))
MARGIN_USDT = float(os.getenv("MARGIN_USDT", "2"))

TIMEFRAME_SECONDS = 300

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

TP_PCT = float(os.getenv("TP_PCT", "0.02"))
SL_PCT = float(os.getenv("SL_PCT", "0.01"))

MAX_SYMBOLS = int(os.getenv("MAX_SYMBOLS", "30"))

REQUEST_TIMEOUT = 15

STATE_FILE = "ati_futures_state.json"


# ============================================================
# GLOBAL STATE
# ============================================================

state_lock = threading.Lock()

STATE = {
    "candles": {},
    "last_signal": {},
    "positions": {},
    "last_heartbeat": 0,
}


# ============================================================
# GENERAL
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def log(message):
    print(f"[{now_utc()}] {message}", flush=True)


def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(STATE, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"STATE SAVE ERROR: {e}")


def load_state():
    global STATE

    try:
        if not os.path.exists(STATE_FILE):
            return

        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            STATE.update(data)

        log("State loaded.")

    except Exception as e:
        log(f"STATE LOAD ERROR: {e}")


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram credentials missing.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            return True

        log(f"Telegram error {response.status_code}: {response.text}")
        return False

    except Exception as e:
        log(f"Telegram exception: {e}")
        return False


# ============================================================
# SIGNING
# ============================================================

def sign_params(params):
    query = "&".join(
        f"{key}={params[key]}"
        for key in sorted(params)
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()

    params["signature"] = signature
    return params


def private_request(method, endpoint, params=None):
    if not API_KEY or not API_SECRET:
        raise RuntimeError("Tabdeal API credentials are missing.")

    if params is None:
        params = {}

    params = dict(params)

    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 10000

    signed = sign_params(params)

    headers = {
        "X-MBX-APIKEY": API_KEY,
    }

    url = f"{BASE_URL}/fapi/{endpoint}"

    if method.upper() == "GET":
        response = requests.get(
            url,
            params=signed,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    elif method.upper() == "POST":
        response = requests.post(
            url,
            data=signed,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    elif method.upper() == "DELETE":
        response = requests.delete(
            url,
            params=signed,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    else:
        raise ValueError(f"Unsupported method: {method}")

    if not response.ok:
        raise RuntimeError(
            f"HTTP {response.status_code}: {response.text}"
        )

    try:
        return response.json()
    except Exception:
        return response.text


# ============================================================
# PUBLIC API
# ============================================================

def public_get(endpoint, params=None):
    url = f"{BASE_URL}/r/fapi/{endpoint}"

    response = requests.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    if not response.ok:
        raise RuntimeError(
            f"HTTP {response.status_code}: {response.text}"
        )

    return response.json()


# ============================================================
# TABDEAL MARKETS
# ============================================================

def get_markets():

    data = public_get("v1/exchangeInfo")

    symbols = data.get("symbols", [])

    result = []

    for item in symbols:

        symbol = str(item.get("symbol", "")).upper()
        status = str(item.get("status", "")).upper()
        quote = str(
            item.get("quoteAsset", "")
            or item.get("quoteCurrency", "")
        ).upper()

        if not symbol:
            continue

        if status and status != "TRADING":
            continue

        if quote and quote != "USDT":
            continue

        if not symbol.endswith("USDT"):
            continue

        result.append(item)

    result = result[:MAX_SYMBOLS]

    log(f"Markets discovered: {len(result)}")

    return result


# ============================================================
# SYMBOL FILTER
# ============================================================

def symbol_info(item):

    symbol = str(item.get("symbol", "")).upper()

    filters = {}

    for f in item.get("filters", []):
        ftype = f.get("filterType")

        if ftype:
            filters[ftype] = f

    return symbol, filters


def normalize_quantity(symbol_item, quantity):

    symbol, filters = symbol_info(symbol_item)

    step = None
    minimum = None

    lot = filters.get("LOT_SIZE")

    if lot:
        step = float(
            lot.get("stepSize")
            or lot.get("step")
            or 0
        )

        minimum = float(
            lot.get("minQty")
            or 0
        )

    if not step or step <= 0:
        return str(quantity)

    quantity = math.floor(quantity / step) * step

    if minimum and quantity < minimum:
        quantity = minimum

    decimals = max(
        0,
        int(round(-math.log10(step)))
    )

    return f"{quantity:.{decimals}f}"


# ============================================================
# PRICE
# ============================================================

def get_mid_price(symbol):

    data = public_get(
        "v1/depth",
        {
            "symbol": symbol,
            "limit": 5,
        },
    )

    bids = data.get("bids") or []
    asks = data.get("asks") or []

    if not bids or not asks:
        return None

    bid = float(bids[0][0])
    ask = float(asks[0][0])

    if bid <= 0 or ask <= 0:
        return None

    return (bid + ask) / 2.0


# ============================================================
# CANDLE BUILDER
# ============================================================

def candle_bucket(timestamp_ms):

    return (
        int(timestamp_ms / 1000)
        // TIMEFRAME_SECONDS
    ) * TIMEFRAME_SECONDS


def add_price(symbol, price, timestamp_ms):

    bucket = candle_bucket(timestamp_ms)

    with state_lock:

        candles = STATE["candles"].setdefault(
            symbol,
            []
        )

        if candles and candles[-1]["time"] == bucket:

            c = candles[-1]

            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["close"] = price

        else:

            candles.append(
                {
                    "time": bucket,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                }
            )

            # Keep enough candles for MACD.
            if len(candles) > 200:
                del candles[:-200]


# ============================================================
# MACD
# ============================================================

def ema(values, period):

    if len(values) < period:
        return []

    multiplier = 2.0 / (period + 1)

    result = []

    seed = sum(values[:period]) / period

    result.append(seed)

    previous = seed

    for value in values[period:]:

        current = (
            (value - previous) * multiplier
            + previous
        )

        result.append(current)
        previous = current

    return result


def macd_signal(closes):

    if len(closes) < MACD_SLOW + MACD_SIGNAL + 5:
        return None

    fast = ema(closes, MACD_FAST)
    slow = ema(closes, MACD_SLOW)

    if not fast or not slow:
        return None

    # Align EMA arrays to the slow EMA timeline.
    offset = MACD_SLOW - MACD_FAST

    if len(fast) <= offset:
        return None

    fast_aligned = fast[offset:]

    count = min(
        len(fast_aligned),
        len(slow)
    )

    macd_line = []

    for i in range(count):
        macd_line.append(
            fast_aligned[i] - slow[i]
        )

    if len(macd_line) < MACD_SIGNAL + 2:
        return None

    signal_line = ema(
        macd_line,
        MACD_SIGNAL
    )

    if len(signal_line) < 2:
        return None

    # Current closed candle
    current_macd = macd_line[-1]
    previous_macd = macd_line[-2]

    current_signal = signal_line[-1]

    # Align previous signal approximately.
    previous_signal = signal_line[-2]

    if (
        previous_macd <= previous_signal
        and current_macd > current_signal
    ):
        return "BUY"

    if (
        previous_macd >= previous_signal
        and current_macd < current_signal
    ):
        return "SELL"

    return None


# ============================================================
# POSITION
# ============================================================

def get_position(symbol):

    try:

        data = private_request(
            "GET",
            "v1/position",
            {
                "symbol": symbol,
            },
        )

        if isinstance(data, list):

            for p in data:

                qty = float(
                    p.get("positionAmt")
                    or p.get("quantity")
                    or p.get("qty")
                    or 0
                )

                if abs(qty) > 0:
                    return p

        elif isinstance(data, dict):

            qty = float(
                data.get("positionAmt")
                or data.get("quantity")
                or data.get("qty")
                or 0
            )

            if abs(qty) > 0:
                return data

        return None

    except Exception as e:

        log(
            f"POSITION ERROR {symbol}: {e}"
        )

        return None


# ============================================================
# LEVERAGE
# ============================================================

def set_leverage(symbol):

    try:

        result = private_request(
            "POST",
            "v1/leverage",
            {
                "symbol": symbol,
                "leverage": LEVERAGE,
            },
        )

        log(
            f"Leverage {symbol}: {LEVERAGE}x"
        )

        return result

    except Exception as e:

        log(
            f"LEVERAGE ERROR {symbol}: {e}"
        )

        return None


# ============================================================
# ORDER
# ============================================================

def calculate_quantity(symbol_item, price):

    if price <= 0:
        return None

    # Margin * leverage = approximate notional.
    notional = MARGIN_USDT * LEVERAGE

    quantity = notional / price

    return normalize_quantity(
        symbol_item,
        quantity,
    )


def send_market_order(symbol, side, quantity):

    result = private_request(
        "POST",
        "v1/order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        },
    )

    return result


# ============================================================
# REAL TRADE
# ============================================================

def execute_trade(symbol_item, signal, price):

    symbol = str(
        symbol_item.get("symbol", "")
    ).upper()

    if not symbol:
        return

    if signal not in ("BUY", "SELL"):
        return

    position = get_position(symbol)

    if position:
        log(
            f"{symbol}: existing position -> skip"
        )
        return

    set_leverage(symbol)

    quantity = calculate_quantity(
        symbol_item,
        price,
    )

    if not quantity:
        log(
            f"{symbol}: invalid quantity"
        )
        return

    side = "BUY" if signal == "BUY" else "SELL"

    log(
        f"SIGNAL {signal} | "
        f"SYMBOL {symbol} | "
        f"PRICE {price} | "
        f"QTY {quantity} | "
        f"REAL={REAL_TRADING}"
    )

    if not REAL_TRADING:

        telegram(
            "🟡 ATI PAPER SIGNAL\n\n"
            f"Symbol: {symbol}\n"
            f"Side: {signal}\n"
            f"Price: {price}\n"
            f"Quantity: {quantity}\n"
            f"Leverage: {LEVERAGE}x\n"
            f"MACD: {MACD_FAST}/{MACD_SLOW}/{MACD_SIGNAL}\n"
            f"Mode: PAPER"
        )

        return

    try:

        order = send_market_order(
            symbol,
            side,
            quantity,
        )

        order_id = (
            order.get("orderId")
            if isinstance(order, dict)
            else None
        )

        fill_price = (
            order.get("avgPrice")
            or order.get("price")
            or price
            if isinstance(order, dict)
            else price
        )

        log(
            f"REAL ORDER SUCCESS | "
            f"{symbol} | {side} | "
            f"orderId={order_id}"
        )

        # Store exact symbol.
        STATE["positions"][symbol] = {
            "symbol": symbol,
            "side": signal,
            "entry": float(fill_price),
            "quantity": quantity,
            "order_id": order_id,
            "time": now_utc(),
        }

        save_state()

        telegram(
            "🔴 ATI REAL TRADE\n\n"
            f"Symbol: {symbol}\n"
            f"Side: {signal}\n"
            f"Entry: {fill_price}\n"
            f"Quantity: {quantity}\n"
            f"Leverage: {LEVERAGE}x\n"
            f"Margin: {MARGIN_USDT} USDT\n"
            f"Order ID: {order_id}\n"
            f"TP: {TP_PCT * 100:.2f}%\n"
            f"SL: {SL_PCT * 100:.2f}%\n"
            f"Mode: REAL"
        )

    except Exception as e:

        log(
            f"REAL ORDER ERROR {symbol}: {e}"
        )

        telegram(
            "🚨 ATI REAL ORDER ERROR\n\n"
            f"Symbol: {symbol}\n"
            f"Side: {signal}\n"
            f"Error: {e}"
        )


# ============================================================
# CANDLE ANALYSIS
# ============================================================

def analyze_symbol(symbol_item):

    symbol = str(
        symbol_item.get("symbol", "")
    ).upper()

    if not symbol:
        return

    with state_lock:

        candles = list(
            STATE["candles"].get(symbol, [])
        )

    # Need enough closed candles.
    if len(candles) < 40:
        return

    # Last candle may still be forming.
    current_bucket = candle_bucket(
        int(time.time() * 1000)
    )

    closed = [
        c for c in candles
        if c["time"] < current_bucket
    ]

    if len(closed) < 40:
        return

    closes = [
        float(c["close"])
        for c in closed
    ]

    signal = macd_signal(closes)

    if not signal:
        return

    signal_key = (
        symbol,
        closed[-1]["time"],
        signal,
    )

    last_signal = STATE["last_signal"].get(
        symbol
    )

    if last_signal == str(signal_key):
        return

    STATE["last_signal"][symbol] = str(
        signal_key
    )

    save_state()

    price = closes[-1]

    execute_trade(
        symbol_item,
        signal,
        price,
    )


# ============================================================
# MARKET PRICE LOOP
# ============================================================

def price_loop(markets):

    log(
        f"Price loop started for "
        f"{len(markets)} symbols."
    )

    while True:

        for item in markets:

            symbol = str(
                item.get("symbol", "")
            ).upper()

            if not symbol:
                continue

            try:

                price = get_mid_price(symbol)

                if price:

                    add_price(
                        symbol,
                        price,
                        int(time.time() * 1000),
                    )

                    analyze_symbol(item)

            except Exception as e:

                log(
                    f"{symbol} ERROR: {e}"
                )

            time.sleep(0.5)

        save_state()

        time.sleep(2)


# ============================================================
# HEARTBEAT
# ============================================================

def heartbeat_loop(markets):

    while True:

        try:

            total_candles = 0

            with state_lock:

                for symbol in STATE["candles"]:
                    total_candles += len(
                        STATE["candles"][symbol]
                    )

            mode = (
                "🔴 REAL TRADING"
                if REAL_TRADING
                else "🟡 PAPER"
            )

            telegram(
                "🤖 ATI FUTURES HEARTBEAT\n\n"
                f"Version: {VERSION}\n"
                f"Mode: {mode}\n"
                f"Markets: {len(markets)}\n"
                f"Candles: {total_candles}\n"
                f"MACD: 12/26/9\n"
                f"Timeframe: 5m\n"
                f"Leverage: {LEVERAGE}x\n"
                f"Margin: {MARGIN_USDT} USDT"
            )

        except Exception as e:

            log(
                f"Heartbeat error: {e}"
            )

        time.sleep(300)


# ============================================================
# STARTUP
# ============================================================

def startup_check():

    log("=" * 60)
    log(VERSION)
    log("=" * 60)

    log(
        f"REAL_TRADING = {REAL_TRADING}"
    )

    log(
        f"MACD = "
        f"{MACD_FAST}/{MACD_SLOW}/{MACD_SIGNAL}"
    )

    log(
        f"TIMEFRAME = 5m"
    )

    log(
        f"LEVERAGE = {LEVERAGE}x"
    )

    log(
        f"MARGIN = {MARGIN_USDT} USDT"
    )

    if not API_KEY or not API_SECRET:

        raise RuntimeError(
            "TABDEAL_API_KEY / "
            "TABDEAL_API_SECRET missing."
        )

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:

        raise RuntimeError(
            "Telegram credentials missing."
        )

    # Test exchange info.
    markets = get_markets()

    if not markets:

        raise RuntimeError(
            "No USDT Futures markets found."
        )

    log(
        f"API OK | {len(markets)} markets"
    )

    return markets


# ============================================================
# MAIN
# ============================================================

def main():

    load_state()

    markets = startup_check()

    telegram(
        "🚀 ATI FUTURES STARTED\n\n"
        f"Version: {VERSION}\n"
        f"Mode: "
        f"{'🔴 REAL' if REAL_TRADING else '🟡 PAPER'}\n"
        f"Markets: {len(markets)}\n"
        f"MACD: 12/26/9\n"
        f"Timeframe: 5m\n"
        f"Leverage: {LEVERAGE}x\n"
        f"Margin: {MARGIN_USDT} USDT"
    )

    t1 = threading.Thread(
        target=price_loop,
        args=(markets,),
        daemon=True,
    )

    t2 = threading.Thread(
        target=heartbeat_loop,
        args=(markets,),
        daemon=True,
    )

    t1.start()
    t2.start()

    while True:
        time.sleep(60)


if __name__ == "__main__":

    try:
        main()

    except Exception as e:

        log(
            f"FATAL ERROR: {e}"
        )

        telegram(
            "🚨 ATI FUTURES STOPPED\n\n"
            f"Error:\n{e}"
        )

        raise
