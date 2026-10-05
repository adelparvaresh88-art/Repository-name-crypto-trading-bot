import os
import time
import hmac
import hashlib
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.62-FIXED
# TABDEAL SPOT
# REAL MARKET BUY
# NO EMA
# 5m CLOSED CANDLE
# ============================================================

VERSION = "V40.2.62-FIXED"

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

SCAN_UNIVERSE = int(os.getenv("SCAN_UNIVERSE", "25"))
MIN_CANDLES = 12
MIN_SCORE = int(os.getenv("MIN_SCORE", "7"))

MAX_REAL_ORDERS_PER_RUN = 1

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/" + VERSION
    }
)

SERVER_OFFSET_MS = 0


# ============================================================
# TIME
# ============================================================

def now_ms():
    return int(time.time() * 1000) + SERVER_OFFSET_MS


def utc_now():
    return datetime.now(timezone.utc).strftime(
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
        print(text, flush=True)
        return False

    try:

        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": text,
            },
            timeout=15,
        )

        print(
            "TELEGRAM:",
            r.status_code,
            r.text[:300],
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
# HTTP HELPERS
# ============================================================

def json_response(r):

    try:
        return r.json()

    except Exception:

        return {
            "_http": r.status_code,
            "_text": r.text[:500],
        }


def public_get(path, params=None):

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
        server_time - local_time
    )

    print(
        f"🕐 SERVER OFFSET: {SERVER_OFFSET_MS} ms",
        flush=True,
    )

    return server_time


# ============================================================
# API CREDENTIALS
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

    os.environ["API_KEY"] = key
    os.environ["API_SECRET"] = secret

    print(
        "🔑 API PAIR: TABDIL/TABDEAL ENV",
        flush=True,
    )


# ============================================================
# HMAC SIGNATURE
# ============================================================

def sign_params(params):

    query = urlencode(params)

    signature = hmac.new(
        os.environ["API_SECRET"].encode(),
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

    api_key = os.environ["API_KEY"]

    params = dict(params or {})

    params["timestamp"] = now_ms()

    query = sign_params(params)

    url = TRADE_ROOT + path

    headers = {
        "X-MBX-APIKEY": api_key
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
                    "application/x-www-form-urlencoded",
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
        and data.get("code") not in (None, 0)
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
            f"canTrade is not true: {data}"
        )

    return data


# ============================================================
# USDT BALANCE
# ============================================================

def usdt_balance(account):

    for balance in account.get(
        "balances",
        [],
    ):

        asset = str(
            balance.get(
                "asset",
                "",
            )
        ).upper()

        if asset == "USDT":

            return Decimal(
                str(
                    balance.get(
                        "free",
                        "0",
                    )
                )
            )

    return Decimal("0")


# ============================================================
# EXCHANGE INFO
# ============================================================

def exchange_info():

    return public_get(
        PUBLIC_ROOT + "/exchangeInfo"
    )


# ============================================================
# SYMBOL HELPERS
# ============================================================

def normalize_symbol(value):

    return str(
        value or ""
    ).replace(
        "_",
        "",
    ).upper()


def market_list(info):

    if isinstance(info, list):

        raw = info

    elif isinstance(info, dict):

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
            dict,
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
                "TRADING",
            )
        ).upper()

        if status not in (
            "TRADING",
            "ACTIVE",
            "ENABLED",
        ):
            continue

        result.append(market)

    return result


def market_symbol(market):

    return normalize_symbol(
        market.get("symbol")
        or market.get("market")
        or market.get("name")
    )


# ============================================================
# RECENT TRADES
# ============================================================

def recent_trades(symbol):

    return public_get(
        PUBLIC_ROOT + "/trades",
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )


def trade_rows(data):

    if isinstance(data, list):

        return data

    if isinstance(data, dict):

        return (
            data.get("data")
            or data.get("trades")
            or []
        )

    return []


# ============================================================
# TRADES -> 5 MIN CANDLES
# ============================================================

