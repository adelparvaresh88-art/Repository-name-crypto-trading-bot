import os
import requests
from datetime import datetime, timezone

# =========================================================
# ATI CRYPTO BOT V28
# BREAKOUT + RETEST CONFIRMATION ENGINE
# BTCUSDT - 5m
# PAPER / TEST ONLY
# REAL TRADING DISABLED
# =========================================================

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"

TRADE_LIMIT = 1000
MIN_CANDLES = 35

BREAKOUT_LOOKBACK = 7
MOMENTUM_LOOKBACK = 6

# Momentum is now a SUPPORTING condition, NOT mandatory
MOMENTUM_THRESHOLD = 0.10

# Breakout buffer
BREAKOUT_BUFFER = 0.03

# Retest tolerance
RETEST_TOLERANCE = 0.25

# Minimum SL / TP
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
        response = requests.post(
            url,
            json=payload,
            timeout=20
        )

        response.raise_for_status()

        return True

    except Exception as e:

        print("Telegram error:", e)

        return False


# =========================================================
# GET TABDEAL TRADES
# =========================================================

def get_trades():

    url = f"{BASE_URL}/r/api/v1/trades"

    params = {
        "symbol": SYMBOL,
        "limit": TRADE_LIMIT
    }

    response = requests.get(
        url,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):

        if "data" in data:
            data = data["data"]

        elif "result" in data:
            data = data["result"]

    if not isinstance(data, list):

        raise RuntimeError(
            "Unexpected Tabdeal trades response"
        )

    return data


# =========================================================
# PARSE TRADE
# =========================================================

def parse_trade(trade):

    price = None
    timestamp = None

    if isinstance(trade, dict):

        for key in [
            "price",
            "p"
        ]:

            if key in trade:

                try:
                    price = float(trade[key])
                    break

                except:
                    pass

        for key in [
            "timestamp",
            "time",
            "T",
            "created_at"
        ]:

            if key in trade:

                try:
                    timestamp = int(
                        float(trade[key])
                    )

                    break

                except:
                    pass

    elif isinstance(trade, list):

        if len(trade) >= 2:

            try:

                price = float(trade[0])
                timestamp = int(
                    float(trade[1])
                )

            except:
                pass

    if price is None or timestamp is None:
        return None

    # Seconds -> milliseconds
    if timestamp < 10_000_000_000:
        timestamp *= 1000

    return price, timestamp


# =========================================================
# BUILD 5 MINUTE CANDLES
# =========================================================

def build_5m_candles(trades):

    buckets = {}

    for raw_trade in trades:

        parsed = parse_trade(raw_trade)

        if not parsed:
            continue

        price, timestamp = parsed

        bucket = (
            timestamp // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price
            }

        else:

            candle = buckets[bucket]

            if price > candle["high"]:
                candle["high"] = price

            if price < candle["low"]:
                candle["low"] = price

            candle["close"] = price

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    # Remove currently forming candle
    if candles:

        now_ms = int(
            datetime.now(
                timezone.utc
            ).timestamp() * 1000
        )

        current_bucket = (
            now_ms // 300000
        ) * 300000

        candles = [
            candle
            for candle in candles
            if candle["time"] < current_bucket
        ]

    return candles


# =========================================================
# PERCENT CHANGE
# =========================================================

def percent_change(old, new):

    if old == 0:
        return 0

    return (
        (new - old) / old
    ) * 100


# =========================================================
# CANDLE DIRECTION
# =========================================================

def candle_direction(candle):

    if candle["close"] > candle["open"]:
        return "BULLISH"

    if candle["close"] < candle["open"]:
        return "BEARISH"

    return "NEUTRAL"


# =========================================================
# CANDLE STRENGTH
# =========================================================

