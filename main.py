import os
import requests
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

# =========================================================
# ATI CRYPTO BOT - REAL TRADING
# =========================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TABDEAL_API_KEY = os.getenv("TABDIL_API_KEY")
TABDEAL_API_SECRET = os.getenv("TABDIL_API_SECRET")

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"

# REAL TRADE SIZE
TRADE_USDT = Decimal("2.00")

SL_PERCENT = Decimal("0.50")
TP_PERCENT = Decimal("1.00")

# Strong signal only
SIGNAL_THRESHOLD = 4

# Safety
MAX_BTC_POSITION_USDT = Decimal("2.50")


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials missing")
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

        print("Telegram:", response.status_code)

        return response.ok

    except Exception as e:

        print("Telegram error:", e)

        return False


# =========================================================
# TABDEAL PUBLIC MARKET
# =========================================================

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

    print("Tabdeal market HTTP:", response.status_code)

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):

        for key in ["data", "result", "trades"]:

            if key in data:

                data = data[key]
                break

    if not isinstance(data, list):

        raise ValueError(
            f"Unexpected market response: {data}"
        )

    return data


# =========================================================
# BUILD 5M CANDLES
# =========================================================

def build_5m_candles(trades):

    candles = {}

    for trade in trades:

        try:

            price = float(
                trade.get("price")
            )

            quantity = float(
                trade.get("qty", 0)
            )

            timestamp = int(
                trade.get("time")
            )

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

        except Exception as e:

            print(
                "Trade parsing error:",
                e
            )

    result = list(
        candles.values()
    )

    result.sort(
        key=lambda x: x["time"]
    )

    return result


# =========================================================
# CLOSED CANDLES
# =========================================================

def get_closed_candles(candles):

    if len(candles) < 6:

        return []

    now_ms = int(
        datetime.now(
            timezone.utc
        ).timestamp() * 1000
    )

    current_bucket = now_ms - (
        now_ms % (5 * 60 * 1000)
    )

    return [

        candle

        for candle in candles

        if candle["time"] < current_bucket

    ]


# =========================================================
# SIGNAL ENGINE
# =========================================================

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

    # 1 - PRICE DIRECTION

    if c1["close"] > c2["close"]:

        buy_score += 1

    if c1["close"] < c2["close"]:

        sell_score += 1

    # 2 - MARKET STRUCTURE

    if (
        c1["high"] > c2["high"]
        and
        c1["low"] > c2["low"]
    ):

        buy_score += 1

    if (
        c1["high"] < c2["high"]
        and
        c1["low"] < c2["low"]
    ):

        sell_score += 1

    # 3 - CANDLE STRENGTH

    body = c1["close"] - c1["open"]

    candle_range = (
        c1["high"] - c1["low"]
    )

    if candle_range > 0:

        body_ratio = (
            abs(body) / candle_range
        )

        if (
            body > 0
            and
            body_ratio >= 0.45
        ):

            buy_score += 1

        if (
            body < 0
            and
            body_ratio >= 0.45
        ):

            sell_score += 1

    # 4 - MOMENTUM

    previous_move = (
        c2["close"] - c3["close"]
    )

    current_move = (
        c1["close"] - c2["close"]
    )

    if (
        current_move > 0
        and
        previous_move > 0
    ):

        buy_score += 1

    if (
        current_move < 0
        and
        previous_move < 0
    ):

        sell_score += 1

    # 5 - BREAKOUT

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

    # STRONG FILTER

    if (
        buy_score >= SIGNAL_THRESHOLD
        and
        buy_score > sell_score
    ):

        signal = "BUY"

    elif (
        sell_score >= SIGNAL_THRESHOLD
        and
        sell_score > buy_score
    ):

        signal = "SELL"

    else:

        signal = "NO SIGNAL"

    return {

        "signal": signal,

        "buy_score": buy_score,

        "sell_score": sell_score,

        "candle": c1

    }


# =========================================================
# MARKET PRICE
# =========================================================

def get_current_price():

    trades = get_trades()

    if not trades:

        raise ValueError(
            "No market trades"
        )

    return Decimal(
        str(trades[-1]["price"])
    )


# =========================================================
# ACCOUNT API
#
# IMPORTANT:
# These authenticated functions intentionally remain
# isolated. They must use the exact Tabdeal authenticated
# endpoint/schema configured for this account.
# =========================================================

def auth_headers():

    if not TABDEAL_API_KEY:

        raise ValueError(
            "TABDIL_API_KEY is missing"
        )

    if not TABDEAL_API_SECRET:

        raise ValueError(
            "TABDIL_API_SECRET is missing"
        )

    return {

        "X-MBX-APIKEY":
            TABDEAL_API_KEY

    }


# =========================================================
# OPEN ORDERS CHECK
# =========================================================

def get_open_orders():

    url = f"{BASE_URL}/api/v1/openOrders"

    response = requests.get(
        url,
        headers=auth_headers(),
        params={
            "symbol": SYMBOL
        },
        timeout=20
    )

    print(
        "Open orders HTTP:",
        response.status_code
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):

        for key in [
            "data",
            "result",
            "orders"
        ]:

            if key in data:

                data = data[key]
                break

    if isinstance(data, list):

        return data

    return []


# =========================================================
# ORDER STATUS MESSAGE
# =========================================================

def order_id_from_response(data):

    if not isinstance(data, dict):

        return "UNKNOWN"

    for key in [
        "orderId",
        "order_id",
        "id"
    ]:

        if key in data:

            return str(
                data[key]
            )

    return "UNKNOWN"


# =========================================================
# REAL MARKET ORDER
# =========================================================

