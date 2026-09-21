import os
import requests
from datetime import datetime, timezone

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
        timeout=15
    )


def get_trades():
    url = f"{BASE_URL}/v1/trade/market-trades"
    params = {
        "symbol": "BTCUSDT",
        "limit": 1000
    }

    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()

    data = r.json()

    if isinstance(data, dict):
        return data.get("data", data.get("result", []))

    return data


def build_candles(trades):
    candles = {}

    for t in trades:
        ts = int(t.get("time", t.get("timestamp", 0)))

        if ts < 100000000000:
            ts *= 1000

        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)

        minute = (dt.minute // 5) * 5

        candle_time = dt.replace(
            minute=minute,
            second=0,
            microsecond=0
        )

        key = candle_time

        price = float(
            t.get("price", t.get("p", 0))
        )

        if price <= 0:
            continue

        if key not in candles:
            candles[key] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price
            }
        else:
            candles[key]["high"] = max(
                candles[key]["high"], price
            )
            candles[key]["low"] = min(
                candles[key]["low"], price
            )
            candles[key]["close"] = price

    return sorted(candles.items())


def calculate_signal(candles):
    if len(candles) < 6:
        return "HOLD", 0, 0

    c = [x[1] for x in candles]

    last = c[-1]
    prev = c[-2]

    buy_score = 0
    sell_score = 0

    # 1 - candle direction
    if last["close"] > last["open"]:
        buy_score += 1
    elif last["close"] < last["open"]:
        sell_score += 1

    # 2 - close compared with previous candle
    if last["close"] > prev["close"]:
        buy_score += 1
    elif last["close"] < prev["close"]:
        sell_score += 1

    # 3 - higher high / lower low
    if last["high"] > prev["high"]:
        buy_score += 1
    elif last["low"] < prev["low"]:
        sell_score += 1

    # 4 - candle strength
    candle_range = last["high"] - last["low"]

    if candle_range > 0:
        body = abs(last["close"] - last["open"])
        strength = body / candle_range

        if strength >= 0.55:
            if last["close"] > last["open"]:
                buy_score += 1
            else:
                sell_score += 1

    # 5 - recent direction
    if c[-1]["close"] > c[-3]["close"]:
        buy_score += 1
    elif c[-1]["close"] < c[-3]["close"]:
        sell_score += 1

    if buy_score >= 4 and buy_score > sell_score:
        return "BUY", buy_score, sell_score

    if sell_score >= 4 and sell_score > buy_score:
        return "SELL", buy_score, sell_score

    return "HOLD", buy_score, sell_score


def main():
    trades = get_trades()

    candles = build_candles(trades)

    if len(candles) < 6:
        print("Not enough candles")
        return

    signal, buy_score, sell_score = calculate_signal(candles)

    candle_time, last = candles[-1]

    entry = last["close"]

    if signal == "BUY":
        sl = entry * 0.995
        tp = entry * 1.010

    elif signal == "SELL":
        sl = entry * 1.005
        tp = entry * 0.990

    else:
        sl = None
        tp = None

    message = (
        "⚡ ATI CRYPTO BOT - STAGE 6\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "💪 STRONG SIGNAL FILTER\n\n"
        f"📊 SIGNAL: {signal}\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n\n"
        f"🕐 Candle: {candle_time.strftime('%H:%M')} UTC\n"
        f"💰 Entry: ${entry:,.2f}\n"
    )

    if signal == "BUY":
        message += (
            "\n🟢 BUY SIGNAL\n"
            f"🛑 SL: ${sl:,.2f}\n"
            f"🎯 TP: ${tp:,.2f}\n"
        )

    elif signal == "SELL":
        message += (
            "\n🔴 SELL SIGNAL\n"
            f"🛑 SL: ${sl:,.2f}\n"
            f"🎯 TP: ${tp:,.2f}\n"
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

    print(message)

    if BOT_TOKEN and CHAT_ID:
        send_telegram(message)
        print("\n✅ Telegram: SENT")


if __name__ == "__main__":
    main()
