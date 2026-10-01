import os
import json
import time
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.13
# REAL SPOT BUY
# FIXED USDT AMOUNT = 0.50 USDT
# QUANTITY = USDT / LIVE PRICE
# MIN_NOTIONAL / MIN_QTY / STEP_SIZE PROTECTION
# FILLED CHECK -> OCO TP/SL
# ============================================================

VERSION = "V40.2.13"

BASE_URL = "https://api1.tabdeal.org"

EXCHANGE_INFO_PATH = "/r/api/v1/exchangeInfo"
TRADES_PATH = "/r/api/v1/trades"

ORDER_PATH = "/api/v1/order"
ORDER_QUERY_PATH = "/r/api/v1/order"

OCO_PATH = "/api/v1/order/oco"

REQUEST_TIMEOUT = 15

MAX_REAL_BUYS_PER_RUN = 1

HEARTBEAT_MINUTES = 5

HISTORY_FILE = "paper_history.json"

# ============================================================
# FIXED ORDER AMOUNT
# ============================================================

# V40.2.13:
# The bot uses ONLY this fixed USDT amount.
# ORDER_QTY is intentionally NOT used anymore.
FIXED_ORDER_USDT = Decimal("0.50")


# ============================================================
# STRATEGY
# ============================================================

MIN_CONFIRMED_SCORE = 10
MIN_CONFIRMED_PRESSURE = 58.0

MIN_EARLY_SCORE = 9
MIN_EARLY_PRESSURE = 60.0

MIN_WATCH_SCORE = 6

MAX_RISK_PERCENT = 1.20

TP1_R = 1.67
TP2_R = 2.67

TOP_CANDIDATES = 100
TOP_DISPLAY = 10


# ============================================================
# API / ENV
# ============================================================

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "")
    .strip()
    .lower()
    == "true"
)

REAL_TRADING_CONFIRM = (
    os.getenv("REAL_TRADING_CONFIRM", "")
    .strip()
    .upper()
    == "YES"
)

REAL_ORDERS = (
    LIVE_TRADING
    and REAL_TRADING_CONFIRM
)


# ============================================================
# DECIMAL HELPERS
# ============================================================

D = Decimal


def dec(value, default="0"):
    try:
        if value is None:
            return D(default)

        return D(str(value))

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ):
        return D(default)


def floor_step(value, step):
    value = dec(value)
    step = dec(step)

    if value <= 0 or step <= 0:
        return D("0")

    units = (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    )

    return units * step


def decimal_to_string(value):
    value = dec(value)

    if value == 0:
        return "0"

    text = format(
        value,
        "f",
    )

    if "." in text:
        text = (
            text
            .rstrip("0")
            .rstrip(".")
        )

    return text


def utc_now():
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):
        print(
            "TELEGRAM: NOT CONFIGURED"
        )
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
        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            return True

        print(
            "TELEGRAM ERROR:",
            response.status_code,
            response.text[:500],
        )

    except Exception as exc:
        print(
            "TELEGRAM EXCEPTION:",
            exc,
        )

    return False


# ============================================================
# GENERIC API
# ============================================================

session = requests.Session()


def public_get(
    path,
    params=None,
):
    url = BASE_URL + path

    response = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


