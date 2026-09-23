import os
import json
import requests
from datetime import datetime, timezone

# =========================================================
# ATI CRYPTO BOT V17
# BTCUSDT / 5 MIN
# SWING STRUCTURE + BOS + PULLBACK + MOMENTUM
# PAPER / TEST ONLY
# =========================================================

VERSION = "V17"

BASE_URL = "https://api1.tabdeal.org"
SYMBOL = "BTCUSDT"
TIMEFRAME_MS = 5 * 60 * 1000

HISTORY_FILE = "active_signal.json"
STATE_FILE = "bot_state.json"

MAX_HISTORY = 500

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT-V17"
})


# =========================================================
# HTTP
# =========================================================

def get_json(url, params=None):
    r = session.get(
        url,
        params=params,
        timeout=20
    )
    r.raise_for_status()
    return r.json()


# =========================================================
# TABDEAL
# =========================================================

def get_current_price():

    data = get_json(
        f"{BASE_URL}/r/api/v1/depth",
        {
            "symbol": SYMBOL,
            "limit": 5
        }
    )

    bids = data.get("bids", [])
    asks = data.get("asks", [])

    if not bids or not asks:
        raise ValueError("Order book is empty")

    bid = float(bids[0][0])
    ask = float(asks[0][0])

    return (bid + ask) / 2


def get_trades():

    data = get_json(
        f"{BASE_URL}/r/api/v1/trades",
        {
            "symbol": SYMBOL,
            "limit": 1000
        }
    )

    if not isinstance(data, list):
        raise ValueError("Invalid trades response")

    return data


# =========================================================
# TRADE PARSER
# =========================================================

def parse_trade(item):

    price = None
    quantity = 0.0
    timestamp = None

    if isinstance(item, dict):

        price = item.get("price", item.get("p"))

        quantity = item.get(
            "qty",
            item.get(
                "quantity",
                item.get("q", 0)
            )
        )

        timestamp = item.get(
            "time",
            item.get(
                "timestamp",
                item.get("T")
            )
        )

    elif isinstance(item, list):

        if len(item) >= 2:
            price = item[0]
            quantity = item[1]

        if len(item) >= 3:
            timestamp = item[2]

    if price is None:
        return None

    try:
        price = float(price)
    except Exception:
        return None

    try:
        quantity = float(quantity)
    except Exception:
        quantity = 0.0

    if timestamp is None:
        timestamp = int(
            datetime.now(timezone.utc).timestamp() * 1000
        )

    try:
        timestamp = int(float(timestamp))
    except Exception:
        return None

    if timestamp < 10_000_000_000:
        timestamp *= 1000

    return {
        "price": price,
        "quantity": quantity,
        "timestamp": timestamp
    }


# =========================================================
# BUILD 5M CANDLES
# =========================================================

def build_candles(trades):

    buckets = {}

    for raw in trades:

        trade = parse_trade(raw)

        if trade is None:
            continue

        ts = trade["timestamp"]
        price = trade["price"]
        qty = trade["quantity"]

        bucket = (
            ts // TIMEFRAME_MS
        ) * TIMEFRAME_MS

        if bucket not in buckets:

            buckets[bucket] = {
                "timestamp": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty
            }

        else:

            c = buckets[bucket]

            c["high"] = max(
                c["high"],
                price
            )

            c["low"] = min(
                c["low"],
                price
            )

            c["close"] = price
            c["volume"] += qty

    return sorted(
        buckets.values(),
        key=lambda x: x["timestamp"]
    )


# =========================================================
# HISTORY
# =========================================================

def load_json_file(filename, default):

    if not os.path.exists(filename):
        return default

    try:
        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        return data

    except Exception:
        return default


def save_json_file(filename, data):

    temp = filename + ".tmp"

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp, filename)


def load_history():

    data = load_json_file(
        HISTORY_FILE,
        []
    )

    if not isinstance(data, list):
        return []

    return data


def merge_history(old, new):

    merged = {}

    for c in old:

        try:
            ts = int(c["timestamp"])
            merged[ts] = c
        except Exception:
            continue

    for c in new:

        try:
            ts = int(c["timestamp"])
            merged[ts] = c
        except Exception:
            continue

    result = sorted(
        merged.values(),
        key=lambda x: x["timestamp"]
    )

    return result[-MAX_HISTORY:]


def get_closed_candles(history):

    now = int(
        datetime.now(timezone.utc).timestamp() * 1000
    )

    current_bucket = (
        now // TIMEFRAME_MS
    ) * TIMEFRAME_MS

    return [
        c for c in history
        if int(c["timestamp"]) < current_bucket
    ]


