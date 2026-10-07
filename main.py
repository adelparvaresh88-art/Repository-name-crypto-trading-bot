import os
import time
import hmac
import hashlib
import json
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode

import requests


# ============================================================
# ATI FUTURES BOT
# Tabdeal Futures REST API
#
# READ  -> https://api1.tabdeal.org/r/fapi/
# WRITE -> https://api1.tabdeal.org/fapi/
#
# NO tabdeal.future import
# ============================================================


# -----------------------------
# CONFIG
# -----------------------------

API_KEY = (
    os.getenv("TABDIL_API_KEY")
    or os.getenv("TABDEAL_API_KEY")
    or ""
).strip()

API_SECRET = (
    os.getenv("TABDIL_API_SECRET")
    or os.getenv("TABDEAL_API_SECRET")
    or ""
).strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

LIVE_TRADING = os.getenv("LIVE_TRADING", "true").lower() == "true"

SYMBOL = os.getenv("FUTURES_SYMBOL", "BTCUSDT").upper()
INTERVAL = os.getenv("FUTURES_INTERVAL", "5m")

LEVERAGE = int(os.getenv("FUTURES_LEVERAGE", "3"))

# مقدار مارجین معامله
ORDER_USDT = Decimal(os.getenv("FUTURES_ORDER_USDT", "2"))

TP_PERCENT = Decimal(os.getenv("FUTURES_TP_PERCENT", "2"))
SL_PERCENT = Decimal(os.getenv("FUTURES_SL_PERCENT", "1"))

RECV_WINDOW = int(os.getenv("RECV_WINDOW", "5000"))

BASE_URL = "https://api1.tabdeal.org"

# طبق SDK رسمی Tabdeal
READ_BASE = f"{BASE_URL}/r/fapi/"
WRITE_BASE = f"{BASE_URL}/fapi/"


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-Bot/1.0",
    "Accept": "application/json",
})


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return

    try:
        url = (
            f"https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}/sendMessage"
        )

        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )

        if response.status_code >= 400:
            print("Telegram error:", response.text)

    except Exception as exc:
        print("Telegram exception:", repr(exc))


# ============================================================
# ERROR HANDLER
# ============================================================

def parse_response(response):
    text = response.text

    try:
        data = response.json()
    except Exception:
        data = None

    if response.status_code >= 400:

        if isinstance(data, dict):
            msg = data.get("msg", data)
            code = data.get("code", "")
            raise RuntimeError(
                f"HTTP {response.status_code} | "
                f"code={code} | msg={msg}"
            )

        raise RuntimeError(
            f"HTTP {response.status_code}: {text[:1000]}"
        )

    return data


# ============================================================
# PUBLIC GET
# /r/fapi/
# ============================================================

def public_get(path, params=None):
    url = READ_BASE + path

    response = session.get(
        url,
        params=params or {},
        timeout=20,
    )

    return parse_response(response)


# ============================================================
# SIGNED REQUEST
#
# GET     -> /r/fapi/
# POST    -> /fapi/
# DELETE  -> /fapi/
#
# This follows the official Client implementation.
# ============================================================

