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
# TABDEAL FUTURES REST
#
# GET /r/fapi/
# POST /fapi/
# DELETE /fapi/
#
# NO tabdeal.future import
# ============================================================


# ============================================================
# CONFIG
# ============================================================

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

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


LIVE_TRADING = (
    os.getenv(
        "LIVE_TRADING",
        "false"
    ).lower()
    == "true"
)


SYMBOL = os.getenv(
    "FUTURES_SYMBOL",
    "BTCUSDT"
).upper()


INTERVAL = os.getenv(
    "FUTURES_INTERVAL",
    "5m"
)


LEVERAGE = int(
    os.getenv(
        "FUTURES_LEVERAGE",
        "3"
    )
)


ORDER_USDT = Decimal(
    os.getenv(
        "FUTURES_ORDER_USDT",
        "2"
    )
)


TP_PERCENT = Decimal(
    os.getenv(
        "FUTURES_TP_PERCENT",
        "2"
    )
)


SL_PERCENT = Decimal(
    os.getenv(
        "FUTURES_SL_PERCENT",
        "1"
    )
)


RECV_WINDOW = int(
    os.getenv(
        "RECV_WINDOW",
        "5000"
    )
)


# ============================================================
# TABDEAL FUTURES BASE URL
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

READ_BASE = (
    f"{BASE_URL}/r/fapi/"
)

WRITE_BASE = (
    f"{BASE_URL}/fapi/"
)


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

def telegram(message):

    print(message)

    if not TELEGRAM_BOT_TOKEN:
        return

    if not TELEGRAM_CHAT_ID:
        return

    try:

        url = (
            "https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}"
            "/sendMessage"
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

            print(
                "TELEGRAM ERROR:",
                response.text
            )

    except Exception as exc:

        print(
            "TELEGRAM EXCEPTION:",
            repr(exc)
        )


# ============================================================
# RESPONSE PARSER
# ============================================================

def parse_response(response):

    text = response.text

    try:

        data = response.json()

    except Exception:

        data = None


    if response.status_code >= 400:

        if isinstance(data, dict):

            code = data.get(
                "code",
                ""
            )

            msg = data.get(
                "msg",
                data
            )

            raise RuntimeError(
                f"HTTP {response.status_code} | "
                f"code={code} | "
                f"msg={msg}"
            )

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{text[:2000]}"
        )


    return data


# ============================================================
# PUBLIC GET
# /r/fapi/
# ============================================================

def public_get(
    path,
    params=None
):

    url = READ_BASE + path

    print(
        f"GET {url}"
    )

    response = session.get(
        url,
        params=params or {},
        timeout=25,
    )

    return parse_response(
        response
    )


# ============================================================
# SIGNED REQUEST
#
# GET    -> /r/fapi/
# POST   -> /fapi/
# DELETE -> /fapi/
# ============================================================

def signed_request(
    method,
    path,
    params=None
):

    if not API_KEY:

        raise RuntimeError(
            "API KEY is empty."
        )

    if not API_SECRET:

        raise RuntimeError(
            "API SECRET is empty."
        )


    data = {}

    if params:

        data.update(
            params
        )


    # Timestamp
    data["timestamp"] = int(
        time.time() * 1000
    )


    # Receive window
    data["recvWindow"] = (
        RECV_WINDOW
    )


    # Build signature
    query_string = urlencode(
        data
    )


    signature = hmac.new(
        API_SECRET.encode(
            "utf-8"
        ),
        query_string.encode(
            "utf-8"
        ),
        hashlib.sha256
    ).hexdigest()


    data["signature"] = signature


    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type":
            "application/x-www-form-urlencoded",
    }


    method = method.upper()


    # --------------------------------------------------------
    # GET -> READ
    # --------------------------------------------------------

    if method == "GET":

        url = (
            READ_BASE + path
        )

        print(
            f"GET {url}"
        )

        response = session.get(
            url,
            params=data,
            headers=headers,
            timeout=25,
        )


    # --------------------------------------------------------
    # POST -> WRITE
    # --------------------------------------------------------

    elif method == "POST":

        url = (
            WRITE_BASE + path
        )

        print(
            f"POST {url}"
        )

        response = session.post(
            url,
            data=data,
            headers=headers,
            timeout=25,
        )


    # --------------------------------------------------------
    # DELETE -> WRITE
    # --------------------------------------------------------

    elif method == "DELETE":

        url = (
            WRITE_BASE + path
        )

        print(
            f"DELETE {url}"
        )

        response = session.delete(
            url,
            params=data,
            headers=headers,
            timeout=25,
        )


    else:

        raise RuntimeError(
            f"Unsupported HTTP method: {method}"
        )


    return parse_response(
        response
    )


