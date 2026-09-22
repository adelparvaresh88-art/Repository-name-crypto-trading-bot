import os
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

from tabdeal.spot import Spot
from tabdeal.enums import OrderSides, OrderTypes


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

API_KEY = os.getenv("TABDIL_API_KEY")
API_SECRET = os.getenv("TABDIL_API_SECRET")

SYMBOL = "BTCUSDT"

TRADE_USDT = Decimal("2.00")

SL_PERCENT = Decimal("0.50")
TP_PERCENT = Decimal("1.00")

SIGNAL_THRESHOLD = 4

# IMPORTANT:
# Real trading is enabled in this version.
REAL_TRADING = True


# =========================================================
# TABDEAL CLIENT
# =========================================================

def get_client():

    if not API_KEY:
        raise RuntimeError(
            "TABDIL_API_KEY is missing"
        )

    if not API_SECRET:
        raise RuntimeError(
            "TABDIL_API_SECRET is missing"
        )

    return Spot(
        API_KEY,
        API_SECRET,
        base_url="https://api1.tabdeal.org",
        version="v1",
        timeout=20,
        receive_window=5000
    )


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    if not BOT_TOKEN:
        print("Telegram token missing")
        return False

    if not CHAT_ID:
        print("Telegram chat ID missing")
        return False

    import requests

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    try:

        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print(
            "Telegram HTTP:",
            response.status_code
        )

        return response.ok

    except Exception as e:

        print(
            "Telegram error:",
            e
        )

        return False


# =========================================================
# MARKET DATA
# =========================================================

def get_trades(client):

    data = client.trades(
        symbol=SYMBOL,
        limit=1000
    )

    if isinstance(data, dict):

        for key in [
            "data",
            "result",
            "trades"
        ]:

            if key in data:

                data = data[key]
                break

    if not isinstance(data, list):

        raise RuntimeError(
            f"Unexpected trades response: {data}"
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

            bucket = (
                timestamp
                -
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

    current_bucket = (
        now_ms
        -
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

    # STRONG SIGNAL

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
# ACCOUNT
# =========================================================

def get_account(client):

    account = client.account()

    if not isinstance(account, dict):

        raise RuntimeError(
            f"Unexpected account response: {account}"
        )

    return account


# =========================================================
# BALANCE PARSER
# =========================================================

def get_free_balance(
    account,
    asset
):

    balances = account.get(
        "balances",
        []
    )

    if isinstance(balances, dict):

        balances = balances.get(
            "data",
            balances
        )

    if not isinstance(
        balances,
        list
    ):

        return Decimal("0")

    for item in balances:

        if not isinstance(
            item,
            dict
        ):
            continue

        item_asset = (
            item.get("asset")
            or
            item.get("currency")
            or
            item.get("symbol")
        )

        if (
            item_asset
            and
            str(item_asset).upper()
            == asset.upper()
        ):

            value = (
                item.get("free")
                or
                item.get("available")
                or
                item.get("balance")
                or
                "0"
            )

            try:

                return Decimal(
                    str(value)
                )

            except Exception:

                return Decimal("0")

    return Decimal("0")


# =========================================================
# OPEN ORDERS
# =========================================================

def get_open_orders(client):

    orders = client.get_open_orders(
        symbol=SYMBOL
    )

    if isinstance(
        orders,
        dict
    ):

        for key in [
            "data",
            "result",
            "orders"
        ]:

            if key in orders:

                orders = orders[key]
                break

    if not isinstance(
        orders,
        list
    ):

        return []

    return orders


# =========================================================
# OPEN OCO ORDERS
# =========================================================

def get_open_oco_orders(client):

    try:

        orders = client.get_oco_open_orders()

        if isinstance(
            orders,
            dict
        ):

            for key in [
                "data",
                "result",
                "orders",
                "orderLists"
            ]:

                if key in orders:

                    orders = orders[key]
                    break

        if isinstance(
            orders,
            list
        ):

            return orders

    except Exception as e:

        print(
            "OCO check error:",
            e
        )

    return []


# =========================================================
# DUPLICATE TRADE PROTECTION
# =========================================================

def trading_state(client):

    """
    Returns:

    True = already exposed / active
    False = safe for new BUY
    """

    # ------------------------------------------
    # 1. OPEN NORMAL ORDERS
    # ------------------------------------------

    open_orders = get_open_orders(
        client
    )

    if open_orders:

        print(
            "🛡 Open normal order exists."
        )

        return True

    # ------------------------------------------
    # 2. OPEN OCO
    # ------------------------------------------

    open_oco = get_open_oco_orders(
        client
    )

    if open_oco:

        print(
            "🛡 Open OCO exists."
        )

        return True

    # ------------------------------------------
    # 3. BTC BALANCE
    # ------------------------------------------

    account = get_account(
        client
    )

    btc_balance = get_free_balance(
        account,
        "BTC"
    )

    print(
        "Free BTC:",
        btc_balance
    )

    # Small dust is ignored.
    if btc_balance > Decimal("0.000001"):

        print(
            "🛡 BTC position already exists."
        )

        return True

    return False


# =========================================================
# MARKET PRICE
# =========================================================

def get_current_price(trades):

    if not trades:

        raise RuntimeError(
            "No current market price"
        )

    return Decimal(
        str(
            trades[-1]["price"]
        )
    )


# =========================================================
# BTC QUANTITY
# =========================================================

def calculate_quantity(price):

    if price <= 0:

        raise RuntimeError(
            "Invalid BTC price"
        )

    quantity = (
        TRADE_USDT / price
    )

    # Conservative BTC precision.
    quantity = quantity.quantize(
        Decimal("0.000001"),
        rounding=ROUND_DOWN
    )

    if quantity <= 0:

        raise RuntimeError(
            "BTC quantity became zero"
        )

    return quantity


# =========================================================
# REAL BUY
# =========================================================

def place_buy(
    client,
    quantity
):

    client_order_id = (
        "ATI_BUY_"
        +
        datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%d%H%M%S"
        )
    )

    print(
        "🚀 REAL BUY"
    )

    print(
        "Quantity:",
        quantity
    )

    result = client.new_order(

        symbol=SYMBOL,

        side=OrderSides.BUY,

        type=OrderTypes.MARKET,

        quantity=str(
            quantity
        ),

        client_order_id=
            client_order_id
    )

    return result


# =========================================================
# OCO
# =========================================================

def place_oco(
    client,
    quantity,
    entry
):

    sl = (
        entry
        *
        (
            Decimal("1")
            -
            SL_PERCENT / Decimal("100")
        )
    )

    tp = (
        entry
        *
        (
            Decimal("1")
            +
            TP_PERCENT / Decimal("100")
        )
    )

    # BTC/USDT price precision
    sl = sl.quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN
    )

    tp = tp.quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN
    )

    # Stop-limit slightly below stop price.
    stop_limit = (
        sl
        *
        Decimal("0.999")
    )

    stop_limit = stop_limit.quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN
    )

    print(
        "OCO TP:",
        tp
    )

    print(
        "OCO SL:",
        sl
    )

    print(
        "OCO STOP LIMIT:",
        stop_limit
    )

    result = client.new_oco_order(

        symbol=SYMBOL,

        side=OrderSides.SELL,

        quantity=str(
            quantity
        ),

        price=str(
            tp
        ),

        stop_price=str(
            sl
        ),

        stop_limit_price=str(
            stop_limit
        ),

        list_client_order_id=(
            "ATI_OCO_"
            +
            datetime.now(
                timezone.utc
            ).strftime(
                "%Y%m%d%H%M%S"
            )
        )
    )

    return result, sl, tp


