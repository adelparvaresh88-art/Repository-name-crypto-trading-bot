import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MIN_CHANGE = 0.03
MIN_SCORE = 4


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

        print("TELEGRAM:", result)
        return result.get("ok") is True

    except Exception as e:
        print("TELEGRAM ERROR:", e)
        return False


def get_prices():
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
            print("Not enough price data")
            return None

        return prices

    except Exception as e:
        print("PRICE ERROR:", e)
        return None


print("================================")
print("ATI CRYPTO BOT - FINAL")
print("================================")

prices = get_prices()

if prices is None:
    raise SystemExit(1)


current = prices[-1]

avg5 = sum(prices[-5:]) / 5
avg10 = sum(prices[-10:]) / 10
avg20 = sum(prices[-20:]) / 20

change3 = ((prices[-1] - prices[-4]) / prices[-4]) * 100
change5 = ((prices[-1] - prices[-6]) / prices[-6]) * 100
change10 = ((prices[-1] - prices[-11]) / prices[-11]) * 100


buy_score = 0
sell_score = 0


# =========================
# BUY SCORE
# =========================

if avg5 > avg10:
    buy_score += 1

if avg10 > avg20:
    buy_score += 1

if change3 > 0:
    buy_score += 1

if change5 >= MIN_CHANGE:
    buy_score += 1

if change10 > 0:
    buy_score += 1


# =========================
# SELL SCORE
# =========================

if avg5 < avg10:
    sell_score += 1

if avg10 < avg20:
    sell_score += 1

if change3 < 0:
    sell_score += 1

if change5 <= -MIN_CHANGE:
    sell_score += 1

if change10 < 0:
    sell_score += 1


print("BTC:", current)
print("BUY SCORE:", buy_score, "/5")
print("SELL SCORE:", sell_score, "/5")


# =========================
# STRONG BUY
# =========================

if buy_score >= MIN_SCORE:

    message = (
        "🟢 STRONG BUY\n\n"
        f"💰 BTC: ${current:,.2f}\n\n"
        f"🟢 BUY SCORE: {buy_score}/5\n"
        f"🔴 SELL SCORE: {sell_score}/5\n\n"
        f"AVG 5: ${avg5:,.2f}\n"
        f"AVG 10: ${avg10:,.2f}\n"
        f"AVG 20: ${avg20:,.2f}\n\n"
        f"3-Candle: {change3:.3f}%\n"
        f"5-Candle: {change5:.3f}%\n"
        f"10-Candle: {change10:.3f}%\n\n"
        "🧪 PAPER / TEST\n"
        "🚫 REAL TRADING: OFF\n\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    if not send_telegram(message):
        raise SystemExit(1)

    print("STRONG BUY SENT")


# =========================
# STRONG SELL
# =========================

elif sell_score >= MIN_SCORE:

    message = (
        "🔴 STRONG SELL\n\n"
        f"💰 BTC: ${current:,.2f}\n\n"
        f"🟢 BUY SCORE: {buy_score}/5\n"
        f"🔴 SELL SCORE: {sell_score}/5\n\n"
        f"AVG 5: ${avg5:,.2f}\n"
        f"AVG 10: ${avg10:,.2f}\n"
        f"AVG 20: ${avg20:,.2f}\n\n"
        f"3-Candle: {change3:.3f}%\n"
        f"5-Candle: {change5:.3f}%\n"
        f"10-Candle: {change10:.3f}%\n\n"
        "🧪 PAPER / TEST\n"
        "🚫 REAL TRADING: OFF\n\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    if not send_telegram(message):
        raise SystemExit(1)

    print("STRONG SELL SENT")


# =========================
# HOLD = NOTHING
# =========================

else:

    print("HOLD - NOTHING SENT TO TELEGRAM")


print("================================")
print("ATI CRYPTO BOT - FINISHED")
print("================================")
