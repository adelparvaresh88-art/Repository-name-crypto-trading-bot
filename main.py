import os
import time
import hmac
import hashlib
import requests
from datetime import datetime, timezone

# =========================================================
# ATI FUTURES V7.5
# DIAGNOSTIC VERSION
# =========================================================

API_BASE = "https://api1.tabdeal.org"

PUBLIC_BASE = API_BASE + "/r/fapi/v1/"
PRIVATE_BASE = API_BASE + "/r/fapi/v3/"

TIMEOUT = 15
INTERVAL = "5m"
KLINE_LIMIT = 100

# ---------------------------------------------------------
# ENV
# ---------------------------------------------------------

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

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

LIVE_TRADING = False

# =========================================================
# SESSION
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-FUTURES-V7.5-DIAGNOSTIC",
    "Accept": "application/json",
    "Connection": "keep-alive",
})


# =========================================================
# TELEGRAM
# =========================================================

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram secrets not configured")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )

        if r.ok:
            return True

        print("Telegram HTTP:", r.status_code)
        print(r.text[:1000])
        return False

    except Exception as e:
        print("Telegram error:", repr(e))
        return False


# =========================================================
# TIME
# =========================================================

def utc_now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# =========================================================
# PUBLIC REQUEST
# =========================================================

def public_request(path, params=None):

    url = PUBLIC_BASE + path

    print()
    print("🌐 PUBLIC REQUEST")
    print("URL:", url)
    print("PARAMS:", params)

    started = time.time()

    try:

        r = session.get(
            url,
            params=params or {},
            timeout=TIMEOUT,
        )

        elapsed = time.time() - started

        print("HTTP STATUS:", r.status_code)
        print("TIME:", round(elapsed, 3), "sec")
        print("CONTENT-TYPE:", r.headers.get("content-type"))

        body = r.text[:3000]

        print("RESPONSE:")
        print(body)

        if not r.ok:
            raise RuntimeError(
                f"HTTP {r.status_code}: {body}"
            )

        try:
            data = r.json()
        except Exception:
            raise RuntimeError(
                "JSON ERROR: response is not valid JSON"
            )

        return data

    except requests.exceptions.ConnectTimeout as e:

        print("❌ CONNECT TIMEOUT")
        print(repr(e))
        raise

    except requests.exceptions.ReadTimeout as e:

        print("❌ READ TIMEOUT")
        print(repr(e))
        raise

    except requests.exceptions.ConnectionError as e:

        print("❌ CONNECTION ERROR")
        print(repr(e))
        raise

    except Exception as e:

        print("❌ PUBLIC ERROR")
        print(repr(e))
        raise


# =========================================================
# SIGNATURE
# =========================================================

def signed_request(method, path, params=None):

    params = dict(params or {})

    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000

    query = "&".join(
        f"{k}={params[k]}"
        for k in sorted(params)
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()

    params["signature"] = signature

    url = PRIVATE_BASE + path

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "User-Agent": "ATI-FUTURES-V7.5-DIAGNOSTIC",
        "Accept": "application/json",
    }

    print()
    print("🔐 PRIVATE REQUEST")
    print("URL:", url)
    print("METHOD:", method)
    print("PARAMS:", {
        k: ("***" if k == "signature" else v)
        for k, v in params.items()
    })

    started = time.time()

    try:

        if method.upper() == "GET":

            r = session.get(
                url,
                params=params,
                headers=headers,
                timeout=TIMEOUT,
            )

        else:

            r = session.post(
                url,
                params=params,
                headers=headers,
                timeout=TIMEOUT,
            )

        elapsed = time.time() - started

        print("HTTP STATUS:", r.status_code)
        print("TIME:", round(elapsed, 3), "sec")
        print("CONTENT-TYPE:", r.headers.get("content-type"))

        print("RESPONSE:")
        print(r.text[:3000])

        if not r.ok:
            raise RuntimeError(
                f"HTTP {r.status_code}: {r.text[:3000]}"
            )

        return r.json()

    except requests.exceptions.ConnectTimeout as e:

        print("❌ PRIVATE CONNECT TIMEOUT")
        print(repr(e))
        raise

    except requests.exceptions.ReadTimeout as e:

        print("❌ PRIVATE READ TIMEOUT")
        print(repr(e))
        raise

    except requests.exceptions.ConnectionError as e:

        print("❌ PRIVATE CONNECTION ERROR")
        print(repr(e))
        raise

    except Exception as e:

        print("❌ PRIVATE ERROR")
        print(repr(e))
        raise


# =========================================================
# EXCHANGE INFO
# =========================================================

