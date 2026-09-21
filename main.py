import os
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api1.tabdeal.org"


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Telegram secrets missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=15
    )

    response.raise_for_status()
    print("✅ Telegram: OK")


def get_trades():
    url = f"{BASE_URL}/r/api/v1/trades"

    params = {
        "symbol": "BTCUSDT",
        "limit": 1000
    }

    response = requests.get(
        url,
        params=params,
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):
        trades = data.get("data", data.get("result", []))
    else:
        trades = data

    if not isinstance(trades, list):
        raise Exception(f"Unexpected API response: {data}")

    return trades


def get_trade_price(trade):
    price = (
        trade.get("price")
        or trade.get("p")
    )

    if price is None:
        return None

    return float(price)


def get_trade_time(trade):
    timestamp = (
        trade.get("time")
        or trade.get("timestamp")
        or trade.get("T")
        or trade.get("ts")
    )

    if timestamp is None:
        return None

    timestamp = int(timestamp)

    if timestamp < 100000000000:
        timestamp *= 1000

    return datetime.fromtimestamp(
        timestamp / 1000,
        tz=timezone.utc
    )


def build_candles(trades):
    candles = {}

    for trade in trades:

        price = get_trade_price(trade)
        trade_time = get_trade_time(trade)

        if price is None or trade_time is None:
            continue

        minute = (trade_time.minute // 5) * 5

        candle_time = trade_time.replace(
            minute=minute,
            second=0,
            microsecond=0
        )

        if candle_time not in candles:
            candles[candle_time] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price
            }

        else:
            candle = candles[candle_time]

            candle["high"] = max(
                candle["high"],
                price
            )

            candle["low"] = min(
                candle["low"],
                price
            )

            candle["close"] = price

    return sorted(candles.items())


def calculate_signal(candles):

    if len(candles) < 6:
        return "HOLD", 0, 0

    data = [item[1] for item in candles]

    last = data[-1]
    previous = data[-2]
    three_back = data[-3]

    buy_score = 0
    sell_score = 0

    # 1. Candle direction
    if last["close"] > last["open"]:
        buy_score += 1

    elif last["close"] < last["open"]:
        sell_score += 1

    # 2. Close compared with previous candle
    if last["close"] > previous["close"]:
        buy_score += 1

    elif last["close"] < previous["close"]:
        sell_score += 1

    # 3. Higher high / lower low
    if last["high"] > previous["high"]:
        buy_score += 1

    elif last["low"] < previous["low"]:
        sell_score += 1

    # 4. Candle body strength
    candle_range = last["high"] - last["low"]

    if candle_range > 0:

        body = abs(
            last["close"] - last["open"]
        )

        strength = body / candle_range

        if strength >= 0.55:

            if last["close"] > last["open"]:
                buy_score += 1

            elif last["close"] < last["open"]:
                sell_score += 1

    # 5. Short-term direction
    if last["close"] > three_back["close"]:
        buy_score += 1

    elif last["close"] < three_back["close"]:
        sell_score += 1

    # Strong signal filter
    if buy_score >= 4 and buy_score > sell_score:
        return "BUY", buy_score, sell_score

    if sell_score >= 4 and sell_score > buy_score:
        return "SELL", buy_score, sell_score

    return "HOLD", buy_score, sell_score


def calculate_sl_tp(signal, entry):

    if signal == "BUY":

        stop_loss = entry * 0.995
        take_profit = entry * 1.010

    elif signal == "SELL":

        stop_loss = entry * 1.005
        take_profit = entry * 0.990

    else:

        stop_loss = None
        take_profit = None

    return stop_loss, take_profit


def main():

    print("⚡ ATI BOT - STAGE 6")
    print("₿ BTC/USDT")
    print("⏱ Timeframe: 5m")
    print()

    # Market data
    trades = get_trades()

    print(f"📊 Trades received: {len(trades)}")

    if not trades:
        raise Exception("No trades received")

    print("✅ Tabdeal Market API: OK")

    # Build 5m candles
    candles = build_candles(trades)

    print(f"🕯 5M candles built: {len(candles)}")

    if len(candles) < 6:
        raise Exception(
            "Not enough 5M candles"
        )

    # Use latest completed candle
    candle_time, candle = candles[-1]

    entry = candle["close"]

    signal, buy_score, sell_score = calculate_signal(
        candles
    )

    stop_loss, take_profit = calculate_sl_tp(
        signal,
        entry
    )

    message = (
        "⚡ ATI CRYPTO BOT - STAGE 6\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "💪 STRONG SIGNAL FILTER\n\n"
        f"📊 SIGNAL: {signal}\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n\n"
        f"🕐 Candle: "
        f"{candle_time.strftime('%H:%M')} UTC\n"
        f"💰 Entry: ${entry:,.2f}\n"
    )

    if signal == "BUY":

        message += (
            "\n🟢 BUY SIGNAL\n"
            f"🛑 SL: ${stop_loss:,.2f}\n"
            f"🎯 TP: ${take_profit:,.2f}\n"
        )

    elif signal == "SELL":

        message += (
            "\n🔴 SELL SIGNAL\n"
            f"🛑 SL: ${stop_loss:,.2f}\n"
            f"🎯 TP: ${take_profit:,.2f}\n"
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

    print()
    print(message)

    send_telegram(message)


if __name__ == "__main__":
    main()
