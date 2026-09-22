import os
import requests
from datetime import datetime, timezone

# =========================
# SETTINGS
# =========================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api1.tabdeal.org"
SYMBOL = "BTCUSDT"

TIMEFRAME_MINUTES = 5

SL_PERCENT = 0.50
TP_PERCENT = 1.00

# =========================
# TELEGRAM
# =========================

def send_telegram(message):
    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is missing")
        return False

    if not CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID is missing")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print("Telegram HTTP:", response.status_code)
        print("Telegram response:", response.text)

        if response.ok:
            print("✅ Telegram message sent")
            return True

        print("❌ Telegram send failed")
        return False

    except Exception as e:
        print("❌ Telegram error:", e)
        return False


# =========================
# TABDEAL MARKET DATA
# =========================

def get_trades():
    url = f"{BASE_URL}/v1/public/trades"

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

    data = response.json()

    if isinstance(data, dict):
        for key in ["data", "result", "trades"]:
            if key in data:
                data = data[key]
                break

    if not isinstance(data, list):
        raise ValueError("Unexpected trades response")

    return data


# =========================
# BUILD 5M CANDLES
# =========================

def build_5m_candles(trades):

    candles = {}

    for trade in trades:

        try:
            price = float(
                trade.get("price")
                or trade.get("p")
                or trade.get("tradePrice")
            )

            quantity = float(
                trade.get("quantity")
                or trade.get("qty")
                or trade.get("amount")
                or trade.get("q")
                or 0
            )

            timestamp = (
                trade.get("timestamp")
                or trade.get("time")
                or trade.get("tradeTime")
                or trade.get("T")
            )

            timestamp = int(timestamp)

            if timestamp < 10000000000:
                timestamp *= 1000

            bucket = timestamp - (
                timestamp % (5 * 60 * 1000)
            )

            if bucket not in candles:

                candles[bucket] = {
                    "time": bucket,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": quantity
                }

            else:

                candle = candles[bucket]

                candle["high"] = max(
                    candle["high"],
                    price
                )

                candle["low"] = min(
                    candle["low"],
                    price
                )

                candle["close"] = price

                candle["volume"] += quantity

        except Exception:
            continue

    result = list(candles.values())

    result.sort(
        key=lambda x: x["time"]
    )

    return result


# =========================
# CLOSED CANDLE
# =========================

def get_closed_candles(candles):

    if len(candles) < 6:
        return []

    now_ms = int(
        datetime.now(timezone.utc).timestamp() * 1000
    )

    current_bucket = now_ms - (
        now_ms % (5 * 60 * 1000)
    )

    closed = [
        c for c in candles
        if c["time"] < current_bucket
    ]

    return closed


# =========================
# SIGNAL ENGINE
# =========================

def calculate_signal(candles):

    if len(candles) < 6:
        return None

    c1 = candles[-1]
    c2 = candles[-2]
    c3 = candles[-3]
    c4 = candles[-4]
    c5 = candles[-5]

    buy_score = 0
    sell_score = 0

    # -------------------------
    # 1. PRICE DIRECTION
    # -------------------------

    if c1["close"] > c2["close"]:
        buy_score += 1

    if c1["close"] < c2["close"]:
        sell_score += 1

    # -------------------------
    # 2. HIGH / LOW STRUCTURE
    # -------------------------

    if (
        c1["high"] > c2["high"]
        and c1["low"] > c2["low"]
    ):
        buy_score += 1

    if (
        c1["high"] < c2["high"]
        and c1["low"] < c2["low"]
    ):
        sell_score += 1

    # -------------------------
    # 3. CANDLE BODY
    # -------------------------

    body = c1["close"] - c1["open"]

    candle_range = c1["high"] - c1["low"]

    if candle_range > 0:

        body_ratio = abs(body) / candle_range

        if body > 0 and body_ratio >= 0.45:
            buy_score += 1

        if body < 0 and body_ratio >= 0.45:
            sell_score += 1

    # -------------------------
    # 4. SHORT MOMENTUM
    # -------------------------

    previous_move = c2["close"] - c3["close"]
    current_move = c1["close"] - c2["close"]

    if (
        current_move > 0
        and previous_move > 0
    ):
        buy_score += 1

    if (
        current_move < 0
        and previous_move < 0
    ):
        sell_score += 1

    # -------------------------
    # 5. BREAKOUT
    # -------------------------

    previous_high = max(
        c2["high"],
        c3["high"],
        c4["high"],
        c5["high"]
    )

    previous_low = min(
        c2["low"],
        c3["low"],
        c4["low"],
        c5["low"]
    )

    if c1["close"] > previous_high:
        buy_score += 1

    if c1["close"] < previous_low:
        sell_score += 1

    # -------------------------
    # STRONG SIGNAL
    # -------------------------

    if buy_score >= 4 and buy_score > sell_score:
        signal = "BUY"

    elif sell_score >= 4 and sell_score > buy_score:
        signal = "SELL"

    else:
        signal = "NO SIGNAL"

    return {
        "signal": signal,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "candle": c1
    }


