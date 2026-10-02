import os
import time
import hmac
import hashlib
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.30
# TABDEAL DIRECT REST API
# AUTH + EXCHANGE INFO RAW/PARSER TEST
# ============================================================

VERSION = "V40.2.30"

BASE_URL = "https://api1.tabdeal.org"

RECV_WINDOW = int(os.getenv("RECV_WINDOW", "5000"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()

# HARD SAFETY LOCK
LIVE_TRADING = False


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN MISSING")
        print(message)
        return False

    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM_CHAT_ID MISSING")
        print(message)
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            return True

        print(
            "Telegram HTTP:",
            response.status_code,
        )

    except Exception as exc:
        print(
            "Telegram ERROR:",
            repr(exc),
        )

    return False


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():

    try:

        response = requests.get(
            BASE_URL + "/r/api/v1/time",
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            return None

        data = response.json()

        if isinstance(data, dict):

            for key in (
                "serverTime",
                "server_time",
                "timestamp",
                "time",
            ):

                value = data.get(key)

                if value is not None:
                    try:
                        return int(value)
                    except Exception:
                        pass

        if isinstance(data, int):
            return int(data)

    except Exception as exc:

        print(
            "SERVER TIME ERROR:",
            repr(exc),
        )

    return None


# ============================================================
# CREDENTIALS
# ============================================================

def get_credentials():

    candidates = [
        (
            "TABDEAL",
            os.getenv(
                "TABDEAL_API_KEY",
                ""
            ).strip(),
            os.getenv(
                "TABDEAL_API_SECRET",
                ""
            ).strip(),
        ),
        (
            "TABDIL",
            os.getenv(
                "TABDIL_API_KEY",
                ""
            ).strip(),
            os.getenv(
                "TABDIL_API_SECRET",
                ""
            ).strip(),
        ),
    ]

    result = []
    seen = set()

    for name, api_key, api_secret in candidates:

        if not api_key or not api_secret:
            continue

        identity = (
            api_key,
            api_secret,
        )

        if identity in seen:
            continue

        seen.add(identity)

        result.append(
            {
                "name": name,
                "api_key": api_key,
                "api_secret": api_secret,
            }
        )

    return result


# ============================================================
# HMAC
# ============================================================

def make_signature(
    api_secret,
    query_string,
):

    return hmac.new(
        api_secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ============================================================
# AUTH TEST
# ============================================================

def test_auth(
    credential,
    server_time,
):

    api_key = credential["api_key"]
    api_secret = credential["api_secret"]

    timestamp = (
        int(server_time)
        if server_time is not None
        else int(time.time() * 1000)
    )

    query_string = (
        "timestamp="
        + str(timestamp)
        + "&recvWindow="
        + str(RECV_WINDOW)
    )

    signature = make_signature(
        api_secret,
        query_string,
    )

    url = (
        BASE_URL
        + "/r/api/v1/account?"
        + query_string
        + "&signature="
        + signature
    )

    headers = {
        "X-MBX-APIKEY": api_key,
        "Content-Type": "application/json",
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 200:

            return {
                "success": True,
                "data": response.json(),
            }

        try:
            data = response.json()
        except Exception:
            data = {}

        return {
            "success": False,
            "http": response.status_code,
            "data": data,
            "text": response.text[:1000],
        }

    except Exception as exc:

        return {
            "success": False,
            "http": 0,
            "data": {},
            "text": repr(exc),
        }


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    url = (
        BASE_URL
        + "/r/api/v1/exchangeInfo"
    )

    try:

        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
        )

        print(
            "EXCHANGE INFO HTTP:",
            response.status_code,
        )

        print(
            "EXCHANGE INFO CONTENT-TYPE:",
            response.headers.get(
                "content-type",
                "",
            ),
        )

        if response.status_code != 200:

            print(
                "EXCHANGE INFO ERROR:",
                response.text[:2000],
            )

            return None

        try:
            data = response.json()
        except Exception as exc:

            print(
                "EXCHANGE INFO JSON ERROR:",
                repr(exc),
            )

            print(
                "RAW:",
                response.text[:3000],
            )

            return None

        # ----------------------------------------------------
        # IMPORTANT:
        # Print only structural information.
        # Do NOT print API credentials.
        # ----------------------------------------------------

        print(
            "EXCHANGE INFO TYPE:",
            type(data).__name__,
        )

        if isinstance(data, list):

            print(
                "EXCHANGE INFO LIST LENGTH:",
                len(data),
            )

            if data:

                print(
                    "FIRST ITEM TYPE:",
                    type(data[0]).__name__,
                )

                print(
                    "FIRST ITEM:",
                    str(data[0])[:3000],
                )

        elif isinstance(data, dict):

            print(
                "EXCHANGE INFO DICT KEYS:",
                list(data.keys())[:50],
            )

            if "symbols" in data:

                symbols = data.get(
                    "symbols",
                    [],
                )

                print(
                    "SYMBOLS TYPE:",
                    type(symbols).__name__,
                )

                print(
                    "SYMBOLS LENGTH:",
                    len(symbols)
                    if isinstance(symbols, list)
                    else "N/A",
                )

                if isinstance(
                    symbols,
                    list,
                ) and symbols:

                    print(
                        "FIRST SYMBOL:",
                        str(symbols[0])[:3000],
                    )

        return data

    except Exception as exc:

        print(
            "EXCHANGE INFO ERROR:",
            repr(exc),
        )

        return None


# ============================================================
# GET RAW SYMBOL LIST
# ============================================================

def get_raw_symbols(data):

    # --------------------------------------------------------
    # CASE 1:
    # API returns:
    #
    # [
    #   {...},
    #   {...}
    # ]
    # --------------------------------------------------------

    if isinstance(data, list):
        return data

    # --------------------------------------------------------
    # CASE 2:
    # API returns:
    #
    # {
    #   "symbols": [...]
    # }
    # --------------------------------------------------------

    if isinstance(data, dict):

        symbols = data.get(
            "symbols"
        )

        if isinstance(
            symbols,
            list,
        ):
            return symbols

        # Some APIs may nest data.
        nested = data.get("data")

        if isinstance(
            nested,
            list,
        ):
            return nested

        if isinstance(
            nested,
            dict,
        ):

            nested_symbols = nested.get(
                "symbols"
            )

            if isinstance(
                nested_symbols,
                list,
            ):
                return nested_symbols

    return []


# ============================================================
# FILTER HELPERS
# ============================================================

def get_filter(
    filters,
    filter_type,
):

    if not isinstance(
        filters,
        list,
    ):
        return {}

    for item in filters:

        if not isinstance(
            item,
            dict,
        ):
            continue

        if str(
            item.get(
                "filterType",
                "",
            )
        ).upper() == filter_type:

            return item

    return {}


def first_value(
    dictionaries,
    keys,
):

    for dictionary in dictionaries:

        if not isinstance(
            dictionary,
            dict,
        ):
            continue

        for key in keys:

            value = dictionary.get(key)

            if value not in (
                None,
                "",
                0,
                "0",
                "0.0",
            ):
                return value

    return None


# ============================================================
# MARKET PARSER
# ============================================================

def parse_usdt_markets(data):

    raw_symbols = get_raw_symbols(
        data
    )

    markets = []

    for item in raw_symbols:

        if not isinstance(
            item,
            dict,
        ):
            continue

        symbol = str(
            item.get(
                "symbol",
                item.get(
                    "market",
                    item.get(
                        "pair",
                        "",
                    ),
                ),
            )
        ).upper().strip()

        # ----------------------------------------------------
        # Normalize common formats
        # ----------------------------------------------------

        normalized = symbol.replace(
            "_",
            "",
        ).replace(
            "-",
            "",
        ).replace(
            "/",
            "",
        )

        if not normalized.endswith(
            "USDT"
        ):
            continue

        status = str(
            item.get(
                "status",
                "",
            )
        ).upper()

        # ----------------------------------------------------
        # If status exists, keep active/trading.
        # If status is absent, don't reject the market.
        # ----------------------------------------------------

        if status and status not in (
            "TRADING",
            "ENABLED",
            "ACTIVE",
            "ONLINE",
        ):
            continue

        filters = item.get(
            "filters",
            [],
        )

        lot = get_filter(
            filters,
            "LOT_SIZE",
        )

        market_lot = get_filter(
            filters,
            "MARKET_LOT_SIZE",
        )

        min_notional = get_filter(
            filters,
            "MIN_NOTIONAL",
        )

        notional = get_filter(
            filters,
            "NOTIONAL",
        )

        step_size = first_value(
            [
                market_lot,
                lot,
                item,
            ],
            [
                "stepSize",
                "step_size",
            ],
        )

        min_qty = first_value(
            [
                market_lot,
                lot,
                item,
            ],
            [
                "minQty",
                "min_qty",
            ],
        )

        min_notional_value = first_value(
            [
                min_notional,
                notional,
                item,
            ],
            [
                "minNotional",
                "min_notional",
                "min_notional_value",
            ],
        )

        markets.append(
            {
                "symbol": symbol,
                "normalized": normalized,
                "status": status,
                "baseAsset": item.get(
                    "baseAsset",
                    "",
                ),
                "quoteAsset": item.get(
                    "quoteAsset",
                    "",
                ),
                "stepSize": step_size,
                "minQty": min_qty,
                "minNotional": min_notional_value,
            }
        )

    return markets


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print(
        f"ATI CRYPTO BOT {VERSION}"
    )
    print("=" * 70)

    startup = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 AUTH + EXCHANGE INFO TEST\n\n"
        f"🔐 DIRECT REST API\n"
        f"🔐 HMAC-SHA256\n"
        f"🔧 PYTHON SDK: DISABLED\n"
        f"📊 RAW EXCHANGE INFO: ENABLED\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🛑 BUY LOCK: ACTIVE\n\n"
        f"🕐 {utc_now()}"
    )

    print(startup)
    send_telegram(startup)

    # ========================================================
    # TIME
    # ========================================================

    local_time = int(
        time.time() * 1000
    )

    server_time = get_server_time()

    if server_time is not None:

        clock_diff = (
            local_time
            - server_time
        )

        time_message = (
            f"🕐 TABDEAL TIME CHECK\n\n"
            f"LOCAL:\n{local_time}\n\n"
            f"SERVER:\n{server_time}\n\n"
            f"DIFF:\n{clock_diff} ms"
        )

    else:

        clock_diff = None

        time_message = (
            "⚠️ TABDEAL TIME CHECK\n\n"
            "SERVER TIME: UNKNOWN"
        )

    print(time_message)
    send_telegram(time_message)

    # ========================================================
    # AUTH
    # ========================================================

    credentials = get_credentials()

    if not credentials:

        message = (
            f"🚨 ATI AUTH FAILED {VERSION}\n\n"
            f"❌ API CREDENTIALS NOT FOUND\n\n"
            f"🔒 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT"
        )

        print(message)
        send_telegram(message)
        return

    working = None

    for credential in credentials:

        result = test_auth(
            credential,
            server_time,
        )

        if result["success"]:

            working = credential

            break

    if working is None:

        message = (
            f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
            f"❌ DIRECT REST AUTH FAILED\n\n"
            f"🔒 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT"
        )

        print(message)
        send_telegram(message)
        return

    auth_message = (
        f"✅ ATI API AUTH SUCCESS {VERSION}\n\n"
        f"🟢 WORKING PAIR:\n"
        f"{working['name']}\n\n"
        f"🔐 HMAC-SHA256\n"
        f"📡 /r/api/v1/account\n\n"
        f"🔒 REAL BUY: DISABLED\n"
        f"🛑 NO ORDER WAS SENT"
    )

    print(auth_message)
    send_telegram(auth_message)

    # ========================================================
    # EXCHANGE INFO
    # ========================================================

    exchange_info = get_exchange_info()

    if exchange_info is None:

        message = (
            f"🚨 EXCHANGE INFO FAILED {VERSION}\n\n"
            f"❌ Could not read exchangeInfo.\n\n"
            f"🔒 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT"
        )

        print(message)
        send_telegram(message)
        return

    # ========================================================
    # PARSE
    # ========================================================

    markets = parse_usdt_markets(
        exchange_info
    )

    print(
        "PARSED USDT MARKETS:",
        len(markets),
    )

    # ========================================================
    # SUCCESS
    # ========================================================

    if markets:

        sample = markets[:10]

        lines = [
            f"📊 ATI MARKET DISCOVERY {VERSION}",
            "",
            f"🟢 USDT MARKETS: {len(markets)}",
            f"📋 SHOWING: {len(sample)}",
            "",
        ]

        for index, market in enumerate(
            sample,
            start=1,
        ):

            lines.append(
                f"{index}. {market['symbol']}"
            )

            lines.append(
                f"   STEP: {market['stepSize'] or '-'}"
            )

            lines.append(
                f"   MIN QTY: {market['minQty'] or '-'}"
            )

            lines.append(
                f"   MIN NOTIONAL: "
                f"{market['minNotional'] or '-'}"
            )

            lines.append("")

        lines.extend(
            [
                "🔒 REAL BUY: DISABLED",
                "🛑 NO ORDER WAS SENT",
                "",
                f"🕐 {utc_now()}",
            ]
        )

        message = "\n".join(lines)

        print(message)
        send_telegram(message)

        final = (
            f"✅ ATI V40.2.30 SAFE CHECK COMPLETE\n\n"
            f"📡 API: OK\n"
            f"🔐 AUTH: OK\n"
            f"📊 EXCHANGE INFO: OK\n"
            f"🟢 USDT MARKETS: {len(markets)}\n\n"
            f"🔒 REAL ORDERS: DISABLED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"NEXT STEP:\n"
            f"5m MARKET SCANNER"
        )

        print(final)
        send_telegram(final)

        return

    # ========================================================
    # NO MARKETS
    # ========================================================

    no_markets = (
        f"🚨 NO USDT MARKETS {VERSION}\n\n"
        f"❌ PARSER FOUND 0 USDT MARKETS\n\n"
        f"📊 EXCHANGE INFO RESPONSE WAS RECEIVED\n"
        f"📋 RAW STRUCTURE WAS PRINTED IN ACTIONS LOG\n\n"
        f"🔒 REAL BUY LOCKED\n"
        f"🛑 NO ORDER WAS SENT\n\n"
        f"🕐 {utc_now()}"
    )

    print(no_markets)
    send_telegram(no_markets)


if __name__ == "__main__":
    main()
