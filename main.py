import os
import requests
from datetime import datetime, timezone

# ============================================================
# ATI CRYPTO BOT - STAGE 8 LIVE
# TABDEAL FUTURES
# BTCUSDT / 5m
# ============================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TABDEAL_API_KEY = os.getenv("TABDEAL_API_KEY")
TABDEAL_API_SECRET = os.getenv("TABDEAL_API_SECRET")

LIVE_TRADING = os.getenv("LIVE_TRADING", "FALSE").upper() == "TRUE"

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"

ORDER_QTY = os.getenv("ORDER_QTY", "0.001")

STRONG_SCORE = 5


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials missing.")
        return False

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        r = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=15
        )

        print("Telegram:", r.status_code)

        return r.ok

    except Exception as e:
        print("Telegram error:", e)
        return False


# ============================================================
# TABDEAL CLIENT
# ============================================================

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


# ============================================================
# API PING
# ============================================================

def check_tabdeal_connection(client):

    try:

        client.ping()

        print("Tabdeal Futures API: OK")

        return True

    except Exception as e:

        print("Tabdeal Futures API ERROR:", e)

        return False


# ============================================================
# POSITION CHECK
# ============================================================

def get_existing_position(client):

    methods = [
        "position_information",
        "get_position",
        "position_risk"
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
                f"Position check failed: {method_name}",
                e
            )

    raise RuntimeError(
        "Open position state could not be safely verified."
    )


def extract_position(data):

    if data is None:
        return None

    if isinstance(data, dict):

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

            if item.get("symbol") not in (None, SYMBOL):
                continue

            if "positionAmt" in item:
                return item

            if "quantity" in item:
                return item

    return None


def position_is_open(position):

    if position is None:
        return False

    values = [
        position.get("positionAmt"),
        position.get("quantity"),
        position.get("qty"),
        position.get("size")
    ]

    for value in values:

        if value is None:
            continue

        try:

            if abs(float(value)) > 0:
                return True

            return False

        except Exception:
            continue

    return False


# ============================================================
# REAL ORDER
# ============================================================

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
    # SAFETY CHECK
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
    # SEND MARKET ORDER
    # --------------------------------------------------------

    try:

        from tabdeal.enums import OrderSides, OrderTypes

        if signal == "BUY":
            side = OrderSides.BUY
        else:
            side = OrderSides.SELL

        order = client.new_order(
            symbol=SYMBOL,
            side=side,
            type=OrderTypes.MARKET,
            quantity=str(ORDER_QTY)
        )

        print("REAL ORDER:")
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


# ============================================================
# MARKET DATA
# ============================================================

def get_market_data():

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

        return response.json()

    except Exception as e:

        print("Market data error:", e)

        return None


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_candles(trades):

    if not trades:
        return []

    candles = {}

    for trade in trades:

        try:

            if not isinstance(trade, dict):
                continue

            price = float(
                trade.get("price")
                or trade.get("p")
            )

            timestamp = (
                trade.get("time")
                or trade.get("timestamp")
                or trade.get("T")
            )

            if timestamp is None:
                continue

            timestamp = int(timestamp)

            if timestamp > 10_000_000_000:
                timestamp //= 1000

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

                c = candles[candle_time]

                c["high"] = max(
                    c["high"],
                    price
                )

                c["low"] = min(
                    c["low"],
                    price
                )

                c["close"] = price

        except Exception:
            continue

    return sorted(
        candles.values(),
        key=lambda x: x["time"]
    )


# ============================================================
# STAGE 8 SIGNAL
# ============================================================

