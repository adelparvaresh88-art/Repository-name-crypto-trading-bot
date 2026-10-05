import os
import time
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.60-FAST
# TABDEAL SPOT
# FAST BUY / CLOSED CANDLE
# AUTH PRESERVED
# ============================================================

VERSION = "V40.2.60-FAST"

BASE = "https://api1.tabdeal.org"
API_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 15

RECV_WINDOW = int(
    os.getenv("RECV_WINDOW", "5000")
)

# FAST SCAN
SCAN_UNIVERSE = int(
    os.getenv("SCAN_UNIVERSE", "80")
)

MIN_CANDLES = int(
    os.getenv("MIN_CANDLES", "20")
)

KLINE_LIMIT = int(
    os.getenv("KLINE_LIMIT", "30")
)

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
    "User-Agent": f"ATI-Crypto-Bot/{VERSION}",
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
# DECIMAL
# ============================================================

def D(value):
    return Decimal(str(value))


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

def build_signed_params(extra=None):

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
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
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

    # Keep working authentication sequence.
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
    limit=KLINE_LIMIT
):

    try:

        data = public_get(
            "/r/api/v1/klines",
            {
                "symbol": symbol,
                "interval": "5m",
                "limit": limit,
            }
        )

    except Exception as exc:

        raise RuntimeError(
            f"KLINE {symbol}: {exc}"
        )

    if not isinstance(
        data,
        list
    ):

        raise RuntimeError(
            f"KLINE {symbol}: "
            "response is not list"
        )

    candles = []

    for row in data:

        if not isinstance(
            row,
            list
        ):
            continue

        if len(row) < 6:
            continue

        try:

            candles.append({

                "open": D(row[1]),

                "high": D(row[2]),

                "low": D(row[3]),

                "close": D(row[4]),

                "volume": D(row[5]),

                "time": int(row[0]),
            })

        except Exception:

            continue

    if len(candles) < MIN_CANDLES:

        raise RuntimeError(
            f"KLINE {symbol}: "
            f"only {len(candles)} candles"
        )

    return candles


# ============================================================
# FILTERS
# ============================================================

