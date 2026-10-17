import os
import time
import hmac
import hashlib
import math
import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from decimal import Decimal, ROUND_DOWN

import requests


# ============================================================
# ATI FUTURES V3.2
# TABDEAL FUTURES
#
# Strategy:
# MACD 12 / 26 / 9
# Timeframe: 5m
#
# IMPORTANT:
# - REAL_TRADING controls real orders.
# - If candle data is unavailable, NO ORDER is submitted.
# - Signature follows Tabdeal official Python SDK method.
# - Futures symbols are normalized: BTC_USDT -> BTCUSDT
# ============================================================

VERSION = "ATI FUTURES V3.2"

BASE_URL = os.getenv(
    "TABDEAL_BASE_URL",
    "https://api1.tabdeal.org"
).rstrip("/")

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()

REAL_TRADING = (
    os.getenv("REAL_TRADING", "false")
    .strip()
    .lower()
    == "true"
)

LEVERAGE = int(os.getenv("LEVERAGE", "3"))
MARGIN_USDT = float(os.getenv("MARGIN_USDT", "2"))

TP_PCT = float(os.getenv("TP_PCT", "0.02"))
SL_PCT = float(os.getenv("SL_PCT", "0.01"))

MAX_SYMBOLS = max(
    1,
    min(int(os.getenv("MAX_SYMBOLS", "30")), 75)
)

FAST = 12
SLOW = 26
SIGNAL = 9

TIMEOUT = 15

# We deliberately do not invent a candle endpoint.
KLINE_ROUTE = None

SESSION = requests.Session()

# Small clock offset correction.
SERVER_TIME_OFFSET_MS = 0


# ============================================================
# LOG
# ============================================================

def log(message):
    print(
        f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] "
        f"{message}",
        flush=True,
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TG_TOKEN or not TG_CHAT:
        log("Telegram credentials missing")
        return False

    try:
        response = SESSION.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={
                "chat_id": TG_CHAT,
                "text": str(message)[:4000],
            },
            timeout=TIMEOUT,
        )

        if not response.ok:
            log(
                f"TELEGRAM ERROR "
                f"{response.status_code}: "
                f"{response.text[:300]}"
            )
            return False

        return True

    except Exception as exc:
        log(f"TELEGRAM ERROR: {exc}")
        return False


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def normalize_futures_symbol(symbol):
    """
    Tabdeal exchangeInfo may return:
        BTC_USDT
        XAUT_USDT

    Futures trading API expects:
        BTCUSDT
        XAUTUSDT
    """

    return str(symbol or "").upper().replace("_", "")


def display_symbol(symbol):
    return str(symbol or "").upper()


# ============================================================
# PUBLIC REQUEST
# ============================================================

def public_get(path, params=None):
    response = SESSION.get(
        BASE_URL + path,
        params=params or {},
        timeout=TIMEOUT,
    )

    if not response.ok:
        raise RuntimeError(
            f"GET {response.url} -> "
            f"HTTP {response.status_code}: "
            f"{response.text[:400]}"
        )

    return response.json()


# ============================================================
# SERVER TIME
# ============================================================

def sync_server_time():
    global SERVER_TIME_OFFSET_MS

    routes = [
        "/r/fapi/v1/time",
        "/fapi/v1/time",
    ]

    for path in routes:
        try:
            before = int(time.time() * 1000)

            data = public_get(path)

            after = int(time.time() * 1000)

            server_time = int(
                data.get("serverTime")
                or data.get("time")
                or 0
            )

            if server_time <= 0:
                continue

            local_mid = (before + after) // 2

            SERVER_TIME_OFFSET_MS = (
                server_time - local_mid
            )

            log(
                f"Server time OK | "
                f"offset={SERVER_TIME_OFFSET_MS} ms"
            )

            return True

        except Exception as exc:
            log(f"Server time failed {path}: {exc}")

    SERVER_TIME_OFFSET_MS = 0
    log("Server time endpoint unavailable; offset=0")
    return False


