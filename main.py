import os
import time
import hmac
import hashlib
import json
from urllib.parse import urlencode

import requests


# ============================================================
# ATI FUTURES - TABDEAL
#
# Official Tabdeal Futures structure:
#
# GET:
#   https://api1.tabdeal.org/r/fapi/
#
# POST / DELETE:
#   https://api1.tabdeal.org/fapi/
#
# No tabdeal.future import
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


SYMBOL = os.getenv(
    "FUTURES_SYMBOL",
    "BTCUSDT"
).upper().strip()


LEVERAGE = int(
    os.getenv(
        "FUTURES_LEVERAGE",
        "3"
    )
)


ORDER_USDT = os.getenv(
    "FUTURES_ORDER_USDT",
    "2"
)


LIVE_TRADING = (
    os.getenv(
        "LIVE_TRADING",
        "false"
    ).lower()
    == "true"
)


RECV_WINDOW = int(
    os.getenv(
        "RECV_WINDOW",
        "5000"
    )
)


BASE_URL = "https://api1.tabdeal.org"

READ_BASE = (
    BASE_URL + "/r/fapi/"
)

WRITE_BASE = (
    BASE_URL + "/fapi/"
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

    print("\n" + message)

    if not TELEGRAM_BOT_TOKEN:
        return

    if not TELEGRAM_CHAT_ID:
        return

    try:

        url = (
            "https://api.telegram.org/bot"
            + TELEGRAM_BOT_TOKEN
            + "/sendMessage"
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
                response.text[:1000]
            )

    except Exception as exc:

        print(
            "TELEGRAM EXCEPTION:",
            repr(exc)
        )


# ============================================================
# RESPONSE HANDLER
# ============================================================

def handle_response(response):

    print(
        "HTTP STATUS:",
        response.status_code
    )

    try:

        data = response.json()

    except Exception:

        data = None


    if response.status_code >= 400:

        if isinstance(data, dict):

            raise RuntimeError(
                "HTTP "
                + str(response.status_code)
                + " | code="
                + str(data.get("code", ""))
                + " | msg="
                + str(data.get("msg", data))
            )

        raise RuntimeError(
            "HTTP "
            + str(response.status_code)
            + ": "
            + response.text[:2000]
        )


    return data


# ============================================================
# PUBLIC GET
# /r/fapi/
# ============================================================

def public_get(
    endpoint,
    params=None
):

    url = (
        READ_BASE
        + endpoint
    )

    print(
        "\n➡️ PUBLIC GET:"
    )

    print(
        url
    )

    if params:

        print(
            "PARAMS:",
            params
        )


    response = session.get(
        url,
        params=params or {},
        timeout=25,
    )


    return handle_response(
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
    endpoint,
    params=None
):

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


    data = {}

    if params:

        data.update(
            params
        )


    # Same signing concept as official Client
    data["timestamp"] = (
        int(time.time() * 1000)
    )

    data["recvWindow"] = (
        RECV_WINDOW
    )


    query = urlencode(
        data
    )


    signature = hmac.new(
        API_SECRET.encode(
            "utf-8"
        ),
        query.encode(
            "utf-8"
        ),
        hashlib.sha256
    ).hexdigest()


    data["signature"] = (
        signature
    )


    headers = {
        "X-MBX-APIKEY": API_KEY
    }


    method = method.upper()


    # --------------------------------------------------------
    # GET -> READ
    # --------------------------------------------------------

    if method == "GET":

        url = (
            READ_BASE
            + endpoint
        )

        print(
            "\n🔐 SIGNED GET:"
        )

        print(
            url
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
            WRITE_BASE
            + endpoint
        )

        print(
            "\n🔐 SIGNED POST:"
        )

        print(
            url
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
            WRITE_BASE
            + endpoint
        )

        print(
            "\n🔐 SIGNED DELETE:"
        )

        print(
            url
        )

        response = session.delete(
            url,
            params=data,
            headers=headers,
            timeout=25,
        )


    else:

        raise RuntimeError(
            "Unsupported method: "
            + method
        )


    return handle_response(
        response
    )


# ============================================================
# PUBLIC FUTURES
# ============================================================

def futures_ping():

    return public_get(
        "v1/ping"
    )


def futures_time():

    return public_get(
        "v1/time"
    )


def futures_exchange_info(
    symbol
):

    # IMPORTANT:
    # Official Future.exchange_info()
    # supports direct symbol parameter.

    return public_get(
        "v1/exchangeInfo",
        {
            "symbol": symbol
        }
    )


def futures_depth(
    symbol
):

    return public_get(
        "v1/depth",
        {
            "symbol": symbol,
            "limit": 20
        }
    )


# ============================================================
# ACCOUNT
# ============================================================

def futures_account():

    return signed_request(
        "GET",
        "v3/account"
    )


def futures_balance():

    return signed_request(
        "GET",
        "v3/balance"
    )


# ============================================================
# POSITION
# ============================================================

def futures_positions(
    symbol
):

    return signed_request(
        "GET",
        "v1/position",
        {
            "symbol": symbol
        }
    )


def futures_position_risk(
    symbol
):

    return signed_request(
        "GET",
        "v3/positionRisk",
        {
            "symbol": symbol
        }
    )


# ============================================================
# LEVERAGE
# ============================================================

def futures_get_leverage(
    symbol
):

    return signed_request(
        "GET",
        "v1/leverage",
        {
            "symbol": symbol
        }
    )


def futures_set_leverage(
    symbol,
    leverage
):

    return signed_request(
        "POST",
        "v1/leverage",
        {
            "symbol": symbol,
            "leverage": leverage
        }
    )


# ============================================================
# POSITION PARSER
# ============================================================

def find_active_position(
    data,
    symbol
):

    if isinstance(
        data,
        list
    ):

        items = data

    elif isinstance(
        data,
        dict
    ):

        items = []

        for key in (
            "positions",
            "data",
            "result"
        ):

            value = data.get(
                key
            )

            if isinstance(
                value,
                list
            ):

                items = value
                break

            if isinstance(
                value,
                dict
            ):

                for nested_key in (
                    "positions",
                    "data",
                    "result"
                ):

                    nested = value.get(
                        nested_key
                    )

                    if isinstance(
                        nested,
                        list
                    ):

                        items = nested
                        break

                if items:
                    break

    else:

        items = []


    symbol = symbol.upper()


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
        ).upper()


        if item_symbol != symbol:
            continue


        # Try common position amount fields
        for field in (
            "positionAmt",
            "amount",
            "quantity",
            "positionQuantity",
            "size"
        ):

            if field in item:

                try:

                    amount = float(
                        item[field]
                    )

                    if amount != 0:

                        return item

                except Exception:

                    pass


        # Alternative active/state fields
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
        "⚡ V2 DIRECT SYMBOL TEST\n"
        f"📡 {SYMBOL}\n"
        f"🔧 LEVERAGE: {LEVERAGE}x\n"
        f"💵 ORDER MARGIN: {ORDER_USDT} USDT\n"
        f"🔓 LIVE: {LIVE_TRADING}\n"
        "📥 GET  -> /r/fapi/\n"
        "📤 POST -> /fapi/"
    )


    try:

        # ====================================================
        # STEP 1 - PING
        # ====================================================

        ping = futures_ping()

        print(
            "\n✅ FUTURES PING OK"
        )

        print(
            json.dumps(
                ping,
                ensure_ascii=False
            )
        )


        # ====================================================
        # STEP 2 - SERVER TIME
        # ====================================================

        server_time = (
            futures_time()
        )

        print(
            "\n✅ FUTURES TIME OK"
        )

        print(
            json.dumps(
                server_time,
                ensure_ascii=False
            )
        )


        # ====================================================
        # STEP 3 - DIRECT BTCUSDT EXCHANGE INFO
        # ====================================================

        print(
            "\n🔎 DIRECT SYMBOL TEST:"
        )

        print(
            SYMBOL
        )


        symbol_info = (
            futures_exchange_info(
                SYMBOL
            )
        )


        print(
            "\n✅ EXCHANGE INFO RESPONSE:"
        )

        print(
            json.dumps(
                symbol_info,
                ensure_ascii=False,
                indent=2
            )[:10000]
        )


        # ====================================================
        # IMPORTANT:
        # Do NOT assume symbols[] exists.
        # Direct symbol request itself is the test.
        # ====================================================

        print(
            "\n✅ DIRECT SYMBOL REQUEST ACCEPTED:"
        )

        print(
            SYMBOL
        )


        # ====================================================
        # STEP 4 - DEPTH TEST
        # ====================================================

        depth = (
            futures_depth(
                SYMBOL
            )
        )


        print(
            "\n✅ DEPTH OK:"
        )

        print(
            json.dumps(
                depth,
                ensure_ascii=False,
                indent=2
            )[:8000]
        )


        # ====================================================
        # STEP 5 - API CREDENTIAL CHECK
        # ====================================================

        if not API_KEY:

            raise RuntimeError(
                "API KEY missing."
            )


        if not API_SECRET:

            raise RuntimeError(
                "API SECRET missing."
            )


        # ====================================================
        # STEP 6 - ACCOUNT
        # ====================================================

        account = (
            futures_account()
        )


        print(
            "\n✅ AUTH SUCCESS"
        )

        print(
            json.dumps(
                account,
                ensure_ascii=False,
                indent=2
            )[:8000]
        )


        # ====================================================
        # STEP 7 - BALANCE
        # ====================================================

        balance = (
            futures_balance()
        )


        print(
            "\n💰 FUTURES BALANCE:"
        )

        print(
            json.dumps(
                balance,
                ensure_ascii=False,
                indent=2
            )[:8000]
        )


        # ====================================================
        # STEP 8 - POSITION
        # ====================================================

        positions = (
            futures_positions(
                SYMBOL
            )
        )


        print(
            "\n📊 FUTURES POSITION:"
        )

        print(
            json.dumps(
                positions,
                ensure_ascii=False,
                indent=2
            )[:8000]
        )


        active = (
            find_active_position(
                positions,
                SYMBOL
            )
        )


        if active:

            telegram(
                "📌 ATI FUTURES\n"
                "⚠️ ACTIVE POSITION FOUND\n\n"
                f"📡 {SYMBOL}\n"
                "🚫 NO NEW ORDER\n\n"
                + json.dumps(
                    active,
                    ensure_ascii=False
                )[:2000]
            )

            return


        # ====================================================
        # STEP 9 - POSITION RISK
        # ====================================================

        try:

            risk = (
                futures_position_risk(
                    SYMBOL
                )
            )


            print(
                "\n📊 POSITION RISK:"
            )

            print(
                json.dumps(
                    risk,
                    ensure_ascii=False,
                    indent=2
                )[:8000]
            )


        except Exception as exc:

            print(
                "\nPOSITION RISK WARNING:",
                repr(exc)
            )


        # ====================================================
        # STEP 10 - CURRENT LEVERAGE
        # ====================================================

        try:

            leverage_info = (
                futures_get_leverage(
                    SYMBOL
                )
            )


            print(
                "\n🔧 CURRENT LEVERAGE:"
            )

            print(
                json.dumps(
                    leverage_info,
                    ensure_ascii=False,
                    indent=2
                )
            )


        except Exception as exc:

            print(
                "\nLEVERAGE READ WARNING:",
                repr(exc)
            )


        # ====================================================
        # STEP 11 - SET LEVERAGE ONLY IF LIVE
        # ====================================================

        if LIVE_TRADING:

            print(
                "\n🔴 LIVE TRADING IS ON"
            )


            leverage_result = (
                futures_set_leverage(
                    SYMBOL,
                    LEVERAGE
                )
            )


            print(
                "\n✅ LEVERAGE SET:"
            )

            print(
                json.dumps(
                    leverage_result,
                    ensure_ascii=False,
                    indent=2
                )
            )


        else:

            print(
                "\n🟢 LIVE TRADING OFF"
            )


        # ====================================================
        # FINAL
        # ====================================================

        telegram(
            "✅ ATI FUTURES API TEST PASSED\n\n"
            f"📡 SYMBOL: {SYMBOL}\n"
            f"🔧 LEVERAGE: {LEVERAGE}x\n"
            f"💵 ORDER MARGIN: {ORDER_USDT} USDT\n"
            f"🔓 LIVE: {LIVE_TRADING}\n\n"
            "✅ PING\n"
            "✅ SERVER TIME\n"
            "✅ DIRECT EXCHANGE INFO\n"
            "✅ DEPTH\n"
            "✅ AUTH\n"
            "✅ BALANCE\n"
            "✅ POSITION\n\n"
            "🚫 NO ORDER SENT"
        )


    except Exception as exc:

        error = (
            "❌ ATI FUTURES ERROR\n\n"
            + type(exc).__name__
            + ": "
            + str(exc)
        )


        print(
            "\n"
            + error
        )


        telegram(
            error
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
