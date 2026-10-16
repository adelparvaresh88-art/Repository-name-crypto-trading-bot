# main.py
# ATI FUTURES V3
# Tabdeal Futures | MACD 12/26/9 | 5m

import os
import time
import hmac
import hashlib
import math
import json
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

VERSION = "ATI FUTURES V3"

BASE_URL = os.getenv(
    "TABDEAL_BASE_URL",
    "https://api1.tabdeal.org"
).rstrip("/")

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()

REAL_TRADING = (
    os.getenv("REAL_TRADING", "false").strip().lower() == "true"
)

LEVERAGE = int(os.getenv("LEVERAGE", "3"))
MARGIN_USDT = float(os.getenv("MARGIN_USDT", "2"))
TP_PCT = float(os.getenv("TP_PCT", "0.02"))
SL_PCT = float(os.getenv("SL_PCT", "0.01"))
MAX_SYMBOLS = int(os.getenv("MAX_SYMBOLS", "30"))

FAST = 12
SLOW = 26
SIGNAL = 9
INTERVAL = "5m"
TIMEOUT = 15
RECV_WINDOW = 10000

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": VERSION})

KLINE_ROUTE = None
MARKETS = []


def log(message):
    print(
        f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] "
        f"{message}",
        flush=True
    )


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
            log(f"TELEGRAM ERROR: {response.status_code} {response.text[:300]}")
            return False

        return True

    except Exception as exc:
        log(f"TELEGRAM ERROR: {exc}")
        return False


def request_json(method, url, params=None, headers=None):
    response = SESSION.request(
        method,
        url,
        params=params,
        headers=headers,
        timeout=TIMEOUT,
    )

    if not response.ok:
        raise RuntimeError(
            f"HTTP {response.status_code}: {response.text[:400]}"
        )

    try:
        return response.json()
    except ValueError:
        raise RuntimeError("API returned invalid JSON")


def public_get(path, params=None):
    return request_json(
        "GET",
        BASE_URL + path,
        params=params,
    )


