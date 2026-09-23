import os
import requests
from datetime import datetime, timezone

# ============================================================
# ATI CRYPTO BOT V13
# TABDEAL
# 5M CLOSED CANDLE
# STRONG SIGNAL ENGINE
# PAPER / TEST ONLY
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"
TIMEFRAME = 5

TRADES_LIMIT = 1000
TIMEOUT = 15

MIN_SCORE = 4

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram secrets missing")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        r = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=TIMEOUT
        )

        if r.status_code == 200:
            print("✅ Telegram OK")
            return True

        print("❌ Telegram:", r.text)
        return False

    except Exception as e:
        print("❌ Telegram error:", e)
        return False


# ============================================================
# CURRENT PRICE
# ============================================================

def get_price():

    url = f"{BASE_URL}/r/api/v1/depth"

    try:
        r = requests.get(
            url,
            params={
                "symbol": SYMBOL,
                "limit": 5
            },
            timeout=TIMEOUT
        )

        r.raise_for_status()

        data = r.json()

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if not bids or not asks:
            return None

        bid = float(bids[0][0])
        ask = float(asks[0][0])

        return (bid + ask) / 2

    except Exception as e:
        print("❌ Price error:", e)
        return None


# ============================================================
# RECENT TRADES
# ============================================================

def get_trades():

    url = f"{BASE_URL}/r/api/v1/trades"

    try:

        r = requests.get(
            url,
            params={
                "symbol": SYMBOL,
                "limit": TRADES_LIMIT
            },
            timeout=TIMEOUT
        )

        r.raise_for_status()

        data = r.json()

        if not isinstance(data, list):
            return []

        return data

    except Exception as e:
        print("❌ Trades error:", e)
        return []


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_candles(trades):

    candles = {}

    bucket_size = TIMEFRAME * 60 * 1000

    for trade in trades:

        try:
            price = float(trade["price"])
            qty = float(trade.get("qty", 0))
            timestamp = int(trade["time"])

        except (KeyError, TypeError, ValueError):
            continue

        bucket = (timestamp // bucket_size) * bucket_size

        if bucket not in candles:

            candles[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty
            }

        else:

            c = candles[bucket]

            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["close"] = price
            c["volume"] += qty

    result = list(candles.values())

    result.sort(key=lambda x: x["time"])

    return result


# ============================================================
# CLOSED CANDLES ONLY
# ============================================================

def closed_candles(candles):

    now = int(
        datetime.now(timezone.utc).timestamp() * 1000
    )

    bucket_size = TIMEFRAME * 60 * 1000

    current_bucket = (
        now // bucket_size
    ) * bucket_size

    return [
        c for c in candles
        if c["time"] < current_bucket
    ]


# ============================================================
# HELPERS
# ============================================================

def body(c):

    return abs(c["close"] - c["open"])


def candle_range(c):

    return max(
        c["high"] - c["low"],
        0.00000001
    )


def body_ratio(c):

    return body(c) / candle_range(c)


def bullish(c):

    return c["close"] > c["open"]


def bearish(c):

    return c["close"] < c["open"]


# ============================================================
# SIGNAL ENGINE V13
# ============================================================

def signal_engine(candles):

    if len(candles) < 8:

        return {
            "signal": "NO SIGNAL",
            "buy": 0,
            "sell": 0
        }

    c1 = candles[-1]
    c2 = candles[-2]
    c3 = candles[-3]
    c4 = candles[-4]
    c5 = candles[-5]

    buy = 0
    sell = 0

    # --------------------------------------------------------
    # 1. CANDLE DIRECTION
    # --------------------------------------------------------

    if bullish(c1):
        buy += 1

    elif bearish(c1):
        sell += 1

    # --------------------------------------------------------
    # 2. PRICE STRUCTURE
    # --------------------------------------------------------

    if (
        c1["high"] > c2["high"]
        and c1["low"] >= c2["low"]
    ):
        buy += 1

    if (
        c1["low"] < c2["low"]
        and c1["high"] <= c2["high"]
    ):
        sell += 1

    # --------------------------------------------------------
    # 3. MOMENTUM
    # --------------------------------------------------------

    if (
        c1["close"] > c2["close"]
        and c2["close"] > c3["close"]
    ):
        buy += 1

    if (
        c1["close"] < c2["close"]
        and c2["close"] < c3["close"]
    ):
        sell += 1

    # --------------------------------------------------------
    # 4. BREAKOUT
    # --------------------------------------------------------

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

    if c1["close"] > previous_high:
        buy += 1

    if c1["close"] < previous_low:
        sell += 1

    # --------------------------------------------------------
    # 5. STRONG BODY
    # --------------------------------------------------------

    strength = body_ratio(c1)

    if bullish(c1) and strength >= 0.55:
        buy += 1

    if bearish(c1) and strength >= 0.55:
        sell += 1

    # --------------------------------------------------------
    # FINAL FILTER
    # --------------------------------------------------------

    signal = "NO SIGNAL"

    if buy >= MIN_SCORE and buy > sell:
        signal = "BUY"

    elif sell >= MIN_SCORE and sell > buy:
        signal = "SELL"

    return {
        "signal": signal,
        "buy": buy,
        "sell": sell
    }


# ============================================================
# SL / TP
# ============================================================

def sl_tp(signal, candles):

    entry = candles[-1]["close"]

    recent = candles[-4:]

    high = max(
        c["high"] for c in recent
    )

    low = min(
        c["low"] for c in recent
    )

    if signal == "BUY":

        risk = entry - low

        if risk <= 0:
            risk = entry * 0.004

        sl = low
        tp = entry + (risk * 2)

        return entry, sl, tp

    if signal == "SELL":

        risk = high - entry

        if risk <= 0:
            risk = entry * 0.004

        sl = high
        tp = entry - (risk * 2)

        return entry, sl, tp

    return entry, None, None


# ============================================================
# PRICE FORMAT
# ============================================================

def price_text(value):

    if value is None:
        return "-"

    return f"${value:,.2f}"


# ============================================================
# MAIN
# ============================================================

def main():

    print("==========================================")
    print("ATI CRYPTO BOT V13")
    print("TABDEAL")
    print("5M CLOSED CANDLE")
    print("STRONG SIGNAL")
    print("PAPER / TEST")
    print("==========================================")

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    price = get_price()

    if price is None:

        telegram(
            """🛡 ATI SAFETY

❌ BTCUSDT PRICE ERROR

Tabdeal API could not return price.

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

        telegram(
            """🛡 ATI SAFETY

❌ TRADES API ERROR

Tabdeal trades could not be read.

🛑 NO TRADE

🛡 PAPER / TEST
"""
        )

        return

    # --------------------------------------------------------
    # CANDLES
    # --------------------------------------------------------

    candles = build_candles(trades)

    closed = closed_candles(candles)

    print("Trades:", len(trades))
    print("Candles:", len(candles))
    print("Closed:", len(closed))

    if len(closed) < 8:

        telegram(
            f"""⚡ ATI CRYPTO BOT V13

₿ BTC/USDT
⏱ Timeframe: 5m

✅ TABDEAL API: OK
✅ TRADES API: OK

💰 Price: {price_text(price)}

📊 CLOSED CANDLES: {len(closed)}

⏳ NOT ENOUGH DATA

🛡 PAPER / TEST
🚫 REAL TRADING DISABLED
"""
        )

        return

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    result = signal_engine(closed)

    signal = result["signal"]
    buy = result["buy"]
    sell = result["sell"]

    last = closed[-1]

    candle_time = datetime.fromtimestamp(
        last["time"] / 1000,
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    entry, sl, tp = sl_tp(
        signal,
        closed
    )

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    message = f"""⚡ ATI CRYPTO BOT V13

₿ BTC/USDT
⏱ Timeframe: 5m
✅ CLOSED CANDLE
💪 STRONG SIGNAL FILTER

📡 TABDEAL API: OK
📊 TRADES API: OK

🕐 Candle: {candle_time}

💰 Current: {price_text(price)}
💵 Candle Close: {price_text(entry)}

📈 BUY SCORE: {buy}/5
📉 SELL SCORE: {sell}/5

"""

    if signal == "BUY":

        message += f"""🟢 SIGNAL: BUY

💵 Entry: {price_text(entry)}
🛑 SL: {price_text(sl)}
🎯 TP: {price_text(tp)}

🔥 STRONG BUY
"""

    elif signal == "SELL":

        message += f"""🔴 SIGNAL: SELL

💵 Entry: {price_text(entry)}
🛑 SL: {price_text(sl)}
🎯 TP: {price_text(tp)}

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

    telegram(message)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