# =========================================================
# CANDLE HELPERS
# =========================================================

def high(c):
    return float(c["high"])


def low(c):
    return float(c["low"])


def close(c):
    return float(c["close"])


def open_price(c):
    return float(c["open"])


def candle_range(c):

    return max(
        high(c) - low(c),
        0.00000001
    )


def body(c):

    return abs(
        close(c) - open_price(c)
    )


def body_ratio(c):

    return body(c) / candle_range(c)


def bullish(c):

    return close(c) > open_price(c)


def bearish(c):

    return close(c) < open_price(c)


# =========================================================
# SWING DETECTION
# =========================================================

def find_swing_highs(candles):

    swings = []

    if len(candles) < 7:
        return swings

    for i in range(3, len(candles) - 3):

        h = high(candles[i])

        left = [
            high(candles[j])
            for j in range(i - 3, i)
        ]

        right = [
            high(candles[j])
            for j in range(i + 1, i + 4)
        ]

        if h > max(left) and h >= max(right):
            swings.append({
                "index": i,
                "price": h,
                "timestamp": candles[i]["timestamp"]
            })

    return swings


def find_swing_lows(candles):

    swings = []

    if len(candles) < 7:
        return swings

    for i in range(3, len(candles) - 3):

        l = low(candles[i])

        left = [
            low(candles[j])
            for j in range(i - 3, i)
        ]

        right = [
            low(candles[j])
            for j in range(i + 1, i + 4)
        ]

        if l < min(left) and l <= min(right):
            swings.append({
                "index": i,
                "price": l,
                "timestamp": candles[i]["timestamp"]
            })

    return swings


# =========================================================
# MARKET STRUCTURE
# =========================================================

def structure_analysis(candles):

    highs = find_swing_highs(candles)
    lows = find_swing_lows(candles)

    recent_highs = highs[-3:]
    recent_lows = lows[-3:]

    bullish_structure = False
    bearish_structure = False

    if len(recent_highs) >= 2:

        h1 = recent_highs[-2]["price"]
        h2 = recent_highs[-1]["price"]

        if h2 > h1:
            bullish_structure = True

    if len(recent_lows) >= 2:

        l1 = recent_lows[-2]["price"]
        l2 = recent_lows[-1]["price"]

        if l2 > l1 and bullish_structure:
            bullish_structure = True

    if len(recent_highs) >= 2:

        h1 = recent_highs[-2]["price"]
        h2 = recent_highs[-1]["price"]

        if h2 < h1:
            bearish_structure = True

    if len(recent_lows) >= 2:

        l1 = recent_lows[-2]["price"]
        l2 = recent_lows[-1]["price"]

        if l2 < l1 and bearish_structure:
            bearish_structure = True

    if bullish_structure and not bearish_structure:
        trend = "UPTREND"

    elif bearish_structure and not bullish_structure:
        trend = "DOWNTREND"

    else:
        trend = "SIDEWAYS"

    return {
        "trend": trend,
        "highs": highs,
        "lows": lows
    }


# =========================================================
# BOS - BREAK OF STRUCTURE
# =========================================================

def detect_bos(candles, structure):

    last = candles[-1]

    last_close = close(last)

    highs = structure["highs"]
    lows = structure["lows"]

    bullish_bos = False
    bearish_bos = False

    resistance = None
    support = None

    if highs:
        resistance = highs[-1]["price"]

    if lows:
        support = lows[-1]["price"]

    if resistance is not None:

        if last_close > resistance:
            bullish_bos = True

    if support is not None:

        if last_close < support:
            bearish_bos = True

    return {
        "bullish": bullish_bos,
        "bearish": bearish_bos,
        "resistance": resistance,
        "support": support
    }


# =========================================================
# MOMENTUM
# =========================================================

def momentum(candles):

    if len(candles) < 6:
        return "NEUTRAL"

    now = close(candles[-1])
    old = close(candles[-5])

    if old == 0:
        return "NEUTRAL"

    change = ((now - old) / old) * 100

    if change >= 0.20:
        return "BULLISH"

    if change <= -0.20:
        return "BEARISH"

    return "NEUTRAL"


# =========================================================
# CANDLE POWER
# =========================================================

def candle_power(candles):

    last = candles[-1]

    ratio = body_ratio(last)

    if ratio < 0.55:
        return "WEAK"

    if bullish(last):
        return "BULLISH"

    if bearish(last):
        return "BEARISH"

    return "WEAK"


# =========================================================
# RANGE LOCATION
# =========================================================

