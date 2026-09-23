import os
import json
import requests
from datetime import datetime, timezone

VERSION = "V21"

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
    "User-Agent": "ATI-CRYPTO-BOT-V21"
})


# =========================================================
# API
# =========================================================

def get_json(url, params=None):
    response = session.get(
        url,
        params=params,
        timeout=20
    )
    response.raise_for_status()
    return response.json()


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
        raise ValueError("Empty order book")

    return (
        float(bids[0][0]) +
        float(asks[0][0])
    ) / 2


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
# 5 MIN CANDLES
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

            candle["volume"] += quantity

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

    os.replace(
        temp,
        filename
    )


def merge_history(old_history, new_candles):

    merged = {}

    if isinstance(old_history, list):

        for candle in old_history:

            try:

                ts = int(
                    candle["timestamp"]
                )

                merged[ts] = candle

            except Exception:
                continue

    for candle in new_candles:

        try:

            ts = int(
                candle["timestamp"]
            )

            merged[ts] = candle

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

def breakout_info(candles):

    if len(candles) < 8:

        return {
            "buy": False,
            "sell": False,
            "high": None,
            "low": None
        }

    current = candles[-1]
    previous = candles[-6:-1]

    resistance = max(
        H(c)
        for c in previous
    )

    support = min(
        L(c)
        for c in previous
    )

    buy = (
        C(current) > resistance
        and bullish(current)
        and body_ratio(current) >= 0.50
    )

    sell = (
        C(current) < support
        and bearish(current)
        and body_ratio(current) >= 0.50
    )

    return {
        "buy": buy,
        "sell": sell,
        "high": resistance,
        "low": support
    }


# =========================================================
# RETEST
# =========================================================

def bullish_retest(candles, resistance):

    if resistance is None:
        return False

    if len(candles) < 4:
        return False

    c1 = candles[-3]
    c2 = candles[-2]
    c3 = candles[-1]

    return (
        C(c1) > resistance
        and L(c2) <= resistance
        and C(c2) >= resistance
        and bullish(c3)
        and C(c3) > C(c2)
    )


def bearish_retest(candles, support):

    if support is None:
        return False

    if len(candles) < 4:
        return False

    c1 = candles[-3]
    c2 = candles[-2]
    c3 = candles[-1]

    return (
        C(c1) < support
        and H(c2) >= support
        and C(c2) <= support
        and bearish(c3)
        and C(c3) < C(c2)
    )


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

    candle = candles[-1]

    ratio = body_ratio(candle)

    if ratio >= 0.60:

        if bullish(candle):
            return "STRONG BULLISH"

        if bearish(candle):
            return "STRONG BEARISH"

    if ratio >= 0.50:

        if bullish(candle):
            return "BULLISH"

        if bearish(candle):
            return "BEARISH"

    return "WEAK"


# =========================================================
# RANGE POSITION
# =========================================================

