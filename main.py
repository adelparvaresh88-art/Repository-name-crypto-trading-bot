import os
import time
import json
import hmac
import hashlib
import math
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.17
# TABDEAL HMAC AUTH FIX
#
# FIX:
#   HTTP 401 / CODE 1103 / Invalid Signature
#
# SIGNING:
#   timestamp -> recvWindow
#   HMAC-SHA256
#   EXACT SAME QUERY STRING IS SIGNED AND SENT
#
# REAL BUY:
#   LOCKED until authentication + trading checks pass
#
# MAX REAL BUY:
#   1 per run
#
# ORDER:
#   FIXED USDT AMOUNT
#   stepSize / minQty / minNotional protection
# ============================================================

VERSION = "V40.2.17"

BASE_URL = "https://api1.tabdeal.org"

EXCHANGE_INFO_PATH = "/r/api/v1/exchangeInfo"
SERVER_TIME_PATH = "/r/api/v1/time"
TRADES_PATH = "/r/api/v1/trades"
DEPTH_PATH = "/r/api/v1/depth"
ACCOUNT_PATH = "/r/api/v1/account"
ORDER_PATH = "/r/api/v1/order"

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").strip().lower() == "true"

try:
    ORDER_USDT = Decimal(os.getenv("ORDER_QTY", "2").strip())
except Exception:
    ORDER_USDT = Decimal("2")

RECV_WINDOW = 10000

REQUEST_TIMEOUT = 20

MAX_REAL_BUYS_PER_RUN = 1

# Never trade these symbols
BLACKLIST = {
    "USDTUSDT",
    "USDCUSDT",
    "FDUSDUSDT",
    "TUSDUSDT",
    "DAIUSDT",
    "EURUSDT",
}

session = requests.Session()

SERVER_TIME_OFFSET_MS = 0

AUTH_OK = False
TRADING_OK = False
REAL_BUY_UNLOCKED = False

REAL_BUYS_THIS_RUN = 0

MARKET_RULES = {}


# ============================================================
# BASIC HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def log(message):
    print(message, flush=True)


def telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
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
        r = requests.post(
            url,
            data=payload,
            timeout=15,
        )

        if r.ok:
            return True

        log(
            "TELEGRAM ERROR "
            + str(r.status_code)
            + " "
            + r.text[:300]
        )

    except Exception as e:
        log("TELEGRAM EXCEPTION: " + str(e))

    return False


def notify(message):
    log(message)
    telegram(message)


def decimal_from(value, default=Decimal("0")):
    try:
        if value is None:
            return default

        return Decimal(str(value))
    except Exception:
        return default


def decimal_to_string(value):
    d = decimal_from(value)

    text = format(d, "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    if text == "":
        text = "0"

    return text


def floor_to_step(value, step):
    value = decimal_from(value)
    step = decimal_from(step)

    if step <= 0:
        return value

    units = (value / step).to_integral_value(
        rounding=ROUND_DOWN
    )

    return units * step


def percent(a, b):
    a = decimal_from(a)
    b = decimal_from(b)

    if b == 0:
        return Decimal("0")

    return ((a - b) / b) * Decimal("100")


# ============================================================
# API TIME
# ============================================================

def extract_server_time(data):
    if isinstance(data, dict):
        for key in (
            "serverTime",
            "server_time",
            "time",
            "timestamp",
        ):
            if key in data:
                try:
                    return int(data[key])
                except Exception:
                    pass

        result = data.get("result")

        if isinstance(result, dict):
            for key in (
                "serverTime",
                "server_time",
                "time",
                "timestamp",
            ):
                if key in result:
                    try:
                        return int(result[key])
                    except Exception:
                        pass

        if isinstance(result, (int, float, str)):
            try:
                return int(result)
            except Exception:
                pass

    return None


def sync_server_time():
    global SERVER_TIME_OFFSET_MS

    try:
        local_before = int(time.time() * 1000)

        r = session.get(
            BASE_URL + SERVER_TIME_PATH,
            timeout=REQUEST_TIMEOUT,
        )

        local_after = int(time.time() * 1000)

        if not r.ok:
            log(
                "SERVER TIME ERROR "
                + str(r.status_code)
                + " "
                + r.text[:300]
            )
            return False

        data = r.json()

        server_ms = extract_server_time(data)

        if server_ms is None:
            # Some API deployments may return server time differently.
            # Try common exchange-info headers/body fallback.
            log("SERVER TIME: RESPONSE TIME NOT FOUND")
            return False

        midpoint = (local_before + local_after) // 2

        SERVER_TIME_OFFSET_MS = server_ms - midpoint

        log(
            "SERVER TIME SYNC OK | OFFSET "
            + str(SERVER_TIME_OFFSET_MS)
            + " ms"
        )

        return True

    except Exception as e:
        log("SERVER TIME EXCEPTION: " + str(e))
        return False


def signed_timestamp():
    local_ms = int(time.time() * 1000)

    return local_ms + SERVER_TIME_OFFSET_MS


# ============================================================
# HMAC-SHA256 SIGNING
# ============================================================

def hmac_signature(query_string):
    """
    IMPORTANT:

    The signature is calculated over the EXACT query string.

    Example:

        timestamp=123456789&recvWindow=10000

    and the exact same string is sent to Tabdeal.

    DO NOT:
        sort()
        reorder()
        urlencode again
        alter timestamp
        alter recvWindow
    """

    return hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_signed_query(extra_params=None):
    """
    IMPORTANT ORDER:

        extra parameters
        timestamp
        recvWindow

    For authentication-only requests extra_params is empty,
    therefore:

        timestamp -> recvWindow

    The same query string is signed and transmitted.
    """

    parts = []

    if extra_params:
        for key, value in extra_params:
            if value is None:
                continue

            parts.append(
                str(key)
                + "="
                + str(value)
            )

    parts.append(
        "timestamp="
        + str(signed_timestamp())
    )

    parts.append(
        "recvWindow="
        + str(RECV_WINDOW)
    )

    query_string = "&".join(parts)

    signature = hmac_signature(query_string)

    return query_string, signature


def private_get(path, extra_params=None):
    query_string, signature = build_signed_query(
        extra_params
    )

    url = (
        BASE_URL
        + path
        + "?"
        + query_string
        + "&signature="
        + signature
    )

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Accept": "application/json",
    }

    return session.get(
        url,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )


