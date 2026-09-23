import os
import json
import time
import requests
from datetime import datetime, timezone

# ============================================================
# ATI CRYPTO BOT - STAGE 8
# TABDEAL FUTURES - LIVE TRADING
# BTCUSDT / 5 MINUTES
# ============================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TABDEAL_API_KEY = os.getenv("TABDEAL_API_KEY")
TABDEAL_API_SECRET = os.getenv("TABDEAL_API_SECRET")

# ------------------------------------------------------------
# LIVE SWITCH
# ------------------------------------------------------------
# Must be exactly TRUE before real orders are allowed.
LIVE_TRADING = os.getenv("LIVE_TRADING", "FALSE").upper() == "TRUE"

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"

# Amount of BTC per real trade.
# IMPORTANT: Change this only after checking your Tabdeal Futures
# minimum quantity and available USDT margin.
ORDER_QTY = os.getenv("ORDER_QTY", "0.001")

# Strong signal requirement
STRONG_SCORE = 5

# ------------------------------------------------------------
# Telegram
# ------------------------------------------------------------

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials missing.")
        return False

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=15
        )

        print("Telegram:", response.status_code)

        return response.ok

    except Exception as e:
        print("Telegram error:", e)
        return False


# ------------------------------------------------------------
# Tabdeal client
# ------------------------------------------------------------

def create_tabdeal_client():

    if not TABDEAL_API_KEY:
        raise RuntimeError("TABDEAL_API_KEY is missing.")

    if not TABDEAL_API_SECRET:
        raise RuntimeError("TABDEAL_API_SECRET is missing.")

    try:
        from tabdeal.future import Future
        return Future(
            TABDEAL_API_KEY,
            TABDEAL_API_SECRET
        )

    except Exception as e:
        raise RuntimeError(
            f"Tabdeal SDK initialization failed: {e}"
        )


# ------------------------------------------------------------
# Check API connection
# ------------------------------------------------------------

def check_tabdeal_connection(client):

    try:
        client.ping()
        print("Tabdeal Futures API: OK")
        return True

    except Exception as e:
        print("Tabdeal Futures API ERROR:", e)
        return False


# ------------------------------------------------------------
# Get Futures exchange information
# ------------------------------------------------------------

def get_exchange_info(client):

    try:
        info = client.exchange_info()

        print("Exchange info received.")

        return info

    except Exception as e:
        print("Exchange info error:", e)
        return None


# ------------------------------------------------------------
# Detect existing BTCUSDT position
# ------------------------------------------------------------

def get_existing_position(client):

    """
    Tries to find an existing BTCUSDT Futures position.

    Tabdeal SDK versions can expose account/position endpoints
    differently, so this function safely tries common methods.

    If the position cannot be verified, trading is BLOCKED.
    """

    methods = [
        "position_information",
        "get_position",
        "position_risk",
        "account"
    ]

    for method_name in methods:

        method = getattr(client, method_name, None)

        if not callable(method):
            continue

        try:

            try:
                result = method(symbol=SYMBOL)
            except TypeError:
                result = method()

            print(
                f"Position check via {method_name}:",
                result
            )

            position = extract_position(result)

            if position is not None:
                return position

        except Exception as e:

            print(
                f"Position method {method_name} failed:",
                e
            )

    # IMPORTANT:
    # Unknown position state means NO TRADE.
    raise RuntimeError(
        "Open position state could not be safely verified."
    )


def extract_position(data):

    if data is None:
        return None

    if isinstance(data, dict):

        # Direct position object
        if "positionAmt" in data:
            return data

        if "quantity" in data:
            return data

        if "position" in data:
            return extract_position(data["position"])

        if "data" in data:
            return extract_position(data["data"])

    if isinstance(data, list):

        for item in data:

            if not isinstance(item, dict):
                continue

            symbol = item.get("symbol")

            if symbol and symbol != SYMBOL:
                continue

            if "positionAmt" in item:
                return item

            if "quantity" in item:
                return item

    return None


def position_is_open(position):

    if position is None:
        return False

    possible_values = [
        position.get("positionAmt"),
        position.get("quantity"),
        position.get("qty"),
        position.get("size")
    ]

    for value in possible_values:

        if value is None:
            continue

        try:
            return abs(float(value)) > 0
        except Exception:
            continue

    return False


# ------------------------------------------------------------
# REAL MARKET ORDER
# ------------------------------------------------------------

