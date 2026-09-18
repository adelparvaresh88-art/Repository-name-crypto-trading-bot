import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MIN_CHANGE = 0.20


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))

        return result.get("ok") is True

    except Exception as e:
        print("TELEGRAM ERROR:", e)
        return False


def get_btc_prices():
    url = (
        "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
        "?vs_currency=usd&days=1"
    )

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "ATI-Crypto-Bot/1.0"}
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

        prices = [float(x[1]) for x in data["prices"]]

        if len(prices) < 20:
            return None

        return prices

    except Exception as e:
        print("PRICE ERROR:", e)
        return None


print("================================")
print("ATI CRYPTO BOT - STRONG SIGNAL")
print("================================")

prices = get_btc_prices()

if prices is None:

    print("Could not get BTC data")
    raise SystemExit(1)


current = prices[-1]

short_avg = sum(prices[-5:]) / 5
long_avg = sum(prices[-20:]) / 20

change = ((current - prices[-5]) / prices[-5]) * 100

signal = "HOLD"

# STRONG BUY
if short_avg > long_avg and change >= MIN_CHANGE:
    signal = "BUY"

# STRONG SELL
elif short_avg < long_avg and change <= -MIN_CHANGE:
    signal = "SELL"


print("BTC:", current)
print("5 AVG:", short_avg)
print("20 AVG:", long_avg)
print("CHANGE:", change)
print("SIGNAL:", signal)


# فقط BUY و SELL ارسال شود
if signal in ["BUY", "SELL"]:

    if signal == "BUY":
        message = (
            "🟢 STRONG BUY SIGNAL\n\n"
            f"💰 BTC: ${current:,.2f}\n"
            f"📈 Change: {change:.2f}%\n"
            f"📊 Short Avg: ${short_avg:,.2f}\n"
            f"📊 Long Avg: ${long_avg:,.2f}\n\n"
            "🧪 PAPER / TEST MODE\n"
            "🚫 REAL TRADING: OFF"
        )

    else:
        message = (
            "🔴 STRONG SELL SIGNAL\n\n"
            f"💰 BTC: ${current:,.2f}\n"
            f"📉 Change: {change:.2f}%\n"
            f"📊 Short Avg: ${short_avg:,.2f}\n"
            f"📊 Long Avg: ${long_avg:,.2f}\n\n"
            "🧪 PAPER / TEST MODE\n"
            "🚫 REAL TRADING: OFF"
        )

    if not send_telegram(message):
        raise SystemExit(1)

    print("SIGNAL SENT TO TELEGRAM")

else:

    print("NO STRONG SIGNAL - NOTHING SENT")

print("================================")
print("ATI CRYPTO BOT - FINISHED")
print("================================")
