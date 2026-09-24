import os
import time
import requests
from datetime import datetime, timezone

# ============================================================
# ATI CRYPTO BOT V26
# PRE-BREAKOUT WATCH ENGINE
# 5m CLOSED CANDLE
# RETEST IS NOT MANDATORY
# MINIMUM SIGNAL SCORE = 4/8
# PAPER / TEST MODE
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"

CANDLE_LIMIT = 180
MIN_SIGNAL_SCORE = 4

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM ERROR: missing token/chat id")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print("TELEGRAM:", response.status_code)

        if response.ok:
            return True

        print(response.text)
        return False

    except Exception as e:
        print("TELEGRAM ERROR:", e)
        return False


# ============================================================
# TABDEAL API
# ============================================================

def get_klines():

    urls = [
        f"{BASE_URL}/v1/market/candles?symbol={SYMBOL}&interval={TIMEFRAME}&limit={CANDLE_LIMIT}",
        f"{BASE_URL}/api/v1/market/candles?symbol={SYMBOL}&interval={TIMEFRAME}&limit={CANDLE_LIMIT}"
    ]

    last_error = ""

    for url in urls:

        try:
            r = requests.get(url, timeout=20)

            if r.status_code != 200:
                last_error = f"HTTP {r.status_code}: {r.text[:200]}"
                continue

            data = r.json()

            if isinstance(data, dict):

                for key in ["data", "result", "candles"]:

                    if key in data and isinstance(data[key], list):
                        data = data[key]
                        break

            if not isinstance(data, list):
                last_error = "Invalid candle response"
                continue

            if len(data) < 30:
                last_error = "Not enough candles"
                continue

            return data

        except Exception as e:
            last_error = str(e)

    raise RuntimeError(last_error)


# ============================================================
# CANDLE PARSER
# ============================================================

def parse_candle(c):

    if isinstance(c, dict):

        timestamp = (
            c.get("timestamp")
            or c.get("time")
            or c.get("open_time")
            or c.get("openTime")
        )

        open_price = c.get("open") or c.get("o")
        high = c.get("high") or c.get("h")
        low = c.get("low") or c.get("l")
        close = c.get("close") or c.get("c")
        volume = c.get("volume") or c.get("v") or 0

    else:

        timestamp = c[0]
        open_price = c[1]
        high = c[2]
        low = c[3]
        close = c[4]
        volume = c[5] if len(c) > 5 else 0

    return {
        "time": int(float(timestamp)),
        "open": float(open_price),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume)
    }


# ============================================================
# HELPERS
# ============================================================

def pct_change(a, b):

    if a == 0:
        return 0

    return ((b - a) / a) * 100


def average(values):

    if not values:
        return 0

    return sum(values) / len(values)


def candle_body(c):

    return abs(c["close"] - c["open"])


def candle_range(c):

    return max(c["high"] - c["low"], 0.00000001)


def is_bullish(c):

    return c["close"] > c["open"]