def range_location(candles):

    recent = candles[-20:]

    highest = max(
        high(c)
        for c in recent
    )

    lowest = min(
        low(c)
        for c in recent
    )

    current = close(candles[-1])

    total = highest - lowest

    if total <= 0:
        return 50.0

    return (
        (current - lowest)
        / total
    ) * 100


# =========================================================
# PULLBACK DETECTION
# =========================================================

def pullback_confirmation(candles, direction):

    if len(candles) < 6:
        return False

    last = candles[-1]
    previous = candles[-2]

    if direction == "BUY":

        # Current candle bullish after a small
        # retracement/continuation
        if bullish(last) and close(last) > close(previous):
            return True

    if direction == "SELL":

        if bearish(last) and close(last) < close(previous):
            return True

    return False


# =========================================================
# SIGNAL ENGINE
# =========================================================

def calculate_signal(candles):

    if len(candles) < 30:

        return {
            "signal": "NO SIGNAL",
            "trend": "UNKNOWN",
            "buy_score": 0,
            "sell_score": 0,
            "reason": "Not enough history"
        }

    structure = structure_analysis(candles)

    trend = structure["trend"]

    bos = detect_bos(
        candles,
        structure
    )

    momentum_direction = momentum(candles)

    power = candle_power(candles)

    location = range_location(candles)

    buy_score = 0
    sell_score = 0

    # -----------------------------------------------------
    # BUY
    # -----------------------------------------------------

    if trend == "UPTREND":
        buy_score += 1

    if bos["bullish"]:
        buy_score += 1

    if momentum_direction == "BULLISH":
        buy_score += 1

    if power == "BULLISH":
        buy_score += 1

    if pullback_confirmation(
        candles,
        "BUY"
    ):
        buy_score += 1

    # -----------------------------------------------------
    # SELL
    # -----------------------------------------------------

    if trend == "DOWNTREND":
        sell_score += 1

    if bos["bearish"]:
        sell_score += 1

    if momentum_direction == "BEARISH":
        sell_score += 1

    if power == "BEARISH":
        sell_score += 1

    if pullback_confirmation(
        candles,
        "SELL"
    ):
        sell_score += 1

    # -----------------------------------------------------
    # TOP / BOTTOM SAFETY
    # -----------------------------------------------------

    # Do not chase price at extreme top.
    if location >= 88:
        buy_score = min(
            buy_score,
            3
        )

    # Do not chase price at extreme bottom.
    if location <= 12:
        sell_score = min(
            sell_score,
            3
        )

    # -----------------------------------------------------
    # SIDEWAYS FILTER
    # -----------------------------------------------------

    if trend == "SIDEWAYS":

        return {
            "signal": "NO SIGNAL",
            "trend": trend,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "reason": "No clear market structure"
        }

    # -----------------------------------------------------
    # STRONG BUY
    # -----------------------------------------------------

    if (
        buy_score >= 4
        and buy_score > sell_score
        and location < 88
    ):

        return {
            "signal": "BUY",
            "trend": trend,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "reason": "Bullish BOS + confirmation"
        }

    # -----------------------------------------------------
    # STRONG SELL
    # -----------------------------------------------------

    if (
        sell_score >= 4
        and sell_score > buy_score
        and location > 12
    ):

        return {
            "signal": "SELL",
            "trend": trend,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "reason": "Bearish BOS + confirmation"
        }

    return {
        "signal": "NO SIGNAL",
        "trend": trend,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "reason": "No strong confirmation"
    }


# =========================================================
# SL / TP
# =========================================================

def calculate_sl_tp(candles, signal):

    entry = close(candles[-1])

    recent = candles[-8:]

    recent_high = max(
        high(c)
        for c in recent
    )

    recent_low = min(
        low(c)
        for c in recent
    )

    if signal == "BUY":

        risk = entry - recent_low

        if risk <= 0:
            risk = entry * 0.004

        sl = recent_low
        tp = entry + (risk * 2)

        return entry, sl, tp

    if signal == "SELL":

        risk = recent_high - entry

        if risk <= 0:
            risk = entry * 0.004

        sl = recent_high
        tp = entry - (risk * 2)

        return entry, sl, tp

    return entry, None, None


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    if not TELEGRAM_CHAT_ID:
        raise ValueError(
            "TELEGRAM_CHAT_ID is missing"
        )

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    response = session.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=20
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise ValueError(
            "Telegram send failed"
        )


# =========================================================
# STATE
# =========================================================

def load_state():

    state = load_json_file(
        STATE_FILE,
        {}
    )

    if not isinstance(state, dict):
        state = {}

    return state


def save_state(state):

    save_json_file(
        STATE_FILE,
        state
    )


# =========================================================
# FORMAT
# =========================================================

