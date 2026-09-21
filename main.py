import os
import json
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api1.tabdeal.org"
SIGNAL_FILE = "active_signal.json"


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

    response = requests.get(
        url,
        params={
            "symbol": "BTCUSDT",
            "limit": 1000
        },
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


def get_price(trade):
    value = trade.get("price") or trade.get("p")

    if value is None:
        return None

    return float(value)


def get_time(trade):
    value = (
        trade.get("time")
        or trade.get("timestamp")
        or trade.get("T")
        or trade.get("ts")
    )

    if value is None:
        return None

    value = int(value)

    if value < 100000000000:
        value *= 1000

    return datetime.fromtimestamp(
        value / 1000,
        tz=timezone.utc
    )


def build_candles(trades):
    candles = {}

    for trade in trades:

        price = get_price(trade)
        trade_time = get_time(trade)

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

    buy = 0
    sell = 0

    if last["close"] > last["open"]:
        buy += 1
    elif last["close"] < last["open"]:
        sell += 1

    if last["close"] > previous["close"]:
        buy += 1
    elif last["close"] < previous["close"]:
        sell += 1

    if last["high"] > previous["high"]:
        buy += 1
    elif last["low"] < previous["low"]:
        sell += 1

    candle_range = last["high"] - last["low"]

    if candle_range > 0:

        body = abs(
            last["close"] - last["open"]
        )

        strength = body / candle_range

        if strength >= 0.55:

            if last["close"] > last["open"]:
                buy += 1
            elif last["close"] < last["open"]:
                sell += 1

    if last["close"] > three_back["close"]:
        buy += 1
    elif last["close"] < three_back["close"]:
        sell += 1

    if buy >= 4 and buy > sell:
        return "BUY", buy, sell

    if sell >= 4 and sell > buy:
        return "SELL", buy, sell

    return "HOLD", buy, sell


def calculate_sl_tp(signal, entry):

    if signal == "BUY":
        return entry * 0.995, entry * 1.010

    if signal == "SELL":
        return entry * 1.005, entry * 0.990

    return None, None


def load_signal():

    if not os.path.exists(SIGNAL_FILE):
        return None

    try:
        with open(
            SIGNAL_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except Exception:
        return None


def save_signal(signal, entry, sl, tp, candle_time):

    data = {
        "signal": signal,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "candle_time": candle_time,
        "created_at": datetime.now(
            timezone.utc
        ).isoformat()
    }

    with open(
        SIGNAL_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=2
        )


def clear_signal():

    if os.path.exists(SIGNAL_FILE):
        os.remove(SIGNAL_FILE)


def check_signal(price):

    active = load_signal()

    if not active:
        return False

    signal = active["signal"]
    entry = float(active["entry"])
    sl = float(active["sl"])
    tp = float(active["tp"])

    if signal == "BUY":

        if price >= tp:

            send_telegram(
                "🎯 ATI RESULT\n\n"
                "🟢 BUY\n"
                f"Entry: ${entry:,.2f}\n"
                f"TP: ${tp:,.2f}\n"
                f"Price: ${price:,.2f}\n\n"
                "✅ TP HIT"
            )

            clear_signal()
            return True

        if price <= sl:

            send_telegram(
                "🛑 ATI RESULT\n\n"
                "🟢 BUY\n"
                f"Entry: ${entry:,.2f}\n"
                f"SL: ${sl:,.2f}\n"
                f"Price: ${price:,.2f}\n\n"
                "❌ SL HIT"
            )

            clear_signal()
            return True

    if signal == "SELL":

        if price <= tp:

            send_telegram(
                "🎯 ATI RESULT\n\n"
                "🔴 SELL\n"
                f"Entry: ${entry:,.2f}\n"
                f"TP: ${tp:,.2f}\n"
                f"Price: ${price:,.2f}\n\n"
                "✅ TP HIT"
            )

            clear_signal()
            return True

        if price >= sl:

            send_telegram(
                "🛑 ATI RESULT\n\n"
                "🔴 SELL\n"
                f"Entry: ${entry:,.2f}\n"
                f"SL: ${sl:,.2f}\n"
                f"Price: ${price:,.2f}\n\n"
                "❌ SL HIT"
            )

            clear_signal()
            return True

    return False


def main():

    print("⚡ ATI CRYPTO BOT - STAGE 7")

    trades = get_trades()

    print(f"📊 Trades received: {len(trades)}")

    candles = build_candles(trades)

    print(f"🕯 5M candles built: {len(candles)}")

    if len(candles) < 6:
        raise Exception("Not enough candles")

    current_price = get_price(trades[-1])

    if current_price is None:
        current_price = candles[-1][1]["close"]

    # First check existing signal
    if check_signal(current_price):
        print("✅ Previous signal completed")

    candle_time, candle = candles[-1]

    entry = candle["close"]

    signal, buy_score, sell_score = calculate_signal(
        candles
    )

    sl, tp = calculate_sl_tp(
        signal,
        entry
    )

    if signal in ("BUY", "SELL"):

        save_signal(
            signal,
            entry,
            sl,
            tp,
            candle_time.isoformat()
        )

    message = (
        "⚡ ATI CRYPTO BOT - STAGE 7\n\n"
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

    send_telegram(message)


if __name__ == "__main__":
    main()
