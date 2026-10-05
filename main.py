# ============================================================
# ATI CRYPTO BOT V40.2.63-REAL-EXIT
# TABDEAL SPOT
#
# REAL BUY
# REAL SELL
# AUTO TP / SL
# TP = +2%
# SL = -1%
# NO EMA
# 5m CLOSED CANDLE
# ============================================================

import os
import time
import hmac
import hashlib
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests


VERSION = "V40.2.63-REAL-EXIT"

BASE = "https://api1.tabdeal.org"
PUBLIC_ROOT = BASE + "/r/api/v1"
TRADE_ROOT = BASE + "/api/v1"

TIMEOUT = 15

ORDER_VALUE = Decimal(os.getenv("ORDER_QTY", "2"))

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "false")
    .strip()
    .lower()
    in ("1", "true", "yes", "on")
)

# ============================================================
# AUTO EXIT
# ============================================================

TP_PERCENT = Decimal(
    os.getenv("TP_PERCENT", "2.0")
)

SL_PERCENT = Decimal(
    os.getenv("SL_PERCENT", "1.0")
)

CHECK_INTERVAL = int(
    os.getenv("EXIT_CHECK_SECONDS", "10")
)

MAX_HOLD_MINUTES = int(
    os.getenv("MAX_HOLD_MINUTES", "300")
)

# ============================================================
# BUY SETTINGS
# ============================================================

SCAN_UNIVERSE = int(
    os.getenv("SCAN_UNIVERSE", "25")
)

MIN_CANDLES = 12

MIN_SCORE = int(
    os.getenv("MIN_SCORE", "7")
)

session = requests.Session()

session.headers.update(
    {
        "User-Agent":
            "ATI-Crypto-Bot/" + VERSION
    }
)

SERVER_OFFSET_MS = 0


# ============================================================
# TIME
# ============================================================

def now_ms():

    return (
        int(time.time() * 1000)
        + SERVER_OFFSET_MS
    )


def utc_now():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram(text):

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN",
        ""
    ).strip()

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID",
        ""
    ).strip()

    if not token or not chat_id:

        print(
            text,
            flush=True
        )

        return False

    try:

        r = requests.post(
            f"https://api.telegram.org/"
            f"bot{token}/sendMessage",

            data={
                "chat_id": chat_id,
                "text": text,
            },

            timeout=15,
        )

        print(
            "TELEGRAM:",
            r.status_code,
            flush=True,
        )

        return r.ok

    except Exception as e:

        print(
            "TELEGRAM ERROR:",
            repr(e),
            flush=True,
        )

        return False


# ============================================================
# JSON
# ============================================================

def json_response(r):

    try:

        return r.json()

    except Exception:

        return {
            "_http": r.status_code,
            "_text": r.text[:500],
        }


# ============================================================
# PUBLIC GET
# ============================================================

def public_get(
    path,
    params=None,
):

    if path.startswith("http"):

        url = path

    else:

        url = BASE + path

    r = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT,
    )

    data = json_response(r)

    if not r.ok:

        raise RuntimeError(
            f"HTTP {r.status_code}: {data}"
        )

    return data


# ============================================================
# SERVER TIME
# ============================================================

def sync_server_time():

    global SERVER_OFFSET_MS

    data = public_get(
        PUBLIC_ROOT + "/time"
    )

    server_time = int(
        data["serverTime"]
    )

    local_time = int(
        time.time() * 1000
    )

    SERVER_OFFSET_MS = (
        server_time
        - local_time
    )

    print(
        f"🕐 SERVER OFFSET: "
        f"{SERVER_OFFSET_MS} ms",
        flush=True,
    )


# ============================================================
# CREDENTIALS
# ============================================================

