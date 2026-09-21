import os
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets are missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=20
    )

    response.raise_for_status()


def get_trades():
    url = f"{BASE_URL}/r/api/v1/trades"

    params = {
        "symbol": SYMBOL,
        "limit": 1000
    }

    response = requests.get(
        url,
        params=params,
        timeout=20
    )

    response.raise_for_status()
    return response.json()


def make_5m_candle(trades):
    if not trades:
        raise Exception("No BTCUSDT trades received")

    cleaned = []

    for trade in trades:
        price = float(trade["price"])
        qty = float(trade["qty"])
        timestamp = int(trade["time"])

        cleaned.append({
            "price": price,
            "qty": qty,
            "time": timestamp
        })

    cleaned.sort(key=lambda x: x["time"])

    # آخرین معامله
    last_time = cleaned[-1]["time"]

    # شروع کندل 5 دقیقه‌ای
    candle_start = (last_time // 300000) * 300000
    candle_end = candle_start + 300000

    candle_trades = [
        t for t in cleaned
        if candle_start <= t["time"] < candle_end
    ]

    if not candle_trades:
        raise Exception("No trades inside current 5m candle")

    prices = [t["price"] for t in candle_trades]

    candle = {
        "open": prices[0],
        "high": max(prices),
        "low": min(prices),
        "close": prices[-1],
        "volume": sum(t["qty"] for t in candle_trades),
        "trades": len(candle_trades),
        "start": candle_start,
        "end": candle_end
    }

    return candle


def main():
    print("================================")
    print("ATI BOT - BTC/USDT 5M")
    print("================================")

    try:
        if not BOT_TOKEN:
            raise Exception("TELEGRAM_BOT_TOKEN is missing")

        if not CHAT_ID:
            raise Exception("TELEGRAM_CHAT_ID is missing")

        trades = get_trades()

        print(f"Symbol: {SYMBOL}")
        print(f"Trades received: {len(trades)}")

        candle = make_5m_candle(trades)

        candle_time = datetime.fromtimestamp(
            candle["start"] / 1000,
            timezone.utc
        ).strftime("%H:%M")

        print("")
        print("5M CANDLE")
        print(f"Time: {candle_time}")
        print(f"Open: {candle['open']}")
        print(f"High: {candle['high']}")
        print(f"Low: {candle['low']}")
        print(f"Close: {candle['close']}")
        print(f"Volume: {candle['volume']}")
        print(f"Trades: {candle['trades']}")

        message = (
            "✅ ATI BOT - BTC/USDT 5M\n\n"
            "✅ Telegram: OK\n"
            "✅ Tabdeal Market API: OK\n"
            f"📊 Symbol: {SYMBOL}\n"
            f"🕯 Timeframe: {TIMEFRAME}\n\n"
            f"🕐 Candle: {candle_time} UTC\n"
            f"Open: {candle['open']:.2f}\n"
            f"High: {candle['high']:.2f}\n"
            f"Low: {candle['low']:.2f}\n"
            f"Close: {candle['close']:.2f}\n"
            f"📊 Trades: {candle['trades']}\n\n"
            "🧪 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

        send_telegram(message)

        print("")
        print("Telegram message sent successfully")

    except requests.exceptions.HTTPError as e:
        print("HTTP ERROR:")
        print(e)

        try:
            send_telegram(
                "⚠️ ATI BOT ERROR\n\n"
                f"HTTPError: {e}\n\n"
                "Symbol: BTCUSDT\n"
                "🚫 REAL TRADING DISABLED"
            )
        except Exception:
            pass

    except Exception as e:
        print("BOT ERROR:")
        print(e)

        try:
            send_telegram(
                "⚠️ ATI BOT ERROR\n\n"
                f"{type(e).__name__}: {e}\n\n"
                "Symbol: BTCUSDT\n"
                "🚫 REAL TRADING DISABLED"
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
