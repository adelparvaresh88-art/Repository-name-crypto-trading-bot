import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V38.0
# BREAKOUT + RETEST + MOMENTUM SCANNER
# PAPER / SCANNER ONLY
# ============================================================

VERSION = "V38.0"

BASE_URL = "https://api1.tabdeal.org"

MAX_MARKETS = 1000
TOP_BUYS = 3
TOP_WATCH = 3

TRADE_LIMIT = 1000
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_MARKETS = 0.03

# Minimum score for WATCH
WATCH_MIN_SCORE = 7

# Minimum score for BUY
BUY_MIN_SCORE = 10

# Do not chase extreme 5m moves
MAX_5M_CHASE = 8.0

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT-V38.0",
    "Accept": "application/json",
})


# ============================================================
# TIME
# ============================================================

def now_utc():
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


# ============================================================
# SAFE FLOAT
# ============================================================

def safe_float(
    value,
    default=0.0
):
    try:
        if value is None:
            return default

        return float(value)

    except Exception:
        return default


# ============================================================
# API GET
# ============================================================

def api_get(
    path,
    params=None
):

    url = BASE_URL + path

    try:

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        return response.json()

    except Exception as exc:

        print(
            f"API ERROR {path}: {exc}"
        )

        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print(
            "TELEGRAM_BOT_TOKEN missing"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "TELEGRAM_CHAT_ID missing"
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    try:

        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT
        )

        if response.ok:

            print(
                "Telegram: OK"
            )

            return True

        print(
            "Telegram ERROR:",
            response.text
        )

        return False

    except Exception as exc:

        print(
            "Telegram ERROR:",
            exc
        )

        return False


# ============================================================
# LOAD USDT MARKETS
# ============================================================

def load_usdt_markets():

    print(
        "Loading Tabdeal exchangeInfo..."
    )

    data = api_get(
        "/r/api/v1/exchangeInfo"
    )

    if data is None:

        return []

    if isinstance(data, list):

        market_items = data

    elif isinstance(data, dict):

        market_items = []

        for key in (
            "data",
            "result",
            "symbols",
            "markets"
        ):

            value = data.get(key)

            if isinstance(value, list):

                market_items = value
                break

    else:

        market_items = []

    if not market_items:

        print(
            "No market data found."
        )

        return []

    markets = []

    for item in market_items:

        if not isinstance(
            item,
            dict
        ):
            continue

        symbol = item.get(
            "symbol",
            ""
        )

        status = str(
            item.get(
                "status",
                "TRADING"
            )
        ).upper()

        quote_asset = str(
            item.get(
                "quoteAsset",
                ""
            )
        ).upper()

        if not isinstance(
            symbol,
            str
        ):
            continue

        symbol = (
            symbol.upper()
            .replace("_", "")
            .replace("-", "")
            .replace("/", "")
        )

        if quote_asset:

            if quote_asset != "USDT":
                continue

        elif not symbol.endswith(
            "USDT"
        ):

            continue

        if status not in (
            "TRADING",
            "ENABLED",
            "ACTIVE"
        ):

            continue

        if not symbol.endswith(
            "USDT"
        ):
            continue

        if symbol not in markets:

            markets.append(
                symbol
            )

    markets = sorted(
        set(markets)
    )

    markets = markets[
        :MAX_MARKETS
    ]

    print(
        f"MARKETS OK: "
        f"{len(markets)} USDT markets"
    )

    return markets


# ============================================================
# LOAD TRADES
# ============================================================

def load_trades(symbol):

    data = api_get(
        "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": TRADE_LIMIT
        }
    )

    if isinstance(
        data,
        list
    ):

        return data

    if isinstance(
        data,
        dict
    ):

        for key in (
            "data",
            "result",
            "trades",
            "items"
        ):

            value = data.get(key)

            if isinstance(
                value,
                list
            ):

                return value

    return []


# ============================================================
# PARSE TRADE
# ============================================================

