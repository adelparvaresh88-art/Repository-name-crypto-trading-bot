import os
import time
import hmac
import hashlib
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.29
# TABDEAL DIRECT REST API
# AUTH + EXCHANGE INFO + USDT MARKET DISCOVERY
# ============================================================

VERSION = "V40.2.29"

BASE_URL = "https://api1.tabdeal.org"

RECV_WINDOW = int(
    os.getenv("RECV_WINDOW", "5000")
)

REQUEST_TIMEOUT = int(
    os.getenv("REQUEST_TIMEOUT", "20")
)

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
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
# SIGNATURE
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
# AUTH ACCOUNT TEST
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

        print(
            "AUTH HTTP:",
            response.status_code,
        )

        if response.status_code == 200:

            try:
                data = response.json()
            except Exception:
                data = {}

            return {
                "success": True,
                "data": data,
                "timestamp": timestamp,
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

        if response.status_code != 200:

            print(
                "EXCHANGE INFO ERROR:",
                response.text[:1000],
            )

            return None

        return response.json()

    except Exception as exc:

        print(
            "EXCHANGE INFO ERROR:",
            repr(exc),
        )

        return None


# ============================================================
# NUMBER FORMAT
# ============================================================

def clean_value(value):

    if value is None:
        return "-"

    return str(value)


# ============================================================
# EXTRACT FILTER
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

        if (
            item.get("filterType")
            == filter_type
        ):
            return item

    return {}


# ============================================================
# MARKET PARSER
# ============================================================

def parse_usdt_markets(data):

    symbols = []

    if not isinstance(data, dict):
        return symbols

    raw_symbols = data.get(
        "symbols",
        [],
    )

    if not isinstance(
        raw_symbols,
        list,
    ):
        return symbols

    for item in raw_symbols:

        if not isinstance(
            item,
            dict,
        ):
            continue

        symbol = str(
            item.get(
                "symbol",
                "",
            )
        ).upper()

        if not symbol.endswith(
            "USDT"
        ):
            continue

        status = str(
            item.get(
                "status",
                "",
            )
        ).upper()

        # Keep active markets.
        if status and status not in (
            "TRADING",
            "ENABLED",
            "ACTIVE",
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

        step_size = (
            market_lot.get(
                "stepSize"
            )
            or lot.get(
                "stepSize"
            )
        )

        min_qty = (
            market_lot.get(
                "minQty"
            )
            or lot.get(
                "minQty"
            )
        )

        min_value = (
            min_notional.get(
                "minNotional"
            )
            or notional.get(
                "minNotional"
            )
        )

        symbols.append(
            {
                "symbol": symbol,
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
                "minNotional": min_value,
            }
        )

    return symbols


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
        f"📊 AUTH + MARKET DISCOVERY\n\n"
        f"🔐 DIRECT REST API\n"
        f"🔐 HMAC-SHA256\n"
        f"🔧 PYTHON SDK: DISABLED\n"
        f"📊 EXCHANGE INFO: ENABLED\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🛑 BUY LOCK: ACTIVE\n\n"
        f"🕐 {utc_now()}"
    )

    print(startup)
    send_telegram(startup)

    # ========================================================
    # SERVER TIME
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
    # CREDENTIALS
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

    # ========================================================
    # AUTH
    # ========================================================

    working = None

    for credential in credentials:

        print(
            "AUTH TEST:",
            credential["name"],
        )

        result = test_auth(
            credential,
            server_time,
        )

        if result["success"]:

            working = credential

            print(
                "AUTH SUCCESS:",
                credential["name"],
            )

            break

        print(
            "AUTH FAILED:",
            credential["name"],
            result.get("http"),
            result.get("data"),
        )

    if working is None:

        message = (
            f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
            f"❌ DIRECT REST AUTH FAILED\n\n"
            f"🔒 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        print(message)
        send_telegram(message)
        return

    # ========================================================
    # AUTH SUCCESS
    # ========================================================

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

    print(
        "=" * 70
    )

    print(
        "EXCHANGE INFO: STARTING"
    )

    exchange_info = get_exchange_info()

    if exchange_info is None:

        message = (
            f"🚨 EXCHANGE INFO FAILED {VERSION}\n\n"
            f"❌ Could not read market information.\n\n"
            f"🔒 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        print(message)
        send_telegram(message)
        return

    # ========================================================
    # PARSE USDT MARKETS
    # ========================================================

    markets = parse_usdt_markets(
        exchange_info
    )

    print(
        "USDT MARKETS:",
        len(markets),
    )

    if not markets:

        message = (
            f"🚨 NO USDT MARKETS {VERSION}\n\n"
            f"❌ exchangeInfo returned no active USDT markets.\n\n"
            f"🔒 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT"
        )

        print(message)
        send_telegram(message)
        return

    # ========================================================
    # SHOW MARKET SAMPLE
    # ========================================================

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
            f"   STEP: {clean_value(market['stepSize'])}"
        )

        lines.append(
            f"   MIN QTY: {clean_value(market['minQty'])}"
        )

        lines.append(
            f"   MIN NOTIONAL: "
            f"{clean_value(market['minNotional'])}"
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

    market_message = "\n".join(
        lines
    )

    print(market_message)
    send_telegram(market_message)

    # ========================================================
    # FINAL SAFE STOP
    # ========================================================

    final_message = (
        f"✅ ATI V40.2.29 SAFE CHECK COMPLETE\n\n"
        f"📡 API: OK\n"
        f"🔐 AUTH: OK\n"
        f"📊 EXCHANGE INFO: OK\n"
        f"🟢 USDT MARKETS: {len(markets)}\n\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🛑 NO ORDER WAS SENT\n\n"
        f"NEXT STEP:\n"
        f"5m MARKET SCANNER"
    )

    print(final_message)
    send_telegram(final_message)


if __name__ == "__main__":
    main()
