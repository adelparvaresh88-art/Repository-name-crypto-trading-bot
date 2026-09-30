import os
import json
import time
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.10
# TABDEAL SIGNATURE FIX
# REAL SPOT BUY -> FILLED CHECK -> OCO TP/SL
# ============================================================

VERSION = "V40.2.10"

BASE_URL = "https://api1.tabdeal.org"

EXCHANGE_INFO_PATH = "/r/api/v1/exchangeInfo"
TRADES_PATH = "/r/api/v1/trades"

ORDER_PATH = "/api/v1/order"
ORDER_QUERY_PATH = "/r/api/v1/order"
OCO_PATH = "/api/v1/order/oco"

REQUEST_TIMEOUT = 15
TELEGRAM_TIMEOUT = 15
TELEGRAM_RETRIES = 4

MAX_SYMBOLS = 529
MAX_REAL_BUYS_PER_RUN = 1

MIN_CANDLES = 12
MAX_HISTORY = 500

CONFIRMED_SCORE = 10
EARLY_SCORE = 9
WATCH_SCORE = 6

MAX_RISK_PCT = 1.20

TP1_R = 1.67
TP2_R = 2.67

RECV_WINDOW = 10000

HISTORY_FILE = "paper_history.json"


# ============================================================
# ENV
# ============================================================

API_KEY = os.getenv(
    "TABDEAL_API_KEY",
    ""
).strip()

API_SECRET = os.getenv(
    "TABDEAL_API_SECRET",
    ""
).strip()

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()

ORDER_QTY_RAW = os.getenv(
    "ORDER_QTY",
    "0.001"
).strip()

LIVE_TRADING = (
    os.getenv(
        "LIVE_TRADING",
        "false"
    ).strip().lower() == "true"
)

REAL_TRADING_CONFIRM = (
    os.getenv(
        "REAL_TRADING_CONFIRM",
        ""
    ).strip().upper() == "YES"
)

# ============================================================
# IMPORTANT:
# REAL BUY requires BOTH:
#
# LIVE_TRADING=true
# REAL_TRADING_CONFIRM=YES
#
# This prevents accidental real orders.
# ============================================================

REAL_ORDERS = (
    LIVE_TRADING
    and REAL_TRADING_CONFIRM
)


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": (
            f"ATI-Crypto-Bot/{VERSION}"
        ),
        "Accept": "application/json",
    }
)


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send_once(message):

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:

        r = session.post(
            url,
            json=payload,
            timeout=TELEGRAM_TIMEOUT,
        )

        if r.status_code != 200:
            return False

        data = r.json()

        return bool(
            data.get("ok")
        )

    except Exception:
        return False


def telegram_send(message):

    if not message:
        return False

    chunks = []

    max_len = 3500

    for i in range(
        0,
        len(message),
        max_len
    ):
        chunks.append(
            message[i:i + max_len]
        )

    all_ok = True

    for chunk in chunks:

        sent = False

        for attempt in range(
            TELEGRAM_RETRIES
        ):

            if telegram_send_once(
                chunk
            ):
                sent = True
                break

            time.sleep(
                2 + attempt * 2
            )

        if not sent:
            all_ok = False

    return all_ok


def heartbeat(text):

    telegram_send(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"{text}\n\n"
        f"🕐 {utc_now()}"
    )


# ============================================================
# TIME
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def now_ms():

    return int(
        time.time() * 1000
    )


# ============================================================
# NUMBER HELPERS
# ============================================================

def D(value):

    try:
        return Decimal(
            str(value)
        )

    except Exception:
        return Decimal("0")


def fmt(
    value,
    digits=12
):

    try:

        x = D(value)

        s = (
            f"{x:.{digits}f}"
            .rstrip("0")
            .rstrip(".")
        )

        if s == "-0":
            s = "0"

        return s

    except Exception:
        return str(value)


def floor_step(
    value,
    step
):

    value = D(value)
    step = D(step)

    if step <= 0:
        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


def floor_to_tick(
    value,
    tick
):

    return floor_step(
        value,
        tick
    )


# ============================================================
# SIGNATURE
# ============================================================

def make_signature(params):

    """
    Tabdeal-compatible HMAC SHA256.

    IMPORTANT:
    The exact URL-encoded parameter string is signed.

    Do not include the signature itself
    inside the string being signed.
    """

    clean = {}

    for key, value in params.items():

        if value is None:
            continue

        if key == "signature":
            continue

        clean[key] = value

    query_string = urlencode(
        clean
    )

    return hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def signed_params(
    params=None
):

    params = dict(
        params or {}
    )

    params["timestamp"] = now_ms()

    params["recvWindow"] = (
        RECV_WINDOW
    )

    params["signature"] = (
        make_signature(params)
    )

    return params


# ============================================================
# PUBLIC API
# ============================================================

def public_get(
    path,
    params=None
):

    url = BASE_URL + path

    r = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    r.raise_for_status()

    return r.json()


# ============================================================
# SIGNED GET
# ============================================================

def signed_get(
    path,
    params=None
):

    if (
        not API_KEY
        or not API_SECRET
    ):
        raise RuntimeError(
            "TABDEAL_API_KEY / "
            "TABDEAL_API_SECRET missing"
        )

    payload = signed_params(
        params
    )

    r = session.get(
        BASE_URL + path,
        params=payload,
        headers={
            "X-MBX-APIKEY": API_KEY,
        },
        timeout=REQUEST_TIMEOUT,
    )

    try:
        data = r.json()

    except Exception:
        data = {
            "raw": r.text
        }

    if r.status_code >= 400:

        raise RuntimeError(
            f"GET {path} "
            f"HTTP {r.status_code}: "
            f"{data}"
        )

    return data