# ============================================================
# PUBLIC FUTURES API
# ============================================================

def futures_ping():

    return public_get(
        "v1/ping"
    )


def futures_time():

    return public_get(
        "v1/time"
    )


def exchange_info():

    return public_get(
        "v1/exchangeInfo"
    )


# ============================================================
# ACCOUNT
# ============================================================

def get_account():

    return signed_request(
        "GET",
        "v3/account"
    )


def get_balance():

    return signed_request(
        "GET",
        "v3/balance"
    )


def get_positions(
    symbol=None
):

    params = {}

    if symbol:

        params["symbol"] = (
            symbol
        )

    return signed_request(
        "GET",
        "v1/position",
        params
    )


def get_position_risk(
    symbol=None
):

    params = {}

    if symbol:

        params["symbol"] = (
            symbol
        )

    return signed_request(
        "GET",
        "v3/positionRisk",
        params
    )


# ============================================================
# LEVERAGE
# ============================================================

def get_leverage(
    symbol
):

    return signed_request(
        "GET",
        "v1/leverage",
        {
            "symbol": symbol
        }
    )


def change_leverage(
    symbol,
    leverage
):

    return signed_request(
        "POST",
        "v1/leverage",
        {
            "symbol": symbol,
            "leverage": leverage,
        }
    )


# ============================================================
# ORDER
# ============================================================

def new_market_order(
    symbol,
    side,
    quantity
):

    return signed_request(
        "POST",
        "v1/order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        }
    )


# ============================================================
# SL / TP
# ============================================================

def set_position_sl_tp(
    position_id,
    symbol,
    sl_price,
    tp_price
):

    return signed_request(
        "POST",
        "v1/positionSlTp",
        {
            "positionId": position_id,
            "symbol": symbol,
            "slPrice": sl_price,
            "tpPrice": tp_price,
        }
    )


# ============================================================
# DECIMAL HELPERS
# ============================================================

def decimal_from(
    value,
    default="0"
):

    try:

        return Decimal(
            str(value)
        )

    except Exception:

        return Decimal(
            default
        )


def decimal_string(
    value
):

    value = Decimal(
        value
    )

    result = format(
        value,
        "f"
    )

    if "." in result:

        result = (
            result
            .rstrip("0")
            .rstrip(".")
        )

    return result


def floor_to_step(
    value,
    step
):

    if step <= 0:

        return value

    units = (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    )

    return units * step


# ============================================================
# EXCHANGE INFO PARSER
# ============================================================

def extract_symbols_container(
    info
):

    """
    Handles all likely Tabdeal response wrappers.

    Possible forms:

    {
        "symbols": [...]
    }

    {
        "data": {
            "symbols": [...]
        }
    }

    {
        "result": {
            "symbols": [...]
        }
    }

    {
        "data": [...]
    }

    {
        "result": [...]
    }

    Or direct list.
    """

    if isinstance(
        info,
        list
    ):

        return info


    if not isinstance(
        info,
        dict
    ):

        return []


    # symbols directly
    if isinstance(
        info.get("symbols"),
        list
    ):

        return info[
            "symbols"
        ]


    # data
    data = info.get(
        "data"
    )

    if isinstance(
        data,
        list
    ):

        return data


    if isinstance(
        data,
        dict
    ):

        if isinstance(
            data.get("symbols"),
            list
        ):

            return data[
                "symbols"
            ]


    # result
    result = info.get(
        "result"
    )

    if isinstance(
        result,
        list
    ):

        return result


    if isinstance(
        result,
        dict
    ):

        if isinstance(
            result.get("symbols"),
            list
        ):

            return result[
                "symbols"
            ]


    return []


def find_symbol_info(
    info,
    symbol
):

    symbol = (
        str(symbol)
        .upper()
        .strip()
    )


    symbols = (
        extract_symbols_container(
            info
        )
    )


    print(
        "EXCHANGE SYMBOL COUNT:",
        len(symbols)
    )


    # Exact symbol
    for item in symbols:

        if not isinstance(
            item,
            dict
        ):
            continue

        item_symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).upper().strip()


        if item_symbol == symbol:

            return item


    return None


# ============================================================
# SYMBOL DIAGNOSTIC
# ============================================================