def create_market_order(
    side,
    quantity
):

    url = f"{BASE_URL}/api/v1/order"

    params = {

        "symbol": SYMBOL,

        "side": side,

        "type": "MARKET",

        "quantity": str(
            quantity
        )

    }

    # NOTE:
    # Tabdeal authenticated requests require signing.
    # This function deliberately does NOT invent a
    # signature format.
    #
    # Before enabling this call in production, the
    # exact signing method from the current Tabdeal
    # API/SDK must be applied.

    raise RuntimeError(
        "REAL ORDER BLOCKED: "
        "Tabdeal authentication/signature "
        "must be configured from the current "
        "official API specification before "
        "placing a live order."
    )


# =========================================================
# BUY QUANTITY
# =========================================================

def calculate_btc_quantity(price):

    if price <= 0:

        raise ValueError(
            "Invalid BTC price"
        )

    quantity = (
        TRADE_USDT / price
    )

    # Conservative rounding.
    quantity = quantity.quantize(
        Decimal("0.000001"),
        rounding=ROUND_DOWN
    )

    if quantity <= 0:

        raise ValueError(
            "Calculated BTC quantity is zero"
        )

    return quantity


# =========================================================
# DUPLICATE BUY PROTECTION
# =========================================================

def has_open_position():

    """
    Safety rule:

    If there are open orders, do not create
    another BUY.

    A future authenticated balance check should
    also be added before enabling live execution.
    """

    try:

        orders = get_open_orders()

        if orders:

            print(
                "⚠️ Open order exists."
            )

            return True

        return False

    except Exception as e:

        print(
            "Open order check failed:",
            e
        )

        # FAIL CLOSED
        # If we cannot verify account state,
        # do NOT trade.

        return True


# =========================================================
# TELEGRAM SIGNAL
# =========================================================

def build_signal_message(result):

    candle = result["candle"]

    signal = result["signal"]

    entry = Decimal(
        str(candle["close"])
    )

    buy_score = result["buy_score"]

    sell_score = result["sell_score"]

    candle_time = datetime.fromtimestamp(
        candle["time"] / 1000,
        tz=timezone.utc
    ).strftime("%H:%M UTC")

    message = (

        "⚡ ATI CRYPTO BOT - REAL MODE\n\n"

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

        sl = (
            entry *
            (
                Decimal("1")
                -
                SL_PERCENT / Decimal("100")
            )
        )

        tp = (
            entry *
            (
                Decimal("1")
                +
                TP_PERCENT / Decimal("100")
            )
        )

        message += (

            "\n🟢 BUY SIGNAL\n"

            f"🛑 SL: ${sl:,.2f}\n"

            f"🎯 TP: ${tp:,.2f}\n\n"

            "💵 TRADE SIZE: 2 USDT\n"

            "⚠️ LIVE EXECUTION: BLOCKED "
            "UNTIL API SIGNING IS VERIFIED"

        )

    elif signal == "SELL":

        sl = (
            entry *
            (
                Decimal("1")
                +
                SL_PERCENT / Decimal("100")
            )
        )

        tp = (
            entry *
            (
                Decimal("1")
                -
                TP_PERCENT / Decimal("100")
            )
        )

        message += (

            "\n🔴 SELL SIGNAL\n"

            f"🛑 SL: ${sl:,.2f}\n"

            f"🎯 TP: ${tp:,.2f}\n\n"

            "💵 TRADE SIZE: existing BTC\n"

            "⚠️ LIVE EXECUTION: BLOCKED "
            "UNTIL API SIGNING IS VERIFIED"

        )

    else:

        message += (

            "\n⏳ NO STRONG SIGNAL\n\n"

            "💵 TRADE SIZE: 2 USDT"

        )

    return message


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        "======================================"
    )

    print(
        "⚡ ATI CRYPTO BOT - REAL TRADING BUILD"
    )

    print(
        "💵 TRADE SIZE: 2 USDT"
    )

    print(
        "======================================"
    )

    try:

        trades = get_trades()

        print(
            f"Trades received: {len(trades)}"
        )

        candles = build_5m_candles(
            trades
        )

        print(
            f"5M candles built: {len(candles)}"
        )

        closed = get_closed_candles(
            candles
        )

        print(
            f"Closed candles: {len(closed)}"
        )

        if len(closed) < 6:

            send_telegram(
                "⚠️ ATI BOT\n\n"
                "Not enough closed 5M candles."
            )

            return

        result = calculate_signal(
            closed
        )

        if not result:

            raise ValueError(
                "Signal calculation failed"
            )

        message = build_signal_message(
            result
        )

        print(message)

        send_telegram(message)

        # =================================================
        # LIVE TRADE GATE
        # =================================================

        if result["signal"] == "NO SIGNAL":

            print(
                "⏳ No trade."
            )

            return

        # Safety:
        # Do not send duplicate orders.

        if has_open_position():

            send_telegram(

                "🛡 ATI SAFETY\n\n"

                "Trade skipped.\n"

                "An open order/position state "
                "could not be safely cleared."

            )

            return

        price = get_current_price()

        quantity = calculate_btc_quantity(
            price
        )

        print(
            f"Calculated BTC quantity: "
            f"{quantity}"
        )

        # =================================================
        # IMPORTANT:
        # This call is deliberately blocked until
        # Tabdeal signing is verified.
        # =================================================

        if result["signal"] == "BUY":

            create_market_order(
                "BUY",
                quantity
            )

        elif result["signal"] == "SELL":

            create_market_order(
                "SELL",
                quantity
            )

    except Exception as e:

        error_message = (

            "🚨 ATI BOT ERROR\n\n"

            f"{type(e).__name__}: {e}"

        )

        print(error_message)

        send_telegram(
            error_message
        )


if __name__ == "__main__":

    main()
