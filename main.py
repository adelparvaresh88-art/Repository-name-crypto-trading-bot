import os
import time
import hmac
import hashlib
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.13
# REAL SPOT BUY
# FIXED USDT AMOUNT
# MIN_NOTIONAL + MIN_QTY + STEP_SIZE PROTECTION
# 5m CLOSED CANDLE SCAN
# TOP 10 CANDIDATES
# TELEGRAM HEARTBEAT
# ============================================================

VERSION = "V40.2.13"

BASE_URL = "https://api1.tabdeal.org"

EXCHANGE_INFO_PATH = "/r/api/v1/exchangeInfo"
TRADES_PATH = "/r/api/v1/trades"
ORDER_PATH = "/r/api/v1/order"

TIMEOUT = 12
MAX_WORKERS = 12

# User requested fixed amount: 0.50 USDT
ORDER_USDT_MIN = Decimal("0.50")

# Show maximum 10 candidates
TOP_N = 10

# Maximum one real/paper buy action per GitHub run
MAX_BUYS_PER_RUN = 1


# ============================================================
# ENV
# ============================================================

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

LIVE_RAW = os.getenv("LIVE_TRADING", "false").strip().lower()

LIVE_TRADING = LIVE_RAW in (
    "1",
    "true",
    "yes",
    "on",
)


# ============================================================
# ORDER AMOUNT
# ============================================================

try:
    CONFIGURED_AMOUNT = Decimal(
        os.getenv("ORDER_QTY", "0.50").strip()
    )
except InvalidOperation:
    CONFIGURED_AMOUNT = Decimal("0.50")

# Prevent old 0.001 setting from creating tiny orders.
ORDER_USDT = max(
    CONFIGURED_AMOUNT,
    ORDER_USDT_MIN
)


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": f"ATI-Crypto-Bot/{VERSION}"
    }
)


# ============================================================
# DECIMAL
# ============================================================

def D(value, default=Decimal("0")):
    try:
        return Decimal(str(value))
    except (
        InvalidOperation,
        TypeError,
        ValueError
    ):
        return default


def decimal_string(value):
    s = format(value, "f")

    if "." in s:
        s = s.rstrip("0").rstrip(".")

    return s or "0"


# ============================================================
# TIME
# ============================================================

def now_utc():
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def tg(message):

    if not TG_TOKEN or not TG_CHAT_ID:
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TG_TOKEN}/sendMessage"
    )

    try:

        response = session.post(
            url,
            data={
                "chat_id": TG_CHAT_ID,
                "text": message,
            },
            timeout=TIMEOUT,
        )

        return response.ok

    except Exception:

        return False


# ============================================================
# PUBLIC API
# ============================================================

