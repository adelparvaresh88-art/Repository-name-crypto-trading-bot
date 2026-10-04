import os
import time
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.51-REAL
# TABDEAL SPOT
#
# AUTH:
# TABDIL -> TABDEAL fallback
# SERVER TIME
# recvWindow = 5000
# HMAC SHA256
#
# STRATEGY:
# Trend -> REAL BOS -> Pullback -> Continuation -> CLOSED
#
# EMA: OFF
# TIMEFRAME: 5m CLOSED CANDLES
# REAL ORDER: ENABLED
# ORDER TARGET: 2 USDT
# MAX REAL BUY PER RUN: 1
# ============================================================

VERSION = "V40.2.51-REAL"

BASE = "https://api1.tabdeal.org"
API_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 15
RECV_WINDOW = 5000

SCAN_LIMIT = int(os.getenv("SCAN_LIMIT", "40"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "12"))
MIN_SCORE = float(os.getenv("MIN_SCORE", "11"))

ORDER_USDT = Decimal(
    os.getenv("ORDER_USDT", "2")
)

MAX_REAL_BUYS_PER_RUN = 1

LIVE_TRADING = (
    os.getenv(
        "LIVE_TRADING",
        "false"
    )
    .strip()
    .lower()
    in ("1", "true", "yes", "on")
)

BUY_LOCK = False


# ============================================================
# KEYS
# ============================================================

TABDIL_KEY = os.getenv(
    "TABDIL_API_KEY",
    ""
).strip()

TABDIL_SECRET = os.getenv(
    "TABDIL_API_SECRET",
    ""
).strip()

TABDEAL_KEY = os.getenv(
    "TABDEAL_API_KEY",
    ""
).strip()

TABDEAL_SECRET = os.getenv(
    "TABDEAL_API_SECRET",
    ""
).strip()


# IMPORTANT:
# TABDIL is the first/primary pair.
if TABDIL_KEY and TABDIL_SECRET:
    API_KEY = TABDIL_KEY
    API_SECRET = TABDIL_SECRET
    AUTH_PAIR = "TABDIL"
elif TABDEAL_KEY and TABDEAL_SECRET:
    API_KEY = TABDEAL_KEY
    API_SECRET = TABDEAL_SECRET
    AUTH_PAIR = "TABDEAL"
else:
    API_KEY = ""
    API_SECRET = ""
    AUTH_PAIR = "NONE"


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


def telegram(message):

    print(message)

    if not TELEGRAM_BOT_TOKEN:
        return

    if not TELEGRAM_CHAT_ID:
        return

    try:

        requests.post(
            "https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}/sendMessage",
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


# ============================================================
# HELPERS
# ============================================================

def now_utc():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def D(value, default="0"):

    try:
        return Decimal(str(value))
    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ):
        return Decimal(default)


def fmt(value):

    value = D(value)

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

    return text or "0"


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


# ============================================================
# PUBLIC REQUEST
# ============================================================

def public_get(
    path,
    params=None
):

    response = requests.get(
        BASE + path,
        params=params or {},
        timeout=TIMEOUT,
    )

    if response.status_code >= 400:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text}"
        )

    return response.json()


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():

    data = public_get(
        "/api/v1/time"
    )

    if isinstance(data, dict):

        for key in (
            "serverTime",
            "server_time",
            "timestamp",
            "time",
        ):

            if key in data:

                return int(
                    data[key]
                )

    if isinstance(
        data,
        (int, float)
    ):

        return int(data)

    raise RuntimeError(
        f"Cannot read server time: {data}"
    )


# ============================================================
# HMAC
#
# IMPORTANT:
# Sign the EXACT query string.
# Do NOT sort the parameters.
#
# Successful pattern:
#
# timestamp
# recvWindow
# optional order params
#
# urlencode()
# HMAC SHA256
# ============================================================

def sign_params(
    params
):

    query = urlencode(
        params
    )

    return hmac.new(
        API_SECRET.encode(
            "utf-8"
        ),
        query.encode(
            "utf-8"
        ),
        hashlib.sha256,
    ).hexdigest()


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(
    method,
    path,
    params=None,
):

    if not API_KEY:
        raise RuntimeError(
            "API KEY missing"
        )

    if not API_SECRET:
        raise RuntimeError(
            "API SECRET missing"
        )

    # IMPORTANT:
    # Keep insertion order.
    data = {}

    data["timestamp"] = (
        get_server_time()
    )

    data["recvWindow"] = (
        RECV_WINDOW
    )

    if params:

        for key, value in params.items():

            data[key] = value

    signature = sign_params(
        data
    )

    data["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type":
            "application/x-www-form-urlencoded",
    }

    method = method.upper()

    url = BASE + path

    if method == "GET":

        response = requests.get(
            url,
            params=data,
            headers=headers,
            timeout=TIMEOUT,
        )

    elif method == "POST":

        response = requests.post(
            url,
            data=data,
            headers=headers,
            timeout=TIMEOUT,
        )

    else:

        response = requests.request(
            method,
            url,
            data=data,
            headers=headers,
            timeout=TIMEOUT,
        )

    if response.status_code >= 400:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text}"
        )

    try:
        return response.json()
    except Exception:
        return response.text


