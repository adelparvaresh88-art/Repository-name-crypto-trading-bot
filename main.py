import os
import time
import requests
from datetime import datetime

# =========================
# ATI BOT - TABDEAL 5M V2
# =========================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TABDEEL_API_KEY = os.getenv("TABDIL_API_KEY")
TABDEEL_API_SECRET = os.getenv("TABDIL_API_SECRET")

TABDEEL_BASE = "https://api.tabdeal.org"

SYMBOL = "BTCIRT"
TIMEFRAME = "5m"


def telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets missing")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        r = requests.post(url, data=data, timeout=15)
        print("Telegram:", r.status_code)
    except Exception as e:
        print("Telegram error:", e)


def get_market_data():
    url = f"{TABDEEL_BASE}/v1/depth"

    params = {
        "symbol": SYMBOL,
        "limit": 500
    }

    headers = {
        "X-TABDEAL-APIKEY": TABDEEL_API_KEY
    }

    r = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=20
    )

    r.raise_for_status()

    return r.json()


def build_candles():
    data = get_market_data()

    trades = []

    if isinstance(data, dict):
        for key in ["trades", "data", "results"]:
            if key in data and isinstance(data[key], list):
                trades = data[key]
                break

    if not trades and isinstance(data, list):
        trades = data

    prices = []

    for item in trades:
        try:
            if isinstance(item, dict):
                price = (
                    item.get("price")
                    or item.get("last")
                    or item.get("p")
                )

                if price:
                    prices.append(float(price))

            elif isinstance(item, (int, float, str)):
                prices.append(float(item))

        except:
            continue

    if len(prices) < 10:
        raise Exception("Not enough market prices")

    return prices


def calculate_signal(prices):
    recent = prices[-20:]

    first = recent[0]
    last = recent[-1]

    change = ((last - first) / first) * 100

    if change >= 0.08:
        signal = "BUY"

    elif change <= -0.08:
        signal = "SELL"

    else:
        signal = "WAIT"

    return signal, change, last


def main():

    print("ATI BOT STARTED")

    try:
        prices = build_candles()

        signal, change, price = calculate_signal(prices)

        message = (
            "⚡ ATI BOT - TABDEAL 5M\n\n"
            "✅ Telegram: OK\n"
            "✅ Tabdil Market API: OK\n"
            f"📊 Prices received: {len(prices)}\n"
            "⏱ Timeframe: 5M\n\n"
            f"💰 BTC/IRT: {price:,.0f}\n"
            f"📈 MOVE: {change:.3f}%\n\n"
            f"📢 SIGNAL: {signal}\n\n"
            "🛑 REAL TRADING: DISABLED\n"
            "🧪 MODE: PAPER / TEST"
        )

        print(message)

        telegram(message)

    except Exception as e:

        error = (
            "⚠️ ATI BOT ERROR\n\n"
            f"{type(e).__name__}: {e}\n\n"
            "🚫 REAL TRADING DISABLED"
        )

        print(error)
        telegram(error)


if __name__ == "__main__":
    main()