def load_credentials():

    key = os.getenv(
        "TABDIL_API_KEY",
        ""
    ).strip()

    secret = os.getenv(
        "TABDIL_API_SECRET",
        ""
    ).strip()

    if not key or not secret:

        key = os.getenv(
            "TABDEAL_API_KEY",
            ""
        ).strip()

        secret = os.getenv(
            "TABDEAL_API_SECRET",
            ""
        ).strip()

    if not key or not secret:

        raise RuntimeError(
            "API KEY/SECRET NOT FOUND"
        )

    os.environ[
        "API_KEY"
    ] = key

    os.environ[
        "API_SECRET"
    ] = secret


# ============================================================
# SIGN
# ============================================================

def sign_params(params):

    query = urlencode(params)

    signature = hmac.new(
        os.environ[
            "API_SECRET"
        ].encode(),

        query.encode(),

        hashlib.sha256,
    ).hexdigest()

    return (
        query
        + "&signature="
        + signature
    )


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(
    method,
    path,
    params=None,
):

    params = dict(
        params or {}
    )

    params["timestamp"] = now_ms()

    query = sign_params(
        params
    )

    url = (
        TRADE_ROOT
        + path
    )

    headers = {
        "X-MBX-APIKEY":
            os.environ[
                "API_KEY"
            ]
    }

    method = method.upper()

    if method == "GET":

        r = session.get(
            url + "?" + query,
            headers=headers,
            timeout=TIMEOUT,
        )

    elif method == "POST":

        r = session.post(
            url,
            headers={
                **headers,
                "Content-Type":
                    "application/"
                    "x-www-form-urlencoded",
            },
            data=query,
            timeout=TIMEOUT,
        )

    elif method == "DELETE":

        r = session.delete(
            url + "?" + query,
            headers=headers,
            timeout=TIMEOUT,
        )

    else:

        raise ValueError(
            "Unsupported HTTP method"
        )

    data = json_response(r)

    if not r.ok:

        raise RuntimeError(
            f"HTTP {r.status_code}: {data}"
        )

    if (
        isinstance(data, dict)
        and data.get("code")
        not in (None, 0)
    ):

        raise RuntimeError(
            f"API ERROR: {data}"
        )

    return data


# ============================================================
# AUTH
# ============================================================

def auth_check():

    data = signed_request(
        "GET",
        "/account",
    )

    if not data.get(
        "canTrade",
        False,
    ):

        raise RuntimeError(
            "canTrade is not true"
        )

    return data


# ============================================================
# MARKET INFO
# ============================================================

def exchange_info():

    return public_get(
        PUBLIC_ROOT
        + "/exchangeInfo"
    )


def normalize_symbol(
    value
):

    return str(
        value or ""
    ).replace(
        "_",
        ""
    ).upper()


def market_list(info):

    if isinstance(
        info,
        list
    ):

        raw = info

    elif isinstance(
        info,
        dict
    ):

        raw = (
            info.get("symbols")
            or info.get("markets")
            or info.get("data")
            or []
        )

    else:

        raw = []

    result = []

    for market in raw:

        if not isinstance(
            market,
            dict
        ):

            continue

        symbol = (
            market.get("symbol")
            or market.get("market")
            or market.get("name")
        )

        if not symbol:

            continue

        symbol = normalize_symbol(
            symbol
        )

        if not symbol.endswith(
            "USDT"
        ):

            continue

        status = str(
            market.get(
                "status",
                "TRADING"
            )
        ).upper()

        if status not in (
            "TRADING",
            "ACTIVE",
            "ENABLED",
        ):

            continue

        result.append(
            market
        )

    return result


def market_symbol(
    market
):

    return normalize_symbol(
        market.get("symbol")
        or market.get("market")
        or market.get("name")
    )


# ============================================================
# MARKET FILTERS
# ============================================================

def step_from_market(
    market
):

    filters = (
        market.get(
            "filters"
        )
        or []
    )

    for f in filters:

        ft = str(
            f.get(
                "filterType",
                f.get(
                    "type",
                    ""
                )
            )
        ).upper()

        if ft in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE",
        ):

            for key in (
                "stepSize",
                "step",
                "quantityStep",
            ):

                if f.get(key):

                    try:

                        return Decimal(
                            str(
                                f[key]
                            )
                        )

                    except Exception:

                        pass

    return Decimal(
        "0.00000001"
    )


