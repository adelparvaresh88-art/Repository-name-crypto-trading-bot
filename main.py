import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# حداقل تغییر قیمت برای تأیید سیگنال قوی
MIN_CHANGE = 0.05


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


print("ATI CRYPTO BOT STARTED")

prices = get_btc_prices()

if prices is None:
    print("BTC DATA ERROR")
    raise SystemExit(1)

current = prices[-1]

short_avg = sum(prices[-5:]) / 5
long_avg = sum(prices[-20:]) / 20

change = ((current - prices[-5]) / prices[-5]) * 100

signal = None

# STRONG BUY
if short_avg > long_avg and change >= MIN_CHANGE:
    signal = "STRONG BUY"

# STRONG SELL
elif short_avg < long_avg and change <= -MIN_CHANGE:
    signal = "STRONG SELL"


print("BTC:", current)
print("CHANGE:", change)
print("SIGNAL:", signal)

# فقط BUY و SELL ارسال شود
if signal:

    if signal == "STRONG BUY":
        emoji = "🟢"
    else:
        emoji = "🔴"

    message = (
        f"{emoji} {signal}\n\n"
        f"💰 BTC: ${current:,.2f}\n"
        f"📈 Change: {change:.3f}%\n"
        f"📊 5 Avg: ${short_avg:,.2f}\n"
        f"📊 20 Avg: ${long_avg:,.2f}\n\n"
        "🧪 PAPER / TEST MODE\n"
        "🚫 REAL TRADING: OFF\n\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    if not send_telegram(message):
        raise SystemExit(1)

    print("SIGNAL SENT")

else:
    print("NO STRONG SIGNAL - TELEGRAM MESSAGE NOT SENT")

print("ATI CRYPTO BOT FINISHED")
