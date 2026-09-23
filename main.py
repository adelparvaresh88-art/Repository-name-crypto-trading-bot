import os
import requests
from datetime import datetime, timezone

# ============================================================
# ATI CRYPTO BOT V14
# TABDEAL PUBLIC API
# 5M CLOSED CANDLE
# PRECISION SIGNAL ENGINE
# PAPER / TEST ONLY
# REAL TRADING DISABLED
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"
TIMEFRAME_MINUTES = 5

TRADES_LIMIT = 1000
TIMEOUT = 15

# Strong signal threshold
MIN_SCORE = 4

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN missing")
        return False

    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID missing")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=TIMEOUT
        )

        if response.status_code == 200:
            print("✅ Telegram OK")
            return True

        print("❌ Telegram error:", response.text)
        return False

    except Exception as e:
        print("❌ Telegram exception:", e)
        return False


# ============================================================
# TABDEAL CURRENT PRICE
# ============================================================

def get_current_price():

    url = f"{BASE_URL}/r/api/v1/depth"

    params = {
        "symbol": SYMBOL,
        "limit": 5
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=TIMEOUT
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

    except Exception as e:

        print("❌ Price API error:", e)
        return None


# ============================================================
# TABDEAL RECENT TRADES
# ============================================================

def get_trades():

    url = f"{BASE_URL}/r/api/v1/trades"

    params = {
        "symbol": SYMBOL,
        "limit": TRADES_LIMIT
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, list):
            return []

        return data

    except Exception as e:

        print("❌ Trades API error:", e)
        return []


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_5m_candles(trades):

    candles = {}

    bucket_size = TIMEFRAME_MINUTES * 60 * 1000

    for trade in trades:

        try:

            price = float(trade["price"])
            quantity = float(trade.get("qty", 0))
            timestamp = int(trade["time"])

        except (KeyError, TypeError, ValueError):

            continue

        bucket = (
            timestamp // bucket_size
        ) * bucket_size

        if bucket not in candles:

            candles[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": quantity
            }

        else:

            candle = candles[bucket]

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

    result = list(candles.values())

    result.sort(
        key=lambda candle: candle["time"]
    )

    return result


# ============================================================
# CLOSED CANDLES
# ============================================================

def get_closed_candles(candles):

    now_ms = int(
        datetime.now(timezone.utc).timestamp() * 1000
    )

    bucket_size = TIMEFRAME_MINUTES * 60 * 1000

    current_bucket = (
        now_ms // bucket_size
    ) * bucket_size

    return [
        candle
        for candle in candles
        if candle["time"] < current_bucket
    ]


# ============================================================
# CANDLE FUNCTIONS
# ============================================================

def candle_range(c):

    return max(
        c["high"] - c["low"],
        0.00000001
    )


def candle_body(c):

    return abs(
        c["close"] - c["open"]
    )


def body_ratio(c):

    return (
        candle_body(c)
        / candle_range(c)
    )


def upper_wick(c):

    return (
        c["high"]
        - max(c["open"], c["close"])
    )


def lower_wick(c):

    return (
        min(c["open"], c["close"])
        - c["low"]
    )


def is_bullish(c):

    return c["close"] > c["open"]


def is_bearish(c):

    return c["close"] < c["open"]


# ============================================================
# SIMPLE MOVING AVERAGE
# Used internally only for trend calculation.
# No indicator is displayed on Telegram.
# ============================================================

def sma(candles, length):

    if len(candles) < length:
        return None

    values = [
        c["close"]
        for c in candles[-length:]
    ]

    return sum(values) / len(values)


# ============================================================
# V14 PRECISION SIGNAL ENGINE
# ============================================================

def calculate_signal(candles):

    if len(candles) < 12:

        return {
            "signal": "NO SIGNAL",
            "buy": 0,
            "sell": 0,
            "trend": "UNKNOWN",
            "reason": "Not enough candles"
        }

    c1 = candles[-1]
    c2 = candles[-2]
    c3 = candles[-3]
    c4 = candles[-4]
    c5 = candles[-5]

    buy = 0
    sell = 0

    # ========================================================
    # 1. TREND
    # ========================================================

    sma5 = sma(candles, 5)
    sma10 = sma(candles, 10)

    trend = "SIDEWAYS"

    if sma5 is not None and sma10 is not None:

        if (
            c1["close"] > sma5
            and sma5 > sma10
        ):
            buy += 1
            trend = "UP"

        elif (
            c1["close"] < sma5
            and sma5 < sma10
        ):
            sell += 1
            trend = "DOWN"

    # ========================================================
    # 2. PRICE STRUCTURE
    # Higher High + Higher Low
    # Lower High + Lower Low
    # ========================================================

    higher_high = (
        c1["high"] > c2["high"]
        and c2["high"] >= c3["high"]
    )

    higher_low = (
        c1["low"] > c2["low"]
        and c2["low"] >= c3["low"]
    )

    lower_high = (
        c1["high"] < c2["high"]
        and c2["high"] <= c3["high"]
    )

    lower_low = (
        c1["low"] < c2["low"]
        and c2["low"] <= c3["low"]
    )

    if higher_high and higher_low:
        buy += 1

    if lower_high and lower_low:
        sell += 1

    # ========================================================
    # 3. MOMENTUM
    # ========================================================

    bullish_momentum = (
        c1["close"] > c2["close"]
        and c2["close"] > c3["close"]
        and c3["close"] >= c4["close"]
    )

    bearish_momentum = (
        c1["close"] < c2["close"]
        and c2["close"] < c3["close"]
        and c3["close"] <= c4["close"]
    )

    if bullish_momentum:
        buy += 1

    if bearish_momentum:
        sell += 1

    # ========================================================
    # 4. BREAKOUT
    # ========================================================

    previous_high = max(
        c2["high"],
        c3["high"],
        c4["high"],
        c5["high"]
    )

    previous_low = min(
        c2["low"],
        c3["low"],
        c4["low"],
        c5["low"]
    )

    bullish_breakout = (
        c1["close"] > previous_high
    )

    bearish_breakout = (
        c1["close"] < previous_low
    )

    if bullish_breakout:
        buy += 1

    if bearish_breakout:
        sell += 1

    # ========================================================
    # 5. CANDLE POWER
    # ========================================================

    ratio = body_ratio(c1)

    bullish_power = (
        is_bullish(c1)
        and ratio >= 0.60
        and lower_wick(c1) <= candle_body(c1) * 0.80
    )

    bearish_power = (
        is_bearish(c1)
        and ratio >= 0.60
        and upper_wick(c1) <= candle_body(c1) * 0.80
    )

    if bullish_power:
        buy += 1

    if bearish_power:
        sell += 1

    # ========================================================
    # FINAL DECISION
    # ========================================================

    signal = "NO SIGNAL"

    if buy >= MIN_SCORE and buy > sell:

        signal = "BUY"

    elif sell >= MIN_SCORE and sell > buy:

        signal = "SELL"

    return {
        "signal": signal,
        "buy": buy,
        "sell": sell,
        "trend": trend,
        "ratio": ratio
    }


# ============================================================
# STOP LOSS / TAKE PROFIT
# ============================================================

def calculate_sl_tp(signal, candles):

    entry = candles[-1]["close"]

    recent = candles[-5:]

    recent_high = max(
        c["high"]
        for c in recent
    )

    recent_low = min(
        c["low"]
        for c in recent
    )

    if signal == "BUY":

        risk = entry - recent_low

        if risk <= 0:
            risk = entry * 0.004

        stop_loss = recent_low

        take_profit = (
            entry + risk * 2.0
        )

        return (
            entry,
            stop_loss,
            take_profit
        )

    if signal == "SELL":

        risk = recent_high - entry

        if risk <= 0:
            risk = entry * 0.004

        stop_loss = recent_high

        take_profit = (
            entry - risk * 2.0
        )

        return (
            entry,
            stop_loss,
            take_profit
        )

    return (
        entry,
        None,
        None
    )


# ============================================================
# FORMAT
# ============================================================

def fmt(value):

    if value is None:
        return "-"

    return f"${value:,.2f}"


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("ATI CRYPTO BOT V14")
    print("PRECISION 5M SIGNAL ENGINE")
    print("PAPER / TEST")
    print("=" * 60)

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    current_price = get_current_price()

    if current_price is None:

        send_telegram(
            """🛡 ATI SAFETY

❌ BTCUSDT PRICE ERROR

Tabdeal price API failed.

🛑 NO TRADE

🛡 PAPER / TEST
"""
        )

        return

    # --------------------------------------------------------
    # TRADES
    # --------------------------------------------------------

    trades = get_trades()

    if not trades:

        send_telegram(
            """🛡 ATI SAFETY

❌ TRADES API ERROR

Tabdeal trades API failed.

🛑 NO TRADE

🛡 PAPER / TEST
"""
        )

        return

    # --------------------------------------------------------
    # CANDLES
    # --------------------------------------------------------

    candles = build_5m_candles(
        trades
    )

    closed = get_closed_candles(
        candles
    )

    print("Trades:", len(trades))
    print("Candles:", len(candles))
    print("Closed:", len(closed))

    if len(closed) < 12:

        send_telegram(
            f"""⚡ ATI CRYPTO BOT V14

₿ BTC/USDT
⏱ Timeframe: 5m

📡 TABDEAL API: OK
📊 TRADES API: OK

💰 Current: {fmt(current_price)}

📊 CLOSED CANDLES: {len(closed)}

⏳ WAITING FOR MORE DATA

🛡 MODE: PAPER / TEST
🚫 REAL TRADING DISABLED
"""
        )

        return

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    result = calculate_signal(
        closed
    )

    signal = result["signal"]
    buy_score = result["buy"]
    sell_score = result["sell"]
    trend = result["trend"]

    last = closed[-1]

    candle_time = datetime.fromtimestamp(
        last["time"] / 1000,
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    entry, sl, tp = calculate_sl_tp(
        signal,
        closed
    )

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    message = f"""⚡ ATI CRYPTO BOT V14

₿ BTC/USDT
⏱ Timeframe: 5m
✅ CLOSED CANDLE
🧠 PRECISION SIGNAL ENGINE

📡 TABDEAL API: OK
📊 TRADES API: OK

🕐 Candle: {candle_time}

💰 Current: {fmt(current_price)}
💵 Candle Close: {fmt(entry)}

📊 TREND: {trend}

📈 BUY SCORE: {buy_score}/5
📉 SELL SCORE: {sell_score}/5

"""

    if signal == "BUY":

        message += f"""🟢 SIGNAL: BUY

💵 Entry: {fmt(entry)}
🛑 SL: {fmt(sl)}
🎯 TP: {fmt(tp)}

🔥 STRONG BUY
"""

    elif signal == "SELL":

        message += f"""🔴 SIGNAL: SELL

💵 Entry: {fmt(entry)}
🛑 SL: {fmt(sl)}
🎯 TP: {fmt(tp)}

🔥 STRONG SELL
"""

    else:

        message += """⚪ SIGNAL: NO SIGNAL

⏳ NO TRADE
"""

    message += """
🛡 MODE: PAPER / TEST
🚫 REAL TRADING DISABLED

📡 TELEGRAM: OK
"""

    print(message)

    send_telegram(message)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