def make_candles(rows):

    buckets = {}

    for trade in rows:

        try:

            price = Decimal(
                str(trade["price"])
            )

            qty = Decimal(
                str(
                    trade.get(
                        "qty",
                        trade.get(
                            "quantity",
                            "0",
                        ),
                    )
                )
            )

            trade_time = int(
                trade.get(
                    "time",
                    trade.get(
                        "timestamp"
                    ),
                )
            )

        except Exception:

            continue

        bucket = (
            trade_time // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = {
                "t": bucket,
                "o": price,
                "h": price,
                "l": price,
                "c": price,
                "v": Decimal("0"),
                "n": 0,
            }

        candle = buckets[bucket]

        candle["h"] = max(
            candle["h"],
            price,
        )

        candle["l"] = min(
            candle["l"],
            price,
        )

        candle["c"] = price

        candle["v"] += qty

        candle["n"] += 1

    candles = [
        buckets[k]
        for k in sorted(buckets)
    ]

    current_bucket = (
        int(time.time() * 1000)
        // 300000
    ) * 300000

    candles = [
        c
        for c in candles
        if c["t"] < current_bucket
    ]

    return candles


# ============================================================
# PERCENT
# ============================================================

def pct(a, b):

    if b == 0:
        return Decimal("0")

    return (
        (a / b)
        - Decimal("1")
    ) * Decimal("100")


# ============================================================
# BUY SIGNAL
# ============================================================

def signal(candles):

    if len(candles) < MIN_CANDLES:
        return None

    last = candles[-1]
    previous = candles[-2]

    lookback = candles[-7:-1]

    recent_high = max(
        c["h"]
        for c in lookback
    )

    recent_low = min(
        c["l"]
        for c in lookback
    )

    score = 0
    reasons = []

    # --------------------------------------------------------
    # BOS
    # --------------------------------------------------------

    if last["c"] > recent_high:

        score += 4
        reasons.append("BOS")

    elif (
        last["c"]
        >= recent_high
        * Decimal("0.998")
    ):

        score += 2
        reasons.append("NEAR_BOS")

    else:

        return None

    # --------------------------------------------------------
    # DIRECTION
    # --------------------------------------------------------

    if last["c"] > previous["c"]:

        score += 1
        reasons.append("UP")

    # --------------------------------------------------------
    # STRONG CLOSED CANDLE
    # --------------------------------------------------------

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
        and body / candle_range
        >= Decimal("0.55")
    ):

        score += 2
        reasons.append(
            "STRONG_CLOSE"
        )

    # --------------------------------------------------------
    # GREEN CANDLE
    # --------------------------------------------------------

    if last["c"] > last["o"]:

        score += 1
        reasons.append("GREEN")

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    move = pct(
        last["c"],
        previous["c"],
    )

    if move > Decimal("0.15"):

        score += 1
        reasons.append("MOMENTUM")

    # --------------------------------------------------------
    # CHASE PROTECTION
    # --------------------------------------------------------

    if move > Decimal("2.2"):

        return None

    if score < MIN_SCORE:

        return None

    return {
        "symbol": None,
        "price": last["c"],
        "score": score,
        "reasons": reasons,
        "move": move,
        "high": recent_high,
        "low": recent_low,
    }


# ============================================================
# MARKET FILTERS
# ============================================================

