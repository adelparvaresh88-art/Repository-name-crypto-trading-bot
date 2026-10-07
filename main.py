import os
import time
import hmac
import hashlib
from decimal import Decimal
from urllib.parse import urlencode

import requests


# =========================================================
# ATI FUTURES
# MULTI COIN
# AUTH + MARKET DISCOVERY
# =========================================================

API_BASE = "https://api1.tabdeal.org"

# Public Futures
READ_BASE = API_BASE + "/r/fapi/"

# Private Futures
WRITE_BASE = API_BASE + "/fapi/"

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

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# =========================================================
# SETTINGS
# =========================================================

LEVERAGE = int(
    os.getenv(
        "FUTURES_LEVERAGE",
        "3"
    )
)

ORDER_USDT = Decimal(
    os.getenv(
        "ORDER_USDT",
        "2"
    )
)

MAX_SYMBOLS = int(
    os.getenv(
        "MAX_FUTURES_SYMBOLS",
        "75"
    )
)

RECV_WINDOW = 5000
TIMEOUT = 20

# فعلاً OFF
# بعد از AUTH SUCCESS روشن می‌کنیم.
REAL_TRADING = False


session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-FUTURES/2.0",
    "Accept": "application/json",
})


# =========================================================
# TELEGRAM
# =========================================================

def telegram(message):

    print("\n" + message)

    if not TELEGRAM_TOKEN:
        return

    if not TELEGRAM_CHAT_ID:
        return

    try:

        url = (
            "https://api.telegram.org/bot"
            + TELEGRAM_TOKEN
            + "/sendMessage"
        )

        session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )

    except Exception as e:

        print(
            "Telegram error:",
            e
        )


# =========================================================
# JSON
# =========================================================

def read_json(response):

    try:

        return response.json()

    except Exception:

        raise RuntimeError(
            "HTTP "
            + str(response.status_code)
            + ":\n"
            + response.text[:1500]
        )


# =========================================================
# PUBLIC REQUEST
# =========================================================

def public_get(
    endpoint,
    params=None
):

    url = READ_BASE + endpoint

    response = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT,
    )

    if response.status_code >= 400:

        raise RuntimeError(
            "HTTP "
            + str(response.status_code)
            + ":\n"
            + response.text[:1500]
        )

    return read_json(response)


# =========================================================
# SIGNATURE
# =========================================================

def make_signature(data):

    query = urlencode(data)

    return hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# =========================================================
# PRIVATE GET
# =========================================================

def private_get(
    endpoint,
    version="v1",
    params=None
):

    if not API_KEY:

        raise RuntimeError(
            "TABDIL_API_KEY not found"
        )

    if not API_SECRET:

        raise RuntimeError(
            "TABDIL_API_SECRET not found"
        )

    data = dict(
        params or {}
    )

    # timestamp integer
    data["timestamp"] = int(
        time.time() * 1000
    )

    data["recvWindow"] = RECV_WINDOW

    data["signature"] = make_signature(
        data
    )

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = (
        API_BASE
        + "/r/fapi/"
        + version
        + "/"
        + endpoint
    )

    print(
        "📥 PRIVATE GET:",
        url
    )

    response = session.get(
        url,
        params=data,
        headers=headers,
        timeout=TIMEOUT,
    )

    if response.status_code >= 400:

        raise RuntimeError(
            "HTTP "
            + str(response.status_code)
            + ":\n"
            + response.text[:1500]
        )

    return read_json(response)


# =========================================================
# PRIVATE POST
# =========================================================

def private_post(
    endpoint,
    version="v1",
    params=None
):

    if not API_KEY:

        raise RuntimeError(
            "TABDIL_API_KEY not found"
        )

    if not API_SECRET:

        raise RuntimeError(
            "TABDIL_API_SECRET not found"
        )

    data = dict(
        params or {}
    )

    data["timestamp"] = int(
        time.time() * 1000
    )

    data["recvWindow"] = RECV_WINDOW

    data["signature"] = make_signature(
        data
    )

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type":
            "application/x-www-form-urlencoded",
    }

    url = (
        WRITE_BASE
        + version
        + "/"
        + endpoint
    )

    print(
        "📤 PRIVATE POST:",
        url
    )

    response = session.post(
        url,
        data=data,
        headers=headers,
        timeout=TIMEOUT,
    )

    if response.status_code >= 400:

        raise RuntimeError(
            "HTTP "
            + str(response.status_code)
            + ":\n"
            + response.text[:1500]
        )

    return read_json(response)


