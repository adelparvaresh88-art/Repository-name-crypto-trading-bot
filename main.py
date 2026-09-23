import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from datetime import datetime, timezone

# =========================
# ATI CRYPTO BOT
# TABDEAL FUTURES
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

# Risk
SL_PERCENT = 0.005   # 0.5%
TP_PERCENT = 0.010   # 1%

# فقط سیگنال کاملاً قوی
SIGNAL_THRESHOLD = 4


# =========================
# TELEGRAM
# =========================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        return

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=15
        )
    except Exception:
        pass


# =========================
# SIGNED REQUEST
# =========================

def signed_request(method, path, params=None):

    if not API_KEY or not API_SECRET:
        raise Exception("TABDEAL_API_KEY / TABDEAL_API_SECRET missing")

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
# BUILD 5M CANDLES
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

        minute = timestamp // 300000
        candle_time = minute * 300000

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

    # آخرین کندل را استفاده نمی‌کنیم
    # چون ممکن است هنوز باز باشد
    current = candles[-2]
    previous = candles[-3]

    buy_score = 0
    sell_score = 0

    # 1. Candle direction
    if current["close"] > current["open"]:
        buy_score += 1

    elif current["close"] < current["open"]:
        sell_score += 1

    # 2. Close vs previous close
    if current["close"] > previous["close"]:
        buy_score += 1

    elif current["close"] < previous["close"]:
        sell_score += 1

    # 3. Higher high / lower high
    if current["high"] > previous["high"]:
        buy_score += 1

    elif current["high"] < previous["high"]:
        sell_score += 1

    # 4. Higher low / lower low
    if current["low"] > previous["low"]:
        buy_score += 1

    elif current["low"] < previous["low"]:
        sell_score += 1

    # 5. Strong body
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

    if buy_score >= SIGNAL_THRESHOLD and buy_score > sell_score:
        signal = "BUY"

    elif sell_score >= SIGNAL_THRESHOLD and sell_score > buy_score:
        signal = "SELL"

    return signal, buy_score, sell_score


# =========================
# POSITION
# =========================

def get_positions():

    return signed_request(
        "GET",
        "/fapi/v1/position",
        {
            "symbol": SYMBOL
        }
    )


def get_open_position():

    positions = get_positions()

    if isinstance(positions, dict):
        positions = [positions]

    if not isinstance(positions, list):
        return None

    for position in positions:

        symbol = str(
            position.get("symbol", "")
        ).upper()

        if symbol != SYMBOL:
            continue

        amount = (
            position.get("positionAmt")
            or position.get("quantity")
            or position.get("qty")
            or position.get("amount")
        )

        if amount is None:
            continue

        try:
            amount = float(amount)
        except Exception:
            continue

        if abs(amount) > 0:

            return position

    return None


# =========================
# MARKET ORDER
# =========================

def place_market_order(signal):

    side = "BUY" if signal == "BUY" else "SELL"

    return signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": SYMBOL,
            "side": side,
            "type": "MARKET",
            "quantity": ORDER_QTY
        }
    )


# =========================
# SL / TP
# =========================

def calculate_sl_tp(entry_price, signal):

    if signal == "BUY":

        sl = entry_price * (1 - SL_PERCENT)
        tp = entry_price * (1 + TP_PERCENT)

    else:

        sl = entry_price * (1 + SL_PERCENT)
        tp = entry_price * (1 - TP_PERCENT)

    return sl, tp


def set_sl_tp(position, signal):

    position_id = (
        position.get("positionId")
        or position.get("id")
    )

    entry_price = float(
        position.get("entryPrice")
        or position.get("avgPrice")
        or position.get("price")
    )

    if not position_id:
        raise Exception("positionId not found")

    sl, tp = calculate_sl_tp(
        entry_price,
        signal
    )

    result = signed_request(
        "POST",
        "/fapi/v1/positionSlTp",
        {
            "positionId": position_id,
            "symbol": SYMBOL,
            "slPrice": f"{sl:.2f}",
            "tpPrice": f"{tp:.2f}"
        }
    )

    return entry_price, sl, tp, result


# =========================
# EMERGENCY CLOSE
# =========================

def emergency_close():

    return signed_request(
        "DELETE",
        "/fapi/v1/position",
        {
            "symbol": SYMBOL
        }
    )


# =========================
# MAIN
# =========================

