import os
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api1.tabdeal.org"
SYMBOL = "BTCUSDT"
TIMEFRAME_MINUTES = 5
TARGET_CANDLES = 20


def send_telegram(message):
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

    response = requests.get(
        url,
        params={
            "symbol": SYMBOL,
            "limit": 1000
        },
        timeout=20
    )

    response.raise_for_status()
    return response.json()


def build_candles(trades):
    candles = {}

    for trade in trades:
        price = float(trade["price"])
        quantity = float(trade["qty"])
        timestamp = int(trade["time"])

        candle_time = (
            timestamp // (TIMEFRAME_MINUTES * 60 * 1000)
        ) * (TIMEFRAME_MINUTES * 60 * 1000)

        if candle_time not in candles:
            candles[candle_time] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": quantity,
                "trades": 1
            }
        else:
            candle = candles[candle_time]

            candle["high"] = max(candle["high"], price)
            candle["low"] = min(candle["low"], price)
            candle["close"] = price
            candle["volume"] += quantity
            candle["trades"] += 1

    result = []

    for timestamp in sorted(candles.keys()):
        candle = candles[timestamp]
        candle["time"] = timestamp
        result.append(candle)

    return result[-TARGET_CANDLES:]


def format_candle(candle):
    time_text = datetime.fromtimestamp(
        candle["time"] / 1000,
        timezone.utc
    ).strftime("%H:%M")

    return (
        f"{time_text} | "
        f"O {candle['open']:.2f} | "
        f"H {candle['high']:.2f} | "
        f"L {candle['low']:.2f} | "
        f"C {candle['close']:.2f} | "
        f"T {candle['trades']}"
    )


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

        if not trades:
            raise Exception("No BTCUSDT trades received")

        candles = build_candles(trades)

        if not candles:
            raise Exception("Could not build 5M candles")

        print(f"Trades received: {len(trades)}")
        print(f"5M candles built: {len(candles)}")

        lines = []

        for candle in candles:
            lines.append(format_candle(candle))

        message = (
            "✅ ATI BOT - BTC/USDT 5M\n\n"
            "✅ Telegram: OK\n"
            "✅ Tabdeal Market API: OK\n"
            f"📊 Symbol: {SYMBOL}\n"
            "🕯 Timeframe: 5m\n\n"
            f"📊 Trades received: {len(trades)}\n"
            f"🕯 5M candles built: {len(candles)}\n\n"
            + "\n".join(lines)
            + "\n\n"
            "🧪 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

        send_telegram(message)

        print("Telegram message sent successfully")

    except requests.exceptions.HTTPError as e:
        print("HTTP ERROR:", e)

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
        print("BOT ERROR:", e)

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