def get_exchange_info():

    print()
    print("=" * 70)
    print("1️⃣ EXCHANGE INFO TEST")
    print("=" * 70)

    data = public_request("exchangeInfo")

    if not isinstance(data, dict):
        raise RuntimeError(
            "exchangeInfo returned unexpected format"
        )

    symbols = data.get("symbols", [])

    print()
    print("📊 SYMBOL COUNT:", len(symbols))

    if not symbols:
        raise RuntimeError(
            "exchangeInfo returned ZERO symbols"
        )

    active = []

    for s in symbols:

        symbol = s.get("symbol", "")
        status = s.get("status", "")

        if symbol and status:
            active.append(
                (symbol, status)
            )

    print("📈 FIRST 20 SYMBOLS:")

    for symbol, status in active[:20]:
        print(
            f"   {symbol:<20} {status}"
        )

    return data


# =========================================================
# FIND TEST SYMBOL
# =========================================================

def choose_test_symbol(exchange_info):

    symbols = exchange_info.get("symbols", [])

    preferred = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "DOGEUSDT",
    ]

    available = {
        s.get("symbol"): s
        for s in symbols
        if s.get("symbol")
    }

    for symbol in preferred:

        if symbol in available:

            print()
            print("🎯 TEST SYMBOL:", symbol)

            return symbol

    for s in symbols:

        symbol = s.get("symbol", "")

        if symbol.endswith("USDT"):

            print()
            print("🎯 TEST SYMBOL:", symbol)

            return symbol

    raise RuntimeError(
        "No USDT Futures symbol found"
    )


# =========================================================
# KLINE TEST
# =========================================================

def test_kline(symbol):

    print()
    print("=" * 70)
    print("2️⃣ FUTURES KLINE TEST")
    print("=" * 70)

    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "limit": KLINE_LIMIT,
    }

    try:

        data = public_request(
            "klines",
            params,
        )

        print()
        print("✅ KLINE REQUEST SUCCESS")

        if isinstance(data, list):

            print("📈 CANDLE COUNT:", len(data))

            if data:

                print()
                print("🕯️ FIRST CANDLE:")
                print(data[0])

                print()
                print("🕯️ LAST CANDLE:")
                print(data[-1])

            return True

        print()
        print("⚠️ KLINE RESPONSE IS NOT LIST")

        return False

    except Exception as e:

        print()
        print("❌ KLINE TEST FAILED")
        print("EXACT ERROR:")
        print(repr(e))

        return False


# =========================================================
# RAW KLINE ALTERNATIVE DIAGNOSTIC
# =========================================================

def raw_endpoint_test(symbol):

    print()
    print("=" * 70)
    print("3️⃣ RAW FUTURES ENDPOINT DIAGNOSTIC")
    print("=" * 70)

    candidates = [

        (
            "/r/fapi/v1/klines",
            {
                "symbol": symbol,
                "interval": "5m",
                "limit": 10,
            },
        ),

        (
            "/fapi/v1/klines",
            {
                "symbol": symbol,
                "interval": "5m",
                "limit": 10,
            },
        ),

    ]

    for path, params in candidates:

        print()
        print("-" * 70)
        print("TEST URL:")
        print(API_BASE + path)
        print("PARAMS:", params)

        try:

            r = session.get(
                API_BASE + path,
                params=params,
                timeout=TIMEOUT,
            )

            print("HTTP:", r.status_code)
            print("CONTENT-TYPE:",
                  r.headers.get("content-type"))

            print("BODY:")
            print(r.text[:2000])

        except Exception as e:

            print("ERROR:")
            print(repr(e))


# =========================================================
# BALANCE TEST
# =========================================================

def test_balance():

    print()
    print("=" * 70)
    print("4️⃣ FUTURES BALANCE TEST")
    print("=" * 70)

    if not API_KEY or not API_SECRET:

        print("❌ API KEY / SECRET NOT FOUND")

        return False

    print("🔑 API KEY: PRESENT")
    print("🔐 API SECRET: PRESENT")

    try:

        data = signed_request(
            "GET",
            "balance",
        )

        print()

        if isinstance(data, list):

            print("💰 BALANCE ASSETS:")

            for item in data:

                asset = item.get("asset", "")
                balance = item.get("balance", "")
                available = item.get(
                    "availableBalance",
                    "",
                )

                if asset in [
                    "USDT",
                    "USDC",
                    "BUSD",
                ]:

                    print(
                        f"{asset}: "
                        f"balance={balance} "
                        f"available={available}"
                    )

            return True

        print("⚠️ Unexpected balance format")

        return False

    except Exception as e:

        print()
        print("❌ BALANCE TEST FAILED")
        print(repr(e))

        return False


# =========================================================
# SERVER TIME TEST
# =========================================================

