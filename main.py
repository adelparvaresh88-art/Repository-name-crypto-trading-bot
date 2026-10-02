import os
import time
import hmac
import hashlib
from urllib.parse import urlencode
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.26
# TABDEAL SPOT - OFFICIAL SDK SIGNING METHOD
# ============================================================
# IMPORTANT:
# - REAL ORDERS ARE DISABLED
# - NO BUY ORDER WILL BE SENT
# - AUTH TEST ONLY
# - SIGNING MATCHES OFFICIAL TABDEAL PYTHON SDK
# ============================================================

VERSION = "V40.2.26"

BASE_URL = "https://api1.tabdeal.org"

AUTH_ENDPOINT = "/r/api/v1/account"
TIME_ENDPOINT = "/r/api/v1/time"

RECV_WINDOW = int(os.getenv("RECV_WINDOW", "5000"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

REQUEST_TIMEOUT = 20

# HARD SAFETY LOCK
LIVE_TRADING = False


# ============================================================
# UTC TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM CONFIG MISSING")
        print(message)
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
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
            "Telegram error:",
            response.status_code,
            response.text[:500],
        )

    except Exception as exc:
        print(
            "Telegram exception:",
            repr(exc),
        )

    return False


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():
    try:
        response = requests.get(
            BASE_URL + TIME_ENDPOINT,
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
                if data.get(key) is not None:
                    return int(data[key])

        if isinstance(data, int):
            return int(data)

    except Exception as exc:
        print(
            "Server time check failed:",
            repr(exc),
        )

    return None


# ============================================================
# CREDENTIALS
# ============================================================

def get_credential_pairs():
    candidates = [
        (
            "TABDEAL",
            os.getenv("TABDEAL_API_KEY", "").strip(),
            os.getenv("TABDEAL_API_SECRET", "").strip(),
        ),
        (
            "TABDIL",
            os.getenv("TABDIL_API_KEY", "").strip(),
            os.getenv("TABDIL_API_SECRET", "").strip(),
        ),
    ]

    pairs = []
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

        pairs.append(
            {
                "name": name,
                "api_key": api_key,
                "api_secret": api_secret,
            }
        )

    return pairs


# ============================================================
# OFFICIAL TABDEAL SDK STYLE SIGNING
# ============================================================

def make_signed_account_request(
    api_key,
    api_secret,
):
    """
    This follows the official Tabdeal Python SDK pattern:

        timestamp = time.time() * 1000

        data.update({
            "timestamp": timestamp
        })

        data.update({
            "recvWindow": receive_window
        })

        data_query = urlencode(data)

        signature = HMAC-SHA256(
            secret,
            data_query
        )

        data["signature"] = signature

    The GET request then sends the data as query parameters.
    """

    # IMPORTANT:
    # Do NOT convert this to int().
    # Official SDK uses time.time() * 1000.
    timestamp = time.time() * 1000

    data = {
        "timestamp": timestamp,
        "recvWindow": RECV_WINDOW,
    }

    # EXACT SDK-STYLE ENCODING
    data_query = urlencode(data)

    # EXACT SDK-STYLE HMAC
    signature = hmac.new(
        api_secret.encode("utf-8"),
        data_query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Add signature AFTER signing
    data["signature"] = signature

    headers = {
        "X-MBX-APIKEY": api_key,
        "Accept": "application/json",
    }

    # Use requests params exactly like SDK's _get(..., params=data)
    response = requests.get(
        BASE_URL + AUTH_ENDPOINT,
        params=data,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )

    return {
        "response": response,
        "timestamp": timestamp,
        "data_query": data_query,
        "signature": signature,
    }


# ============================================================
# AUTH TEST
# ============================================================

def test_credentials(credential):
    name = credential["name"]
    api_key = credential["api_key"]
    api_secret = credential["api_secret"]

    print("=" * 60)
    print(f"TESTING PAIR: {name}")
    print("=" * 60)

    try:

        result = make_signed_account_request(
            api_key,
            api_secret,
        )

        response = result["response"]

        print(
            f"{name} HTTP:",
            response.status_code,
        )

        print(
            f"{name} RESPONSE:",
            response.text[:1000],
        )

        return {
            "success": response.status_code == 200,
            "name": name,
            "http": response.status_code,
            "text": response.text,
            "timestamp": result["timestamp"],
        }

    except Exception as exc:

        print(
            f"{name} EXCEPTION:",
            repr(exc),
        )

        return {
            "success": False,
            "name": name,
            "http": 0,
            "text": repr(exc),
            "timestamp": time.time() * 1000,
        }


# ============================================================
# ERROR EXTRACTION
# ============================================================

def extract_error(text):
    if not text:
        return "EMPTY RESPONSE"

    try:
        data = requests.models.complexjson.loads(text)

        if isinstance(data, dict):

            code = data.get("code")
            msg = data.get("msg")

            if code is not None or msg is not None:
                return (
                    f"CODE: {code}\n"
                    f"MSG: {msg}"
                )

    except Exception:
        pass

    return text[:500]


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print(f"ATI CRYPTO BOT {VERSION}")
    print("=" * 60)

    startup = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 AUTH TEST: STARTING\n\n"
        f"🔐 HMAC-SHA256\n"
        f"🔢 OFFICIAL SDK TIMESTAMP\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🔒 BUY LOCK: ACTIVE\n\n"
        f"🕐 {utc_now()}"
    )

    print(startup)
    send_telegram(startup)

    # --------------------------------------------------------
    # LOCAL / SERVER TIME CHECK
    # --------------------------------------------------------

    local_timestamp = int(
        time.time() * 1000
    )

    server_timestamp = get_server_time()

    if server_timestamp is not None:

        clock_diff = (
            local_timestamp
            - server_timestamp
        )

        time_message = (
            f"🕐 TABDEAL TIME CHECK\n\n"
            f"LOCAL:\n"
            f"{local_timestamp}\n\n"
            f"SERVER:\n"
            f"{server_timestamp}\n\n"
            f"DIFF:\n"
            f"{clock_diff} ms"
        )

        print(time_message)
        send_telegram(time_message)

    else:

        clock_diff = None

        print(
            "⚠️ TABDEAL SERVER TIME: UNKNOWN"
        )

    # --------------------------------------------------------
    # GET CREDENTIAL PAIRS
    # --------------------------------------------------------

    credentials = get_credential_pairs()

    if not credentials:

        message = (
            f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
            f"❌ NO API CREDENTIALS FOUND\n\n"
            f"Expected:\n"
            f"• TABDEAL_API_KEY + TABDEAL_API_SECRET\n"
            f"or\n"
            f"• TABDIL_API_KEY + TABDIL_API_SECRET\n\n"
            f"🔒 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        print(message)
        send_telegram(message)
        return

    # --------------------------------------------------------
    # TEST CREDENTIALS
    # --------------------------------------------------------

    results = []

    working = None

    for credential in credentials:

        result = test_credentials(
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
            f"📡 ENDPOINT:\n"
            f"{AUTH_ENDPOINT}\n\n"
            f"🔐 SIGN METHOD:\n"
            f"HMAC-SHA256\n\n"
            f"🔢 TIMESTAMP:\n"
            f"OFFICIAL SDK STYLE\n\n"
            f"🧾 HTTP:\n"
            f"{working['http']}\n\n"
            f"🔒 REAL BUY: DISABLED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        print(success_message)
        send_telegram(success_message)

        return

    # --------------------------------------------------------
    # FAILURE
    # --------------------------------------------------------

    lines = [
        f"🚨 ATI API AUTH FAILED {VERSION}",
        "",
        "❌ ALL CREDENTIAL PAIRS FAILED",
        "",
    ]

    for result in results:

        lines.append(
            f"🔑 PAIR: {result['name']}"
        )

        lines.append(
            f"❌ HTTP: {result['http']}"
        )

        lines.append(
            extract_error(result["text"])
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

    else:

        lines.extend(
            [
                "🕐 CLOCK DIFF:",
                "UNKNOWN",
                "",
            ]
        )

    lines.extend(
        [
            "📡 ENDPOINT:",
            AUTH_ENDPOINT,
            "",
            "🔐 METHOD: HMAC-SHA256",
            "🔢 TIMESTAMP: OFFICIAL SDK STYLE",
            "🔒 REAL BUY LOCKED",
            "🛑 NO ORDER WAS SENT",
            "",
            f"🕐 {utc_now()}",
        ]
    )

    failure_message = "\n".join(lines)

    print(failure_message)
    send_telegram(failure_message)

    # --------------------------------------------------------
    # SAFE STOP
    # --------------------------------------------------------

    safe_stop = (
        f"🛑 ATI SAFE STOP {VERSION}\n\n"
        f"🚫 PRIVATE API AUTH FAILED\n"
        f"🔒 REAL BUY DISABLED\n"
        f"🛑 NO ORDER WAS SENT\n\n"
        f"🕐 {utc_now()}"
    )

    print(safe_stop)
    send_telegram(safe_stop)


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    main()
