import os
import time
import json
import hmac
import hashlib
import requests
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone


# ============================================================
# ATI FUTURES V3.3
# TABDEAL FUTURES
#
# STRATEGY:
# MACD 12 / 26 / 9
# TIMEFRAME: 5m
#
# IMPORTANT:
# - NO /klines endpoint is used.
# - 5m candles are built from Futures trades.
# - REAL_TRADING is controlled by GitHub Secret.
# - NO REAL ORDER is sent until valid candles + MACD exist.
# ============================================================


VERSION = "ATI FUTURES V3.3"

BASE_URL = os.getenv(
    "TABDEAL_BASE_URL",
    "https://api1.tabdeal.org"
).rstrip("/")

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

REAL_TRADING = os.getenv(
    "REAL_TRADING",
    os.getenv("LIVE_TRADING", "false")
).lower() in ("1", "true", "yes", "on")

TIMEFRAME_MINUTES = 5

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

LEVERAGE = 3
MARGIN_USDT = Decimal("2.0")

MAX_MARKETS = 30
TRADES_LIMIT = 1000

STATE_FILE = "ati_futures_state.json"

REQUEST_TIMEOUT = 15

# ------------------------------------------------------------
# IMPORTANT:
# We deliberately do NOT use /klines.
# ------------------------------------------------------------

FUTURES_PREFIX = "/r/fapi/v1"


# ============================================================
# GLOBAL SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-FUTURES-V3.3"
})


# ============================================================
# LOGGING
# ============================================================

def log(message):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{now}] {message}", flush=True)


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

        r = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=REQUEST_TIMEOUT
        )

        return r.ok

    except Exception as e:
        log(f"Telegram error: {e}")
        return False


# ============================================================
# HTTP
# ============================================================

