import os
import time
import json
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V39.6.6
# CLEAN EARLY ENTRY + CONFIRMED BREAKOUT
# ============================================================

VERSION = "V39.6.6"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 180
MAX_MARKETS = 1000
REQUEST_TIMEOUT = 10
MAX_WORKERS = 20

TOP_CONFIRMED = 3
TOP_EARLY = 5
TOP_WATCH = 5

CONFIRMED_MIN_SCORE = 12
EARLY_MIN_SCORE = 9
WATCH_MIN_SCORE = 8

BREAKOUT_BUFFER = 0.05

PAPER_TRACKING = True
MAX_HISTORY = 500
STATE_FILE = "paper_trades.json"

# Real orders intentionally disabled
LIVE_TRADING = False


# ============================================================
# ENV
# ============================================================

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

GH_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GH_REPO = os.getenv("GITHUB_REPOSITORY", "").strip()


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/39.6.6"
    }
)


# ============================================================
# TIME
# ============================================================

def now_text():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram(text):

    if not TG_TOKEN or not TG_CHAT_ID:
        print("Telegram credentials are missing.")
        return False

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"

    try:

        response = session.post(
            url,
            json={
                "chat_id": TG_CHAT_ID,
                "text": text
            },
            timeout=REQUEST_TIMEOUT
        )

        print("Telegram:", response.status_code)

        return response.ok

    except Exception as e:

        print("Telegram error:", e)

        return False


# ============================================================
# TABDEAL API
# ============================================================

def api_get(path, params=None):

    url = BASE_URL + path

    try:

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        print(
            "API",
            path,
            response.status_code
        )

        if not response.ok:

            print(
                response.text[:500]
            )

            return None

        return response.json()

    except Exception as e:

        print(
            "API error:",
            path,
            e
        )

        return None


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def normalize_symbol(value):

    if not isinstance(value, str):
        return ""

    symbol = (
        value
        .strip()
        .upper()
        .replace("_", "")
        .replace("-", "")
        .replace("/", "")
    )

    if (
        symbol.endswith("USDT")
        and len(symbol) >= 7
        and symbol.isalnum()
    ):
        return symbol

    return ""


# ============================================================
# EXCHANGE INFO PARSER
# Handles LIST and DICT responses
# ============================================================

def extract_exchange_symbols(data):

    if isinstance(data, list):

        items = data

    elif isinstance(data, dict):

        items = None

        for key in (
            "symbols",
            "data",
            "result",
            "markets",
            "items"
        ):

            value = data.get(key)

            if isinstance(value, list):

                items = value
                break

        if items is None:
            items = [data]

    else:

        return []

    output = []
    seen = set()

    for item in items:

        symbol = ""

        # -------------------------
        # String item
        # -------------------------

        if isinstance(item, str):

            symbol = normalize_symbol(item)

        # -------------------------
        # Dictionary item
        # -------------------------

        elif isinstance(item, dict):

            for key in (
                "symbol",
                "tabdealSymbol",
                "market",
                "pair",
                "name"
            ):

                symbol = normalize_symbol(
                    item.get(key)
                )

                if symbol:
                    break

            status = str(
                item.get("status", "")
            ).upper()

            if status:

                allowed = {
                    "TRADING",
                    "ACTIVE",
                    "ENABLED",
                    "OPEN"
                }

                if status not in allowed:
                    continue

        else:

            continue

        if symbol and symbol not in seen:

            seen.add(symbol)

            output.append(symbol)

    return output


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_markets():

    data = api_get(
        "/r/api/v1/exchangeInfo"
    )

    markets = extract_exchange_symbols(
        data
    )

    print(
        "ExchangeInfo type:",
        type(data).__name__
    )

    print(
        "USDT markets:",
        len(markets)
    )

    print(
        "First markets:",
        markets[:10]
    )

    return markets[:MAX_MARKETS]


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    # -------------------------
    # LIST / TUPLE
    # -------------------------

    if isinstance(
        item,
        (list, tuple)
    ):

        if len(item) < 2:
            return None

        try:

            price = float(item[0])
            quantity = float(item[1])

            if len(item) > 2:

                timestamp = int(
                    float(item[2])
                )

            else:

                timestamp = int(
                    time.time() * 1000
                )

            return (
                timestamp,
                price,
                quantity
            )

        except Exception:

            return None

    # -------------------------
    # DICT
    # -------------------------

    if isinstance(item, dict):

        try:

            price = float(
                item.get(
                    "price",
                    item.get("p")
                )
            )

            quantity = float(
                item.get(
                    "qty",
                    item.get(
                        "quantity",
                        item.get("q")
                    )
                )
            )

            timestamp = int(
                float(
                    item.get(
                        "time",
                        item.get(
                            "timestamp",
                            item.get(
                                "T",
                                time.time() * 1000
                            )
                        )
                    )
                )
            )

            return (
                timestamp,
                price,
                quantity
            )

        except Exception:

            return None

    return None