def current_timestamp_ms():
    return int(time.time() * 1000) + SERVER_TIME_OFFSET_MS


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(method, path, params=None):
    """
    Signature implementation follows the official Tabdeal
    Python SDK pattern:

        data.update(timestamp)
        data.update(recvWindow)
        data_query = urlencode(data)
        signature = HMAC_SHA256(secret, data_query)
        data.update(signature)

    IMPORTANT:
    The exact same encoded parameter set is used for signing
    and sending.
    """

    if not API_KEY:
        raise RuntimeError("Missing TABDEAL_API_KEY")

    if not API_SECRET:
        raise RuntimeError("Missing TABDEAL_API_SECRET")

    data = dict(params or {})

    # Official SDK style timestamp.
    data["timestamp"] = current_timestamp_ms()

    # Tabdeal accepts receive windows up to 60000.
    data["recvWindow"] = 10000

    # EXACT string used for HMAC.
    data_query = urlencode(data)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        data_query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Signature is added AFTER signing.
    data["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY,
    }

    method = method.upper()
    url = BASE_URL + path

    if method == "GET":
        response = SESSION.get(
            url,
            params=data,
            headers=headers,
            timeout=TIMEOUT,
        )

    elif method == "POST":
        # Send dict exactly like official Tabdeal SDK.
        response = SESSION.post(
            url,
            data=data,
            headers=headers,
            timeout=TIMEOUT,
        )

    elif method == "DELETE":
        response = SESSION.delete(
            url,
            params=data,
            headers=headers,
            timeout=TIMEOUT,
        )

    else:
        raise ValueError(
            f"Unsupported method: {method}"
        )

    if not response.ok:
        raise RuntimeError(
            f"PRIVATE API HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    try:
        return response.json()

    except Exception:
        raise RuntimeError(
            f"PRIVATE API returned non-JSON: "
            f"{response.text[:500]}"
        )


# ============================================================
# MARKETS
# ============================================================

def discover_markets():
    data = public_get(
        "/r/fapi/v1/exchangeInfo"
    )

    items = (
        data.get("symbols", [])
        if isinstance(data, dict)
        else []
    )

    result = []

    for item in items:

        raw_symbol = str(
            item.get("symbol", "")
        ).upper()

        status = str(
            item.get("status", "")
        ).upper()

        quote = str(
            item.get("quoteAsset")
            or item.get("quoteCurrency")
            or ""
        ).upper()

        if not raw_symbol:
            continue

        normalized = normalize_futures_symbol(
            raw_symbol
        )

        if not normalized.endswith("USDT"):
            continue

        if status and status != "TRADING":
            continue

        if quote and quote != "USDT":
            continue

        # Keep original exchangeInfo item.
        # Add normalized futures symbol.
        item = dict(item)
        item["_raw_symbol"] = raw_symbol
        item["_futures_symbol"] = normalized

        result.append(item)

    if not result:
        raise RuntimeError(
            "No eligible USDT futures markets found"
        )

    return result[:MAX_SYMBOLS]


# ============================================================
# CANDLE PARSER
# ============================================================

def parse_candles(data):
    if not isinstance(data, list):
        return None

    if len(data) < 35:
        return None

    result = []

    for row in data:

        if not isinstance(row, (list, tuple)):
            return None

        if len(row) < 5:
            return None

        try:
            open_time = int(row[0])

            open_price = float(row[1])
            high = float(row[2])
            low = float(row[3])
            close = float(row[4])

            if len(row) > 6:
                close_time = int(row[6])
            else:
                close_time = (
                    open_time
                    + 300000
                    - 1
                )

            if min(
                open_price,
                high,
                low,
                close
            ) <= 0:
                return None

            result.append(
                {
                    "time": open_time,
                    "close_time": close_time,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                }
            )

        except (
            ValueError,
            TypeError,
            IndexError,
        ):
            return None

    return sorted(
        result,
        key=lambda item: item["time"]
    )


# ============================================================
# CANDLE ENDPOINT DISCOVERY
# ============================================================

def discover_kline_route(symbol):
    """
    We only accept a route if it actually returns valid
    5-minute candle data.

    No order is allowed before this succeeds.
    """

    global KLINE_ROUTE

    futures_symbol = normalize_futures_symbol(
        symbol
    )

    routes = [
        "/r/fapi/v1/klines",
        "/fapi/v1/klines",
        "/r/fapi/v1/candles",
        "/fapi/v1/candles",
    ]

    for path in routes:

        try:

            data = public_get(
                path,
                {
                    "symbol": futures_symbol,
                    "interval": "5m",
                    "limit": 100,
                },
            )

            candles = parse_candles(data)

            if candles:
                KLINE_ROUTE = path

                log(
                    f"Verified candle route: "
                    f"{path} | "
                    f"symbol={futures_symbol} | "
                    f"candles={len(candles)}"
                )

                return candles

            log(
                f"Invalid candle response "
                f"{path}"
            )

        except Exception as exc:

            log(
                f"Candle route failed "
                f"{path}: {exc}"
            )

    return None


def get_candles(symbol):

    if not KLINE_ROUTE:
        return discover_kline_route(
            symbol
        )

    futures_symbol = normalize_futures_symbol(
        symbol
    )

    try:

        data = public_get(
            KLINE_ROUTE,
            {
                "symbol": futures_symbol,
                "interval": "5m",
                "limit": 100,
            },
        )

        return parse_candles(data)

    except Exception as exc:

        log(
            f"CANDLE ERROR "
            f"{futures_symbol}: {exc}"
        )

        return None


# ============================================================
# EMA / MACD
# ============================================================

def ema(values, period):

    if len(values) < period:
        return []

    alpha = 2.0 / (period + 1)

    result = [
        sum(values[:period]) / period
    ]

    for value in values[period:]:
        result.append(
            result[-1]
            + alpha * (
                value - result[-1]
            )
        )

    return result


def macd_cross(closes):

    if len(closes) < 60:
        return None

    fast = ema(
        closes,
        FAST
    )

    slow = ema(
        closes,
        SLOW
    )

    if not fast or not slow:
        return None

    # Align EMA12 with EMA26.
    fast = fast[SLOW - FAST:]

    count = min(
        len(fast),
        len(slow)
    )

    macd = [
        fast[i] - slow[i]
        for i in range(count)
    ]

    signal = ema(
        macd,
        SIGNAL
    )

    if len(signal) < 2:
        return None

    aligned_macd = macd[
        SIGNAL - 1:
    ]

    if len(aligned_macd) < 2:
        return None

    previous_macd = aligned_macd[-2]
    current_macd = aligned_macd[-1]

    previous_signal = signal[-2]
    current_signal = signal[-1]

    if (
        previous_macd <= previous_signal
        and current_macd > current_signal
    ):
        return "BUY"

    if (
        previous_macd >= previous_signal
        and current_macd < current_signal
    ):
        return "SELL"

    return None


# ============================================================
# CLOSED CANDLES
# ============================================================

def closed_candles(candles):

    now_ms = int(
        time.time() * 1000
    )

    return [
        candle
        for candle in candles
        if candle["close_time"] < now_ms
    ]


# ============================================================
# FILTERS
# ============================================================

def get_filters(item):

    return {
        f.get("filterType"): f
        for f in item.get(
            "filters",
            []
        )
        if f.get("filterType")
    }


def decimals_for_step(step):

    value = (
        Decimal(str(step))
        .normalize()
    )

    return max(
        0,
        -value.as_tuple().exponent
    )


def round_down_step(value, step):

    value = Decimal(
        str(value)
    )

    step = Decimal(
        str(step)
    )

    if step <= 0:
        raise RuntimeError(
            "Invalid exchange step"
        )

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


def format_quantity(
    item,
    quantity
):

    filters = get_filters(item)

    lot = (
        filters.get(
            "MARKET_LOT_SIZE"
        )
        or filters.get(
            "LOT_SIZE"
        )
    )

    if not lot:
        raise RuntimeError(
            f"{item.get('symbol')}: "
            f"quantity filters missing"
        )

    step = Decimal(
        str(
            lot.get(
                "stepSize",
                "0"
            )
        )
    )

    minimum = Decimal(
        str(
            lot.get(
                "minQty",
                "0"
            )
        )
    )

    maximum = Decimal(
        str(
            lot.get(
                "maxQty",
                "0"
            )
        )
    )

    if step <= 0:
        raise RuntimeError(
            "Invalid quantity stepSize"
        )

    qty = round_down_step(
        quantity,
        step
    )

    if qty < minimum:
        raise RuntimeError(
            f"Quantity {qty} "
            f"below minimum {minimum}"
        )

    if (
        maximum > 0
        and qty > maximum
    ):
        raise RuntimeError(
            f"Quantity {qty} "
            f"above maximum {maximum}"
        )

    return f"{qty:.{decimals_for_step(step)}f}"


def format_price(
    item,
    price
):

    price_filter = get_filters(
        item
    ).get(
        "PRICE_FILTER"
    )

    if not price_filter:
        raise RuntimeError(
            f"{item.get('symbol')}: "
            f"PRICE_FILTER missing"
        )

    tick = Decimal(
        str(
            price_filter.get(
                "tickSize",
                "0"
            )
        )
    )

    if tick <= 0:
        raise RuntimeError(
            "Invalid tickSize"
        )

    value = round_down_step(
        price,
        tick
    )

    return f"{value:.{decimals_for_step(tick)}f}"


# ============================================================
# ORDER BOOK
# ============================================================

def get_mid_price(symbol):

    futures_symbol = normalize_futures_symbol(
        symbol
    )

    data = public_get(
        "/r/fapi/v1/depth",
        {
            "symbol": futures_symbol,
            "limit": 5,
        },
    )

    bids = data.get("bids") or []
    asks = data.get("asks") or []

    if not bids or not asks:
        raise RuntimeError(
            "Order book is empty"
        )

    bid = float(bids[0][0])
    ask = float(asks[0][0])

    if (
        bid <= 0
        or ask <= 0
        or ask < bid
    ):
        raise RuntimeError(
            "Invalid order book prices"
        )

    return (
        bid + ask
    ) / 2.0


# ============================================================
# POSITION
# ============================================================

def get_position(symbol):

    futures_symbol = normalize_futures_symbol(
        symbol
    )

    errors = []

    routes = [
        "/fapi/v1/positionRisk",
        "/fapi/v1/position",
    ]

    for path in routes:

        try:

            data = signed_request(
                "GET",
                path,
                {
                    "symbol":
                        futures_symbol
                },
            )

            positions = (
                data
                if isinstance(
                    data,
                    list
                )
                else [data]
            )

            for position in positions:

                if not isinstance(
                    position,
                    dict
                ):
                    continue

                found_symbol = normalize_futures_symbol(
                    position.get(
                        "symbol",
                        futures_symbol
                    )
                )

                if (
                    found_symbol
                    != futures_symbol
                ):
                    continue

                amount = float(
                    position.get(
                        "positionAmt"
                    )
                    or position.get(
                        "quantity"
                    )
                    or position.get(
                        "qty"
                    )
                    or 0
                )

                if abs(amount) > 0:
                    return position

            return None

        except Exception as exc:

            errors.append(
                f"{path}: {exc}"
            )

    raise RuntimeError(
        "Could not verify position: "
        + " | ".join(errors)
    )


# ============================================================
# LEVERAGE
# ============================================================

def set_leverage(symbol):

    futures_symbol = normalize_futures_symbol(
        symbol
    )

    return signed_request(
        "POST",
        "/fapi/v1/leverage",
        {
            "symbol":
                futures_symbol,
            "leverage":
                LEVERAGE,
        },
    )


# ============================================================
# MARKET ORDER
# ============================================================

def market_order(
    symbol,
    side,
    quantity
):

    futures_symbol = normalize_futures_symbol(
        symbol
    )

    return signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol":
                futures_symbol,
            "side":
                side,
            "type":
                "MARKET",
            "quantity":
                quantity,
        },
    )


