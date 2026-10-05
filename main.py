import os
import time
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.58-REAL
# TABDEAL SPOT
# AUTH FIX + BEST BUY FILTER
# ============================================================

VERSION = "V40.2.58-REAL"

BASE = "https://api1.tabdeal.org"
API_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 15
RECV_WINDOW = 5000

SCAN_UNIVERSE = 40
MIN_CANDLES = 30

ORDER_VALUE = Decimal(
    os.getenv("ORDER_QTY", "2")
)

LIVE_TRADING = (
    os.getenv(
        "LIVE_TRADING",
        "false"
    ).lower() == "true"
)

API_KEY = (
    os.getenv("TABDIL_API_KEY")
    or os.getenv("TABDEAL_API_KEY")
    or ""
).strip()

API_SECRET = (
    os.getenv("TABDIL_API_SECRET")
    or os.getenv("TABDIL_SECRET")
    or os.getenv("TABDEAL_API_SECRET")
    or os.getenv("TABDEAL_SECRET")
    or ""
).strip()

TG_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TG_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()

session = requests.Session()

session.headers.update({
    "User-Agent":
        f"ATI-Crypto-Bot/{VERSION}",
    "Accept": "application/json",
})

SERVER_OFFSET_MS = 0


# ============================================================
# TIME
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):

    print(
        message,
        flush=True
    )

    if not TG_TOKEN or not TG_CHAT_ID:
        return

    try:

        requests.post(
            f"https://api.telegram.org/"
            f"bot{TG_TOKEN}/sendMessage",

            data={
                "chat_id": TG_CHAT_ID,
                "text": message,
            },

            timeout=10,
        )

    except Exception as exc:

        print(
            "TELEGRAM ERROR:",
            exc,
            flush=True
        )


# ============================================================
# PUBLIC GET
# ============================================================

def public_get(
    path,
    params=None
):

    response = session.get(
        f"{BASE}{path}",
        params=params or {},
        timeout=TIMEOUT,
    )

    if response.status_code >= 400:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:800]}"
        )

    return response.json()


# ============================================================
# SERVER TIME
# ============================================================

