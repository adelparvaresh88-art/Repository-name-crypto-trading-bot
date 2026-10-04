import os
import time
import json
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.46-REAL
# TABDEAL SPOT
# SIGNAL DEBUG + TELEGRAM ERROR REPORTING
# ============================================================

VERSION = "V40.2.46-REAL"

BASE = "https://api1.tabdeal.org"

PUBLIC_ROOT = f"{BASE}/r/api/v1"
SIGNED_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 20
RECV_WINDOW = 10000

STATE_FILE = "ati_state.json"


# ============================================================
# API KEYS
# ============================================================

API_KEY = (
    os.getenv("TABDIL_API_KEY", "").strip()
    or os.getenv("TABDEAL_API_KEY", "").strip()
)

API_SECRET = (
    os.getenv("TABDIL_API_SECRET", "").strip()
    or os.getenv("TABDEAL_API_SECRET", "").strip()
)


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()


# ============================================================
# REAL TRADING
# ============================================================

REAL_TRADING = (
    os.getenv(
        "LIVE_TRADING",
        os.getenv("REAL_TRADING", "false")
    ).strip().lower()
    in ("1", "true", "yes", "on")
)


# ============================================================
# ORDER SETTINGS
# ============================================================

try:
    ORDER_USDT = Decimal(
        os.getenv(
            "ORDER_USDT",
            os.getenv("ORDER_QTY", "2")
        ).strip()
    )
except Exception:
    ORDER_USDT = Decimal("2")

if ORDER_USDT <= 0:
    ORDER_USDT = Decimal("2")


# ============================================================
# BALANCE RESERVE
# ============================================================

try:
    BALANCE_RESERVE_USDT = Decimal(
        os.getenv(
            "BALANCE_RESERVE_USDT",
            "0.02"
        ).strip()
    )
except Exception:
    BALANCE_RESERVE_USDT = Decimal("0.02")

if BALANCE_RESERVE_USDT < 0:
    BALANCE_RESERVE_USDT = Decimal("0")


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": f"ATI-Crypto-Bot/{VERSION}",
    "Accept": "application/json",
})


# ============================================================
# BASIC HELPERS
# ============================================================

def log(message):
    print(str(message), flush=True)


def utc_now():
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def dec(value, default="0"):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def decimal_text(value):

    value = dec(value)

    text = format(value, "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def floor_step(value, step):

    value = dec(value)
    step = dec(step)

    if step <= 0:
        return value

    units = (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    )

    return units * step


# ============================================================
# JSON
# ============================================================

def response_json(response):

    try:
        return response.json()
    except Exception:
        return {
            "raw": response.text
        }


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):

    if not TELEGRAM_TOKEN:
        log(
            "TELEGRAM ERROR: TOKEN EMPTY"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        log(
            "TELEGRAM ERROR: CHAT ID EMPTY"
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    try:

        response = SESSION.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": str(message),
            },
            timeout=15
        )

        log(
            f"TELEGRAM HTTP: {response.status_code}"
        )

        if response.status_code != 200:

            log(
                "TELEGRAM ERROR: "
                f"{response.text[:500]}"
            )

            return False

        data = response_json(response)

        if isinstance(data, dict):
            if data.get("ok") is False:
                log(
                    "TELEGRAM API ERROR: "
                    f"{json.dumps(data, ensure_ascii=False)}"
                )
                return False

        return True

    except Exception as exc:

        log(
            f"TELEGRAM EXCEPTION: {exc}"
        )

        return False


def telegram_test():

    return telegram(
        "🟢 ATI TELEGRAM TEST\n"
        f"⚡ {VERSION}\n"
        f"🕐 {utc_now()}\n"
        "✅ Telegram connection is working."
    )


# ============================================================
# HMAC
# ============================================================

def create_signed_parameters(parameters=None):

    params = {}

    if parameters:

        for key, value in parameters.items():

            if key in (
                "signature",
                "timestamp",
                "recvWindow"
            ):
                continue

            if value is None:
                continue

            value = str(value)

            if not value.strip():
                continue

            params[key] = value

    timestamp = int(
        time.time() * 1000
    )

    params["timestamp"] = timestamp
    params["recvWindow"] = RECV_WINDOW

    query_string = "&".join(
        f"{key}={value}"
        for key, value in params.items()
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return params, signature


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(
    method,
    path,
    params=None,
    order=False
):

    if not API_KEY:
        raise RuntimeError(
            "API KEY MISSING"
        )

    if not API_SECRET:
        raise RuntimeError(
            "API SECRET MISSING"
        )

    params, signature = create_signed_parameters(
        params
    )

    request_params = dict(params)
    request_params["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Accept": "application/json",
        "User-Agent": f"ATI-Crypto-Bot/{VERSION}",
    }

    root = (
        ORDER_ROOT
        if order
        else SIGNED_ROOT
    )

    url = f"{root}{path}"

    log(
        f"REQUEST: {method.upper()} {url}"
    )

    try:

        method = method.upper()

        if method == "GET":

            response = SESSION.get(
                url,
                params=request_params,
                headers=headers,
                timeout=TIMEOUT
            )

        elif method == "POST":

            headers["Content-Type"] = (
                "application/x-www-form-urlencoded"
            )

            response = SESSION.post(
                url,
                data=request_params,
                headers=headers,
                timeout=TIMEOUT
            )

        elif method == "DELETE":

            response = SESSION.delete(
                url,
                params=request_params,
                headers=headers,
                timeout=TIMEOUT
            )

        else:

            response = SESSION.request(
                method,
                url,
                params=request_params,
                headers=headers,
                timeout=TIMEOUT
            )

    except requests.RequestException as exc:

        raise RuntimeError(
            f"NETWORK ERROR: {exc}"
        )

    data = response_json(response)

    if not (
        200 <= response.status_code < 300
    ):

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{json.dumps(data, ensure_ascii=False)}"
        )

    if isinstance(data, dict):

        if str(data.get("code")) == "1103":

            raise RuntimeError(
                "HTTP 401: Invalid Signature"
            )

    return data


