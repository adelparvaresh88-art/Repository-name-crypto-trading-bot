import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from datetime import datetime, timezone

# =========================
# ATI CRYPTO BOT
# TELEGRAM TEST VERSION
# =========================

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"

API_KEY = os.getenv("TABDEAL_API_KEY")
API_SECRET = os.getenv("TABDEAL_API_SECRET")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LIVE_TRADING = os.getenv("LIVE_TRADING", "FALSE").upper()
ORDER_QTY = os.getenv("ORDER_QTY", "0.001")

SL_PERCENT = 0.005
TP_PERCENT = 0.010

SIGNAL_THRESHOLD = 4


# =========================
# TELEGRAM
# =========================

def send_telegram(message):

    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN missing")
        return False

    if not CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID missing")
        return False

    try:

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

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

        if response.status_code == 200:

            data = response.json()

            if data.get("ok") is True:
                print("✅ TELEGRAM SEND: OK")
                return True

        print("❌ TELEGRAM SEND: FAILED")
        return False

    except Exception as e:

        print("❌ TELEGRAM ERROR:", e)
        return False


# =========================
# TELEGRAM CONNECTION TEST
# =========================

def telegram_test():

    message = (
        "🧪 ATI TELEGRAM TEST\n\n"
        "✅ Telegram connection is working.\n"
        "🤖 ATI CRYPTO BOT is running.\n\n"
        "📡 Test message received successfully."
    )

    return send_telegram(message)


# =========================
# SIGNED REQUEST
# =========================

def signed_request(method, path, params=None):

    if not API_KEY or not API_SECRET:
        raise Exception(
            "TABDEAL_API_KEY / TABDEAL_API_SECRET missing"
        )

    params = params or {}

    params["timestamp"] = int(time.time() * 1000)

    query = urlencode(params)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    params["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = BASE_URL + path

    if method == "GET":

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=20
        )

    elif method == "POST":

        response = requests.post(
            url,
            data=params,
            headers=headers,
            timeout=20
        )

    elif method == "DELETE":

        response = requests.delete(
            url,
            params=params,
            headers=headers,
            timeout=20
        )

    else:
        raise Exception("Unsupported HTTP method")

    if response.status_code >= 400:
        raise Exception(
            f"HTTP {response.status_code}: {response.text}"
        )

    return response.json()


# =========================
# MARKET DATA
# =========================

def get_trades():

    url = f"{BASE_URL}/api/v1/trades"

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


# =========================
# BUILD CANDLES
# =========================

def build_candles(trades):

    candles = {}

    for trade in trades:

        price = float(
            trade.get("price")
            or trade.get("p")
        )

        timestamp = int(
            trade.get("time")
            or trade.get("T")
        )

        candle_id = timestamp // 300000
        candle_time = candle_id * 300000

        if candle_time not in candles:

            candles[candle_time] = {
                "time": candle_time,
                "open": price,
                "high": price,
                "low": price,
                "close": price
            }

        else:

            candles[candle_time]["high"] = max(
                candles[candle_time]["high"],
                price
            )

            candles[candle_time]["low"] = min(
                candles[candle_time]["low"],
                price
            )

            candles[candle_time]["close"] = price

    return sorted(
        candles.values(),
        key=lambda x: x["time"]
    )


# =========================
# SIGNAL
# =========================

def calculate_signal(candles):

    if len(candles) < 3:

        return "NO SIGNAL", 0, 0

    current = candles[-2]
    previous = candles[-3]

    buy_score = 0
    sell_score = 0

    # 1. Candle direction

    if current["close"] > current["open"]:
        buy_score += 1

    elif current["close"] < current["open"]:
        sell_score += 1

    # 2. Close comparison

    if current["close"] > previous["close"]:
        buy_score += 1

    elif current["close"] < previous["close"]:
        sell_score += 1

    # 3. High

    if current["high"] > previous["high"]:
        buy_score += 1

    elif current["high"] < previous["high"]:
        sell_score += 1

    # 4. Low

    if current["low"] > previous["low"]:
        buy_score += 1

    elif current["low"] < previous["low"]:
        sell_score += 1

    # 5. Candle body strength

    candle_range = current["high"] - current["low"]

    if candle_range > 0:

        body = abs(
            current["close"] - current["open"]
        )

        body_strength = body / candle_range

        if body_strength >= 0.55:

            if current["close"] > current["open"]:
                buy_score += 1

            elif current["close"] < current["open"]:
                sell_score += 1

    signal = "NO SIGNAL"

    if (
        buy_score >= SIGNAL_THRESHOLD
        and buy_score > sell_score
    ):
        signal = "BUY"

    elif (
        sell_score >= SIGNAL_THRESHOLD
        and sell_score > buy_score
    ):
        signal = "SELL"

    return signal, buy_score, sell_score


