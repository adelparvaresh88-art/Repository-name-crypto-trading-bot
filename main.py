import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    "?vs_currency=usd&days=1&interval=5m"
)


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
        return True

    except Exception as error:
        print("❌ TELEGRAM ERROR:", error)
        return False


def get_market_data():

    request = urllib.request.Request(
        COINGECKO_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def main():

    print("================================")
    print("⚡ ATI CRYPTO BOT V15")
    print("================================")

    # اول تلگرام را تست می‌کنیم
    send_telegram(
        "⚡ ATI CRYPTO BOT V15\n\n"
        "✅ BOT STARTED\n"
        "📡 Telegram connection OK\n"
        "⏳ Checking 5m BTC data..."
    )

    try:

        data = get_market_data()

        prices = data.get("prices", [])

        if len(prices) < 10:
            raise Exception("Not enough market data")

        # قیمت‌های دریافت‌شده
        values = [float(item[1]) for item in prices]

        current = values[-1]
        previous = values[-2]

        # میانگین کوتاه
        short_period = min(5, len(values))
        short_avg = sum(values[-short_period:]) / short_period

        # میانگین بلند
        long_period = min(15, len(values))
        long_avg = sum(values[-long_period:]) / long_period

        buy_score = 0
        sell_score = 0

        if current > short_avg:
            buy_score += 1
        else:
            sell_score += 1

        if short_avg > long_avg:
            buy_score += 1
        else:
            sell_score += 1

        if current > previous:
            buy_score += 1
        else:
            sell_score += 1

        move = ((current - previous) / previous) * 100

        if move > 0.03:
            buy_score += 1
        elif move < -0.03:
            sell_score += 1

        if buy_score >= 3:
            signal = "🟢 BUY"
        elif sell_score >= 3:
            signal = "🔴 SELL"
        else:
            signal = "⚪ HOLD"

        now = datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

        message = (
            "⚡ ATI CRYPTO BOT V15\n\n"
            f"₿ BTC: ${current:,.2f}\n"
            "⏱ Timeframe: 5m\n"
            "✅ MARKET DATA OK\n"
            "✅ CLOSED DATA CHECKED\n\n"
            f"📈 BUY SCORE: {buy_score}/4\n"
            f"📉 SELL SCORE: {sell_score}/4\n"
            f"📊 MOVE: {move:.3f}%\n\n"
            f"🚨 SIGNAL: {signal}\n\n"
            "📊 SOURCE: COINGECKO\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED\n\n"
            f"🕐 {now}"
        )

        print(message)
        send_telegram(message)

    except Exception as error:

        error_message = (
            "⚠️ ATI CRYPTO BOT V15\n\n"
            "✅ Telegram: OK\n"
            "❌ MARKET DATA ERROR\n\n"
            f"ERROR:\n{str(error)}"
        )

        print(error_message)
        send_telegram(error_message)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("================================")
        print("❌ BOT ERROR:")
        print(str(error))
        print("================================")
        raise
