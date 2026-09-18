import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTCUSDT"
LIMIT = 30


def get_btc_price():
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval=5m&limit={LIMIT}"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-Crypto-Bot"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode())

    closes = [float(candle[4]) for candle in data]

    return closes


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets not found.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    request = urllib.request.Request(url, data=data)

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode())

        if result.get("ok"):
            print("Telegram message sent successfully.")
        else:
            print("Telegram returned an error.")

    except Exception as error:
        print("Telegram error:", error)


print("================================")
print("ATI CRYPTO BOT")
print("MODE: PAPER / TEST")
print("TRADING: DISABLED")
print("================================")

try:
    closes = get_btc_price()

    current = closes[-1]
    previous = closes[-2]

    avg5 = sum(closes[-5:]) / 5
    avg15 = sum(closes[-15:]) / 15

    if avg5 > avg15 and current > previous:
        signal = "🟢 BUY"

    elif avg5 < avg15 and current < previous:
        signal = "🔴 SELL"

    else:
        signal = "⚪ HOLD"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    message = (
        "ATI CRYPTO BOT\n\n"
        f"Symbol: {SYMBOL}\n"
        f"Price: ${current:,.2f}\n"
        f"5 Candle Avg: ${avg5:,.2f}\n"
        f"15 Candle Avg: ${avg15:,.2f}\n\n"
        f"Signal: {signal}\n\n"
        "PAPER / TEST ONLY\n"
        "NO REAL TRADING\n"
        f"Time: {now}"
    )

    print(message)

    send_telegram(message)

    print("\nBOT FINISHED SUCCESSFULLY")

except Exception as error:
    print("BOT ERROR:", error)
    print("BOT STOPPED")