def min_qty_from_market(
    market
):

    filters = (
        market.get(
            "filters"
        )
        or []
    )

    for f in filters:

        ft = str(
            f.get(
                "filterType",
                f.get(
                    "type",
                    ""
                )
            )
        ).upper()

        if ft in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE",
        ):

            for key in (
                "minQty",
                "minQuantity",
            ):

                if f.get(key):

                    try:

                        return Decimal(
                            str(
                                f[key]
                            )
                        )

                    except Exception:

                        pass

    return Decimal("0")


def floor_step(
    value,
    step
):

    if step <= 0:

        return value

    return (
        (
            value / step
        ).to_integral_value(
            rounding=ROUND_DOWN
        )
        * step
    )


def fmt_decimal(
    value
):

    text = format(
        value,
        "f"
    )

    if "." in text:

        text = (
            text
            .rstrip("0")
            .rstrip(".")
        )

    return text


# ============================================================
# TRADES / PRICE
# ============================================================

def recent_trades(
    symbol
):

    return public_get(
        PUBLIC_ROOT
        + "/trades",

        {
            "symbol": symbol,
            "limit": 100,
        },
    )


def trade_rows(
    data
):

    if isinstance(
        data,
        list
    ):

        return data

    if isinstance(
        data,
        dict
    ):

        return (
            data.get("data")
            or data.get("trades")
            or []
        )

    return []


def current_price(
    symbol
):

    rows = trade_rows(
        recent_trades(
            symbol
        )
    )

    if not rows:

        raise RuntimeError(
            f"No trades for {symbol}"
        )

    last = rows[-1]

    return Decimal(
        str(
            last["price"]
        )
    )


# ============================================================
# CANDLES
# ============================================================

def make_candles(
    rows
):

    buckets = {}

    for trade in rows:

        try:

            price = Decimal(
                str(
                    trade["price"]
                )
            )

            trade_time = int(
                trade.get(
                    "time",
                    trade.get(
                        "timestamp"
                    )
                )
            )

        except Exception:

            continue

        bucket = (
            trade_time
            // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = {
                "t": bucket,
                "o": price,
                "h": price,
                "l": price,
                "c": price,
            }

        candle = buckets[
            bucket
        ]

        candle["h"] = max(
            candle["h"],
            price
        )

        candle["l"] = min(
            candle["l"],
            price
        )

        candle["c"] = price

    candles = [
        buckets[k]
        for k in sorted(
            buckets
        )
    ]

    current_bucket = (
        int(
            time.time()
            * 1000
        )
        // 300000
    ) * 300000

    return [
        c
        for c in candles
        if c["t"]
        < current_bucket
    ]


# ============================================================
# SIGNAL
# ============================================================

def signal(
    candles
):

    if len(candles) < MIN_CANDLES:

        return None

    last = candles[-1]

    previous = candles[-2]

    lookback = candles[-7:-1]

    recent_high = max(
        c["h"]
        for c in lookback
    )

    score = 0

    reasons = []

    if last["c"] > recent_high:

        score += 4

        reasons.append(
            "BOS"
        )

    elif (
        last["c"]
        >= recent_high
        * Decimal("0.998")
    ):

        score += 2

        reasons.append(
            "NEAR_BOS"
        )

    else:

        return None

    if last["c"] > previous["c"]:

        score += 1

        reasons.append(
            "UP"
        )

    candle_range = (
        last["h"]
        - last["l"]
    )

    body = abs(
        last["c"]
        - last["o"]
    )

    if (
        candle_range > 0
        and
        body / candle_range
        >= Decimal("0.55")
    ):

        score += 2

        reasons.append(
            "STRONG_CLOSE"
        )

    if last["c"] > last["o"]:

        score += 1

        reasons.append(
            "GREEN"
        )

    move = (
        (
            last["c"]
            / previous["c"]
        )
        - 1
    ) * 100

    if move > Decimal("0.15"):

        score += 1

        reasons.append(
            "MOMENTUM"
        )

    if move > Decimal("2.2"):

        return None

    if score < MIN_SCORE:

        return None

    return {
        "price": last["c"],
        "score": score,
        "reasons": reasons,
    }