# =========================
# MESSAGE
# =========================

def build_message(result):

    candle = result["candle"]

    signal = result["signal"]

    entry = candle["close"]

    buy_score = result["buy_score"]
    sell_score = result["sell_score"]

    candle_time = datetime.fromtimestamp(
        candle["time"] / 1000,
        tz=timezone.utc
    ).strftime("%H:%M UTC")

    message = (
        "⚡ ATI CRYPTO BOT - STAGE 8\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "💪 STRONG SIGNAL FILTER\n\n"
        f"📊 SIGNAL: {signal}\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n\n"
        f"🕐 Candle: {candle_time}\n"
        f"💰 Entry: ${entry:,.2f}\n"
    )

    if signal == "BUY":

        sl = entry * (1 - SL_PERCENT / 100)
        tp = entry * (1 + TP_PERCENT / 100)

        message += (
            "\n🟢 BUY SIGNAL\n"
            f"🛑 SL: ${sl:,.2f}\n"
            f"🎯 TP: ${tp:,.2f}\n\n"
            "🧪 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

    elif signal == "SELL":

        sl = entry * (1 + SL_PERCENT / 100)
        tp = entry * (1 - TP_PERCENT / 100)

        message += (
            "\n🔴 SELL SIGNAL\n"
            f"🛑 SL: ${sl:,.2f}\n"
            f"🎯 TP: ${tp:,.2f}\n\n"
            "🧪 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

    else:

        message += (
            "\n⏳ NO STRONG SIGNAL\n\n"
            "🧪 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

    return message


# =========================
# MAIN
# =========================

def main():

    print("================================")
    print("⚡ ATI CRYPTO BOT - STAGE 8")
    print("================================")

    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN missing")
        return

    if not CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID missing")
        return

    try:

        print("📡 Getting Tabdeal trades...")

        trades = get_trades()

        print(
            f"✅ Trades received: {len(trades)}"
        )

        candles = build_5m_candles(trades)

        print(
            f"🕯 5M candles built: {len(candles)}"
        )

        closed = get_closed_candles(candles)

        print(
            f"✅ Closed candles: {len(closed)}"
        )

        if len(closed) < 6:

            send_telegram(
                "⚠️ ATI BOT\n\n"
                "Not enough closed 5M candles."
            )

            return

        result = calculate_signal(closed)

        if not result:

            print("❌ Signal calculation failed")
            return

        message = build_message(result)

        print("\n" + message)

        send_telegram(message)

        print("================================")
        print("✅ ATI STAGE 8 FINISHED")
        print("================================")

    except Exception as e:

        error_message = (
            "🚨 ATI BOT ERROR\n\n"
            f"{type(e).__name__}: {e}\n\n"
            "🧪 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

        print(error_message)

        send_telegram(error_message)


if __name__ == "__main__":
    main()