# ============================================================
# PROTECTIVE ORDER
# ============================================================

def protective_order(
    symbol,
    side,
    order_type,
    quantity,
    stop_price
):

    futures_symbol = normalize_futures_symbol(
        symbol
    )

    return signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol":
                futures_symbol,
            "side":
                side,
            "type":
                order_type,
            "quantity":
                quantity,
            "stopPrice":
                stop_price,
            "reduceOnly":
                "true",
            "workingType":
                "MARK_PRICE",
        },
    )


# ============================================================
# STATE
# ============================================================

def save_record(record):

    path = (
        "ati_futures_state.json"
    )

    state = {}

    try:

        if os.path.exists(path):

            with open(
                path,
                "r",
                encoding="utf-8"
            ) as file:

                loaded = json.load(
                    file
                )

                if isinstance(
                    loaded,
                    dict
                ):
                    state = loaded

    except Exception as exc:

        log(
            f"State read error: "
            f"{exc}"
        )

    state.update(record)

    try:

        with open(
            path,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                state,
                file,
                ensure_ascii=False,
                indent=2,
            )

    except Exception as exc:

        log(
            f"State write error: "
            f"{exc}"
        )


def get_last_signal_key():

    try:

        with open(
            "ati_futures_state.json",
            "r",
            encoding="utf-8"
        ) as file:

            state = json.load(
                file
            )

            if isinstance(
                state,
                dict
            ):
                return state.get(
                    "last_signal_key"
                )

    except (
        OSError,
        ValueError
    ):
        pass

    return None


