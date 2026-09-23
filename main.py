import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from datetime import datetime, timezone


# =========================================================
# ATI CRYPTO BOT
# TABDEAL FUTURES - LIVE TRADING
# BTCUSDT / 5M
# =========================================================

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"

API_KEY = os.getenv("TABDEAL_API_KEY")
API_SECRET = os.getenv("TABDEAL_API_SECRET")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LIVE_TRADING = os.getenv("LIVE_TRADING", "FALSE").upper()

ORDER_QTY = os.getenv("ORDER_QTY", "0.001")

# 0.5% Stop Loss
SL_PERCENT = float(os.getenv("SL_PERCENT", "0.005"))

# 1% Take Profit
TP_PERCENT = float(os.getenv("TP_PERCENT", "0.010"))


session = requests.Session()


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials missing")
        return False

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}/sendMessage"
        )

        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=15
        )

        print(
            "Telegram status:",
            response.status_code
        )

        return response.ok

    except Exception as e:

        print(
            "Telegram error:",
            str(e)
        )

        return False


# =========================================================
# TABDEAL SIGNATURE
# =========================================================

def signed_request(
    method,
    path,
    params=None
):

    if not API_KEY:
        raise Exception(
            "TABDEAL_API_KEY is missing"
        )

    if not API_SECRET:
        raise Exception(
            "TABDEAL_API_SECRET is missing"
        )

    if params is None:
        params = {}

    params = dict(params)

    params["timestamp"] = int(
        time.time() * 1000
    )

    query_string = urlencode(
        params,
        doseq=True
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    params["signature"] = signature

    url = BASE_URL + path

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    if method == "GET":

        response = session.get(
            url,
            params=params,
            headers=headers,
            timeout=20
        )

    elif method == "POST":

        response = session.post(
            url,
            data=params,
            headers=headers,
            timeout=20
        )

    elif method == "DELETE":

        response = session.delete(
            url,
            params=params,
            headers=headers,
            timeout=20
        )

    else:

        raise Exception(
            f"Unsupported HTTP method: {method}"
        )

    print(
        "API",
        method,
        path,
        "STATUS:",
        response.status_code
    )

    print(
        "API RESPONSE:",
        response.text[:1500]
    )

    if response.status_code >= 400:

        raise Exception(
            f"Tabdeal API error "
            f"{response.status_code}: "
            f"{response.text[:1000]}"
        )

    try:
        return response.json()

    except Exception:

        return {
            "raw": response.text
        }


# =========================================================
# PUBLIC MARKET DATA
# =========================================================

def get_trades():

    url = (
        f"{BASE_URL}/api/v1/trades"
    )

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

    if isinstance(data, dict):

        if "data" in data:
            data = data["data"]

        elif "result" in data:
            data = data["result"]

    if not isinstance(data, list):

        raise Exception(
            "Unexpected Tabdeal trades response"
        )

    return data


# =========================================================
# BUILD 5 MINUTE CANDLES
# =========================================================

def build_candles(trades):

    candles = {}

    for trade in trades:

        try:

            price_value = (
                trade.get("price")
                or trade.get("p")
                or trade.get("rate")
            )

            quantity_value = (
                trade.get("quantity")
                or trade.get("q")
                or trade.get("amount")
                or 0
            )

            timestamp_value = (
                trade.get("timestamp")
                or trade.get("time")
                or trade.get("T")
            )

            if (
                price_value is None
                or timestamp_value is None
            ):
                continue

            price = float(
                price_value
            )

            quantity = float(
                quantity_value
            )

            timestamp = int(
                timestamp_value
            )

            if timestamp < 10_000_000_000:

                timestamp *= 1000

            bucket = (
                timestamp // 300000
            )

            if bucket not in candles:

                candles[bucket] = {
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": quantity,
                    "time": bucket * 1000
                }

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

    result = list(
        candles.values()
    )

    result.sort(
        key=lambda x: x["time"]
    )

    return result


# =========================================================
# SIGNAL
# =========================================================

def calculate_signal(candles):

    if len(candles) < 6:

        return (
            "NO SIGNAL",
            0,
            0
        )

    # آخرین کندل = ممکن است هنوز باز باشد
    # بنابراین [-2] استفاده می‌شود
    current = candles[-2]

    previous = candles[-3]

    buy_score = 0
    sell_score = 0


    # -------------------------
    # 1. Candle direction
    # -------------------------

    if current["close"] > current["open"]:

        buy_score += 1

    elif current["close"] < current["open"]:

        sell_score += 1


    # -------------------------
    # 2. Close comparison
    # -------------------------

    if current["close"] > previous["close"]:

        buy_score += 1

    elif current["close"] < previous["close"]:

        sell_score += 1


    # -------------------------
    # 3. Higher / lower high
    # -------------------------

    if current["high"] > previous["high"]:

        buy_score += 1

    elif current["high"] < previous["high"]:

        sell_score += 1


    # -------------------------
    # 4. Higher / lower low
    # -------------------------

    if current["low"] > previous["low"]:

        buy_score += 1

    elif current["low"] < previous["low"]:

        sell_score += 1


    # -------------------------
    # 5. Candle strength
    # -------------------------

    candle_range = (
        current["high"]
        - current["low"]
    )

    if candle_range > 0:

        body = abs(
            current["close"]
            - current["open"]
        )

        strength = (
            body / candle_range
        )

        if strength >= 0.55:

            if current["close"] > current["open"]:

                buy_score += 1

            elif current["close"] < current["open"]:

                sell_score += 1


    # -------------------------
    # FINAL SIGNAL
    # -------------------------

    if (
        buy_score >= 4
        and buy_score > sell_score
    ):

        return (
            "BUY",
            buy_score,
            sell_score
        )

    if (
        sell_score >= 4
        and sell_score > buy_score
    ):

        return (
            "SELL",
            buy_score,
            sell_score
        )

    return (
        "NO SIGNAL",
        buy_score,
        sell_score
    )


# =========================================================
# POSITION QUERY
# =========================================================

def get_positions():

    return signed_request(
        "GET",
        "/fapi/v1/position",
        {
            "symbol": SYMBOL
        }
    )


# =========================================================
# NORMALIZE RESPONSE
# =========================================================

def normalize_list(data):

    if isinstance(data, list):

        return data

    if isinstance(data, dict):

        for key in (
            "data",
            "result",
            "positions"
        ):

            value = data.get(key)

            if isinstance(value, list):

                return value

        return [data]

    return []


# =========================================================
# FIND OPEN POSITION
# =========================================================

def get_open_position():

    data = get_positions()

    positions = normalize_list(
        data
    )

    for position in positions:

        try:

            quantity = float(
                position.get("positionAmt")
                or position.get("quantity")
                or position.get("qty")
                or position.get("amount")
                or 0
            )

            if abs(quantity) > 0:

                position_id = (
                    position.get("positionId")
                    or position.get("id")
                )

                entry_price = float(
                    position.get("entryPrice")
                    or position.get("avgPrice")
                    or position.get("price")
                    or 0
                )

                return {
                    "id": position_id,
                    "quantity": quantity,
                    "entry_price": entry_price,
                    "raw": position
                }

        except Exception:

            continue

    return None


# =========================================================
# REAL MARKET ORDER
# =========================================================

def place_market_order(signal):

    if signal == "BUY":

        side = "BUY"

    elif signal == "SELL":

        side = "SELL"

    else:

        raise Exception(
            "Invalid order signal"
        )

    quantity = str(
        ORDER_QTY
    )

    print(
        "================================"
    )

    print(
        "REAL FUTURES ORDER"
    )

    print(
        "SYMBOL:",
        SYMBOL
    )

    print(
        "SIDE:",
        side
    )

    print(
        "QUANTITY:",
        quantity
    )

    print(
        "================================"
    )

    return signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": SYMBOL,
            "side": side,
            "type": "MARKET",
            "quantity": quantity
        }
    )


