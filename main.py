import os
import json
import time
import requests
from datetime import datetime, timezone

# =========================================================
# ATI CRYPTO BOT V25
# PRE-BREAKOUT WATCH ENGINE
# PAPER / TEST ONLY
# =========================================================

VERSION = "V25"

BASE_URL = "https://api1.tabdeal.org"
SYMBOL = "BTCUSDT"
TIMEFRAME_MS = 5 * 60 * 1000

HISTORY_FILE = "active_signal.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT/25"
})


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:

        url = (
            f"https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}/sendMessage"
        )

        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=15
        )

        return response.ok

    except Exception:
        return False


# =========================================================
# PRICE
# =========================================================

def get_price():

    try:

        response = session.get(
            f"{BASE_URL}/r/api/v1/depth",
            params={
                "symbol": SYMBOL,
                "limit": 5
            },
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if not bids or not asks:
            return None

        bid = float(bids[0][0])
        ask = float(asks[0][0])

        return (bid + ask) / 2

    except Exception:
        return None


# =========================================================
# TRADES
# =========================================================

def get_trades():

    try:

        response = session.get(
            f"{BASE_URL}/r/api/v1/trades",
            params={
                "symbol": SYMBOL,
                "limit": 1000
            },
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        if isinstance(data, dict):

            for key in ["data", "trades", "results"]:

                if key in data:
                    data = data[key]
                    break

        return data if isinstance(data, list) else []

    except Exception:
        return []


# =========================================================
# PARSE TRADE
# =========================================================

def parse_trade(item):

    try:

        if isinstance(item, dict):

            price = item.get("price") or item.get("p")

            quantity = (
                item.get("qty")
                or item.get("quantity")
                or item.get("q")
                or 0
            )

            timestamp = (
                item.get("time")
                or item.get("timestamp")
                or item.get("T")
            )

        elif isinstance(item, list):

            if len(item) < 3:
                return None

            price = item[0]
            quantity = item[1]
            timestamp = item[2]

        else:
            return None

        if price is None or timestamp is None:
            return None

        timestamp = int(timestamp)

        if timestamp < 10_000_000_000:
            timestamp *= 1000

        return {
            "price": float(price),
            "quantity": float(quantity),
            "timestamp": timestamp
        }

    except Exception:
        return None


# =========================================================
# BUILD 5M CANDLES
# =========================================================

def build_candles(trades):

    buckets = {}

    for item in trades:

        trade = parse_trade(item)

        if not trade:
            continue

        bucket = (
            trade["timestamp"] // TIMEFRAME_MS
        ) * TIMEFRAME_MS

        price = trade["price"]

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0
            }

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

        candle["volume"] += trade["quantity"]

    candles = list(buckets.values())

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


# =========================================================
# HISTORY
# =========================================================

def load_history():

    if not os.path.exists(HISTORY_FILE):
        return []

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        return data if isinstance(data, list) else []

    except Exception:
        return []


def save_history(candles):

    try:

        with open(
            HISTORY_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                candles[-200:],
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception:
        pass


def merge_history(history, candles):

    merged = {}

    for candle in history:

        try:
            merged[int(candle["time"])] = candle
        except Exception:
            pass

    for candle in candles:

        try:
            merged[int(candle["time"])] = candle
        except Exception:
            pass

    result = list(merged.values())

    result.sort(
        key=lambda x: x["time"]
    )

    return result[-200:]


# =========================================================
# CLOSED CANDLES
# =========================================================

def get_closed_candles(candles):

    now = int(time.time() * 1000)

    current_bucket = (
        now // TIMEFRAME_MS
    ) * TIMEFRAME_MS

    return [
        c for c in candles
        if int(c["time"]) < current_bucket
    ]


# =========================================================
# CANDLE
# =========================================================

def candle_direction(candle):

    if candle["close"] > candle["open"]:
        return "BULLISH"

    if candle["close"] < candle["open"]:
        return "BEARISH"

    return "NEUTRAL"


def candle_body_ratio(candle):

    total = candle["high"] - candle["low"]

    if total <= 0:
        return 0

    body = abs(
        candle["close"] - candle["open"]
    )

    return body / total


def candle_strength(candle):

    ratio = candle_body_ratio(candle)

    if ratio >= 0.65:
        return "STRONG"

    if ratio >= 0.45:
        return "NORMAL"

    return "WEAK"


# =========================================================
# TREND
# =========================================================

def analyze_trend(candles):

    if len(candles) < 20:
        return "UNKNOWN"

    first = sum(
        c["close"]
        for c in candles[-20:-15]
    ) / 5

    middle = sum(
        c["close"]
        for c in candles[-10:-5]
    ) / 5

    last = sum(
        c["close"]
        for c in candles[-5:]
    ) / 5

    if last > middle > first:
        return "UPTREND"

    if last < middle < first:
        return "DOWNTREND"

    return "SIDEWAYS"


# =========================================================
# STRUCTURE
# =========================================================

def analyze_structure(candles):

    if len(candles) < 15:
        return "UNKNOWN"

    recent = candles[-10:]

    highs = [
        c["high"] for c in recent
    ]

    lows = [
        c["low"] for c in recent
    ]

    if (
        highs[-1] > highs[-5]
        and lows[-1] > lows[-5]
    ):
        return "BULLISH"

    if (
        highs[-1] < highs[-5]
        and lows[-1] < lows[-5]
    ):
        return "BEARISH"

    return "SIDEWAYS"


# =========================================================
# MOMENTUM
# =========================================================

def analyze_momentum(candles):

    if len(candles) < 6:
        return "NEUTRAL"

    old = candles[-6]["close"]
    current = candles[-1]["close"]

    change = (
        (current - old) / old
    ) * 100

    if change >= 0.10:
        return "BULLISH"

    if change <= -0.10:
        return "BEARISH"

    return "NEUTRAL"


# =========================================================
# RANGE POSITION
# =========================================================

def range_position(candles):

    recent = candles[-20:]

    high = max(
        c["high"] for c in recent
    )

    low = min(
        c["low"] for c in recent
    )

    current = candles[-1]["close"]

    if high == low:
        return 50

    position = (
        (current - low)
        / (high - low)
    ) * 100

    return max(
        0,
        min(100, position)
    )


# =========================================================
# BREAKOUT
# =========================================================

def breakout_engine(candles):

    if len(candles) < 12:

        return {
            "buy": False,
            "sell": False,
            "strong_buy": False,
            "strong_sell": False,
            "resistance": None,
            "support": None
        }

    previous = candles[-9:-1]

    resistance = max(
        c["high"]
        for c in previous
    )

    support = min(
        c["low"]
        for c in previous
    )

    current = candles[-1]

    close = current["close"]

    direction = candle_direction(
        current
    )

    body = candle_body_ratio(
        current
    )

    # Confirmed breakout distance
    buffer = 0.00020

    resistance_trigger = (
        resistance * (1 + buffer)
    )

    support_trigger = (
        support * (1 - buffer)
    )

    buy = (
        close >= resistance_trigger
        and direction == "BULLISH"
        and body >= 0.45
    )

    sell = (
        close <= support_trigger
        and direction == "BEARISH"
        and body >= 0.45
    )

    strong_buy = (
        close >= resistance_trigger
        and direction == "BULLISH"
        and body >= 0.60
    )

    strong_sell = (
        close <= support_trigger
        and direction == "BEARISH"
        and body >= 0.60
    )

    return {
        "buy": buy,
        "sell": sell,
        "strong_buy": strong_buy,
        "strong_sell": strong_sell,
        "resistance": resistance,
        "support": support
    }


# =========================================================
# PRE-BREAKOUT WATCH
# =========================================================

def pre_breakout(candles, breakout):

    current = candles[-1]

    close = current["close"]

    resistance = breakout["resistance"]
    support = breakout["support"]

    if not resistance or not support:
        return "NONE"

    direction = candle_direction(current)
    momentum = analyze_momentum(candles)
    structure = analyze_structure(candles)

    # Distance from resistance/support
    distance_to_resistance = (
        (resistance - close)
        / close
    ) * 100

    distance_to_support = (
        (close - support)
        / close
    ) * 100

    # BUY WATCH:
    # within 0.12% of resistance
    # bullish momentum
    # bullish candle/structure

    if (
        distance_to_resistance <= 0.12
        and distance_to_resistance > 0
        and momentum == "BULLISH"
        and (
            direction == "BULLISH"
            or structure == "BULLISH"
        )
    ):

        return "WATCH BUY"

    # SELL WATCH

    if (
        distance_to_support <= 0.12
        and distance_to_support > 0
        and momentum == "BEARISH"
        and (
            direction == "BEARISH"
            or structure == "BEARISH"
        )
    ):

        return "WATCH SELL"

    return "NONE"


# =========================================================
# RETEST
# =========================================================

def detect_retest(
    candles,
    resistance,
    support
):

    if len(candles) < 4:
        return None

    c1 = candles[-3]
    c2 = candles[-2]
    c3 = candles[-1]

    if resistance:

        bullish = (
            c1["close"] > resistance
            and c2["low"] <= resistance
            and c2["close"] >= resistance
            and c3["close"] > c2["close"]
            and c3["close"] > c3["open"]
        )

        if bullish:
            return "BULLISH"

    if support:

        bearish = (
            c1["close"] < support
            and c2["high"] >= support
            and c2["close"] <= support
            and c3["close"] < c2["close"]
            and c3["close"] < c3["open"]
        )

        if bearish:
            return "BEARISH"

    return None


# =========================================================
# SIGNAL
# =========================================================

def generate_signal(candles):

    current = candles[-1]

    trend = analyze_trend(candles)
    structure = analyze_structure(candles)
    momentum = analyze_momentum(candles)

    direction = candle_direction(current)
    strength = candle_strength(current)

    position = range_position(candles)

    breakout = breakout_engine(candles)

    retest = detect_retest(
        candles,
        breakout["resistance"],
        breakout["support"]
    )

    watch = pre_breakout(
        candles,
        breakout
    )

    buy_score = 0
    sell_score = 0

    if trend == "UPTREND":
        buy_score += 1

    if trend == "DOWNTREND":
        sell_score += 1

    if structure == "BULLISH":
        buy_score += 1

    if structure == "BEARISH":
        sell_score += 1

    if momentum == "BULLISH":
        buy_score += 1

    if momentum == "BEARISH":
        sell_score += 1

    if direction == "BULLISH" and strength != "WEAK":
        buy_score += 1

    if direction == "BEARISH" and strength != "WEAK":
        sell_score += 1

    if breakout["buy"]:
        buy_score += 2

    if breakout["sell"]:
        sell_score += 2

    if retest == "BULLISH":
        buy_score += 1

    if retest == "BEARISH":
        sell_score += 1

    signal = "NO SIGNAL"
    reason = ""

    # =====================================================
    # CONFIRMED BUY
    # =====================================================

    if (
        breakout["buy"]
        and momentum == "BULLISH"
        and buy_score >= 4
        and buy_score > sell_score
    ):

        signal = "BUY"

        if breakout["strong_buy"]:
            reason = "STRONG resistance breakout confirmed"
        else:
            reason = "Resistance breakout confirmed"

    # =====================================================
    # CONFIRMED SELL
    # =====================================================

    elif (
        breakout["sell"]
        and momentum == "BEARISH"
        and sell_score >= 4
        and sell_score > buy_score
    ):

        signal = "SELL"

        if breakout["strong_sell"]:
            reason = "STRONG support breakdown confirmed"
        else:
            reason = "Support breakdown confirmed"

    # =====================================================
    # RETEST BUY
    # =====================================================

    elif (
        retest == "BULLISH"
        and momentum == "BULLISH"
        and buy_score >= 4
        and buy_score > sell_score
    ):

        signal = "BUY"
        reason = "Bullish breakout retest confirmed"

    # =====================================================
    # RETEST SELL
    # =====================================================

    elif (
        retest == "BEARISH"
        and momentum == "BEARISH"
        and sell_score >= 4
        and sell_score > buy_score
    ):

        signal = "SELL"
        reason = "Bearish breakdown retest confirmed"

    # =====================================================
    # NO SIGNAL REASON
    # =====================================================

    if signal == "NO SIGNAL":

        if watch == "WATCH BUY":

            reason = (
                "Price approaching resistance - "
                "watching for BUY breakout"
            )

        elif watch == "WATCH SELL":

            reason = (
                "Price approaching support - "
                "watching for SELL breakdown"
            )

        elif momentum == "BULLISH":

            reason = (
                "Bullish momentum - "
                "waiting for resistance break"
            )

        elif momentum == "BEARISH":

            reason = (
                "Bearish momentum - "
                "waiting for support break"
            )

        else:

            reason = (
                "No confirmed setup"
            )

    return {
        "signal": signal,
        "watch": watch,
        "reason": reason,
        "trend": trend,
        "structure": structure,
        "momentum": momentum,
        "direction": direction,
        "strength": strength,
        "position": position,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "retest": retest,
        "breakout": breakout
    }


# =========================================================
# SL / TP
# =========================================================

def calculate_sl_tp(candles, signal):

    entry = candles[-1]["close"]

    recent = candles[-8:]

    if signal == "BUY":

        low = min(
            c["low"]
            for c in recent
        )

        risk = entry - low

        if risk <= 0:
            return None, None

        return (
            low,
            entry + risk * 2
        )

    if signal == "SELL":

        high = max(
            c["high"]
            for c in recent
        )

        risk = high - entry

        if risk <= 0:
            return None, None

        return (
            high,
            entry - risk * 2
        )

    return None, None


# =========================================================
# TIME
# =========================================================

def format_time(timestamp):

    dt = datetime.fromtimestamp(
        timestamp / 1000,
        timezone.utc
    )

    return dt.strftime(
        "%Y-%m-%d %H:%M UTC"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    price = get_price()

    if price is None:

        message = (
            "🛡 ATI SAFETY\n\n"
            "❌ BTCUSDT price could not be read."
        )

        send_telegram(message)
        print(message)
        return

    trades = get_trades()

    if not trades:

        message = (
            "🛡 ATI SAFETY\n\n"
            "❌ Trades API could not be read."
        )

        send_telegram(message)
        print(message)
        return

    candles = build_candles(trades)

    history = load_history()

    merged = merge_history(
        history,
        candles
    )

    save_history(merged)

    closed = get_closed_candles(
        merged
    )

    if len(closed) < 20:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            "₿ BTC/USDT\n"
            "⏱ Timeframe: 5m\n\n"
            f"📚 Stored Candles: {len(closed)}\n\n"
            "⏳ Waiting for more candle history..."
        )

        send_telegram(message)
        print(message)
        return

    result = generate_signal(
        closed
    )

    candle = closed[-1]

    signal = result["signal"]

    sl, tp = calculate_sl_tp(
        closed,
        signal
    )

    breakout = result["breakout"]

    resistance = breakout["resistance"]
    support = breakout["support"]

    breakout_text = "NONE"

    if breakout["buy"]:
        breakout_text = "BULLISH"

    elif breakout["sell"]:
        breakout_text = "BEARISH"

    retest_text = (
        result["retest"]
        if result["retest"]
        else "NONE"
    )

    watch_text = result["watch"]

    if signal == "BUY":
        signal_text = "🟢 BUY"

    elif signal == "SELL":
        signal_text = "🔴 SELL"

    elif watch_text == "WATCH BUY":
        signal_text = "🟡 WATCH BUY"

    elif watch_text == "WATCH SELL":
        signal_text = "🟠 WATCH SELL"

    else:
        signal_text = "⚪ NO SIGNAL"

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"

        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "👀 PRE-BREAKOUT WATCH ENGINE\n\n"

        "📡 TABDEAL API: OK\n"
        "📊 TRADES API: OK\n\n"

        f"🕐 Candle: {format_time(candle['time'])}\n\n"

        f"📚 Stored Candles: {len(closed)}\n\n"

        f"💰 Current: ${price:,.2f}\n"
        f"💵 Candle Close: ${candle['close']:,.2f}\n\n"

        f"📊 TREND: {result['trend']}\n"
        f"🏗 STRUCTURE: {result['structure']}\n"
        f"💥 BREAKOUT: {breakout_text}\n"
        f"🔄 RETEST: {retest_text}\n"
        f"🚀 MOMENTUM: {result['momentum']}\n"
        f"🕯 CANDLE: {result['strength']}\n"
        f"📍 RANGE POSITION: {result['position']:.1f}%\n\n"

        f"📏 RESISTANCE: ${resistance:,.2f}\n"
        f"📏 SUPPORT: ${support:,.2f}\n\n"

        f"📈 BUY SCORE: {result['buy_score']}/8\n"
        f"📉 SELL SCORE: {result['sell_score']}/8\n\n"

        f"📊 SIGNAL: {signal_text}\n"
        f"📝 REASON: {result['reason']}\n\n"
    )

    if signal in ["BUY", "SELL"] and sl and tp:

        message += (
            f"💵 ENTRY: ${candle['close']:,.2f}\n"
            f"🛑 SL: ${sl:,.2f}\n"
            f"🎯 TP: ${tp:,.2f}\n\n"
            "⚠️ PAPER SIGNAL ONLY\n\n"
        )

    elif watch_text == "WATCH BUY":

        message += (
            "👀 WATCH ONLY\n"
            "⏳ Waiting for confirmed resistance breakout\n"
            "🚫 No trade yet\n\n"
        )

    elif watch_text == "WATCH SELL":

        message += (
            "👀 WATCH ONLY\n"
            "⏳ Waiting for confirmed support breakdown\n"
            "🚫 No trade yet\n\n"
        )

    else:

        message += (
            "⏳ NO TRADE\n\n"
        )

    message += (
        "🛡 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING DISABLED\n\n"
        "📡 TELEGRAM: OK"
    )

    send_telegram(message)

    print(message)


if __name__ == "__main__":
    main()