def private_post(path, extra_params=None):
    query_string, signature = build_signed_query(
        extra_params
    )

    full_query = (
        query_string
        + "&signature="
        + signature
    )

    url = BASE_URL + path

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    return session.post(
        url,
        headers=headers,
        data=full_query,
        timeout=REQUEST_TIMEOUT,
    )


# ============================================================
# PUBLIC API
# ============================================================

def public_get(path, params=None):
    try:
        r = session.get(
            BASE_URL + path,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        return r

    except Exception as e:
        log(
            "PUBLIC API EXCEPTION "
            + path
            + ": "
            + str(e)
        )

        return None


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():
    try:
        r = public_get(EXCHANGE_INFO_PATH)

        if r is None:
            return None

        if not r.ok:
            log(
                "EXCHANGE INFO ERROR "
                + str(r.status_code)
                + " "
                + r.text[:500]
            )
            return None

        return r.json()

    except Exception as e:
        log(
            "EXCHANGE INFO EXCEPTION: "
            + str(e)
        )

        return None


def parse_symbol_rules(info):
    global MARKET_RULES

    MARKET_RULES = {}

    if not isinstance(info, dict):
        return

    symbols = info.get("symbols")

    if symbols is None:
        symbols = info.get("data")

    if isinstance(info.get("data"), dict):
        symbols = info["data"].get("symbols", symbols)

    if not isinstance(symbols, list):
        return

    for item in symbols:
        if not isinstance(item, dict):
            continue

        symbol = str(
            item.get("symbol", "")
        ).upper()

        if not symbol.endswith("USDT"):
            continue

        status = str(
            item.get("status", "TRADING")
        ).upper()

        if status not in (
            "",
            "TRADING",
            "ENABLED",
        ):
            continue

        base_asset = str(
            item.get("baseAsset", "")
        )

        quote_asset = str(
            item.get("quoteAsset", "USDT")
        )

        min_qty = Decimal("0")
        max_qty = Decimal("0")
        step_size = Decimal("0")
        min_notional = Decimal("0")

        filters = item.get("filters", [])

        if isinstance(filters, list):
            for f in filters:
                if not isinstance(f, dict):
                    continue

                ftype = str(
                    f.get("filterType", "")
                ).upper()

                if ftype in (
                    "LOT_SIZE",
                    "MARKET_LOT_SIZE",
                ):
                    min_qty = max(
                        min_qty,
                        decimal_from(
                            f.get("minQty")
                        ),
                    )

                    max_qty = decimal_from(
                        f.get("maxQty")
                    )

                    if step_size == 0:
                        step_size = decimal_from(
                            f.get("stepSize")
                        )

                elif ftype in (
                    "MIN_NOTIONAL",
                    "NOTIONAL",
                ):
                    min_notional = max(
                        min_notional,
                        decimal_from(
                            f.get("minNotional")
                        ),
                    )

        MARKET_RULES[symbol] = {
            "baseAsset": base_asset,
            "quoteAsset": quote_asset,
            "minQty": min_qty,
            "maxQty": max_qty,
            "stepSize": step_size,
            "minNotional": min_notional,
        }


# ============================================================
# ACCOUNT AUTH
# ============================================================

def authenticate_account():
    global AUTH_OK

    AUTH_OK = False

    if not API_KEY or not API_SECRET:
        notify(
            "🚨 ATI API AUTH FAILED "
            + VERSION
            + "\n\n"
            + "❌ API KEY/SECRET MISSING\n"
            + "🛑 REAL BUY LOCKED"
        )
        return False

    # Sync server time immediately before private auth.
    if not sync_server_time():
        notify(
            "🚨 ATI AUTH TIME SYNC FAILED "
            + VERSION
            + "\n\n"
            + "❌ SERVER TIME NOT AVAILABLE\n"
            + "🛑 REAL BUY LOCKED"
        )
        return False

    try:
        r = private_get(
            ACCOUNT_PATH
        )

        if r is None:
            notify(
                "🚨 ATI API AUTH FAILED "
                + VERSION
                + "\n\n"
                + "❌ NO RESPONSE\n"
                + "🛑 REAL BUY LOCKED"
            )
            return False

        if r.status_code == 200:
            try:
                data = r.json()
            except Exception:
                data = {}

            if isinstance(data, dict):
                code = data.get("code")

                if code not in (
                    None,
                    0,
                    "0",
                ):
                    notify(
                        "🚨 ATI API AUTH FAILED "
                        + VERSION
                        + "\n\n"
                        + "❌ CODE: "
                        + str(code)
                        + "\n"
                        + "❌ RESPONSE: "
                        + str(data)[:500]
                        + "\n\n"
                        + "🛑 REAL BUY LOCKED"
                    )
                    return False

            AUTH_OK = True

            notify(
                "🔐 ATI API AUTH OK "
                + VERSION
                + "\n\n"
                + "✅ HMAC-SHA256\n"
                + "✅ SERVER TIME SYNCED\n"
                + "✅ TIMESTAMP → RECVWINDOW\n"
                + "✅ ACCOUNT ACCESS OK"
            )

            return True

        text = r.text[:800]

        code = ""

        try:
            body = r.json()

            if isinstance(body, dict):
                code = body.get("code", "")
        except Exception:
            pass

        if r.status_code == 401 or str(code) == "1103":
            notify(
                "🚨 ATI API AUTH FAILED "
                + VERSION
                + "\n\n"
                + "❌ HTTP "
                + str(r.status_code)
                + "\n"
                + "❌ CODE: "
                + str(code)
                + "\n"
                + "❌ Invalid Signature\n\n"
                + "🔐 SIGN METHOD: HMAC-SHA256\n"
                + "🔐 PARAM ORDER: timestamp → recvWindow\n"
                + "🔐 EXACT QUERY SIGNED/SENT\n\n"
                + "🛑 REAL BUY LOCKED\n"
                + "🛑 NO ORDER WAS SENT"
            )

        else:
            notify(
                "🚨 ATI API AUTH FAILED "
                + VERSION
                + "\n\n"
                + "❌ HTTP "
                + str(r.status_code)
                + "\n"
                + "❌ CODE: "
                + str(code)
                + "\n"
                + "❌ "
                + text
                + "\n\n"
                + "🛑 REAL BUY LOCKED"
            )

        return False

    except Exception as e:
        notify(
            "🚨 ATI AUTH EXCEPTION "
            + VERSION
            + "\n\n"
            + str(e)
            + "\n\n"
            + "🛑 REAL BUY LOCKED"
        )

        return False


# ============================================================
# TRADING PERMISSION CHECK
# ============================================================

def check_trading_access():
    global TRADING_OK
    global REAL_BUY_UNLOCKED

    TRADING_OK = False
    REAL_BUY_UNLOCKED = False

    if not AUTH_OK:
        return False

    try:
        # Account response is already the main permission check.
        # Keep a second private request so real BUY is never unlocked
        # from a partial/invalid authentication result.
        r = private_get(
            ACCOUNT_PATH
        )

        if r is None:
            notify(
                "🛑 ATI TRADING CHECK FAILED\n"
                "❌ NO ACCOUNT RESPONSE\n"
                "🛑 REAL BUY LOCKED"
            )
            return False

        if r.status_code != 200:
            notify(
                "🛑 ATI TRADING CHECK FAILED\n"
                "❌ HTTP "
                + str(r.status_code)
                + "\n"
                "🛑 REAL BUY LOCKED"
            )
            return False

        data = r.json()

        if isinstance(data, dict):
            code = data.get("code")

            if code not in (
                None,
                0,
                "0",
            ):
                notify(
                    "🛑 ATI TRADING CHECK FAILED\n"
                    "❌ CODE "
                    + str(code)
                    + "\n"
                    "🛑 REAL BUY LOCKED"
                )
                return False

            permissions = data.get(
                "permissions"
            )

            if isinstance(permissions, list):
                normalized = {
                    str(x).upper()
                    for x in permissions
                }

                if (
                    "SPOT" not in normalized
                    and "TRADING" not in normalized
                    and "TRADE" not in normalized
                ):
                    log(
                        "ACCOUNT PERMISSIONS: "
                        + str(permissions)
                    )

        TRADING_OK = True

        if LIVE_TRADING:
            REAL_BUY_UNLOCKED = True

        notify(
            "🔓 ATI TRADING CHECK OK "
            + VERSION
            + "\n\n"
            + "✅ PRIVATE API ACCESS OK\n"
            + "✅ ACCOUNT CHECK OK\n"
            + (
                "🟢 REAL BUY UNLOCKED"
                if REAL_BUY_UNLOCKED
                else "🟡 PAPER MODE"
            )
        )

        return True

    except Exception as e:
        notify(
            "🛑 ATI TRADING CHECK EXCEPTION\n"
            + str(e)
            + "\n🛑 REAL BUY LOCKED"
        )

        return False


# ============================================================
# BALANCE
# ============================================================

def extract_balances(data):
    if not isinstance(data, dict):
        return []

    for key in (
        "balances",
        "assets",
        "data",
    ):
        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            nested = value.get("balances")

            if isinstance(nested, list):
                return nested

    if isinstance(data.get("data"), dict):
        value = data["data"].get("balances")

        if isinstance(value, list):
            return value

    return []


def get_usdt_balance():
    if not AUTH_OK:
        return Decimal("0")

    try:
        r = private_get(
            ACCOUNT_PATH
        )

        if r is None or r.status_code != 200:
            return Decimal("0")

        data = r.json()

        balances = extract_balances(data)

        for b in balances:
            if not isinstance(b, dict):
                continue

            asset = str(
                b.get(
                    "asset",
                    b.get("currency", "")
                )
            ).upper()

            if asset != "USDT":
                continue

            for key in (
                "free",
                "available",
                "availableBalance",
                "balance",
            ):
                if key in b:
                    return decimal_from(
                        b.get(key)
                    )

        # Some APIs return USDT directly.
        for key in (
            "USDT",
            "usdt",
        ):
            if key in data:
                return decimal_from(
                    data[key]
                )

    except Exception as e:
        log(
            "BALANCE ERROR: "
            + str(e)
        )

    return Decimal("0")


# ============================================================
# MARKET DATA
# ============================================================

def get_trades(symbol):
    try:
        r = public_get(
            TRADES_PATH,
            {
                "symbol": symbol,
                "limit": 1000,
            },
        )

        if r is None or not r.ok:
            return []

        data = r.json()

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            for key in (
                "data",
                "trades",
                "result",
            ):
                value = data.get(key)

                if isinstance(value, list):
                    return value

        return []

    except Exception:
        return []


def trade_price(trade):
    if not isinstance(trade, dict):
        return Decimal("0")

    for key in (
        "price",
        "p",
    ):
        if key in trade:
            return decimal_from(
                trade[key]
            )

    return Decimal("0")


def trade_qty(trade):
    if not isinstance(trade, dict):
        return Decimal("0")

    for key in (
        "qty",
        "quantity",
        "q",
        "amount",
    ):
        if key in trade:
            return decimal_from(
                trade[key]
            )

    return Decimal("0")


def trade_time(trade):
    if not isinstance(trade, dict):
        return 0

    for key in (
        "time",
        "timestamp",
        "T",
    ):
        if key in trade:
            try:
                return int(
                    trade[key]
                )
            except Exception:
                return 0

    return 0


# ============================================================
# SIMPLE 5-MINUTE SIGNAL ENGINE
# ============================================================

def build_candles(trades):
    """
    Converts recent trades into approximate 5-minute candles.
    """

    buckets = {}

    for t in trades:
        price = trade_price(t)
        qty = trade_qty(t)
        ts = trade_time(t)

        if price <= 0 or ts <= 0:
            continue

        # Accept seconds as well as milliseconds.
        if ts < 100000000000:
            ts *= 1000

        bucket = (
            ts // 300000
        ) * 300000

        if bucket not in buckets:
            buckets[bucket] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": Decimal("0"),
            }

        c = buckets[bucket]

        c["high"] = max(
            c["high"],
            price,
        )

        c["low"] = min(
            c["low"],
            price,
        )

        c["close"] = price

        c["volume"] += qty

    result = []

    for ts in sorted(buckets):
        c = buckets[ts]

        c["time"] = ts

        result.append(c)

    return result