def public_get(path, params=None):

    response = session.get(
        BASE_URL + path,
        params=params or {},
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# SIGNED API
# ============================================================

def signed_request(
    method,
    path,
    params=None,
):

    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDEAL_API_KEY / TABDEAL_API_SECRET missing"
        )

    p = dict(params or {})

    p["timestamp"] = int(
        time.time() * 1000
    )

    query = "&".join(
        f"{key}={p[key]}"
        for key in sorted(p)
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()

    p["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    method = method.upper()

    if method == "GET":

        response = session.get(
            BASE_URL + path,
            params=p,
            headers=headers,
            timeout=TIMEOUT,
        )

    elif method == "POST":

        response = session.post(
            BASE_URL + path,
            params=p,
            headers=headers,
            timeout=TIMEOUT,
        )

    else:

        raise RuntimeError(
            f"Unsupported method: {method}"
        )

    if not response.ok:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    return response.json()


# ============================================================
# EXCHANGE INFO
# ============================================================

def normalize_filters(item):

    filters = {}

    raw_filters = item.get(
        "filters",
        []
    )

    if isinstance(
        raw_filters,
        list
    ):

        for f in raw_filters:

            if not isinstance(
                f,
                dict
            ):
                continue

            filter_type = str(
                f.get(
                    "filterType",
                    ""
                )
            ).upper()

            if filter_type:
                filters[filter_type] = f

    # Direct LOT SIZE fallback
    if "LOT_SIZE" not in filters:

        if (
            "minQty" in item
            or "stepSize" in item
        ):

            filters["LOT_SIZE"] = {
                "minQty": item.get(
                    "minQty",
                    "0"
                ),
                "stepSize": item.get(
                    "stepSize",
                    "0"
                ),
            }

    # Direct MIN NOTIONAL fallback
    if "MIN_NOTIONAL" not in filters:

        if (
            "minNotional" in item
            or "notional" in item
        ):

            filters["MIN_NOTIONAL"] = {
                "minNotional": item.get(
                    "minNotional",
                    item.get(
                        "notional",
                        "0"
                    )
                )
            }

    return filters


def load_markets():

    data = public_get(
        EXCHANGE_INFO_PATH
    )

    if isinstance(
        data,
        dict
    ):

        items = (
            data.get("symbols")
            or data.get("data")
            or data.get("result")
            or []
        )

    else:

        items = data

    markets = []

    for item in items:

        if not isinstance(
            item,
            dict
        ):
            continue

        symbol = str(
            item.get("symbol")
            or item.get("market")
            or item.get("code")
            or ""
        ).upper()

        if not symbol.endswith("USDT"):
            continue

        status = str(
            item.get(
                "status",
                "TRADING"
            )
        ).upper()

        if status not in (
            "",
            "TRADING",
            "ENABLED",
            "ACTIVE",
        ):
            continue

        markets.append(
            {
                "symbol": symbol,
                "filters": normalize_filters(
                    item
                ),
                "raw": item,
            }
        )

    unique = {}

    for market in markets:

        unique[
            market["symbol"]
        ] = market

    return list(
        unique.values()
    )


# ============================================================
# TRADES
# ============================================================

def extract_trades(data):

    if isinstance(
        data,
        dict
    ):

        for key in (
            "data",
            "trades",
            "result",
            "items",
        ):

            if isinstance(
                data.get(key),
                list
            ):

                return data[key]

    if isinstance(
        data,
        list
    ):
        return data

    return []


def trade_fields(trade):

    if not isinstance(
        trade,
        dict
    ):
        return None, None, None

    price = D(
        trade.get("price")
        or trade.get("p")
        or trade.get("lastPrice")
    )

    quantity = D(
        trade.get("qty")
        or trade.get("quantity")
        or trade.get("q")
        or trade.get("amount")
    )

    timestamp = (
        trade.get("time")
        or trade.get("timestamp")
        or trade.get("T")
        or trade.get("createdAt")
    )

    try:

        timestamp = int(
            float(timestamp)
        )

    except (
        TypeError,
        ValueError
    ):

        timestamp = 0

    # Convert seconds to milliseconds
    if (
        0 < timestamp
        < 10_000_000_000
    ):

        timestamp *= 1000

    return (
        price,
        quantity,
        timestamp
    )


# ============================================================
# 5 MINUTE CLOSED CANDLES
# ============================================================

def build_closed_candles(
    trades
):

    buckets = {}

    for trade in trades:

        price, quantity, timestamp = (
            trade_fields(trade)
        )

        if price <= 0:
            continue

        if timestamp <= 0:
            continue

        bucket = (
            timestamp // 300_000
        )

        if bucket not in buckets:

            buckets[bucket] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": D("0"),
            }

        candle = buckets[bucket]

        candle["high"] = max(
            candle["high"],
            price
        )

        candle["low"] = min(
            candle["low"],
            price
        )

        candle["close"] = price

        candle["volume"] += quantity

    if not buckets:
        return []

    current_bucket = (
        int(time.time() * 1000)
        // 300_000
    )

    closed = []

    for bucket in sorted(
        buckets
    ):

        # Current candle is excluded.
        if bucket < current_bucket:

            closed.append(
                buckets[bucket]
            )

    return closed


# ============================================================
# SYMBOL ANALYSIS
# ============================================================

def analyze_symbol(
    market
):

    symbol = market["symbol"]

    try:

        raw = public_get(
            TRADES_PATH,
            {
                "symbol": symbol,
                "limit": 1000,
            }
        )

        trades = extract_trades(
            raw
        )

        candles = build_closed_candles(
            trades
        )

        if len(candles) < 5:
            return None

        closes = [
            c["close"]
            for c in candles
        ]

        last = closes[-1]

        def percent_from(old):

            if old <= 0:
                return Decimal("0")

            return (
                last / old
                - Decimal("1")
            ) * Decimal("100")

        move_5m = percent_from(
            closes[-1]
        )

        move_15m = (
            percent_from(
                closes[-3]
            )
            if len(closes) >= 3
            else Decimal("0")
        )

        move_1h = (
            percent_from(
                closes[-12]
            )
            if len(closes) >= 12
            else percent_from(
                closes[0]
            )
        )

        previous_candles = candles[-6:-1]

        if not previous_candles:
            return None

        recent_high = max(
            c["high"]
            for c in previous_candles
        )

        recent_low = min(
            c["low"]
            for c in previous_candles
        )

        breakout = (
            last > recent_high
        )

        near_breakout = (
            last
            >= recent_high
            * Decimal("0.998")
        )

        higher_lows = (
            candles[-1]["low"]
            >= candles[-2]["low"]
            and
            candles[-2]["low"]
            >= candles[-3]["low"]
        )

        score = 0

        # 5m momentum
        if move_5m > Decimal("0.30"):
            score += 3

        if move_5m > Decimal("0.80"):
            score += 2

        # 15m momentum
        if move_15m > Decimal("0.50"):
            score += 3

        if move_15m > Decimal("1.50"):
            score += 2

        # 1h momentum
        if move_1h > Decimal("1.00"):
            score += 2

        if move_1h > Decimal("3.00"):
            score += 2

        # Breakout
        if breakout:

            score += 4

        elif near_breakout:

            score += 2

        # Structure
        if higher_lows:
            score += 2

        # Anti-chase / negative momentum
        if move_5m < Decimal("-1.0"):
            score -= 4

        if move_15m < Decimal("-2.0"):
            score -= 3

        # Minimum opportunity score
        if score < 7:
            return None

        return {
            "symbol": symbol,
            "price": last,
            "score": score,
            "move5": move_5m,
            "move15": move_15m,
            "move1h": move_1h,
            "breakout": breakout,
            "near_breakout": near_breakout,
            "higher_lows": higher_lows,
            "filters": market["filters"],
        }

    except Exception:

        return None


# ============================================================
# QUANTITY / STEP SIZE / MIN NOTIONAL
# ============================================================

def floor_step(
    value,
    step
):

    if step <= 0:
        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


def order_quantity(
    signal
):

    filters = signal["filters"]

    lot = filters.get(
        "LOT_SIZE",
        {}
    )

    min_qty = D(
        lot.get(
            "minQty",
            "0"
        )
    )

    step_size = D(
        lot.get(
            "stepSize",
            "0"
        )
    )

    min_notional_filter = (
        filters.get(
            "MIN_NOTIONAL"
        )
        or
        filters.get(
            "NOTIONAL"
        )
        or {}
    )

    min_notional = D(
        min_notional_filter.get(
            "minNotional"
        )
        or
        min_notional_filter.get(
            "notional"
        )
        or "0"
    )

    price = signal["price"]

    if price <= 0:

        return (
            None,
            "invalid price"
        )

    # Fixed USDT -> quantity
    raw_quantity = (
        ORDER_USDT
        / price
    )

    # Floor to exchange step size
    quantity = floor_step(
        raw_quantity,
        step_size
    )

    # Never send zero
    if quantity <= 0:

        return (
            None,
            f"quantity "
            f"{decimal_string(quantity)} "
            f"<= 0"
        )

    # Minimum quantity
    if (
        min_qty > 0
        and quantity < min_qty
    ):

        return (
            None,
            f"quantity "
            f"{decimal_string(quantity)} "
            f"< minimum "
            f"{decimal_string(min_qty)}"
        )

    # Actual order value after step-size rounding
    actual_notional = (
        quantity * price
    )

    # Minimum notional
    if (
        min_notional > 0
        and actual_notional
        < min_notional
    ):

        return (
            None,
            f"order value "
            f"{decimal_string(actual_notional)} "
            f"< MIN_NOTIONAL "
            f"{decimal_string(min_notional)}"
        )

    return (
        quantity,
        None
    )


# ============================================================
# MARKET BUY
# ============================================================

def buy_market(
    signal
):

    symbol = signal["symbol"]

    quantity, reason = (
        order_quantity(signal)
    )

    if quantity is None:

        return {
            "ok": False,
            "skipped": True,
            "reason": reason,
            "symbol": symbol,
        }

    # Paper mode
    if not LIVE_TRADING:

        return {
            "ok": True,
            "paper": True,
            "symbol": symbol,
            "qty": quantity,
            "price": signal["price"],
        }

    # Real order
    result = signed_request(
        "POST",
        ORDER_PATH,
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": decimal_string(
                quantity
            ),
        }
    )

    return {
        "ok": True,
        "paper": False,
        "symbol": symbol,
        "qty": quantity,
        "price": signal["price"],
        "response": result,
    }