# =========================================================
# STOP LOSS / TAKE PROFIT
# =========================================================

def calculate_sl_tp(
    entry_price,
    signal
):

    if signal == "BUY":

        sl = (
            entry_price
            * (1 - SL_PERCENT)
        )

        tp = (
            entry_price
            * (1 + TP_PERCENT)
        )

    else:

        sl = (
            entry_price
            * (1 + SL_PERCENT)
        )

        tp = (
            entry_price
            * (1 - TP_PERCENT)
        )

    return (
        round(sl, 2),
        round(tp, 2)
    )


# =========================================================
# SET SL / TP
# =========================================================

def set_sl_tp(
    position,
    signal
):

    position_id = position["id"]

    entry_price = position[
        "entry_price"
    ]

    if not position_id:

        raise Exception(
            "Position ID was not returned"
        )

    if entry_price <= 0:

        raise Exception(
            "Invalid position entry price"
        )

    sl_price, tp_price = (
        calculate_sl_tp(
            entry_price,
            signal
        )
    )

    print(
        "ENTRY:",
        entry_price
    )

    print(
        "SL:",
        sl_price
    )

    print(
        "TP:",
        tp_price
    )

    result = signed_request(
        "POST",
        "/fapi/v1/positionSlTp",
        {
            "positionId": str(
                position_id
            ),
            "symbol": SYMBOL,
            "slPrice": str(
                sl_price
            ),
            "tpPrice": str(
                tp_price
            )
        }
    )

    return (
        result,
        sl_price,
        tp_price
    )