# ============================================================
# GET TRADES
# ============================================================

def get_trades(symbol):

    data = api_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000
        }
    )

    if isinstance(data, dict):

        for key in (
            "data",
            "trades",
            "result",
            "items"
        ):

            if isinstance(
                data.get(key),
                list
            ):

                data = data[key]
                break

    if not isinstance(data, list):
        return []

    output = []

    for item in data:

        parsed = parse_trade(item)

        if parsed:
            output.append(parsed)

    return sorted(output)


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_5m_candles(trades):

    if not trades:
        return []

    buckets = {}

    for timestamp, price, quantity in trades:

        bucket = (
            timestamp // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = [
                price,
                price,
                price,
                price,
                0.0
            ]

        candle = buckets[bucket]

        candle[1] = max(
            candle[1],
            price
        )

        candle[2] = min(
            candle[2],
            price
        )

        candle[3] = price

        candle[4] += quantity

    output = []

    for timestamp in sorted(buckets):

        open_price, high, low, close, volume = (
            buckets[timestamp]
        )

        output.append(
            {
                "t": timestamp,
                "o": open_price,
                "h": high,
                "l": low,
                "c": close,
                "v": volume
            }
        )

    return output[-CANDLE_LIMIT:]


# ============================================================
# AGGREGATE CANDLES
# ============================================================

def aggregate(candles, minutes):

    step = minutes // 5

    if len(candles) < step:
        return []

    output = []

    for i in range(
        0,
        len(candles) - step + 1,
        step
    ):

        group = candles[
            i:i + step
        ]

        output.append(
            {
                "t": group[0]["t"],
                "o": group[0]["o"],
                "h": max(
                    x["h"] for x in group
                ),
                "l": min(
                    x["l"] for x in group
                ),
                "c": group[-1]["c"],
                "v": sum(
                    x["v"] for x in group
                )
            }
        )

    return output


# ============================================================
# PERCENT CHANGE
# ============================================================

def pct(old, new):

    if not old:
        return 0.0

    return (
        (new - old) / old
    ) * 100.0


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(candles, n=20):

    if len(candles) < n + 1:
        return 0.0

    average = (
        sum(
            x["v"]
            for x in candles[-n - 1:-1]
        ) / n
    )

    if average <= 0:
        return 0.0

    return candles[-1]["v"] / average


# ============================================================
# RESISTANCE
# ============================================================

def resistance(candles, n=24):

    if len(candles) < n + 1:
        return 0.0

    return max(
        x["h"]
        for x in candles[-n - 1:-1]
    )


# ============================================================
# AVERAGE RANGE
# ============================================================

def average_range(candles, n=20):

    part = candles[-n:]

    if not part:
        return 0.0

    return (
        sum(
            x["h"] - x["l"]
            for x in part
        )
        / len(part)
    )


# ============================================================
# STRONG BULLISH CANDLE
# ============================================================

def strong_bullish_candle(candle):

    candle_range = (
        candle["h"] - candle["l"]
    )

    if candle_range <= 0:
        return False

    body = (
        candle["c"] - candle["o"]
    )

    return (
        body > 0
        and body / candle_range >= 0.45
        and candle["c"]
        >= candle["l"]
        + candle_range * 0.65
    )


