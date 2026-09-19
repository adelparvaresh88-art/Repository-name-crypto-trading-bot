import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 50

SL_PERCENT = 0.6
TP_PERCENT = 1.2


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram settings missing")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    try:
        request = urllib.request.Request(
            url,
            data=data,
            headers={"User-Agent": "ATI-CRYPTO-BOT"},
            method="POST"
        )

        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))

        print("TELEGRAM:", result)

        return result.get("ok", False)

    except Exception as e:
        print("TELEGRAM ERROR:", e)
        return False


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
        return json.loads(response.read().decode("utf-8"))


def calculate_signal(candles):
    closes = [float(c[4]) for c in candles]

    current = closes[-1]

    sma5 = sum(closes[-5:]) / 5
    sma15 = sum(closes[-15:]) / 15

    previous = closes[-2]

    if sma5 > sma15 and current > previous:
        return "BUY", current, sma5, sma15

    if sma5 < sma15 and current < previous:
        return "SELL", current, sma5, sma15

    return "HOLD", current, sma5, sma15


print("================================")
print("ATI CRYPTO BOT V8")
print("TIMEFRAME: 5m")
print("MODE: PAPER / TEST")
print("REAL TRADING: DISABLED")
print("================================")


try:
    candles = get_candles()

    signal, price, sma5, sma15 = calculate_signal(candles)

    print("PRICE:", price)
    print("SMA5:", sma5)
    print("SMA15:", sma15)
    print("SIGNAL:", signal)

    if signal == "BUY":

        stop_loss = price * (1 - SL_PERCENT / 100)
        take_profit = price * (1 + TP_PERCENT / 100)

        message = (
            "🟢 BUY SIGNAL\n\n"
            f"₿ BTC: ${price:,.2f}\n"
            f"⏱ Timeframe: {INTERVAL}\n\n"
            f"🎯 Entry: ${price:,.2f}\n"
            f"🛑 Stop Loss: ${stop_loss:,.2f}\n"
            f"💰 Take Profit: ${take_profit:,.2f}\n\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING: DISABLED"
        )

        send_telegram(message)

    elif signal == "SELL":

        stop_loss = price * (1 + SL_PERCENT / 100)
        take_profit = price * (1 - TP_PERCENT / 100)

        message = (
            "🔴 SELL SIGNAL\n\n"
            f"₿ BTC: ${price:,.2f}\n"
            f"⏱ Timeframe: {INTERVAL}\n\n"
            f"🎯 Entry: ${price:,.2f}\n"
            f"🛑 Stop Loss: ${stop_loss:,.2f}\n"
            f"💰 Take Profit: ${take_profit:,.2f}\n\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING: DISABLED"
        )

        send_telegram(message)

    else:

        print("HOLD - no Telegram signal sent")

except Exception as e:

    print("BOT ERROR:", e)

    send_telegram(
        "⚠️ ATI BOT ERROR\n\n"
        f"{e}\n\n"
        "📊 MODE: PAPER / TEST"
    )


print("FINISHED")
