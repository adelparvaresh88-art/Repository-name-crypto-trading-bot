import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTCUSDT"
LIMIT = 30


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("ERROR: Telegram secrets are missing")
        return False

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
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))

        print("TELEGRAM:", result)

        return result.get("ok") is True

    except Exception as e:
        print("TELEGRAM ERROR:", str(e))
        return False



    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval=5m&limit={LIMIT}"
    )

    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
def get_candles():
    url = (
        "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
        "?vs_currency=usd&interval=5m&days=1"
    )

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

        prices = [float(item[1]) for item in data["prices"]]

        candles = []
        for price in prices[-30:]:
            candles.append([0, 0, 0, 0, price])

        return candles

    except Exception as e:
        print("COINGECKO ERROR:", str(e))
        return None
    except Exception as e:
        print("BINANCE ERROR:", str(e))
        return None


def calculate_signal(candles):
    closes = [float(candle[4]) for candle in candles]

    short_avg = sum(closes[-5:]) / 5
    long_avg = sum(closes[-15:]) / 15

    current_price = closes[-1]
    previous_price = closes[-2]

    if short_avg > long_avg and current_price > previous_price:
        signal = "🟢 BUY"

    elif short_avg < long_avg and current_price < previous_price:
        signal = "🔴 SELL"

    else:
        signal = "⚪ HOLD"

    return signal, current_price, short_avg, long_avg


print("================================")
print("ATI CRYPTO SIGNAL BOT")
print("MODE: PAPER / SIGNAL ONLY")
print("TRADING: DISABLED")
print("================================")

candles = get_candles()

if candles is None:
    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        "⚠️ خطا در دریافت اطلاعات BTC\n"
        "TRADING: DISABLED"
    )
else:
    signal, price, short_avg, long_avg = calculate_signal(candles)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        f"💰 BTC: ${price:,.2f}\n"
        f"📊 SIGNAL: {signal}\n\n"
        f"5C AVG: ${short_avg:,.2f}\n"
        f"15C AVG: ${long_avg:,.2f}\n\n"
        f"⏰ {now}\n"
        "🧪 PAPER / TEST\n"
        "🚫 REAL TRADING: OFF"
    )

print(message)

success = send_telegram(message)

if not success:
    print("BOT FAILED: Telegram message was not sent")
    raise SystemExit(1)

print("BOT FINISHED SUCCESSFULLY")