def money(value):

    if value is None:
        return "-"

    return f"${value:,.2f}"


def candle_datetime(timestamp):

    dt = datetime.fromtimestamp(
        timestamp / 1000,
        tz=timezone.utc
    )

    return dt.strftime(
        "%Y-%m-%d %H:%M UTC"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    # -----------------------------------------------------
    # API
    # -----------------------------------------------------

    try:
        current_price = get_current_price()
    except Exception as e:

        try:
            send_telegram(
                "🛡 ATI SAFETY\n\n"
                "❌ BTCUSDT price could not be read.\n\n"
                f"API ERROR: {e}"
            )
        except Exception:
            pass

        raise

    try:
        trades = get_trades()
    except Exception as e:

        try:
            send_telegram(
                "🛡 ATI SAFETY\n\n"
                "❌ Trades API could not be read.\n\n"
                f"API ERROR: {e}"
            )
        except Exception:
            pass

        raise

    if not trades:
        raise ValueError(
            "Trades API returned no trades"
        )

    # -----------------------------------------------------
    # CANDLES
    # -----------------------------------------------------

    new_candles = build_candles(trades)

    if not new_candles:
        raise ValueError(
            "No candles created"
        )

    # -----------------------------------------------------
    # HISTORY
    # -----------------------------------------------------

    old_history = load_history()

    history = merge_history(
        old_history,
        new_candles
    )

    save_json_file(
        HISTORY_FILE,
        history
    )

    closed = get_closed_candles(
        history
    )

    # -----------------------------------------------------
    # NOT ENOUGH DATA
    # -----------------------------------------------------

    if len(closed) < 30:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            "₿ BTC/USDT\n"
            "⏱ Timeframe: 5m\n"
            "✅ CLOSED CANDLE\n"
            "🧠 SWING STRUCTURE ENGINE\n\n"
            "📡 TABDEAL API: OK\n"
            "📊 TRADES API: OK\n\n"
            f"📚 Stored Candles: {len(closed)}\n\n"
            f"💰 Current: {money(current_price)}\n\n"
            "⏳ WAITING FOR HISTORY\n\n"
            "🛡 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED\n\n"
            "📡 TELEGRAM: OK"
        )

        send_telegram(message)
        return

    # -----------------------------------------------------
    # SIGNAL
    # -----------------------------------------------------

    result = calculate_signal(closed)

    signal = result["signal"]

    trend = result["trend"]

    buy_score = result["buy_score"]
    sell_score = result["sell_score"]

    last = closed[-1]

    entry, sl, tp = calculate_sl_tp(
        closed,
        signal
    )

    # -----------------------------------------------------
    # SIGNAL TEXT
    # -----------------------------------------------------

    if signal == "BUY":

        signal_text = "🟢 STRONG BUY"

        trade_text = (
            "🟢 BUY SIGNAL\n"
            f"💰 Entry: {money(entry)}\n"
            f"🛑 SL: {money(sl)}\n"
            f"🎯 TP: {money(tp)}"
        )

    elif signal == "SELL":

        signal_text = "🔴 STRONG SELL"

        trade_text = (
            "🔴 SELL SIGNAL\n"
            f"💰 Entry: {money(entry)}\n"
            f"🛑 SL: {money(sl)}\n"
            f"🎯 TP: {money(tp)}"
        )

    else:

        signal_text = "⚪ NO SIGNAL"

        trade_text = "⏳ NO TRADE"

    # -----------------------------------------------------
    # MESSAGE
    # -----------------------------------------------------

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "🧠 SWING + BOS + PULLBACK ENGINE\n\n"
        "📡 TABDEAL API: OK\n"
        "📊 TRADES API: OK\n\n"
        f"🕐 Candle: {candle_datetime(last['timestamp'])}\n\n"
        f"📚 Stored Candles: {len(closed)}\n\n"
        f"💰 Current: {money(current_price)}\n"
        f"💵 Candle Close: {money(last['close'])}\n\n"
        f"📊 TREND: {trend}\n\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n\n"
        f"📊 SIGNAL: {signal_text}\n\n"
        f"{trade_text}\n\n"
        "🛡 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING DISABLED\n\n"
        "📡 TELEGRAM: OK"
    )

    # -----------------------------------------------------
    # SEND
    # -----------------------------------------------------

    send_telegram(message)

    # -----------------------------------------------------
    # STATE
    # -----------------------------------------------------

    state = load_state()

    state["last_candle"] = int(
        last["timestamp"]
    )

    state["last_signal"] = signal

    state["last_update"] = datetime.now(
        timezone.utc
    ).isoformat()

    save_state(state)


if __name__ == "__main__":
    main()