# ============================================================
# ACCOUNT
# ============================================================

def get_account():

    return signed_request(
        "GET",
        "/r/api/v1/account",
    )


def get_free_usdt(
    account=None
):

    if account is None:

        account = get_account()

    balances = account.get(
        "balances",
        account.get(
            "assets",
            []
        )
    )

    for balance in balances:

        asset = str(
            balance.get(
                "asset",
                balance.get(
                    "currency",
                    ""
                )
            )
        ).upper()

        if asset == "USDT":

            return D(
                balance.get(
                    "free",
                    balance.get(
                        "available",
                        "0"
                    )
                )
            )

    return Decimal("0")


# ============================================================
# AUTH TEST
# ============================================================

def auth_test():

    telegram(
        "🔐 AUTH TEST\n"
        f"🔑 PAIR: {AUTH_PAIR}\n"
        f"🕐 {now_utc()}"
    )

    account = get_account()

    can_trade = account.get(
        "canTrade",
        account.get(
            "can_trade",
            True
        )
    )

    balance = get_free_usdt(
        account
    )

    telegram(
        "✅ AUTH SUCCESS\n"
        f"🔑 PAIR: {AUTH_PAIR}\n"
        f"🔓 canTrade={can_trade}\n"
        f"💰 FREE USDT: {balance}"
    )

    if can_trade is False:

        raise RuntimeError(
            "API account cannot trade"
        )

    return account


# ============================================================
# MARKETS
# ============================================================

def get_usdt_markets():

    data = public_get(
        "/api/v1/exchangeInfo"
    )

    if isinstance(
        data,
        dict
    ):

        symbols = data.get(
            "symbols",
            data.get(
                "data",
                []
            )
        )

    else:

        symbols = data

    markets = []

    for item in symbols:

        if not isinstance(
            item,
            dict
        ):
            continue

        symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).upper()

        status = str(
            item.get(
                "status",
                "TRADING"
            )
        ).upper()

        if not symbol.endswith(
            "USDT"
        ):
            continue

        if status not in (
            "TRADING",
            "ENABLED",
            "1",
            "",
        ):
            continue

        markets.append(item)

    return markets


# ============================================================
# TRADES
# ============================================================

def get_trades(
    symbol
):

    try:

        data = public_get(
            "/api/v1/trades",
            {
                "symbol": symbol,
                "limit": 500,
            }
        )

        if isinstance(
            data,
            dict
        ):

            data = data.get(
                "data",
                data.get(
                    "trades",
                    []
                )
            )

        return data or []

    except Exception:

        return []


# ============================================================
# 5M CLOSED CANDLES
# ============================================================

def build_candles(
    trades
):

    buckets = {}

    for trade in trades:

        try:

            if "time" in trade:
                ts = int(
                    trade["time"]
                )
            elif "timestamp" in trade:
                ts = int(
                    trade["timestamp"]
                )
            else:
                continue

            price = D(
                trade.get(
                    "price",
                    trade.get(
                        "p",
                        "0"
                    )
                )
            )

            quantity = D(
                trade.get(
                    "qty",
                    trade.get(
                        "quantity",
                        trade.get(
                            "q",
                            "0"
                        )
                    )
                )
            )

            if price <= 0:
                continue

            bucket = (
                ts // 300000
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

            candle = buckets[
                bucket
            ]

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

        except Exception:

            continue

    candles = [
        buckets[key]
        for key in sorted(
            buckets
        )
    ]

    # Remove current forming candle.
    current_bucket = (
        int(
            time.time() * 1000
        )
        // 300000
    ) * 300000

    candles = [
        candle
        for candle in candles
        if candle["time"]
        < current_bucket
    ]

    return candles


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    candles,
    period=14
):

    if len(candles) < period + 1:
        return Decimal("0")

    trs = []

    for index in range(
        1,
        len(candles)
    ):

        current = candles[index]
        previous = candles[index - 1]

        high = current["high"]
        low = current["low"]
        previous_close = (
            previous["close"]
        )

        tr = max(
            high - low,
            abs(
                high
                - previous_close
            ),
            abs(
                low
                - previous_close
            ),
        )

        trs.append(tr)

    return (
        sum(trs[-period:])
        / Decimal(period)
    )