def test_server_time():

    print()
    print("=" * 70)
    print("5️⃣ FUTURES SERVER TIME TEST")
    print("=" * 70)

    try:

        data = public_request(
            "time"
        )

        print()
        print("🕐 SERVER RESPONSE:")
        print(data)

        if isinstance(data, dict):

            server_time = data.get(
                "serverTime"
            )

            if server_time:

                local_ms = int(
                    time.time() * 1000
                )

                diff = (
                    server_time -
                    local_ms
                )

                print()
                print(
                    "⏱️ SERVER-LOCAL DIFF:",
                    diff,
                    "ms"
                )

        return True

    except Exception as e:

        print()
        print("❌ SERVER TIME FAILED")
        print(repr(e))

        return False


# =========================================================
# TELEGRAM REPORT
# =========================================================

def send_report(
    symbol,
    kline_ok,
    balance_ok,
    server_ok,
):

    status = (
        "✅"
        if kline_ok
        else "❌"
    )

    balance_status = (
        "✅"
        if balance_ok
        else "❌"
    )

    server_status = (
        "✅"
        if server_ok
        else "❌"
    )

    message = f"""
🧪 ATI FUTURES V7.5 DIAGNOSTIC

📡 TABDEAL FUTURES
⏱️ TIMEFRAME: 5m

🎯 TEST SYMBOL:
{symbol}

{status} KLINE TEST
{balance_status} BALANCE TEST
{server_status} SERVER TIME

🔒 REAL TRADING: OFF
🚫 NO ORDERS WILL BE PLACED

🕐 {utc_now()}
"""

    telegram(message)


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("=" * 70)
    print("💓 ATI FUTURES V7.5")
    print("🔎 FULL CONNECTION DIAGNOSTIC")
    print("=" * 70)

    print()
    print("📡 API:", API_BASE)
    print("📊 PUBLIC:", PUBLIC_BASE)
    print("🔐 PRIVATE:", PRIVATE_BASE)
    print("⏱️ TIMEFRAME:", INTERVAL)
    print("🔒 REAL TRADING:", LIVE_TRADING)
    print("🕐", utc_now())

    telegram(
        f"""
💓 ATI FUTURES V7.5 START

🔎 FULL API DIAGNOSTIC
📡 TABDEAL FUTURES
⏱️ 5m
🔒 REAL TRADING: OFF
🚫 NO ORDERS

🕐 {utc_now()}
"""
    )

    # -----------------------------------------------------
    # SERVER TIME
    # -----------------------------------------------------

    server_ok = test_server_time()

    # -----------------------------------------------------
    # EXCHANGE INFO
    # -----------------------------------------------------

    try:

        exchange_info = get_exchange_info()

    except Exception as e:

        print()
        print("💥 EXCHANGE INFO FAILED")
        print(repr(e))

        telegram(
            f"""
❌ ATI FUTURES V7.5

EXCHANGE INFO FAILED

{repr(e)}

🕐 {utc_now()}
"""
        )

        return

    # -----------------------------------------------------
    # SYMBOL
    # -----------------------------------------------------

    try:

        symbol = choose_test_symbol(
            exchange_info
        )

    except Exception as e:

        print()
        print("💥 SYMBOL SELECTION FAILED")
        print(repr(e))

        return

    # -----------------------------------------------------
    # KLINE
    # -----------------------------------------------------

    kline_ok = test_kline(
        symbol
    )

    # -----------------------------------------------------
    # RAW ENDPOINT TEST
    # -----------------------------------------------------

    if not kline_ok:

        raw_endpoint_test(
            symbol
        )

    # -----------------------------------------------------
    # BALANCE
    # -----------------------------------------------------

    balance_ok = test_balance()

    # -----------------------------------------------------
    # TELEGRAM REPORT
    # -----------------------------------------------------

    send_report(
        symbol,
        kline_ok,
        balance_ok,
        server_ok,
    )

    # -----------------------------------------------------
    # FINAL
    # -----------------------------------------------------

    print()
    print("=" * 70)
    print("🏁 V7.5 DIAGNOSTIC FINISHED")
    print("=" * 70)

    print()
    print("🎯 SYMBOL:", symbol)
    print("📈 KLINE:", "OK" if kline_ok else "FAILED")
    print("💰 BALANCE:", "OK" if balance_ok else "FAILED")
    print("🕐 SERVER TIME:", "OK" if server_ok else "FAILED")

    if kline_ok:

        print()
        print("🎉 KLINE ENDPOINT IS WORKING")
        print("➡️ Next version can use the scanner.")

    else:

        print()
        print("🚨 KLINE ENDPOINT IS NOT WORKING")
        print("➡️ EXACT HTTP RESPONSE ABOVE MUST BE USED")
        print("➡️ DO NOT ENABLE REAL TRADING YET.")

    print()
    print("🕐", utc_now())


if __name__ == "__main__":
    main()
