import os
import json
import urllib.request
import urllib.parse

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TIMEFRAME = "5m"
LOOKBACK = 5


def send_telegram(message):

    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is missing")
        return False

    if not CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID is missing")
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

            result = json.loads(
                response.read().decode("utf-8")
            )

        print("TELEGRAM RESULT:", result)

        if result.get("ok"):
            print("TELEGRAM MESSAGE SENT")
            return True

        print("TELEGRAM SEND FAILED")
        return False

    except Exception as e:

        print("TELEGRAM ERROR:", e)
        return False


def get_candles():

    url = (
        "https://api.exchange.coinbase.com/products/"
        "BTC-USD/candles?granularity=300"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-CRYPTO-BOT"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:

        data = json.loads(
            response.read().decode("utf-8")
        )

    if not data or len(data) < LOOKBACK + 2:
        raise Exception("Not enough 5m candles")

    candles = []

    for candle in data:

        timestamp = int(candle[0])
        low = float(candle[1])
        high = float(candle[2])
        open_price = float(candle[3])
        close = float(candle[4])
        volume = float(candle[5])

        candles.append({
            "time": timestamp,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume
        })

    # API معمولاً از جدید به قدیم برمی‌گرداند
    candles.sort(key=lambda x: x["time"])

    # آخرین کندل ممکن است هنوز بسته نشده باشد
    closed = candles[:-1]

    return closed


def calculate_signal(candles):

    if len(candles) < LOOKBACK + 1:
        return "HOLD", None

    current = candles[-1]

    previous = candles[-(LOOKBACK + 1):-1]

    previous_high = max(
        candle["high"] for candle in previous
    )

    previous_low = min(
        candle["low"] for candle in previous
    )

    open_price = current["open"]
    close = current["close"]
    high = current["high"]
    low = current["low"]

    candle_range = high - low

    if candle_range <= 0:
        return "HOLD", current

    body = abs(close - open_price)

    body_strength = body / candle_range

    print("CURRENT OPEN:", open_price)
    print("CURRENT HIGH:", high)
    print("CURRENT LOW:", low)
    print("CURRENT CLOSE:", close)
    print("5-CANDLE HIGH:", previous_high)
    print("5-CANDLE LOW:", previous_low)
    print("BODY STRENGTH:", round(body_strength, 3))

    # BUY:
    # کندل صعودی باشد
    # بالای سقف 5 کندل قبلی بسته شود
    # بدنه حداقل 45 درصد کل کندل باشد

    if (
        close > open_price
        and close > previous_high
        and body_strength >= 0.45
    ):

        return "BUY", current

    # SELL:
    # کندل نزولی باشد
    # زیر کف 5 کندل قبلی بسته شود
    # بدنه حداقل 45 درصد کل کندل باشد

    if (
        close < open_price
        and close < previous_low
        and body_strength >= 0.45
    ):

        return "SELL", current

    return "HOLD", current


def create_signal_message(signal, candle):

    entry = candle["close"]

    if signal == "BUY":

        stop_loss = candle["low"]

        risk = entry - stop_loss

        if risk <= 0:
            stop_loss = entry * 0.994
            risk = entry - stop_loss

        take_profit = entry + (risk * 2)

        return (
            "🟢 BUY SIGNAL\n\n"
            f"₿ BTC: ${entry:,.2f}\n"
            "⏱ Timeframe: 5m\n\n"
            f"🎯 Entry: ${entry:,.2f}\n"
            f"🛑 Stop Loss: ${stop_loss:,.2f}\n"
            f"💰 Take Profit: ${take_profit:,.2f}\n\n"
            "📈 شرط: Breakout + Bullish Candle\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING: DISABLED"
        )

    if signal == "SELL":

        stop_loss = candle["high"]

        risk = stop_loss - entry

        if risk <= 0:
            stop_loss = entry * 1.006
            risk = stop_loss - entry

        take_profit = entry - (risk * 2)

        return (
            "🔴 SELL SIGNAL\n\n"
            f"₿ BTC: ${entry:,.2f}\n"
            "⏱ Timeframe: 5m\n\n"
            f"🎯 Entry: ${entry:,.2f}\n"
            f"🛑 Stop Loss: ${stop_loss:,.2f}\n"
            f"💰 Take Profit: ${take_profit:,.2f}\n\n"
            "📉 شرط: Breakdown + Bearish Candle\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING: DISABLED"
        )

    return (
        "⚪ ATI CRYPTO BOT\n\n"
        f"₿ BTC: ${entry:,.2f}\n"
        "⏱ Timeframe: 5m\n"
        "⚪ SIGNAL: HOLD\n\n"
        "📊 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )


print("================================")
print("ATI CRYPTO BOT V13")
print("TIMEFRAME: 5m")
print("REAL 5M CANDLE SIGNAL")
print("MODE: PAPER / TEST")
print("REAL TRADING: DISABLED")
print("================================")


try:

    candles = get_candles()

    print("5M CANDLES:", len(candles))

    signal, candle = calculate_signal(candles)

    print("SIGNAL:", signal)

    if candle is None:
        raise Exception("No valid candle")

    message = create_signal_message(
        signal,
        candle
    )

    send_telegram(message)

except Exception as e:

    print("BOT ERROR:", e)

    send_telegram(
        "⚠️ ATI BOT ERROR\n\n"
        f"{e}\n\n"
        "📊 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )


print("FINISHED")