def candle_strength(candle):

    candle_range = (
        candle["high"] -
        candle["low"]
    )

    if candle_range <= 0:
        return "WEAK"

    body = abs(
        candle["close"] -
        candle["open"]
    )

    ratio = body / candle_range

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

    # -----------------------------------------------------
    # SUPPORT / RESISTANCE
    # -----------------------------------------------------

    recent = candles[-24:]

    support = min(
        candle["low"]
        for candle in recent
    )

    resistance = max(
        candle["high"]
        for candle in recent
    )

    # -----------------------------------------------------
    # TREND
    # -----------------------------------------------------

    first_10 = candles[-20:-10]
    last_10 = candles[-10:]

    avg_first = (
        sum(
            candle["close"]
            for candle in first_10
        )
        / len(first_10)
    )

    avg_last = (
        sum(
            candle["close"]
            for candle in last_10
        )
        / len(last_10)
    )

    trend_change = percent_change(
        avg_first,
        avg_last
    )

    if trend_change > 0.20:

        trend = "BULLISH"

    elif trend_change < -0.20:

        trend = "BEARISH"

    else:

        trend = "SIDEWAYS"

    # -----------------------------------------------------
    # STRUCTURE
    # -----------------------------------------------------

    structure_candles = candles[-12:]

    first_half = structure_candles[:6]
    second_half = structure_candles[6:]

    first_high = max(
        candle["high"]
        for candle in first_half
    )

    second_high = max(
        candle["high"]
        for candle in second_half
    )

    first_low = min(
        candle["low"]
        for candle in first_half
    )

    second_low = min(
        candle["low"]
        for candle in second_half
    )

    if (
        second_high > first_high
        and
        second_low > first_low
    ):

        structure = "BULLISH"

    elif (
        second_high < first_high
        and
        second_low < first_low
    ):

        structure = "BEARISH"

    else:

        structure = "MIXED"

    # -----------------------------------------------------
    # BREAKOUT LEVELS
    # -----------------------------------------------------

    previous = candles[
        -(BREAKOUT_LOOKBACK + 1):-1
    ]

    previous_high = max(
        candle["high"]
        for candle in previous
    )

    previous_low = min(
        candle["low"]
        for candle in previous
    )

    # -----------------------------------------------------
    # BREAKOUT
    # -----------------------------------------------------

    bullish_breakout = (
        last["close"]
        >
        previous_high *
        (1 + BREAKOUT_BUFFER / 100)
    )

    bearish_breakout = (
        last["close"]
        <
        previous_low *
        (1 - BREAKOUT_BUFFER / 100)
    )

    if bullish_breakout:

        breakout = "BULLISH"

    elif bearish_breakout:

        breakout = "BEARISH"

    else:

        breakout = "NONE"

    # -----------------------------------------------------
    # RETEST
    # -----------------------------------------------------

    retest = "NONE"

    if bullish_breakout:

        distance = (
            abs(
                last["low"] -
                previous_high
            )
            /
            previous_high
        ) * 100

        if distance <= RETEST_TOLERANCE:

            retest = "BULLISH"

    elif bearish_breakout:

        distance = (
            abs(
                last["high"] -
                previous_low
            )
            /
            previous_low
        ) * 100

        if distance <= RETEST_TOLERANCE:

            retest = "BEARISH"

    # -----------------------------------------------------
    # MOMENTUM
    # -----------------------------------------------------

    momentum_start = candles[
        -MOMENTUM_LOOKBACK - 1
    ]["close"]

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

    direction = candle_direction(
        last
    )

    strength = candle_strength(
        last
    )

    # -----------------------------------------------------
    # RANGE POSITION
    # -----------------------------------------------------

    total_range = (
        resistance -
        support
    )

    if total_range > 0:

        range_position = (
            (
                last["close"] -
                support
            )
            /
            total_range
        ) * 100

    else:

        range_position = 50

    # =====================================================
    # V28 SIGNAL ENGINE
    # =====================================================

    buy_conditions = 0
    sell_conditions = 0

    # -----------------------------------------------------
    # BUY CONDITIONS
    # -----------------------------------------------------

    if bullish_breakout:
        buy_conditions += 1

    if retest == "BULLISH":
        buy_conditions += 1

    if direction == "BULLISH":
        buy_conditions += 1

    if strength in [
        "STRONG",
        "MEDIUM"
    ]:
        buy_conditions += 1

    if momentum == "BULLISH":
        buy_conditions += 1

    # -----------------------------------------------------
    # SELL CONDITIONS
    # -----------------------------------------------------

    if bearish_breakout:
        sell_conditions += 1

    if retest == "BEARISH":
        sell_conditions += 1

    if direction == "BEARISH":
        sell_conditions += 1

    if strength in [
        "STRONG",
        "MEDIUM"
    ]:
        sell_conditions += 1

    if momentum == "BEARISH":
        sell_conditions += 1

    # -----------------------------------------------------
    # FINAL SIGNAL
    # -----------------------------------------------------

    signal = "NO SIGNAL"

    reason = (
        "Waiting for breakout + "
        "closed candle confirmation"
    )

    # =====================================================
    # STRONG BUY
    # =====================================================

    if (
        bullish_breakout
        and
        direction == "BULLISH"
        and
        strength in [
            "STRONG",
            "MEDIUM"
        ]
        and
        (
            retest == "BULLISH"
            or
            momentum == "BULLISH"
        )
    ):

        signal = "BUY"

        if retest == "BULLISH":

            reason = (
                "Bullish breakout + "
                "bullish retest + "
                "confirmed candle"
            )

        else:

            reason = (
                "Bullish breakout + "
                "bullish momentum + "
                "confirmed candle"
            )

    # =====================================================
    # STRONG SELL
    # =====================================================

    elif (
        bearish_breakout
        and
        direction == "BEARISH"
        and
        strength in [
            "STRONG",
            "MEDIUM"
        ]
        and
        (
            retest == "BEARISH"
            or
            momentum == "BEARISH"
        )
    ):

        signal = "SELL"

        if retest == "BEARISH":

            reason = (
                "Bearish breakout + "
                "bearish retest + "
                "confirmed candle"
            )

        else:

            reason = (
                "Bearish breakout + "
                "bearish momentum + "
                "confirmed candle"
            )

    # =====================================================
    # PRE-BREAKOUT WATCH
    # =====================================================

    elif (
        not bullish_breakout
        and
        not bearish_breakout
        and
        momentum == "BULLISH"
        and
        direction == "BULLISH"
        and
        strength in [
            "STRONG",
            "MEDIUM"
        ]
    ):

        signal = "WATCH BUY"

        reason = (
            "Bullish pressure before breakout"
        )

    elif (
        not bullish_breakout
        and
        not bearish_breakout
        and
        momentum == "BEARISH"
        and
        direction == "BEARISH"
        and
        strength in [
            "STRONG",
            "MEDIUM"
        ]
    ):

        signal = "WATCH SELL"

        reason = (
            "Bearish pressure before breakdown"
        )

    return {
        "last": last,
        "trend": trend,
        "structure": structure,
        "breakout": breakout,
        "retest": retest,
        "momentum": momentum,
        "momentum_change": momentum_change,
        "direction": direction,
        "strength": strength,
        "range_position": range_position,
        "resistance": resistance,
        "support": support,
        "buy_conditions": buy_conditions,
        "sell_conditions": sell_conditions,
        "signal": signal,
        "reason": reason
    }


