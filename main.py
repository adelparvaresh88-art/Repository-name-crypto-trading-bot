import os
import requests
from datetime import datetime, timezone

# ============================================================
# ATI CRYPTO BOT V12
# TABDEAL PUBLIC API
# 5 MINUTE CANDLES BUILT FROM RECENT TRADES
# PAPER / TEST ONLY
# REAL TRADING DISABLED
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"
TIMEFRAME_MINUTES = 5

TRADES_LIMIT = 1000
REQUEST_TIMEOUT = 15

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is missing")
        return False

    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID is missing")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            print("❌ Telegram error:", response.text)
            return False

        print("✅ Telegram message sent")
        return True

    except Exception as e:
        print("❌ Telegram connection error:", e)
        return False


# ============================================================
# TABDEAL TRADES
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
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, list):
            print("❌ Unexpected trades response")
            return []

        return data

    except Exception as e:
        print("❌ Tabdeal trades error:", e)
        return []


# ============================================================
# CURRENT PRICE
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
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if not bids or not asks:
            return None

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])

        return (best_bid + best_ask) / 2

    except Exception as e:
        print("❌ Price API error:", e)
        return None


# ============================================================
# BUILD 5 MINUTE CANDLES
# ============================================================

def build_5m_candles(trades):

    candles = {}

    for trade in trades:

        try:
            price = float(trade["price"])
            timestamp_ms = int(trade["time"])

        except (KeyError, TypeError, ValueError):
            continue

        # Convert milliseconds to 5-minute bucket
        bucket_ms = (
            timestamp_ms // (TIMEFRAME_MINUTES * 60 * 1000)
        ) * (TIMEFRAME_MINUTES * 60 * 1000)

        if bucket_ms not in candles:
            candles[bucket_ms] = {
                "time": bucket_ms,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0
            }

        candle = candles[bucket_ms]

        candle["high"] = max(candle["high"], price)
        candle["low"] = min(candle["low"], price)
        candle["close"] = price

        try:
            candle["volume"] += float(trade.get("qty", 0))
        except (TypeError, ValueError):
            pass

    result = list(candles.values())

    result.sort(key=lambda x: x["time"])

    return result


# ============================================================
# REMOVE CURRENT / OPEN CANDLE
# ============================================================

def get_closed_candles(candles):

    now_ms = int(
        datetime.now(timezone.utc).timestamp() * 1000
    )

    current_bucket = (
        now_ms // (TIMEFRAME_MINUTES * 60 * 1000)
    ) * (TIMEFRAME_MINUTES * 60 * 1000)

    closed = [
        candle
        for candle in candles
        if candle["time"] < current_bucket
    ]

    return closed


# ============================================================
# CANDLE HELPERS
# ============================================================

def candle_body(c):
    return abs(c["close"] - c["open"])


def candle_range(c):
    return max(c["high"] - c["low"], 0.00000001)


def bullish(c):
    return c["close"] > c["open"]


def bearish(c):
    return c["close"] < c["open"]


# ============================================================
# SIGNAL ENGINE
# ============================================================

def calculate_signal(candles):

    if len(candles) < 8:
        return {
            "signal": "NO SIGNAL",
            "buy_score": 0,
            "sell_score": 0,
            "reason": "Not enough closed candles"
        }

    c1 = candles[-1]
    c2 = candles[-2]
    c3 = candles[-3]
    c4 = candles[-4]

    buy_score = 0
    sell_score = 0

    # --------------------------------------------------------
    # 1. LAST CANDLE DIRECTION
    # --------------------------------------------------------

    if bullish(c1):
        buy_score += 1

    if bearish(c1):
        sell_score += 1

    # --------------------------------------------------------
    # 2. SHORT-TERM STRUCTURE
    # --------------------------------------------------------

    if c1["high"] > c2["high"] and c1["low"] > c2["low"]:
        buy_score += 1

    if c1["high"] < c2["high"] and c1["low"] < c2["low"]:
        sell_score += 1

    # --------------------------------------------------------
    # 3. MOMENTUM
    # --------------------------------------------------------

    if c1["close"] > c2["close"] > c3["close"]:
        buy_score += 1

    if c1["close"] < c2["close"] < c3["close"]:
        sell_score += 1

    # --------------------------------------------------------
    # 4. BREAKOUT
    # --------------------------------------------------------

    previous_high = max(
        c2["high"],
        c3["high"],
        c4["high"]
    )

    previous_low = min(
        c2["low"],
        c3["low"],
        c4["low"]
    )

    if c1["close"] > previous_high:
        buy_score += 1

    if c1["close"] < previous_low:
        sell_score += 1

    # --------------------------------------------------------
    # 5. CANDLE STRENGTH
    # --------------------------------------------------------

    body = candle_body(c1)
    total_range = candle_range(c1)

    body_ratio = body / total_range

    if bullish(c1) and body_ratio >= 0.55:
        buy_score += 1

    if bearish(c1) and body_ratio >= 0.55:
        sell_score += 1

    # --------------------------------------------------------
    # STRONG FILTER
    # Require 4/5 or better
    # --------------------------------------------------------

    signal = "NO SIGNAL"

    if buy_score >= 4 and buy_score > sell_score:
        signal = "BUY"

    elif sell_score >= 4 and sell_score > buy_score:
        signal = "SELL"

    return {
        "signal": signal,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "reason": "5-point strong signal filter"
    }