def signed_request(
    method,
    path,
    params=None,
):
    if (
        not API_KEY
        or not API_SECRET
    ):
        raise RuntimeError(
            "TABDEAL_API_KEY_OR_SECRET_MISSING"
        )

    params = dict(
        params or {}
    )

    params["timestamp"] = int(
        time.time() * 1000
    )

    query = "&".join(
        f"{k}={params[k]}"
        for k in sorted(params)
        if params[k] is not None
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()

    params["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY,
    }

    url = BASE_URL + path

    method = method.upper()

    if method == "GET":
        response = session.get(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    elif method == "POST":
        response = session.post(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    else:
        raise RuntimeError(
            "UNSUPPORTED_HTTP_METHOD"
        )

    try:
        data = response.json()

    except Exception:
        data = response.text

    if not response.ok:
        raise RuntimeError(
            f"HTTP_{response.status_code}: {data}"
        )

    return data


# ============================================================
# RESPONSE HELPERS
# ============================================================

def unwrap_list(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in (
            "data",
            "result",
            "items",
            "symbols",
            "markets",
        ):

            value = data.get(key)

            if isinstance(value, list):
                return value

    return []


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():
    return public_get(
        EXCHANGE_INFO_PATH
    )


def normalize_symbol(value):
    return (
        str(value or "")
        .upper()
        .replace("/", "")
    )


def market_filters(symbol_info):

    filters = {}

    raw_filters = symbol_info.get(
        "filters",
        []
    )

    if isinstance(
        raw_filters,
        dict,
    ):
        raw_filters = list(
            raw_filters.values()
        )

    for item in raw_filters:

        if not isinstance(
            item,
            dict,
        ):
            continue

        filter_type = str(
            item.get(
                "filterType"
            )
            or item.get("type")
            or ""
        ).upper()

        if filter_type:
            filters[
                filter_type
            ] = item

    # --------------------------------------------------------
    # LOT SIZE
    # --------------------------------------------------------

    lot = filters.get(
        "LOT_SIZE",
        {}
    )

    market_lot = filters.get(
        "MARKET_LOT_SIZE",
        {}
    )

    step_size = dec(
        market_lot.get(
            "stepSize"
        ),
        "0",
    )

    if step_size <= 0:

        step_size = dec(
            lot.get("stepSize"),
            "0",
        )

    min_qty = dec(
        market_lot.get(
            "minQty"
        ),
        "0",
    )

    if min_qty <= 0:

        min_qty = dec(
            lot.get("minQty"),
            "0",
        )

    max_qty = dec(
        market_lot.get(
            "maxQty"
        ),
        "0",
    )

    if max_qty <= 0:

        max_qty = dec(
            lot.get("maxQty"),
            "0",
        )

    # --------------------------------------------------------
    # MIN NOTIONAL
    # --------------------------------------------------------

    min_notional = D("0")

    mn = filters.get(
        "MIN_NOTIONAL",
        {}
    )

    min_notional = dec(
        mn.get("minNotional")
        or mn.get("notional")
        or mn.get("min_notional"),
        "0",
    )

    nt = filters.get(
        "NOTIONAL",
        {}
    )

    notional_value = dec(
        nt.get("minNotional")
        or nt.get("notional")
        or nt.get("min_notional"),
        "0",
    )

    if (
        notional_value
        > min_notional
    ):
        min_notional = (
            notional_value
        )

    # --------------------------------------------------------
    # PRICE FILTER
    # --------------------------------------------------------

    price_filter = filters.get(
        "PRICE_FILTER",
        {}
    )

    tick_size = dec(
        price_filter.get(
            "tickSize"
        ),
        "0",
    )

    # --------------------------------------------------------
    # OCO
    # --------------------------------------------------------

    oco_allowed = bool(
        symbol_info.get(
            "ocoAllowed",
            True,
        )
    )

    return {
        "stepSize": step_size,
        "minQty": min_qty,
        "maxQty": max_qty,
        "minNotional": min_notional,
        "tickSize": tick_size,
        "ocoAllowed": oco_allowed,
    }


# ============================================================
# SYMBOL MAP
# ============================================================

def build_symbol_map(
    exchange_info
):
    result = {}

    symbols = unwrap_list(
        exchange_info
    )

    for item in symbols:

        if not isinstance(
            item,
            dict,
        ):
            continue

        symbol = normalize_symbol(
            item.get("symbol")
            or item.get("market")
            or item.get(
                "baseAssetSymbol"
            )
        )

        if not symbol:
            continue

        status = str(
            item.get(
                "status",
                "TRADING",
            )
        ).upper()

        if status not in (
            "TRADING",
            "ENABLED",
            "ACTIVE",
        ):
            continue

        quote = str(
            item.get("quoteAsset")
            or item.get("quote")
            or ""
        ).upper()

        if (
            quote
            and quote != "USDT"
        ):
            continue

        if (
            not quote
            and not symbol.endswith(
                "USDT"
            )
        ):
            continue

        result[symbol] = item

    return result


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):

    data = public_get(
        TRADES_PATH,
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )

    return unwrap_list(data)


def trade_price(item):

    if not isinstance(
        item,
        dict,
    ):
        return D("0")

    return dec(
        item.get("price")
        or item.get("p")
        or item.get("rate"),
        "0",
    )


def trade_qty(item):

    if not isinstance(
        item,
        dict,
    ):
        return D("0")

    return dec(
        item.get("qty")
        or item.get("quantity")
        or item.get("q")
        or item.get("amount"),
        "0",
    )


def trade_time(
    item,
    fallback,
):

    if not isinstance(
        item,
        dict,
    ):
        return fallback

    raw = (
        item.get("time")
        or item.get("timestamp")
        or item.get("T")
        or item.get("date")
    )

    try:
        return int(raw)

    except Exception:
        return fallback


def build_5m_candles(
    trades
):

    buckets = {}

    for index, item in enumerate(
        trades
    ):

        price = trade_price(
            item
        )

        qty = trade_qty(
            item
        )

        if price <= 0:
            continue

        timestamp = trade_time(
            item,
            index,
        )

        if timestamp > 10_000_000_000:
            timestamp //= 1000

        bucket = (
            timestamp // 300
        ) * 300

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": D("0"),
                "buy_volume": D("0"),
                "sell_volume": D("0"),
            }

        candle = buckets[
            bucket
        ]

        candle["high"] = max(
            candle["high"],
            price,
        )

        candle["low"] = min(
            candle["low"],
            price,
        )

        candle["close"] = price

        candle["volume"] += qty

        side = str(
            item.get("side")
            or item.get("S")
            or ""
        ).upper()

        is_buyer_maker = item.get(
            "isBuyerMaker"
        )

        if side == "BUY":

            candle[
                "buy_volume"
            ] += qty

        elif side == "SELL":

            candle[
                "sell_volume"
            ] += qty

        elif is_buyer_maker is True:

            candle[
                "sell_volume"
            ] += qty

        elif is_buyer_maker is False:

            candle[
                "buy_volume"
            ] += qty

    candles = [
        buckets[key]
        for key in sorted(
            buckets
        )
    ]

    # Remove unfinished current candle.
    if len(candles) > 2:
        candles = candles[:-1]

    return candles


# ============================================================
# STRATEGY
# ============================================================

def pct_change(
    a,
    b,
):

    a = dec(a)
    b = dec(b)

    if a <= 0:
        return D("0")

    return (
        (b - a)
        / a
    ) * D("100")


def calculate_pressure(
    candles
):

    if not candles:
        return D("50")

    recent = candles[-6:]

    buy = sum(
        (
            x["buy_volume"]
            for x in recent
        ),
        D("0"),
    )

    sell = sum(
        (
            x["sell_volume"]
            for x in recent
        ),
        D("0"),
    )

    total = buy + sell

    if total <= 0:
        return D("50")

    return (
        buy / total
    ) * D("100")


def calculate_score(
    candles
):

    if len(candles) < 8:
        return 0, []

    last = candles[-1]
    prev = candles[-2]

    score = 0
    reasons = []

    move_3 = pct_change(
        candles[-4]["close"],
        last["close"],
    )

    if move_3 > D("0.30"):

        score += 1
        reasons.append(
            "MOMENTUM"
        )

    if (
        candles[-3]["close"]
        < candles[-2]["close"]
        < candles[-1]["close"]
    ):

        score += 1
        reasons.append(
            "3C-UP"
        )

    if (
        last["high"]
        > prev["high"]
        and last["low"]
        >= prev["low"]
    ):

        score += 1
        reasons.append(
            "HH-HL"
        )

    candle_range = (
        last["high"]
        - last["low"]
    )

    if candle_range > 0:

        body = (
            last["close"]
            - last["open"]
        )

        if body > 0:

            body_ratio = (
                body
                / candle_range
            )

            if body_ratio >= D(
                "0.50"
            ):

                score += 1
                reasons.append(
                    "STRONG-BODY"
                )

    volumes = [
        x["volume"]
        for x in candles[-7:-1]
        if x["volume"] > 0
    ]

    if volumes:

        avg_volume = (
            sum(volumes)
            / D(len(volumes))
        )

        if (
            avg_volume > 0
            and last["volume"]
            >= avg_volume * D("1.30")
        ):

            score += 1
            reasons.append(
                "VOL-BREAK"
            )

    pressure = calculate_pressure(
        candles
    )

    if pressure >= D("58"):

        score += 1
        reasons.append(
            "BUY-PRESSURE"
        )

    recent_high = max(
        x["high"]
        for x in candles[-8:-1]
    )

    if last["close"] > recent_high:

        score += 2
        reasons.append(
            "BREAKOUT"
        )

    if (
        candles[-1]["close"]
        > candles[-3]["close"]
    ):

        score += 1
        reasons.append(
            "BULLISH"
        )

    if (
        candles[-3]["close"]
        <= candles[-4]["close"]
        and last["close"]
        > candles[-3]["close"]
    ):

        score += 1
        reasons.append(
            "PULLBACK"
        )

    return score, reasons


def build_signal(
    symbol,
    candles,
):

    if len(candles) < 10:
        return None

    last = candles[-1]
    price = last["close"]

    if price <= 0:
        return None

    move = pct_change(
        candles[-6]["close"],
        price,
    )

    pressure = calculate_pressure(
        candles
    )

    score, reasons = calculate_score(
        candles
    )

    breakout = (
        last["close"]
        > max(
            x["high"]
            for x in candles[-8:-1]
        )
    )

    signal_type = "WATCH"

    if (
        breakout
        and score
        >= MIN_CONFIRMED_SCORE
        and pressure
        >= D("58")
    ):

        signal_type = (
            "CONFIRMED BUY"
        )

    elif (
        score
        >= MIN_EARLY_SCORE
        and pressure
        >= D("60")
        and move > D("0.15")
    ):

        signal_type = (
            "EARLY BUY"
        )

    elif score >= MIN_WATCH_SCORE:

        signal_type = "WATCH"

    else:
        return None

    recent_low = min(
        x["low"]
        for x in candles[-5:]
    )

    sl = (
        recent_low
        * D("0.998")
    )

    if sl >= price:

        sl = (
            price
            * D("0.988")
        )

    risk = price - sl

    if risk <= 0:
        return None

    risk_pct = (
        risk / price
    ) * D("100")

    if (
        risk_pct
        > D(str(MAX_RISK_PERCENT))
    ):
        return None

    tp1 = (
        price
        + risk * D(str(TP1_R))
    )

    tp2 = (
        price
        + risk * D(str(TP2_R))
    )

    return {
        "symbol": symbol,
        "price": price,
        "score": score,
        "pressure": pressure,
        "move": move,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk_pct": risk_pct,
        "signal_type": signal_type,
        "reasons": reasons,
        "candle_time": last["time"],
    }


# ============================================================
# HISTORY
# ============================================================

def load_history():

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        if not isinstance(
            data,
            dict,
        ):
            data = {}

    except Exception:

        data = {}

    data.setdefault(
        "signals",
        {}
    )

    data.setdefault(
        "real_trades",
        []
    )

    return data


def save_history(
    history
):

    try:

        with open(
            HISTORY_FILE,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                history,
                f,
                ensure_ascii=False,
                indent=2,
            )

    except Exception as exc:

        print(
            "HISTORY SAVE ERROR:",
            exc,
        )


def signal_id(
    signal
):

    return (
        f"{signal['symbol']}_"
        f"{signal['candle_time']}"
    )


# ============================================================
# ORDER QUANTITY
# ============================================================

def calculate_order_quantity(
    symbol,
    market_info,
    live_price,
):

    filters = market_filters(
        market_info
    )

    step = filters[
        "stepSize"
    ]

    min_qty = filters[
        "minQty"
    ]

    max_qty = filters[
        "maxQty"
    ]

    min_notional = filters[
        "minNotional"
    ]

    price = dec(
        live_price
    )

    # --------------------------------------------------------
    # FIXED BUDGET
    # --------------------------------------------------------

    if (
        FIXED_ORDER_USDT
        <= 0
    ):

        return {
            "ok": False,
            "reason":
                "FIXED_ORDER_USDT_INVALID",
            "quantity": D("0"),
            "notional": D("0"),
            "filters": filters,
        }

    if price <= 0:

        return {
            "ok": False,
            "reason":
                "LIVE_PRICE_INVALID",
            "quantity": D("0"),
            "notional": D("0"),
            "filters": filters,
        }

    if step <= 0:

        return {
            "ok": False,
            "reason":
                "STEP_SIZE_MISSING",
            "quantity": D("0"),
            "notional": D("0"),
            "filters": filters,
        }

    # --------------------------------------------------------
    # USDT -> QUANTITY
    # --------------------------------------------------------

    raw_qty = (
        FIXED_ORDER_USDT
        / price
    )

    if raw_qty <= 0:

        return {
            "ok": False,
            "reason":
                "RAW_QUANTITY_ZERO",
            "quantity": D("0"),
            "notional": D("0"),
            "filters": filters,
        }

    quantity = floor_step(
        raw_qty,
        step,
    )

    if quantity <= 0:

        return {
            "ok": False,
            "reason":
                "QUANTITY_ZERO_AFTER_STEP",
            "quantity": quantity,
            "notional": D("0"),
            "filters": filters,
        }

    # --------------------------------------------------------
    # MIN QTY
    # --------------------------------------------------------

    if (
        min_qty > 0
        and quantity < min_qty
    ):

        return {
            "ok": False,
            "reason": (
                "MIN_QTY: "
                + decimal_to_string(
                    quantity
                )
                + " < "
                + decimal_to_string(
                    min_qty
                )
            ),
            "quantity": quantity,
            "notional":
                quantity * price,
            "filters": filters,
        }

    # --------------------------------------------------------
    # MAX QTY
    # --------------------------------------------------------

    if (
        max_qty > 0
        and quantity > max_qty
    ):

        quantity = floor_step(
            max_qty,
            step,
        )

    if quantity <= 0:

        return {
            "ok": False,
            "reason":
                "QUANTITY_ZERO_AFTER_MAX_QTY",
            "quantity": quantity,
            "notional": D("0"),
            "filters": filters,
        }

    # --------------------------------------------------------
    # FINAL MIN QTY
    # --------------------------------------------------------

    if (
        min_qty > 0
        and quantity < min_qty
    ):

        return {
            "ok": False,
            "reason":
                "MIN_QTY_AFTER_MAX",
            "quantity": quantity,
            "notional":
                quantity * price,
            "filters": filters,
        }

    # --------------------------------------------------------
    # NOTIONAL
    # --------------------------------------------------------

    notional = (
        quantity * price
    )

    if (
        min_notional > 0
        and notional < min_notional
    ):

        return {
            "ok": False,
            "reason": (
                "MIN_NOTIONAL: "
                + decimal_to_string(
                    notional
                )
                + " < "
                + decimal_to_string(
                    min_notional
                )
            ),
            "quantity": quantity,
            "notional": notional,
            "filters": filters,
        }

    return {
        "ok": True,
        "reason": "OK",
        "quantity": quantity,
        "notional": notional,
        "filters": filters,
    }


# ============================================================
# FRESH PRICE
# ============================================================

def get_fresh_price(
    symbol
):

    trades = get_trades(
        symbol
    )

    if not trades:
        return D("0")

    for item in reversed(
        trades
    ):

        price = trade_price(
            item
        )

        if price > 0:
            return price

    return D("0")


# ============================================================
# MARKET BUY
# ============================================================

def place_real_market_buy(
    symbol,
    quantity,
):

    quantity = dec(
        quantity
    )

    if quantity <= 0:

        raise RuntimeError(
            "BLOCKED_QUANTITY_ZERO"
        )

    params = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quantity":
            decimal_to_string(
                quantity
            ),
        "recvWindow": 5000,
    }

    return signed_request(
        "POST",
        ORDER_PATH,
        params,
    )


# ============================================================
# FILLED CHECK
# ============================================================

def get_order(
    symbol,
    order_id,
):

    return signed_request(
        "GET",
        ORDER_QUERY_PATH,
        {
            "symbol": symbol,
            "orderId": order_id,
            "recvWindow": 5000,
        },
    )


def wait_until_filled(
    symbol,
    order_id,
    attempts=6,
):

    for _ in range(
        attempts
    ):

        time.sleep(2)

        try:

            order = get_order(
                symbol,
                order_id,
            )

            status = str(
                order.get(
                    "status",
                    ""
                )
            ).upper()

            if status == "FILLED":
                return order

            if status in (
                "CANCELED",
                "CANCELLED",
                "REJECTED",
                "EXPIRED",
            ):
                return order

        except Exception as exc:

            print(
                "FILLED CHECK ERROR:",
                exc,
            )

    return None


# ============================================================
# FILLED PRICE
# ============================================================

def filled_average_price(
    order
):

    executed_qty = dec(
        order.get(
            "executedQty"
        )
        or order.get(
            "origQty"
        )
        or order.get(
            "quantity"
        ),
        "0",
    )

    quote_qty = dec(
        order.get(
            "cummulativeQuoteQty"
        )
        or order.get(
            "cumulativeQuoteQty"
        )
        or order.get(
            "quoteQty"
        ),
        "0",
    )

    if (
        executed_qty > 0
        and quote_qty > 0
    ):

        return (
            quote_qty
            / executed_qty
        )

    fills = order.get(
        "fills"
    )

    if isinstance(
        fills,
        list,
    ):

        total_qty = D("0")
        total_quote = D("0")

        for fill in fills:

            qty = dec(
                fill.get(
                    "qty"
                ),
                "0",
            )

            price = dec(
                fill.get(
                    "price"
                ),
                "0",
            )

            if (
                qty > 0
                and price > 0
            ):

                total_qty += qty
                total_quote += (
                    qty * price
                )

        if total_qty > 0:

            return (
                total_quote
                / total_qty
            )

    return D("0")


# ============================================================
# OCO PRICE ROUNDING
# ============================================================

def floor_price(
    price,
    tick,
):

    if tick <= 0:
        return price

    return floor_step(
        price,
        tick,
    )


def make_oco_prices(
    entry,
    tp1,
    sl,
    tick,
):

    entry = dec(entry)
    tp1 = dec(tp1)
    sl = dec(sl)
    tick = dec(tick)

    if entry <= 0:
        raise RuntimeError(
            "INVALID_ENTRY_PRICE"
        )

    if tick > 0:

        limit_price = floor_price(
            tp1,
            tick,
        )

        stop_price = floor_price(
            sl,
            tick,
        )

        stop_limit_price = floor_price(
            sl - tick,
            tick,
        )

    else:

        limit_price = tp1
        stop_price = sl
        stop_limit_price = sl

    if limit_price <= entry:

        raise RuntimeError(
            "OCO_TP_NOT_ABOVE_ENTRY"
        )

    if stop_price >= entry:

        raise RuntimeError(
            "OCO_STOP_NOT_BELOW_ENTRY"
        )

    if stop_limit_price >= stop_price:

        if tick > 0:

            stop_limit_price = (
                stop_price - tick
            )

        else:

            stop_limit_price = (
                stop_price
            )

    if (
        tick > 0
        and stop_limit_price <= 0
    ):

        raise RuntimeError(
            "OCO_STOP_LIMIT_INVALID"
        )

    return (
        limit_price,
        stop_price,
        stop_limit_price,
    )


# ============================================================
# OCO SELL
# ============================================================

def place_oco_sell(
    symbol,
    quantity,
    entry,
    tp1,
    sl,
    tick,
):

    quantity = dec(
        quantity
    )

    if quantity <= 0:

        raise RuntimeError(
            "OCO_QUANTITY_ZERO"
        )

    (
        limit_price,
        stop_price,
        stop_limit_price,
    ) = make_oco_prices(
        entry,
        tp1,
        sl,
        tick,
    )

    params = {
        "symbol": symbol,
        "side": "SELL",
        "quantity":
            decimal_to_string(
                quantity
            ),
        "price":
            decimal_to_string(
                limit_price
            ),
        "stopPrice":
            decimal_to_string(
                stop_price
            ),
        "stopLimitPrice":
            decimal_to_string(
                stop_limit_price
            ),
        "stopLimitTimeInForce":
            "GTC",
        "recvWindow": 5000,
    }

    return signed_request(
        "POST",
        OCO_PATH,
        params,
    )


# ============================================================
# REAL TRADE EXECUTION
# ============================================================

def execute_real_trade(
    signal,
    market_info,
):

    symbol = signal[
        "symbol"
    ]

    filters = market_filters(
        market_info
    )

    if not filters[
        "ocoAllowed"
    ]:

        raise RuntimeError(
            "OCO_NOT_ALLOWED_SKIP_UNPROTECTED_BUY"
        )

    # --------------------------------------------------------
    # LIVE PRICE
    # --------------------------------------------------------

    live_price = get_fresh_price(
        symbol
    )

    if live_price <= 0:

        raise RuntimeError(
            "LIVE_PRICE_UNAVAILABLE"
        )

    # --------------------------------------------------------
    # QUANTITY CHECK
    # --------------------------------------------------------

    quantity_info = (
        calculate_order_quantity(
            symbol,
            market_info,
            live_price,
        )
    )

    if not quantity_info[
        "ok"
    ]:

        raise RuntimeError(
            quantity_info[
                "reason"
            ]
        )

    quantity = (
        quantity_info[
            "quantity"
        ]
    )

    if quantity <= 0:

        raise RuntimeError(
            "FINAL_QUANTITY_ZERO"
        )

    print(
        "ORDER CHECK "
        + symbol
        + ": "
        + "BUDGET="
        + decimal_to_string(
            FIXED_ORDER_USDT
        )
        + " USDT "
        + "PRICE="
        + decimal_to_string(
            live_price
        )
        + " QTY="
        + decimal_to_string(
            quantity
        )
        + " NOTIONAL="
        + decimal_to_string(
            quantity_info[
                "notional"
            ]
        )
        + " MIN_NOTIONAL="
        + decimal_to_string(
            filters[
                "minNotional"
            ]
        )
    )

    # --------------------------------------------------------
    # REAL MARKET BUY
    # --------------------------------------------------------

    order = place_real_market_buy(
        symbol,
        quantity,
    )

    order_id = (
        order.get(
            "orderId"
        )
        or order.get("id")
    )

    if not order_id:

        raise RuntimeError(
            "BUY_ORDER_ID_MISSING"
        )

    filled = wait_until_filled(
        symbol,
        order_id,
    )

    if not filled:

        raise RuntimeError(
            "BUY_NOT_CONFIRMED_FILLED"
        )

    status = str(
        filled.get(
            "status",
            ""
        )
    ).upper()

    if status != "FILLED":

        raise RuntimeError(
            "BUY_STATUS_"
            + status
        )

    executed_qty = dec(
        filled.get(
            "executedQty"
        )
        or filled.get(
            "origQty"
        )
        or quantity,
        "0",
    )

    if executed_qty <= 0:

        raise RuntimeError(
            "FILLED_BUT_EXECUTED_QTY_ZERO"
        )

    entry = filled_average_price(
        filled
    )

    if entry <= 0:
        entry = live_price

    # --------------------------------------------------------
    # FINAL OCO LEVELS
    # --------------------------------------------------------

    risk = (
        entry
        - signal["sl"]
    )

    if risk <= 0:

        raise RuntimeError(
            "INVALID_RISK_AFTER_FILL"
        )

    tp1 = (
        entry
        + risk * D(
            str(TP1_R)
        )
    )

    tp2 = (
        entry
        + risk * D(
            str(TP2_R)
        )
    )

    # --------------------------------------------------------
    # OCO
    # --------------------------------------------------------

    oco = place_oco_sell(
        symbol,
        executed_qty,
        entry,
        tp1,
        signal["sl"],
        filters[
            "tickSize"
        ],
    )

    return {
        "symbol": symbol,
        "order_id": order_id,
        "executed_qty":
            executed_qty,
        "entry": entry,
        "sl": signal["sl"],
        "tp1": tp1,
        "tp2": tp2,
        "oco": oco,
        "notional":
            executed_qty * entry,
    }


# ============================================================
# TELEGRAM SIGNAL
# ============================================================

def send_signal_message(
    signal
):

    reasons = ", ".join(
        signal["reasons"]
    )

    message = (
        "🚨 NEW ATI BUY SIGNAL\n\n"
        f"🟢 {signal['signal_type']}\n"
        f"🪙 {signal['symbol']}\n"
        f"💰 PRICE: "
        f"{decimal_to_string(signal['price'])}\n"
        f"📊 SCORE: "
        f"{signal['score']}\n"
        f"💪 PRESSURE: "
        f"{signal['pressure']:.1f}%\n"
        f"📈 MOVE: "
        f"{signal['move']:.2f}%\n"
        f"🛑 SL: "
        f"{decimal_to_string(signal['sl'])}\n"
        f"🎯 TP1: "
        f"{decimal_to_string(signal['tp1'])}\n"
        f"🎯 TP2: "
        f"{decimal_to_string(signal['tp2'])}\n"
        f"🧠 {reasons}\n"
    )

    telegram_send(
        message
    )


# ============================================================
# ORDER CHECK MESSAGE
# ============================================================

def send_order_skip_message(
    symbol,
    reason,
):

    message = (
        "⛔ REAL BUY SKIPPED\n\n"
        f"🪙 {symbol}\n"
        f"💵 BUDGET: "
        f"{decimal_to_string(FIXED_ORDER_USDT)} USDT\n"
        f"❌ {reason}\n"
        "🛡 NO ORDER SENT"
    )

    telegram_send(
        message
    )


# ============================================================
# REAL BUY MESSAGE
# ============================================================

def send_real_buy_message(
    result
):

    message = (
        "✅ REAL SPOT BUY FILLED\n\n"
        f"🪙 {result['symbol']}\n"
        f"📦 QTY: "
        f"{decimal_to_string(result['executed_qty'])}\n"
        f"💰 ENTRY: "
        f"{decimal_to_string(result['entry'])}\n"
        f"💵 VALUE: "
        f"{decimal_to_string(result['notional'])} USDT\n"
        f"🛑 SL: "
        f"{decimal_to_string(result['sl'])}\n"
        f"🎯 TP1: "
        f"{decimal_to_string(result['tp1'])}\n"
        f"🎯 TP2: "
        f"{decimal_to_string(result['tp2'])}\n"
        "🔐 OCO: PLACED\n"
        f"🆔 ORDER: "
        f"{result['order_id']}\n"
    )

    telegram_send(
        message
    )


def send_trade_error(
    symbol,
    reason,
):

    message = (
        "🚨 REAL TRADE ERROR\n\n"
        f"🪙 {symbol}\n"
        f"❌ {reason}\n"
        "🛡 ORDER PROTECTION ACTIVE"
    )

    telegram_send(
        message
    )


# ============================================================
# START MESSAGE
# ============================================================

def send_scan_start():

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        "📡 TABDEAL API: CONNECTING...\n"
        "📊 SCAN: STARTING\n"
        "⏱ TIMEFRAME: 5m\n"
        "🕯 CLOSED CANDLE: YES\n"
        "💵 ORDER MODE: FIXED USDT AMOUNT\n"
        f"💰 ORDER AMOUNT: "
        f"{decimal_to_string(FIXED_ORDER_USDT)} USDT\n"
        f"🔧 REAL ORDERS: "
        f"{'ENABLED' if REAL_ORDERS else 'DISABLED'}\n"
        f"🕐 {utc_now()}"
    )

    telegram_send(
        message
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        f"ATI CRYPTO BOT {VERSION}"
    )

    send_scan_start()

    # --------------------------------------------------------
    # CONFIGURATION
    # --------------------------------------------------------

    if FIXED_ORDER_USDT <= 0:

        telegram_send(
            "🚨 ATI CONFIG ERROR\n\n"
            "❌ FIXED ORDER AMOUNT INVALID."
        )

        return

    # --------------------------------------------------------
    # API KEY CHECK
    # --------------------------------------------------------

    if (
        not API_KEY
        or not API_SECRET
    ):

        telegram_send(
            "🚨 ATI CONFIG ERROR\n\n"
            "❌ TABDEAL API KEY/SECRET MISSING."
        )

        return

    # --------------------------------------------------------
    # EXCHANGE INFO
    # --------------------------------------------------------

    try:

        exchange_info = (
            get_exchange_info()
        )

        symbol_map = (
            build_symbol_map(
                exchange_info
            )
        )

    except Exception as exc:

        telegram_send(
            "🚨 ATI API ERROR\n\n"
            "❌ EXCHANGE INFO FAILED\n"
            f"{exc}"
        )

        print(
            "EXCHANGE INFO ERROR:",
            exc,
        )

        return

    market_count = len(
        symbol_map
    )

    print(
        "TABDEAL API: OK"
    )

    print(
        "USDT MARKETS:",
        market_count,
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    candidates = []

    valid_trades = 0
    insufficient = 0
    api_errors = 0

    for symbol in symbol_map:

        try:

            trades = get_trades(
                symbol
            )

            if not trades:

                insufficient += 1
                continue

            candles = (
                build_5m_candles(
                    trades
                )
            )

            if len(candles) < 10:

                insufficient += 1
                continue

            valid_trades += 1

            signal = build_signal(
                symbol,
                candles,
            )

            if signal:

                candidates.append(
                    signal
                )

        except Exception as exc:

            api_errors += 1

            print(
                f"SCAN ERROR {symbol}:",
                exc,
            )

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["pressure"],
            x["move"],
        ),
        reverse=True,
    )

    candidates = candidates[
        :TOP_CANDIDATES
    ]

    # --------------------------------------------------------
    # DISPLAY
    # --------------------------------------------------------

    history = load_history()

    print()
    print(
        f"MARKETS: {market_count}"
    )
    print(
        f"VALID: {valid_trades}"
    )
    print(
        f"INSUFFICIENT DATA: {insufficient}"
    )
    print(
        f"API/SCAN ERRORS: {api_errors}"
    )
    print(
        f"CANDIDATES: {len(candidates)}"
    )

    lines = [
        f"⚡ ATI CRYPTO BOT {VERSION}",
        "",
        "🧠 OPPORTUNITY ENGINE",
        "",
        "📡 TABDEAL API: OK",
        f"📊 USDT MARKETS: {market_count}",
        f"📥 VALID TRADES: {valid_trades}",
        f"⚠️ INSUFFICIENT DATA: {insufficient}",
        f"⚠️ API/SCAN ERRORS: {api_errors}",
        "",
        "💵 ORDER MODE: FIXED USDT",
        f"💰 ORDER AMOUNT: "
        f"{decimal_to_string(FIXED_ORDER_USDT)} USDT",
        (
            "🔧 REAL ORDERS: ENABLED"
            if REAL_ORDERS
            else "🔧 REAL ORDERS: DISABLED"
        ),
        "",
        f"🕐 {utc_now()}",
        "",
        "🔥 TOP 10:",
    ]

    for index, signal in enumerate(
        candidates[
            :TOP_DISPLAY
        ],
        start=1,
    ):

        lines.append(
            f"{index}. "
            f"{signal['symbol']} "
            f"{signal['signal_type']} "
            f"SCORE "
            f"{signal['score']} "
            f"P "
            f"{signal['pressure']:.0f}%"
        )

    if not candidates:

        lines.append(
            "No valid BUY/WATCH candidates."
        )

    telegram_send(
        "\n".join(lines)
    )

    # --------------------------------------------------------
    # REAL ORDER ENGINE
    # --------------------------------------------------------

    real_buy_count = 0
    failed_real_attempts = 0
    skipped_minimum = 0

    if REAL_ORDERS:

        for signal in candidates:

            if (
                real_buy_count
                >= MAX_REAL_BUYS_PER_RUN
            ):
                break

            # Do not trade WATCH.
            if (
                signal["signal_type"]
                == "WATCH"
            ):
                continue

            sid = signal_id(
                signal
            )

            previous = (
                history[
                    "signals"
                ].get(sid)
            )

            if previous:

                previous_status = str(
                    previous.get(
                        "execution_status",
                        "",
                    )
                ).upper()

                if previous_status in (
                    "FILLED",
                    "OPEN",
                    "OCO_PLACED",
                ):

                    continue

            send_signal_message(
                signal
            )

            # ------------------------------------------------
            # PRE-CHECK BEFORE ORDER
            # ------------------------------------------------

            try:

                market_info = (
                    symbol_map[
                        signal["symbol"]
                    ]
                )

                live_price = (
                    get_fresh_price(
                        signal["symbol"]
                    )
                )

                if live_price <= 0:

                    raise RuntimeError(
                        "LIVE_PRICE_UNAVAILABLE"
                    )

                quantity_info = (
                    calculate_order_quantity(
                        signal["symbol"],
                        market_info,
                        live_price,
                    )
                )

                if not quantity_info[
                    "ok"
                ]:

                    skipped_minimum += 1

                    reason = (
                        quantity_info[
                            "reason"
                        ]
                    )

                    print(
                        "BUY SKIPPED "
                        f"{signal['symbol']}: "
                        f"{reason}"
                    )

                    send_order_skip_message(
                        signal["symbol"],
                        reason,
                    )

                    continue

                print(
                    "PRE-ORDER OK "
                    f"{signal['symbol']} "
                    f"BUDGET="
                    f"{decimal_to_string(FIXED_ORDER_USDT)} "
                    f"PRICE="
                    f"{decimal_to_string(live_price)} "
                    f"QTY="
                    f"{decimal_to_string(quantity_info['quantity'])} "
                    f"NOTIONAL="
                    f"{decimal_to_string(quantity_info['notional'])}"
                )

            except Exception as exc:

                failed_real_attempts += 1

                send_trade_error(
                    signal["symbol"],
                    str(exc),
                )

                continue

            # ------------------------------------------------
            # EXECUTE
            # ------------------------------------------------

            try:

                result = execute_real_trade(
                    signal,
                    market_info,
                )

                history[
                    "signals"
                ][sid] = {
                    "symbol":
                        signal["symbol"],
                    "price":
                        decimal_to_string(
                            signal["price"]
                        ),
                    "status":
                        "OPEN",
                    "execution_status":
                        "OCO_PLACED",
                    "order_id":
                        str(
                            result[
                                "order_id"
                            ]
                        ),
                    "entry":
                        decimal_to_string(
                            result["entry"]
                        ),
                    "quantity":
                        decimal_to_string(
                            result[
                                "executed_qty"
                            ]
                        ),
                    "time":
                        utc_now(),
                }

                history[
                    "real_trades"
                ].append({
                    "symbol":
                        signal["symbol"],
                    "