def calculate_signal(symbol, candles):
    """
    Conservative price-action breakout/retest signal.

    Uses CLOSED candles only.
    """

    if len(candles) < 8:
        return None

    # Exclude current/incomplete candle.
    closed = candles[:-1]

    if len(closed) < 7:
        return None

    last = closed[-1]

    previous = closed[-2]

    lookback = closed[-7:-1]

    resistance = max(
        c["high"]
        for c in lookback
    )

    recent_low = min(
        c["low"]
        for c in lookback
    )

    close = last["close"]

    if close <= 0:
        return None

    body = abs(
        last["close"]
        - last["open"]
    )

    candle_range = (
        last["high"]
        - last["low"]
    )

    if candle_range <= 0:
        return None

    body_ratio = (
        body / candle_range
    )

    breakout_pct = percent(
        close,
        resistance,
    )

    previous_below = (
        previous["close"]
        <= resistance
    )

    breakout = (
        close > resistance
        and previous_below
    )

    # Retest / continuation:
    # price must remain above resistance
    # and not be an extreme chase.
    hold = close >= resistance * Decimal("0.998")

    momentum = close > previous["close"]

    if not breakout and not (
        hold
        and momentum
        and close > resistance
    ):
        return None

    if body_ratio < Decimal("0.45"):
        return None

    if breakout_pct > Decimal("8"):
        return None

    move_from_low = percent(
        close,
        recent_low,
    )

    if move_from_low > Decimal("15"):
        return None

    score = 0

    if breakout:
        score += 6

    if hold:
        score += 3

    if momentum:
        score += 2

    if body_ratio >= Decimal("0.60"):
        score += 2

    if breakout_pct >= Decimal("0.20"):
        score += 1

    if score < 9:
        return None

    # Risk model
    sl = resistance * Decimal("0.985")

    if sl >= close:
        sl = close * Decimal("0.985")

    risk = close - sl

    if risk <= 0:
        return None

    tp1 = close + (
        risk * Decimal("1.5")
    )

    tp2 = close + (
        risk * Decimal("2.5")
    )

    return {
        "symbol": symbol,
        "price": close,
        "score": score,
        "resistance": resistance,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "move": move_from_low,
        "breakout": breakout,
    }