def print_symbol_diagnostic(
    info
):

    symbols = (
        extract_symbols_container(
            info
        )
    )


    print(
        "TOTAL SYMBOLS:",
        len(symbols)
    )


    if not symbols:

        print(
            "EXCHANGE INFO RAW:"
        )

        print(
            json.dumps(
                info,
                ensure_ascii=False
            )[:8000]
        )

        return


    names = []


    for item in symbols:

        if not isinstance(
            item,
            dict
        ):
            continue

        name = item.get(
            "symbol"
        )

        if name:

            names.append(
                str(name)
            )


    print(
        "FIRST SYMBOLS:"
    )

    print(
        names[:100]
    )


    # Find BTC-like names
    btc_names = [
        x for x in names
        if "BTC" in x.upper()
    ]


    if btc_names:

        print(
            "BTC SYMBOLS:"
        )

        print(
            btc_names[:50]
        )


# ============================================================
# QUANTITY RULES
# ============================================================

def get_quantity_rules(
    symbol_info
):

    step_size = Decimal(
        "0.000001"
    )

    min_qty = Decimal(
        "0"
    )


    if not isinstance(
        symbol_info,
        dict
    ):

        return (
            step_size,
            min_qty
        )


    filters = symbol_info.get(
        "filters",
        []
    )


    if not isinstance(
        filters,
        list
    ):

        return (
            step_size,
            min_qty
        )


    for item in filters:

        if not isinstance(
            item,
            dict
        ):
            continue


        filter_type = str(
            item.get(
                "filterType",
                ""
            )
        ).upper()


        if filter_type in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE"
        ):

            if item.get(
                "stepSize"
            ) is not None:

                step_size = (
                    decimal_from(
                        item[
                            "stepSize"
                        ],
                        "0.000001"
                    )
                )


            if item.get(
                "minQty"
            ) is not None:

                min_qty = (
                    decimal_from(
                        item[
                            "minQty"
                        ],
                        "0"
                    )
                )


            break


    return (
        step_size,
        min_qty
    )


# ============================================================
# ACTIVE POSITION PARSER
# ============================================================

def extract_position_list(
    data
):

    if isinstance(
        data,
        list
    ):

        return data


    if not isinstance(
        data,
        dict
    ):

        return []


    for key in (
        "positions",
        "data",
        "result",
    ):

        value = data.get(
            key
        )


        if isinstance(
            value,
            list
        ):

            return value


        if isinstance(
            value,
            dict
        ):

            nested = extract_position_list(
                value
            )

            if nested:

                return nested


    return []


