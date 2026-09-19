import os
import json
import urllib.request
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 30

SL_PERCENT = 1.0
TP_PERCENT = 2.0


def get_klines():
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval={INTERVAL}&limit={LIMIT}"
    )

    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode())


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram settings are missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = json.dumps({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        print("Telegram:", response.read().decode())


def main():
    candles = get_klines()

    closes = [float(candle[4]) for candle in candles]

    current = closes[-1]
    previous = closes[-2]

    short_avg = sum(closes[-5:]) / 5
    long_avg = sum(closes[-15:]) / 15

    if short_avg > long_avg and current > previous:
        signal = "BUY"
    elif short_avg < long_avg and current < previous:
        signal = "SELL"
    else:
        signal = "HOLD"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if signal == "BUY":
        stop_loss = current * (1 - SL_PERCENT / 100)
        take_profit = current * (1 + TP_PERCENT / 100)

    elif signal == "SELL":
        stop_loss = current * (1 + SL_PERCENT / 100)
        take_profit = current * (1 - TP_PERCENT / 100)

    else:
        stop_loss = 0
        take_profit = 0

    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        f"₿ BTC: ${current:,.2f}\n"
        f"⏱ Timeframe: {INTERVAL}\n"
        f"🕐 {now}\n\n"
        f"📢 SIGNAL: {signal}\n\n"
        "📊 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )

    if signal != "HOLD":
        message += (
            f"\n\n🎯 Entry: ${current:,.2f}"
            f"\n🛑 Stop Loss: ${stop_loss:,.2f}"
            f"\n💰 Take Profit: ${take_profit:,.2f}"
        )

    print(message)
    send_telegram(message)


if __name__ == "__main__":
    main()