# ============================================================
# ANALYZE SYMBOL
# ============================================================

def analyze_symbol(symbol):

    trades = get_trades(symbol)

    candles = build_5m_candles(
        trades
    )

    if len(candles) < 40:
        return None

    # Ignore currently forming candle
    closed = candles[:-1]

    if len(closed) < 35:
        return None

    candle = closed[-1]

    candles_15m = aggregate(
        closed,
        15
    )

    candles_1h = aggregate(
        closed,
        60
    )

    if (
        len(candles_15m) < 4
        or len(candles_1h) < 2
    ):
        return None

    price = candle["c"]

    change_5m = pct(
        closed[-2]["c"],
        price
    )

    change_15m = pct(
        candles_15m[-2]["c"],
        candles_15m[-1]["c"]
    )

    change_1h = pct(
        candles_1h[-2]["c"],
        candles_1h[-1]["c"]
    )

    vol_ratio = volume_ratio(
        closed
    )

    res = resistance(
        closed
    )

    if res:

        resistance_distance = pct(
            price,
            res
        )

    else:

        resistance_distance = 99.0

    breakout = False

    if res:

        breakout = (
            price
            >= res
            * (
                1
                + BREAKOUT_BUFFER / 100
            )
        )

    near_resistance = (
        0.0
        <= resistance_distance
        <= 2.2
    )

    retest = False

    if (
        len(closed) >= 3
        and res
    ):

        retest = (
            closed[-2]["l"]
            <= res * 1.002
            and price > res
        )

    strong_candle = (
        strong_bullish_candle(
            candle
        )
    )

    # ========================================================
    # SCORE
    # ========================================================

    score = 0

    if change_5m > 0.20:
        score += 2

    if change_15m > 0.50:
        score += 2

    if change_1h > 1.00:
        score += 2

    if vol_ratio >= 1.2:
        score += 2

    if strong_candle:
        score += 1

    if breakout:
        score += 3

    if retest:
        score += 2

    if near_resistance:
        score += 1

    # ========================================================
    # CONFIRMED
    # ========================================================

    confirmed = (
        score >= CONFIRMED_MIN_SCORE
        and 0.20
        <= change_5m
        <= 4.0
        and change_15m >= 0.50
        and change_1h >= 1.00
        and 1.20
        <= vol_ratio
        <= 8.00
        and (
            breakout
            or retest
        )
    )

    # ========================================================
    # EARLY
    # ========================================================

    early = (
        score >= EARLY_MIN_SCORE
        and -0.10
        <= change_5m
        <= 3.00
        and change_15m >= 0.30
        and change_1h >= 0.60
        and 0.60
        <= vol_ratio
        <= 8.00
        and 0.03
        <= resistance_distance
        <= 1.80
    )

    # ========================================================
    # WATCH
    # ========================================================

    watch = (
        score >= WATCH_MIN_SCORE
        and -0.10
        <= change_5m
        <= 3.00
        and change_15m >= 0.20
        and change_1h >= 0.50
        and 0.60
        <= vol_ratio
        <= 8.00
        and 0.03
        <= resistance_distance
        <= 2.20
    )

    if not (
        confirmed
        or early
        or watch
    ):
        return None

    # ========================================================
    # SL / TP
    # ========================================================

    risk = (
        average_range(closed)
        * 1.2
    )

    minimum_risk = (
        price * 0.004
    )

    maximum_risk = (
        price * 0.012
    )

    risk = max(
        risk,
        minimum_risk
    )

    risk = min(
        risk,
        maximum_risk
    )

    stop_loss = (
        price - risk
    )

    tp1 = (
        price + risk * 1.5
    )

    tp2 = (
        price + risk * 2.5
    )

    return {
        "symbol": symbol,
        "price": price,
        "score": score,

        "ch5": change_5m,
        "ch15": change_15m,
        "ch1h": change_1h,

        "vr": vol_ratio,
        "dist": resistance_distance,

        "confirmed": confirmed,
        "early": early,
        "watch": watch,

        "breakout": breakout,
        "retest": retest,

        "sl": stop_loss,
        "tp1": tp1,
        "tp2": tp2
    }