def calculate_signal(candles):

    if len(candles) < 10:

        return {
            "signal": "NO SIGNAL",
            "buy_score": 0,
            "sell_score": 0
        }

    # Last CLOSED candle
    c = candles[-2]

    prev = candles[-3]

    open_price = float(c["open"])
    high = float(c["high"])
    low = float(c["low"])
    close = float(c["close"])

    prev_close = float(prev["close"])

    buy_score = 0
    sell_score = 0

    # --------------------------------------------------------
    # 1. Candle direction
    # --------------------------------------------------------

    if close > open_price:
        buy_score += 1

    elif close < open_price:
        sell_score += 1

    # --------------------------------------------------------
    # 2. Previous candle comparison
    # --------------------------------------------------------

    if close > prev_close:
        buy_score += 1

    elif close < prev_close:
        sell_score += 1

    # --------------------------------------------------------
    # 3. Close position
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
    # 4. Momentum
    # --------------------------------------------------------

    recent = [
        float(x["close"])
        for x in candles[-6:]
    ]

    if len(recent) >= 5:

        if recent[-1] > recent[0]:
            buy_score += 1

        elif recent[-1] < recent[0]:
            sell_score += 1

    # --------------------------------------------------------
    # 5. Structure
    # --------------------------------------------------------

    highs = [
        float(x["high"])
        for x in candles[-5:]
    ]

    lows = [
        float(x["low"])
        for x in candles[-5:]
    ]

    if close >= max(highs[:-1]):
        buy_score += 1

    if close <= min(lows[:-1]):
        sell_score += 1

    # --------------------------------------------------------
    # STRONG SIGNAL
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


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

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

    if LIVE_TRADING:

        mode = "🔴 MODE: LIVE"

    else:

        mode = "🧪 MODE: PAPER/TEST"

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

{mode}
"""

    if order_result:

        if order_result.get("success"):

            message += """
            
✅ REAL ORDER SENT
"""

            message += (
                "\n📦 ORDER:\n"
                + str(order_result.get("order"))
            )

        else:

            message += f"""

🛡 ATI SAFETY

❌ Trade skipped.
{order_result.get("reason", "Unknown error")}
"""

    return message.strip()


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("ATI CRYPTO BOT - STAGE 8 LIVE")
    print("TABDEAL FUTURES")
    print("BTCUSDT / 5m")
    print("=" * 60)

    # --------------------------------------------------------
    # CREATE CLIENT
    # --------------------------------------------------------

    try:

        client = create_tabdeal_client()

    except Exception as e:

        print(e)

        send_telegram(
            f"""
🛡 ATI SAFETY

Bot stopped.

❌ {e}
""".strip()
        )

        return

    # --------------------------------------------------------
    # API CHECK
    # --------------------------------------------------------

    if not check_tabdeal_connection(client):

        send_telegram(
            """
🛡 ATI SAFETY

Bot stopped.

❌ Tabdeal Futures API connection failed.
No order was sent.
""".strip()
        )

        return

    # --------------------------------------------------------
    # MARKET DATA
    # --------------------------------------------------------

    trades = get_market_data()

    if not trades:

        send_telegram(
            """
🛡 ATI SAFETY

Bot stopped.

❌ Market data unavailable.
No order was sent.
""".strip()
        )

        return

    candles = build_candles(trades)

    print("5m candles:", len(candles))

    if len(candles) < 10:

        send_telegram(
            """
🛡 ATI SAFETY

Bot stopped.

❌ Not enough 5m candles.
No order was sent.
""".strip()
        )

        return

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    signal_data = calculate_signal(candles)

    print(
        "SIGNAL:",
        signal_data["signal"]
    )

    print(
        "BUY SCORE:",
        signal_data["buy_score"]
    )

    print(
        "SELL SCORE:",
        signal_data["sell_score"]
    )

    # --------------------------------------------------------
    # NO SIGNAL
    # --------------------------------------------------------

    if signal_data["signal"] == "NO SIGNAL":

        send_telegram(
            build_message(signal_data)
        )

        return

    # --------------------------------------------------------
    # REAL TRADE
    # --------------------------------------------------------

    order_result = place_real_market_order(
        client,
        signal_data["signal"]
    )

    # --------------------------------------------------------
    # TELEGRAM RESULT
    # --------------------------------------------------------

    send_telegram(
        build_message(
            signal_data,
            order_result
        )
    )

    print("=" * 60)
    print("BOT FINISHED")
    print("=" * 60)


if __name__ == "__main__":
    main()