# ============================================================
# STRATEGY
# ============================================================

def analyze(
    symbol
):

    trades = get_trades(
        symbol
    )

    candles = build_candles(
        trades
    )

    if len(candles) < 30:
        return None

    current = candles[-1]
    previous = candles[-2]

    price = current["close"]

    atr = calculate_atr(
        candles,
        14
    )

    if atr <= 0:
        return None

    lookback = candles[
        -21:-1
    ]

    swing_high = max(
        candle["high"]
        for candle in lookback
    )

    swing_low = min(
        candle["low"]
        for candle in lookback
    )

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    recent = candles[-6:]

    rising = (
        recent[-1]["close"]
        > recent[0]["close"]
    )

    higher_lows = (
        recent[-1]["low"]
        >= recent[0]["low"]
    )

    trend = (
        rising
        or higher_lows
    )

    if not trend:
        return None

    # --------------------------------------------------------
    # REAL BOS / NEAR BOS
    # --------------------------------------------------------

    bos_level = swing_high

    bos_strength = (
        price - bos_level
    ) / atr

    real_bos = (
        price > bos_level
        and bos_strength
        >= Decimal("0.05")
    )

    near_bos = (
        bos_strength
        >= Decimal("-0.25")
    )

    if not real_bos and not near_bos:
        return None

    # --------------------------------------------------------
    # PULLBACK
    # --------------------------------------------------------

    pullback_distance = (
        abs(
            price - bos_level
        )
        / atr
    )

    if pullback_distance > Decimal("0.80"):
        return None

    # --------------------------------------------------------
    # CLOSED SIGNAL BAR
    # --------------------------------------------------------

    candle_range = (
        current["high"]
        - current["low"]
    )

    if candle_range <= 0:
        return None

    close_position = (
        current["close"]
        - current["low"]
    ) / candle_range

    bullish = (
        current["close"]
        > current["open"]
    )

    signal_bar = (
        bullish
        and close_position
        >= Decimal("0.55")
    )

    # --------------------------------------------------------
    # CONTINUATION
    # --------------------------------------------------------

    continuation = (
        current["close"]
        >= previous["close"]
    )

    # --------------------------------------------------------
    # CHASE
    # --------------------------------------------------------

    move_from_low = (
        price - swing_low
    ) / atr

    chase = (
        move_from_low
        > Decimal("2.20")
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0.0

    if trend:
        score += 3

    if real_bos:
        score += 4
    elif near_bos:
        score += 2

    if pullback_distance <= Decimal("0.80"):
        score += 2

    if signal_bar:
        score += 3

    if continuation:
        score += 2

    if chase:
        score -= 3

    if not real_bos:
        score -= 1

    if score < MIN_SCORE:
        return None

    # --------------------------------------------------------
    # RISK
    # --------------------------------------------------------

    entry = price

    sl = (
        min(
            current["low"],
            previous["low"]
        )
        - (
            atr
            * Decimal("0.15")
        )
    )

    risk = entry - sl

    if risk <= 0:
        return None

    tp1 = (
        entry
        + risk * Decimal("1.5")
    )

    tp2 = (
        entry
        + risk * Decimal("2.2")
    )

    return {
        "symbol": symbol,
        "score": score,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "atr": atr,
        "real_bos": real_bos,
    }


# ============================================================
# SCAN
# ============================================================

def scan():

    telegram(
        "🔎 SCAN STARTING\n"
        f"⚡ {VERSION}\n"
        "🧠 BOS → PULLBACK → "
        "CONTINUATION → CLOSED CONFIRM\n"
        "⏱ 5m CLOSED CANDLES\n"
        "🚫 EMA: OFF\n"
        f"💵 ORDER TARGET: "
        f"{ORDER_USDT} USDT\n"
        f"🕐 {now_utc()}"
    )

    markets = get_usdt_markets()

    telegram(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
    )

    results = []

    selected = markets[
        :SCAN_LIMIT
    ]

    def worker(market):

        symbol = str(
            market.get(
                "symbol",
                ""
            )
        ).upper()

        return analyze(
            symbol
        )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                worker,
                market
            )
            for market in selected
        ]

        for future in as_completed(
            futures
        ):

            try:

                result = (
                    future.result()
                )

                if result:
                    results.append(
                        result
                    )

            except Exception as e:

                print(
                    "Scan error:",
                    e
                )

    results.sort(
        key=lambda item:
            item["score"],
        reverse=True
    )

    if not results:

        telegram(
            "👀 NO BUY READY\n"
            "هیچ سیگنال واجد شرایطی پیدا نشد."
        )

        return []

    lines = [
        "📡 ATI SCAN RESULT"
    ]

    for result in results[:10]:

        lines.append(
            f"🔥 BUY READY "
            f"{result['symbol']} | "
            f"score "
            f"{result['score']:.1f} | "
            f"entry~ "
            f"{fmt(result['entry'])}"
        )

    telegram(
        "\n".join(lines)
    )

    return results


