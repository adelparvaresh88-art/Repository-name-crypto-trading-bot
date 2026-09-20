import urllib.request
import json
from datetime import datetime, timezone

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 50

TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

MIN_MOVE = 0.08
SL_PERCENT = 0.50
TP_PERCENT = 1.00


def get_candles():
    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval={INTERVAL}&limit={LIMIT}"
    )

    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode())


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram settings are missing.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    data = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        print("Telegram:", response.read().decode())


def main():
    candles = get_candles()

    # آخرین کندل بسته‌شده
    closed = candles[-2]
    previous = candles[-3]

    current = float(closed[4])
    previous_close = float(previous[4])

    change = ((current - previous_close) / previous_close) * 100

    closes = [float(c[4]) for c in candles[:-1]]

    fast_avg = sum(closes[-5:]) / 5
    slow_avg = sum(closes[-15:]) / 15

    buy_score = 0
    sell_score = 0

    if fast_avg > slow_avg:
        buy_score += 1

    if fast_avg < slow_avg:
        sell_score += 1

    if current > previous_close:
        buy_score += 1

    if current < previous_close:
        sell_score += 1

    if change >= MIN_MOVE:
        buy_score += 2

    if change <= -MIN_MOVE:
        sell_score += 2

    print("================================")
    print("⚡ ATI CRYPTO BOT V12")
    print("BTC:", current)
    print("BUY SCORE:", buy_score, "/5")
    print("SELL SCORE:", sell_score, "/5")
    print("MOVE:", round(change, 3), "%")
    print("================================")

    signal = None

    if buy_score >= 3 and buy_score > sell_score:
        signal = "BUY"

    elif sell_score >= 3 and sell_score > buy_score:
        signal = "SELL"

    if signal is None:
        print("HOLD - No strong signal")
        return

    if signal == "BUY":
        sl = current * (1 - SL_PERCENT / 100)
        tp = current * (1 + TP_PERCENT / 100)
        emoji = "🟢"

    else:
        sl = current * (1 + SL_PERCENT / 100)
        tp = current * (1 - TP_PERCENT / 100)
        emoji = "🔴"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    message = (
        "⚡ ATI CRYPTO BOT V12\n\n"
        f"₿ BTC: ${current:,.2f}\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE CONFIRMED\n"
        "💪 STRONG SIGNAL FILTER\n\n"
        f"{emoji} SIGNAL: {signal}\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n"
        f"📊 MOVE: {change:.3f}%\n\n"
        f"💰 Entry: ${current:,.2f}\n"
        f"🛑 SL: ${sl:,.2f}\n"
        f"🎯 TP: ${tp:,.2f}\n\n"
        "🧪 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED\n"
        f"🕐 {now}"
    )

    print(message)
    send_telegram(message)


if __name__ == "__main__":
    main()
