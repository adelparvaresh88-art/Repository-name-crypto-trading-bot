import os
import requests
from datetime import datetime, timezone

BASE_URL = "https://api1.tabdeal.org"
SYMBOL = "BTCUSDT"
INTERVAL = "5m"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM ERROR: missing token or chat id")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print("TELEGRAM STATUS:", response.status_code)
        print("TELEGRAM RESPONSE:", response.text[:500])

        return response.ok

    except Exception as e:
        print("TELEGRAM ERROR:", e)
        return False


def get_price():
    urls = [
        f"{BASE_URL}/v1/ticker/{SYMBOL}",
        f"{BASE_URL}/api/v1/ticker/{SYMBOL}",
        f"{BASE_URL}/v1/ticker/24hr?symbol={SYMBOL}",
        f"{BASE_URL}/api/v1/ticker/24hr?symbol={SYMBOL}"
    ]

    for url in urls:
        try:
            print("PRICE API:", url)

            response = requests.get(url, timeout=15)

            print("STATUS:", response.status_code)

            if response.status_code != 200:
                continue

            data = response.json()
            price = extract_price(data)

            if price is not None:
                return price

        except Exception as e:
            print("PRICE ERROR:", e)

    return None


def extract_price(data):
    if isinstance(data, dict):

        for key in [
            "last",
            "lastPrice",
            "price",
            "close",
            "c",
            "last_price"
        ]:
            value = data.get(key)

            if value is not None:
                try:
                    return float(value)
                except Exception:
                    pass

        for key in ["data", "result", "ticker"]:
            nested = data.get(key)

            if isinstance(nested, dict):
                price = extract_price(nested)

                if price is not None:
                    return price

    return None


def get_candles(limit=50):
    urls = [
        f"{BASE_URL}/v1/klines?symbol={SYMBOL}&interval={INTERVAL}&limit={limit}",
        f"{BASE_URL}/api/v1/klines?symbol={SYMBOL}&interval={INTERVAL}&limit={limit}",
        f"{BASE_URL}/v1/candles?symbol={SYMBOL}&interval={INTERVAL}&limit={limit}",
        f"{BASE_URL}/api/v1/candles?symbol={SYMBOL}&interval={INTERVAL}&limit={limit}"
    ]

    for url in urls:
        try:
            print("CANDLE API:", url)

            response = requests.get(url, timeout=20)

            print("CANDLE STATUS:", response.status_code)

            if response.status_code != 200:
                continue

            data = response.json()

            if isinstance(data, list):
                return data

            if isinstance(data, dict):
                for key in ["data", "result", "candles", "klines"]:
                    if isinstance(data.get(key), list):
                        return data[key]

        except Exception as e:
            print("CANDLE ERROR:", e)

    return []


def calculate_signal(candles):
    if len(candles) < 6:
        return "NO SIGNAL", 0, 0

    closes = []

    try:
        for candle in candles:
            if isinstance(candle, list) and len(candle) >= 5:
                closes.append(float(candle[4]))

            elif isinstance(candle, dict):
                value = candle.get("close") or candle.get("c")

                if value is not None:
                    closes.append(float(value))

        if len(closes) < 6:
            return "NO SIGNAL", 0, 0

        last = closes[-2]
        previous = closes[-3]

        average = sum(closes[-6:-1]) / 5

        buy_score = 0
        sell_score = 0

        if last > previous:
            buy_score += 1
        elif last < previous:
            sell_score += 1

        if last > average:
            buy_score += 1
        elif last < average:
            sell_score += 1

        movement = ((last - previous) / previous) * 100

        if movement > 0.05:
            buy_score += 1

        if movement < -0.05:
            sell_score += 1

        if closes[-4] < closes[-3] < closes[-2]:
            buy_score += 1

        if closes[-4] > closes[-3] > closes[-2]:
            sell_score += 1

        if last > max(closes[-6:-2]):
            buy_score += 1

        if last < min(closes[-6:-2]):
            sell_score += 1

        if buy_score >= 4 and buy_score > sell_score:
            signal = "BUY"

        elif sell_score >= 4 and sell_score > buy_score:
            signal = "SELL"

        else:
            signal = "NO SIGNAL"

        return signal, buy_score, sell_score

    except Exception as e:
        print("SIGNAL ERROR:", e)
        return "NO SIGNAL", 0, 0


def main():

    print("=" * 60)
    print("ATI CRYPTO BOT")
    print("TABDEAL BTCUSDT")
    print("=" * 60)

    price = get_price()

    if price is None:

        message = """🛡 ATI SAFETY

❌ BTCUSDT price could not be read.

The bot could not connect to the Tabdeal public price API.
No trade was sent.
"""

        print(message)
        send_telegram(message)
        return

    candles = get_candles()

    if not candles:

        message = f"""🛡 ATI SAFETY

⚠️ BTCUSDT PRICE: ${price:,.2f}

❌ 5m candles could not be read.

No trade was sent.
"""

        print(message)
        send_telegram(message)
        return

    signal, buy_score, sell_score = calculate_signal(candles)

    now = datetime.now(timezone.utc)

    if signal == "BUY":

        sl = price * 0.995
        tp = price * 1.010

        trade_text = f"""
🟢 BUY SIGNAL

💰 Entry: ${price:,.2f}
🛑 SL: ${sl:,.2f}
🎯 TP: ${tp:,.2f}
"""

    elif signal == "SELL":

        sl = price * 1.005
        tp = price * 0.990

        trade_text = f"""
🔴 SELL SIGNAL

💰 Entry: ${price:,.2f}
🛑 SL: ${sl:,.2f}
🎯 TP: ${tp:,.2f}
"""

    else:

        trade_text = """
⏳ NO TRADE

No strong signal confirmed.
"""

    message = f"""⚡ ATI CRYPTO BOT

₿ BTC/USDT
⏱ Timeframe: 5m
✅ CLOSED CANDLE
💪 STRONG SIGNAL FILTER

📊 SIGNAL: {signal}
📈 BUY SCORE: {buy_score}/5
📉 SELL SCORE: {sell_score}/5

🕐 UTC: {now.strftime("%Y-%m-%d %H:%M:%S")}
💰 Price: ${price:,.2f}
{trade_text}
🛡 MODE: PAPER / TEST
🚫 REAL TRADING DISABLED
"""

    print(message)

    if send_telegram(message):
        print("TELEGRAM: MESSAGE SENT")
    else:
        print("TELEGRAM: MESSAGE FAILED")


if __name__ == "__main__":
    main()