# ============================================================
# REAL TRADE
# ============================================================

def execute_trade(
    item,
    signal,
    price,
    candle_time
):

    raw_symbol = str(
        item.get(
            "_raw_symbol",
            item.get(
                "symbol",
                ""
            )
        )
    ).upper()

    symbol = normalize_futures_symbol(
        raw_symbol
    )

    # PAPER
    if not REAL_TRADING:

        telegram(
            f"🟡 ATI PAPER SIGNAL\n\n"
            f"Symbol: {raw_symbol}\n"
            f"API Symbol: {symbol}\n"
            f"Signal: {signal}\n"
            f"Price: {price}\n"
            f"MACD: 12/26/9\n"
            f"Timeframe: 5m"
        )

        return

    if not API_KEY:
        raise RuntimeError(
            "Missing API credentials"
        )

    if not API_SECRET:
        raise RuntimeError(
            "Missing API credentials"
        )

    # NEVER trade if position cannot be checked.
    position = get_position(
        symbol
    )

    if position:
        log(
            f"{symbol}: existing "
            f"position; skip"
        )
        return

    quantity = format_quantity(
        item,
        (
            MARGIN_USDT
            * LEVERAGE
            / price
        ),
    )

    log(
        f"{symbol}: REAL order "
        f"pre-check passed | "
        f"side={signal} | "
        f"qty={quantity}"
    )

    set_leverage(
        symbol
    )

    side = (
        "BUY"
        if signal == "BUY"
        else "SELL"
    )

    exit_side = (
        "SELL"
        if side == "BUY"
        else "BUY"
    )

    # ========================================================
    # REAL MARKET ORDER
    # ========================================================

    order = market_order(
        symbol,
        side,
        quantity
    )

    if not isinstance(
        order,
        dict
    ):
        raise RuntimeError(
            "Unexpected market "
            "order response"
        )

    order_id = order.get(
        "orderId"
    )

    fill_price = float(
        order.get(
            "avgPrice"
        )
        or order.get(
            "averagePrice"
        )
        or order.get(
            "price"
        )
        or price
    )

    if fill_price <= 0:
        raise RuntimeError(
            "Invalid order fill price"
        )

    tp_price = (
        fill_price
        * (
            1 + TP_PCT
            if side == "BUY"
            else 1 - TP_PCT
        )
    )

    sl_price = (
        fill_price
        * (
            1 - SL_PCT
            if side == "BUY"
            else 1 + SL_PCT
        )
    )

    tp_formatted = format_price(
        item,
        tp_price
    )

    sl_formatted = format_price(
        item,
        sl_price
    )

    try:

        tp_order = protective_order(
            symbol,
            exit_side,
            "TAKE_PROFIT_MARKET",
            quantity,
            tp_formatted,
        )

        sl_order = protective_order(
            symbol,
            exit_side,
            "STOP_MARKET",
            quantity,
            sl_formatted,
        )

    except Exception as exc:

        log(
            f"PROTECTIVE ORDER FAILURE "
            f"{symbol}: {exc}"
        )

        telegram(
            f"🚨 PROTECTIVE ORDER FAILURE\n"
            f"Symbol: {raw_symbol}\n"
            f"Entry order ID: {order_id}\n"
            f"Error: {exc}\n"
            f"CHECK POSITION IMMEDIATELY."
        )

        raise

    save_record(
        {
            "last_trade": {
                "symbol":
                    raw_symbol,
                "api_symbol":
                    symbol,
                "side":
                    signal,
                "quantity":
                    quantity,
                "entry":
                    fill_price,
                "order_id":
                    order_id,
                "tp_order_id":
                    tp_order.get(
                        "orderId"
                    ),
                "sl_order_id":
                    sl_order.get(
                        "orderId"
                    ),
                "candle_time":
                    candle_time,
                "time":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),
            }
        }
    )

    telegram(
        f"🔴 ATI REAL TRADE\n\n"
        f"Symbol: {raw_symbol}\n"
        f"API Symbol: {symbol}\n"
        f"Side: {signal}\n"
        f"Entry: {fill_price}\n"
        f"Quantity: {quantity}\n"
        f"Leverage: {LEVERAGE}x\n"
        f"Margin: {MARGIN_USDT} USDT\n"
        f"TP: {tp_formatted}\n"
        f"SL: {sl_formatted}\n"
        f"Entry order ID: {order_id}\n"
        f"TP order ID: "
        f"{tp_order.get('orderId')}\n"
        f"SL order ID: "
        f"{sl_order.get('orderId')}"
    )