# ============================================================
# QUANTITY
# ============================================================

def build_quantity(
    market,
    price
):

    step = step_from_market(
        market
    )

    min_qty = min_qty_from_market(
        market
    )

    quantity = floor_step(
        ORDER_VALUE / price,
        step
    )

    if quantity < min_qty:

        quantity = min_qty

    return quantity


# ============================================================
# BUY
# ============================================================

def place_market_buy(
    symbol,
    quantity
):

    return signed_request(
        "POST",
        "/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity":
                fmt_decimal(
                    quantity
                ),
        }
    )


# ============================================================
# SELL
# ============================================================

def place_market_sell(
    symbol,
    quantity
):

    return signed_request(
        "POST",
        "/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity":
                fmt_decimal(
                    quantity
                ),
        }
    )


# ============================================================
# ORDER
# ============================================================

def get_order(
    symbol,
    order_id
):

    return signed_request(
        "GET",
        "/order",
        {
            "symbol": symbol,
            "orderId":
                int(order_id),
        }
    )


# ============================================================
# ACTUAL FILLED PRICE
# ============================================================

def filled_price(
    order
):

    executed = Decimal(
        str(
            order.get(
                "executedQty",
                "0"
            )
        )
    )

    quote = Decimal(
        str(
            order.get(
                "cummulativeQuoteQty",
                order.get(
                    "cumulativeQuoteQty",
                    "0"
                )
            )
        )
    )

    if executed <= 0:

        return Decimal("0")

    return (
        quote
        / executed
    )


# ============================================================
# AUTO EXIT MANAGER
# ============================================================