def main():

    try:

        # -------------------------
        # Secrets check
        # -------------------------

        missing = []

        if not API_KEY:
            missing.append("TABDEAL_API_KEY")

        if not API_SECRET:
            missing.append("TABDEAL_API_SECRET")

        if not BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")

        if not CHAT_ID:
            missing.append("TELEGRAM_CHAT_ID")

        if missing:

            message = (
                "🛡 ATI SAFETY\n\n"
                "❌ Missing secrets:\n"
                + "\n".join(missing)
            )

            send_telegram(message)

            print(message)

            return


        # -------------------------
        # Market data
        # -------------------------

        trades = get_trades()

        candles = build_candles(trades)

        signal, buy_score, sell_score = calculate_signal(
            candles
        )

        current_candle = candles[-2]

        entry_price = float(
            current_candle["close"]
        )

        candle_time = datetime.fromtimestamp(
            current_candle["time"] / 1000,
            tz=timezone.utc
        ).strftime("%H:%M")


        # -------------------------
        # No signal
        # -------------------------

        if signal == "NO SIGNAL":

            message = (
                "⚡ ATI CRYPTO BOT\n\n"
                "₿ BTC/USDT\n"
                "⏱ Timeframe: 5m\n"
                "✅ CLOSED CANDLE\n"
                "💪 STRONG SIGNAL FILTER\n\n"
                f"📊 SIGNAL: NO SIGNAL\n"
                f"📈 BUY SCORE: {buy_score}/5\n"
                f"📉 SELL SCORE: {sell_score}/5\n\n"
                f"🕐 Candle: {candle_time} UTC\n"
                f"💰 Price: ${entry_price:,.2f}\n\n"
                "⏳ NO TRADE"
            )

            send_telegram(message)

            print(message)

            return


        # -------------------------
        # Existing position check
        # -------------------------

        try:

            existing_position = get_open_position()

        except Exception as e:

            message = (
                "🛡 ATI SAFETY\n\n"
                "❌ Position check failed.\n"
                "No order was sent.\n\n"
                f"{e}"
            )

            send_telegram(message)

            print(message)

            return


        if existing_position:

            message = (
                "🛡 ATI SAFETY\n\n"
                "⚠️ Existing Futures position detected.\n"
                "No new order was sent."
            )

            send_telegram(message)

            print(message)

            return


        # -------------------------
        # Signal found
        # -------------------------

        signal_message = (
            "🚨 ATI REAL TRADE SIGNAL\n\n"
            "₿ BTC/USDT FUTURES\n"
            "⏱ 5m\n"
            "✅ CLOSED CANDLE\n\n"
            f"📊 SIGNAL: {signal}\n"
            f"📈 BUY SCORE: {buy_score}/5\n"
            f"📉 SELL SCORE: {sell_score}/5\n\n"
            f"💰 Entry: ${entry_price:,.2f}\n"
            f"💵 ORDER QTY: {ORDER_QTY}\n"
            f"🔴 LIVE TRADING: {LIVE_TRADING}"
        )

        send_telegram(signal_message)

        print(signal_message)


        # -------------------------
        # LIVE TRADING protection
        # -------------------------

        if LIVE_TRADING != "TRUE":

            message = (
                "🛡 ATI SAFETY\n\n"
                "⚠️ LIVE_TRADING is not TRUE.\n"
                "No real order was sent."
            )

            send_telegram(message)

            print(message)

            return


        # -------------------------
        # REAL MARKET ORDER
        # -------------------------

        order = place_market_order(signal)

        print("ORDER RESPONSE:")
        print(order)


        # -------------------------
        # Wait for position
        # -------------------------

        position = None

        for _ in range(10):

            time.sleep(1)

            position = get_open_position()

            if position:
                break


        if not position:

            message = (
                "🚨 ATI TRADE ERROR\n\n"
                "Order was submitted but position "
                "could not be confirmed.\n\n"
                f"Order:\n{order}"
            )

            send_telegram(message)

            print(message)

            return


        # -------------------------
        # SL / TP
        # -------------------------

        try:

            entry, sl, tp, sltp_result = set_sl_tp(
                position,
                signal
            )

        except Exception as e:

            send_telegram(
                "🚨 ATI EMERGENCY\n\n"
                "❌ SL/TP installation failed.\n"
                "Attempting emergency close..."
            )

            try:

                emergency_close()

                send_telegram(
                    "🛡 ATI SAFETY\n\n"
                    "✅ Emergency close completed.\n"
                    "Position was closed because SL/TP "
                    "could not be installed."
                )

            except Exception as close_error:

                send_telegram(
                    "🚨 CRITICAL ATI ERROR\n\n"
                    "❌ SL/TP failed.\n"
                    "❌ Emergency close also failed.\n\n"
                    f"{close_error}"
                )

            print(e)

            return


        # -------------------------
        # SUCCESS
        # -------------------------

        message = (
            "✅ ATI REAL TRADE OPENED\n\n"
            "₿ BTC/USDT FUTURES\n"
            f"📊 SIDE: {signal}\n"
            "⏱ 5m\n\n"
            f"💰 ENTRY: ${entry:,.2f}\n"
            f"🛑 SL: ${sl:,.2f}\n"
            f"🎯 TP: ${tp:,.2f}\n"
            f"💵 QTY: {ORDER_QTY}\n\n"
            "🔴 LIVE TRADING: TRUE\n"
            "✅ REAL ORDER SENT\n"
            "✅ SL INSTALLED\n"
            "✅ TP INSTALLED"
        )

        send_telegram(message)

        print(message)


    except Exception as e:

        error_message = (
            "🚨 ATI BOT ERROR\n\n"
            f"{type(e).__name__}\n"
            f"{e}"
        )

        send_telegram(error_message)

        print(error_message)


if __name__ == "__main__":
    main()