# ============================================================
# ORDER QUANTITY
# ============================================================

def calculate_order_quantity(symbol, price):
    rules = MARKET_RULES.get(symbol)

    if not rules:
        return None, "NO MARKET RULES"

    if price <= 0:
        return None, "INVALID PRICE"

    step = rules["stepSize"]
    min_qty = rules["minQty"]
    max_qty = rules["maxQty"]
    min_notional = rules["minNotional"]

    if ORDER_USDT <= 0:
        return None, "ORDER_USDT <= 0"

    raw_qty = (
        ORDER_USDT / price
    )

    if step <= 0:
        qty = raw_qty
    else:
        qty = floor_to_step(
            raw_qty,
            step,
        )

    if qty <= 0:
        return None, (
            "quantity 0 after stepSize"
        )

    if qty < min_qty:
        return None, (
            "quantity "
            + decimal_to_string(qty)
            + " < minQty "
            + decimal_to_string(min_qty)
        )

    if max_qty > 0 and qty > max_qty:
        qty = floor_to_step(
            max_qty,
            step,
        )

    notional = qty * price

    if (
        min_notional > 0
        and notional < min_notional
    ):
        return None, (
            "order value "
            + decimal_to_string(notional)
            + " < MIN_NOTIONAL "
            + decimal_to_string(min_notional)
        )

    if qty <= 0:
        return None, "FINAL QUANTITY <= 0"

    return qty, None