# =========================================================
# EXCHANGE INFO
# =========================================================

def get_exchange_info():

    print(
        "🔎 GET FUTURES EXCHANGE INFO"
    )

    data = public_get(
        "exchangeInfo"
    )

    return data


# =========================================================
# EXTRACT SYMBOLS
# =========================================================

def extract_symbols(data):

    rows = []

    if isinstance(data, list):

        rows = data

    elif isinstance(data, dict):

        if isinstance(
            data.get("symbols"),
            list
        ):

            rows = data["symbols"]

        elif isinstance(
            data.get("data"),
            list
        ):

            rows = data["data"]

        elif isinstance(
            data.get("result"),
            list
        ):

            rows = data["result"]

        elif isinstance(
            data.get("data"),
            dict
        ):

            nested = data["data"]

            if isinstance(
                nested.get("symbols"),
                list
            ):

                rows = nested["symbols"]

        elif isinstance(
            data.get("result"),
            dict
        ):

            nested = data["result"]

            if isinstance(
                nested.get("symbols"),
                list
            ):

                rows = nested["symbols"]

    symbols = []

    for row in rows:

        if isinstance(row, str):

            symbol = row.upper().strip()

        elif isinstance(row, dict):

            symbol = str(
                row.get("symbol")
                or row.get("contract")
                or row.get("pair")
                or row.get("name")
                or ""
            ).upper().strip()

            status = str(
                row.get("status")
                or ""
            ).upper().strip()

            if status:

                allowed = {
                    "TRADING",
                    "OPEN",
                    "ACTIVE",
                    "1",
                }

                if status not in allowed:
                    continue

        else:

            continue

        if not symbol:
            continue

        # فقط بازارهای USDT/USD
        if not (
            symbol.endswith("USDT")
            or symbol.endswith("USDC")
            or symbol.endswith("USD")
        ):
            continue

        # موارد غیرمعامله‌ای
        if "INDEX" in symbol:
            continue

        if "MARK" in symbol:
            continue

        if "TEST" in symbol:
            continue

        symbols.append(symbol)

    return sorted(
        set(symbols)
    )


# =========================================================
# DEPTH
# =========================================================

def get_depth(symbol):

    return public_get(
        "depth",
        {
            "symbol": symbol,
            "limit": 5,
        }
    )


# =========================================================
# TEST SYMBOLS
# =========================================================

def verify_symbols(symbols):

    verified = []

    print(
        "\n" + "=" * 55
    )

    print(
        "🧪 VERIFY FUTURES SYMBOLS"
    )

    print(
        "=" * 55
    )

    for symbol in symbols:

        try:

            data = get_depth(
                symbol
            )

            bids = data.get(
                "bids",
                []
            )

            asks = data.get(
                "asks",
                []
            )

            if bids and asks:

                verified.append(
                    symbol
                )

                print(
                    "✅",
                    symbol
                )

            else:

                print(
                    "⚠️",
                    symbol,
                    "EMPTY BOOK"
                )

        except Exception as e:

            print(
                "❌",
                symbol,
                str(e)[:150]
            )

    return verified


# =========================================================
# FUTURES ACCOUNT
# =========================================================

def futures_account():

    print(
        "\n" + "=" * 55
    )

    print(
        "🔐 FUTURES ACCOUNT AUTH"
    )

    print(
        "=" * 55
    )

    # مهم:
    # Futures account در v3
    data = private_get(
        "account",
        version="v3"
    )

    if not isinstance(
        data,
        dict
    ):

        raise RuntimeError(
            "Unexpected account response"
        )

    print(
        "✅ AUTH SUCCESS"
    )

    print(
        "🔓 canTrade:",
        data.get(
            "canTrade"
        )
    )

    print(
        "📥 ACCOUNT RESPONSE OK"
    )

    return data


# =========================================================
# FUTURES POSITIONS
# =========================================================