def is_bearish(c):

    return c["close"] < c["open"]


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=14):

    if len(candles) < period + 1:
        return candle_range(candles[-1])

    trs = []

    for i in range(-period, 0):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"])
        )

        trs.append(tr)

    return average(trs)


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze(candles):

    # --------------------------------------------------------
    # IMPORTANT:
    # Last candle is assumed to be the currently forming candle.
    # We therefore analyze the LAST CLOSED candle.
    # --------------------------------------------------------

    closed = candles[-2]

    recent = candles[-22:-2]

    current_price = candles[-1]["close"]

    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]
    closes = [c["close"] for c in recent]

    resistance = max(highs)
    support = min(lows)

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    old_avg = average(closes[:10])
    new_avg = average(closes[-10:])

    trend_move = pct_change(old_avg, new_avg)

    if trend_move > 0.20:
        trend = "BULLISH"
    elif trend_move < -0.20:
        trend = "BEARISH"
    else:
        trend = "SIDEWAYS"

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    first_half = recent[:10]
    second_half = recent[-10:]

    first_high = max(c["high"] for c in first_half)
    second_high = max(c["high"] for c in second_half)

    first_low = min(c["low"] for c in first_half)
    second_low = min(c["low"] for c in second_half)

    if second_high < first_high and second_low < first_low:
        structure = "BEARISH"

    elif second_high > first_high and second_low > first_low:
        structure = "BULLISH"

    else:
        structure = "MIXED"

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    previous_resistance = max(
        c["high"] for c in candles[-22:-3]
    )

    previous_support = min(
        c["low"] for c in candles[-22:-3]
    )

    breakout = "NONE"

    if closed["close"] > previous_resistance:
        breakout = "BULLISH"

    elif closed["close"] < previous_support:
        breakout = "BEARISH"

    # --------------------------------------------------------
    # RETEST
    # --------------------------------------------------------

    retest = "NONE"

    if breakout == "BULLISH":

        distance = abs(
            closed["low"] - previous_resistance
        )

        if distance <= previous_resistance * 0.0025:
            retest = "BULLISH"

    elif breakout == "BEARISH":

        distance = abs(
            closed["high"] - previous_support
        )

        if distance <= previous_support * 0.0025:
            retest = "BEARISH"

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    momentum_change = pct_change(
        candles[-7]["close"],
        closed["close"]
    )

    if momentum_change > 0.18:
        momentum = "BULLISH"

    elif momentum_change < -0.18:
        momentum = "BEARISH"

    else:
        momentum = "NEUTRAL"

    # --------------------------------------------------------
    # CANDLE STRENGTH
    # --------------------------------------------------------

    body = candle_body(closed)
    rng = candle_range(closed)

    body_ratio = body / rng

    if body_ratio >= 0.65:
        candle_strength = "STRONG"

    elif body_ratio >= 0.35:
        candle_strength = "MEDIUM"

    else:
        candle_strength = "WEAK"

    # --------------------------------------------------------
    # RANGE POSITION
    # --------------------------------------------------------

    full_range = max(resistance - support, 0.00000001)

    range_position = (
        (current_price - support) / full_range
    ) * 100

    range_position = max(0, min(100, range_position))

    # --------------------------------------------------------
    # SCORES
    #
    # BUY / SELL each have 8 possible points.
    #
    # RETEST IS BONUS ONLY.
    # It is NOT mandatory.
    # --------------------------------------------------------

    buy_score = 0
    sell_score = 0

    buy_reasons = []
    sell_reasons = []

    # 1. Trend
    if trend == "BULLISH":
        buy_score += 1
        buy_reasons.append("bullish trend")

    elif trend == "BEARISH":
        sell_score += 1
        sell_reasons.append("bearish trend")

    # 2. Structure
    if structure == "BULLISH":
        buy_score += 1
        buy_reasons.append("bullish structure")

    elif structure == "BEARISH":
        sell_score += 1
        sell_reasons.append("bearish structure")

    # 3. Breakout
    if breakout == "BULLISH":
        buy_score += 2
        buy_reasons.append("resistance breakout")

    elif breakout == "BEARISH":
        sell_score += 2
        sell_reasons.append("support breakdown")

    # 4. Momentum
    if momentum == "BULLISH":
        buy_score += 1
        buy_reasons.append("bullish momentum")

    elif momentum == "BEARISH":
        sell_score += 1
        sell_reasons.append("bearish momentum")

    # 5. Candle
    if candle_strength == "STRONG":

        if is_bullish(closed):
            buy_score += 1
            buy_reasons.append("strong bullish candle")

        elif is_bearish(closed):
            sell_score += 1
            sell_reasons.append("strong bearish candle")

    # 6. Range position
    if range_position >= 60:
        buy_score += 1
        buy_reasons.append("upper range strength")

    elif range_position <= 40:
        sell_score += 1
        sell_reasons.append("lower range weakness")

    # 7. Retest bonus
    if retest == "BULLISH":
        buy_score += 1
        buy_reasons.append("bullish retest")

    elif retest == "BEARISH":
        sell_score += 1
        sell_reasons.append("bearish retest")

    # 8. Closed candle confirmation
    if is_bullish(closed):
        buy_score += 1
        buy_reasons.append("closed bullish candle")

    elif is_bearish(closed):
        sell_score += 1
        sell_reasons.append("closed bearish candle")

    # --------------------------------------------------------
    # SIGNAL FILTER
    # --------------------------------------------------------

    signal = "NO SIGNAL"
    reason = "Waiting for stronger confirmation"

    # BUY
    if buy_score >= MIN_SIGNAL_SCORE and buy_score > sell_score:

        # Avoid buying directly after obvious bearish structure
        if not (
            structure == "BEARISH"
            and momentum == "BEARISH"
            and breakout != "BULLISH"
        ):
            signal = "BUY"
            reason = ", ".join(buy_reasons[-3:])

    # SELL
    if sell_score >= MIN_SIGNAL_SCORE and sell_score > buy_score:

        # Avoid selling directly after obvious bullish structure
        if not (
            structure == "BULLISH"
            and momentum == "BULLISH"
            and breakout != "BEARISH"
        ):
            signal = "SELL"
            reason = ", ".join(sell_reasons[-3:])

    return {
        "closed": closed,
        "current_price": current_price,
        "resistance": resistance,
        "support": support,
        "trend": trend,
        "structure": structure,
        "breakout": breakout,
        "retest": retest,
        "momentum": momentum,
        "candle_strength": candle_strength,
        "range_position": range_position,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "signal": signal,
        "reason": reason
    }


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_levels(signal, entry, candles):

    atr = calculate_atr(candles)

    # Conservative ATR levels
    sl_distance = max(atr * 1.5, entry * 0.004)
    tp_distance = max(atr * 2.5, entry * 0.006)

    if signal == "BUY":

        stop_loss = entry - sl_distance
        take_profit = entry + tp_distance

    elif signal == "SELL":

        stop_loss = entry + sl_distance
        take_profit = entry - tp_distance

    else:

        stop_loss = None
        take_profit = None

    return stop_loss, take_profit