def sync_server_time():

    global SERVER_OFFSET_MS

    data = public_get(
        "/r/api/v1/time"
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

    return server_time


# ============================================================
# HMAC
# ============================================================

def build_signed_params(
    extra=None
):

    timestamp = (
        int(time.time() * 1000)
        + SERVER_OFFSET_MS
    )

    params = {}

    if extra:

        for key, value in extra.items():

            if value is None:
                continue

            params[key] = str(value)

    params["timestamp"] = str(
        timestamp
    )

    params["recvWindow"] = str(
        RECV_WINDOW
    )

    query = urlencode(
        params,
        doseq=True
    )

    signature = hmac.new(
        API_SECRET.encode(
            "utf-8"
        ),
        query.encode(
            "utf-8"
        ),
        hashlib.sha256,
    ).hexdigest()

    params["signature"] = signature

    return params


# ============================================================
# SIGNED GET
# ============================================================

def signed_get(
    path,
    extra=None
):

    params = build_signed_params(
        extra
    )

    response = session.get(
        f"{BASE}{path}",
        params=params,

        headers={
            "X-MBX-APIKEY":
                API_KEY,
        },

        timeout=TIMEOUT,
    )

    if response.status_code >= 400:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    return response.json()


# ============================================================
# SIGNED POST
# ============================================================

def signed_post(
    path,
    extra=None
):

    params = build_signed_params(
        extra
    )

    response = session.post(
        f"{BASE}{path}",
        data=params,

        headers={
            "X-MBX-APIKEY":
                API_KEY,

            "Content-Type":
                "application/x-www-form-urlencoded",
        },

        timeout=TIMEOUT,
    )

    if response.status_code >= 400:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    return response.json()


# ============================================================
# AUTH
# ============================================================

def auth_check():

    if not API_KEY:
        raise RuntimeError(
            "TABDIL_API_KEY is EMPTY"
        )

    if not API_SECRET:
        raise RuntimeError(
            "TABDIL_API_SECRET is EMPTY"
        )

    sync_server_time()

    account = signed_get(
        "/r/api/v1/account"
    )

    can_trade = bool(
        account.get(
            "canTrade",
            False
        )
    )

    balances = account.get(
        "balances",
        []
    )

    usdt_free = Decimal("0")

    for balance in balances:

        if balance.get(
            "asset"
        ) == "USDT":

            usdt_free = Decimal(
                str(
                    balance.get(
                        "free",
                        "0"
                    )
                )
            )

            break

    return (
        can_trade,
        usdt_free
    )


# ============================================================
# MARKETS
# ============================================================

def get_markets():

    data = public_get(
        "/r/api/v1/exchangeInfo"
    )

    if isinstance(
        data,
        dict
    ):

        markets = (
            data.get("symbols")
            or data.get("data")
            or []
        )

    else:

        markets = data

    result = []

    for market in markets:

        if not isinstance(
            market,
            dict
        ):
            continue

        if market.get(
            "status"
        ) != "TRADING":

            continue

        if market.get(
            "quoteAsset"
        ) != "USDT":

            continue

        symbol = market.get(
            "symbol"
        )

        if not symbol:
            continue

        result.append(
            market
        )

    return result


# ============================================================
# KLINES
# ============================================================

def get_klines(
    symbol,
    limit=40
):

    data = public_get(
        "/r/api/v1/klines",
        {
            "symbol": symbol,
            "interval": "5m",
            "limit": limit,
        }
    )

    if not isinstance(
        data,
        list
    ):
        return []

    candles = []

    for row in data:

        if len(row) < 6:
            continue

        candles.append({

            "open":
                Decimal(str(row[1])),

            "high":
                Decimal(str(row[2])),

            "low":
                Decimal(str(row[3])),

            "close":
                Decimal(str(row[4])),

            "volume":
                Decimal(str(row[5])),

            "time":
                int(row[0]),
        })

    return candles


# ============================================================
# MARKET FILTERS
# ============================================================

def get_filters(
    market
):

    result = {

        "minQty":
            Decimal("0"),

        "stepSize":
            Decimal("0"),

        "minNotional":
            Decimal("0"),
    }

    for f in market.get(
        "filters",
        []
    ):

        filter_type = f.get(
            "filterType"
        )

        if filter_type in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE",
        ):

            min_qty = Decimal(
                str(
                    f.get(
                        "minQty",
                        "0"
                    )
                )
            )

            step = Decimal(
                str(
                    f.get(
                        "stepSize",
                        "0"
                    )
                )
            )

            if min_qty > result[
                "minQty"
            ]:

                result[
                    "minQty"
                ] = min_qty

            if step > 0:

                result[
                    "stepSize"
                ] = step

        elif filter_type == (
            "MIN_NOTIONAL"
        ):

            result[
                "minNotional"
            ] = Decimal(
                str(
                    f.get(
                        "minNotional",
                        "0"
                    )
                )
            )

    return result


# ============================================================
# QUANTITY ROUNDING
# ============================================================