def place_real_market_order(client, signal):

    if not LIVE_TRADING:

        return {
            "success": False,
            "blocked": True,
            "reason": "LIVE_TRADING is not TRUE."
        }

    signal = signal.upper()

    if signal not in ("BUY", "SELL"):
        return {
            "success": False,
            "blocked": True,
            "reason": "Invalid signal."
        }

    # --------------------------------------------------------
    # Check existing position BEFORE sending order
    # --------------------------------------------------------

    try:

        position = get_existing_position(client)

        if position_is_open(position):

            return {
                "success": False,
                "blocked": True,
                "reason": "Existing BTCUSDT position detected."
            }

    except Exception as e:

        return {
            "success": False,
            "blocked": True,
            "reason": str(e)
        }

    # --------------------------------------------------------
    # Side
    # --------------------------------------------------------

    try:
        from tabdeal.enums import OrderSides, OrderTypes

        side = (
            OrderSides.BUY
            if signal == "BUY"
            else OrderSides.SELL
        )

        # ----------------------------------------------------
        # REAL ORDER
        # ----------------------------------------------------

        order = client.new_order(
            symbol=SYMBOL,
            side=side,
            type=OrderTypes.MARKET,
            quantity=str(ORDER_QTY)
        )

        print("REAL ORDER RESPONSE:")
        print(order)

        return {
            "success": True,
            "blocked": False,
            "order": order
        }

    except Exception as e:

        print("REAL ORDER ERROR:", e)

        return {
            "success": False,
            "blocked": False,
            "reason": str(e)
        }


# ------------------------------------------------------------
# Candle data
# ------------------------------------------------------------

def get_market_data():

    """
    Uses Tabdeal public market API.

    Returns recent trades and builds 5m candles.
    """

    url = "https://api1.tabdeal.org/v1/trades"

    try:

        response = requests.get(
            url,
            params={
                "symbol": SYMBOL,
                "limit": 1000
            },
            timeout=20
        )

        response.raise_for_status()

        data = response.json()

        return data

    except Exception as e:

        print("Market data error:", e)
        return None


# ------------------------------------------------------------
# Build simple 5m candles
# ------------------------------------------------------------

