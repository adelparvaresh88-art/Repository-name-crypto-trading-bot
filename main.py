import os
import json
import requests
from datetime import datetime, timezone

VERSION = "V20"

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
    "User-Agent": "ATI-CRYPTO-BOT-V20"
})


# =========================================================
# API
# =========================================================

def get_json(url, params=None):
    r = session.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def get_current_price():
    data = get_json(
        f"{BASE_URL}/r/api/v1/depth",
        {"symbol": SYMBOL, "limit": 5}
    )

    bids = data.get("bids", [])
    asks = data.get("asks", [])

    if not bids or not asks:
        raise ValueError("Empty order book")

    bid = float(bids[0][0])
    ask = float(asks[0][0])

    return (bid + ask) / 2


def get_trades():
    data = get_json(
        f"{BASE_URL}/r/api/v1/trades",
        {"symbol": SYMBOL, "limit": 1000}
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

        price = item.get(
            "price",
            item.get("p")
        )

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
        quantity = trade["quantity"]

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
                "volume": quantity
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
            c["volume"] += quantity

    return sorted(
        buckets.values(),
        key=lambda x: x["timestamp"]
    )


# =========================================================
# STORAGE
# =========================================================

def load_json(filename, default):

    if not os.path.exists(filename):
        return default

    try:

        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return default


def save_json(filename, data):

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


def merge_history(old_history, new_candles):

    merged = {}

    if isinstance(old_history, list):

        for c in old_history:

            try:
                ts = int(c["timestamp"])
                merged[ts] = c
            except Exception:
                continue

    for c in new_candles:

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

def O(c):
    return float(c["open"])


def H(c):
    return float(c["high"])


def L(c):
    return float(c["low"])


def C(c):
    return float(c["close"])


def candle_range(c):
    return max(
        H(c) - L(c),
        0.00000001
    )


def body(c):
    return abs(
        C(c) - O(c)
    )


def body_ratio(c):
    return body(c) / candle_range(c)


def bullish(c):
    return C(c) > O(c)


def bearish(c):
    return C(c) < O(c)


# =========================================================
# SWINGS
# =========================================================

def swing_highs(candles):

    result = []

    if len(candles) < 7:
        return result

    for i in range(
        3,
        len(candles) - 3
    ):

        current = H(candles[i])

        left = max(
            H(candles[x])
            for x in range(i - 3, i)
        )

        right = max(
            H(candles[x])
            for x in range(i + 1, i + 4)
        )

        if current > left and current >= right:

            result.append({
                "index": i,
                "price": current,
                "timestamp": candles[i]["timestamp"]
            })

    return result


def swing_lows(candles):

    result = []

    if len(candles) < 7:
        return result

    for i in range(
        3,
        len(candles) - 3
    ):

        current = L(candles[i])

        left = min(
            L(candles[x])
            for x in range(i - 3, i)
        )

        right = min(
            L(candles[x])
            for x in range(i + 1, i + 4)
        )

        if current < left and current <= right:

            result.append({
                "index": i,
                "price": current,
                "timestamp": candles[i]["timestamp"]
            })

    return result


# =========================================================
# STRUCTURE
# =========================================================

def get_structure(candles):

    highs = swing_highs(candles)
    lows = swing_lows(candles)

    trend = "SIDEWAYS"

    if len(highs) >= 2 and len(lows) >= 2:

        h1 = highs[-2]["price"]
        h2 = highs[-1]["price"]

        l1 = lows[-2]["price"]
        l2 = lows[-1]["price"]

        if h2 > h1 and l2 > l1:
            trend = "UPTREND"

        elif h2 < h1 and l2 < l1:
            trend = "DOWNTREND"

    return {
        "trend": trend,
        "highs": highs,
        "lows": lows
    }


# =========================================================
# BREAKOUT
# =========================================================

def breakout_quality(candles, direction):

    if len(candles) < 8:
        return False

    current = candles[-1]
    previous = candles[-6:-1]

    if direction == "BUY":

        resistance = max(
            H(c) for c in previous
        )

        return (
            C(current) > resistance
            and bullish(current)
            and body_ratio(current) >= 0.50
        )

    if direction == "SELL":

        support = min(
            L(c) for c in previous
        )

        return (
            C(current) < support
            and bearish(current)
            and body_ratio(current) >= 0.50
        )

    return False


# =========================================================
# BOS
# =========================================================

def get_bos(candles, structure):

    last_close = C(candles[-1])

    highs = structure["highs"]
    lows = structure["lows"]

    resistance = (
        highs[-1]["price"]
        if highs else None
    )

    support = (
        lows[-1]["price"]
        if lows else None
    )

    bullish_bos = False
    bearish_bos = False

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

def get_momentum(candles):

    if len(candles) < 6:
        return "NEUTRAL"

    current = C(candles[-1])
    previous = C(candles[-5])

    if previous == 0:
        return "NEUTRAL"

    change = (
        (current - previous)
        / previous
    ) * 100

    if change >= 0.12:
        return "BULLISH"

    if change <= -0.12:
        return "BEARISH"

    return "NEUTRAL"


# =========================================================
# CANDLE STRENGTH
# =========================================================

def get_candle_strength(candles):

    c = candles[-1]

    ratio = body_ratio(c)

    if ratio < 0.50:
        return "WEAK"

    if bullish(c):
        return "BULLISH"

    if bearish(c):
        return "BEARISH"

    return "WEAK"


# =========================================================
# PULLBACK / RETEST
# =========================================================

def pullback_buy(candles):

    if len(candles) < 5:
        return False

    c1 = candles[-3]
    c2 = candles[-2]
    c3 = candles[-1]

    return (
        bearish(c1)
        and bullish(c2)
        and bullish(c3)
        and C(c3) > C(c2)
    )


def pullback_sell(candles):

    if len(candles) < 5:
        return False

    c1 = candles[-3]
    c2 = candles[-2]
    c3 = candles[-1]

    return (
        bullish(c1)
        and bearish(c2)
        and bearish(c3)
        and C(c3) < C(c2)
    )


# =========================================================
# RANGE POSITION
# =========================================================

def price_location(candles):

    recent = candles[-20:]

    top = max(
        H(c) for c in recent
    )

    bottom = min(
        L(c) for c in recent
    )

    current = C(candles[-1])

    distance = top - bottom

    if distance <= 0:
        return 50.0

    return (
        (current - bottom)
        / distance
    ) * 100


# =========================================================
# V20 SIGNAL ENGINE
# =========================================================

def signal_engine(candles):

    if len(candles) < 30:

        return {
            "signal": "NO SIGNAL",
            "trend": "WAITING",
            "buy_score": 0,
            "sell_score": 0,
            "structure": "WAITING",
            "bos": "NONE",
            "pullback": "NONE",
            "momentum": "NEUTRAL",
            "candle": "WEAK",
            "location": 50,
            "reason": "Not enough history"
        }

    structure = get_structure(candles)

    trend = structure["trend"]

    bos = get_bos(
        candles,
        structure
    )

    momentum = get_momentum(candles)

    candle_strength = get_candle_strength(
        candles
    )

    location = price_location(
        candles
    )

    buy_pullback = pullback_buy(candles)
    sell_pullback = pullback_sell(candles)

    buy_breakout = (
        bos["bullish"]
        or breakout_quality(
            candles,
            "BUY"
        )
    )

    sell_breakout = (
        bos["bearish"]
        or breakout_quality(
            candles,
            "SELL"
        )
    )

    buy_score = 0
    sell_score = 0

    # -----------------------------------------------------
    # BUY
    # -----------------------------------------------------

    if trend == "UPTREND":
        buy_score += 1

    if momentum == "BULLISH":
        buy_score += 1

    if candle_strength == "BULLISH":
        buy_score += 1

    if buy_breakout:
        buy_score += 1

    if buy_pullback:
        buy_score += 1

    # -----------------------------------------------------
    # SELL
    # -----------------------------------------------------

    if trend == "DOWNTREND":
        sell_score += 1

    if momentum == "BEARISH":
        sell_score += 1

    if candle_strength == "BEARISH":
        sell_score += 1

    if sell_breakout:
        sell_score += 1

    if sell_pullback:
        sell_score += 1

    # -----------------------------------------------------
    # EXTREME FILTER
    # -----------------------------------------------------

    if location >= 90:

        buy_score = min(
            buy_score,
            3
        )

    if location <= 10:

        sell_score = min(
            sell_score,
            3
        )

    # -----------------------------------------------------
    # BUY CONFIRMATION
    # -----------------------------------------------------

    buy_confirmed = (
        buy_score >= 4
        and buy_score > sell_score
        and location < 90
        and momentum == "BULLISH"
        and candle_strength == "BULLISH"
        and (
            buy_breakout
            or buy_pullback
        )
    )

    # -----------------------------------------------------
    # SELL CONFIRMATION
    # -----------------------------------------------------

    sell_confirmed = (
        sell_score >= 4
        and sell_score > buy_score
        and location > 10
        and momentum == "BEARISH"
        and candle_strength == "BEARISH"
        and (
            sell_breakout
            or sell_pullback
        )
    )

    if buy_confirmed:

        return {
            "signal": "BUY",
            "trend": (
                "UPTREND"
                if trend == "UPTREND"
                else "BULLISH SETUP"
            ),
            "buy_score": buy_score,
            "sell_score": sell_score,
            "structure": "BULLISH",
            "bos": (
                "CONFIRMED"
                if bos["bullish"]
                else "BREAKOUT"
                if buy_breakout
                else "NO"
            ),
            "pullback": (
                "CONFIRMED"
                if buy_pullback
                else "NO"
            ),
            "momentum": momentum,
            "candle": candle_strength,
            "location": location,
            "reason": "Strong BUY confirmation"
        }

    if sell_confirmed:

        return {
            "signal": "SELL",
            "trend": (
                "DOWNTREND"
                if trend == "DOWNTREND"
                else "BEARISH SETUP"
            ),
            "buy_score": buy_score,
            "sell_score": sell_score,
            "structure": "BEARISH",
            "bos": (
                "CONFIRMED"
                if bos["bearish"]
                else "BREAKDOWN"
                if sell_breakout
                else "NO"
            ),
            "pullback": (
                "CONFIRMED"
                if sell_pullback
                else "NO"
            ),
            "momentum": momentum,
            "candle": candle_strength,
            "location": location,
            "reason": "Strong SELL confirmation"
        }

    # -----------------------------------------------------
    # NO SIGNAL
    # -----------------------------------------------------

    if location >= 90:

        reason = "Price near range high"

    elif location <= 10:

        reason = "Price near range low"

    elif momentum == "BULLISH":

        reason = "Bullish momentum waiting for confirmation"

    elif momentum == "BEARISH":

        reason = "Bearish momentum waiting for confirmation"

    else:

        reason = "Waiting for structure confirmation"

    return {
        "signal": "NO SIGNAL",
        "trend": trend,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "structure": (
            "BULLISH"
            if buy_score > sell_score
            else "BEARISH"
            if sell_score > buy_score
            else "UNCLEAR"
        ),
        "bos": (
            "BULLISH"
            if buy_breakout
            else "BEARISH"
            if sell_breakout
            else "NONE"
        ),
        "pullback": (
            "BUY"
            if buy_pullback
            else "SELL"
            if sell_pullback
            else "NONE"
        ),
        "momentum": momentum,
        "candle": candle_strength,
        "location": location,
        "reason": reason
    }


# =========================================================
# SL / TP
# =========================================================

def calculate_sl_tp(candles, signal):

    entry = C(candles[-1])

    recent = candles[-8:]

    high = max(
        H(c) for c in recent
    )

    low = min(
        L(c) for c in recent
    )

    if signal == "BUY":

        risk = entry - low

        if risk <= 0:
            risk = entry * 0.004

        sl = low
        tp = entry + (
            risk * 2
        )

        return entry, sl, tp

    if signal == "SELL":

        risk = high - entry

        if risk <= 0:
            risk = entry * 0.004

        sl = high
        tp = entry - (
            risk * 2
        )

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
        f"{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    r = session.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=20
    )

    r.raise_for_status()

    result = r.json()

    if not result.get("ok"):
        raise ValueError(
            "Telegram API failed"
        )