# ============================================================
# REAL SPOT BUY
# ============================================================

def place_real_buy(symbol, price):
    global REAL_BUYS_THIS_RUN

    if not LIVE_TRADING:
        return {
            "ok": False,
            "locked": True,
            "error": "LIVE_TRADING=false",
        }

    if not AUTH_OK:
        return {
            "ok": False,
            "locked": True,
            "error": "AUTH NOT OK",
        }

    if not TRADING_OK:
        return {
            "ok": False,
            "locked": True,
            "error": "TRADING CHECK NOT OK",
        }

    if not REAL_BUY_UNLOCKED:
        return {
            "ok": False,
            "locked": True,
            "error": "REAL BUY LOCKED",
        }

    if REAL_BUYS_THIS_RUN >= MAX_REAL_BUYS_PER_RUN:
        return {
            "ok": False,
            "locked": True,
            "error": "MAX BUY PER RUN REACHED",
        }

    quantity, error = calculate_order_quantity(
        symbol,
        price,
    )

    if quantity is None:
        return {
            "ok": False,
            "locked": False,
            "error": error,
        }

    balance = get_usdt_balance()

    if balance < ORDER_USDT:
        return {
            "ok": False,
            "locked": False,
            "error": (
                "USDT balance "
                + decimal_to_string(balance)
                + " < order "
                + decimal_to_string(ORDER_USDT)
            ),
        }

    notify(
        "🚨 REAL BUY START "
        + VERSION
        + "\n\n"
        + "🪙 "
        + symbol
        + "\n"
        + "💰 PRICE: "
        + decimal_to_string(price)
        + "\n"
        + "💵 USDT: "
        + decimal_to_string(ORDER_USDT)
        + "\n"
        + "📦 QTY: "
        + decimal_to_string(quantity)
        + "\n"
        + "🛡 MAX BUY/RUN: 1"
    )

    # IMPORTANT:
    # Keep business parameters in deterministic insertion order.
    # timestamp and recvWindow are appended by build_signed_query().
    params = [
        ("symbol", symbol),
        ("side", "BUY"),
        ("type", "MARKET"),
        (
            "quantity",
            decimal_to_string(quantity),
        ),
    ]

    try:
        r = private_post(
            ORDER_PATH,
            params,
        )

        if r is None:
            return {
                "ok": False,
                "locked": False,
                "error": "NO ORDER RESPONSE",
            }

        text = r.text[:1200]

        try:
            data = r.json()
        except Exception:
            data = {}

        if r.status_code not in (
            200,
            201,
        ):
            code = ""

            if isinstance(data, dict):
                code = data.get(
                    "code",
                    "",
                )

            if (
                r.status_code == 401
                or str(code) == "1103"
            ):
                REAL_BUY_UNLOCKED = False

                notify(
                    "🚨 REAL BUY AUTH ERROR "
                    + VERSION
                    + "\n\n"
                    + "🪙 "
                    + symbol
                    + "\n"
                    + "❌ HTTP "
                    + str(r.status_code)
                    + "\n"
                    + "❌ CODE "
                    + str(code)
                    + "\n"
                    + "❌ Invalid Signature\n\n"
                    + "🛑 REAL BUY LOCKED\n"
                    + "🛑 NO RETRY THIS RUN"
                )

                return {
                    "ok": False,
                    "locked": True,
                    "error": (
                        "INVALID SIGNATURE"
                    ),
                }

            notify(
                "🚨 REAL TRADE ERROR "
                + VERSION
                + "\n\n"
                + "🪙 "
                + symbol
                + "\n"
                + "❌ HTTP "
                + str(r.status_code)
                + "\n"
                + "❌ "
                + text
            )

            return {
                "ok": False,
                "locked": False,
                "error": text,
            }

        # Some APIs return an error inside HTTP 200.
        if isinstance(data, dict):
            code = data.get("code")

            if code not in (
                None,
                0,
                "0",
            ):
                notify(
                    "🚨 REAL TRADE REJECTED "
                    + VERSION
                    + "\n\n"
                    + "🪙 "
                    + symbol
                    + "\n"
                    + "❌ CODE "
                    + str(code)
                    + "\n"
                    + "❌ "
                    + str(data)[:700]
                )

                return {
                    "ok": False,
                    "locked": False,
                    "error": str(data),
                }

        REAL_BUYS_THIS_RUN += 1

        order_id = ""

        if isinstance(data, dict):
            order_id = str(
                data.get(
                    "orderId",
                    data.get(
                        "id",
                        "",
                    ),
                )
            )

        notify(
            "✅ REAL BUY SUCCESS "
            + VERSION
            + "\n\n"
            + "🟢 "
            + symbol
            + "\n"
            + "💰 PRICE: "
            + decimal_to_string(price)
            + "\n"
            + "💵 USDT: "
            + decimal_to_string(ORDER_USDT)
            + "\n"
            + "📦 QTY: "
            + decimal_to_string(quantity)
            + "\n"
            + "🆔 ORDER: "
            + order_id
            + "\n\n"
            + "🛑 MAX BUY/RUN = 1"
        )

        return {
            "ok": True,
            "locked": False,
            "order_id": order_id,
            "quantity": quantity,
            "response": data,
        }

    except Exception as e:
        notify(
            "🚨 REAL ORDER EXCEPTION "
            + VERSION
            + "\n\n"
            + "🪙 "
            + symbol
            + "\n"
            + "❌ "
            + str(e)
        )

        return {
            "ok": False,
            "locked": False,
            "error": str(e),
        }