def price_location(candles):

    recent = candles[-20:]

    top = max(
        H(c)
        for c in recent
    )

    bottom = min(
        L(c)
        for c in recent
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
# V21 SIGNAL ENGINE
# =========================================================

def signal_engine(candles):

    if len(candles) < 30:

        return {
            "signal": "NO SIGNAL",
            "trend": "WAITING",
            "structure": "WAITING",
            "bos": "NONE",
            "retest": "NONE",
            "momentum": "NEUTRAL",
            "candle": "WEAK",
            "location": 50.0,
            "buy_score": 0,
            "sell_score": 0,
            "reason": "Not enough history"
        }

    structure = get_structure(
        candles
    )

    trend = structure["trend"]

    breakout = breakout_info(
        candles
    )

    momentum = get_momentum(
        candles
    )

    candle_strength = get_candle_strength(
        candles
    )

    location = price_location(
        candles
    )

    resistance = breakout["high"]
    support = breakout["low"]

    buy_retest = bullish_retest(
        candles,
        resistance
    )

    sell_retest = bearish_retest(
        candles,
        support
    )

    buy_score = 0
    sell_score = 0

    # BUY SCORE
    if trend == "UPTREND":
        buy_score += 1

    if momentum == "BULLISH":
        buy_score += 1

    if candle_strength in (
        "BULLISH",
        "STRONG BULLISH"
    ):
        buy_score += 1

    if breakout["buy"]:
        buy_score += 1

    if buy_retest:
        buy_score += 1

    # SELL SCORE
    if trend == "DOWNTREND":
        sell_score += 1

    if momentum == "BEARISH":
        sell_score += 1

    if candle_strength in (
        "BEARISH",
        "STRONG BEARISH"
    ):
        sell_score += 1

    if breakout["sell"]:
        sell_score += 1

    if sell_retest:
        sell_score += 1

    # -----------------------------------------------------
    # STRONG BREAKOUT OVERRIDES RANGE-HIGH BLOCK
    # -----------------------------------------------------

    strong_buy_breakout = (
        breakout["buy"]
        and momentum == "BULLISH"
        and candle_strength == "STRONG BULLISH"
    )

    strong_sell_breakout = (
        breakout["sell"]
        and momentum == "BEARISH"
        and candle_strength == "STRONG BEARISH"
    )

    # -----------------------------------------------------
    # NORMAL BUY
    # -----------------------------------------------------

    normal_buy = (
        buy_score >= 4
        and buy_score > sell_score
        and momentum == "BULLISH"
        and candle_strength in (
            "BULLISH",
            "STRONG BULLISH"
        )
        and location < 90
        and (
            breakout["buy"]
            or buy_retest
        )
    )

    # -----------------------------------------------------
    # BREAKOUT BUY
    # -----------------------------------------------------

    breakout_buy = (
        strong_buy_breakout
        and buy_score >= 3
        and buy_score > sell_score
    )

    # -----------------------------------------------------
    # NORMAL SELL
    # -----------------------------------------------------

    normal_sell = (
        sell_score >= 4
        and sell_score > buy_score
        and momentum == "BEARISH"
        and candle_strength in (
            "BEARISH",
            "STRONG BEARISH"
        )
        and location > 10
        and (
            breakout["sell"]
            or sell_retest
        )
    )

    # -----------------------------------------------------
    # BREAKDOWN SELL
    # -----------------------------------------------------

    breakout_sell = (
        strong_sell_breakout
        and sell_score >= 3
        and sell_score > buy_score
    )

    if breakout_buy:

        return {
            "signal": "BUY",
            "trend": "BULLISH BREAKOUT",
            "structure": "BULLISH",
            "bos": "CONFIRMED",
            "retest": (
                "CONFIRMED"
                if buy_retest
                else "WAITING"
            ),
            "momentum": momentum,
            "candle": candle_strength,
            "location": location,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "reason": "Strong bullish breakout"
        }

    if normal_buy:

        return {
            "signal": "BUY",
            "trend": trend,
            "structure": "BULLISH",
            "bos": (
                "CONFIRMED"
                if breakout["buy"]
                else "NO"
            ),
            "retest": (
                "CONFIRMED"
                if buy_retest
                else "WAITING"
            ),
            "momentum": momentum,
            "candle": candle_strength,
            "location": location,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "reason": "Bullish confirmation"
        }

    if breakout_sell:

        return {
            "signal": "SELL",
            "trend": "BEARISH BREAKDOWN",
            "structure": "BEARISH",
            "bos": "CONFIRMED",
            "retest": (
                "CONFIRMED"
                if sell_retest
                else "WAITING"
            ),
            "momentum": momentum,
            "candle": candle_strength,
            "location": location,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "reason": "Strong bearish breakdown"
        }

    if normal_sell:

        return {
            "signal": "SELL",
            "trend": trend,
            "structure": "BEARISH",
            "bos": (
                "CONFIRMED"
                if breakout["sell"]
                else "NO"
            ),
            "retest": (
                "CONFIRMED"
                if sell_retest
                else "WAITING"
            ),
            "momentum": momentum,
            "candle": candle_strength,
            "location": location,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "reason": "Bearish confirmation"
        }

    # -----------------------------------------------------
    # NO SIGNAL REASON
    # -----------------------------------------------------

    if location >= 90:
        reason = "Near range high - waiting for strong breakout"

    elif location <= 10:
        reason = "Near range low - waiting for strong breakdown"

    elif momentum == "BULLISH":
        reason = "Bullish momentum - waiting for breakout/retest"

    elif momentum == "BEARISH":
        reason = "Bearish momentum - waiting for breakdown/retest"

    else:
        reason = "Waiting for confirmation"

    return {
        "signal": "NO SIGNAL",
        "trend": trend,
        "structure": (
            "BULLISH"
            if buy_score > sell_score
            else "BEARISH"
            if sell_score > buy_score
            else "UNCLEAR"
        ),
        "bos": (
            "BULLISH"
            if breakout["buy"]
            else "BEARISH"
            if breakout["sell"]
            else "NONE"
        ),
        "retest": (
            "BUY"
            if buy_retest
            else "SELL"
            if sell_retest
            else "NONE"
        ),
        "momentum": momentum,
        "candle": candle_strength,
        "location": location,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "reason": reason
    }


# =========================================================
# SL / TP
# =========================================================

def calculate_sl_tp(candles, signal):

    entry = C(candles[-1])

    recent = candles[-8:]

    high = max(
        H(c)
        for c in recent
    )

    low = min(
        L(c)
        for c in recent
    )

    if signal == "BUY":

        risk = entry - low

        if risk <= 0:
            risk = entry * 0.004

        return (
            entry,
            low,
            entry + risk * 2
        )

    if signal == "SELL":

        risk = high - entry

        if risk <= 0:
            risk = entry * 0.004

        return (
            entry,
            high,
            entry - risk * 2
        )

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

    response = session.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=20
    )

    response.raise_for_status()

    if not response.json().get("ok"):
        raise ValueError(
            "Telegram API failed"
        )


def money(value):

    if value is None:
        return "-"

    return f"${value:,.2f}"


def candle_time(timestamp):

    return datetime.fromtimestamp(
        timestamp / 1000,
        tz=timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


# =========================================================
# MAIN
# =========================================================

def main():

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
            "No trades returned"
        )

    candles = build_candles(
        trades
    )

    if not candles:
        raise ValueError(
            "No candles created"
        )

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

    if len(closed) < 30:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            "₿ BTC/USDT\n"
            "⏱ Timeframe: 5m\n"
            "✅ CLOSED CANDLE\n"
            "🧠 BREAKOUT + RETEST ENGINE\n\n"
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

    result = signal_engine(
        closed
    )

    signal = result["signal"]

    entry, sl, tp = calculate_sl_tp(
        closed,
        signal
    )

    last = closed[-1]

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

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "🧠 BREAKOUT + RETEST ENGINE\n\n"
        "📡 TABDEAL API: OK\n"
        "📊 TRADES API: OK\n\n"
        f"🕐 Candle: {candle_time(last['timestamp'])}\n\n"
        f"📚 Stored Candles: {len(closed)}\n\n"
        f"💰 Current: {money(current_price)}\n"
        f"💵 Candle Close: {money(last['close'])}\n\n"
        f"📊 TREND: {result['trend']}\n"
        f"🏗 STRUCTURE: {result['structure']}\n"
        f"💥 BOS: {result['bos']}\n"
        f"🔄 RETEST: {result['retest']}\n"
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


if __name__ == "__main__":
    main()
