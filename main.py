import os
import requests
from datetime import datetime, timezone

SYMBOL = "BTCUSDT"
INTERVAL = "5m"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets are missing.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print("TELEGRAM STATUS:", r.status_code)
        print("TELEGRAM RESPONSE:", r.text[:500])

        return r.ok

    except Exception as e:
        print("TELEGRAM ERROR:", e)
        return False


def get_price():

    urls = [
        "https://api1.tabdeal.org/api/v1/ticker/24hr?symbol=BTCUSDT",
        "https://api1.tabdeal.org/v1/ticker/24hr?symbol=BTCUSDT",
        "https://api1.tabdeal.org/api/v1/ticker/BTCUSDT",
        "https://api1.tabdeal.org/v1/ticker/BTCUSDT",
    ]

    for url in urls:

        try:
            print("TRY PRICE:", url)

            r = requests.get(
                url,
                headers={
                    "User-Agent": "ATI-Crypto-Bot/1.0",
                    "Accept": "application/json"
                },
                timeout=15
            )

            print("HTTP:", r.status_code)
            print("BODY:", r.text[:500])

            if r.status_code != 200:
                continue

            data = r.json()

            price = find_price(data)

            if price is not None:
                print("BTCUSDT PRICE:", price)
                return price

        except Exception as e:
            print("API ERROR:", repr(e))

    return None


def find_price(data):

    if isinstance(data, dict):

        keys = [
            "lastPrice",
            "last",
            "price",
            "close",
            "c"
        ]

        for key in keys:

            value = data.get(key)

            if value is not None:

                try:
                    return float(value)
                except:
                    pass

        for key in [
            "data",
            "result",
            "ticker",
            "tick"
        ]:

            nested = data.get(key)

            if nested is not None:

                price = find_price(nested)

                if price is not None:
                    return price

    elif isinstance(data, list):

        for item in data:

            price = find_price(item)

            if price is not None:
                return price

    return None


def get_candles():

    urls = [
        "https://api1.tabdeal.org/api/v1/klines?symbol=BTCUSDT&interval=5m&limit=50",
        "https://api1.tabdeal.org/v1/klines?symbol=BTCUSDT&interval=5m&limit=50",
    ]

    for url in urls:

        try:

            print("TRY CANDLES:", url)

            r = requests.get(
                url,
                headers={
                    "User-Agent": "ATI-Crypto-Bot/1.0",
                    "Accept": "application/json"
                },
                timeout=20
            )

            print("CANDLE HTTP:", r.status_code)
            print("CANDLE BODY:", r.text[:500])

            if r.status_code != 200:
                continue

            data = r.json()

            if isinstance(data, list):
                return data

            if isinstance(data, dict):

                for key in [
                    "data",
                    "result",
                    "candles",
                    "klines"
                ]:

                    if isinstance(data.get(key), list):
                        return data[key]

        except Exception as e:
            print("CANDLE ERROR:", repr(e))

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

        buy = 0
        sell = 0

        if last > previous:
            buy += 1

        elif last < previous:
            sell += 1

        if last > average:
            buy += 1

        elif last < average:
            sell += 1

        movement = ((last - previous) / previous) * 100

        if movement > 0.05:
            buy += 1

        if movement < -0.05:
            sell += 1

        if closes[-4] < closes[-3] < closes[-2]:
            buy += 1

        if closes[-4] > closes[-3] > closes[-2]:
            sell += 1

        if last > max(closes[-6:-2]):
            buy += 1

        if last < min(closes[-6:-2]):
            sell += 1

        if buy >= 4 and buy > sell:
            return "BUY", buy, sell

        if sell >= 4 and sell > buy:
            return "SELL", buy, sell

        return "NO SIGNAL", buy, sell

    except Exception as e:

        print("SIGNAL ERROR:", repr(e))

        return "NO SIGNAL", 0, 0


def main():

    print("=" * 60)
    print("ATI CRYPTO BOT")
    print("BTCUSDT / 5m")
    print("=" * 60)

    price = get_price()

    if price is None:

        message = """🛡 ATI SAFETY

❌ BTCUSDT price could not be read.

Tabdeal public API did not return a usable price.

🚫 No trade was sent.
"""

        print(message)
        send_telegram(message)
        return

    candles = get_candles()

    if not candles:

        message = f"""🛡 ATI SAFETY

💰 BTCUSDT: ${price:,.2f}

❌ 5m candles could not be read.

🚫 No trade was sent.
"""

        print(message)
        send_telegram(message)
        return

    signal, buy, sell = calculate_signal(candles)

    now = datetime.now(timezone.utc)

    if signal == "BUY":

        sl = price * 0.995
        tp = price * 1.010

        trade = f"""
🟢 BUY SIGNAL

💰 Entry: ${price:,.2f}
🛑 SL: ${sl:,.2f}
🎯 TP: ${tp:,.2f}
"""

    elif signal == "SELL":

        sl = price * 1.005
        tp = price * 0.990

        trade = f"""
🔴 SELL SIGNAL

💰 Entry: ${price:,.2f}
🛑 SL: ${sl:,.2f}
🎯 TP: ${tp:,.2f}
"""

    else:

        trade = """
⏳ NO TRADE

No strong signal confirmed.
"""

    message = f"""⚡ ATI CRYPTO BOT

₿ BTC/USDT
⏱ Timeframe: 5m
✅ CLOSED CANDLE
💪 STRONG SIGNAL FILTER

📊 SIGNAL: {signal}
📈 BUY SCORE: {buy}/5
📉 SELL SCORE: {sell}/5

🕐 UTC: {now.strftime("%Y-%m-%d %H:%M:%S")}
💰 Price: ${price:,.2f}
{trade}
🛡 MODE: PAPER / TEST
🚫 REAL TRADING DISABLED
"""

    print(message)
    send_telegram(message)


if __name__ == "__main__":
    main()