# ============================================================
# SIGNED POST
# ============================================================

def signed_post(
    path,
    params=None
):

    if (
        not API_KEY
        or not API_SECRET
    ):
        raise RuntimeError(
            "TABDEAL_API_KEY / "
            "TABDEAL_API_SECRET missing"
        )

    payload = signed_params(
        params
    )

    r = session.post(
        BASE_URL + path,
        data=payload,
        headers={
            "X-MBX-APIKEY": API_KEY,
            "Content-Type":
                "application/x-www-form-urlencoded",
        },
        timeout=REQUEST_TIMEOUT,
    )

    try:
        data = r.json()

    except Exception:
        data = {
            "raw": r.text
        }

    if r.status_code >= 400:

        raise RuntimeError(
            f"POST {path} "
            f"HTTP {r.status_code}: "
            f"{data}"
        )

    return data


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    return public_get(
        EXCHANGE_INFO_PATH
    )


def extract_symbols(
    exchange
):

    if isinstance(
        exchange,
        dict
    ):

        symbols = exchange.get(
            "symbols"
        )

        if isinstance(
            symbols,
            list
        ):
            return symbols

        if exchange.get(
            "symbol"
        ):
            return [exchange]

    if isinstance(
        exchange,
        list
    ):
        return exchange

    return []


def is_usdt_market(
    item
):

    symbol = str(
        item.get(
            "symbol",
            ""
        )
    ).upper()

    tabdeal_symbol = str(
        item.get(
            "tabdealSymbol",
            ""
        )
    ).upper()

    quote = str(
        item.get(
            "quoteAsset",
            ""
        )
    ).upper()

    return (
        quote == "USDT"
        or symbol.endswith("USDT")
        or tabdeal_symbol.endswith(
            "_USDT"
        )
    )


def market_symbol(
    item
):

    return str(
        item.get(
            "symbol"
        )
        or item.get(
            "market"
        )
        or ""
    ).upper()


def tabdeal_symbol(
    item
):

    value = item.get(
        "tabdealSymbol"
    )

    if value:
        return str(
            value
        ).upper()

    symbol = market_symbol(
        item
    )

    if symbol.endswith(
        "USDT"
    ):

        return (
            symbol[:-4]
            + "_USDT"
        )

    return symbol


def market_filters(
    item
):

    filters = item.get(
        "filters",
        []
    )

    result = {
        "tickSize": Decimal("0"),
        "stepSize": Decimal("0"),
        "minQty": Decimal("0"),
        "maxQty": Decimal("0"),
        "marketStepSize":
            Decimal("0"),
        "marketMinQty":
            Decimal("0"),
        "marketMaxQty":
            Decimal("0"),
        "minNotional":
            Decimal("0"),
        "ocoAllowed":
            bool(
                item.get(
                    "ocoAllowed",
                    False
                )
            ),
    }

    for f in filters:

        ftype = str(
            f.get(
                "filterType",
                ""
            )
        ).upper()

        if ftype == "PRICE_FILTER":

            result[
                "tickSize"
            ] = D(
                f.get(
                    "tickSize",
                    "0"
                )
            )

        elif ftype == "LOT_SIZE":

            result[
                "stepSize"
            ] = D(
                f.get(
                    "stepSize",
                    "0"
                )
            )

            result[
                "minQty"
            ] = D(
                f.get(
                    "minQty",
                    "0"
                )
            )

            result[
                "maxQty"
            ] = D(
                f.get(
                    "maxQty",
                    "0"
                )
            )

        elif (
            ftype
            == "MARKET_LOT_SIZE"
        ):

            step = D(
                f.get(
                    "stepSize",
                    "0"
                )
            )

            if step > 0:

                result[
                    "marketStepSize"
                ] = step

            result[
                "marketMinQty"
            ] = D(
                f.get(
                    "minQty",
                    "0"
                )
            )

            result[
                "marketMaxQty"
            ] = D(
                f.get(
                    "maxQty",
                    "0"
                )
            )

        elif (
            ftype
            == "MIN_NOTIONAL"
        ):

            result[
                "minNotional"
            ] = D(
                f.get(
                    "minNotional",
                    "0"
                )
            )

    if (
        result[
            "marketStepSize"
        ] <= 0
    ):

        result[
            "marketStepSize"
        ] = result[
            "stepSize"
        ]

    return result


# ============================================================
# TRADES -> 5M CANDLES
# ============================================================

def get_trades(
    symbol
):

    return public_get(
        TRADES_PATH,
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )


def trade_price(
    t
):

    for key in (
        "price",
        "p"
    ):

        if key in t:
            return D(
                t[key]
            )

    return Decimal("0")


def trade_qty(
    t
):

    for key in (
        "qty",
        "quantity",
        "q"
    ):

        if key in t:
            return D(
                t[key]
            )

    return Decimal("0")


def trade_time(
    t
):

    for key in (
        "time",
        "timestamp",
        "T"
    ):

        if key in t:

            try:
                return int(
                    t[key]
                )

            except Exception:
                pass

    return 0


def trade_side(
    t
):

    if "isBuyerMaker" in t:

        return (
            "SELL"
            if bool(
                t["isBuyerMaker"]
            )
            else "BUY"
        )

    side = str(
        t.get(
            "side",
            ""
        )
    ).upper()

    if side in (
        "BUY",
