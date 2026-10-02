import os
import time
import hmac
import hashlib
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.25
# TABDEAL SPOT
# DUAL CREDENTIAL AUTH DIAGNOSTIC
# ============================================================

VERSION = "V40.2.25"

BASE_URL = "https://api1.tabdeal.org"
AUTH_ENDPOINT = "/r/api/v1/account"

REAL_BUY_LOCKED = True

RECV_WINDOW = int(
    os.getenv("RECV_WINDOW", "5000")
)

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()


SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": f"ATI-Crypto-Bot/{VERSION}",
    "Accept": "application/json",
})


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):

    if not TELEGRAM_BOT_TOKEN:
        return False

    if not TELEGRAM_CHAT_ID:
        return False

    try:

        r = SESSION.post(
            "https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )

        return r.ok

    except Exception:
        return False


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():

    try:

        r = SESSION.get(
            f"{BASE_URL}/r/api/v1/time",
            timeout=15,
        )

        if r.status_code != 200:
            return None

        data = r.json()

        if isinstance(data, dict):

            for key in (
                "serverTime",
                "server_time",
                "timestamp",
            ):

                if key in data:
                    return int(data[key])

        if isinstance(data, int):
            return data

        return None

    except Exception:
        return None


# ============================================================
# SIGNATURE
# ============================================================

def make_signed_request(
    api_key,
    api_secret,
):

    # --------------------------------------------------------
    # IMPORTANT:
    # EXACT Postman-style INTEGER TIMESTAMP
    # --------------------------------------------------------

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

    final_query = (
        query_string
        f"&signature={signature}"
    )

    url = (
        f"{BASE_URL}"
        f"{AUTH_ENDPOINT}"
        f"?{final_query}"
    )

    try:

        response = SESSION.get(
            url,
            headers={
                "X-MBX-APIKEY": api_key,
            },
            timeout=20,
        )

        try:
            data = response.json()
        except Exception:
            data = {}

        code = ""
        msg = ""

        if isinstance(data, dict):

            code = data.get(
                "code",
                ""
            )

            msg = data.get(
                "msg",
                ""
            )

        if not msg:
            msg = response.text[:300]

        return {
            "ok": response.status_code == 200,
            "http": response.status_code,
            "code": code,
            "msg": msg,
            "timestamp": timestamp,
        }

    except Exception as e:

        return {
            "ok": False,
            "http": 0,
            "code": "NETWORK",
            "msg": str(e)[:300],
            "timestamp": timestamp,
        }


# ============================================================
# LOAD CREDENTIAL PAIRS
# ============================================================

def get_credential_pairs():

    pairs = []

    tabdeal_key = os.getenv(
        "TABDEAL_API_KEY",
        ""
    ).strip()

    tabdeal_secret = os.getenv(
        "TABDEAL_API_SECRET",
        ""
    ).strip()

    tabdil_key = os.getenv(
        "TABDIL_API_KEY",
        ""
    ).strip()

    tabdil_secret = os.getenv(
        "TABDIL_API_SECRET",
        ""
    ).strip()

    if tabdeal_key and tabdeal_secret:

        pairs.append({
            "name": "TABDEAL_*",
            "key": tabdeal_key,
            "secret": tabdeal_secret,
        })

    if tabdil_key and tabdil_secret:

        # Avoid testing the exact same pair twice.
        if (
            tabdil_key != tabdeal_key
            or tabdil_secret != tabdeal_secret
        ):

            pairs.append({
                "name": "TABDIL_*",
                "key": tabdil_key,
                "secret": tabdil_secret,
            })

    return pairs


# ============================================================
# AUTH DIAGNOSTIC
# ============================================================

def authenticate():

    pairs = get_credential_pairs()

    if not pairs:

        result = {
            "ok": False,
            "name": "NONE",
            "http": 0,
            "code": "MISSING",
            "msg": "NO API CREDENTIAL PAIR FOUND",
            "timestamp": 0,
        }

        return result

    # --------------------------------------------------------
    # SERVER CLOCK CHECK
    # --------------------------------------------------------

    server_time = get_server_time()

    local_time = int(
        time.time() * 1000
    )

    if server_time is not None:

        clock_diff = (
            local_time
            - server_time
        )

    else:

        clock_diff = None

    # --------------------------------------------------------
    # TEST EVERY AVAILABLE CREDENTIAL PAIR
    # --------------------------------------------------------

    failures = []

    for pair in pairs:

        result = make_signed_request(
            pair["key"],
            pair["secret"],
        )

        result["name"] = pair["name"]
        result["server_time"] = server_time
        result["clock_diff"] = clock_diff

        if result["ok"]:

            return result

        failures.append(result)

    # --------------------------------------------------------
    # NONE WORKED
    # --------------------------------------------------------

    last = failures[-1]

    return {
        "ok": False,
        "name": "ALL_PAIRS_FAILED",
        "http": last["http"],
        "code": last["code"],
        "msg": last["msg"],
        "timestamp": last["timestamp"],
        "server_time": server_time,
        "clock_diff": clock_diff,
        "tested": [
            x["name"]
            for x in failures
        ],
    }


# ============================================================
# AUTH SUCCESS MESSAGE
# ============================================================

def send_auth_success(result):

    diff = result.get(
        "clock_diff"
    )

    if diff is None:
        diff_text = "UNKNOWN"
    else:
        diff_text = f"{diff} ms"

    telegram_send(
        f"✅ ATI API AUTH OK {VERSION}\n\n"
        f"🟢 WORKING SECRET PAIR:\n"
        f"{result.get('name')}\n\n"
        f"📡 ENDPOINT:\n"
        f"{AUTH_ENDPOINT}\n"
        f"🔐 HMAC-SHA256\n"
        f"🔢 INTEGER TIMESTAMP\n"
        f"🕐 CLOCK DIFF: {diff_text}\n\n"
        f"🔒 REAL BUY: LOCKED\n"
        f"🛑 NO ORDER SENT\n"
        f"🕐 {utc_now()}"
    )


# ============================================================
# AUTH FAILURE MESSAGE
# ============================================================

def send_auth_failure(result):

    diff = result.get(
        "clock_diff"
    )

    if diff is None:
        diff_text = "UNKNOWN"
    else:
        diff_text = f"{diff} ms"

    tested = result.get(
        "tested",
        []
    )

    tested_text = (
        ", ".join(tested)
        if tested
        else "NONE"
    )

    telegram_send(
        f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
        f"❌ HTTP: {result.get('http')}\n"
        f"❌ CODE: {result.get('code')}\n"
        f"❌ MSG: {result.get('msg')}\n\n"
        f"🔐 METHOD: HMAC-SHA256\n"
        f"🔢 TIMESTAMP: INTEGER\n"
        f"🔐 PARAM ORDER:\n"
        f"timestamp → recvWindow\n"
        f"🔑 HEADER: X-MBX-APIKEY\n"
        f"📡 ENDPOINT:\n"
        f"{AUTH_ENDPOINT}\n\n"
        f"🧪 TESTED PAIRS:\n"
        f"{tested_text}\n\n"
        f"🕐 CLOCK DIFF: {diff_text}\n\n"
        f"🔒 REAL BUY LOCKED\n"
        f"🛑 NO ORDER WAS SENT\n"
        f"🕐 {utc_now()}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    telegram_send(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 AUTH DIAGNOSTIC: STARTING\n"
        f"🔐 HMAC-SHA256\n"
        f"🔢 INTEGER TIMESTAMP\n"
        f"🧪 DUAL SECRET TEST\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🔒 BUY LOCK: ACTIVE\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    result = authenticate()

    if not result["ok"]:

        send_auth_failure(result)

        telegram_send(
            f"🛑 ATI SAFE STOP {VERSION}\n\n"
            f"🚫 PRIVATE API AUTH FAILED\n"
            f"❌ HTTP: {result.get('http')}\n"
            f"❌ CODE: {result.get('code')}\n"
            f"❌ MSG: {result.get('msg')}\n\n"
            f"🔒 REAL BUY DISABLED\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    send_auth_success(result)

    telegram_send(
        f"💓 ATI HEARTBEAT {VERSION}\n\n"
        f"✅ PRIVATE API AUTHENTICATED\n"
        f"🟢 WORKING PAIR: "
        f"{result.get('name')}\n"
        f"🔒 REAL BUY: LOCKED\n"
        f"🛑 NO ORDER SENT\n"
        f"🕐 {utc_now()}"
    )


if __name__ == "__main__":
    main()