def manage_position(
    symbol,
    market,
    executed_qty,
    entry_price
):

    if executed_qty <= 0:

        raise RuntimeError(
            "No executed quantity"
        )

    tp_price = (
        entry_price
        * (
            Decimal("1")
            + TP_PERCENT
            / Decimal("100")
        )
    )

    sl_price = (
        entry_price
        * (
            Decimal("1")
            - SL_PERCENT
            / Decimal("100")
        )
    )

    started = time.time()

    telegram(
        "🛡 AUTO EXIT ACTIVE\n"
        f"🪙 {symbol}\n"
        f"📥 ENTRY: {entry_price}\n"
        f"🎯 TP: {tp_price}\n"
        f"🛑 SL: {sl_price}\n"
        f"📦 QTY: "
        f"{fmt_decimal(executed_qty)}"
    )

    print(
        "🛡 AUTO EXIT ACTIVE",
        flush=True
    )

    print(
        f"🎯 TP = {tp_price}",
        flush=True
    )

    print(
        f"🛑 SL = {sl_price}",
        flush=True
    )

    while True:

        elapsed = (
            time.time()
            - started
        )

        if (
            elapsed
            >= MAX_HOLD_MINUTES
            * 60
        ):

            reason = (
                "MAX_HOLD_TIME"
            )

            break

        try:

            price = current_price(
                symbol
            )

            print(
                f"👀 {symbol} "
                f"PRICE={price} "
                f"TP={tp_price} "
                f"SL={sl_price}",
                flush=True
            )

            if price >= tp_price:

                reason = "TAKE_PROFIT"

                break

            if price <= sl_price:

                reason = "STOP_LOSS"

                break

        except Exception as e:

            print(
                f"⚠️ EXIT CHECK: {e}",
                flush=True
            )

        time.sleep(
            CHECK_INTERVAL
        )

    telegram(
        "🚨 EXIT TRIGGERED\n"
        f"🪙 {symbol}\n"
        f"📌 REASON: {reason}\n"
        f"📦 QTY: "
        f"{fmt_decimal(executed_qty)}"
    )

    # --------------------------------------------------------
    # SELL
    # --------------------------------------------------------

    print(
        "🚀 SENDING REAL MARKET SELL",
        flush=True
    )

    try:

        sell_order = (
            place_market_sell(
                symbol,
                executed_qty
            )
        )

    except Exception as e:

        telegram(
            "🚨 REAL SELL FAILED\n"
            f"🪙 {symbol}\n"
            f"📦 QTY: "
            f"{fmt_decimal(executed_qty)}\n"
            f"❌ {e}"
        )

        raise

    sell_id = sell_order.get(
        "orderId"
    )

    telegram(
        "✅ SELL ACCEPTED\n"
        f"🪙 {symbol}\n"
        f"🆔 {sell_id}\n"
        f"📌 STATUS: "
        f"{sell_order.get('status')}"
    )

    if sell_id is not None:

        time.sleep(1)

        try:

            final_sell = get_order(
                symbol,
                sell_id
            )

            sell_status = (
                final_sell.get(
                    "status",
                    "UNKNOWN"
                )
            )

            sell_qty = (
                final_sell.get(
                    "executedQty",
                    "0"
                )
            )

            sell_quote = (
                final_sell.get(
                    "cummulativeQuoteQty",
                    final_sell.get(
                        "cumulativeQuoteQty",
                        "0"
                    )
                )
            )

            telegram(
                "🧾 SELL RESULT\n"
                f"🪙 {symbol}\n"
                f"🆔 {sell_id}\n"
                f"📌 STATUS: "
                f"{sell_status}\n"
                f"📦 EXECUTED: "
                f"{sell_qty}\n"
                f"💵 QUOTE: "
                f"{sell_quote}\n"
                f"📌 REASON: {reason}"
            )

        except Exception as e:

            telegram(
                "⚠️ SELL SENT BUT "
                "STATUS CHECK FAILED\n"
                f"🆔 {sell_id}\n"
                f"❌ {e}"
            )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        f"⚡ ATI BOT {VERSION}",
        flush=True
    )

    print(
        "📡 TABDEAL SPOT",
        flush=True
    )

    print(
        f"🔓 LIVE TRADING: "
        f"{LIVE_TRADING}",
        flush=True
    )

    print(
        f"💵 ORDER: "
        f"{ORDER_VALUE} USDT",
        flush=True
    )

    telegram(
        "💓 ATI ALIVE\n"
        f"⚡ {VERSION}\n"
        "📡 TABDEAL SPOT\n"
        f"🔓 LIVE: {LIVE_TRADING}\n"
        f"💵 ORDER: {ORDER_VALUE} USDT\n"
        f"🎯 TP: +{TP_PERCENT}%\n"
        f"🛑 SL: -{SL_PERCENT}%"
    )

    load_credentials()

    sync_server_time()

    account = auth_check()

    balance = Decimal("0")

    for b in account.get(
        "balances",
        []
    ):

        if str(
            b.get(
                "asset",
                ""
            )
        ).upper() == "USDT":

            balance = Decimal(
                str(
                    b.get(
                        "free",
                        "0"
                    )
                )
            )

            break

    telegram(
        "✅ AUTH SUCCESS\n"
        f"🔓 canTrade="
        f"{account.get('canTrade')}\n"
        f"💰 USDT FREE: {balance}"
    )

    if balance < ORDER_VALUE:

        telegram(
            "❌ USDT BALANCE TOO LOW\n"
            f"💰 FREE: {balance}\n"
            f"💵 REQUIRED: {ORDER_VALUE}"
        )

        return

    info = exchange_info()

    markets = market_list(
        info
    )

    telegram(
        f"📊 MARKETS: {len(markets)}\n"
        f"🔎 SCANNING: "
        f"{min(SCAN_UNIVERSE, len(markets))}"
    )

    candidates = []

    for market in markets[
        :SCAN_UNIVERSE
    ]:

        symbol = market_symbol(
            market
        )

        try:

            rows = trade_rows(
                recent_trades(
                    symbol
                )
            )

            candles = make_candles(
                rows
            )

            result = signal(
                candles
            )

            if result:

                result[
                    "symbol"
                ] = symbol

                result[
                    "market"
                ] = market

                candidates.append(
                    result
                )

        except Exception as e:

            print(
                f"⚠️ {symbol}: {e}",
                flush=True
            )

    if not candidates:

        telegram(
            "🔎 SCAN FINISHED\n"
            "⚪ NO BUY\n"
            f"🕐 {utc_now()}"
        )

        return

    candidates.sort(
        key=lambda x:
            x["score"],
        reverse=True
    )

    best = candidates[0]

    symbol = best[
        "symbol"
    ]

    price = best[
        "price"
    ]

    market = best[
        "market"
    ]

    quantity = build_quantity(
        market,
        price
    )

    notional = (
        quantity * price
    )

    telegram(
        "🎯 BUY CANDIDATE\n"
        f"🪙 {symbol}\n"
        f"💵 PRICE: {price}\n"
        f"📦 QTY: "
        f"{fmt_decimal(quantity)}\n"
        f"💰 NOTIONAL: "
        f"{notional:.8f}\n"
        f"⭐ SCORE: "
        f"{best['score']}\n"
        f"🧠 "
        f"{', '.join(best['reasons'])}"
    )

    if not LIVE_TRADING:

        telegram(
            "🟡 PAPER ONLY\n"
            "🚫 REAL ORDER NOT SENT"
        )

        return

    if notional > balance:

        raise RuntimeError(
            "Order exceeds balance"
        )

    # ========================================================
    # REAL BUY
    # ========================================================

    telegram(
        "🚀 REAL MARKET BUY\n"
        f"🪙 {symbol}\n"
        f"📦 QTY: "
        f"{fmt_decimal(quantity)}"
    )

    order = place_market_buy(
        symbol,
        quantity
    )

    order_id = order.get(
        "orderId"
    )

    telegram(
        "✅ ORDER ACCEPTED\n"
        f"🪙 {symbol}\n"
        f"🆔 {order_id}\n"
        f"📌 STATUS: "
        f"{order.get('status')}"
    )

    # ========================================================
    # VERIFY BUY
    # ========================================================

    time.sleep(1)

    final_order = get_order(
        symbol,
        order_id
    )

    status = final_order.get(
        "status",
        "UNKNOWN"
    )

    executed_qty = Decimal(
        str(
            final_order.get(
                "executedQty",
                "0"
            )
        )
    )

    entry_price = filled_price(
        final_order
    )

    telegram(
        "🧾 BUY RESULT\n"
        f"🪙 {symbol}\n"
        f"🆔 {order_id}\n"
        f"📌 STATUS: {status}\n"
        f"📦 EXECUTED: "
        f"{executed_qty}\n"
        f"💵 AVG ENTRY: "
        f"{entry_price}"
    )

    if status != "FILLED":

        telegram(
            "⚠️ BUY IS NOT FILLED\n"
            "🛑 AUTO EXIT NOT STARTED"
        )

        return

    if executed_qty <= 0:

        raise RuntimeError(
            "BUY filled but executedQty is zero"
        )

    # ========================================================
    # START AUTO EXIT
    # ========================================================

    manage_position(
        symbol,
        market,
        executed_qty,
        entry_price
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        error = (
            "🚨 ATI BOT ERROR\n"
            f"⚡ {VERSION}\n"
            f"❌ {e}\n"
            f"🕐 {utc_now()}"
        )

        print(
            error,
            flush=True
        )

        telegram(error)

        raise