def futures_positions():

    print(
        "\n" + "=" * 55
    )

    print(
        "📌 FUTURES POSITIONS"
    )

    print(
        "=" * 55
    )

    data = private_get(
        "positionRisk",
        version="v3"
    )

    if not isinstance(
        data,
        list
    ):

        if isinstance(
            data,
            dict
        ):

            if isinstance(
                data.get("data"),
                list
            ):

                data = data["data"]

            elif isinstance(
                data.get("result"),
                list
            ):

                data = data["result"]

    positions = []

    if isinstance(
        data,
        list
    ):

        for position in data:

            if not isinstance(
                position,
                dict
            ):

                continue

            qty = (
                position.get(
                    "positionAmt"
                )
                or position.get(
                    "quantity"
                )
                or position.get(
                    "qty"
                )
                or "0"
            )

            try:

                qty_decimal = Decimal(
                    str(qty)
                )

            except Exception:

                qty_decimal = Decimal(
                    "0"
                )

            if qty_decimal != 0:

                positions.append(
                    position
                )

                print(
                    "🟢",
                    position.get(
                        "symbol"
                    ),
                    "QTY=",
                    qty
                )

    if not positions:

        print(
            "✅ NO OPEN POSITIONS"
        )

    return positions


# =========================================================
# MAIN
# =========================================================

def main():

    telegram(
        "💓 ATI FUTURES\n"
        "⚡ MULTI-COIN V3 AUTH FIX\n"
        "📡 TABDEAL FUTURES\n"
        f"⚙️ LEVERAGE: {LEVERAGE}x\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        "🔒 REAL ORDER: OFF"
    )

    # -----------------------------------------------------
    # API CHECK
    # -----------------------------------------------------

    if not API_KEY:

        telegram(
            "❌ TABDIL_API_KEY پیدا نشد."
        )

        return

    if not API_SECRET:

        telegram(
            "❌ TABDIL_API_SECRET پیدا نشد."
        )

        return

    # -----------------------------------------------------
    # AUTH
    # -----------------------------------------------------

    try:

        account = futures_account()

        telegram(
            "✅ FUTURES AUTH SUCCESS\n"
            "🔓 canTrade="
            + str(
                account.get(
                    "canTrade"
                )
            )
        )

    except Exception as e:

        telegram(
            "❌ FUTURES AUTH ERROR\n\n"
            + str(e)
        )

        return

    # -----------------------------------------------------
    # POSITIONS
    # -----------------------------------------------------

    try:

        positions = futures_positions()

        telegram(
            "📌 OPEN POSITIONS: "
            + str(
                len(positions)
            )
        )

    except Exception as e:

        telegram(
            "❌ POSITION ERROR\n\n"
            + str(e)
        )

        return

    # -----------------------------------------------------
    # EXCHANGE INFO
    # -----------------------------------------------------

    try:

        info = get_exchange_info()

        symbols = extract_symbols(
            info
        )

    except Exception as e:

        telegram(
            "❌ EXCHANGE INFO ERROR\n\n"
            + str(e)
        )

        return

    if not symbols:

        telegram(
            "❌ هیچ Futures Symbol پیدا نشد."
        )

        return

    print(
        "\n📊 TOTAL FUTURES SYMBOLS:",
        len(symbols)
    )

    # -----------------------------------------------------
    # LIMIT
    # -----------------------------------------------------

    symbols = symbols[
        :MAX_SYMBOLS
    ]

    # -----------------------------------------------------
    # VERIFY
    # -----------------------------------------------------

    verified = verify_symbols(
        symbols
    )

    telegram(
        "✅ ATI FUTURES SCAN OK\n"
        f"📊 TOTAL: {len(symbols)}\n"
        f"🟢 VERIFIED: {len(verified)}\n"
        "🔐 AUTH: SUCCESS\n"
        "🔒 REAL ORDER: OFF"
    )

    # -----------------------------------------------------
    # END
    # -----------------------------------------------------

    print(
        "\n" + "=" * 55
    )

    print(
        "✅ ATI FUTURES COMPLETE"
    )

    print(
        "AUTH = SUCCESS"
    )

    print(
        "REAL ORDER = OFF"
    )

    print(
        "=" * 55
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        telegram(
            "🚨 ATI FUTURES CRITICAL ERROR\n\n"
            + str(e)
        )
