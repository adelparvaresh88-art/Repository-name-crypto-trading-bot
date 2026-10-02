import os
import time
from datetime import datetime, timezone

import requests

from tabdeal.spot import Spot
from tabdeal.exceptions import ClientException, ServerException


# ============================================================
# ATI CRYPTO BOT V40.2.27
# TABDEAL OFFICIAL PYTHON SDK AUTH TEST
# ============================================================
# IMPORTANT:
# - REAL ORDERS DISABLED
# - NO BUY ORDER IS SENT
# - AUTHENTICATION TEST ONLY
# - Uses official tabdeal-python Spot.account()
# ============================================================

VERSION = "V40.2.27"

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

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            return True

        print(
            "Telegram HTTP:",
            response.status_code,
        )

        print(
            response.text[:500]
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
                    return int(value)

        if isinstance(data, int):
            return int(data)

    except Exception as exc:

        print(
            "SERVER TIME ERROR:",
            repr(exc),
        )

    return None


# ============================================================
# CREDENTIAL PAIRS
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
# OFFICIAL SDK AUTH TEST
# ============================================================

def test_official_sdk(credential):

    name = credential["name"]
    api_key = credential["api_key"]
    api_secret = credential["api_secret"]

    print("=" * 60)
    print(
        "OFFICIAL SDK TEST:",
        name,
    )
    print("=" * 60)

    try:

        # ----------------------------------------------------
        # IMPORTANT:
        # This is the official Tabdeal Spot client.
        # ----------------------------------------------------

        client = Spot(
            api_key=api_key,
            api_secret=api_secret,
            base_url=BASE_URL,
            version="v1",
            timeout=REQUEST_TIMEOUT,
            receive_window=RECV_WINDOW,
        )

        # ----------------------------------------------------
        # IMPORTANT:
        # account() is the official SDK method.
        # NO order method is called.
        # ----------------------------------------------------

        result = client.account()

        print(
            "OFFICIAL SDK ACCOUNT SUCCESS"
        )

        print(
            "RESPONSE:",
            str(result)[:1000],
        )

        return {
            "success": True,
            "name": name,
            "http": 200,
            "result": result,
        }

    except ClientException as exc:

        print(
            "OFFICIAL SDK CLIENT ERROR"
        )

        print(
            "STATUS:",
            getattr(
                exc,
                "status",
                "UNKNOWN",
            ),
        )

        print(
            "CODE:",
            getattr(
                exc,
                "code",
                "UNKNOWN",
            ),
        )

        print(
            "MESSAGE:",
            getattr(
                exc,
                "message",
                str(exc),
            ),
        )

        return {
            "success": False,
            "name": name,
            "http": getattr(
                exc,
                "status",
                0,
            ),
            "code": getattr(
                exc,
                "code",
                "UNKNOWN",
            ),
            "message": getattr(
                exc,
                "message",
                str(exc),
            ),
        }

    except ServerException as exc:

        print(
            "OFFICIAL SDK SERVER ERROR:",
            repr(exc),
        )

        return {
            "success": False,
            "name": name,
            "http": getattr(
                exc,
                "status",
                500,
            ),
            "code": "SERVER_ERROR",
            "message": str(exc),
        }

    except Exception as exc:

        print(
            "OFFICIAL SDK UNKNOWN ERROR:",
            repr(exc),
        )

        return {
            "success": False,
            "name": name,
            "http": 0,
            "code": "UNKNOWN",
            "message": repr(exc),
        }


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
        f"📊 AUTH TEST: OFFICIAL SDK\n\n"
        f"🔐 TABDEAL PYTHON SDK\n"
        f"🔐 Spot.account()\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🔒 BUY LOCK: ACTIVE\n\n"
        f"🕐 {utc_now()}"
    )

    print(startup)

    send_telegram(startup)

    # --------------------------------------------------------
    # TIME CHECK
    # --------------------------------------------------------

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
            f"LOCAL:\n"
            f"{local_time}\n\n"
            f"SERVER:\n"
            f"{server_time}\n\n"
            f"DIFF:\n"
            f"{clock_diff} ms"
        )

        print(time_message)

        send_telegram(
            time_message
        )

    else:

        clock_diff = None

        time_message = (
            f"⚠️ TABDEAL TIME CHECK\n\n"
            f"SERVER TIME: UNKNOWN\n\n"
            f"🕐 {utc_now()}"
        )

        print(time_message)

        send_telegram(
            time_message
        )

    # --------------------------------------------------------
    # CREDENTIALS
    # --------------------------------------------------------

    credentials = get_credentials()

    if not credentials:

        message = (
            f"🚨 ATI AUTH FAILED {VERSION}\n\n"
            f"❌ NO API CREDENTIALS FOUND\n\n"
            f"Expected:\n"
            f"• TABDEAL_API_KEY\n"
            f"• TABDEAL_API_SECRET\n\n"
            f"or:\n"
            f"• TABDIL_API_KEY\n"
            f"• TABDIL_API_SECRET\n\n"
            f"🔒 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        print(message)

        send_telegram(message)

        return

    # --------------------------------------------------------
    # TEST ALL AVAILABLE PAIRS
    # --------------------------------------------------------

    results = []

    working = None

    for credential in credentials:

        result = test_official_sdk(
            credential
        )

        results.append(result)

        if result["success"]:

            working = result

            break

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    if working:

        success_message = (
            f"✅ ATI API AUTH SUCCESS {VERSION}\n\n"
            f"🟢 WORKING PAIR:\n"
            f"{working['name']}\n\n"
            f"🔐 METHOD:\n"
            f"OFFICIAL TABDEAL PYTHON SDK\n\n"
            f"🔐 CALL:\n"
            f"Spot.account()\n\n"
            f"📡 ENDPOINT:\n"
            f"/r/api/v1/account\n\n"
            f"🔒 REAL BUY: DISABLED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        print(success_message)

        send_telegram(
            success_message
        )

        return

    # --------------------------------------------------------
    # FAILURE
    # --------------------------------------------------------

    lines = [
        f"🚨 ATI API AUTH FAILED {VERSION}",
        "",
        "❌ OFFICIAL SDK AUTH FAILED",
        "",
    ]

    for result in results:

        lines.append(
            f"🔑 PAIR: {result['name']}"
        )

        lines.append(
            f"❌ HTTP: {result.get('http', 'UNKNOWN')}"
        )

        lines.append(
            f"❌ CODE: {result.get('code', 'UNKNOWN')}"
        )

        lines.append(
            f"❌ MSG: {result.get('message', 'UNKNOWN')}"
        )

        lines.append("")

    if clock_diff is not None:

        lines.extend(
            [
                "🕐 CLOCK DIFF:",
                f"{clock_diff} ms",
                "",
            ]
        )

    lines.extend(
        [
            "🔐 AUTH METHOD:",
            "OFFICIAL TABDEAL PYTHON SDK",
            "",
            "🔐 CALL:",
            "Spot.account()",
            "",
            "📡 ENDPOINT:",
            "/r/api/v1/account",
            "",
            "🔒 REAL BUY LOCKED",
            "🛑 NO ORDER WAS SENT",
            "",
            f"🕐 {utc_now()}",
        ]
    )

    failure_message = "\n".join(
        lines
    )

    print(failure_message)

    send_telegram(
        failure_message
    )

    # --------------------------------------------------------
    # SAFE STOP
    # --------------------------------------------------------

    safe_stop = (
        f"🛑 ATI SAFE STOP {VERSION}\n\n"
        f"🚫 OFFICIAL SDK AUTH FAILED\n"
        f"🔒 REAL BUY DISABLED\n"
        f"🛑 NO ORDER WAS SENT\n\n"
        f"🕐 {utc_now()}"
    )

    print(safe_stop)

    send_telegram(
        safe_stop
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    main()