# ============================================================
# MARKET LIMITS
# ============================================================

def get_market_limits(
    symbol
):

    data = public_get(
        "/api/v1/exchangeInfo"
    )

    symbols = (
        data.get(
            "symbols",
            []
        )
        if isinstance(
            data,
            dict
        )
        else data
    )

    for market in symbols:

        if str(
            market.get(
                "symbol",
                ""
            )
        ).upper() != symbol.upper():

            continue

        filters = market.get(
            "filters",
            []
        )

        min_qty = Decimal("0")
        max_qty = Decimal("0")
        step_size = Decimal("0")
        min_notional = Decimal("0")

        # MARKET_LOT_SIZE
        for item in filters:

            if str(
                item.get(
                    "filterType",
                    ""
                )
            ).upper() == "MARKET_LOT_SIZE":

                min_qty = D(
                    item.get(
                        "minQty",
                        "0"
                    )
                )

                max_qty = D(
                    item.get(
                        "maxQty",
                        "0"
                    )
                )

                step_size = D(
                    item.get(
                        "stepSize",
                        "0"
                    )
                )

                break

        # LOT_SIZE fallback
        if (
            min_qty <= 0
            or step_size <= 0
        ):

            for item in filters:

                if str(
                    item.get(
                        "filterType",
                        ""
                    )
                ).upper() == "LOT_SIZE":

                    min_qty = D(
                        item.get(
                            "minQty",
                            "0"
                        )
                    )

                    max_qty = D(
                        item.get(
                            "maxQty",
                            "0"
                        )
                    )

                    step_size = D(
                        item.get(
                            "stepSize",
                            "0"
                        )
                    )

                    break

        # NOTIONAL
        for item in filters:

            filter_type = str(
                item.get(
                    "filterType",
                    ""
                )
            ).upper()

            if filter_type in (
                "MIN_NOTIONAL",
                "NOTIONAL",
            ):

                min_notional = D(
                    item.get(
                        "minNotional",
                        item.get(
                            "notional",
                            "0"
                        )
                    )
                )

                if min_notional > 0:
                    break

        return {
            "min_qty": min_qty,
            "max_qty": max_qty,
            "step_size": step_size,
            "min_notional":
                min_notional,
        }

    raise RuntimeError(
        f"Market limits not found: "
        f"{symbol}"
    )


# ============================================================
# PREPARE 2 USDT ORDER
# ============================================================

def prepare_market_buy(
    symbol,
    price
):

    if price <= 0:

        raise RuntimeError(
            "Invalid price"
        )

    limits = get_market_limits(
        symbol
    )

    min_qty = limits[
        "min_qty"
    ]

    max_qty = limits[
        "max_qty"
    ]

    step = limits[
        "step_size"
    ]

    min_notional = limits[
        "min_notional"
    ]

    raw_qty = (
        ORDER_USDT
        / price
    )

    qty = raw_qty

    if step > 0:

        qty = floor_step(
            qty,
            step
        )

    if (
        max_qty > 0
        and qty > max_qty
    ):

        qty = max_qty

    if (
        min_qty > 0
        and qty < min_qty
    ):

        raise RuntimeError(
            "ORDER SKIPPED: "
            f"qty={qty} "
            f"< minQty={min_qty}"
        )

    estimated_value = (
        qty * price
    )

    if (
        min_notional > 0
        and estimated_value
        < min_notional
    ):

        raise RuntimeError(
            "ORDER SKIPPED: "
            f"value={estimated_value} "
            f"< minNotional="
            f"{min_notional}"
        )

    return {
        "qty": qty,
        "estimated_value":
            estimated_value,
        "min_qty": min_qty,
        "step_size": step,
        "min_notional":
            min_notional,
    }


# ============================================================
# REAL BUY
# ============================================================

