import os
import json
import urllib.request
import urllib.parse
import traceback

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def request_json(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        }
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode())


def get_market_data():
    url = (
        "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
        "?vs_currency=usd&days=1&interval=5"
    )

    data = request_json(url)

    prices = data.get("prices", [])

    if len(prices) < 30:
        raise Exception("داده کافی از CoinGecko دریافت نشد.")

    closes = [float(item[1]) for item in prices]

    return closes


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        raise Exception("Telegram secrets پیدا نشد.")

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read().decode()


def calculate_signal(closes):
    current = closes[-1]
    previous = closes[-2]

    short_avg = sum(closes[-5:]) / 5
    long_avg = sum(closes[-15:]) / 15

    if short_avg > long_avg and current > previous:
        return "BUY"

    if short_avg < long_avg and current < previous:
        return "SELL"

    return "HOLD"


def main():
    print("ATI CRYPTO BOT STARTED")

    closes = get_market_data()

    price = closes[-1]
    signal = calculate_signal(closes)

    if signal == "BUY":
        icon = "🟢"
    elif signal == "SELL":
        icon = "🔴"
    else:
        icon = "⚪"

    message = (
        "⚡ ATI CRYPTO BOT\n\n"
        f"₿ BTC: ${price:,.2f}\n"
        "⏱ Timeframe: 5m\n"
        f"{icon} SIGNAL: {signal}\n\n"
        "📊 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )

    print(message)
    send_telegram(message)


try:
    main()

except Exception as error:
    print("BOT ERROR:")
    print(traceback.format_exc())

    try:
        send_telegram(
            "⚠️ ATI CRYPTO BOT\n\n"
            "خطای دقیق:\n\n"
            + str(error)
        )
    except Exception:
        pass