# ============================================================
# AUTH
# ============================================================

def auth_test():

    log("AUTH TEST: STARTING")

    account = signed_request(
        "GET",
        "/account"
    )

    log("AUTH TEST: SUCCESS")

    return account


# ============================================================
# PUBLIC REQUEST
# ============================================================

def public_request(
    path,
    params=None
):

    url = f"{PUBLIC_ROOT}{path}"

    try:

        response = SESSION.get(
            url,
            params=params or {},
            timeout=TIMEOUT
        )

    except requests.RequestException as exc:

        raise RuntimeError(
            f"PUBLIC API ERROR: {exc}"
        )

    data = response_json(response)

    if response.status_code != 200:

        raise RuntimeError(
            f"PUBLIC HTTP {response.status_code}: "
            f"{json.dumps(data, ensure_ascii=False)}"
        )

    return data


# ============================================================
# MARKETS
# ============================================================

def get_exchange_info():

    return public_request(
        "/exchangeInfo"
    )


def extract_markets(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in (
        "symbols",
        "data",
        "markets",
        "result"
    ):

        value = data.get(key)

        if isinstance(value, list):
            return value

    return []


def get_usdt_markets():

    data = get_exchange_info()

    raw = extract_markets(data)

    markets = []

    for item in raw:

        if not isinstance(item, dict):
            continue

        symbol = str(
            item.get("symbol")
            or item.get("market")
            or ""
        ).upper()

        if not symbol.endswith("USDT"):
            continue

        status = str(
            item.get("status", "TRADING")
        ).upper()

        if status not in (
            "TRADING",
            "ACTIVE",
            "ENABLED"
        ):
            continue

        markets.append(item)

    return markets


# ============================================================
# MARKET RULES
# ============================================================

def market_rules(item):

    filters = item.get(
        "filters",
        []
    )

    step_size = Decimal("0.000001")
    min_qty = Decimal("0")
    min_notional = Decimal("0")
    tick_size = Decimal("0.00000001")

    for f in filters:

        if not isinstance(f, dict):
            continue

        ft = str(
            f.get("filterType", "")
        ).upper()

        if ft in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE"
        ):

            step_size = dec(
                f.get(
                    "stepSize",
                    step_size
                ),
                str(step_size)
            )

            min_qty = dec(
                f.get(
                    "minQty",
                    min_qty
                ),
                str(min_qty)
            )

        elif ft in (
            "MIN_NOTIONAL",
            "NOTIONAL"
        ):

            min_notional = dec(
                f.get(
                    "minNotional",
                    min_notional
                ),
                str(min_notional)
            )

        elif ft == "PRICE_FILTER":

            tick_size = dec(
                f.get(
                    "tickSize",
                    tick_size
                ),
                str(tick_size)
            )

    return {
        "step_size": step_size,
        "min_qty": min_qty,
        "min_notional": min_notional,
        "tick_size": tick_size,
    }


# ============================================================
# TRADES
# ============================================================

def get_recent_trades(
    symbol,
    limit=300
):

    data = public_request(
        "/trades",
        {
            "symbol": symbol,
            "limit": limit
        }
    )

    if isinstance(data, dict):

        for key in (
            "data",
            "trades",
            "results"
        ):

            if isinstance(
                data.get(key),
                list
            ):

                data = data[key]
                break

    return data if isinstance(data, list) else []


def parse_trade(item):

    if not isinstance(item, dict):
        return None

    price = (
        item.get("price")
        or item.get("p")
    )

    quantity = (
        item.get("qty")
        or item.get("quantity")
        or item.get("q")
        or "0"
    )

    timestamp = (
        item.get("time")
        or item.get("timestamp")
        or item.get("T")
    )

    if price is None or timestamp is None:
        return None

    try:

        return (
            int(timestamp),
            Decimal(str(price)),
            Decimal(str(quantity))
        )

    except Exception:

        return None


# ============================================================
# 5M CLOSED CANDLES
# ============================================================

def make_5m_candles(trades):

    buckets = {}

    for item in trades:

        parsed = parse_trade(item)

        if not parsed:
            continue

        timestamp, price, quantity = parsed

        bucket = (
            timestamp // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": quantity,
            }

        else:

            c = buckets[bucket]

            c["high"] = max(
                c["high"],
                price
            )

            c["low"] = min(
                c["low"],
                price
            )

            c["close"] = price
            c["volume"] += quantity

    candles = [
        buckets[key]
        for key in sorted(buckets)
    ]

    current_bucket = (
        int(time.time() * 1000)
        // 300000
    ) * 300000

    if candles:

        if candles[-1]["time"] >= current_bucket:
            candles.pop()

    return candles


# ============================================================
# PRICE ACTION
# ============================================================

def candle_range(c):
   
