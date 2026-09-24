import os
import requests
from datetime import datetime, timezone

# =========================================================
# ATI CRYPTO BOT V27
# PRE-BREAKOUT / BREAKOUT ENGINE
# BTCUSDT - 5m
# PAPER / TEST ONLY
# REAL TRADING DISABLED
# =========================================================

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"

TRADE_LIMIT = 1000
MIN_CANDLES = 35

# Signal settings
BREAKOUT_LOOKBACK = 7
MOMENTUM_LOOKBACK = 6

# Minimum movement required for momentum
MOMENTUM_THRESHOLD = 0.18

# Breakout tolerance
BREAKOUT_BUFFER = 0.03

# SL / TP
SL_PERCENT_MIN = 0.40
TP_PERCENT_MIN = 0.60

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM credentials missing")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        r = requests.post(url, json=payload, timeout=20)
        r.raise_for_status()
        return True
    except Exception as e:
        print("Telegram error:", e)
        return False


# =========================================================
# GET TRADES FROM TABDEAL
# =========================================================

def get_trades():
    url = f"{BASE_URL}/r/api/v1/trades"

    params = {
        "symbol": SYMBOL,
        "limit": TRADE_LIMIT
    }

    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()

    data = r.json()

    if isinstance(data, dict):
        if "data" in data:
            data = data["data"]
        elif "result" in data:
            data = data["result"]

    if not isinstance(data, list):
        raise RuntimeError("Unexpected Tabdeal trades response")

    return data


# =========================================================
# PARSE TRADE
# =========================================================

def parse_trade(t):
    price = None
    timestamp = None

    if isinstance(t, dict):

        for key in ["price", "p"]:
            if key in t:
                try:
                    price = float(t[key])
                    break
                except:
                    pass

        for key in ["timestamp", "time", "T", "created_at"]:
            if key in t:
                try:
                    timestamp = int(float(t[key]))
                    break
                except:
                    pass

    elif isinstance(t, list):
        if len(t) >= 2:
            try:
                price = float(t[0])
                timestamp = int(float(t[1]))
            except:
                pass

    if price is None or timestamp is None:
        return None

    # Detect seconds vs milliseconds
    if timestamp < 10_000_000_000:
        timestamp *= 1000

    return price, timestamp


# =========================================================
# BUILD 5M CANDLES
# =========================================================