# =========================================================
# SL / TP
# =========================================================

def calculate_levels(
    price,
    signal,
    candles
):

    recent = candles[-14:]

    ranges = [
        candle["high"] -
        candle["low"]
        for candle in recent
        if candle["high"] >
        candle["low"]
    ]

    if ranges:

        atr = (
            sum(ranges) /
            len(ranges)
        )

    else:

        atr = price * 0.004

    sl_distance = max(
        atr * 1.5,
        price *
        (SL_PERCENT_MIN / 100)
    )

    tp_distance = max(
        atr * 2.5,
        price *
        (TP_PERCENT_MIN / 100)
    )

    if signal == "BUY":

        sl = price - sl_distance
        tp = price + tp_distance

    else:

        sl = price + sl_distance
        tp = price - tp_distance

    return sl, tp


# =========================================================
# TELEGRAM MESSAGE
# =========================================================

def create_message(
    candles,
    analysis
):

    last = analysis["last"]

    price = last["close"]

    signal = analysis["signal"]

    candle_time = datetime.fromtimestamp(
        last["time"] / 1000,
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    message = f"""
⚡ ATI CRYPTO BOT V28

₿ BTC/USDT
⏱ Timeframe: 5m
✅ CLOSED CANDLE
🚀 BREAKOUT + RETEST ENGINE

📡 TABDEAL API: OK
📊 TRADES API: OK

🕐 Candle:
{candle_time}

📚 Stored Candles: {len(candles)}

💰 Current: ${price:,.2f}
💵 Candle Close: ${price:,.2f}

📊 TREND: {analysis["trend"]}
🏗 STRUCTURE: {analysis["structure"]}
💥 BREAKOUT: {analysis["breakout"]}
🔄 RETEST: {analysis["retest"]}
🚀 MOMENTUM: {analysis["momentum"]}
🕯️ CANDLE:
{analysis["direction"]} / {analysis["strength"]}

📈 MOMENTUM MOVE:
{analysis["momentum_change"]:.3f}%

📍 RANGE POSITION:
{analysis["range_position"]:.1f}%

📏 RESISTANCE:
${analysis["resistance"]:,.2f}

📏 SUPPORT:
${analysis["support"]:,.2f}

📈 BUY CONDITIONS:
{analysis["buy_conditions"]}/5

📉 SELL CONDITIONS:
{analysis["sell_conditions"]}/5

📊 SIGNAL:
"""

    # =====================================================
    # BUY
    # =====================================================

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

📐 RISK / REWARD:
Approx. 1 : 1.67

⚠️ PAPER TRADE ONLY
"""

    # =====================================================
    # SELL
    # =====================================================

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

📐 RISK / REWARD:
Approx. 1 : 1.67

⚠️ PAPER TRADE ONLY
"""

    # =====================================================
    # WATCH BUY
    # =====================================================

    elif signal == "WATCH BUY":

        message += f"""
🟡 WATCH BUY

📝 REASON:
{analysis["reason"]}

⏳ Waiting for bullish breakout
🚫 NO TRADE
"""

    # =====================================================
    # WATCH SELL
    # =====================================================

    elif signal == "WATCH SELL":

        message += f"""
🟠 WATCH SELL

📝 REASON:
{analysis["reason"]}

⏳ Waiting for bearish breakdown
🚫 NO TRADE
"""

    # =====================================================
    # NO SIGNAL
    # =====================================================

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

        # -------------------------------------------------
        # GET TRADES
        # -------------------------------------------------

        trades = get_trades()

        if not trades:

            raise RuntimeError(
                "Tabdeal returned no trades"
            )

        # -------------------------------------------------
        # BUILD CANDLES
        # -------------------------------------------------

        candles = build_5m_candles(
            trades
        )

        # -------------------------------------------------
        # ANALYZE
        # -------------------------------------------------

        analysis = analyze(
            candles
        )

        # -------------------------------------------------
        # CREATE MESSAGE
        # -------------------------------------------------

        message = create_message(
            candles,
            analysis
        )

        print(message)

        # -------------------------------------------------
        # SEND TELEGRAM
        # -------------------------------------------------

        send_telegram(
            message
        )

    except Exception as e:

        error_message = f"""
🛡 ATI SAFETY

❌ BOT ERROR

{type(e).__name__}: {e}

🚫 NO TRADE

🛡 REAL TRADING DISABLED
"""

        print(error_message)

        send_telegram(
            error_message
        )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