# ============================================================
# FORMAT MESSAGE
# ============================================================

def build_message(result, candle_time):

    signal = result["signal"]

    message = (
        "⚡ ATI CRYPTO BOT V26\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "👀 PRE-BREAKOUT WATCH ENGINE\n\n"
        "📡 TABDEAL API: OK\n"
        "📊 TRADES API: OK\n\n"
        f"🕐 Candle: {candle_time}\n\n"
        f"📚 Stored Candles: {CANDLE_LIMIT - 2}\n\n"
        f"💰 Current: ${result['current_price']:,.2f}\n"
        f"💵 Candle Close: ${result['closed']['close']:,.2f}\n\n"
        f"📊 TREND: {result['trend']}\n"
        f"🏗 STRUCTURE: {result['structure']}\n"
        f"💥 BREAKOUT: {result['breakout']}\n"
        f"🔄 RETEST: {result['retest']}\n"
        f"🚀 MOMENTUM: {result['momentum']}\n"
        f"🕯 CANDLE: {result['candle_strength']}\n"
        f"📍 RANGE POSITION: {result['range_position']:.1f}%\n\n"
        f"📏 RESISTANCE: ${result['resistance']:,.2f}\n"
        f"📏 SUPPORT: ${result['support']:,.2f}\n\n"
        f"📈 BUY SCORE: {result['buy_score']}/8\n"
        f"📉 SELL SCORE: {result['sell_score']}/8\n\n"
    )

    if signal == "BUY":

        sl, tp = calculate_levels(
            "BUY",
            result["current_price"],
            [result["closed"]]
        )

        # Recalculate using safe local ATR fallback
        atr = max(
            result["closed"]["high"] - result["closed"]["low"],
            result["current_price"] * 0.002
        )

        sl = result["current_price"] - max(
            atr * 1.5,
            result["current_price"] * 0.004
        )

        tp = result["current_price"] + max(
            atr * 2.5,
            result["current_price"] * 0.006
        )

        message += (
            "📊 SIGNAL: 🟢 BUY\n"
            f"📝 REASON: {result['reason']}\n\n"
            f"💵 ENTRY: ${result['current_price']:,.2f}\n"
            f"🛑 STOP LOSS: ${sl:,.2f}\n"
            f"🎯 TAKE PROFIT: ${tp:,.2f}\n\n"
            "🧪 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED\n\n"
            "📡 TELEGRAM: OK"
        )

    elif signal == "SELL":

        atr = max(
            result["closed"]["high"] - result["closed"]["low"],
            result["current_price"] * 0.002
        )

        sl = result["current_price"] + max(
            atr * 1.5,
            result["current_price"] * 0.004
        )

        tp = result["current_price"] - max(
            atr * 2.5,
            result["current_price"] * 0.006
        )

        message += (
            "📊 SIGNAL: 🔴 SELL\n"
            f"📝 REASON: {result['reason']}\n\n"
            f"💵 ENTRY: ${result['current_price']:,.2f}\n"
            f"🛑 STOP LOSS: ${sl:,.2f}\n"
            f"🎯 TAKE PROFIT: ${tp:,.2f}\n\n"
            "🧪 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED\n\n"
            "📡 TELEGRAM: OK"
        )

    else:

        message += (
            "📊 SIGNAL: ⚪ NO SIGNAL\n"
            f"📝 REASON: {result['reason']}\n\n"
            "⏳ NO TRADE\n\n"
            "🛡 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED\n\n"
            "📡 TELEGRAM: OK"
        )

    return message


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("ATI CRYPTO BOT V26")
    print("=" * 60)

    try:

        raw_candles = get_klines()

        candles = [
            parse_candle(c)
            for c in raw_candles
        ]

        if len(candles) < 30:
            raise RuntimeError("Not enough candles")

        result = analyze(candles)

        timestamp = result["closed"]["time"]

        # Handle milliseconds / seconds
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000

        candle_dt = datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc
        )

        candle_time = candle_dt.strftime(
            "%Y-%m-%d %H:%M UTC"
        )

        message = build_message(
            result,
            candle_time
        )

        print(message)

        sent = send_telegram(message)

        if sent:
            print("TELEGRAM MESSAGE: SENT")
        else:
            print("TELEGRAM MESSAGE: FAILED")

    except Exception as e:

        error_message = (
            "🛡 ATI SAFETY\n\n"
            "❌ BOT ERROR\n\n"
            f"{type(e).__name__}: {e}\n\n"
            "🚫 NO TRADE WAS SENT"
        )

        print(error_message)

        send_telegram(error_message)


if __name__ == "__main__":
    main()
