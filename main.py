import os
import json
import time
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI FUTURES V9.4
# TABDEAL FUTURES
# ICHIMOKU 9 / 26 / 52
#
# IMPORTANT:
# - NO fake historical candles
# - NO guessed KLINE endpoint
# - Real 5-minute candles are built from real Futures depth
# - Persistent state is saved between GitHub Actions runs
# - Parallel market scan
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

STATE_FILE = "ati_futures_state.json"

ORDER_USDT = float(os.getenv("ORDER_USDT", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

REAL_TRADING = os.getenv(
    "REAL_TRADING", "true"
).lower() == "true"

TP_PCT = float(os.getenv("TP_PCT", "0.02"))
SL_PCT = float(os.getenv("SL_PCT", "0.01"))

MIN_SCORE = int(os.getenv("MIN_SCORE", "6"))

# Ichimoku requires 52 + current candle.
MIN_CANDLES = 53

SCAN_UNIVERSE = int(
    os.getenv("SCAN_UNIVERSE", "75")
)

MAX_WORKERS = int(
    os.getenv("MAX_WORKERS", "20")
)

REQUEST_TIMEOUT = int(
    os.getenv("REQUEST_TIMEOUT", "8")
)

RECV_WINDOW = int(
    os.getenv("RECV_WINDOW", "5000")
)

MAX_SIGNALS = 1

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-FUTURES-V9.4",
    "Accept": "application/json",
})


# ============================================================
# ENV
# ============================================================

def env_first(*names):

    for name in names:

        value = os.getenv(name)

        if value:
            return value.strip()

    return ""


API_KEY = env_first(
    "TABDEAL_API_KEY",
    "TABDIL_API_KEY",
    "TABDEAL_KEY",
    "TABDIL_KEY",
)

API_SECRET = env_first(
    "TABDEAL_API_SECRET",
    "TABDIL_API_SECRET",
    "TABDEAL_SECRET",
    "TABDIL_SECRET",
)

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()


# ============================================================
# TIME
# ============================================================

def now_utc():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def now_ms():

    return int(
        time.time() * 1000
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram(text):

    if not TELEGRAM_TOKEN:
        return False

    if not TELEGRAM_CHAT_ID:
        return False

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{TELEGRAM_TOKEN}/sendMessage"
        )

        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
            },
            timeout=10,
        )

        return response.ok

    except Exception:

        return False


# ============================================================
# STATE
# ============================================================

def load_state():

    if not os.path.exists(
        STATE_FILE
    ):
        return {}

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception:
        pass

    return {}


def save_state(state):

    temp = STATE_FILE + ".tmp"

    try:

        with open(
            temp,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                state,
                f,
                ensure_ascii=False,
                separators=(",", ":"),
            )

        os.replace(
            temp,
            STATE_FILE,
        )

    except Exception as exc:

        print(
            f"⚠️ STATE SAVE ERROR: {exc}"
        )


# ============================================================
# PUBLIC GET
# ============================================================