def parse_trade(item):

    if not isinstance(
        item,
        dict
    ):
        return None

    price = safe_float(
        item.get(
            "price"
        )
    )

    quantity = safe_float(
        item.get(
            "qty",
            item.get(
                "quantity",
                1
            )
        )
    )

    timestamp = item.get(
        "time"
    )

    if timestamp is None:

        timestamp = item.get(
            "timestamp"
        )

    timestamp = safe_float(
        timestamp
    )

    if price <= 0:
        return None

    if timestamp <= 0:
        return None

    if quantity <= 0:

        quantity = 1.0

    # milliseconds -> seconds

    if timestamp > 100000000000:

        timestamp /= 1000

    return {
        "price": price,
        "quantity": quantity,
        "timestamp": timestamp
    }


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_candles(
    trades
):

    parsed = []

    for item in trades:

        trade = parse_trade(
            item
        )

        if trade:

            parsed.append(
                trade
            )

    if not parsed:

        return []

    parsed.sort(
        key=lambda x:
        x["timestamp"]
    )

    candles = {}

    bucket_size = 300

    for trade in parsed:

        bucket = (
            int(
                trade["timestamp"]
                / bucket_size
            )
            * bucket_size
        )

        price = trade[
            "price"
        ]

        quantity = trade[
            "quantity"
        ]

        if bucket not in candles:

            candles[bucket] = {
                "timestamp": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": quantity
            }

        else:

            candle = candles[
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

    return sorted(
        candles.values(),
        key=lambda x:
        x["timestamp"]
    )


# ============================================================
# PERCENT CHANGE
# ============================================================

def percent_change(
    old,
    new
):

    if old <= 0:

        return 0.0

    return (
        (new - old)
        / old
        * 100.0
    )


# ============================================================
# MOMENTUM
# ============================================================

def momentum(
    candles,
    periods
):

    if len(candles) <= periods:

        return 0.0

    old_price = candles[
        -(periods + 1)
    ]["close"]

    new_price = candles[
        -1
    ]["close"]

    return percent_change(
        old_price,
        new_price
    )


# ============================================================
# RECENT HIGH
# ============================================================

def recent_high(
    candles,
    count
):

    if len(candles) < count:

        return 0.0

    values = candles[
        -count:
    ]

    return max(
        candle["high"]
        for candle in values
    )


# ============================================================
# ANALYZE MARKET
# ============================================================

def analyze_market(
    symbol
):

    trades = load_trades(
        symbol
    )

    if not trades:

        return None

    candles = build_candles(
        trades
    )

    # Need enough candles
    if len(candles) < 20:

        return None

    # Ignore unfinished candle
    closed = candles[:-1]

    if len(closed) < 19:

        return None

    last = closed[-1]
    previous = closed[-2]

    price = last[
        "close"
    ]

    if price <= 0:

        return None

    # ========================================================
    # MOMENTUM
    # ========================================================

    m5 = momentum(
        closed,
        1
    )

    m15 = momentum(
        closed,
        3
    )

    m1h = momentum(
        closed,
        12
    )

    # ========================================================
    # EXTREME MOVE FILTER
    # ========================================================

    if m5 > MAX_5M_CHASE:

        return {
            "symbol": symbol,
            "status": "REJECT",
            "reason": "5M CHASE",
            "score": 0,
            "price": price,
            "m5": m5,
            "m15": m15,
            "m1h": m1h
        }

    # ========================================================
    # SCORE
    # ========================================================

    score = 0

    # --------------------------------------------------------
    # 5M MOMENTUM
    # --------------------------------------------------------

    if m5 > 0.10:

        score += 2

    elif m5 > 0.03:

        score += 1

    # --------------------------------------------------------
    # 15M MOMENTUM
    # --------------------------------------------------------

    if m15 > 0.50:

        score += 3

    elif m15 > 0.20:

        score += 2

    elif m15 > 0:

        score += 1

    # --------------------------------------------------------
    # 1H MOMENTUM
    # --------------------------------------------------------

    if m1h > 1.00:

        score += 3

    elif m1h > 0.40:

        score += 2

    elif m1h > 0:

        score += 1

    # --------------------------------------------------------
    # BULLISH CANDLE
    # --------------------------------------------------------

    bullish = (
        last["close"]
        > last["open"]
    )

    if bullish:

        score += 1

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    previous_high = max(
        candle["high"]
        for candle in closed[
            -7:-1
        ]
    )

    breakout = (
        last["close"]
        > previous_high
    )

    if breakout:

        score += 3

    # --------------------------------------------------------
    # HIGHER HIGH
    # --------------------------------------------------------

    older_high = recent_high(
        closed[:-1],
        6
    )

    higher_high = (
        last["high"]
        > older_high
    )

    if higher_high:

        score += 2

    # ========================================================
    # RETEST
    # ========================================================

    retest = False

    breakout_level = previous_high

    # Price must remain close to breakout level
    # instead of running too far away.

    if breakout:

        distance_from_breakout = (
            (
                price
                - breakout_level
            )
            / breakout_level
            * 100
        )

        if (
            distance_from_breakout
            <= 1.20
        ):

            retest = True

    # Also accept a small pullback
    # that stays above breakout level.

    if not retest:

        if (
            last["low"]
            <= breakout_level
            * 1.003
            and
            last["close"]
            > breakout_level
        ):

            retest = True

    # ========================================================
    # PULLBACK QUALITY
    # ========================================================

    pullback = False

    if len(closed) >= 4:

        c1 = closed[-2]
        c2 = closed[-3]
        c3 = closed[-4]

        if (
            c3["close"]
            <= c2["close"]
            and
            c1["close"]
            >= c2["close"]
        ):

            pullback = True

    # ========================================================
    # NEGATIVE MOMENTUM FILTER
    # ========================================================

    if (
        m5 <= 0
        and
        m15 <= 0
    ):

        return None

    # ========================================================
    # STATUS
    # ========================================================

    status = "WATCH"

    # Strong confirmed setup
    if (
        score >= BUY_MIN_SCORE
        and
        breakout
        and
        retest
        and
        bullish
        and
        m5 > 0
        and
        m15 > 0
    ):

        status = "BUY"

    # Good setup but waiting
    elif (
        score >= WATCH_MIN_SCORE
        and
        m15 > 0
        and
        (
            breakout
            or
            higher_high
        )
    ):

        status = "WATCH"

    else:

        return None

    # ========================================================
    # RISK LEVELS
    # ========================================================

    sl = price * 0.995

    tp1 = price * 1.008

    tp2 = price * 1.015

    # ========================================================
    # RETURN
    # ========================================================

    return {
        "symbol": symbol,
        "status": status,
        "score": score,
        "price": price,
        "m5": m5,
        "m15": m15,
        "m1h": m1h,
        "breakout": breakout,
        "retest": retest,
        "pullback": pullback,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2
    }


# ============================================================
# SCANNER
# ============================================================

def scan_markets(
    markets
):

    buys = []
    watches = []

    total = len(
        markets
    )

    print()
    print(
        f"Scanning {total} markets..."
    )

    for index, symbol in enumerate(
        markets,
        start=1
    ):

        try:

            result = analyze_market(
                symbol
            )

            if result is not None:

                if result[
                    "status"
                ] == "BUY":

                    buys.append(
                        result
                    )

                elif result[
                    "status"
                ] == "WATCH":

                    watches.append(
                        result
                    )

        except Exception as exc:

            print(
                f"{symbol} ERROR: "
                f"{exc}"
            )

        if index % 50 == 0:

            print(
                f"Progress: "
                f"{index}/{total}"
            )

        time.sleep(
            SLEEP_BETWEEN_MARKETS
        )

    buys.sort(
        key=lambda x: (
            x["score"],
            x["m15"],
            x["m5"]
        ),
        reverse=True
    )

    watches.sort(
        key=lambda x: (
            x["score"],
            x["m15"],
            x["m5"]
        ),
        reverse=True
    )

    return (
        buys[:TOP_BUYS],
        watches[:TOP_WATCH]
    )


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(
    signal
):

    status = signal[
        "status"
    ]

    if status == "BUY":

        title = "🟢 BUY"

    else:

        title = "🟡 WATCH"

    breakout_text = (
        "YES"
        if signal["breakout"]
        else "NO"
    )

    retest_text = (
        "YES"
        if signal["retest"]
        else "NO"
    )

    pullback_text = (
        "YES"
        if signal["pullback"]
        else "NO"
    )

    return [
        f"{title}",
        f"🪙 {signal['symbol']}",
        f"⭐ SCORE: {signal['score']}",
        f"💰 PRICE: {signal['price']:.8f}",
        f"📈 5M: {signal['m5']:+.2f}%",
        f"📊 15M: {signal['m15']:+.2f}%",
        f"⏱ 1H: {signal['m1h']:+.2f}%",
        "",
        f"💥 BREAKOUT: {breakout_text}",
        f"🔄 RETEST: {retest_text}",
        f"↩️ PULLBACK: {pullback_text}",
        "",
        f"🛑 SL: {signal['sl']:.8f}",
        f"🎯 TP1: {signal['tp1']:.8f}",
        f"🎯 TP2: {signal['tp2']:.8f}",
        ""
    ]


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def create_message(
    buys,
    watches,
    market_count
):

    lines = [
        f"⚡ ATI CRYPTO BOT {VERSION}",
        "",
        "🚀 BREAKOUT + RETEST SCANNER",
        "",
        "📡 TABDEAL API: OK",
        f"📊 USDT MARKETS: {market_count}",
        f"🟢 BUY MIN SCORE: {BUY_MIN_SCORE}",
        f"🟡 WATCH MIN SCORE: {WATCH_MIN_SCORE}",
        f"🚫 5M CHASE LIMIT: {MAX_5M_CHASE:.1f}%",
        ""
    ]

    # ========================================================
    # BUY
    # ========================================================

    lines.append(
        "🟢 CONFIRMED BUY"
    )

    lines.append("")

    if buys:

        for index, signal in enumerate(
            buys,
            start=1
        ):

            lines.append(
                f"#{index}"
            )

            lines.extend(
                format_signal(
                    signal
                )
            )

    else:

        lines.extend([
            "❌ NO CONFIRMED BUY",
            ""
        ])

    # ========================================================
    # WATCH
    # ========================================================

    lines.append(
        "🟡 WATCH / WAIT FOR CONFIRMATION"
    )

    lines.append("")

    if watches:

        for index, signal in enumerate(
            watches,
            start=1
        ):

            lines.append(
                f"#{index}"
            )

            lines.extend(
                format_signal(
                    signal
                )
            )

    else:

        lines.extend([
            "❌ NO WATCH SIGNAL",
            ""
        ])

    lines.append(
        f"🕐 {now_utc()}"
    )

    return "\n".join(
        lines
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)

    print(
        f"ATI CRYPTO BOT {VERSION}"
    )

    print(
        "BREAKOUT + RETEST SCANNER"
    )

    print(
        "REAL TRADING: DISABLED"
    )

    print("=" * 60)

    markets = load_usdt_markets()

    if not markets:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            "❌ TABDEAL MARKET ERROR\n"
            "Could not load USDT markets.\n\n"
            f"🕐 {now_utc()}"
        )

        print(
            message
        )

        send_telegram(
            message
        )

        return

    buys, watches = scan_markets(
        markets
    )

    message = create_message(
        buys,
        watches,
        len(markets)
    )

    print()
    print(message)

    send_telegram(
        message
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