def signed_request(method, path, params=None):

    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDIL/TABDEAL API KEY or SECRET is missing."
        )

    data = {}

    if params:
        data.update(params)

    # Official SDK uses timestamp in milliseconds.
    data["timestamp"] = int(time.time() * 1000)

    data["recvWindow"] = RECV_WINDOW

    query_string = urlencode(data)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    data["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    method = method.upper()

    if method == "GET":

        url = READ_BASE + path

        response = session.get(
            url,
            params=data,
            headers=headers,
            timeout=20,
        )

    elif method == "POST":

        url = WRITE_BASE + path

        response = session.post(
            url,
            data=data,
            headers=headers,
            timeout=20,
        )

    elif method == "DELETE":

        url = WRITE_BASE + path

        response = session.delete(
            url,
            params=data,
            headers=headers,
            timeout=20,
        )

    else:
        raise RuntimeError(f"Unsupported HTTP method: {method}")

    return parse_response(response)


# ============================================================
# BASIC API
# ============================================================

def futures_ping():
    return public_get("v1/ping")


def futures_time():
    return public_get("v1/time")


def exchange_info(symbol=None):

    params = {}

    if symbol:
        params["symbol"] = symbol

    return public_get(
        "v1/exchangeInfo",
        params,
    )


# ============================================================
# ACCOUNT
# ============================================================

def get_account():
    return signed_request(
        "GET",
        "v3/account",
    )


def get_balance():
    return signed_request(
        "GET",
        "v3/balance",
    )


def get_positions(symbol=None):

    params = {}

    if symbol:
        params["symbol"] = symbol

    return signed_request(
        "GET",
        "v1/position",
        params,
    )


def get_position_risk(symbol=None):

    params = {}

    if symbol:
        params["symbol"] = symbol

    return signed_request(
        "GET",
        "v3/positionRisk",
        params,
    )


# ============================================================
# LEVERAGE
# ============================================================

def get_leverage(symbol):

    return signed_request(
        "GET",
        "v1/leverage",
        {
            "symbol": symbol,
        },
    )


def change_leverage(symbol, leverage):

    return signed_request(
        "POST",
        "v1/leverage",
        {
            "symbol": symbol,
            "leverage": leverage,
        },
    )


# ============================================================
# ORDER
# ============================================================

def new_market_order(
    symbol,
    side,
    quantity,
):

    return signed_request(
        "POST",
        "v1/order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        },
    )


# ============================================================
# POSITION SL / TP
# ============================================================

def set_position_sl_tp(
    position_id,
    symbol,
    sl_price,
    tp_price,
):

    return signed_request(
        "POST",
        "v1/positionSlTp",
        {
            "positionId": position_id,
            "symbol": symbol,
            "slPrice": sl_price,
            "tpPrice": tp_price,
        },
    )


# ============================================================
# HELPERS
# ============================================================

def decimal_from(value, default="0"):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def find_symbol_info(info, symbol):

    if not isinstance(info, dict):
        return None

    symbols = info.get("symbols", [])

    if isinstance(symbols, list):

        for item in symbols:

            if not isinstance(item, dict):
                continue

            item_symbol = str(
                item.get("symbol", "")
            ).upper()

            if item_symbol == symbol:
                return item

    return None


def get_quantity_rules(symbol_info):

    """
    Extract quantity precision / LOT_SIZE style filters
    from exchangeInfo when available.
    """

    step_size = Decimal("0.000001")
    min_qty = Decimal("0")

    if not isinstance(symbol_info, dict):
        return step_size, min_qty

    filters = symbol_info.get("filters", [])

    if isinstance(filters, list):

        for f in filters:

            if not isinstance(f, dict):
                continue

            filter_type = str(
                f.get("filterType", "")
            ).upper()

            if filter_type in (
                "LOT_SIZE",
                "MARKET_LOT_SIZE",
            ):

                if f.get("stepSize") is not None:
                    step_size = decimal_from(
                        f["stepSize"],
                        "0.000001",
                    )

                if f.get("minQty") is not None:
                    min_qty = decimal_from(
                        f["minQty"],
                        "0",
                    )

                break

    return step_size, min_qty


def floor_to_step(value, step):

    if step <= 0:
        return value

    units = (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    )

    return units * step


def decimal_string(value):

    value = Decimal(value)

    text = format(
        value,
        "f",
    )

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text


# ============================================================
# POSITION DETECTION
# ============================================================

def extract_active_position(positions, symbol):

    if positions is None:
        return None

    if isinstance(positions, dict):

        # Sometimes API may wrap the array.
        for key in (
            "positions",
            "data",
            "result",
        ):

            if key in positions:

                candidate = positions[key]

                if isinstance(candidate, list):
                    positions = candidate
                    break

    if not isinstance(positions, list):
        return None

    for p in positions:

        if not isinstance(p, dict):
            continue

        p_symbol = str(
            p.get("symbol", "")
        ).upper()

        if p_symbol != symbol:
            continue

        amount = None

        for key in (
            "positionAmt",
            "amount",
            "quantity",
            "positionQuantity",
            "size",
        ):

            if key in p:
                amount = decimal_from(
                    p[key]
                )
                break

        if amount is not None and amount != 0:
            return p

        # Some Tabdeal responses may identify
        # active state without positionAmt.
        state = str(
            p.get("state", "")
        ).lower()

        is_active = p.get("isActive")

        if state in (
            "active",
            "open",
        ):
            return p

        if is_active in (
            True,
            1,
            "1",
            "true",
        ):
            return p

    return None


# ============================================================
# SIMPLE PRICE ACTION SIGNAL
#
# No EMA.
# No indicator.
# Closed-candle breakout.
# ============================================================

def get_market_signal(symbol_info):

    """
    This function intentionally does not use EMA/RSI/MACD.

    For the first working Futures version we keep the trading
    logic conservative and separate from API connectivity.
    """

    # Public exchangeInfo does not provide candles.
    # Therefore this version only validates the Futures API.
    #
    # Actual entry signal should be added after the API
    # connection is confirmed.
    return None


# ============================================================
# MAIN
# ============================================================

def main():

    telegram(
        "💓 ATI FUTURES ALIVE\n"
        "⚡ API STRUCTURE FIXED\n"
        f"📡 {SYMBOL}\n"
        f"⏱ {INTERVAL}\n"
        f"🔧 LEVERAGE: {LEVERAGE}x\n"
        f"💵 ORDER MARGIN: {ORDER_USDT} USDT\n"
        f"🔓 LIVE: {LIVE_TRADING}\n"
        "📥 GET  -> /r/fapi/\n"
        "📤 POST -> /fapi/"
    )

    try:

        # ----------------------------------------------------
        # 1. Public ping
        # ----------------------------------------------------

        ping = futures_ping()

        print("PING OK:", ping)

        # ----------------------------------------------------
        # 2. Server time
        # ----------------------------------------------------

        server_time = futures_time()

        print("SERVER TIME:", server_time)

        # ----------------------------------------------------
        # 3. Exchange info
        # ----------------------------------------------------

        info = exchange_info(SYMBOL)

        symbol_info = find_symbol_info(
            info,
            SYMBOL,
        )

        if symbol_info is None:

            raise RuntimeError(
                f"Futures symbol not found: {SYMBOL}"
            )

        print(
            "EXCHANGE INFO OK:",
            json.dumps(
                symbol_info,
                ensure_ascii=False,
            )[:3000],
        )

        # ----------------------------------------------------
        # 4. Authentication
        # ----------------------------------------------------

        if not API_KEY or not API_SECRET:

            raise RuntimeError(
                "API credentials are missing."
            )

        account = get_account()

        print(
            "AUTH SUCCESS:",
            json.dumps(
                account,
                ensure_ascii=False,
            )[:3000],
        )

        # ----------------------------------------------------
        # 5. Balance
        # ----------------------------------------------------

        balance = get_balance()

        print(
            "FUTURES BALANCE:",
            json.dumps(
                balance,
                ensure_ascii=False,
            )[:3000],
        )

        # ----------------------------------------------------
        # 6. Current position
        # ----------------------------------------------------

        positions = get_positions(SYMBOL)

        print(
            "POSITIONS:",
            json.dumps(
                positions,
                ensure_ascii=False,
            )[:3000],
        )

        active_position = extract_active_position(
            positions,
            SYMBOL,
        )

        if active_position:

            telegram(
                "📌 ATI FUTURES\n"
                "⚠️ ACTIVE POSITION EXISTS\n"
                f"Symbol: {SYMBOL}\n"
                f"Position: {json.dumps(active_position, ensure_ascii=False)[:1200]}\n"
                "🚫 New entry skipped."
            )

            print(
                "ACTIVE POSITION FOUND."
            )

            return

        # ----------------------------------------------------
        # 7. Leverage
        # ----------------------------------------------------

        try:

            lev = get_leverage(SYMBOL)

            print(
                "CURRENT LEVERAGE:",
                lev,
            )

        except Exception as exc:

            print(
                "GET LEVERAGE WARNING:",
                repr(exc),
            )

        # ----------------------------------------------------
        # 8. Set leverage
        # ----------------------------------------------------

        if LIVE_TRADING:

            try:

                lev_result = change_leverage(
                    SYMBOL,
                    LEVERAGE,
                )

                print(
                    "LEVERAGE SET:",
                    lev_result,
                )

            except Exception as exc:

                # If leverage is already correct,
                # some exchanges can still return a warning.
                print(
                    "LEVERAGE SET WARNING:",
                    repr(exc),
                )

        # ----------------------------------------------------
        # 9. Signal
        # ----------------------------------------------------

        signal = get_market_signal(
            symbol_info
        )

        if signal is None:

            telegram(
                "📊 ATI FUTURES\n"
                f"✅ API OK: {SYMBOL}\n"
                "🔐 AUTH OK\n"
                f"🔧 LEVERAGE: {LEVERAGE}x\n"
                "🔎 NO ENTRY SIGNAL\n"
                "🚫 NO ORDER SENT"
            )

            print(
                "NO SIGNAL - NO ORDER."
            )

            return

        # ----------------------------------------------------
        # 10. Real order section
        # ----------------------------------------------------

        if not LIVE_TRADING:

            telegram(
                "🧪 ATI FUTURES PAPER MODE\n"
                f"Signal: {signal}\n"
                "🚫 LIVE_TRADING=false"
            )

            return

        side = signal["side"]
        price = Decimal(str(signal["price"]))

        step_size, min_qty = get_quantity_rules(
            symbol_info
        )

        # Margin * leverage = approximate notional.
        notional = (
            ORDER_USDT
            * Decimal(LEVERAGE)
        )

        quantity = (
            notional / price
        )

        quantity = floor_to_step(
            quantity,
            step_size,
        )

        if quantity <= 0:
            raise RuntimeError(
                f"Calculated quantity is zero. "
                f"price={price}, "
                f"order_usdt={ORDER_USDT}, "
                f"leverage={LEVERAGE}, "
                f"step={step_size}"
            )

        if min_qty > 0 and quantity < min_qty:

            raise RuntimeError(
                f"Quantity {quantity} is below "
                f"minimum quantity {min_qty}"
            )

        quantity_text = decimal_string(
            quantity
        )

        telegram(
            "🚨 ATI FUTURES REAL ORDER\n"
            f"Symbol: {SYMBOL}\n"
            f"Side: {side}\n"
            f"Price: {price}\n"
            f"Quantity: {quantity_text}\n"
            f"Leverage: {LEVERAGE}x"
        )

        # ----------------------------------------------------
        # 11. MARKET ENTRY
        # ----------------------------------------------------

        order = new_market_order(
            SYMBOL,
            side,
            quantity_text,
        )

        print(
            "ENTRY ORDER:",
            json.dumps(
                order,
                ensure_ascii=False,
            )[:5000],
        )

        # ----------------------------------------------------
        # 12. Get position after entry
        # ----------------------------------------------------

        time.sleep(1)

        positions_after = get_positions(
            SYMBOL
        )

        print(
            "POSITIONS AFTER ENTRY:",
            json.dumps(
                positions_after,
                ensure_ascii=False,
            )[:5000],
        )

        position = extract_active_position(
            positions_after,
            SYMBOL,
        )

        if not position:

            telegram(
                "⚠️ ENTRY ORDER SENT\n"
                "اما پوزیشن فعال از API دریافت نشد.\n"
                "SL/TP تنظیم نشد."
            )

            return

        # ----------------------------------------------------
        # 13. Position ID
        # ----------------------------------------------------

        position_id = (
            position.get("positionId")
            or position.get("id")
        )

        if position_id is None:

            raise RuntimeError(
                "Position ID was not returned; "
                "cannot safely set SL/TP."
            )

        # ----------------------------------------------------
        # 14. Entry price
        # ----------------------------------------------------

        entry_price = None

        for key in (
            "entryPrice",
            "avgPrice",
            "averagePrice",
            "price",
        ):

            if key in position:

                candidate = decimal_from(
                    position[key]
                )

                if candidate > 0:
                    entry_price = candidate
                    break

        if entry_price is None:
            entry_price = price

        # ----------------------------------------------------
        # 15. Calculate SL / TP
        # ----------------------------------------------------

        if side == "BUY":

            tp_price = (
                entry_price
                * (
                    Decimal("1")
                    + TP_PERCENT / Decimal("100")
                )
            )

            sl_price = (
                entry_price
                * (
                    Decimal("1")
                    - SL_PERCENT / Decimal("100")
                )
            )

        else:

            tp_price = (
                entry_price
                * (
                    Decimal("1")
                    - TP_PERCENT / Decimal("100")
                )
            )

            sl_price = (
                entry_price
                * (
                    Decimal("1")
                    + SL_PERCENT / Decimal("100")
                )
            )

        # Use a conservative 8 decimal representation.
        tp_price = tp_price.quantize(
            Decimal("0.00000001"),
            rounding=ROUND_DOWN,
        )

        sl_price = sl_price.quantize(
            Decimal("0.00000001"),
            rounding=ROUND_DOWN,
        )

        # ----------------------------------------------------
        # 16. SL / TP
        # ----------------------------------------------------

        sltp = set_position_sl_tp(
            position_id=position_id,
            symbol=SYMBOL,
            sl_price=decimal_string(sl_price),
            tp_price=decimal_string(tp_price),
        )

        print(
            "SL/TP RESULT:",
            json.dumps(
                sltp,
                ensure_ascii=False,
            )[:5000],
        )

        telegram(
            "✅ ATI FUTURES TRADE OPENED\n"
            f"📌 {SYMBOL}\n"
            f"➡️ SIDE: {side}\n"
            f"💰 ENTRY: {entry_price}\n"
            f"🔧 LEVERAGE: {LEVERAGE}x\n"
            f"📦 QTY: {quantity_text}\n"
            f"🎯 TP: {tp_price}\n"
            f"🛑 SL: {sl_price}"
        )

    except Exception as exc:

        error_text = (
            "❌ ATI FUTURES ERROR\n\n"
            f"{type(exc).__name__}: {exc}"
        )

        print(error_text)

        telegram(error_text)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
