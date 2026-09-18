import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# حداقل قدرت حرکت
MIN_CHANGE = 0.10


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

        if len(prices) < 30:
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
    print("BTC DATA ERROR")
    raise SystemExit(1)


current = prices[-1]

# میانگین‌های کوتاه و بلند
avg_5 = sum(prices[-5:]) / 5
avg_10 = sum(prices[-10:]) / 10
avg_20 = sum(prices[-20:]) / 20

# حرکت قیمت در چند بازه
change_3 = ((prices[-1] - prices[-4]) / prices[-4]) * 100
change_5 = ((prices[-1] - prices[-6]) / prices[-6]) * 100
change_10 = ((prices[-1] - prices[-11]) / prices[-11]) * 100


signal = None


# =========================
# STRONG BUY
# =========================
if (
    avg_5 > avg_10
    and avg_10 > avg_20
    and change_3 > 0
    and change_5 >= MIN_CHANGE
    and change_10 > 0
):
    signal = "STRONG BUY"


# =========================
# STRONG SELL
# =========================
elif (
    avg_5 < avg_10
    and avg_10 < avg_20
    and change_3 < 0
    and change_5 <= -MIN_CHANGE
    and change_10 < 0
):

    signal = "STRONG SELL"


print("BTC:", current)
print("AVG 5:", avg_5)
print("AVG 10:", avg_10)
print("AVG 20:", avg_20)
print("CHANGE 3:", change_3)
print("CHANGE 5:", change_5)
print("CHANGE 10:", change_10)
print("SIGNAL:", signal)


# فقط سیگنال قوی ارسال شود
if signal is not None:

    if signal == "STRONG BUY":
        emoji = "🟢"
    else:
        emoji = "🔴"

    message = (
        f"{emoji} {signal}\n\n"
        f"💰 BTC: ${current:,.2f}\n\n"
        f"📊 Avg 5: ${avg_5:,.2f}\n"
        f"📊 Avg 10: ${avg_10:,.2f}\n"
        f"📊 Avg 20: ${avg_20:,.2f}\n\n"
        f"📈 3-Candle: {change_3:.3f}%\n"
        f"📈 5-Candle: {change_5:.3f}%\n"
        f"📈 10-Candle: {change_10:.3f}%\n\n"
        "🧪 PAPER / TEST MODE\n"
        "🚫 REAL TRADING: OFF\n\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    if not send_telegram(message):
        raise SystemExit(1)

    print("SIGNAL SENT TO TELEGRAM")

else:

    print("NO STRONG SIGNAL")
    print("NOTHING SENT TO TELEGRAM")


print("================================")
print("ATI CRYPTO BOT - FINISHED")
print("================================")