# =========================================================
# FORMAT
# =========================================================

def money(value):

    if value is None:
        return "-"

    return f"${value:,.2f}"


def candle_time(timestamp):

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

    # PRICE
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

    # TRADES
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
            "No trades returned"
        )

    # CANDLES
    candles = build_candles(
        trades
    )

    if not candles:
        raise ValueError(
            "No candles created"
        )

    # HISTORY
    history = load_json(
        HISTORY_FILE,
        []
    )

    history = merge_history(
        history,
        candles
    )

    save_json(
        HISTORY_FILE,
        history
    )

    closed = get_closed_candles(
        history
    )

    # HISTORY WAIT
    if len(closed) < 30:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            "₿ BTC/USDT\n"
            "⏱ Timeframe: 5m\n"
            "✅ CLOSED CANDLE\n"
            "🧠 SMART PRICE ACTION ENGINE\n\n"
            "📡 TABDEAL API: OK\n"
            "📊 TRADES API: OK\n\n"
            f"📚 Stored Candles: {len(closed)}\n\n"
            f"💰 Current: {money(current_price)}\n\n"
            "⏳ WAITING FOR MORE HISTORY\n\n"
            "🛡 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED\n\n"
            "📡 TELEGRAM: OK"
        )

        send_telegram(message)

        return

    # SIGNAL
    result = signal_engine(
        closed
    )

    signal = result["signal"]

    entry, sl, tp = calculate_sl_tp(
        closed,
        signal
    )

    last = closed[-1]

    # TRADE BLOCK
    if signal == "BUY":

        signal_text = "🟢 STRONG BUY"

        trade_block = (
            "🟢 BUY SIGNAL\n"
            f"💰 Entry: {money(entry)}\n"
            f"🛑 SL: {money(sl)}\n"
            f"🎯 TP: {money(tp)}"
        )

    elif signal == "SELL":

        signal_text = "🔴 STRONG SELL"

        trade_block = (
            "🔴 SELL SIGNAL\n"
            f"💰 Entry: {money(entry)}\n"
            f"🛑 SL: {money(sl)}\n"
            f"🎯 TP: {money(tp)}"
        )

    else:

        signal_text = "⚪ NO SIGNAL"

        trade_block = "⏳ NO TRADE"

    # TELEGRAM MESSAGE
    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "🧠 SMART BREAKOUT ENGINE\n\n"
        "📡 TABDEAL API: OK\n"
        "📊 TRADES API: OK\n\n"
        f"🕐 Candle: {candle_time(last['timestamp'])}\n\n"
        f"📚 Stored Candles: {len(closed)}\n\n"
        f"💰 Current: {money(current_price)}\n"
        f"💵 Candle Close: {money(last['close'])}\n\n"
        f"📊 TREND: {result['trend']}\n"
        f"🏗 STRUCTURE: {result['structure']}\n"
        f"💥 BOS: {result['bos']}\n"
        f"↩️ PULLBACK: {result['pullback']}\n"
        f"🚀 MOMENTUM: {result['momentum']}\n"
        f"🕯 CANDLE: {result['candle']}\n"
        f"📍 RANGE POSITION: {result['location']:.1f}%\n\n"
        f"📈 BUY SCORE: {result['buy_score']}/5\n"
        f"📉 SELL SCORE: {result['sell_score']}/5\n\n"
        f"📊 SIGNAL: {signal_text}\n"
        f"📝 REASON: {result['reason']}\n\n"
        f"{trade_block}\n\n"
        "🛡 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING DISABLED\n\n"
        "📡 TELEGRAM: OK"
    )

    send_telegram(message)

    # STATE
    state = load_json(
        STATE_FILE,
        {}
    )

    state["last_candle"] = int(
        last["timestamp"]
    )

    state["last_signal"] = signal

    state["last_update"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    save_json(
        STATE_FILE,
        state
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
