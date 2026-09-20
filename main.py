import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 50


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Telegram secrets are missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    request = urllib.request.Request(url, data=data)

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = response.read().decode()
            print("✅ Telegram sent")
            print(result)
    except Exception as error:
        print("❌ Telegram ERROR:", error)


def get_candles():
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval={INTERVAL}&limit={LIMIT}"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-CRYPTO-BOT"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def main():
    print("================================")
    print("⚡ ATI CRYPTO BOT V12")
    print("₿ BTCUSDT | 5m")
    print("📊 PAPER / TEST MODE")
    print("🚫 REAL TRADING DISABLED")
    print("================================")

    candles = get_candles()

    # آخرین کندل بسته‌شده
    closed = candles[:-1]

    closes = [float(candle[4]) for candle in closed]

    current = closes[-1]
    previous = closes[-2]

    short_avg = sum(closes[-5:]) / 5
    long_avg = sum(closes[-15:]) / 15

    buy_score = 0
    sell_score = 0

    if short_avg > long_avg:
        buy_score += 1
    else:
        sell_score += 1

    if current > previous:
        buy_score += 1
    else:
        sell_score += 1

    if current > short_avg:
        buy_score += 1
    else:
        sell_score += 1

    # تغییر قیمت آخرین کندل بسته‌شده
    move_percent = ((current - previous) / previous) * 100

    if move_percent > 0.05:
        buy_score += 1

    if move_percent < -0.05:
        sell_score += 1

    signal = "HOLD"

    if buy_score >= 3:
        signal = "BUY"
    elif sell_score >= 3:
        signal = "SELL"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    message = (
        "⚡ ATI CRYPTO BOT V12\n\n"
        f"₿ BTC: ${current:,.2f}\n"
        f"⏱ Timeframe: {INTERVAL}\n"
        "✅ CLOSED CANDLE CONFIRMED\n\n"
        f"🟢 BUY SCORE: {buy_score}/4\n"
        f"🔴 SELL SCORE: {sell_score}/4\n"
        f"📊 MOVE: {move_percent:.3f}%\n\n"
        f"📌 SIGNAL: {signal}\n\n"
        "📊 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED\n"
        f"🕐 {now}"
    )

    print(message)
    send_telegram(message)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("================================")
        print("❌ BOT ERROR:")
        print(str(error))
        print("================================")
        raise