def get_filters(market):

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

            min_qty = D(
                f.get(
                    "minQty",
                    "0"
                )
            )

            step = D(
                f.get(
                    "stepSize",
                    "0"
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
            ] = D(
                f.get(
                    "minNotional",
                    "0"
                )
            )

    return result


# ============================================================
# ROUND DOWN
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
# FAST PRICE ACTION ENGINE
#
# CLOSED CANDLE ONLY
#
# PATH A:
# REAL BOS
#
# PATH B:
# NEAR BOS
#
# PATH C:
# MOMENTUM RECLAIM
#
# NO EMA
# ============================================================

def calculate_signal(candles):

    if len(candles) < MIN_CANDLES:
        return None

    # Never use the live/open candle.
    closed = candles[:-1]

    if len(closed) < 18:
        return None

    current = closed[-1]
    previous = closed[-2]

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    structure = closed[-12:-2]

    if len(structure) < 6:
        return None

    structure_high = max(
        x["high"]
        for x in structure
    )

    structure_low = min(
        x["low"]
        for x in structure
    )

    if structure_high <= 0:
        return None

    # --------------------------------------------------------
    # CURRENT CANDLE
    # --------------------------------------------------------

    candle_range = (
        current["high"]
        -
        current["low"]
    )

    if candle_range <= 0:
        return None

    bullish = (
        current["close"]
        >
        current["open"]
    )

    if not bullish:
        return None

    close_position = (
        current["close"]
        -
        current["low"]
    ) / candle_range

    # FAST CONFIRM
    if close_position < Decimal("0.50"):
        return None

    continuation = (
        current["close"]
        >=
        previous["close"]
    )

    if not continuation:
        return None

    # --------------------------------------------------------
    # BOS
    # --------------------------------------------------------

    bos_distance = (
        (
            current["close"]
            /
            structure_high
        )
        -
        Decimal("1")
    ) * Decimal("100")

    real_bos = (
        bos_distance
        >= Decimal("0.02")
    )

    near_bos = (
        bos_distance
        >= Decimal("-0.50")
    )

    # --------------------------------------------------------
    # RECLAIM
    # --------------------------------------------------------

    reclaim = (
        current["high"]
        >=
        structure_high
    )

    # --------------------------------------------------------
    # PULLBACK
    # --------------------------------------------------------

    pullback_tolerance = Decimal(
        "1.20"
    )

    pullback = (
        previous["low"]
        <=
        structure_high
        *
        (
            Decimal("1")
            +
            pullback_tolerance
            /
            Decimal("100")
        )
    )

    # --------------------------------------------------------
    # CHASE
    # --------------------------------------------------------

    chase_distance = (
        (
            current["close"]
            /
            structure_high
        )
        -
        Decimal("1")
    ) * Decimal("100")

    if chase_distance > Decimal("3.0"):
        return None

    # --------------------------------------------------------
    # PRESSURE
    # --------------------------------------------------------

    pressure = (
        (
            current["close"]
            -
            current["open"]
        )
        /
        candle_range
    ) * Decimal("100")

    # --------------------------------------------------------
    # SETUP
    # --------------------------------------------------------

    if real_bos and pullback:

        setup = "A-FAST-REAL-BOS"

    elif near_bos and pullback:

        setup = "B-FAST-NEAR-BOS"

    elif reclaim:

        setup = "C-MOMENTUM-RECLAIM"

    else:

        return None

    # --------------------------------------------------------
    # STOP
    # --------------------------------------------------------

    recent_lows = [
        x["low"]
        for x in closed[-5:]
    ]

    recent_low = min(
        recent_lows
    )

    sl = (
        recent_low
        *
        Decimal("0.997")
    )

    entry = current["close"]

    risk = (
        entry
        -
        sl
    )

    if risk <= 0:
        return None

    risk_percent = (
        risk
        /
        entry
    ) * Decimal("100")

    # FAST MODE:
    # allow wider risk than old version,
    # but prevent extreme setups.
    if risk_percent > Decimal("6"):
        return None

    if risk_percent < Decimal("0.08"):
        return None

    # --------------------------------------------------------
    # TP
    # --------------------------------------------------------

    tp1 = (
        entry
        +
        risk * Decimal("1.40")
    )

    tp2 = (
        entry
        +
        risk * Decimal("2.20")
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = Decimal("0")

    if real_bos:
        score += Decimal("6")
    elif near_bos:
        score += Decimal("4")
    else:
        score += Decimal("3")

    if pullback:
        score += Decimal("3")

    if continuation:
        score += Decimal("2")

    if reclaim:
        score += Decimal("2")

    if close_position >= Decimal("0.65"):
        score += Decimal("2")

    elif close_position >= Decimal("0.55"):
        score += Decimal("1")

    if pressure >= Decimal("70"):
        score += Decimal("2")

    elif pressure >= Decimal("55"):
        score += Decimal("1")

    if chase_distance <= Decimal("0.80"):
        score += Decimal("1")

    # FAST minimum
    if real_bos:

        if score < Decimal("11"):
            return None

    else:

        if score < Decimal("9"):
            return None

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

        "setup":
            setup,

        "bos_distance":
            bos_distance,

        "chase_distance":
            chase_distance,

        "close_position":
            close_position,
    }


# ============================================================
# RANKING
# ============================================================

def rank_candidate(candidate):

    signal = candidate[
        "signal"
    ]

    score = signal[
        "score"
    ]

    pressure = signal[
        "pressure"
    ]

    risk = signal[
        "risk_percent"
    ]

    bos_distance = signal[
        "bos_distance"
    ]

    setup_bonus = Decimal("0")

    if signal["setup"] == (
        "A-FAST-REAL-BOS"
    ):

        setup_bonus = Decimal("7")

    elif signal["setup"] == (
        "B-FAST-NEAR-BOS"
    ):

        setup_bonus = Decimal("4")

    else:

        setup_bonus = Decimal("2")

    return (
        score * Decimal("10")
        +
        pressure / Decimal("10")
        +
        bos_distance
        +
        setup_bonus
        -
        risk * Decimal("1.5")
    )


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

    # Safety reserve:
    # never use all USDT.
    max_spend = (
        usdt_free
        *
        Decimal("0.90")
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
            f"{symbol}: quantity zero"
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
        f"🧠 {signal['setup']}\n"
        f"🏆 SCORE: {signal['score']}\n"
        f"💵 VALUE: {notional} USDT\n"
        f"📦 QTY: {quantity}\n"
        f"💰 ENTRY: {signal['entry']}\n"
        f"🛑 SL: {signal['sl']}\n"
        f"🎯 TP1: {signal['tp1']}\n"
        f"🎯 TP2: {signal['tp2']}\n"
        "⚠️ REAL MARKET BUY"
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
        "🚀 FAST BUY ENGINE\n"
        "🧠 REAL BOS / NEAR BOS / RECLAIM\n"
        "→ PULLBACK\n"
        "→ CONTINUATION\n"
        "→ CLOSED CANDLE\n"
        "🚫 EMA: OFF\n"
        f"🔓 REAL TRADING: "
        f"{'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"
        f"💵 TARGET: "
        f"{ORDER_VALUE} USDT\n"
        f"📊 UNIVERSE: "
        f"{SCAN_UNIVERSE}\n"
        f"🕐 {utc_now()}"
    )

    # ========================================================
    # AUTH
    # ========================================================

    telegram(
        "🔐 AUTH CHECK "
        "BEFORE BUY..."
    )

    try:

        can_trade, usdt_free = (
            auth_check()
        )

        telegram(
            "✅ AUTH SUCCESS\n"
            "🔑 PAIR: TABDIL\n"
            f"🔓 canTrade={can_trade}\n"
            f"💰 USDT FREE: {usdt_free}\n"
            f"⏱ OFFSET: "
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

    # FAST universe
    markets = markets[
        :SCAN_UNIVERSE
    ]

    telegram(
        "🔎 FAST SCAN STARTING\n"
        f"📊 MARKETS: {len(markets)}\n"
        "⏱ TIMEFRAME: 5m\n"
        "🔒 CLOSED CANDLE ONLY"
    )

    # ========================================================
    # SCAN
    # ========================================================

    candidates = []

    kline_success = 0
    kline_errors = 0
    error_samples = []

    for market in markets:

        symbol = market[
            "symbol"
        ]

        try:

            candles = get_klines(
                symbol,
                KLINE_LIMIT
            )

            kline_success += 1

            signal = calculate_signal(
                candles
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

        except Exception as exc:

            kline_errors += 1

            if len(error_samples) < 5:

                error_samples.append(
                    f"{symbol}: {str(exc)[:120]}"
                )

            continue

    # ========================================================
    # SCAN REPORT
    # ========================================================

    report = (
        "📡 SCAN FINISHED\n"
        f"✅ KLINE OK: {kline_success}\n"
        f"❌ KLINE ERROR: {kline_errors}\n"
        f"🎯 CANDIDATES: "
        f"{len(candidates)}"
    )

    if error_samples:

        report += (
            "\n\n⚠️ KLINE ERRORS:\n"
            +
            "\n".join(
                error_samples
            )
        )

    telegram(report)

    # ========================================================
    # NO CANDIDATE
    # ========================================================

    if not candidates:

        telegram(
            "💓 ATI RUN ALIVE\n"
            "👀 NO BUY SETUP\n"
            "🚫 NO ORDER\n"
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

    # ========================================================
    # BEST BUY
    # ========================================================

    telegram(
        "🔥 FAST BUY FOUND\n"
        f"💎 {symbol}\n"
        f"🧠 {signal['setup']}\n"
        f"🏆 SCORE: {signal['score']}\n"
        f"📊 RANK: "
        f"{best['ranking']:.2f}\n"
        f"📈 BOS: "
        f"{signal['bos_distance']:.3f}%\n"
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
        f"👀 CANDIDATES: "
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
            f"🧠 {signal['setup']}\n"
            f"💵 VALUE: {notional} USDT\n"
            f"📦 QTY: {quantity}\n"
            f"🆔 ORDER ID: {order_id}\n"
            f"📌 STATUS: {status}"
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
