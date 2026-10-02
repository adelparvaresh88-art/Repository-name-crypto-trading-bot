import os
import time
import hmac
import hashlib
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.28
# TABDEAL REST API - NO PYTHON SDK
# DIRECT HMAC-SHA256 AUTH TEST
# ============================================================
#
# IMPORTANT:
# - NO tabdeal package
# - NO tabdeal.spot import
# - NO SDK dependency
# - REAL ORDERS DISABLED
# - AUTHENTICATION TEST ONLY
# - NO BUY ORDER IS SENT
#
# ============================================================

VERSION = "V40.2.28"

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

        print(
            "TIME HTTP:",
            response.status_code,
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
# HMAC SHA256
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
# AUTHENTICATED ACCOUNT REQUEST
# ============================================================

def test_rest_auth(credential, server_time=None):

    name = credential["name"]
    api_key = credential["api_key"]
    api_secret = credential["api_secret"]

    print("=" * 70)
    print(
        "DIRECT REST AUTH TEST:",
        name,
    )
    print("=" * 70)

    # --------------------------------------------------------
    # Use server timestamp when available.
    # Otherwise local UTC milliseconds.
    # --------------------------------------------------------

    if server_time is not None:
        timestamp = int(server_time)
    else:
        timestamp = int(
            time.time() * 1000
        )

    # --------------------------------------------------------
    # IMPORTANT:
    # Parameter order:
    #
    # timestamp
    # recvWindow
    #
    # --------------------------------------------------------

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

    print(
        "TIMESTAMP:",
        timestamp,
    )

    print(
        "RECV WINDOW:",
        RECV_WINDOW,
    )

    print(
        "SIGN METHOD:",
        "HMAC-SHA256",
    )

    print(
        "PARAM ORDER:",
        "timestamp -> recvWindow",
    )

    print(
        "ENDPOINT:",
        "/r/api/v1/account",
    )

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        print(
            "HTTP:",
            response.status_code,
        )

        print(
            "RESPONSE:",
            response.text[:2000],
        )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        if response.status_code == 200:

            try:
                data = response.json()
            except Exception:
                data = response.text

            return {
                "success": True,
                "name": name,
                "http": response.status_code,
                "code": 0,
                "message": "AUTH SUCCESS",
                "result": data,
            }

        # ----------------------------------------------------
        # ERROR
        # ----------------------------------------------------

        code = "UNKNOWN"
        message = response.text[:1000]

        try:

            data = response.json()

            if isinstance(data, dict):

                if "code" in data:
                    code = data.get("code")

                if "msg" in data:
                    message = data.get("msg")

                elif "message" in data:
                    message = data.get("message")

        except Exception:
            pass

        return {
            "success": False,
            "name": name,
            "http": response.status_code,
            "code": code,
            "message": message,
        }

    except Exception as exc:

        print(
            "REST AUTH ERROR:",
            repr(exc),
        )

        return {
            "success": False,
            "name": name,
            "http": 0,
            "code": "REQUEST_ERROR",
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
        f"📊 AUTH TEST: DIRECT REST API\n\n"
        f"🔐 HMAC-SHA256\n"
        f"🔢 TIMESTAMP + RECVWINDOW\n"
        f"🔧 PYTHON SDK: DISABLED\n"
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
            f"LOCAL:\n"
            f"{local_time}\n\n"
            f"SERVER:\n"
            f"{server_time}\n\n"
            f"DIFF:\n"
            f"{clock_diff} ms"
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

    # ========================================================
    # CREDENTIALS
    # ========================================================

    credentials = get_credentials()

    if not credentials:

        message = (
            f"🚨 ATI AUTH FAILED {VERSION}\n\n"
            f"❌ NO API CREDENTIALS FOUND\n\n"
            f"Expected one of:\n"
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

    # ========================================================
    # AUTH TEST
    # ========================================================

    results = []

    working = None

    for credential in credentials:

        result = test_rest_auth(
            credential,
            server_time,
        )

        results.append(result)

        if result["success"]:

            working = result

            break

    # ========================================================
    # SUCCESS
    # ========================================================

    if working:

        success_message = (
            f"✅ ATI API AUTH SUCCESS {VERSION}\n\n"
            f"🟢 WORKING PAIR:\n"
            f"{working['name']}\n\n"
            f"🔐 METHOD:\n"
            f"DIRECT REST API\n\n"
            f"🔐 SIGN:\n"
            f"HMAC-SHA256\n\n"
            f"🔢 PARAM ORDER:\n"
            f"timestamp → recvWindow\n\n"
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

    # ========================================================
    # FAILURE
    # ========================================================

    lines = [
        f"🚨 ATI API AUTH FAILED {VERSION}",
        "",
        "❌ DIRECT REST AUTH FAILED",
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
            "DIRECT REST API",
            "",
            "🔐 SIGN:",
            "HMAC-SHA256",
            "",
            "🔢 PARAM ORDER:",
            "timestamp -> recvWindow",
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

    # ========================================================
    # SAFE STOP
    # ========================================================

    safe_stop = (
        f"🛑 ATI SAFE STOP {VERSION}\n\n"
        f"🚫 API AUTH FAILED\n"
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