def extract_active_position(
    positions,
    symbol
):

    symbol = (
        str(symbol)
        .upper()
        .strip()
    )


    items = (
        extract_position_list(
            positions
        )
    )


    for item in items:

        if not isinstance(
            item,
            dict
        ):
            continue


        item_symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).upper().strip()


        if item_symbol != symbol:
            continue


        # Common Futures fields
        for key in (
            "positionAmt",
            "amount",
            "quantity",
            "positionQuantity",
            "size",
        ):

            if key in item:

                amount = decimal_from(
                    item[key]
                )

                if amount != 0:

                    return item


        # Alternate state
        state = str(
            item.get(
                "state",
                ""
            )
        ).lower()


        if state in (
            "open",
            "active"
        ):

            return item


        if item.get(
            "isActive"
        ) in (
            True,
            1,
            "1",
            "true"
        ):

            return item


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

        # ====================================================
        # 1. PING
        # ====================================================

        ping = futures_ping()

        print(
            "✅ PING OK:"
        )

        print(
            json.dumps(
                ping,
                ensure_ascii=False
            )
        )


        # ====================================================
        # 2. SERVER TIME
        # ====================================================

        server_time = (
            futures_time()
        )

        print(
            "✅ SERVER TIME:"
        )

        print(
            json.dumps(
                server_time,
                ensure_ascii=False
            )
        )


        # ====================================================
        # 3. EXCHANGE INFO
        # ====================================================

        info = exchange_info()

        print(
            "✅ EXCHANGE INFO RECEIVED"
        )


        print_symbol_diagnostic(
            info
        )


        # ====================================================
        # 4. FIND SYMBOL
        # ====================================================

        symbol_info = (
            find_symbol_info(
                info,
                SYMBOL
            )
        )


        if symbol_info is None:

            telegram(
                "❌ ATI FUTURES SYMBOL ERROR\n\n"
                f"Requested: {SYMBOL}\n\n"
                "ExchangeInfo دریافت شد، "
                "اما این نماد در پاسخ پیدا نشد.\n\n"
                "لیست نمادهای BTC در لاگ GitHub چاپ شده است."
            )


            raise RuntimeError(
                f"Futures symbol not found: "
                f"{SYMBOL}"
            )


        print(
            "✅ FUTURES SYMBOL FOUND:",
            SYMBOL
        )


        print(
            "SYMBOL INFO:"
        )

        print(
            json.dumps(
                symbol_info,
                ensure_ascii=False
            )[:6000]
        )


        # ====================================================
        # 5. AUTH CHECK
        # ====================================================

        if not API_KEY:

            raise RuntimeError(
                "TABDIL_API_KEY / "
                "TABDEAL_API_KEY is missing."
            )


        if not API_SECRET:

            raise RuntimeError(
                "TABDIL_API_SECRET / "
                "TABDEAL_API_SECRET is missing."
            )


        account = (
            get_account()
        )


        print(
            "✅ AUTH SUCCESS"
        )


        print(
            json.dumps(
                account,
                ensure_ascii=False
            )[:5000]
        )


        # ====================================================
        # 6. BALANCE
        # ====================================================

        balance = (
            get_balance()
        )


        print(
            "💰 FUTURES BALANCE:"
        )


        print(
            json.dumps(
                balance,
                ensure_ascii=False
            )[:6000]
        )


        # ====================================================
        # 7. CURRENT POSITION
        # ====================================================

        positions = (
            get_positions(
                SYMBOL
            )
        )


        print(
            "📊 CURRENT POSITIONS:"
        )


        print(
            json.dumps(
                positions,
                ensure_ascii=False
            )[:6000]
        )


        active_position = (
            extract_active_position(
                positions,
                SYMBOL
            )
        )


        if active_position:

            telegram(
                "📌 ATI FUTURES\n"
                "⚠️ ACTIVE POSITION EXISTS\n"
                f"📡 {SYMBOL}\n"
                "🚫 New entry skipped.\n\n"
                f"{json.dumps(active_position, ensure_ascii=False)[:2000]}"
            )


            return


        # ====================================================
        # 8. LEVERAGE
        # ====================================================

        try:

            current_leverage = (
                get_leverage(
                    SYMBOL
                )
            )


            print(
                "CURRENT LEVERAGE:"
            )


            print(
                json.dumps(
                    current_leverage,
                    ensure_ascii=False
                )
            )


        except Exception as exc:

            print(
                "LEVERAGE READ WARNING:",
                repr(exc)
            )


        # ====================================================
        # 9. LIVE MODE
        # ====================================================

        if LIVE_TRADING:

            print(
                "🔴 LIVE TRADING ENABLED"
            )


            try:

                leverage_result = (
                    change_leverage(
                        SYMBOL,
                        LEVERAGE
                    )
                )


                print(
                    "✅ LEVERAGE SET:"
                )


                print(
                    json.dumps(
                        leverage_result,
                        ensure_ascii=False
                    )
                )


            except Exception as exc:

                print(
                    "LEVERAGE SET WARNING:",
                    repr(exc)
                )


        else:

            print(
                "🟢 LIVE TRADING OFF"
            )


        # ====================================================
        # 10. NO AUTO ENTRY YET
        # ====================================================
        #
        # IMPORTANT:
        # API validation is complete.
        # We intentionally do not send an order from this
        # diagnostic version.
        #
        # This prevents an accidental real Futures order
        # while the symbol/API structure is being verified.
        # ====================================================

        telegram(
            "✅ ATI FUTURES API OK\n\n"
            f"📡 SYMBOL: {SYMBOL}\n"
            f"⏱ INTERVAL: {INTERVAL}\n"
            f"🔧 LEVERAGE: {LEVERAGE}x\n"
            f"💰 ORDER MARGIN: {ORDER_USDT} USDT\n"
            f"🔓 LIVE: {LIVE_TRADING}\n\n"
            "✅ PING OK\n"
            "✅ SERVER TIME OK\n"
            "✅ EXCHANGE INFO OK\n"
            "✅ SYMBOL FOUND\n"
            "✅ AUTH OK\n"
            "✅ BALANCE READ OK\n"
            "✅ POSITION READ OK\n\n"
            "🚫 NO ORDER SENT"
        )


    except Exception as exc:

        error_message = (
            "❌ ATI FUTURES ERROR\n\n"
            f"{type(exc).__name__}: {exc}"
        )


        print(
            error_message
        )


        telegram(
            error_message
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