# =========================
# MAIN
# =========================

def main():

    print("================================")
    print("ATI CRYPTO BOT")
    print("================================")

    # --------------------------------
    # Telegram test ALWAYS runs first
    # --------------------------------

    telegram_ok = telegram_test()

    if not telegram_ok:

        print(
            "⚠️ Telegram test failed."
        )

        # ادامه نمی‌دهیم تا مشکل Telegram
        # مشخص باشد.
        return

    # --------------------------------
    # Secrets check
    # --------------------------------

    missing = []

    if not API_KEY:
        missing.append("TABDEAL_API_KEY")

    if not API_SECRET:
        missing.append("TABDEAL_API_SECRET")

    if missing:

        message = (
            "🛡 ATI SAFETY\n\n"
            "❌ Missing Tabdeal secrets:\n"
            + "\n".join(missing)
        )

        send_telegram(message)

        print(message)

        return

    # --------------------------------
    # Market data
    # --------------------------------

    try:

        trades = get_trades()

        candles = build_candles(trades)

        if len(candles) < 3:

            message = (
                "⚠️ ATI CRYPTO BOT\n\n"
                "❌ Not enough candle data."
            )

            send_telegram(message)

            return

        signal, buy_score, sell_score = calculate_signal(
            candles
        )

        current = candles[-2]

        price = float(current["close"])

        candle_time = datetime.fromtimestamp(
            current["time"] / 1000,
            tz=timezone.utc
        ).strftime("%H:%M")

        # --------------------------------
        # NO SIGNAL
        # --------------------------------

        if signal == "NO SIGNAL":

            message = (
                "⚡ ATI CRYPTO BOT\n\n"
                "₿ BTC/USDT\n"
                "⏱ Timeframe: 5m\n"
                "✅ CLOSED CANDLE\n"
                "💪 STRONG SIGNAL FILTER\n\n"
                "📊 SIGNAL: NO SIGNAL\n"
                f"📈 BUY SCORE: {buy_score}/5\n"
                f"📉 SELL SCORE: {sell_score}/5\n\n"
                f"🕐 Candle: {candle_time} UTC\n"
                f"💰 Price: ${price:,.2f}\n\n"
                "⏳ NO TRADE\n\n"
                "📡 TELEGRAM TEST: OK"
            )

            telegram_result = send_telegram(message)

            print(message)
            print(
                "Telegram result:",
                telegram_result
            )

            return

        # --------------------------------
        # SIGNAL
        # --------------------------------

        message = (
            "🚨 ATI CRYPTO BOT\n\n"
            "₿ BTC/USDT FUTURES\n"
            "⏱ Timeframe: 5m\n"
            "✅ CLOSED CANDLE\n\n"
            f"📊 SIGNAL: {signal}\n"
            f"📈 BUY SCORE: {buy_score}/5\n"
            f"📉 SELL SCORE: {sell_score}/5\n\n"
            f"💰 Entry: ${price:,.2f}\n"
            f"🔴 LIVE TRADING: {LIVE_TRADING}\n"
            f"💵 ORDER QTY: {ORDER_QTY}\n\n"
            "📡 TELEGRAM TEST: OK"
        )

        send_telegram(message)

        print(message)

        # --------------------------------
        # IMPORTANT
        # --------------------------------
        #
        # معامله واقعی در این تست دست‌کاری نشده.
        # فقط Telegram و signal را تست می‌کنیم.
        #
        # --------------------------------

    except Exception as e:

        error = (
            "🚨 ATI CRYPTO BOT ERROR\n\n"
            f"{type(e).__name__}\n"
            f"{e}"
        )

        print(error)

        send_telegram(error)


if __name__ == "__main__":
    main()
