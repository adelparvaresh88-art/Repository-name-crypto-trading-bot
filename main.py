import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTCUSDT"
LIMIT = 30
MIN_SCORE = 3
SL_PERCENT = 1.0
TP_PERCENT = 2.0


def get_btc_data():
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval=5m&limit={LIMIT}"
    )

    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode())


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram settings are missing.")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    request = urllib.request.Request(url, data=data)

    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode())

    print("Telegram:", result.get("ok"))
    return result.get("ok", False)


print("================================")
print("ATI CRYPTO BOT V5")
print("MODE: PAPER / TEST")
print("TRADING: DISABLED")
print("================================")

try:
    candles = get_btc_data()

    closes = [float(c[4]) for c in candles]

    current = closes[-1]
    previous = closes[-2]

    avg5 = sum(closes[-5:]) / 5
    avg15 = sum(closes[-15:]) / 15

    buy_score = 0
    sell_score = 0

    if avg5 > avg15:
        buy_score += 1

    if avg5 < avg15:
        sell_score += 1

    if current > previous:
        buy_score += 1

    if current < previous:
        sell_score += 1

    if current > avg5:
        buy_score += 1

    if current < avg5:
        sell_score += 1

    print("BTC PRICE:", current)
    print("AVG 5:", avg5)
    print("AVG 15:", avg15)
    print("BUY SCORE:", buy_score, "/3")
    print("SELL SCORE:", sell_score, "/3")

    message = None

    if buy_score >= MIN_SCORE:
        stop_loss = current * (1 - SL_PERCENT / 100)
        take_profit = current * (1 + TP_PERCENT / 100)

        message = (
            "🟢 STRONG BUY - PAPER\n\n"
            f"💰 Entry: ${current:,.2f}\n"
            f"🛑 SL: ${stop_loss:,.2f}\n"
            f"🎯 TP: ${take_profit:,.2f}\n\n"
            f"📊 BUY SCORE: {buy_score}/3\n"
            "⚠️ PAPER ONLY - NO REAL TRADE"
        )

    elif sell_score >= MIN_SCORE:
        stop_loss = current * (1 + SL_PERCENT / 100)
        take_profit = current * (1 - TP_PERCENT / 100)

        message = (
            "🔴 STRONG SELL - PAPER\n\n"
            f"💰 Entry: ${current:,.2f}\n"
            f"🛑 SL: ${stop_loss:,.2f}\n"
            f"🎯 TP: ${take_profit:,.2f}\n\n"
            f"📊 SELL SCORE: {sell_score}/3\n"
            "⚠️ PAPER ONLY - NO REAL TRADE"
        )

    else:
        message = (
            "⚪ BTCUSDT - HOLD\n\n"
            f"💰 Price: ${current:,.2f}\n"
            f"📊 BUY: {buy_score}/3\n"
            f"📊 SELL: {sell_score}/3\n\n"
            "⚠️ PAPER ONLY - NO REAL TRADE"
        )

    print(message)
    send_telegram(message)

    print("BOT FINISHED SUCCESSFULLY")

except Exception as e:
    print("ERROR:", str(e))
    raise
