import os
import json
import urllib.request
import urllib.parse

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 50


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ TELEGRAM SECRETS MISSING")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    try:
        request = urllib.request.Request(url, data=data)

        with urllib.request.urlopen(request, timeout=20) as response:
            result = response.read().decode()

        print("✅ TELEGRAM SENT")
        print(result)
        return True

    except Exception as error:
        print("❌ TELEGRAM ERROR:")
        print(str(error))
        return False


def get_binance_candles():
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval={INTERVAL}&limit={LIMIT}"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def get_binance_price():
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode())

    return float(data["price"])


def main():

    print("================================")
    print("⚡ ATI CRYPTO BOT V13")
    print("================================")

    # اول مطمئن می‌شویم تلگرام کار می‌کند
    send_telegram(
        "⚡ ATI CRYPTO BOT V13\n\n"
        "✅ BOT STARTED\n"
        "📡 Telegram connection OK\n"
        "⏳ Checking BTC..."
    )

    try:
        candles = get_binance_candles()

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

        move = ((current - previous) / previous) * 100

        if move > 0.05:
            buy_score += 1
        elif move < -0.05:
            sell_score += 1

        if buy_score >= 3:
            signal = "🟢 BUY"
        elif sell_score >= 3:
            signal = "🔴 SELL"
        else:
            signal = "⚪ HOLD"

        message = (
            "⚡ ATI CRYPTO BOT V13\n\n"
            f"₿ BTC: ${current:,.2f}\n"
            "⏱ Timeframe: 5m\n"
            "✅ CLOSED CANDLE CONFIRMED\n\n"
            f"📈 BUY SCORE: {buy_score}/4\n"
            f"📉 SELL SCORE: {sell_score}/4\n"
            f"📊 MOVE: {move:.3f}%\n\n"
            f"🚨 SIGNAL: {signal}\n\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

        print(message)
        send_telegram(message)

    except Exception as error:

        error_message = (
            "⚠️ ATI CRYPTO BOT V13\n\n"
            "✅ Telegram: OK\n"
            "❌ Market Data Error\n\n"
            f"ERROR:\n{str(error)}"
        )

        print(error_message)
        send_telegram(error_message)


if __name__ == "__main__":
    main()