# =========================================================
# TELEGRAM MESSAGE
# =========================================================

def signal_message(result):

    candle = result["candle"]

    entry = Decimal(
        str(candle["close"])
    )

    signal = result["signal"]

    candle_time = datetime.fromtimestamp(
        candle["time"] / 1000,
        tz=timezone.utc
    ).strftime(
        "%H:%M UTC"
    )

    message = (

        "⚡ ATI CRYPTO BOT - REAL MODE\n\n"

        "₿ BTC/USDT\n"

        "⏱ Timeframe: 5m\n"

        "✅ CLOSED CANDLE\n"

        "💪 STRONG SIGNAL FILTER\n\n"

        f"📊 SIGNAL: {signal}\n"

        f"📈 BUY SCORE: "
        f"{result['buy_score']}/5\n"

        f"📉 SELL SCORE: "
        f"{result['sell_score']}/5\n\n"

        f"🕐 Candle: {candle_time}\n"

        f"💰 Entry: ${entry:,.2f}\n"

    )

    if signal == "BUY":

        sl = (
            entry
            *
            (
                Decimal("1")
                -
                SL_PERCENT / Decimal("100")
            )
        )

        tp = (
            entry
            *
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

            "🔐 REAL TRADING: ENABLED"

        )

    elif signal == "SELL":

        message += (

            "\n🔴 SELL SIGNAL\n\n"

            "🔐 REAL TRADING: ENABLED"

        )

    else:

        message += (

            "\n⏳ NO STRONG SIGNAL"

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
        "⚡ ATI CRYPTO BOT - REAL MODE V2"
    )

    print(
        "💵 TRADE SIZE: 2 USDT"
    )

    print(
        "======================================"
    )

    try:

        # --------------------------------------
        # CLIENT
        # --------------------------------------

        client = get_client()

        print(
            "✅ Tabdeal authenticated client ready"
        )

        # --------------------------------------
        # ACCOUNT CHECK
        # --------------------------------------

        account = get_account(
            client
        )

        usdt_balance = get_free_balance(
            account,
            "USDT"
        )

        btc_balance = get_free_balance(
            account,
            "BTC"
        )

        print(
            "USDT:",
            usdt_balance
        )

        print(
            "BTC:",
            btc_balance
        )

        if usdt_balance < TRADE_USDT:

            send_telegram(

                "🛡 ATI SAFETY\n\n"

                "Trade skipped.\n"

                f"USDT balance is "
                f"{usdt_balance}, "
                f"but 2 USDT is required."

            )

            return

        # --------------------------------------
        # MARKET
        # --------------------------------------

        trades = get_trades(
            client
        )

        print(
            f"Trades received: "
            f"{len(trades)}"
        )

        candles = build_5m_candles(
            trades
        )

        print(
            f"5M candles built: "
            f"{len(candles)}"
        )

        closed = get_closed_candles(
            candles
        )

        print(
            f"Closed candles: "
            f"{len(closed)}"
        )

        if len(closed) < 6:

            send_telegram(
                "⚠️ ATI BOT\n\n"
                "Not enough closed 5M candles."
            )

            return

        # --------------------------------------
        # SIGNAL
        # --------------------------------------

        result = calculate_signal(
            closed
        )

        if not result:

            raise RuntimeError(
                "Signal calculation failed"
            )

        message = signal_message(
            result
        )

        print(message)

        send_telegram(
            message
        )

        # --------------------------------------
        # NO SIGNAL
        # --------------------------------------

        if result["signal"] == "NO SIGNAL":

            print(
                "⏳ No trade."
            )

            return

        # --------------------------------------
        # SAFETY / DUPLICATE CHECK
        # --------------------------------------

        if trading_state(
            client
        ):

            send_telegram(

                "🛡 ATI SAFETY\n\n"

                "Trade skipped.\n\n"

                "An active order, OCO, "
                "or BTC position already exists.\n"

                "🚫 Duplicate trade prevented."

            )

            return

        # --------------------------------------
        # BUY
        # --------------------------------------

        if result["signal"] == "BUY":

            price = get_current_price(
                trades
            )

            quantity = calculate_quantity(
                price
            )

            print(
                "BTC quantity:",
                quantity
            )

            if not REAL_TRADING:

                print(
                    "REAL TRADING DISABLED"
                )

                return

            # ----------------------------------
            # REAL MARKET BUY
            # ----------------------------------

            buy_result = place_buy(
                client,
                quantity
            )

            print(
                "BUY RESPONSE:",
                buy_result
            )

            # ----------------------------------
            # USE ACTUAL FILLED QUANTITY
            # ----------------------------------

            filled_quantity = quantity

            if isinstance(
                buy_result,
                dict
            ):

                for key in [
                    "executedQty",
                    "executed_quantity",
                    "filledQty"
                ]:

                    if key in buy_result:

                        try:

                            filled_quantity = Decimal(
                                str(
                                    buy_result[key]
                                )
                            )

                        except Exception:
                            pass

            if filled_quantity <= 0:

                raise RuntimeError(
                    "BUY returned zero filled quantity"
                )

            # ----------------------------------
            # OCO
            # ----------------------------------

            oco_result, sl, tp = place_oco(

                client,

                filled_quantity,

                price

            )

            print(
                "OCO RESPONSE:",
                oco_result
            )

            send_telegram(

                "✅ ATI REAL TRADE EXECUTED\n\n"

                "₿ BTC/USDT\n"

                "🟢 BUY\n"

                f"💵 Size: "
                f"{TRADE_USDT} USDT\n"

                f"📦 BTC: "
                f"{filled_quantity}\n"

                f"💰 Entry: "
                f"${price:,.2f}\n"

                f"🛑 SL: "
                f"${sl:,.2f}\n"

                f"🎯 TP: "
                f"${tp:,.2f}\n\n"

                "🛡 OCO protection active."

            )

            return

        # --------------------------------------
        # SELL
        # --------------------------------------

        if result["signal"] == "SELL":

            # Conservative rule:
            # Never sell unknown/manual BTC holdings.
            #
            # SELL is only reported for now.
            # The BUY position is protected by OCO.

            send_telegram(

                "🔴 ATI SELL SIGNAL\n\n"

                "SELL detected.\n"

                "🛡 Manual/unknown BTC holdings "
                "will NOT be sold automatically.\n\n"

                "Existing bot BUY positions "
                "are protected by OCO."

            )

            return

    except Exception as e:

        error_message = (

            "🚨 ATI REAL BOT ERROR\n\n"

            f"{type(e).__name__}: {e}\n\n"

            "🛡 NO FURTHER ORDER SENT"

        )

        print(
            error_message
        )

        send_telegram(
            error_message
        )


if __name__ == "__main__":

    main()