# ============================================================
# ANALYZE
# ============================================================

def analyze_market(item):

    raw_symbol = str(
        item.get(
            "_raw_symbol",
            item.get(
                "symbol",
                ""
            )
        )
    ).upper()

    symbol = normalize_futures_symbol(
        raw_symbol
    )

    candles = get_candles(
        symbol
    )

    if not candles:

        log(
            f"{raw_symbol}: "
            f"no valid candles"
        )

        return False

    closed = closed_candles(
        candles
    )

    if len(closed) < 60:

        log(
            f"{raw_symbol}: only "
            f"{len(closed)} closed candles"
        )

        return False

    closes = [
        c["close"]
        for c in closed
    ]

    signal = macd_cross(
        closes
    )

    if not signal:
        return True

    latest = closed[-1]

    key = (
        f"{symbol}:"
        f"{latest['time']}:"
        f"{signal}"
    )

    if (
        get_last_signal_key()
        == key
    ):
        log(
            f"{raw_symbol}: "
            f"duplicate signal"
        )
        return True

    log(
        f"MACD SIGNAL | "
        f"{raw_symbol} | "
        f"{signal} | "
        f"close={latest['close']}"
    )

    execute_trade(
        item,
        signal,
        latest["close"],
        latest["time"],
    )

    save_record(
        {
            "last_signal_key":
                key
        }
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    log("=" * 60)
    log(VERSION)
    log(
        f"Mode: "
        f"{'REAL' if REAL_TRADING else 'PAPER'}"
    )
    log(
        f"MACD: "
        f"{FAST}/{SLOW}/{SIGNAL}"
    )
    log(
        "Timeframe: 5m"
    )
    log(
        f"Leverage: {LEVERAGE}x"
    )
    log(
        f"Margin: {MARGIN_USDT} USDT"
    )
    log(
        f"TP: {TP_PCT}"
    )
    log(
        f"SL: {SL_PCT}"
    )

    telegram(
        f"🤖 {VERSION}\n"
        f"Mode: "
        f"{'🔴 REAL' if REAL_TRADING else '🟡 PAPER'}\n"
        f"MACD: 12/26/9\n"
        f"Timeframe: 5m\n"
        f"Leverage: {LEVERAGE}x\n"
        f"Margin: {MARGIN_USDT} USDT"
    )

    # ========================================================
    # SERVER TIME
    # ========================================================

    sync_server_time()

    # ========================================================
    # MARKET DISCOVERY
    # ========================================================

    markets = discover_markets()

    log(
        f"Markets found: "
        f"{len(markets)}"
    )

    if markets:

        examples = [
            (
                item.get(
                    "_raw_symbol",
                    item.get(
                        "symbol",
                        ""
                    )
                )
            )
            for item in markets[:5]
        ]

        log(
            "Examples: "
            + ", ".join(examples)
        )

    # ========================================================
    # CANDLE ROUTE
    # ========================================================

    for item in markets:

        raw_symbol = str(
            item.get(
                "_raw_symbol",
                item.get(
                    "symbol",
                    ""
                )
            )
        ).upper()

        if discover_kline_route(
            raw_symbol
        ):
            break

    # ========================================================
    # ABSOLUTE SAFETY:
    # NO CANDLE = NO TRADE
    # ========================================================

    if not KLINE_ROUTE:

        message = (
            "🚨 ATI FUTURES\n\n"
            "No working candle "
            "endpoint found.\n\n"
            "NO REAL ORDER WAS "
            "SUBMITTED."
        )

        log(message)
        telegram(message)

        return

    log(
        f"Using candle route: "
        f"{KLINE_ROUTE}"
    )

    # ========================================================
    # SCAN
    # ========================================================

    processed = 0
    signals = 0
    errors = 0

    for item in markets:

        try:

            success = analyze_market(
                item
            )

            if success:
                processed += 1

        except Exception as exc:

            errors += 1

            log(
                f"MARKET ERROR "
                f"{item.get('symbol')}: "
                f"{exc}"
            )

            # Do not stop the whole scan.
            continue

        time.sleep(0.2)

    log(
        f"Scan complete | "
        f"markets={len(markets)} | "
        f"processed={processed} | "
        f"errors={errors}"
    )

    telegram(
        f"📊 ATI FUTURES SCAN\n\n"
        f"Version: {VERSION}\n"
        f"Markets: {len(markets)}\n"
        f"Processed: {processed}\n"
        f"Errors: {errors}\n"
        f"Candle route: "
        f"{KLINE_ROUTE}\n"
        f"Mode: "
        f"{'🔴 REAL' if REAL_TRADING else '🟡 PAPER'}"
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        log(
            f"FATAL ERROR: {exc}"
        )

        telegram(
            f"🚨 {VERSION} FATAL ERROR\n"
            f"{exc}"
        )

        raise