def public_get(
    path,
    params=None,
):

    response = session.get(
        BASE_URL + path,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code >= 400:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:200]}"
        )

    return response.json()


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(
    method,
    path,
    params=None,
):

    if not API_KEY:
        raise RuntimeError(
            "API KEY missing"
        )

    if not API_SECRET:
        raise RuntimeError(
            "API SECRET missing"
        )

    data = dict(
        params or {}
    )

    data["timestamp"] = now_ms()
    data["recvWindow"] = RECV_WINDOW

    query = "&".join(
        f"{key}={data[key]}"
        for key in sorted(data)
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()

    data["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = BASE_URL + path

    if method == "GET":

        response = session.get(
            url,
            params=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    elif method == "POST":

        response = session.post(
            url,
            data=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    else:

        raise RuntimeError(
            "Unsupported HTTP method"
        )

    if response.status_code >= 400:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    try:

        return response.json()

    except Exception:

        return {
            "raw": response.text
        }


# ============================================================
# FUTURES MARKETS
# ============================================================

def get_markets():

    data = public_get(
        "/r/fapi/v1/exchangeInfo"
    )

    markets = []

    for symbol_info in data.get(
        "symbols", []
    ):

        symbol = symbol_info.get(
            "symbol", ""
        )

        status = str(
            symbol_info.get(
                "status", ""
            )
        ).upper()

        if not symbol.endswith(
            "USDT"
        ):
            continue

        if status not in (
            "TRADING",
            "ACTIVE",
            "1",
        ):
            continue

        markets.append(
            symbol_info
        )

    return markets[
        :SCAN_UNIVERSE
    ]


# ============================================================
# DEPTH
# ============================================================

def get_depth_price(symbol):

    data = public_get(
        "/r/fapi/v1/depth",
        {
            "symbol": symbol,
            "limit": 5,
        },
    )

    bids = data.get(
        "bids", []
    )

    asks = data.get(
        "asks", []
    )

    if not bids:
        raise RuntimeError(
            "No bids"
        )

    if not asks:
        raise RuntimeError(
            "No asks"
        )

    bid = float(
        bids[0][0]
    )

    ask = float(
        asks[0][0]
    )

    if bid <= 0 or ask <= 0:
        raise RuntimeError(
            "Invalid price"
        )

    return (
        (bid + ask) / 2.0
    )


# ============================================================
# BUILD TRUE 5M CANDLE
# ============================================================

def update_5m_candle(
    state,
    symbol,
    price,
):

    bucket = (
        now_ms() // 300000
    ) * 300000

    candles = state.get(
        symbol,
        []
    )

    if not isinstance(
        candles,
        list
    ):
        candles = []

    # --------------------------------------------------------
    # Existing current candle
    # --------------------------------------------------------

    if candles:

        last = candles[-1]

        last_time = int(
            last.get("t", 0)
        )

        if last_time == bucket:

            last["h"] = max(
                float(last["h"]),
                price,
            )

            last["l"] = min(
                float(last["l"]),
                price,
            )

            last["c"] = price

        elif last_time < bucket:

            # Previous candle is now closed.
            # Add the new real-price candle.

            candles.append({
                "t": bucket,
                "o": price,
                "h": price,
                "l": price,
                "c": price,
            })

        else:

            # Clock/state anomaly.
            candles = [
                {
                    "t": bucket,
                    "o": price,
                    "h": price,
                    "l": price,
                    "c": price,
                }
            ]

    else:

        # First real candle.
        candles.append({
            "t": bucket,
            "o": price,
            "h": price,
            "l": price,
            "c": price,
        })

    # Keep enough history.
    state[symbol] = candles[-120:]

    return state[symbol]


# ============================================================
# CLOSED CANDLES
# ============================================================

def closed_candles(
    candles
):

    current_bucket = (
        now_ms() // 300000
    ) * 300000

    result = []

    for candle in candles:

        try:

            t = int(
                candle["t"]
            )

            # A candle is closed when
            # its 5-minute interval ended.

            if t < current_bucket:

                result.append(
                    candle
                )

        except Exception:
            continue

    return result


# ============================================================
# ICHIMOKU
# ============================================================

def ichimoku(
    candles
):

    candles = closed_candles(
        candles
    )

    if len(candles) < MIN_CANDLES:
        return None

    highs = [
        float(x["h"])
        for x in candles
    ]

    lows = [
        float(x["l"])
        for x in candles
    ]

    closes = [
        float(x["c"])
        for x in candles
    ]

    i = len(closes) - 1

    def midpoint(
        length,
        index,
    ):

        if index + 1 < length:
            return None

        high_part = highs[
            index - length + 1:
            index + 1
        ]

        low_part = lows[
            index - length + 1:
            index + 1
        ]

        return (
            max(high_part)
            + min(low_part)
        ) / 2.0

    tenkan = midpoint(
        9,
        i
    )

    kijun = midpoint(
        26,
        i
    )

    tenkan_prev = midpoint(
        9,
        i - 1
    )

    kijun_prev = midpoint(
        26,
        i - 1
    )

    high52 = max(
        highs[
            i - 51:
            i + 1
        ]
    )

    low52 = min(
        lows[
            i - 51:
            i + 1
        ]
    )

    span_a = (
        tenkan + kijun
    ) / 2.0

    span_b = (
        high52 + low52
    ) / 2.0

    price = closes[i]

    cloud_top = max(
        span_a,
        span_b
    )

    cloud_bottom = min(
        span_a,
        span_b
    )

    buy_score = 0
    sell_score = 0

    buy_reasons = []
    sell_reasons = []

    # --------------------------------------------------------
    # PRICE / CLOUD
    # --------------------------------------------------------

    if price > cloud_top:

        buy_score += 2

        buy_reasons.append(
            "PRICE_ABOVE_CLOUD"
        )

    elif price < cloud_bottom:

        sell_score += 2

        sell_reasons.append(
            "PRICE_BELOW_CLOUD"
        )

    # --------------------------------------------------------
    # TENKAN / KIJUN
    # --------------------------------------------------------

    if tenkan > kijun:

        buy_score += 2

        buy_reasons.append(
            "TENKAN_GT_KIJUN"
        )

    elif tenkan < kijun:

        sell_score += 2

        sell_reasons.append(
            "TENKAN_LT_KIJUN"
        )

    # --------------------------------------------------------
    # CLOUD DIRECTION
    # --------------------------------------------------------

    if span_a > span_b:

        buy_score += 1

        buy_reasons.append(
            "BULLISH_CLOUD"
        )

    elif span_a < span_b:

        sell_score += 1

        sell_reasons.append(
            "BEARISH_CLOUD"
        )

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if closes[i] > closes[i - 3]:

        buy_score += 1

        buy_reasons.append(
            "MOMENTUM_UP"
        )

    elif closes[i] < closes[i - 3]:

        sell_score += 1

        sell_reasons.append(
            "MOMENTUM_DOWN"
        )

    # --------------------------------------------------------
    # KIJUN SLOPE
    # --------------------------------------------------------

    if (
        kijun_prev is not None
        and kijun > kijun_prev
    ):

        buy_score += 1

        buy_reasons.append(
            "KIJUN_RISING"
        )

    elif (
        kijun_prev is not None
        and kijun < kijun_prev
    ):

        sell_score += 1

        sell_reasons.append(
            "KIJUN_FALLING"
        )

    signal = None
    score = 0
    reasons = []

    if (
        buy_score >= MIN_SCORE
        and buy_score > sell_score
    ):

        signal = "BUY"
        score = buy_score
        reasons = buy_reasons

    elif (
        sell_score >= MIN_SCORE
        and sell_score > buy_score
    ):

        signal = "SELL"
        score = sell_score
        reasons = sell_reasons

    return {
        "signal": signal,
        "score": score,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "price": price,
        "tenkan": tenkan,
        "kijun": kijun,
        "span_a": span_a,
        "span_b": span_b,
        "reasons": reasons,
        "candle_time": candles[-1]["t"],
    }


# ============================================================
# SYMBOL FILTER
# ============================================================

def quantity_rules(
    symbol_info
):

    step = 0.0
    minimum = 0.0
    maximum = 0.0

    for item in symbol_info.get(
        "filters", []
    ):

        filter_type = item.get(
            "filterType"
        )

        if filter_type in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE",
        ):

            try:

                step = max(
                    step,
                    float(
                        item.get(
                            "stepSize",
                            0
                        )
                    )
                )

            except Exception:
                pass

            try:

                minimum = max(
                    minimum,
                    float(
                        item.get(
                            "minQty",
                            0
                        )
                    )
                )

            except Exception:
                pass

            try:

                maximum = float(
                    item.get(
                        "maxQty",
                        0
                    )
                )

            except Exception:
                pass

    return (
        step,
        minimum,
        maximum
    )


def floor_step(
    value,
    step
):

    if step <= 0:
        return value

    a = Decimal(
        str(value)
    )

    b = Decimal(
        str(step)
    )

    return float(
        (
            a / b
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * b
    )


def calculate_quantity(
    symbol_info,
    price
):

    step, minimum, maximum = (
        quantity_rules(
            symbol_info
        )
    )

    notional = (
        ORDER_USDT
        * LEVERAGE
    )

    quantity = (
        notional / price
    )

    quantity = floor_step(
        quantity,
        step
    )

    if quantity < minimum:
        quantity = minimum

    if (
        maximum > 0
        and quantity > maximum
    ):
        quantity = maximum

    return quantity


# ============================================================
# FUTURES ACCOUNT
# ============================================================

def account_test():

    if not API_KEY or not API_SECRET:

        return False

    candidates = [
        "/fapi/v1/account",
        "/api/v1/account",
    ]

    for path in candidates:

        try:

            signed_request(
                "GET",
                path
            )

            return True

        except Exception:
            continue

    return False


# ============================================================
# LEVERAGE
# ============================================================

def set_leverage(
    symbol
):

    candidates = [
        "/fapi/v1/leverage",
        "/api/v1/leverage",
    ]

    last_error = None

    for path in candidates:

        try:

            return signed_request(
                "POST",
                path,
                {
                    "symbol": symbol,
                    "leverage": LEVERAGE,
                }
            )

        except Exception as exc:

            last_error = exc

    raise RuntimeError(
        str(last_error)
    )


# ============================================================
# MARKET ORDER
# ============================================================

def market_order(
    symbol,
    side,
    quantity
):

    candidates = [
        "/fapi/v1/order",
        "/api/v1/order",
    ]

    last_error = None

    for path in candidates:

        try:

            return signed_request(
                "POST",
                path,
                {
                    "symbol": symbol,
                    "side": side,
                    "type": "MARKET",
                    "quantity": quantity,
                }
            )

        except Exception as exc:

            last_error = exc

    raise RuntimeError(
        str(last_error)
    )


# ============================================================
# SCAN ONE MARKET
# ============================================================

def scan_one(
    symbol_info,
    state
):

    symbol = symbol_info.get(
        "symbol"
    )

    try:

        price = get_depth_price(
            symbol
        )

        candles = update_5m_candle(
            state,
            symbol,
            price
        )

        closed = closed_candles(
            candles
        )

        analysis = None

        if len(closed) >= MIN_CANDLES:

            analysis = ichimoku(
                candles
            )

        return {
            "ok": True,
            "symbol": symbol,
            "price": price,
            "closed": len(closed),
            "analysis": analysis,
            "info": symbol_info,
        }

    except Exception as exc:

        return {
            "ok": False,
            "symbol": symbol,
            "error": str(exc),
        }


# ============================================================
# TELEGRAM SIGNAL
# ============================================================

def signal_text(
    symbol,
    analysis,
):

    side = analysis[
        "signal"
    ]

    entry = analysis[
        "price"
    ]

    if side == "BUY":

        tp = entry * (
            1 + TP_PCT
        )

        sl = entry * (
            1 - SL_PCT
        )

    else:

        tp = entry * (
            1 - TP_PCT
        )

        sl = entry * (
            1 + SL_PCT
        )

    return (
        "🔥 ATI FUTURES V9.4\n\n"
        f"💰 {symbol}\n"
        f"📌 {side}\n"
        f"📊 SCORE: {analysis['score']}\n\n"
        f"💵 ENTRY: {entry:.10g}\n"
        f"🎯 TP: {tp:.10g}\n"
        f"🛑 SL: {sl:.10g}\n\n"
        "☁️ ICHIMOKU 9 / 26 / 52\n"
        f"Tenkan: {analysis['tenkan']:.10g}\n"
        f"Kijun: {analysis['kijun']:.10g}\n"
        f"Cloud A: {analysis['span_a']:.10g}\n"
        f"Cloud B: {analysis['span_b']:.10g}\n\n"
        "🧠 "
        + ", ".join(
            analysis["reasons"]
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    state = load_state()

    errors = 0
    depth_ok = 0
    ready = 0

    signals = []

    print("")
    print(
        "💓 ATI FUTURES V9.4"
    )
    print("")
    print(
        "⚡ PARALLEL DEPTH → REAL 5M"
    )
    print(
        "☁️ ICHIMOKU 9 / 26 / 52"
    )
    print("")

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    try:

        markets = get_markets()

    except Exception as exc:

        error = (
            "❌ ATI FUTURES ERROR\n\n"
            f"{exc}\n\n"
            f"🕐 {now_utc()}"
        )

        print(error)
        telegram(error)
        raise

    print(
        f"📊 Markets: {len(markets)}"
    )

    # --------------------------------------------------------
    # ACCOUNT
    # --------------------------------------------------------

    authenticated = account_test()

    print(
        "🔐 FUTURES AUTH: "
        + (
            "OK"
            if authenticated
            else "NOT VERIFIED"
        )
    )

    # --------------------------------------------------------
    # PARALLEL SCAN
    # --------------------------------------------------------

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        jobs = [
            executor.submit(
                scan_one,
                market,
                state
            )
            for market in markets
        ]

        for future in as_completed(
            jobs
        ):

            try:

                result = future.result()

                results.append(
                    result
                )

            except Exception as exc:

                errors += 1

                print(
                    f"⚠️ WORKER: {exc}"
                )

    # --------------------------------------------------------
    # PROCESS RESULTS
    # --------------------------------------------------------

    for result in results:

        if not result.get(
            "ok"
        ):

            errors += 1
            continue

        depth_ok += 1

        closed = result.get(
            "closed",
            0
        )

        if closed >= MIN_CANDLES:

            ready += 1

        analysis = result.get(
            "analysis"
        )

        if not analysis:
            continue

        if not analysis.get(
            "signal"
        ):
            continue

        signals.append(
            result
        )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_state(
        state
    )

    elapsed = (
        time.time()
        - started
    )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print("")
    print(
        f"📈 Depth OK: {depth_ok}"
    )

    print(
        f"🧠 Ready: {ready}"
    )

    print(
        f"🔥 Signals: {len(signals)}"
    )

    print(
        f"❌ Errors: {errors}"
    )

    print(
        f"⏱️ Scan: {elapsed:.2f}s"
    )

    # --------------------------------------------------------
    # NO SIGNAL
    # --------------------------------------------------------

    if not signals:

        # Find highest history count
        max_history = 0

        for result in results:

            max_history = max(
                max_history,
                int(
                    result.get(
                        "closed",
                        0
                    )
                )
            )

        message = (
            "💓 ATI FUTURES V9.4\n\n"
            "⚡ PARALLEL DEPTH → REAL 5M\n"
            "☁️ ICHIMOKU 9 / 26 / 52\n\n"
            f"📊 Markets: {len(markets)}\n"
            f"📈 Depth OK: {depth_ok}\n"
            f"🧠 Ready: {ready}\n"
            f"🔥 Signals: 0\n"
            f"❌ Errors: {errors}\n"
            f"⏱️ Scan: {elapsed:.2f}s\n\n"
            f"📚 Max closed candles: {max_history}\n\n"
            "☁️ NO SIGNAL THIS CYCLE\n\n"
            f"💵 ORDER: {ORDER_USDT} USDT\n"
            f"⚡ LEVERAGE: {LEVERAGE}x\n"
            f"🔒 REAL TRADING: {REAL_TRADING}\n"
            f"🕐 {now_utc()}"
        )

        print("")
        print(message)

        telegram(
            message
        )

        return

    # --------------------------------------------------------
    # BEST SIGNAL
    # --------------------------------------------------------

    signals.sort(
        key=lambda x:
        x["analysis"]["score"],
        reverse=True
    )

    best = signals[0]

    symbol = best[
        "symbol"
    ]

    analysis = best[
        "analysis"
    ]

    side = analysis[
        "signal"
    ]

    entry = analysis[
        "price"
    ]

    symbol_info = best[
        "info"
    ]

    quantity = calculate_quantity(
        symbol_info,
        entry
    )

    print("")
    print(
        f"🔥 BEST: {symbol} "
        f"{side}"
    )

    print(
        f"📊 SCORE: "
        f"{analysis['score']}"
    )

    print(
        f"💵 ENTRY: {entry}"
    )

    print(
        f"📦 QTY: {quantity}"
    )

    # --------------------------------------------------------
    # SEND SIGNAL
    # --------------------------------------------------------

    telegram(
        signal_text(
            symbol,
            analysis
        )
    )

    # --------------------------------------------------------
    # SAFETY
    # --------------------------------------------------------

    if not REAL_TRADING:

        print(
            "🔒 REAL TRADING OFF"
        )

        return

    if not authenticated:

        message = (
            "⚠️ ATI SIGNAL FOUND\n\n"
            f"{symbol} {side}\n\n"
            "🚫 REAL ORDER BLOCKED\n"
            "Futures authentication was not verified."
        )

        print(message)
        telegram(message)

        return

    # --------------------------------------------------------
    # LEVERAGE
    # --------------------------------------------------------

    try:

        set_leverage(
            symbol
        )

        print(
            f"⚡ {LEVERAGE}x "
            "LEVERAGE SET"
        )

    except Exception as exc:

        message = (
            "❌ LEVERAGE ERROR\n\n"
            f"{symbol}\n"
            f"{exc}"
        )

        print(message)
        telegram(message)

        return

    # --------------------------------------------------------
    # REAL MARKET ORDER
    # --------------------------------------------------------

    try:

        order = market_order(
            symbol,
            side,
            quantity
        )

        print("")
        print(
            "🚀 REAL FUTURES ORDER SENT"
        )

        print(
            json.dumps(
                order,
                ensure_ascii=False
            )
        )

    except Exception as exc:

        message = (
            "❌ REAL FUTURES ORDER FAILED\n\n"
            f"💰 {symbol}\n"
            f"📌 {side}\n"
            f"📦 QTY: {quantity}\n\n"
            f"{exc}"
        )

        print(message)
        telegram(message)

        return

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    if side == "BUY":

        tp = entry * (
            1 + TP_PCT
        )

        sl = entry * (
            1 - SL_PCT
        )

    else:

        tp = entry * (
            1 - TP_PCT
        )

        sl = entry * (
            1 + SL_PCT
        )

    final = (
        "🚀 ATI FUTURES V9.4\n\n"
        "✅ REAL MARKET ORDER SENT\n\n"
        f"💰 {symbol}\n"
        f"📌 {side}\n"
        f"📊 SCORE: {analysis['score']}\n"
        f"💵 ENTRY: {entry:.10g}\n"
        f"📦 QTY: {quantity}\n"
        f"⚡ LEVERAGE: {LEVERAGE}x\n\n"
        f"🎯 TP: {tp:.10g}\n"
        f"🛑 SL: {sl:.10g}\n\n"
        f"🕐 {now_utc()}"
    )

    print("")
    print(final)

    telegram(final)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        message = (
            "❌ ATI FUTURES V9.4 "
            "CRITICAL ERROR\n\n"
            f"{type(exc).__name__}: "
            f"{exc}\n\n"
            f"🕐 {now_utc()}"
        )

        print(message)

        telegram(
            message
        )

        raise