def signed_request(method, path, params=None):
    if not API_KEY or not API_SECRET:
        raise RuntimeError("Missing Tabdeal API credentials")

    values = dict(params or {})
    values["timestamp"] = int(time.time() * 1000)
    values["recvWindow"] = RECV_WINDOW

    query = urlencode(values)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    signed_query = query + "&signature=" + signature

    headers = {"X-MBX-APIKEY": API_KEY}
    url = BASE_URL + path

    if method.upper() == "GET":
        response = SESSION.get(
            url + "?" + signed_query,
            headers=headers,
            timeout=TIMEOUT,
        )

    elif method.upper() == "DELETE":
        response = SESSION.delete(
            url + "?" + signed_query,
            headers=headers,
            timeout=TIMEOUT,
        )

    elif method.upper() == "POST":
        response = SESSION.post(
            url,
            data=signed_query,
            headers={
                **headers,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=TIMEOUT,
        )

    else:
        raise ValueError("Unsupported HTTP method")

    if not response.ok:
        raise RuntimeError(
            f"PRIVATE API HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    try:
        return response.json()
    except ValueError:
        return {"response": response.text}


def discover_markets():
    data = public_get("/r/fapi/v1/exchangeInfo")

    if not isinstance(data, dict):
        raise RuntimeError("Invalid exchangeInfo response")

    items = data.get("symbols", [])
    if not isinstance(items, list):
        raise RuntimeError("exchangeInfo symbols missing")

    result = []

    for item in items:
        symbol = str(item.get("symbol", "")).upper()
        status = str(item.get("status", "")).upper()
        quote = str(
            item.get("quoteAsset")
            or item.get("quoteCurrency")
            or ""
        ).upper()

        if not symbol:
            continue

        if status and status != "TRADING":
            continue

        if quote and quote != "USDT":
            continue

        if not symbol.endswith("USDT"):
            continue

        result.append(item)

    if not result:
        raise RuntimeError("No tradable USDT futures markets")

    return result[:MAX_SYMBOLS]


def parse_kline_response(data):
    if not isinstance(data, list) or len(data) < 35:
        return None

    parsed = []

    for row in data:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
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
                close_time = open_time + 300000 - 1

            if min(open_price, high, low, close) <= 0:
                return None

            parsed.append({
                "time": open_time,
                "close_time": close_time,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
            })

        except (ValueError, TypeError, IndexError):
            return None

    return sorted(parsed, key=lambda candle: candle["time"])


def discover_kline_route(symbol):
    global KLINE_ROUTE

    candidates = [
        "/r/fapi/v1/klines",
        "/fapi/v1/klines",
        "/r/api/v1/klines",
        "/api/v1/klines",
        "/r/fapi/v1/candles",
        "/fapi/v1/candles",
    ]

    for path in candidates:
        try:
            data = public_get(
                path,
                {
                    "symbol": symbol,
                    "interval": INTERVAL,
                    "limit": 100,
                },
            )

            candles = parse_kline_response(data)

            if candles and len(candles) >= 35:
                KLINE_ROUTE = path
                log(f"KLINE ROUTE VERIFIED: {path}")
                return candles

            log(f"KLINE FORMAT NOT RECOGNIZED: {path}")

        except Exception as exc:
            log(f"KLINE TEST FAILED {path}: {exc}")

    return None


def get_candles(symbol):
    global KLINE_ROUTE

    if not KLINE_ROUTE:
        return discover_kline_route(symbol)

    try:
        data = public_get(
            KLINE_ROUTE,
            {
                "symbol": symbol,
                "interval": INTERVAL,
                "limit": 100,
            },
        )

        return parse_kline_response(data)

    except Exception as exc:
        log(f"KLINE ERROR {symbol}: {exc}")
        return None


def closed_candles(candles):
    now_ms = int(time.time() * 1000)

    return [
        candle for candle in candles
        if candle["close_time"] < now_ms
    ]


def ema(values, period):
    if len(values) < period:
        return []

    alpha = 2.0 / (period + 1.0)

    result = [sum(values[:period]) / period]

    for value in values[period:]:
        result.append(
            result[-1] + alpha * (value - result[-1])
        )

    return result


def calculate_macd(closes):
    if len(closes) < 60:
        return None

    fast_ema = ema(closes, FAST)
    slow_ema = ema(closes, SLOW)

    offset = SLOW - FAST
    fast_ema = fast_ema[offset:]

    count = min(len(fast_ema), len(slow_ema))

    macd_line = [
        fast_ema[index] - slow_ema[index]
        for index in range(count)
    ]

    if len(macd_line) < SIGNAL + 2:
        return None

    signal_line = ema(macd_line, SIGNAL)

    # EMA signal begins at macd_line index SIGNAL-1.
    aligned_macd = macd_line[SIGNAL - 1:]

    if len(aligned_macd) != len(signal_line):
        return None

    previous_macd = aligned_macd[-2]
    current_macd = aligned_macd[-1]

    previous_signal = signal_line[-2]
    current_signal = signal_line[-1]

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


def get_symbol_filters(item):
    filters = {}

    for entry in item.get("filters", []):
        filter_type = entry.get("filterType")
        if filter_type:
            filters[filter_type] = entry

    return filters


def decimal_places(step):
    step = Decimal(str(step)).normalize()
    return max(0, -step.as_tuple().exponent)


def floor_to_step(value, step):
    value = Decimal(str(value))
    step = Decimal(str(step))

    if step <= 0:
        raise ValueError("Invalid quantity step")

    units = (value / step).to_integral_value(
        rounding=ROUND_DOWN
    )

    return units * step


def format_quantity(item, quantity):
    filters = get_symbol_filters(item)

    lot = filters.get("LOT_SIZE") or filters.get("MARKET_LOT_SIZE")

    if not lot:
        raise RuntimeError(
            f"{item.get('symbol')}: quantity filters missing"
        )

    step = Decimal(str(lot.get("stepSize", "0")))
    minimum = Decimal(str(lot.get("minQty", "0")))
    maximum = Decimal(str(lot.get("maxQty", "0")))

    if step <= 0:
        raise RuntimeError("Invalid quantity stepSize")

    qty = floor_to_step(quantity, step)

    if qty < minimum:
        raise RuntimeError(
            f"Quantity {qty} below exchange minimum {minimum}"
        )

    if maximum > 0 and qty > maximum:
        raise RuntimeError(
            f"Quantity {qty} above exchange maximum {maximum}"
        )

    return f"{qty:.{decimal_places(step)}f}"


def get_mid_price(symbol):
    data = public_get(
        "/r/fapi/v1/depth",
        {
            "symbol": symbol,
            "limit": 5,
        },
    )

    bids = data.get("bids") or []
    asks = data.get("asks") or []

    if not bids or not asks:
        raise RuntimeError("Order book is empty")

    bid = float(bids[0][0])
    ask = float(asks[0][0])

    if bid <= 0 or ask <= 0 or ask < bid:
        raise RuntimeError("Invalid order book prices")

    return (bid + ask) / 2.0


def get_position(symbol):
    paths = [
        "/fapi/v1/positionRisk",
        "/fapi/v1/position",
    ]

    errors = []

    for path in paths:
        try:
            data = signed_request(
                "GET",
                path,
                {"symbol": symbol},
            )

            if isinstance(data, list):
                matching = [
                    position for position in data
                    if str(position.get("symbol", "")).upper() == symbol
                ]

                for position in matching:
                    amount = float(
                        position.get("positionAmt")
                        or position.get("quantity")
                        or position.get("qty")
                        or 0
                    )

                    if abs(amount) > 0:
                        return position

                return None

            if isinstance(data, dict):
                amount = float(
                    data.get("positionAmt")
                    or data.get("quantity")
                    or data.get("qty")
                    or 0
                )

                if abs(amount) > 0:
                    return data

                if any(
                    key in data
                    for key in ("positionAmt", "quantity", "qty")
                ):
                    return None

            errors.append(f"{path}: unexpected response")

        except Exception as exc:
            errors.append(f"{path}: {exc}")

    raise RuntimeError(
        "Cannot verify existing position: " + " | ".join(errors)
    )


def set_leverage(symbol):
    return signed_request(
        "POST",
        "/fapi/v1/leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE,
        },
    )


def market_order(symbol, side, quantity):
    return signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        },
    )


def protective_order(symbol, side, order_type, quantity, stop_price):
    return signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": symbol,
            "side": side,
            "type": order_type,
