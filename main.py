import os
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api1.tabdeal.org"
SYMBOL = "BTCUSDT"

TIMEFRAME_MINUTES = 5
TARGET_CANDLES = 20

SL_PERCENT = 0.005
TP_PERCENT = 0.010


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


def calculate_signal(candles):
    if len(candles) < 10:
        raise Exception("Not enough candles")

    # آخرین کندل را تشکیل‌شونده در نظر می‌گیریم
    closed = candles[:-1]

    current = closed[-1]
    previous = closed[-2]

    buy_score = 0
    sell_score = 0

    # 1 - جهت قیمت
    if current["close"] > previous["close"]:
        buy_score += 1

    elif current["close"] < previous["close"]:
        sell_score += 1

    # 2 - شکست سقف / کف
    if current["close"] > previous["high"]:
        buy_score += 1

    elif current["close"] < previous["low"]:
        sell_score += 1

    # 3 - قدرت بدنه کندل
    candle_range = current["high"] - current["low"]

    if candle_range > 0:
        body = abs(current["close"] - current["open"])
        body_ratio = body / candle_range

        if body_ratio >= 0.55:
            if current["close"] > current["open"]:
                buy_score += 1

            elif current["close"] < current["open"]:
                sell_score += 1

    # 4 - مقایسه با میانگین 4 کندل قبلی
    previous_closes = [
        candle["close"] for candle in closed[-5:-1]
    ]

    average_close = sum(previous_closes) / len(previous_closes)

    if current["close"] > average_close:
        buy_score += 1

    elif current["close"] < average_close:
        sell_score += 1

    # 5 - دو کندل پشت سر هم
    if (
        current["close"] > current["open"]
        and previous["close"] > previous["open"]
    ):
        buy_score += 1

    elif (
        current["close"] < current["open"]
        and previous["close"] < previous["open"]
    ):
        sell_score += 1

    if buy_score >= 4 and buy_score > sell_score:
        signal = "BUY"

    elif sell_score >= 4 and sell_score > buy_score:
        signal = "SELL"

    else:
        signal = "HOLD"

    return signal, buy_score, sell_score, current


def calculate_levels(signal, entry):
    if signal == "BUY":
        sl = entry * (1 - SL_PERCENT)
        tp = entry * (1 + TP_PERCENT)

    elif signal == "SELL":
        sl = entry * (1 + SL_PERCENT)
        tp = entry * (1 - TP_PERCENT)

    else:
        sl = None
        tp = None

    return sl, tp


def check_result(signal, entry, sl, tp, future_candles):
    if signal == "HOLD":
        return "NO TRADE"

    for candle in future_candles:

        high = candle["high"]
        low = candle["low"]

        if signal == "BUY":

            # اگر هر دو در یک کندل لمس شوند،
            # محافظه‌کارانه SL را اول حساب می‌کنیم.
            if low <= sl:
                return "SL HIT"

            if high >= tp:
                return "TP HIT"

        elif signal == "SELL":

            if high >= sl:
                return "SL HIT"

            if low <= tp:
                return "TP HIT"

    return "OPEN / NOT RESOLVED"


def main():
    print("================================")
    print("ATI BOT - STAGE 5")
    print("BTC/USDT 5M SIGNAL TEST")
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

        if len(candles) < 10:
            raise Exception("Not enough candles")

        signal, buy_score, sell_score, candle = calculate_signal(
            candles
        )

        entry = candle["close"]

        sl, tp = calculate_levels(
            signal,
            entry
        )

        # کندل‌های بعدی برای تست نتیجه
        future_candles = candles[
            candles.index(candle) + 1:
        ]

        result = check_result(
            signal,
            entry,
            sl,
            tp,
            future_candles
        )

        candle_time = datetime.fromtimestamp(
            candle["time"] / 1000,
            timezone.utc
        ).strftime("%H:%M")

        print("")
        print("SIGNAL:", signal)
        print("BUY SCORE:", buy_score)
        print("SELL SCORE:", sell_score)
        print("ENTRY:", entry)

        if sl:
            print("SL:", sl)
            print("TP:", tp)

        print("RESULT:", result)

        message = (
            "⚡ ATI CRYPTO BOT - STAGE 5\n\n"
            "₿ BTC/USDT\n"
            "⏱ Timeframe: 5m\n"
            "✅ CLOSED CANDLE\n"
            "💪 STRONG SIGNAL FILTER\n\n"
            f"📊 SIGNAL: {signal}\n"
            f"📈 BUY SCORE: {buy_score}/5\n"
            f"📉 SELL SCORE: {sell_score}/5\n\n"
            f"🕐 Candle: {candle_time} UTC\n"
            f"💰 Entry: ${entry:,.2f}\n"
        )

        if signal != "HOLD":

            message += (
                f"🛑 SL: ${sl:,.2f}\n"
                f"🎯 TP: ${tp:,.2f}\n\n"
                f"📊 TEST RESULT: {result}\n"
            )

        else:

            message += (
                "⏸ HOLD\n"
                "No strong signal\n"
            )

        message += (
            "\n🧪 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

        send_telegram(message)

        print("")
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