def place_real_buy(
    signal
):

    symbol = signal[
        "symbol"
    ]

    entry = signal[
        "entry"
    ]

    prepared = prepare_market_buy(
        symbol,
        entry
    )

    qty = prepared[
        "qty"
    ]

    estimated_value = prepared[
        "estimated_value"
    ]

    telegram(
        "✅ ORDER SIZE VALID\n\n"
        f"🪙 {symbol}\n"
        f"📦 QTY: {fmt(qty)}\n"
        f"💵 EST. VALUE: "
        f"{estimated_value:.8f} USDT\n"
        f"📏 minQty: "
        f"{fmt(prepared['min_qty'])}\n"
        f"📐 stepSize: "
        f"{fmt(prepared['step_size'])}"
    )

    # --------------------------------------------------------
    # FINAL BALANCE
    # --------------------------------------------------------

    account = get_account()

    free_usdt = get_free_usdt(
        account
    )

    if free_usdt < estimated_value:

        raise RuntimeError(
            "Insufficient USDT: "
            f"need~"
            f"{estimated_value}, "
            f"free="
            f"{free_usdt}"
        )

    if not LIVE_TRADING:

        telegram(
            "🧪 PAPER MODE\n"
            "❌ REAL ORDER NOT SENT"
        )

        return None

    if BUY_LOCK:

        telegram(
            "🔒 BUY LOCK ACTIVE\n"
            "❌ REAL ORDER NOT SENT"
        )

        return None

    telegram(
        "🚀 SENDING ONE REAL BUY...\n\n"
        f"🪙 {symbol}\n"
        f"💵 TARGET: "
        f"{ORDER_USDT} USDT\n"
        f"📦 QTY: {fmt(qty)}\n"
        f"💰 FREE USDT: "
        f"{free_usdt}"
    )

    # --------------------------------------------------------
    # REAL MARKET ORDER
    # --------------------------------------------------------

    order = signed_request(
        "POST",
        "/api/v1/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": fmt(qty),
        }
    )

    order_id = None

    if isinstance(
        order,
        dict
    ):

        order_id = order.get(
            "orderId"
        )

    telegram(
        "🟢 ATI REAL BUY ACCEPTED\n\n"
        f"🪙 {symbol}\n"
        f"📦 QTY: {fmt(qty)}\n"
        f"💵 TARGET: "
        f"{ORDER_USDT} USDT\n"
        f"🆔 ORDER ID: "
        f"{order_id}\n"
        f"🕐 {now_utc()}"
    )

    return order


# ============================================================
# MAIN
# ============================================================

def main():

    telegram(
        "⚡ ATI BOT "
        f"{VERSION}\n"
        "🧠 REAL BOS / NEAR BOS → "
        "PULLBACK → CLOSED CONFIRM\n"
        "🚫 EMA: OFF\n"
        f"🔓 REAL TRADING: "
        f"{'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"
        f"💵 ORDER TARGET: "
        f"{ORDER_USDT} USDT\n"
        f"🔑 AUTH PAIR: "
        f"{AUTH_PAIR}\n"
        f"🕐 {now_utc()}"
    )

    try:

        # AUTH
        auth_test()

        # SCAN
        signals = scan()

        if not signals:
            return

        signal = signals[0]

        telegram(
            "🔥 BUY READY\n\n"
            f"🪙 {signal['symbol']}\n"
            f"📊 SCORE: "
            f"{signal['score']:.0f}\n"
            "📐 Trend → BOS → Pullback "
            "→ Continuation → CLOSED\n"
            f"💵 ENTRY~ "
            f"{fmt(signal['entry'])}\n"
            f"🛡 SL(calc) "
            f"{fmt(signal['sl'])}\n"
            f"🎯 TP1(calc) "
            f"{fmt(signal['tp1'])}\n"
            f"🎯 TP2(calc) "
            f"{fmt(signal['tp2'])}\n"
            f"💵 ORDER TARGET: "
            f"{ORDER_USDT} USDT"
        )

        if not LIVE_TRADING:

            telegram(
                "🧪 PAPER MODE\n"
                "❌ REAL ORDER NOT SENT"
            )

            return

        telegram(
            "🔐 AUTH CHECK BEFORE REAL BUY..."
        )

        auth_test()

        place_real_buy(
            signal
        )

    except Exception as e:

        message = (
            f"🚨 ATI ERROR {VERSION}\n\n"
            f"❌ {str(e)}\n\n"
            "🛑 REAL BUY NOT COMPLETED"
        )

        telegram(message)

        print(message)


if __name__ == "__main__":
    main()