def get_public(path, params=None):

    url = BASE_URL + path

    try:

        r = session.get(
            url,
            params=params or {},
            timeout=REQUEST_TIMEOUT
        )

        if not r.ok:
            log(
                f"GET {path} -> HTTP {r.status_code} "
                f"{r.text[:300]}"
            )
            return None

        return r.json()

    except Exception as e:

        log(f"GET error {path}: {e}")
        return None


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(method, path, params=None):

    if not API_KEY or not API_SECRET:
        raise RuntimeError("API credentials missing")

    params = dict(params or {})

    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 10000

    query = "&".join(
        f"{k}={params[k]}"
        for k in sorted(params)
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    params["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = BASE_URL + path

    if method.upper() == "GET":

        r = session.get(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

    elif method.upper() == "POST":

        r = session.post(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

    elif method.upper() == "DELETE":

        r = session.delete(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

    else:
        raise RuntimeError("Unsupported HTTP method")

    if not r.ok:

        log(
            f"SIGNED {method} {path} -> "
            f"HTTP {r.status_code} {r.text[:500]}"
        )

        return None

    try:
        return r.json()
    except Exception:
        return r.text


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    data = get_public(
        f"{FUTURES_PREFIX}/exchangeInfo"
    )

    if not isinstance(data, dict):
        return None

    symbols = data.get("symbols")

    if not isinstance(symbols, list):
        return None

    return symbols


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def normalize_symbol(symbol):

    if not symbol:
        return ""

    return symbol.replace("_", "").upper()


# ============================================================
# GET FUTURES MARKETS
# ============================================================

def get_markets():

    symbols = get_exchange_info()

    if not symbols:
        log("No Futures exchangeInfo")
        return []

    markets = []

    for item in symbols:

        try:

            symbol = item.get("symbol", "")
            status = item.get("status", "")
            quote = item.get("quoteAsset", "")

            symbol_clean = normalize_symbol(symbol)

            if (
                status == "TRADING"
                and quote.upper() == "USDT"
                and symbol_clean.endswith("USDT")
            ):

                markets.append({
                    "symbol": symbol_clean,
                    "tabdeal_symbol": symbol,
                    "base": item.get("baseAsset", ""),
                    "quote": quote
                })

        except Exception:
            continue

    markets = markets[:MAX_MARKETS]

    log(f"Futures markets: {len(markets)}")

    return markets


# ============================================================
# FUTURES TRADES
#
# This replaces the broken /klines dependency.
# ============================================================

def get_trades(symbol):

    candidates = [
        f"{FUTURES_PREFIX}/trades",
        f"/fapi/v1/trades"
    ]

    params_list = [
        {
            "symbol": symbol,
            "limit": TRADES_LIMIT
        }
    ]

    for path in candidates:

        for params in params_list:

            data = get_public(
                path,
                params
            )

            if isinstance(data, list) and data:

                return data

    return []


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(trade):

    try:

        price = Decimal(
            str(
                trade.get(
                    "price",
                    trade.get("p")
                )
            )
        )

        qty = Decimal(
            str(
                trade.get(
                    "qty",
                    trade.get("q")
                )
            )
        )

        timestamp = int(
            trade.get(
                "time",
                trade.get("T", 0)
            )
        )

        if price <= 0 or timestamp <= 0:
            return None

        return {
            "price": price,
            "qty": qty,
            "time": timestamp
        }

    except Exception:
        return None


# ============================================================
# 5 MINUTE CANDLE BUILDER
# ============================================================

def candle_bucket(timestamp_ms):

    bucket_ms = TIMEFRAME_MINUTES * 60 * 1000

    return (
        timestamp_ms // bucket_ms
    ) * bucket_ms


def build_candles_from_trades(trades):

    candles = {}

    for raw in trades:

        trade = parse_trade(raw)

        if not trade:
            continue

        bucket = candle_bucket(
            trade["time"]
        )

        price = trade["price"]
        qty = trade["qty"]

        if bucket not in candles:

            candles[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty
            }

        else:

            c = candles[bucket]

            if price > c["high"]:
                c["high"] = price

            if price < c["low"]:
                c["low"] = price

            c["close"] = price
            c["volume"] += qty

    result = [
        candles[k]
        for k in sorted(candles.keys())
    ]

    return result


# ============================================================
# ONLY CLOSED 5M CANDLES
# ============================================================

def get_closed_candles(symbol):

    trades = get_trades(symbol)

    if not trades:
        return []

    candles = build_candles_from_trades(
        trades
    )

    if not candles:
        return []

    now_ms = int(
        time.time() * 1000
    )

    current_bucket = candle_bucket(
        now_ms
    )

    closed = [
        c for c in candles
        if c["time"] < current_bucket
    ]

    return closed


# ============================================================
# STATE
# ============================================================

def load_state():

    if not os.path.exists(STATE_FILE):
        return {}

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(data, dict):
                return data

    except Exception as e:

        log(f"State load error: {e}")

    return {}


def save_state(state):

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                state,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        log(f"State save error: {e}")


# ============================================================
# MERGE CANDLES INTO STATE
# ============================================================

def merge_candles(
    state,
    symbol,
    candles
):

    symbol_state = state.setdefault(
        symbol,
        []
    )

    existing = {
        int(c["time"]): c
        for c in symbol_state
        if isinstance(c, dict)
        and "time" in c
    }

    for candle in candles:
        existing[int(candle["time"])] = candle

    merged = [
        existing[k]
        for k in sorted(existing.keys())
    ]

    # Keep enough history for MACD.
    merged = merged[-200:]

    state[symbol] = merged

    return merged


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return []

    multiplier = Decimal("2") / (
        Decimal(period) + Decimal("1")
    )

    sma = (
        sum(values[:period])
        / Decimal(period)
    )

    result = [sma]

    previous = sma

    for value in values[period:]:

        current = (
            (value - previous)
            * multiplier
            + previous
        )

        result.append(current)
        previous = current

    return result


# ============================================================
# MACD
# ============================================================

def calculate_macd(candles):

    closes = [
        Decimal(str(c["close"]))
        for c in candles
    ]

    minimum = MACD_SLOW + MACD_SIGNAL + 5

    if len(closes) < minimum:
        return None

    fast = ema(
        closes,
        MACD_FAST
    )

    slow = ema(
        closes,
        MACD_SLOW
    )

    if not fast or not slow:
        return None

    # Align EMA12 with EMA26.
    offset = MACD_SLOW - MACD_FAST

    fast_aligned = fast[offset:]

    count = min(
        len(fast_aligned),
        len(slow)
    )

    fast_aligned = fast_aligned[-count:]
    slow = slow[-count:]

    macd_line = [
        fast_aligned[i] - slow[i]
        for i in range(count)
    ]

    signal_line = ema(
        macd_line,
        MACD_SIGNAL
    )

    if not signal_line:
        return None

    macd_current = macd_line[-1]
    signal_current = signal_line[-1]

    # Signal EMA starts after MACD_SIGNAL-1 values.
    macd_previous = macd_line[-2]
    signal_previous = signal_line[-2]

    histogram_current = (
        macd_current - signal_current
    )

    histogram_previous = (
        macd_previous - signal_previous
    )

    return {
        "macd": macd_current,
        "signal": signal_current,
        "histogram": histogram_current,
        "previous_macd": macd_previous,
        "previous_signal": signal_previous,
        "previous_histogram": histogram_previous
    }


# ============================================================
# SIGNAL
# ============================================================

def get_signal(candles):

    macd = calculate_macd(candles)

    if not macd:
        return None, None

    previous_macd = macd["previous_macd"]
    previous_signal = macd["previous_signal"]

    current_macd = macd["macd"]
    current_signal = macd["signal"]

    # BUY:
    # MACD crosses above signal.
    if (
        previous_macd <= previous_signal
        and current_macd > current_signal
    ):
        return "BUY", macd

    # SELL:
    # MACD crosses below signal.
    if (
        previous_macd >= previous_signal
        and current_macd < current_signal
    ):
        return "SELL", macd

    return None, macd


# ============================================================
# PRICE / QUANTITY FILTER HELPERS
# ============================================================

def get_filter_value(
    market,
    filter_type,
    key
):

    filters = market.get("filters", [])

    for f in filters:

        if f.get("filterType") == filter_type:
            return f.get(key)

    return None


# ============================================================
# QUANTITY
# ============================================================

def calculate_quantity(
    price,
    margin_usdt
):

    if price <= 0:
        return Decimal("0")

    notional = (
        margin_usdt
        * Decimal(str(LEVERAGE))
    )

    quantity = (
        notional / price
    )

    return quantity


def decimal_down(value, step):

    if step <= 0:
        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


# ============================================================
# FUTURES ACCOUNT
# ============================================================

def get_account():

    paths = [
        f"{FUTURES_PREFIX}/account",
        "/fapi/v1/account"
    ]

    for path in paths:

        data = signed_request(
            "GET",
            path
        )

        if isinstance(data, dict):
            return data

    return None


# ============================================================
# ORDER
#
# REAL ORDER IS ONLY CALLED AFTER:
# 1. valid closed candles
# 2. valid MACD
# 3. confirmed crossover
# ============================================================

def send_market_order(
    symbol,
    side,
    quantity
):

    if not REAL_TRADING:

        log(
            f"REAL OFF -> simulated order "
            f"{side} {symbol} qty={quantity}"
        )

        return {
            "simulated": True,
            "symbol": symbol,
            "side": side,
            "quantity": str(quantity)
        }

    if quantity <= 0:

        log("Invalid quantity. Order blocked.")
        return None

    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": str(quantity)
    }

    paths = [
        f"{FUTURES_PREFIX}/order",
        "/fapi/v1/order"
    ]

    for path in paths:

        result = signed_request(
            "POST",
            path,
            params
        )

        if result is not None:

            return result

    return None


# ============================================================
# PROCESS ONE MARKET
# ============================================================

def process_market(
    market,
    state
):

    symbol = market["symbol"]

    candles = get_closed_candles(
        symbol
    )

    if not candles:

        return {
            "symbol": symbol,
            "candles": 0,
            "macd": False,
            "signal": None
        }

    merged = merge_candles(
        state,
        symbol,
        candles
    )

    if len(merged) < 40:

        return {
            "symbol": symbol,
            "candles": len(merged),
            "macd": False,
            "signal": None
        }

    signal, macd = get_signal(
        merged
    )

    if not macd:

        return {
            "symbol": symbol,
            "candles": len(merged),
            "macd": False,
            "signal": None
        }

    result = {
        "symbol": symbol,
        "candles": len(merged),
        "macd": True,
        "signal": signal
    }

    # --------------------------------------------------------
    # NO SIGNAL
    # --------------------------------------------------------

    if signal is None:
        return result

    # --------------------------------------------------------
    # PREVENT SAME CANDLE DUPLICATE
    # --------------------------------------------------------

    last_candle_time = merged[-1]["time"]

    processed = state.setdefault(
        "_processed_signals",
        {}
    )

    previous = processed.get(
        symbol
    )

    signal_id = (
        f"{last_candle_time}:{signal}"
    )

    if previous == signal_id:

        log(
            f"{symbol}: duplicate signal blocked"
        )

        return result

    # --------------------------------------------------------
    # CURRENT PRICE
    # --------------------------------------------------------

    price = Decimal(
        str(merged[-1]["close"])
    )

    quantity = calculate_quantity(
        price,
        MARGIN_USDT
    )

    if quantity <= 0:
        return result

    # --------------------------------------------------------
    # ORDER
    # --------------------------------------------------------

    log(
        f"🚨 SIGNAL {symbol} "
        f"{signal} "
        f"price={price} "
        f"qty={quantity}"
    )

    order = send_market_order(
        symbol,
        signal,
        quantity
    )

    if order is not None:

        processed[symbol] = signal_id

        telegram(
            "🚨 ATI FUTURES SIGNAL\n\n"
            f"Symbol: {symbol}\n"
            f"Side: {signal}\n"
            f"Price: {price}\n"
            f"Quantity: {quantity}\n"
            f"MACD: {macd['macd']}\n"
            f"Signal: {macd['signal']}\n"
            f"Mode: "
            f"{'🔴 REAL' if REAL_TRADING else '🟡 PAPER'}"
        )

    return result


# ============================================================
# HEARTBEAT
# ============================================================

def heartbeat(
    markets_count,
    candles_count,
    macd_count,
    signals_count,
    errors
):

    mode = (
        "🔴 REAL"
        if REAL_TRADING
        else "🟢 PAPER"
    )

    message = (
        f"🤖 ATI FUTURES {VERSION}\n\n"
        f"Mode: {mode}\n"
        f"MACD: 12/26/9\n"
        f"Timeframe: 5m\n"
        f"Leverage: {LEVERAGE}x\n"
        f"Margin: {MARGIN_USDT} USDT\n\n"
        f"Markets: {markets_count}\n"
        f"Closed candles: {candles_count}\n"
        f"MACD ready: {macd_count}\n"
        f"Signals: {signals_count}\n"
        f"Errors: {errors}\n\n"
        f"5m candles are built from Futures trades."
    )

    telegram(message)


# ============================================================
# MAIN
# ============================================================

def main():

    log("=" * 60)
    log(VERSION)
    log("=" * 60)

    log(
        f"Mode: "
        f"{'REAL' if REAL_TRADING else 'PAPER'}"
    )

    log(
        f"MACD: "
        f"{MACD_FAST}/{MACD_SLOW}/{MACD_SIGNAL}"
    )

    log(
        f"Timeframe: {TIMEFRAME_MINUTES}m"
    )

    log(
        f"Leverage: {LEVERAGE}x"
    )

    log(
        f"Margin: {MARGIN_USDT} USDT"
    )

    if not API_KEY or not API_SECRET:

        telegram(
            f"🚨 ATI FUTURES {VERSION}\n\n"
            "API credentials are missing."
        )

        raise RuntimeError(
            "TABDEAL_API_KEY / "
            "TABDEAL_API_SECRET missing"
        )

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    markets = get_markets()

    if not markets:

        telegram(
            f"🚨 ATI FUTURES {VERSION}\n\n"
            "No Futures USDT market found."
        )

        raise RuntimeError(
            "No Futures markets"
        )

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    state = load_state()

    total_candles = 0
    macd_ready = 0
    signals = 0
    errors = 0

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    for market in markets:

        try:

            result = process_market(
                market,
                state
            )

            total_candles += result["candles"]

            if result["macd"]:
                macd_ready += 1

            if result["signal"]:
                signals += 1

        except Exception as e:

            errors += 1

            log(
                f"{market['symbol']} ERROR: {e}"
            )

    # --------------------------------------------------------
    # SAVE STATE
    # --------------------------------------------------------

    save_state(state)

    # --------------------------------------------------------
    # HEARTBEAT
    # --------------------------------------------------------

    heartbeat(
        len(markets),
        total_candles,
        macd_ready,
        signals,
        errors
    )

    log("=" * 60)
    log("SCAN COMPLETE")
    log("=" * 60)


if __name__ == "__main__":
    main()