# ============================================================
# SORT
# ============================================================

def sort_key(item):

    return (
        item["score"],
        item["ch1h"],
        item["ch15"],
        item["vr"]
    )


# ============================================================
# FORMAT SIGNAL
# IMPORTANT:
# No fragile multiline f-string
# ============================================================

def format_candidate(item, label):

    if label == "BUY":
        emoji = "🟢"
    else:
        emoji = "🟡"

    lines = []

    lines.append(
        f"{emoji} {label}"
    )

    lines.append(
        f"🪙 {item['symbol']}"
    )

    lines.append(
        f"⭐ SCORE: {item['score']}"
    )

    lines.append(
        f"💰 PRICE: {item['price']:.8g}"
    )

    lines.append(
        f"📈 5M: {item['ch5']:+.2f}% | "
        f"15M: {item['ch15']:+.2f}% | "
        f"1H: {item['ch1h']:+.2f}%"
    )

    lines.append(
        f"📊 VOL: {item['vr']:.2f}x | "
        f"RES DIST: {item['dist']:.2f}%"
    )

    lines.append(
        f"🎯 SL: {item['sl']:.8g} | "
        f"TP1: {item['tp1']:.8g} | "
        f"TP2: {item['tp2']:.8g}"
    )

    flags = []

    if item["breakout"]:
        flags.append("BREAKOUT")

    if item["retest"]:
        flags.append("RETEST")

    if flags:

        lines.append(
            "🔥 "
            + " + ".join(flags)
        )

    return "\n".join(lines)


# ============================================================
# SCAN ALL MARKETS
# ============================================================

def scan(markets):

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_symbol,
                symbol
            ): symbol
            for symbol in markets
        }

        for future in as_completed(
            futures
        ):

            symbol = futures[future]

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception as e:

                print(
                    "Analyze error:",
                    symbol,
                    e
                )

    results.sort(
        key=sort_key,
        reverse=True
    )

    return results


# ============================================================
# PAPER STATE
# ============================================================

def load_state():

    try:

        if os.path.exists(
            STATE_FILE
        ):

            with open(
                STATE_FILE,
                "r",
                encoding="utf-8"
            ) as file:

                data = json.load(file)

            if isinstance(
                data,
                list
            ):

                return data

    except Exception as e:

        print(
            "State load error:",
            e
        )

    return []


# ============================================================
# SAVE STATE
# ============================================================

def save_state(state):

    state = state[
        -MAX_HISTORY:
    ]

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                state,
                file,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            "State save error:",
            e
        )


# ============================================================
# PAPER TRADE ID
# ============================================================

def make_trade_id(item):

    raw = (
        f"{item['symbol']}|"
        f"{item['price']}|"
        f"{item['sl']}|"
        f"{item['tp1']}|"
        f"{item['tp2']}|"
        f"{now_text()}"
    )

    return hashlib.sha256(
        raw.encode()
    ).hexdigest()[:16]


# ============================================================
# ADD PAPER TRADES
# ============================================================

def paper_add(results):

    if not PAPER_TRACKING:
        return

    state = load_state()

    existing = {
        item.get("symbol")
        for item in state
        if item.get("status") == "OPEN"
    }

    for item in results:

        if item["symbol"] in existing:
            continue

        if not (
            item["confirmed"]
            or item["early"]
        ):
            continue

        state.append(
            {
                "id": make_trade_id(item),

                "symbol": item["symbol"],

                "entry": item["price"],

                "sl": item["sl"],

                "tp1": item["tp1"],

                "tp2": item["tp2"],

                "opened_at": now_text(),

                "status": "OPEN"
            }
        )

        existing.add(
            item["symbol"]
        )

    save_state(state)


# ============================================================
# PAPER STATISTICS
# ============================================================

def paper_stats():

    state = load_state()

    total = len(state)

    tp = sum(
        1
        for item in state
        if item.get("status") == "TP"
    )

    sl = sum(
        1
        for item in state
        if item.get("status") == "SL"
    )

    open_count = sum(
        1
        for item in state
        if item.get("status") == "OPEN"
    )

    return (
        total,
        tp,
        sl,
        open_count
    )