def build_candles(trades):

    if not trades:
        return []

    candles = {}

    for trade in trades:

        try:

            if isinstance(trade, dict):

                price = float(
                    trade.get("price")
                    or trade.get("p")
                )

                timestamp = (
                    trade.get("time")
                    or trade.get("timestamp")
                    or trade.get("T")
                )

            else:
                continue

            if timestamp is None:
                continue

            timestamp = int(timestamp)

            # milliseconds -> seconds
            if timestamp > 10_000_000_000:
                timestamp = timestamp // 1000

            candle_time = timestamp - (
                timestamp % 300
            )

            if candle_time not in candles:

                candles[candle_time] = {
                    "time": candle_time,
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

        except Exception:
            continue

    result = sorted(
        candles.values(),
        key=lambda x: x["time"]
    )

    return result


# ------------------------------------------------------------
# Stage 8 Signal Engine
# ------------------------------------------------------------

def calculate_signal(candles):

    """
    Stage 8 strong-signal filter.

    BUY requires 5/5.
    SELL requires 5/5.

    This keeps the existing philosophy:
    no weak signal -> no trade.
    """

    if len(candles) < 10:

        return {
            "signal": "NO SIGNAL",
            "buy_score": 0,
            "sell_score": 0
        }

    c = candles[-2]
    prev = candles[-3]

    close = float(c["close"])
    open_price = float(c["open"])
    high = float(c["high"])
    low = float(c["low"])

    prev_close = float(prev["close"])

    buy_score = 0
    sell_score = 0

    # --------------------------------------------------------
    # 1. Candle direction
    # --------------------------------------------------------

    if close > open_price:
        buy_score += 1

    if close < open_price:
        sell_score += 1

    # --------------------------------------------------------
    # 2. Close versus previous close
    # --------------------------------------------------------

    if close > prev_close:
        buy_score += 1

    if close < prev_close:
        sell_score += 1

    # --------------------------------------------------------
    # 3. Candle position
    # --------------------------------------------------------

    candle_range = high - low

    if candle_range > 0:

        close_position = (
            (close - low) / candle_range
        )

        if close_position >= 0.70:
            buy_score += 1

        if close_position <= 0.30:
            sell_score += 1

    # --------------------------------------------------------
    # 4. Recent momentum
    # --------------------------------------------------------

    recent_closes = [
        float(x["close"])
        for x in candles[-6:]
    ]

    if len(recent_closes) >= 5:

        if recent_closes[-1] > recent_closes[0]:
            buy_score += 1

        if recent_closes[-1] < recent_closes[0]:
            sell_score += 1

    # --------------------------------------------------------
    # 5. Higher/lower recent structure
    # --------------------------------------------------------

    recent_highs = [
        float(x["high"])
        for x in candles[-5:]
    ]

    recent_lows = [
        float(x["low"])
        for x in candles[-5:]
    ]

    if close >= max(recent_highs[:-1]):
        buy_score += 1

    if close <= min(recent_lows[:-1]):
        sell_score += 1

    # --------------------------------------------------------
    # Strong signal
    # --------------------------------------------------------

    if buy_score >= STRONG_SCORE:

        signal = "BUY"

    elif sell_score >= STRONG_SCORE:

        signal = "SELL"

    else:

        signal = "NO SIGNAL"

    return {
        "signal": signal,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "price": close,
        "candle": c
    }


# ------------------------------------------------------------
# Telegram message
# ------------------------------------------------------------

def build_message(signal_data, order_result=None):

    signal = signal_data["signal"]
    buy_score = signal_data["buy_score"]
    sell_score = signal_data["sell_score"]
    price = signal_data.get("price", 0)

    candle = signal_data.get("candle")

    if candle:

        candle_time = datetime.fromtimestamp(
            candle["time"],
            tz=timezone.utc
        ).strftime("%H:%M UTC")

    else:

        candle_time = "N/A"

    if signal == "BUY":

        signal_text = "🟢 BUY SIGNAL"

    elif signal == "SELL":

        signal_text = "🔴 SELL SIGNAL"

    else:

        signal_text = "⏳ NO STRONG SIGNAL"

    message = f"""
⚡ ATI CRYPTO BOT - STAGE 8

₿ BTC/USDT
⏱ Timeframe: 5m
✅ CLOSED CANDLE
💪 STRONG SIGNAL FILTER

📊 SIGNAL: {signal}
📈 BUY SCORE: {buy_score}/5
📉 SELL SCORE: {sell_score}/5

🕐 Candle: {candle_time}
💰 Entry: ${price:,.2f}

{signal_text}
"""

    if signal in ("BUY", "SELL"):

        if LIVE_TRADING:

            message += """
🔴 MODE: LIVE
⚠️ REAL FUTURES ORDER
"""

        else:

            message += """
🧪 MODE: PAPER/TEST
"""

    else:

        message += """
⏳ NO TRADE
"""

    if order_result:

        if order_result.get("success"):

            message += """
✅ REAL ORDER SENT
"""

            message += f"""
📦 Order:
{str(order_result.get("order"))}
"""

        else:

            message += f"""
🛡 ATI SAFETY

❌ Trade skipped.
{order_result.get("reason", "Unknown error")}
"""

    return message.strip()


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():

    print("=" * 60)
    print("ATI CRYPTO BOT - STAGE 8")
    print("TABDEAL FUTURES")
    print("BTCUSDT / 5m")
    print("=" * 60)

    # --------------------------------------------------------
    # Telegram test
    # --------------------------------------------------------

    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is missing.")

    if not CHAT_ID:
        print("TELEGRAM_CHAT_ID is missing.")

    # --------------------------------------------------------
    # Tabdeal client
    # --------------------------------------------------------

    try:

        client = create_tabdeal_client()

    except Exception as e:

        message = f"""
🛡 ATI SAFETY

Bot stopped.

❌ {e}
"""

        send_telegram(message)

        print(e)
        return

    # --------------------------------------------------------
    # API connection
    # --------------------------------------------------------

    if not check_tabdeal_connection(client):

        message = """
🛡 ATI SAFETY

Bot stopped.

❌ Tabdeal Futures API connection failed.
No order was sent.
"""

        send_telegram(message)
        return

    # --------------------------------------------------------
    # Market data
    # --------------------------------------------------------

    trades = get_market_data()

    if not trades:

        message = """
🛡 ATI SAFETY

Bot stopped.

❌ Market data unavailable.
No order was sent.
"""

        send_telegram(message)
        return

    candles = build_candles(trades)

    print("5m candles:", len(candles))

    if len(candles) < 10:

        message = """
🛡 ATI SAFETY

Bot stopped.

❌ Not enough 5m candles.
No order was sent.
"""

        send_telegram(message)
        return

    # --------------------------------------------------------
    # Signal
    # --------------------------------------------------------

    signal_data = calculate_signal(candles)

    print("Signal:", signal_data["signal"])
    print("BUY:", signal_data["buy_score"])
    print("SELL:", signal_data["sell_score"])

    # --------------------------------------------------------
    # NO SIGNAL
    # --------------------------------------------------------

    if signal_data["signal"] == "NO SIGNAL":

        message = build_message(signal_data)

        send_telegram(message)

        return

    # --------------------------------------------------------
    # REAL TRADE
    # --------------------------------------------------------

    order_result = place_real_market_order(
        client,
        signal_data["signal"]
    )

    # --------------------------------------------------------
    # Telegram result
    # --------------------------------------------------------

    message = build_message(
        signal_data,
        order_result
    )

    send_telegram(message)

    print("=" * 60)
    print("BOT FINISHED")
    print("=" * 60)


if __name__ == "__main__":
    main()