# ============================================================
# CANDIDATE SCANNER
# ============================================================

def get_usdt_symbols():
    symbols = []

    for symbol in MARKET_RULES:
        if not symbol.endswith("USDT"):
            continue

        if symbol in BLACKLIST:
            continue

        symbols.append(symbol)

    return sorted(symbols)


def score_candidate(symbol):
    trades = get_trades(symbol)

    if len(trades) < 100:
        return None

    candles = build_candles(trades)

    return calculate_signal(
        symbol,
        candles,
    )


def scan_markets():
    symbols = get_usdt_symbols()

    total = len(symbols)

    notify(
        "📊 ATI SCAN START "
        + VERSION
        + "\n\n"
        + "📊 USDT MARKETS: "
        + str(total)
        + "\n"
        + "⏱ TIMEFRAME: 5m\n"
        + "🕯 CLOSED CANDLE: YES\n"
        + "🎯 TOP CANDIDATES: 10\n"
        + (
            "🟢 REAL MODE: ON"
            if LIVE_TRADING
            else "🟡 PAPER MODE: ON"
        )
        + "\n"
        + "🕐 "
        + utc_now()
    )

    candidates = []

    checked = 0

    for symbol in symbols:
        checked += 1

        try:
            result = score_candidate(
                symbol
            )

            if result:
                candidates.append(
                    result
                )

        except Exception as e:
            log(
                "SCAN ERROR "
                + symbol
                + ": "
                + str(e)
            )

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["move"],
        ),
        reverse=True,
    )

    top = candidates[:10]

    notify(
        "📊 ATI SCAN FINISHED "
        + VERSION
        + "\n\n"
        + "📊 MARKETS: "
        + str(total)
        + "\n"
        + "📥 CHECKED: "
        + str(checked)
        + "\n"
        + "🟢 CANDIDATES: "
        + str(len(candidates))
        + "\n"
        + "🎯 TOP 10: "
        + str(len(top))
        + "\n"
        + "🚨 REAL BUY THIS RUN: "
        + str(REAL_BUYS_THIS_RUN)
    )

    return top


