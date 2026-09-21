import os
import requests
from datetime import datetime

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api1.tabdeal.org"


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=20
    )


def get_trades():
    url = f"{BASE_URL}/r/api/v1/trades"

    params = {
        "symbol": "BTCIRT",
        "limit": 500
    }

    response = requests.get(
        url,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    return response.json()


def make_5m_candles(trades):
    candles = {}

    for trade in trades:
        price = float(trade["price"])
        qty = float(trade["qty"])
        timestamp = int(trade["time"])

        # شروع کندل 5 دقیقه‌ای
        bucket = (timestamp // 300000) * 300000

        if bucket not in candles:
            candles[bucket] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty
            }
        else:
            candles[bucket]["high"] = max(
                candles[bucket]["high"],
                price
            )

            candles[bucket]["low"] = min(
                candles[bucket]["low"],
                price
            )

            candles[bucket]["close"] = price
            candles[bucket]["volume"] += qty

    return candles


def main():
    try:
        trades = get_trades()

        if not trades:
            send_telegram(
                "❌ ATI BOT\n\n"
                "هیچ معامله‌ای از بازار BTCIRT دریافت نشد.\n\n"
                "🚫 REAL TRADING DISABLED"
            )
            return

        candles = make_5m_candles(trades)

        sorted_candles = sorted(
            candles.items(),
            key=lambda x: x[0],
            reverse=True
        )

        message = (
            "✅ ATI BOT - TABDEAL 5M MARKET\n\n"
            "✅ Telegram: OK\n"
            "✅ Tabdil Market API: OK\n"
            f"📊 Trades received: {len(trades)}\n"
            f"🕯 5M candles: {len(candles)}\n\n"
        )

        for timestamp, candle in sorted_candles[:3]:

            time_text = datetime.fromtimestamp(
                timestamp / 1000
            ).strftime("%H:%M")

            message += (
                f"🕯 {time_text}\n"
                f"Open: {candle['open']:,.0f}\n"
                f"High: {candle['high']:,.0f}\n"
                f"Low: {candle['low']:,.0f}\n"
                f"Close: {candle['close']:,.0f}\n"
                f"Volume: {candle['volume']:.6f}\n\n"
            )

        message += "🚫 REAL TRADING DISABLED"

        send_telegram(message)

    except Exception as e:
        send_telegram(
            "❌ TABDEAL 5M MARKET ERROR\n\n"
            f"{str(e)}\n\n"
            "🚫 REAL TRADING DISABLED"
        )


if __name__ == "__main__":
    main()
