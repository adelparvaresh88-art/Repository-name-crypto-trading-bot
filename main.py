import os
import json
import urllib.request
import urllib.parse

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTCUSDT"


def get_candles():
    url = (
        "https://api.binance.com/api/v3/klines"
        "?symbol=BTCUSDT&interval=5m&limit=50"
    )

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode())


def get_price():
    url = (
        "https://api.binance.com/api/v3/ticker/price"
        "?symbol=BTCUSDT"
    )

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read().decode())

    return float(data["price"])


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets are missing.")
        return

    url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(req, timeout=15) as response:
        print(response.read().decode())


def calculate_signal(candles):
    closes = [float(c[4]) for c in candles]

    # آخرین کندل کامل
    current = closes[-2]
    previous = closes[-3]

    # میانگین کوتاه و بلند
    short_avg = sum(closes[-7:-2]) / 5
    long_avg = sum(closes[-17:-2]) / 15

    # حرکت اخیر
    recent_high = max(closes[-7:-2])
    recent_low = min(closes[-7:-2])

    buy_score = 0
    sell_score = 0

    # روند
    if short_avg > long_avg:
        buy_score += 1

    if short_avg < long_avg:
        sell_score += 1

    # حرکت قیمت
    if current > previous:
        buy_score += 1

    if current < previous:
        sell_score += 1

    # شکست سقف/کف کوتاه‌مدت
    if current > recent_high:
        buy_score += 2

    if current < recent_low:
        sell_score += 2

    # تصمیم نهایی
    if buy_score >= 2 and buy_score > sell_score:
        return "BUY", buy_score, sell_score

    if sell_score >= 2 and sell_score > buy_score:
        return "SELL", buy_score, sell_score

    return "HOLD", buy_score, sell_score


def main():
    print("================================")
    print("ATI CRYPTO BOT V3")
    print("================================")

    try:
        candles = get_candles()
        price = get_price()

        signal, buy_score, sell_score = calculate_signal(candles)

        if signal == "BUY":
            icon = "🟢"
        elif signal == "SELL":
            icon = "🔴"
        else:
            icon = "⚪"

        message = (
            "⚡ ATI CRYPTO BOT V3\n\n"
            f"₿ BTC: ${price:,.2f}\n"
            "⏱ Timeframe: 5m\n\n"
            f"{icon} SIGNAL: {signal}\n"
            f"🟢 BUY SCORE: {buy_score}/4\n"
            f"🔴 SELL SCORE: {sell_score}/4\n\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING: DISABLED"
        )

        print(message)
        send_telegram(message)

    except Exception as error:
        print("BOT ERROR:")
        print(str(error))

        try:
            send_telegram(
                "⚠️ ATI CRYPTO BOT\n\n"
                "خطا در اجرای ربات.\n"
                "معامله واقعی انجام نشد."
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