# ============================================================
# MAIN
# ============================================================

def main():

    startup_lines = [
        f"⚡ ATI CRYPTO BOT {VERSION}",
        "🚀 CLEAN EARLY ENTRY + CONFIRMED BREAKOUT",
        "📡 TABDEAL API: CONNECTING...",
        "📊 SCAN: STARTING",
        "⏱ TIMEFRAME: 5m",
        "🕯 CLOSED CANDLE: YES",
    ]

    if PAPER_TRACKING:

        startup_lines.append(
            "📊 PAPER TRACKING: ON"
        )

    else:

        startup_lines.append(
            "📊 PAPER TRACKING: OFF"
        )

    startup_lines.extend(
        [
            "🔧 REAL ORDERS: DISABLED",
            f"🕐 {now_text()}"
        ]
    )

    telegram(
        "\n".join(
            startup_lines
        )
    )

    # ========================================================
    # MARKET DISCOVERY
    # ========================================================

    markets = get_markets()

    if not markets:

        error_lines = [
            f"⚠️ ATI BOT {VERSION}",
            "❌ TABDEAL MARKET DATA ERROR",
            "📡 No USDT markets found.",
            "🔎 MARKET DISCOVERY FAILED",
            f"🕐 {now_text()}"
        ]

        telegram(
            "\n".join(
                error_lines
            )
        )

        return

    # ========================================================
    # SCAN
    # ========================================================

    results = scan(
        markets
    )

    confirmed = [
        item
        for item in results
        if item["confirmed"]
    ][:TOP_CONFIRMED]

    early = [
        item
        for item in results
        if item["early"]
        and not item["confirmed"]
    ][:TOP_EARLY]

    watch = [
        item
        for item in results
        if item["watch"]
        and not item["confirmed"]
        and not item["early"]
    ][:TOP_WATCH]

    # ========================================================
    # PAPER
    # ========================================================

    paper_add(
        results
    )

    total, tp, sl, open_count = (
        paper_stats()
    )

    # ========================================================
    # TELEGRAM MESSAGE
    # ========================================================

    lines = [
        f"⚡ ATI CRYPTO BOT {VERSION}",
        "🚀 CLEAN EARLY ENTRY + CONFIRMED BREAKOUT",
        "📡 TABDEAL API: OK",
        f"📊 USDT MARKETS: {len(markets)}",
        f"🕐 {now_text()}",
        ""
    ]

    # --------------------------------------------------------
    # CONFIRMED
    # --------------------------------------------------------

    if confirmed:

        lines.append(
            "🟢 CONFIRMED BUY"
        )

        for item in confirmed:

            lines.append(
                format_candidate(
                    item,
                    "BUY"
                )
            )

            lines.append("")

    else:

        lines.append(
            "🟢 CONFIRMED BUY"
        )

        lines.append(
            "NONE"
        )

        lines.append("")

    # --------------------------------------------------------
    # EARLY
    # --------------------------------------------------------

    if early:

        lines.append(
            "⚡ EARLY ENTRY"
        )

        for item in early:

            lines.append(
                format_candidate(
                    item,
                    "BUY"
                )
            )

            lines.append("")

    else:

        lines.append(
            "⚡ EARLY ENTRY"
        )

        lines.append(
            "NONE"
        )

        lines.append("")

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    if watch:

        lines.append(
            "🟡 WATCH"
        )

        for item in watch:

            lines.append(
                format_candidate(
                    item,
                    "WATCH"
                )
            )

            lines.append("")

    else:

        lines.append(
            "🟡 WATCH"
        )

        lines.append(
            "NONE"
        )

        lines.append("")

    # --------------------------------------------------------
    # PAPER STATS
    # --------------------------------------------------------

    lines.append(
        "📊 PAPER STATS"
    )

    lines.append(
        f"Trades: {total} | "
        f"TP: {tp} | "
        f"SL: {sl} | "
        f"OPEN: {open_count}"
    )

    lines.append(
        "🔧 REAL ORDERS: DISABLED"
    )

    telegram(
        "\n".join(lines)
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