# ============================================================
# SL / TP
# ============================================================

def calculate_sl_tp(signal, candles):

    entry = candles[-1]["close"]

    recent = candles[-4:]

    recent_high = max(c["high"] for c in recent)
    recent_low = min(c["low"] for c in recent)

    if signal == "BUY":

        risk = entry - recent_low

        # Safety fallback
        if risk <= 0:
            risk = entry * 0.004

        stop_loss = recent_low
        take_profit = entry + (risk * 2.0)

        return entry, stop_loss, take_profit

    if signal == "SELL":

        risk = recent_high - entry

        # Safety fallback
        if risk <= 0:
            risk = entry * 0.004

        stop_loss = recent_high
        take_profit = entry - (risk * 2.0)

        return entry, stop_loss, take_profit

    return entry, None, None


# ============================================================
# FORMAT PRICE
# ============================================================

def fmt_price(value):

    if value is None:
        return "-"

    return f"${value:,.2f}"


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("ATI CRYPTO BOT V12")
    print("TABDEAL API")
    print("5M CLOSED CANDLE")
    print("PAPER / TEST")
    print("=" * 60)

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    current_price = get_current_price()

    if current_price is None:

        message = """🛡 ATI SAFETY

❌ BTCUSDT price could not be read.

API: Tabdeal price API failed.

🛑 NO TRADE
"""

        send_telegram(message)
        return

    print(f"BTCUSDT price: {current_price}")

    # --------------------------------------------------------
    # TRADES
    # --------------------------------------------------------

    trades = get_trades()

    if not trades:

        message = """🛡 ATI SAFETY

❌ BTCUSDT trades could not be read.

API: Tabdeal trades API failed.

🛑 NO TRADE
"""

        send_telegram(message)
        return

    print(f"Trades received: {len(trades)}")

    # --------------------------------------------------------
    # BUILD CANDLES
    # --------------------------------------------------------

    all_candles = build_5m_candles(trades)

    closed_candles = get_closed_candles(all_candles)

    print(f"5M candles created: {len(all_candles)}")
    print(f"Closed candles: {len(closed_candles)}")

    if len(closed_candles) < 8:

        message = f"""⚡ ATI CRYPTO BOT V12

₿ BTC/USDT
⏱ Timeframe: 5m

✅ TABDEAL API CONNECTED
✅ TRADES API CONNECTED

💰 Price: {fmt_price(current_price)}

📊 5M CANDLES: {len(closed_candles)}

⏳ Waiting for enough closed candles.

🛡 MODE: PAPER / TEST
🚫 REAL TRADING DISABLED
"""

        send_telegram(message)
        return

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    result = calculate_signal(closed_candles)

    signal = result["signal"]
    buy_score = result["buy_score"]
    sell_score = result["sell_score"]

    last_candle = closed_candles[-1]

    candle_time = datetime.fromtimestamp(
        last_candle["time"] / 1000,
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    entry, stop_loss, take_profit = calculate_sl_tp(
        signal,
        closed_candles
    )

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    message = f"""⚡ ATI CRYPTO BOT V12

₿ BTC/USDT
⏱ Timeframe: 5m
✅ CLOSED CANDLE
💪 STRONG SIGNAL FILTER

📡 TABDEAL API: OK
📊 TRADES API: OK

🕐 Candle: {candle_time}

💰 Current Price: {fmt_price(current_price)}
💵 Candle Close: {fmt_price(entry)}

📈 BUY SCORE: {buy_score}/5
📉 SELL SCORE: {sell_score}/5

"""

    if signal == "BUY":

        message += f"""🟢 SIGNAL: BUY

💵 Entry: {fmt_price(entry)}
🛑 SL: {fmt_price(stop_loss)}
🎯 TP: {fmt_price(take_profit)}

🔥 STRONG BUY
"""

    elif signal == "SELL":

        message += f"""🔴 SIGNAL: SELL

💵 Entry: {fmt_price(entry)}
🛑 SL: {fmt_price(stop_loss)}
🎯 TP: {fmt_price(take_profit)}

🔥 STRONG SELL
"""

    else:

        message += """⚪ SIGNAL: NO SIGNAL

⏳ NO TRADE
"""

    message += """
🛡 MODE: PAPER / TEST
🚫 REAL TRADING DISABLED

📡 Telegram: OK
"""

    print(message)

    send_telegram(message)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
