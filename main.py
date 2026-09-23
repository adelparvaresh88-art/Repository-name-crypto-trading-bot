import os
import json
import time
import requests
from datetime import datetime, timezone

# =========================================================
# ATI CRYPTO BOT V23
# SMART BREAKOUT ENGINE
# PAPER / TEST ONLY
# =========================================================

VERSION = "V23"

BASE_URL = "https://api1.tabdeal.org"
SYMBOL = "BTCUSDT"
TIMEFRAME_MS = 5 * 60 * 1000

HISTORY_FILE = "active_signal.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT/23"
})


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
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
# TABDEAL PRICE
# =========================================================

def get_price():

    url = f"{BASE_URL}/r/api/v1/depth"

    try:
        response = session.get(
            url,
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
# TABDEAL TRADES
# =========================================================

def get_trades():

    url = f"{BASE_URL}/r/api/v1/trades"

    try:
        response = session.get(
            url,
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

        if not isinstance(data, list):
            return []

        return data

    except Exception:
        return []


# =========================================================
# TRADE PARSER
# =========================================================

def parse_trade(item):

    try:

        if isinstance(item, dict):

            price = (
                item.get("price")
                or item.get("p")
            )

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

            if len(item) >= 3:
                price = item[0]
                quantity = item[1]
                timestamp = item[2]
            else:
                return None

        else:
            return None

        if price is None or timestamp is None:
            return None

        price = float(price)
        quantity = float(quantity)
        timestamp = int(timestamp)

        if timestamp < 10_000_000_000:
            timestamp *= 1000

        return {
            "price": price,
            "quantity": quantity,
            "timestamp": timestamp
        }

    except Exception:
        return None


# =========================================================
# BUILD 5 MINUTE CANDLES
# =========================================================

def build_candles(trades):

    buckets = {}

    for item in trades:

        trade = parse_trade(item)

        if not trade:
            continue

        ts = trade["timestamp"]
        price = trade["price"]

        bucket = (ts // TIMEFRAME_MS) * TIMEFRAME_MS

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

        if isinstance(data, list):
            return data

        return []

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

    now_ms = int(time.time() * 1000)

    current_bucket = (
        now_ms // TIMEFRAME_MS
    ) * TIMEFRAME_MS

    return [
        c for c in candles
        if int(c["time"]) < current_bucket
    ]


# =========================================================
# CANDLE STRENGTH
# =========================================================

def candle_direction(c):

    if c["close"] > c["open"]:
        return "BULLISH"

    if c["close"] < c["open"]:
        return "BEARISH"

    return "NEUTRAL"


def candle_body_ratio(c):

    total = c["high"] - c["low"]

    if total <= 0:
        return 0

    body = abs(
        c["close"] - c["open"]
    )

    return body / total


def candle_strength(c):

    ratio = candle_body_ratio(c)

    if ratio >= 0.65:
        return "STRONG"

    if ratio >= 0.50:
        return "NORMAL"

    return "WEAK"


# =========================================================
# SWINGS
# =========================================================

def find_swing_highs(candles):

    result = []

    for i in range(3, len(candles) - 3):

        h = candles[i]["high"]

        if (
            h > candles[i-1]["high"]
            and h > candles[i-2]["high"]
            and h > candles[i-3]["high"]
            and h > candles[i+1]["high"]
            and h > candles[i+2]["high"]
            and h > candles[i+3]["high"]
        ):
            result.append(candles[i])

    return result


def find_swing_lows(candles):

    result = []

    for i in range(3, len(candles) - 3):

        low = candles[i]["low"]

        if (
            low < candles[i-1]["low"]
            and low < candles[i-2]["low"]
            and low < candles[i-3]["low"]
            and low < candles[i+1]["low"]
            and low < candles[i+2]["low"]
            and low < candles[i+3]["low"]
        ):
            result.append(candles[i])

    return result


# =========================================================
# STRUCTURE
# =========================================================

def analyze_structure(candles):

    highs = find_swing_highs(candles)
    lows = find_swing_lows(candles)

    if len(highs) < 2 or len(lows) < 2:
        return "UNKNOWN"

    h1 = highs[-2]["high"]
    h2 = highs[-1]["high"]

    l1 = lows[-2]["low"]
    l2 = lows[-1]["low"]

    if h2 > h1 and l2 > l1:
        return "BULLISH"

    if h2 < h1 and l2 < l1:
        return "BEARISH"

    return "SIDEWAYS"


# =========================================================
# TREND
# =========================================================

def analyze_trend(candles):

    if len(candles) < 20:
        return "UNKNOWN"

    closes = [
        c["close"]
        for c in candles[-20:]
    ]

    first = sum(closes[:5]) / 5
    middle = sum(closes[7:12]) / 5
    last = sum(closes[-5:]) / 5

    if last > middle > first:
        return "UPTREND"

    if last < middle < first:
        return "DOWNTREND"

    return "SIDEWAYS"


# =========================================================
# MOMENTUM
# =========================================================

def analyze_momentum(candles):

    if len(candles) < 6:
        return "NEUTRAL"

    current = candles[-1]["close"]
    old = candles[-6]["close"]

    change = (
        (current - old) / old
    ) * 100

    if change >= 0.12:
        return "BULLISH"

    if change <= -0.12:
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
# BREAKOUT ENGINE V23
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

    current = candles[-1]

    # Important:
    # Current candle is NOT used to calculate levels.

    previous = candles[-9:-1]

    resistance = max(
        c["high"] for c in previous
    )

    support = min(
        c["low"] for c in previous
    )

    close = current["close"]

    direction = candle_direction(
        current
    )

    body = candle_body_ratio(
        current
    )

    # V23:
    # 0.03% confirmation distance
    breakout_buffer = 0.00030

    resistance_trigger = (
        resistance
        * (1 + breakout_buffer)
    )

    support_trigger = (
        support
        * (1 - breakout_buffer)
    )

    buy = (
        close >= resistance_trigger
        and direction == "BULLISH"
        and body >= 0.50
    )

    sell = (
        close <= support_trigger
        and direction == "BEARISH"
        and body >= 0.50
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
# RETEST
# =========================================================

def detect_retest(candles, resistance, support):

    if len(candles) < 4:
        return None

    c1 = candles[-3]
    c2 = candles[-2]
    c3 = candles[-1]

    if resistance:

        bullish_retest = (
            c1["close"] > resistance
            and c2["low"] <= resistance
            and c2["close"] >= resistance
            and c3["close"] > c2["close"]
            and c3["close"] > c3["open"]
        )

        if bullish_retest:
            return "BULLISH"

    if support:

        bearish_retest = (
            c1["close"] < support
            and c2["high"] >= support
            and c2["close"] <= support
            and c3["close"] < c2["close"]
            and c3["close"] < c3["open"]
        )

        if bearish_retest:
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

    buy_score = 0
    sell_score = 0

    # Trend
    if trend == "UPTREND":
        buy_score += 1

    if trend == "DOWNTREND":
        sell_score += 1

    # Structure
    if structure == "BULLISH":
        buy_score += 1

    if structure == "BEARISH":
        sell_score += 1

    # Momentum
    if momentum == "BULLISH":
        buy_score += 1

    if momentum == "BEARISH":
        sell_score += 1

    # Candle
    if direction == "BULLISH" and strength != "WEAK":
        buy_score += 1

    if direction == "BEARISH" and strength != "WEAK":
        sell_score += 1

    # Breakout
    if breakout["buy"]:
        buy_score += 1

    if breakout["sell"]:
        sell_score += 1

    # Retest
    if retest == "BULLISH":
        buy_score += 1

    if retest == "BEARISH":
        sell_score += 1

    signal = "NO SIGNAL"
    reason = ""

    # =====================================================
    # STRONG BREAKOUT
    # =====================================================

    if (
        breakout["strong_buy"]
        and momentum == "BULLISH"
        and buy_score >= 4
        and buy_score > sell_score
    ):

        signal = "BUY"
        reason = "Confirmed strong resistance breakout"

    elif (
        breakout["strong_sell"]
        and momentum == "BEARISH"
        and sell_score >= 4
        and sell_score > buy_score
    ):

        signal = "SELL"
        reason = "Confirmed strong support breakdown"

    # =====================================================
    # NORMAL BREAKOUT
    # =====================================================

    elif (
        breakout["buy"]
        and momentum == "BULLISH"
        and buy_score >= 4
        and buy_score > sell_score
    ):

        signal = "BUY"
        reason = "Confirmed resistance breakout"

    elif (
        breakout["sell"]
        and momentum == "BEARISH"
        and sell_score >= 4
        and sell_score > buy_score
    ):

        signal = "SELL"
        reason = "Confirmed support breakdown"

    # =====================================================
    # RETEST ENTRY
    # =====================================================

    elif (
        retest == "BULLISH"
        and momentum == "BULLISH"
        and buy_score >= 4
        and buy_score > sell_score
    ):

        signal = "BUY"
        reason = "Breakout retest confirmed"

    elif (
        retest == "BEARISH"
        and momentum == "BEARISH"
        and sell_score >= 4
        and sell_score > buy_score
    ):

        signal = "SELL"
        reason = "Breakdown retest confirmed"

    # =====================================================
    # NO SIGNAL REASONS
    # =====================================================

    if signal == "NO SIGNAL":

        if (
            position >= 95
            and momentum == "BULLISH"
            and not breakout["buy"]
        ):

            reason = (
                "Near range high - "
                "waiting for confirmed breakout"
            )

        elif (
            position <= 5
            and momentum == "BEARISH"
            and not breakout["sell"]
        ):

            reason = (
                "Near range low - "
                "waiting for confirmed breakdown"
            )

        elif (
            momentum == "BULLISH"
            and not breakout["buy"]
        ):

            reason = (
                "Bullish momentum - "
                "waiting for resistance break"
            )

        elif (
            momentum == "BEARISH"
            and not breakout["sell"]
        ):

            reason = (
                "Bearish momentum - "
                "waiting for support break"
            )

        else:

            reason = (
                "Breakout confirmation not strong enough"
            )

    return {
        "signal": signal,
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

        sl = low
        tp = entry + (
            risk * 2
        )

        return sl, tp

    if signal == "SELL":

        high = max(
            c["high"]
            for c in recent
        )

        risk = high - entry

        if risk <= 0:
            return None, None

        sl = high
        tp = entry - (
            risk * 2
        )

        return sl, tp

    return None, None


# =========================================================
# TIME
# =========================================================

def format_candle_time(timestamp):

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

    price = get_price()

    if price is None:

        message = (
            "🛡 ATI SAFETY\n\n"
            "❌ BTCUSDT price could not be read.\n\n"
            "API: Tabdeal public API error."
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

    new_candles = build_candles(trades)

    history = load_history()

    merged = merge_history(
        history,
        new_candles
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

    candle_time = format_candle_time(
        candle["time"]
    )

    breakout = result["breakout"]

    resistance = breakout["resistance"]
    support = breakout["support"]

    retest_text = (
        result["retest"]
        if result["retest"]
        else "NONE"
    )

    bos = "NONE"

    if breakout["buy"]:
        bos = "BULLISH"

    elif breakout["sell"]:
        bos = "BEARISH"

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"

        f"₿ BTC/USDT\n"
        f"⏱ Timeframe: 5m\n"
        f"✅ CLOSED CANDLE\n"
        f"🧠 SMART BREAKOUT ENGINE\n\n"

        f"📡 TABDEAL API: OK\n"
        f"📊 TRADES API: OK\n\n"

        f"🕐 Candle: {candle_time}\n\n"

        f"📚 Stored Candles: {len(closed)}\n\n"

        f"💰 Current: ${price:,.2f}\n"
        f"💵 Candle Close: ${candle['close']:,.2f}\n\n"

        f"📊 TREND: {result['trend']}\n"
        f"🏗 STRUCTURE: {result['structure']}\n"
        f"💥 BREAKOUT: {bos}\n"
        f"🔄 RETEST: {retest_text}\n"
        f"🚀 MOMENTUM: {result['momentum']}\n"
        f"🕯 CANDLE: {result['strength']}\n"
        f"📍 RANGE POSITION: {result['position']:.1f}%\n\n"

        f"📏 RESISTANCE: ${resistance:,.2f}\n"
        f"📏 SUPPORT: ${support:,.2f}\n\n"

        f"📈 BUY SCORE: {result['buy_score']}/7\n"
        f"📉 SELL SCORE: {result['sell_score']}/7\n\n"

        f"📊 SIGNAL: "
        f"{'🟢 BUY' if signal == 'BUY' else '🔴 SELL' if signal == 'SELL' else '⚪ NO SIGNAL'}\n"
        f"📝 REASON: {result['reason']}\n\n"
    )

    if signal in ["BUY", "SELL"]:

        message += (
            f"💵 ENTRY: ${candle['close']:,.2f}\n"
            f"🛑 SL: ${sl:,.2f}\n"
            f"🎯 TP: ${tp:,.2f}\n\n"
            f"⚠️ PAPER SIGNAL ONLY\n"
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