# =========================================================
# EMERGENCY CLOSE
# =========================================================

def emergency_close():

    print(
        "!!! EMERGENCY CLOSE !!!"
    )

    try:

        result = signed_request(
            "DELETE",
            "/fapi/v1/position",
            {
                "symbol": SYMBOL
            }
        )

        return result

    except Exception as e:

        print(
            "Emergency close failed:",
            str(e)
        )

        raise


# =========================================================
# WAIT FOR POSITION
# =========================================================

def wait_for_position(
    attempts=10
):

    for attempt in range(
        attempts
    ):

        print(
            "Checking position:",
            attempt + 1,
            "/",
            attempts
        )

        try:

            position = (
                get_open_position()
            )

            if position:

                return position

        except Exception as e:

            print(
                "Position check error:",
                str(e)
            )

        time.sleep(1)

    return None


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        "=========================================="
    )

    print(
        "ATI CRYPTO BOT - TABDEAL FUTURES"
    )

    print(
        "BTCUSDT / 5M"
    )

    print(
        "=========================================="
    )


    # -----------------------------------------------------
    # CREDENTIAL CHECK
    # -----------------------------------------------------

    if not API_KEY:

        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "Bot stopped.\n\n"
            "❌ TABDEAL_API_KEY is missing."
        )

        return


    if not API_SECRET:

        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "Bot stopped.\n\n"
            "❌ TABDEAL_API_SECRET is missing."
        )

        return


    if not BOT_TOKEN:

        print(
            "WARNING: Telegram token missing"
        )


    if not CHAT_ID:

        print(
            "WARNING: Telegram chat ID missing"
        )


    try:

        # -------------------------------------------------
        # MARKET DATA
        # -------------------------------------------------

        trades = get_trades()

        print(
            "Trades received:",
            len(trades)
        )

        candles = build_candles(
            trades
        )

        print(
            "5M candles built:",
            len(candles)
        )


        if len(candles) < 6:

            send_telegram(
                "🛡 ATI SAFETY\n\n"
                "Bot stopped.\n\n"
                "❌ Not enough 5M candles."
            )

            return


        # -------------------------------------------------
        # SIGNAL
        # -------------------------------------------------

        signal, buy_score, sell_score = (
            calculate_signal(
                candles
            )
        )

        candle = candles[-2]

        entry_price = float(
            candle["close"]
        )

        candle_time = (
            datetime.fromtimestamp(
                candle["time"] / 1000,
                tz=timezone.utc
            )
            .strftime("%H:%M UTC")
        )


        print(
            "SIGNAL:",
            signal
        )

        print(
            "BUY SCORE:",
            buy_score
        )

        print(
            "SELL SCORE:",
            sell_score
        )


        # -------------------------------------------------
        # NO SIGNAL
        # -------------------------------------------------

        if signal == "NO SIGNAL":

            send_telegram(
                "⚡ ATI CRYPTO BOT\n\n"
                "₿ BTC/USDT\n"
                "⏱ Timeframe: 5m\n"
                "✅ CLOSED CANDLE\n"
                "💪 STRONG SIGNAL FILTER\n\n"
                "📊 SIGNAL: NO SIGNAL\n"
                f"📈 BUY SCORE: "
                f"{buy_score}/5\n"
                f"📉 SELL SCORE: "
                f"{sell_score}/5\n\n"
                f"🕐 Candle: "
                f"{candle_time}\n"
                f"💰 Price: "
                f"${entry_price:,.2f}\n\n"
                "⏳ NO TRADE"
            )

            return


        # -------------------------------------------------
        # CHECK EXISTING POSITION
        # -------------------------------------------------

        existing_position = (
            get_open_position()
        )

        if existing_position:

            send_telegram(
                "🛡 ATI SAFETY\n\n"
                "Trade skipped.\n\n"
                "❌ An existing BTCUSDT "
                "Futures position is already open."
            )

            return


        # -------------------------------------------------
        # LIVE MODE CHECK
        # -------------------------------------------------

        if LIVE_TRADING != "TRUE":

            send_telegram(
                "🧪 ATI PAPER SIGNAL\n\n"
                f"📊 SIGNAL: {signal}\n"
                f"📈 BUY SCORE: "
                f"{buy_score}/5\n"
                f"📉 SELL SCORE: "
                f"{sell_score}/5\n\n"
                f"💰 Entry: "
                f"${entry_price:,.2f}\n\n"
                "⚠️ LIVE_TRADING is not TRUE.\n"
                "❌ No real order sent."
            )

            return


        # -------------------------------------------------
        # REAL ORDER
        # -------------------------------------------------

        send_telegram(
            "⚠️ ATI LIVE TRADING\n\n"
            f"📊 SIGNAL: {signal}\n"
            f"📈 BUY SCORE: "
            f"{buy_score}/5\n"
            f"📉 SELL SCORE: "
            f"{sell_score}/5\n\n"
            f"📦 Quantity: "
            f"{ORDER_QTY}\n\n"
            "⏳ Sending real Futures order..."
        )


        order_result = (
            place_market_order(
                signal
            )
        )


        print(
            "ORDER RESULT:",
            order_result
        )


        # -------------------------------------------------
        # VERIFY POSITION
        # -------------------------------------------------

        position = (
            wait_for_position(
                attempts=10
            )
        )


        if not position:

            send_telegram(
                "🚨 ATI SAFETY\n\n"
                "⚠️ Real order response received.\n\n"
                "❌ Open position could not "
                "be verified.\n\n"
                "🛡 Emergency close will be attempted."
            )

            try:

                emergency_close()

                send_telegram(
                    "🛡 ATI SAFETY\n\n"
                    "Emergency close attempted."
                )

            except Exception as close_error:

                send_telegram(
                    "🚨 CRITICAL SAFETY ERROR\n\n"
                    "Position verification failed.\n"
                    "Emergency close also failed.\n\n"
                    f"{str(close_error)[:900]}"
                )

            return


        # -------------------------------------------------
        # INSTALL SL / TP
        # -------------------------------------------------

        try:

            (
                sltp_result,
                sl_price,
                tp_price
            ) = set_sl_tp(
                position,
                signal
            )

            print(
                "SL/TP RESULT:",
                sltp_result
            )


        except Exception as sltp_error:

            print(
                "SL/TP ERROR:",
                str(sltp_error)
            )

            send_telegram(
                "🚨 ATI SAFETY\n\n"
                "REAL POSITION OPENED.\n\n"
                "❌ SL/TP installation FAILED.\n\n"
                "🛡 Emergency close will be attempted."
            )

            try:

                emergency_close()

                send_telegram(
                    "🛡 ATI SAFETY\n\n"
                    "Emergency close attempted "
                    "after SL/TP failure."
                )

            except Exception as close_error:

                send_telegram(
                    "🚨 CRITICAL SAFETY ERROR\n\n"
                    "SL/TP failed.\n"
                    "Emergency close also failed.\n\n"
                    f"{str(close_error)[:900]}"
                )

            return


        # -------------------------------------------------
        # SUCCESS
        # -------------------------------------------------

        actual_entry = position[
            "entry_price"
        ]

        message = (
            "🚨 ATI CRYPTO BOT\n"
            "🔥 REAL FUTURES TRADE\n\n"
            "₿ BTC/USDT\n"
            "⏱ Timeframe: 5m\n"
            "✅ CLOSED CANDLE\n"
            "💪 STRONG SIGNAL\n\n"
            f"📊 SIGNAL: {signal}\n"
            f"📈 BUY SCORE: "
            f"{buy_score}/5\n"
            f"📉 SELL SCORE: "
            f"{sell_score}/5\n\n"
            f"💰 Entry: "
            f"${actual_entry:,.2f}\n"
            f"📦 Quantity: "
            f"{ORDER_QTY}\n\n"
            f"🛑 SL: "
            f"${sl_price:,.2f}\n"
            f"🎯 TP: "
            f"${tp_price:,.2f}\n\n"
            "✅ SL/TP installed\n"
            "⚡ LIVE TRADING: TRUE"
        )

        send_telegram(
            message
        )


    except Exception as e:

        print(
            "BOT ERROR:",
            repr(e)
        )

        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "Bot stopped.\n\n"
            f"❌ {str(e)[:1200]}"
        )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    main()