def step_from_market(market):

    filters = (
        market.get("filters")
        or []
    )

    for f in filters:

        filter_type = str(
            f.get(
                "filterType",
                f.get(
                    "type",
                    "",
                ),
            )
        ).upper()

        if filter_type in (
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

                    except InvalidOperation:

                        pass

    for key in (
        "stepSize",
        "quantityStep",
        "baseAssetPrecision",
    ):

        if market.get(key):

            try:

                value = Decimal(
                    str(
                        market[key]
                    )
                )

                if value > 1:

                    return (
                        Decimal("1")
                        / (
                            Decimal("10")
                            ** int(value)
                        )
                    )

                return value

            except Exception:

                pass

    return Decimal(
        "0.00000001"
    )


def min_qty_from_market(market):

    filters = (
        market.get("filters")
        or []
    )

    for f in filters:

        filter_type = str(
            f.get(
                "filterType",
                f.get(
                    "type",
                    "",
                ),
            )
        ).upper()

        if filter_type in (
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

                    except InvalidOperation:

                        pass

    return Decimal("0")


# ============================================================
# QUANTITY
# ============================================================

def floor_step(
    value,
    step,
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


def fmt_decimal(value):

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


def build_quantity(
    market,
    price,
):

    step = step_from_market(
        market
    )

    min_qty = min_qty_from_market(
        market
    )

    quantity = floor_step(
        ORDER_VALUE / price,
        step,
    )

    if quantity < min_qty:

        quantity = min_qty

    return quantity


# ============================================================
# REAL MARKET BUY
# ============================================================

def place_market_buy(
    symbol,
    quantity,
):

    return signed_request(
        "POST",
        "/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": fmt_decimal(
                quantity
            ),
        },
    )


# ============================================================
# ORDER STATUS
# ============================================================

def get_order(
    symbol,
    order_id,
):

    return signed_request(
        "GET",
        "/order",
        {
            "symbol": symbol,
            "orderId": int(order_id),
        },
    )


# ============================================================
# ORDER REPORT
# ============================================================

def format_order(order):

    status = order.get(
        "status",
        "UNKNOWN",
    )

    order_id = order.get(
        "orderId",
        "?",
    )

    executed = order.get(
        "executedQty",
        "0",
    )

    quote = order.get(
        "cummulativeQuoteQty",
        order.get(
            "cumulativeQuoteQty",
            "0",
        ),
    )

    return (
        "🧾 ORDER RESULT\n"
        f"🆔 {order_id}\n"
        f"📌 STATUS: {status}\n"
        f"📦 EXECUTED: {executed}\n"
        f"💵 QUOTE: {quote}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        f"⚡ ATI BOT {VERSION}",
        flush=True,
    )

    print(
        "📡 TABDEAL SPOT",
        flush=True,
    )

    print(
        f"🔓 LIVE TRADING: {LIVE_TRADING}",
        flush=True,
    )

    print(
        f"💵 ORDER VALUE: {ORDER_VALUE} USDT",
        flush=True,
    )

    print(
        f"🕐 {utc_now()}",
        flush=True,
    )

    telegram(
        f"💓 ATI ALIVE\n"
        f"⚡ {VERSION}\n"
        f"📡 TABDEAL SPOT\n"
        f"🔓 LIVE TRADING: {LIVE_TRADING}\n"
        f"💵 ORDER: {ORDER_VALUE} USDT\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # CREDENTIALS
    # --------------------------------------------------------

    load_credentials()

    # --------------------------------------------------------
    # SERVER TIME
    # --------------------------------------------------------

    sync_server_time()

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    account = auth_check()

    balance = usdt_balance(
        account
    )

    print(
        f"✅ AUTH SUCCESS | canTrade={account.get('canTrade')}",
        flush=True,
    )

    print(
        f"💰 USDT FREE: {balance}",
        flush=True,
    )

    telegram(
        "✅ AUTH SUCCESS\n"
        f"🔓 canTrade={account.get('canTrade')}\n"
        f"💰 USDT FREE: {balance}"
    )

    # --------------------------------------------------------
    # BALANCE CHECK
    # --------------------------------------------------------

    if balance < ORDER_VALUE:

        msg = (
            "❌ USDT BALANCE TOO LOW\n"
            f"💰 FREE: {balance}\n"
            f"💵 REQUIRED: {ORDER_VALUE}"
        )

        telegram(msg)

        return

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    info = exchange_info()

    markets = market_list(
        info
    )

    print(
        f"📊 USDT MARKETS: {len(markets)}",
        flush=True,
    )

    telegram(
        f"📊 MARKETS: {len(markets)}\n"
        f"🔎 SCANNING: "
        f"{min(SCAN_UNIVERSE, len(markets))}"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

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

                result["symbol"] = symbol
                result["market"] = market

                candidates.append(
                    result
                )

                print(
                    f"🎯 {symbol} "
                    f"score={result['score']} "
                    f"price={result['price']} "
                    f"{','.join(result['reasons'])}",
                    flush=True,
                )

        except Exception as e:

            print(
                f"⚠️ {symbol}: {e}",
                flush=True,
            )

    # --------------------------------------------------------
    # NO BUY
    # --------------------------------------------------------

    if not candidates:

        msg = (
            "🔎 SCAN FINISHED\n"
            "⚪ NO BUY\n"
            f"📊 SCANNED: "
            f"{min(SCAN_UNIVERSE, len(markets))}\n"
            f"🕐 {utc_now()}"
        )

        telegram(msg)

        return

    # --------------------------------------------------------
    # BEST SIGNAL
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    best = candidates[0]

    symbol = best["symbol"]

    price = best["price"]

    market = best["market"]

    quantity = build_quantity(
        market,
        price,
    )

    notional = (
        quantity * price
    )

    candidate_message = (
        "🎯 BUY CANDIDATE\n"
        f"🪙 {symbol}\n"
        f"💵 PRICE: {price}\n"
        f"📦 QTY: {fmt_decimal(quantity)}\n"
        f"💰 NOTIONAL: {notional:.8f}\n"
        f"⭐ SCORE: {best['score']}\n"
        f"🧠 {', '.join(best['reasons'])}"
    )

    print(
        candidate_message,
        flush=True,
    )

    telegram(
        candidate_message
    )

    # --------------------------------------------------------
    # PAPER MODE
    # --------------------------------------------------------

    if not LIVE_TRADING:

        telegram(
            "🟡 PAPER ONLY\n"
            "🚫 REAL ORDER NOT SENT"
        )

        return

    # --------------------------------------------------------
    # SAFETY CHECKS
    # --------------------------------------------------------

    if notional <= 0:

        raise RuntimeError(
            "Calculated order notional is zero"
        )

    if notional > balance:

        raise RuntimeError(
            f"Calculated notional "
            f"{notional} exceeds "
            f"USDT balance {balance}"
        )

    # --------------------------------------------------------
    # REAL ORDER
    # --------------------------------------------------------

    print(
        "🚀 SENDING REAL MARKET BUY",
        flush=True,
    )

    print(
        f"🪙 SYMBOL: {symbol}",
        flush=True,
    )

    print(
        f"📦 QUANTITY: {fmt_decimal(quantity)}",
        flush=True,
    )

    try:

        order = place_market_buy(
            symbol,
            quantity,
        )

    except Exception as e:

        error_message = (
            "🚨 REAL BUY FAILED\n"
            f"🪙 {symbol}\n"
            f"❌ {e}"
        )

        telegram(
            error_message
        )

        raise

    # --------------------------------------------------------
    # ACCEPTED
    # --------------------------------------------------------

    order_id = order.get(
        "orderId"
    )

    status = order.get(
        "status",
        "UNKNOWN",
    )

    telegram(
        "✅ ORDER ACCEPTED BY TABDEAL\n"
        f"🪙 {symbol}\n"
        f"🆔 {order_id}\n"
        f"📌 STATUS: {status}"
    )

    # --------------------------------------------------------
    # VERIFY ORDER
    # --------------------------------------------------------

    if order_id is not None:

        time.sleep(1)

        try:

            final_order = get_order(
                symbol,
                order_id,
            )

            report = format_order(
                final_order
            )

            print(
                report,
                flush=True,
            )

            telegram(report)

        except Exception as e:

            telegram(
                "⚠️ ORDER SENT BUT "
                "STATUS CHECK FAILED\n"
                f"🆔 {order_id}\n"
                f"❌ {e}"
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
            flush=True,
        )

        telegram(error)

        raise
