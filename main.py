import os
import time
import hmac
import hashlib
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.25
# TABDEAL SPOT - AUTH DIAGNOSTIC
# ============================================================
# IMPORTANT:
# - REAL ORDERS ARE LOCKED
# - NO BUY ORDER IS SENT
# - Tests TABDEAL and TABDIL credential pairs
# - Uses HMAC-SHA256
# - Uses integer millisecond timestamp
# ============================================================

VERSION = "V40.2.25"

BASE_URL = "https://api1.tabdeal.org"

AUTH_ENDPOINT = "/r/api/v1/account"
TIME_ENDPOINT = "/r/api/v1/time"

RECV_WINDOW = int(os.getenv("RECV_WINDOW", "5000"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

LIVE_TRADING = False

REQUEST_TIMEOUT = 20


# ============================================================
# TIME
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
            response.text,
        )

    except Exception as e:
        print("Telegram exception:", repr(e))

    return False


# ============================================================
# HTTP TIME
# ============================================================

def get_server_time():
    """
    Try to read Tabdeal server time.

    This is diagnostic only.
    Failure here does NOT stop authentication testing.
    """

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
                value = data.get(key)

                if value is not None:
                    return int(value)

        if isinstance(data, int):
            return int(data)

    except Exception:
        pass

    return None


# ============================================================
# CREDENTIAL PAIRS
# ============================================================

def get_credential_pairs():
    pairs = []

    credentials = [
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

    seen = set()

    for name, api_key, api_secret in credentials:

        if not api_key or not api_secret:
            continue

        pair_id = (api_key, api_secret)

        if pair_id in seen:
            continue

        seen.add(pair_id)

        pairs.append(
            {
                "name": name,
                "api_key": api_key,
                "api_secret": api_secret,
            }
        )

    return pairs


# ============================================================
# SIGNED ACCOUNT REQUEST
# ============================================================

def make_signed_request(api_key, api_secret):
    """
    Tabdeal Spot private account request.

    Signature:
        HMAC-SHA256(secret, query_string)

    Query order:
        timestamp
        recvWindow
        signature
    """

    timestamp = int(
        time.time() * 1000
    )

    query_string = (
        f"timestamp={timestamp}"
        f"&recvWindow={RECV_WINDOW}"
    )

    signature = hmac.new(
        api_secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # IMPORTANT:
    # The '+' below fixes the previous SyntaxError.
    final_query = (
        query_string
        + f"&signature={signature}"
    )

    url = (
        BASE_URL
        + AUTH_ENDPOINT
        + "?"
        + final_query
    )

    headers = {
        "X-MBX-APIKEY": api_key,
        "Accept": "application/json",
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )

    return {
        "response": response,
        "timestamp": timestamp,
        "signature": signature,
        "query_string": query_string,
    }


# ============================================================
# AUTH TEST
# ============================================================

def test_credentials(credential):
    name = credential["name"]
    api_key = credential["api_key"]
    api_secret = credential["api_secret"]

    print(
        f"Testing credential pair: {name}"
    )

    try:

        result = make_signed_request(
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

        if response.status_code == 200:

            return {
                "success": True,
                "name": name,
                "http": response.status_code,
                "text": response.text,
                "timestamp": result["timestamp"],
            }

        return {
            "success": False,
            "name": name,
            "http": response.status_code,
            "text": response.text,
            "timestamp": result["timestamp"],
        }

    except Exception as e:

        print(
            f"{name} EXCEPTION:",
            repr(e),
        )

        return {
            "success": False,
            "name": name,
            "http": 0,
            "text": repr(e),
            "timestamp": int(time.time() * 1000),
        }


# ============================================================
# PARSE ERROR
# ============================================================

def extract_error(text):
    if not text:
        return "UNKNOWN"

    try:
        data = requests.models.complexjson.loads(text)

        if isinstance(data, dict):
            code = data.get("code")
            msg = data.get("msg")

            if code is not None or msg:
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

    startup_message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 AUTH DIAGNOSTIC: STARTING\n\n"
        f"🔐 HMAC-SHA256\n"
        f"🔢 INTEGER TIMESTAMP\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🔒 BUY LOCK: ACTIVE\n\n"
        f"🕐 {utc_now()}"
    )

    print(startup_message)
    send_telegram(startup_message)

    # --------------------------------------------------------
    # Server time diagnostic
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
            "⚠️ SERVER TIME: UNKNOWN"
        )

    # --------------------------------------------------------
    # Credentials
    # --------------------------------------------------------

    credentials = get_credential_pairs()

    if not credentials:

        message = (
            f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
            f"❌ NO API CREDENTIAL PAIR FOUND\n\n"
            f"Expected one of:\n"
            f"• TABDEAL_API_KEY + TABDEAL_API_SECRET\n"
            f"• TABDIL_API_KEY + TABDIL_API_SECRET\n\n"
            f"🔒 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n\n"
            f"🕐 {utc_now()}"
        )

        print(message)
        send_telegram(message)

        return

    # --------------------------------------------------------
    # Test every credential pair
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
            f"🟢 WORKING SECRET PAIR:\n"
            f"{working['name']}\n\n"
            f"📡 ENDPOINT:\n"
            f"{AUTH_ENDPOINT}\n\n"
            f"🔐 METHOD: HMAC-SHA256\n"
            f"🔢 TIMESTAMP: INTEGER\n"
            f"🧾 HTTP: {working['http']}\n\n"
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
            extract_error(
                result["text"]
            )
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
            f"📡 ENDPOINT:",
            AUTH_ENDPOINT,
            "",
            "🔐 METHOD: HMAC-SHA256",
            "🔢 TIMESTAMP: INTEGER",
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
