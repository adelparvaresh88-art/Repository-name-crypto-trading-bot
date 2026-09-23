import os
import time
import requests
from datetime import datetime, timezone

# =========================
# ATI CRYPTO BOT
# TABDEAL MARKET TEST
# =========================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TABDEAL_API_KEY = os.getenv("TABDEAL_API_KEY")
TABDEAL_API_SECRET = os.getenv("TABDEAL_API_SECRET")

LIVE_TRADING = os.getenv("LIVE_TRADING", "FALSE").upper()
ORDER_QTY = os.getenv("ORDER_QTY", "0.001")

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"
INTERVAL = "5m"


# =========================
# TELEGRAM
# =========================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=15
        )

        print("Telegram:", response.status_code)

    except Exception as e:
        print("Telegram error:", e)


# =========================
# TABDEAL MARKET DATA
# =========================

def get_trades():
    url = f"{BASE_URL}/api/v1/trades"

    params = {
        "symbol": SYMBOL,
        "limit": 1000
    }

    response = requests.get(
        url,
        params=params,
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):
        if "data" in data:
            data = data["data"]
        elif "result" in data:
            data = data["result"]

    return data


# =========================
# BUILD 5M CANDLES
# =========================

def build_candles(trades):
    candles = {}

    for trade in trades:

        try:
            price = float(
                trade.get("price")
                or trade.get("p")
                or trade.get("rate")
            )

            quantity = float(
                trade.get("quantity")
                or trade.get("q")
                or trade.get("amount")
                or 0
            )

            timestamp = (
                trade.get("timestamp")
                or trade.get("time")
                or trade.get("T")
            )

            timestamp = int(timestamp)

            if timestamp < 10000000000:
                timestamp *= 1000

            bucket = timestamp // 300000

            if bucket not in candles:
                candles[bucket] = {
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": quantity,
                    "time": bucket * 1000
                }

            candle = candles[bucket]

            candle["high"] = max(candle["high"], price)
            candle["low"] = min(candle["low"], price)
            candle["close"] = price
            candle["volume"] += quantity

        except Exception:
            continue

    result = list(candles.values())

    result.sort(key=lambda x: x["time"])

    return result


# =========================
# SIGNAL
# =========================

def calculate_signal(candles):

    if len(candles) < 6:
        return "NO SIGNAL", 0, 0

    # آخرین کندل کامل
    current = candles[-2]
    previous = candles[-3]

    buy_score = 0
    sell_score = 0

    # 1 - candle direction
    if current["close"] > current["open"]:
        buy_score += 1

    if current["close"] < current["open"]:
        sell_score += 1

    # 2 - close vs previous close
    if current["close"] > previous["close"]:
        buy_score += 1

    if current["close"] < previous["close"]:
        sell_score += 1

    # 3 - higher/lower high
    if current["high"] > previous["high"]:
        buy_score += 1

    if current["high"] < previous["high"]:
        sell_score += 1

    # 4 - higher/lower low
    if current["low"] > previous["low"]:
        buy_score += 1

    if current["low"] < previous["low"]:
        sell_score += 1

    # 5 - candle body strength
    candle_range = current["high"] - current["low"]

    if candle_range > 0:

        body = abs(
            current["close"] - current["open"]
        )

        strength = body / candle_range

        if strength >= 0.55:

            if current["close"] > current["open"]:
                buy_score += 1

            if current["close"] < current["open"]:
                sell_score += 1

    if buy_score >= 4 and buy_score > sell_score:
        signal = "BUY"

    elif sell_score >= 4 and sell_score > buy_score:
        signal = "SELL"

    else:
        signal = "NO SIGNAL"

    return signal, buy_score, sell_score


# =========================
# MAIN
# =========================

def main():

    print("================================")
    print("ATI CRYPTO BOT")
    print("TABDEAL 5M")
    print("================================")

    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN missing")
        return

    if not CHAT_ID:
        print("TELEGRAM_CHAT_ID missing")
        return

    if not TABDEAL_API_KEY:
        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "Bot stopped.\n\n"
            "❌ TABDEAL_API_KEY is missing."
        )
        return

    if not TABDEAL_API_SECRET:
        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "Bot stopped.\n\n"
            "❌ TABDEAL_API_SECRET is missing."
        )
        return

    try:

        trades = get_trades()

        print("Trades received:", len(trades))

        candles = build_candles(trades)

        print("5M candles built:", len(candles))

        if len(candles) < 6:

            send_telegram(
                "🛡 ATI SAFETY\n\n"
                "Bot stopped.\n\n"
                "❌ Not enough BTCUSDT 5M candles."
            )

            return

        signal, buy_score, sell_score = calculate_signal(candles)

        candle = candles[-2]

        entry = candle["close"]

        candle_time = datetime.fromtimestamp(
            candle["time"] / 1000,
            tz=timezone.utc
        ).strftime("%H:%M UTC")

        message = (
            "⚡ ATI CRYPTO BOT\n\n"
            "₿ BTC/USDT\n"
            "⏱ Timeframe: 5m\n"
            "✅ CLOSED CANDLE\n"
            "💪 STRONG SIGNAL FILTER\n\n"
            f"📊 SIGNAL: {signal}\n"
            f"📈 BUY SCORE: {buy_score}/5\n"
            f"📉 SELL SCORE: {sell_score}/5\n\n"
            f"🕐 Candle: {candle_time}\n"
            f"💰 Entry: ${entry:,.2f}\n\n"
            f"🧪 LIVE TRADING: {LIVE_TRADING}\n"
            f"📦 ORDER QTY: {ORDER_QTY}\n\n"
            "⚠️ ORDER EXECUTION: DISABLED\n"
            "🔎 API CONNECTION TEST ONLY"
        )

        print(message)

        send_telegram(message)

    except Exception as e:

        error = str(e)

        print("ERROR:", error)

        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "Bot stopped.\n\n"
            f"❌ Tabdeal API error:\n{error}"
        )


if __name__ == "__main__":
    main()