def round_down(
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


# ============================================================
# PRICE ACTION SIGNAL
# ============================================================

def calculate_signal(
    candles
):

    if len(candles) < MIN_CANDLES:
        return None

    # Last candle is ignored:
    # it may still be forming.
    closed = candles[:-1]

    if len(closed) < 15:
        return None

    current = closed[-1]
    previous = closed[-2]

    structure = closed[
        -10:-3
    ]

    if not structure:
        return None

    previous_high = max(
        x["high"]
        for x in structure
    )

    previous_low = min(
        x["low"]
        for x in structure
    )

    # REAL BOS
    bos = (
        current["close"]
        > previous_high
    )

    # Pullback toward BOS level
    pullback = (
        previous["low"]
        <=
        previous_high
        * Decimal("1.008")
    )

    bullish = (
        current["close"]
        > current["open"]
    )

    candle_range = (
        current["high"]
        -
        current["low"]
    )

    if candle_range <= 0:
        return None

    close_position = (
        current["close"]
        -
        current["low"]
    ) / candle_range

    strong_close = (
        close_position
        >= Decimal("0.55")
    )

    continuation = (
        current["close"]
        >
        previous["close"]
    )

    if not (
        bos
        and pullback
        and bullish
        and strong_close
        and continuation
    ):
        return None

    entry = current["close"]

    recent_low = min(
        x["low"]
        for x in closed[-5:]
    )

    sl = (
        recent_low
        *
        Decimal("0.997")
    )

    risk = (
        entry
        -
        sl
    )

    if risk <= 0:
        return None

    risk_percent = (
        risk / entry
    ) * Decimal("100")

    # Don't accept extremely wide stops.
    if risk_percent > Decimal("5"):
        return None

    tp1 = (
        entry
        +
        risk * Decimal("1.5")
    )

    tp2 = (
        entry
        +
        risk * Decimal("2.5")
    )

    pressure = (
        (
            current["close"]
            -
            current["open"]
        )
        /
        candle_range
    ) * Decimal("100")

    score = Decimal("0")

    if bos:
        score += Decimal("6")

    if pullback:
        score += Decimal("3")

    if strong_close:
        score += Decimal("3")

    if continuation:
        score += Decimal("3")

    # Bonus for strong pressure
    if pressure >= Decimal("70"):
        score += Decimal("2")

    elif pressure >= Decimal("60"):
        score += Decimal("1")

    return {

        "entry":
            entry,

        "sl":
            sl,

        "tp1":
            tp1,

        "tp2":
            tp2,

        "risk":
            risk,

        "risk_percent":
            risk_percent,

        "pressure":
            pressure,

        "score":
            score,
    }


# ============================================================
# FINAL CANDIDATE RANKING
# ============================================================

def rank_candidate(
    candidate
):

    signal = candidate["signal"]

    score = signal[
        "score"
    ]

    pressure = signal[
        "pressure"
    ]

    risk = signal[
        "risk_percent"
    ]

    # Prefer high score,
    # strong pressure,
    # smaller risk.
    ranking = (
        score * Decimal("10")
        +
        pressure / Decimal("10")
        -
        risk * Decimal("2")
    )

    return ranking


# ============================================================
# BUY VALIDATION
# ============================================================

def validate_buy(
    market,
    signal,
    usdt_free
):

    symbol = market[
        "symbol"
    ]

    filters = get_filters(
        market
    )

    entry = signal[
        "entry"
    ]

    if entry <= 0:

        raise RuntimeError(
            "INVALID ENTRY"
        )

    # Never spend the entire balance.
    max_spend = (
        usdt_free
        * Decimal("0.90")
    )

    target = min(
        ORDER_VALUE,
        max_spend
    )

    if target <= 0:

        raise RuntimeError(
            "NO USDT AVAILABLE"
        )

    quantity = (
        target
        /
        entry
    )

    quantity = round_down(
        quantity,
        filters["stepSize"]
    )

    if quantity <= 0:

        raise RuntimeError(
            f"{symbol}: "
            "quantity became zero"
        )

    if (
        filters["minQty"] > 0
        and
        quantity
        <
        filters["minQty"]
    ):

        raise RuntimeError(
            f"{symbol}: quantity "
            f"{quantity} < minQty "
            f"{filters['minQty']}"
        )

    notional = (
        quantity
        *
        entry
    )

    if (
        filters["minNotional"] > 0
        and
        notional
        <
        filters["minNotional"]
    ):

        raise RuntimeError(
            f"{symbol}: notional "
            f"{notional} < minNotional "
            f"{filters['minNotional']}"
        )

    if notional > max_spend:

        raise RuntimeError(
            "ORDER EXCEEDS SAFE BALANCE"
        )

    return (
        quantity,
        notional,
        filters
    )


# ============================================================
# REAL BUY
# ============================================================

def real_buy(
    market,
    signal,
    usdt_free
):

    symbol = market[
        "symbol"
    ]

    (
        quantity,
        notional,
        filters
    ) = validate_buy(
        market,
        signal,
        usdt_free
    )

    telegram(
        "🟠 BUY VALIDATED\n"
        f"💎 {symbol}\n"
        f"💵 VALUE: {notional} USDT\n"
        f"📦 QTY: {quantity}\n"
        f"💰 ENTRY: {signal['entry']}\n"
        f"🛑 SL: {signal['sl']}\n"
        f"🎯 TP1: {signal['tp1']}\n"
        f"🎯 TP2: {signal['tp2']}"
    )

    order = signed_post(
        "/api/v1/order",
        {
            "symbol":
                symbol,

            "side":
                "BUY",

            "type":
                "MARKET",

            "quantity":
                format(
                    quantity,
                    "f"
                ),
        }
    )

    return (
        order,
        quantity,
        notional
    )


# ============================================================
# MAIN
# ============================================================

def main():

    telegram(
        f"⚡ ATI CRYPTO BOT "
        f"{VERSION}\n"
        "🧠 BEST BUY ENGINE\n"
        "📐 BOS → PULLBACK → "
        "CLOSED CONFIRM\n"
        "🚫 EMA: OFF\n"
        f"🔓 REAL TRADING: "
        f"{'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"
        f"💵 TARGET: "
        f"{ORDER_VALUE} USDT\n"
        f"🕐 {utc_now()}"
    )

    # ========================================================
    # AUTH
    # ========================================================

    telegram(
        "🔐 AUTH CHECK "
        "BEFORE REAL BUY..."
    )

    try:

        can_trade, usdt_free = (
            auth_check()
        )

        telegram(
            "✅ AUTH SUCCESS\n"
            "🔑 PAIR: TABDIL\n"
            f"🔓 canTrade={can_trade}\n"
            f"💰 USDT FREE: "
            f"{usdt_free}\n"
            f"⏱ SERVER OFFSET: "
            f"{SERVER_OFFSET_MS} ms"
        )

    except Exception as exc:

        telegram(
            "🚨 AUTH FAILED\n"
            f"❌ {exc}\n"
            "🛑 NO BUY"
        )

        return

    if not can_trade:

        telegram(
            "🛑 canTrade=false\n"
            "NO REAL ORDER"
        )

        return

    if usdt_free <= 0:

        telegram(
            "🛑 USDT BALANCE IS ZERO"
        )

        return

    # ========================================================
    # MARKETS
    # ========================================================

    try:

        markets = get_markets()

    except Exception as exc:

        telegram(
            "🚨 MARKET ERROR\n"
            f"❌ {exc}"
        )

        return

    markets = markets[
        :SCAN_UNIVERSE
    ]

    telegram(
        "🔎 SCAN STARTING\n"
        f"📊 MARKETS: "
        f"{len(markets)}\n"
        "⏱ 5m CLOSED CANDLES"
    )

    # ========================================================
    # SCAN
    # ========================================================

    candidates = []

    for market in markets:

        try:

            symbol = market[
                "symbol"
            ]

            candles = get_klines(
                symbol,
                40
            )

            signal = (
                calculate_signal(
                    candles
                )
            )

            if signal:

                candidates.append({

                    "market":
                        market,

                    "signal":
                        signal,

                    "symbol":
                        symbol,
                })

        except Exception:

            continue

    # ========================================================
    # NO CANDIDATE
    # ========================================================

    if not candidates:

        telegram(
            "💓 ATI RUN ALIVE\n"
            "📡 SCAN FINISHED\n"
            "👀 NO BUY\n"
            f"🕐 {utc_now()}"
        )

        return

    # ========================================================
    # RANK
    # ========================================================

    for candidate in candidates:

        candidate[
            "ranking"
        ] = rank_candidate(
            candidate
        )

    candidates.sort(
        key=lambda x:
            x["ranking"],
        reverse=True
    )

    best = candidates[0]

    market = best[
        "market"
    ]

    signal = best[
        "signal"
    ]

    symbol = best[
        "symbol"
    ]

    telegram(
        "🔥 ATI BEST BUY\n"
        f"💎 {symbol}\n"
        f"🏆 SCORE: "
        f"{signal['score']}\n"
        f"📊 RANK: "
        f"{best['ranking']:.2f}\n"
        f"💵 ENTRY: "
        f"{signal['entry']}\n"
        f"🛑 SL: "
        f"{signal['sl']}\n"
        f"🎯 TP1: "
        f"{signal['tp1']}\n"
        f"🎯 TP2: "
        f"{signal['tp2']}\n"
        f"📉 RISK: "
        f"{signal['risk_percent']:.2f}%\n"
        f"💪 PRESSURE: "
        f"{signal['pressure']:.2f}%\n"
        f"👀 TOTAL CANDIDATES: "
        f"{len(candidates)}"
    )

    # ========================================================
    # PAPER
    # ========================================================

    if not LIVE_TRADING:

        telegram(
            "🟡 PAPER MODE\n"
            "LIVE_TRADING=false\n"
            "🛑 NO REAL BUY"
        )

        return

    # ========================================================
    # REAL BUY
    # ========================================================

    try:

        (
            order,
            quantity,
            notional
        ) = real_buy(
            market,
            signal,
            usdt_free
        )

        order_id = (
            order.get(
                "orderId"
            )
            or order.get(
                "id"
            )
            or "N/A"
        )

        status = order.get(
            "status",
            "N/A"
        )

        telegram(
            "🟢 REAL BUY SUCCESS\n"
            f"💎 {symbol}\n"
            f"💵 VALUE: "
            f"{notional} USDT\n"
            f"📦 QTY: {quantity}\n"
            f"🆔 ORDER ID: "
            f"{order_id}\n"
            f"📌 STATUS: "
            f"{status}"
        )

    except Exception as exc:

        telegram(
            "🚨 REAL BUY FAILED\n"
            f"💎 {symbol}\n"
            f"❌ {exc}\n"
            "🛑 NO RETRY THIS RUN"
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        telegram(
            "🚨 ATI FATAL ERROR\n"
            f"⚡ {VERSION}\n"
            f"❌ {type(exc).__name__}: "
            f"{exc}"
        )