def build_5m_candles(trades):

    buckets = {}

    for raw in trades:
        parsed = parse_trade(raw)

        if not parsed:
            continue

        price, timestamp = parsed

        bucket = (timestamp // 300000) * 300000

        if bucket not in buckets:
            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price
            }
        else:
            c = buckets[bucket]

            if price > c["high"]:
                c["high"] = price

            if price < c["low"]:
                c["low"] = price

            c["close"] = price

    candles = list(buckets.values())
    candles.sort(key=lambda x: x["time"])

    # Remove current forming candle
    if candles:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        current_bucket = (now_ms // 300000) * 300000

        candles = [
            c for c in candles
            if c["time"] < current_bucket
        ]

    return candles


# =========================================================
# HELPERS
# =========================================================

def percent_change(old, new):
    if old == 0:
        return 0

    return ((new - old) / old) * 100


def candle_direction(c):
    if c["close"] > c["open"]:
        return "BULLISH"

    if c["close"] < c["open"]:
        return "BEARISH"

    return "NEUTRAL"


def candle_strength(c):
    total_range = c["high"] - c["low"]

    if total_range <= 0:
        return "WEAK"

    body = abs(c["close"] - c["open"])
    ratio = body / total_range

    if ratio >= 0.65:
        return "STRONG"

    if ratio >= 0.35:
        return "MEDIUM"

    return "WEAK"


# =========================================================
# ANALYSIS
# =========================================================

def analyze(candles):

    if len(candles) < MIN_CANDLES:
        raise RuntimeError(
            f"Not enough closed candles: {len(candles)}"
        )

    last = candles[-1]

    recent = candles[-24:]

    support = min(c["low"] for c in recent)
    resistance = max(c["high"] for c in recent)

    # -----------------------------------------------------
    # TREND
    # -----------------------------------------------------

    first_10 = candles[-20:-10]
    last_10 = candles[-10:]

    avg_first = sum(c["close"] for c in first_10) / len(first_10)
    avg_last = sum(c["close"] for c in last_10) / len(last_10)

    trend_change = percent_change(avg_first, avg_last)

    if trend_change > 0.20:
        trend = "BULLISH"
    elif trend_change < -0.20:
        trend = "BEARISH"
    else:
        trend = "SIDEWAYS"

    # -----------------------------------------------------
    # STRUCTURE
    # -----------------------------------------------------

    half = candles[-12:]

    first_half = half[:6]
    second_half = half[6:]

    first_high = max(c["high"] for c in first_half)
    second_high = max(c["high"] for c in second_half)

    first_low = min(c["low"] for c in first_half)
    second_low = min(c["low"] for c in second_half)

    if second_high > first_high and second_low > first_low:
        structure = "BULLISH"

    elif second_high < first_high and second_low < first_low:
        structure = "BEARISH"

    else:
        structure = "MIXED"

    # -----------------------------------------------------
    # BREAKOUT
    # -----------------------------------------------------

    previous = candles[-(BREAKOUT_LOOKBACK + 1):-1]

    previous_high = max(c["high"] for c in previous)
    previous_low = min(c["low"] for c in previous)

    bullish_breakout = (
        last["close"] >
        previous_high * (1 + BREAKOUT_BUFFER / 100)
    )

    bearish_breakout = (
        last["close"] <
        previous_low * (1 - BREAKOUT_BUFFER / 100)
    )

    if bullish_breakout:
        breakout = "BULLISH"

    elif bearish_breakout:
        breakout = "BEARISH"

    else:
        breakout = "NONE"

    # -----------------------------------------------------
    # MOMENTUM
    # -----------------------------------------------------

    momentum_start = candles[-MOMENTUM_LOOKBACK - 1]["close"]
    momentum_change = percent_change(
        momentum_start,
        last["close"]
    )

    if momentum_change >= MOMENTUM_THRESHOLD:
        momentum = "BULLISH"

    elif momentum_change <= -MOMENTUM_THRESHOLD:
        momentum = "BEARISH"

    else:
        momentum = "NEUTRAL"

    # -----------------------------------------------------
    # CANDLE
    # -----------------------------------------------------

    direction = candle_direction(last)
    strength = candle_strength(last)

    # -----------------------------------------------------
    # RANGE POSITION
    # -----------------------------------------------------

    total_range = resistance - support

    if total_range > 0:
        range_position = (
            (last["close"] - support)
            / total_range
        ) * 100
    else:
        range_position = 50

    # -----------------------------------------------------
    # RETEST
    # -----------------------------------------------------

    retest = "NONE"

    if bullish_breakout:

        distance = abs(
            last["low"] - previous_high
        ) / previous_high * 100

        if distance <= 0.25:
            retest = "BULLISH"

    elif bearish_breakout:

        distance = abs(
            last["high"] - previous_low
        ) / previous_low * 100

        if distance <= 0.25:
            retest = "BEARISH"

    # =====================================================
    # NEW SIMPLE SIGNAL ENGINE
    # =====================================================

    signal = "NO SIGNAL"
    reason = "Waiting for breakout confirmation"

    # BUY:
    # 1. Closed candle above breakout
    # 2. Bullish momentum
    # 3. Bullish candle
    #
    # Retest is NOT mandatory.

    buy_conditions = 0

    if bullish_breakout:
        buy_conditions += 1

    if momentum == "BULLISH":
        buy_conditions += 1

    if direction == "BULLISH":
        buy_conditions += 1

    if strength in ["STRONG", "MEDIUM"]:
        buy_conditions += 1

    # SELL
    sell_conditions = 0

    if bearish_breakout:
        sell_conditions += 1

    if momentum == "BEARISH":
        sell_conditions += 1

    if direction == "BEARISH":
        sell_conditions += 1

    if strength in ["STRONG", "MEDIUM"]:
        sell_conditions += 1

    # -----------------------------------------------------
    # FINAL SIGNAL
    # -----------------------------------------------------

    if (
        bullish_breakout
        and momentum == "BULLISH"
        and direction == "BULLISH"
    ):
        signal = "BUY"
        reason = (
            "Bullish breakout + bullish momentum "
            "+ bullish closed candle"
        )

    elif (
        bearish_breakout
        and momentum == "BEARISH"
        and direction == "BEARISH"
    ):
        signal = "SELL"
        reason = (
            "Bearish breakout + bearish momentum "
            "+ bearish closed candle"
        )

    # -----------------------------------------------------
    # PRE-BREAKOUT WATCH
    # -----------------------------------------------------

    elif (
        not bullish_breakout
        and not bearish_breakout
        and momentum == "BULLISH"
        and direction == "BULLISH"
        and strength in ["STRONG", "MEDIUM"]
    ):
        signal = "WATCH BUY"
        reason = "Bullish pressure before breakout"

    elif (
        not bullish_breakout
        and not bearish_breakout
        and momentum == "BEARISH"
        and direction == "BEARISH"
        and strength in ["STRONG", "MEDIUM"]
    ):
        signal = "WATCH SELL"
        reason = "Bearish pressure before breakdown"

    return {
        "last": last,
        "trend": trend,
        "structure": structure,
        "breakout": breakout,
        "momentum": momentum,
        "direction": direction,
        "strength": strength,
        "range_position": range_position,
        "resistance": resistance,
        "support": support,
        "retest": retest,
        "buy_conditions": buy_conditions,
        "sell_conditions": sell_conditions,
        "signal": signal,
        "reason": reason,
        "momentum_change": momentum_change
    }


# =========================================================
# SL / TP
# =========================================================

def calculate_levels(price, signal, candles):

    recent = candles[-14:]

    ranges = [
        c["high"] - c["low"]
        for c in recent
        if c["high"] > c["low"]
    ]

    if ranges:
        atr = sum(ranges) / len(ranges)
    else:
        atr = price * 0.004

    sl_distance = max(
        atr * 1.5,
        price * (SL_PERCENT_MIN / 100)
    )

    tp_distance = max(
        atr * 2.5,
        price * (TP_PERCENT_MIN / 100)
    )

    if signal == "BUY":

        sl = price - sl_distance
        tp = price + tp_distance

    else:

        sl = price + sl_distance
        tp = price - tp_distance

    return sl, tp


# =========================================================
# MESSAGE
# =========================================================

def create_message(candles, analysis):

    last = analysis["last"]

    price = last["close"]

    signal = analysis["signal"]

    message = f"""
⚡ ATI CRYPTO BOT V27

₿ BTC/USDT
⏱ Timeframe: 5m
✅ CLOSED CANDLE
🚀 SIMPLE BREAKOUT ENGINE

📡 TABDEAL API: OK
📊 TRADES API: OK

🕐 Candle:
{datetime.fromtimestamp(
    last["time"] / 1000,
    timezone.utc
).strftime("%Y-%m-%d %H:%M UTC")}

📚 Stored Candles: {len(candles)}

💰 Current: ${price:,.2f}
💵 Candle Close: ${price:,.2f}

📊 TREND: {analysis["trend"]}
🏗 STRUCTURE: {analysis["structure"]}
💥 BREAKOUT: {analysis["breakout"]}
🔄 RETEST: {analysis["retest"]}
🚀 MOMENTUM: {analysis["momentum"]}
🕯 CANDLE: {analysis["direction"]} / {analysis["strength"]}

📈 MOMENTUM MOVE:
{analysis["momentum_change"]:.3f}%

📍 RANGE POSITION:
{analysis["range_position"]:.1f}%

📏 RESISTANCE:
${analysis["resistance"]:,.2f}

📏 SUPPORT:
${analysis["support"]:,.2f}

📊 BUY CONDITIONS:
{analysis["buy_conditions"]}/4

📊 SELL CONDITIONS:
{analysis["sell_conditions"]}/4

📊 SIGNAL:
"""

    if signal == "BUY":

        sl, tp = calculate_levels(
            price,
            "BUY",
            candles
        )

        message += f"""
🟢 BUY

📝 REASON:
{analysis["reason"]}

💰 ENTRY:
${price:,.2f}

🛑 STOP LOSS:
${sl:,.2f}

🎯 TAKE PROFIT:
${tp:,.2f}

📐 RISK/REWARD:
Approx. 1 : 1.67
"""

    elif signal == "SELL":

        sl, tp = calculate_levels(
            price,
            "SELL",
            candles
        )

        message += f"""
🔴 SELL

📝 REASON:
{analysis["reason"]}

💰 ENTRY:
${price:,.2f}

🛑 STOP LOSS:
${sl:,.2f}

🎯 TAKE PROFIT:
${tp:,.2f}

📐 RISK/REWARD:
Approx. 1 : 1.67
"""

    elif signal == "WATCH BUY":

        message += """
🟡 WATCH BUY

📝 REASON:
""" + analysis["reason"] + """

⏳ Waiting for bullish breakout.
🚫 NO TRADE
"""

    elif signal == "WATCH SELL":

        message += """
🟠 WATCH SELL

📝 REASON:
""" + analysis["reason"] + """

⏳ Waiting for bearish breakdown.
🚫 NO TRADE
"""

    else:

        message += f"""
⚪ NO SIGNAL

📝 REASON:
{analysis["reason"]}

⏳ NO TRADE
"""

    message += """

🛡 MODE: PAPER / TEST
🚫 REAL TRADING DISABLED

📡 TELEGRAM: OK
"""

    return message


# =========================================================
# MAIN
# =========================================================

def main():

    try:

        trades = get_trades()

        if not trades:
            raise RuntimeError(
                "Tabdeal returned no trades"
            )

        candles = build_5m_candles(trades)

        analysis = analyze(candles)

        message = create_message(
            candles,
            analysis
        )

        print(message)

        send_telegram(message)

    except Exception as e:

        error_message = f"""
🛡 ATI SAFETY

❌ BOT ERROR

{type(e).__name__}: {e}

🚫 NO TRADE
"""

        print(error_message)

        send_telegram(error_message)


if __name__ == "__main__":
    main()