# ============================================================
# TELEGRAM FORMAT
# ============================================================

def format_candidate(
    candidate,
    rank
):

    mode = (
        "BREAKOUT"
        if candidate["breakout"]
        else "WATCH"
    )

    return (
        f"{rank}. "
        f"{candidate['symbol']} | "
        f"SCORE {candidate['score']} | "
        f"{mode}\n"
        f"   5m "
        f"{candidate['move5']:.2f}% | "
        f"15m "
        f"{candidate['move15']:.2f}% | "
        f"1h "
        f"{candidate['move1h']:.2f}% | "
        f"PRICE "
        f"{candidate['price']}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    # --------------------------------------------------------
    # STARTUP MESSAGE
    # --------------------------------------------------------

    tg(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED CANDLE: YES\n"
        f"💵 ORDER MODE: FIXED USDT AMOUNT\n"
        f"💰 ORDER AMOUNT: "
        f"{ORDER_USDT} USDT\n"
        f"🔧 REAL ORDERS: "
        f"{'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"
        f"🕐 {now_utc()}"
    )

    # --------------------------------------------------------
    # LOAD MARKETS
    # --------------------------------------------------------

    try:

        markets = load_markets()

    except Exception as error:

        tg(
            f"🚨 ATI ERROR {VERSION}\n\n"
            f"❌ EXCHANGE INFO FAILED\n"
            f"{str(error)[:700]}\n\n"
            f"🕐 {now_utc()}"
        )

        raise

    tg(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: "
        f"{len(markets)}\n"
        f"📥 REQUESTED: "
        f"{len(markets)}\n"
        f"💰 FIXED ORDER: "
        f"{ORDER_USDT} USDT\n"
        f"🔧 REAL MODE: "
        f"{'ON' if LIVE_TRADING else 'OFF'}\n"
        f"🕐 {now_utc()}"
    )

    # --------------------------------------------------------
    # SCAN ALL MARKETS
    # --------------------------------------------------------

    candidates = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                analyze_symbol,
                market
            )
            for market in markets
        ]

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result:
                    candidates.append(
                        result
                    )

            except Exception:

                pass

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    candidates.sort(
        key=lambda item: (
            item["score"],
            item["move15"],
            item["move5"],
        ),
        reverse=True,
    )

    top = candidates[:TOP_N]

    # --------------------------------------------------------
    # NO CANDIDATES
    # --------------------------------------------------------

    if not top:

        tg(
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"✅ SCAN FINISHED\n"
            f"📊 MARKETS: "
            f"{len(markets)}\n"
            f"🚫 CANDIDATES: 0\n"
            f"💰 ORDER: "
            f"{ORDER_USDT} USDT\n"
            f"🔧 REAL MODE: "
            f"{'ON' if LIVE_TRADING else 'OFF'}\n\n"
            f"💓 HEARTBEAT OK\n"
            f"🕐 {now_utc()}"
        )

        return

    # --------------------------------------------------------
    # TOP 10
    # --------------------------------------------------------

    candidate_text = "\n".join(
        format_candidate(
            candidate,
            index + 1
        )
        for index, candidate
        in enumerate(top)
    )

    tg(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📊 SCAN FINISHED\n"
        f"📈 MARKETS: "
        f"{len(markets)}\n"
        f"🚨 CANDIDATES: "
        f"{len(candidates)}\n\n"
        f"🏆 TOP {len(top)}:\n"
        f"{candidate_text}\n\n"
        f"🕐 {now_utc()}"
    )

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    buy_actions = 0

    for signal in top:

        if buy_actions >= MAX_BUYS_PER_RUN:
            break

        try:

            quantity, reason = (
                order_quantity(signal)
            )

            # MIN_NOTIONAL / MIN_QTY / STEP SIZE failed
            if quantity is None:

                tg(
                    f"⚠️ ORDER SKIPPED\n\n"
                    f"🪙 "
                    f"{signal['symbol']}\n"
                    f"💰 FIXED AMOUNT: "
                    f"{ORDER_USDT} USDT\n"
                    f"❌ {reason}\n\n"
                    f"ℹ️ No order was sent."
                )

                continue

            # Candidate message
            tg(
                f"🚨 ATI BUY CANDIDATE\n\n"
                f"🟢 "
                f"{signal['symbol']}\n"
                f"💰 PRICE: "
                f"{signal['price']}\n"
                f"📊 SCORE: "
                f"{signal['score']}\n"
                f"📈 5m: "
                f"{signal['move5']:.2f}%\n"
                f"📈 15m: "
                f"{signal['move15']:.2f}%\n"
                f"📈 1h: "
                f"{signal['move1h']:.2f}%\n"
                f"💵 ORDER VALUE: "
                f"{ORDER_USDT} USDT\n"
                f"🔢 QUANTITY: "
                f"{decimal_string(quantity)}\n"
                f"🔧 REAL MODE: "
                f"{'ON' if LIVE_TRADING else 'OFF'}"
            )

            result = buy_market(
                signal
            )

            if result.get(
                "skipped"
            ):
                continue

            # ------------------------------------------------
            # PAPER
            # ------------------------------------------------

            if result.get("paper"):

                tg(
                    f"📝 PAPER BUY\n\n"
                    f"🪙 "
                    f"{signal['symbol']}\n"
                    f"💵 VALUE: "
                    f"{ORDER_USDT} USDT\n"
                    f"🔢 QTY: "
                    f"{decimal_string(result['qty'])}\n"
                    f"💰 PRICE: "
                    f"{result['price']}\n"
                    f"🕐 {now_utc()}"
                )

            # ------------------------------------------------
            # REAL
            # ------------------------------------------------

            else:

                response = result.get(
                    "response",
                    {}
                )

                order_id = (
                    response.get("orderId")
                    or response.get("id")
                    or response.get("order_id")
                    or "N/A"
                )

                tg(
                    f"🟢 REAL BUY SENT\n\n"
                    f"🪙 "
                    f"{signal['symbol']}\n"
                    f"💵 VALUE: "
                    f"{ORDER_USDT} USDT\n"
                    f"🔢 QTY: "
                    f"{decimal_string(result['qty'])}\n"
                    f"💰 SIGNAL PRICE: "
                    f"{result['price']}\n"
                    f"🆔 ORDER ID: "
                    f"{order_id}\n"
                    f"🕐 {now_utc()}"
                )

            buy_actions += 1

        except Exception as error:

            tg(
                f"🚨 REAL TRADE ERROR\n\n"
                f"🪙 "
                f"{signal['symbol']}\n"
                f"❌ "
                f"{str(error)[:900]}\n"
                f"🕐 {now_utc()}"
            )

    # --------------------------------------------------------
    # FINAL HEARTBEAT
    # --------------------------------------------------------

    tg(
        f"💓 ATI HEARTBEAT {VERSION}\n\n"
        f"✅ RUN FINISHED\n"
        f"📊 MARKETS: "
        f"{len(markets)}\n"
        f"🚨 CANDIDATES: "
        f"{len(candidates)}\n"
        f"🟢 BUY ACTIONS: "
        f"{buy_actions}\n"
        f"💵 FIXED ORDER: "
        f"{ORDER_USDT} USDT\n"
        f"🔧 REAL MODE: "
        f"{'ON' if LIVE_TRADING else 'OFF'}\n"
        f"🕐 {now_utc()}"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