# ============================================================
# CANDIDATE MESSAGE
# ============================================================

def candidate_message(c):
    return (
        "🚨 ATI BUY CANDIDATE "
        + VERSION
        + "\n\n"
        + "🪙 "
        + c["symbol"]
        + "\n"
        + "💰 PRICE: "
        + decimal_to_string(c["price"])
        + "\n"
        + "📊 SCORE: "
        + str(c["score"])
        + "\n"
        + "📈 MOVE: "
        + decimal_to_string(c["move"])
        + "%\n"
        + "🔓 BREAKOUT: "
        + (
            "YES"
            if c["breakout"]
            else "HOLD"
        )
        + "\n"
        + "🛑 SL: "
        + decimal_to_string(c["sl"])
        + "\n"
        + "🎯 TP1: "
        + decimal_to_string(c["tp1"])
        + "\n"
        + "🎯 TP2: "
        + decimal_to_string(c["tp2"])
    )


# ============================================================
# MAIN
# ============================================================

def main():
    global AUTH_OK
    global TRADING_OK
    global REAL_BUY_UNLOCKED

    notify(
        "⚡ ATI CRYPTO BOT "
        + VERSION
        + "\n\n"
        + "📡 TABDEAL API: CONNECTING...\n"
        + "📊 SCAN: STARTING\n"
        + "⏱ TIMEFRAME: 5m\n"
        + "🕯 CLOSED CANDLE: YES\n"
        + "💵 ORDER MODE: FIXED USDT AMOUNT\n"
        + "💰 ORDER AMOUNT: "
        + decimal_to_string(ORDER_USDT)
        + " USDT\n"
        + (
            "🟢 REAL ORDERS: ENABLED"
            if LIVE_TRADING
            else "🟡 REAL ORDERS: DISABLED"
        )
        + "\n"
        + "🔐 AUTH VERSION: HMAC-SHA256 FIX\n"
        + "🕐 "
        + utc_now()
    )

    # --------------------------------------------------------
    # API KEY CHECK
    # --------------------------------------------------------

    if not API_KEY or not API_SECRET:
        notify(
            "🛑 ATI SAFE STOP "
            + VERSION
            + "\n\n"
            + "❌ TABDEAL API KEY/SECRET MISSING\n"
            + "🛑 REAL BUY LOCKED"
        )
        return

    # --------------------------------------------------------
    # EXCHANGE INFO
    # --------------------------------------------------------

    notify(
        "📡 TABDEAL API: CHECKING EXCHANGE INFO..."
    )

    info = get_exchange_info()

    if info is None:
        notify(
            "🛑 ATI SAFE STOP "
            + VERSION
            + "\n\n"
            + "❌ EXCHANGE INFO FAILED\n"
            + "🛑 REAL BUY LOCKED"
        )
        return

    parse_symbol_rules(info)

    notify(
        "✅ EXCHANGE INFO OK "
        + VERSION
        + "\n\n"
        + "📊 USDT MARKETS: "
        + str(
            len(MARKET_RULES)
        )
    )

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    if not authenticate_account():
        return

    # --------------------------------------------------------
    # TRADING CHECK
    # --------------------------------------------------------

    if not check_trading_access():
        return

    # --------------------------------------------------------
    # BALANCE
    # --------------------------------------------------------

    balance = get_usdt_balance()

    notify(
        "💰 USDT BALANCE CHECK "
        + VERSION
        + "\n\n"
        + "💵 AVAILABLE: "
        + decimal_to_string(balance)
        + " USDT\n"
        + "🧾 ORDER: "
        + decimal_to_string(ORDER_USDT)
        + " USDT"
    )

    if LIVE_TRADING and balance < ORDER_USDT:
        notify(
            "🛑 ATI SAFE STOP "
            + VERSION
            + "\n\n"
            + "❌ INSUFFICIENT USDT BALANCE\n"
            + "💰 AVAILABLE: "
            + decimal_to_string(balance)
            + "\n"
            + "💵 REQUIRED: "
            + decimal_to_string(ORDER_USDT)
            + "\n\n"
            + "🛑 REAL BUY LOCKED"
        )
        return

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    candidates = scan_markets()

    if not candidates:
        notify(
            "📭 ATI NO BUY CANDIDATE "
            + VERSION
            + "\n\n"
            + "No confirmed 5m breakout candidate.\n"
            + "🟢 Bot completed normally.\n"
            + "🛑 No order sent.\n"
            + "🕐 "
            + utc_now()
        )
        return

    # --------------------------------------------------------
    # SHOW TOP CANDIDATES
    # --------------------------------------------------------

    lines = [
        "🎯 ATI TOP CANDIDATES "
        + VERSION,
        "",
    ]

    for i, c in enumerate(
        candidates,
        start=1,
    ):
        lines.append(
            str(i)
            + ". "
            + c["symbol"]
            + " | SCORE "
            + str(c["score"])
            + " | "
            + decimal_to_string(
                c["price"]
            )
        )

    notify(
        "\n".join(lines)
    )

    # --------------------------------------------------------
    # REAL BUY
    # --------------------------------------------------------

    if not LIVE_TRADING:
        notify(
            "🟡 PAPER MODE "
            + VERSION
            + "\n\n"
            + "🛑 REAL BUY DISABLED\n"
            + "📌 No order was sent."
        )
        return

    if not REAL_BUY_UNLOCKED:
        notify(
            "🛑 ATI SAFE STOP "
            + VERSION
            + "\n\n"
            + "❌ REAL BUY IS LOCKED\n"
            + "🛑 NO ORDER WAS SENT"
        )
        return

    # Only first/top candidate is eligible.
    candidate = candidates[0]

    notify(
        candidate_message(
            candidate
        )
    )

    result = place_real_buy(
        candidate["symbol"],
        candidate["price"],
    )

    if not result.get("ok"):
        notify(
            "🛑 ATI BUY NOT EXECUTED "
            + VERSION
            + "\n\n"
            + "🪙 "
            + candidate["symbol"]
            + "\n"
            + "❌ "
            + str(
                result.get(
                    "error",
                    "UNKNOWN ERROR",
                )
            )
            + "\n"
            + "🛑 NO RETRY THIS RUN"
        )
        return

    notify(
        "🏁 ATI RUN COMPLETE "
        + VERSION
        + "\n\n"
        + "✅ REAL BUY COMPLETED\n"
        + "🪙 "
        + candidate["symbol"]
        + "\n"
        + "💵 "
        + decimal_to_string(
            ORDER_USDT
        )
        + " USDT\n"
        + "🛒 BUY COUNT: "
        + str(
            REAL_BUYS_THIS_RUN
        )
        + "/1\n"
        + "🕐 "
        + utc_now()
    )


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        notify(
            "🛑 ATI STOPPED "
            + VERSION
        )

    except Exception as e:
        AUTH_OK = False
        TRADING_OK = False
        REAL_BUY_UNLOCKED = False

        notify(
            "🚨 ATI FATAL ERROR "
            + VERSION
            + "\n\n"
            + str(e)
            + "\n\n"
            + "🛑 REAL BUY LOCKED"
        )

        raise
