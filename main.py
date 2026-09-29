import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.1
# FIXED MARKET DISCOVERY
# DATA RECOVERY + RATE LIMIT PROTECTION
# ============================================================

VERSION = "V40.2.1"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

MAX_MARKETS = 529
MAX_WORKERS = 6

TRADE_LIMIT = 1000
REQUEST_TIMEOUT = 15

SCAN_INTERVAL_SECONDS = 300
REQUEST_DELAY = 0.08
MAX_RETRIES = 4

RECENT_MINUTES = 15
TOP_RESULTS = 15


# ============================================================
# SIGNAL SETTINGS
# ============================================================

SL_PERCENT = 0.60
TP1_PERCENT = 1.00
TP2_PERCENT = 1.60

CHASE_LIMIT_5M = 7.0

CONFIRMED_MIN_SCORE = 8
EARLY_MIN_SCORE = 7

MIN_BUY_PRESSURE_CONFIRMED = 58.0
MIN_CANDLE_POSITION = 0.65


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


HEADERS = {
    "User-Agent": "ATI-Crypto-Bot/40.2.1",
    "Accept": "application/json",
}


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_string():
    return utc_now().strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# SAFE FLOAT
# ============================================================

def safe_float(value, default=0.0):

    try:

        if value is None:
            return default

        if isinstance(value, bool):
            return default

        return float(value)

    except Exception:

        return default


# ============================================================
# NORMALIZE SYMBOL
# ============================================================

def clean_symbol(symbol):

    if not symbol:
        return ""

    return (
        str(symbol)
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN MISSING")
        return False

    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM_CHAT_ID MISSING")
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=15,
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


def send_long_telegram(
    message,
    chunk_size=3900,
):

    if len(message) <= chunk_size:

        send_telegram(message)

        return

    parts = []

    current = ""

    for line in message.splitlines(True):

        if (
            len(current) + len(line)
            > chunk_size
        ):

            if current:
                parts.append(current)

            current = line

        else:

            current += line

    if current:
        parts.append(current)

    for part in parts:

        send_telegram(part)

        time.sleep(0.3)


# ============================================================
# HTTP GET WITH RETRY
# ============================================================

def get_json(
    path,
    params=None,
    retries=MAX_RETRIES,
):

    url = BASE_URL + path

    last_error = None

    for attempt in range(retries):

        try:

            time.sleep(
                REQUEST_DELAY
            )

            response = requests.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            status = response.status_code

            # ------------------------------------------------
            # SUCCESS
            # ------------------------------------------------

            if status == 200:

                try:

                    return response.json()

                except Exception as exc:

                    last_error = (
                        f"JSON ERROR: {exc}"
                    )

            # ------------------------------------------------
            # RATE LIMIT
            # ------------------------------------------------

            elif status == 429:

                wait_seconds = min(
                    2.0 * (attempt + 1),
                    8.0,
                )

                print(
                    "RATE LIMIT 429 | "
                    f"attempt={attempt + 1} | "
                    f"wait={wait_seconds}s"
                )

                time.sleep(
                    wait_seconds
                )

                last_error = "HTTP 429"

            # ------------------------------------------------
            # SERVER ERROR
            # ------------------------------------------------

            elif status >= 500:

                wait_seconds = min(
                    1.5 * (attempt + 1),
                    6.0,
                )

                print(
                    f"SERVER ERROR {status} | "
                    f"attempt={attempt + 1}"
                )

                time.sleep(
                    wait_seconds
                )

                last_error = (
                    f"HTTP {status}"
                )

            # ------------------------------------------------
            # OTHER ERROR
            # ------------------------------------------------

            else:

                last_error = (
                    f"HTTP {status}: "
                    f"{response.text[:300]}"
                )

                break

        except requests.RequestException as exc:

            last_error = str(exc)

            wait_seconds = min(
                1.5 * (attempt + 1),
                6.0,
            )

            time.sleep(
                wait_seconds
            )

        except Exception as exc:

            last_error = str(exc)

            time.sleep(1)

    print(
        f"GET FAILED {path}: "
        f"{last_error}"
    )

    return None


# ============================================================
# TABDEAL API TEST
# ============================================================

def ping_tabdeal():

    data = get_json(
        "/r/api/v1/trades",
        params={
            "symbol": "BTCUSDT",
            "limit": 5,
        },
        retries=3,
    )

    return data is not None


# ============================================================
# MARKET SYMBOL EXTRACTION
# ============================================================

def extract_exchange_symbols(data):

    symbols = []

    def add_symbol(item):

        if isinstance(item, str):

            symbol = clean_symbol(item)

            if symbol:
                symbols.append(symbol)

            return

        if not isinstance(item, dict):
            return

        symbol_value = None

        for key in [
            "symbol",
            "market",
            "pair",
            "instrument",
            "code",
            "name",
        ]:

            if item.get(key):

                symbol_value = item.get(key)

                break

        if not symbol_value:
            return

        symbol = clean_symbol(
            symbol_value
        )

        if not symbol:
            return

        # ----------------------------------------------------
        # MARKET STATUS
        # ----------------------------------------------------

        status = str(
            item.get(
                "status",
                ""
            )
        ).upper()

        allowed_status = {
            "",
            "TRADING",
            "ACTIVE",
            "ENABLED",
            "1",
        }

        if status not in allowed_status:
            return

        symbols.append(symbol)

    # --------------------------------------------------------
    # TOP LEVEL LIST
    # --------------------------------------------------------

    if isinstance(data, list):

        for item in data:

            add_symbol(item)

    # --------------------------------------------------------
    # DICT
    # --------------------------------------------------------

    elif isinstance(data, dict):

        containers = [
            "symbols",
            "data",
            "result",
            "markets",
            "items",
        ]

        for key in containers:

            value = data.get(key)

            if isinstance(value, list):

                for item in value:

                    add_symbol(item)

            elif isinstance(value, dict):

                # بعضی پاسخ‌ها:
                # {"symbols": {"data": [...]}}
                for subkey in [
                    "symbols",
                    "data",
                    "result",
                    "markets",
                    "items",
                ]:

                    subvalue = value.get(
                        subkey
                    )

                    if isinstance(
                        subvalue,
                        list,
                    ):

                        for item in subvalue:

                            add_symbol(item)

        # اگر خود dict یک market باشد
        add_symbol(data)

    return list(
        dict.fromkeys(symbols)
    )


# ============================================================
# GET USDT MARKETS
# ============================================================

def get_usdt_markets():

    # ========================================================
    # مهم‌ترین اصلاح V40.2.1
    #
    # این همان endpoint سالم نسخه‌های قبلی است
    # که 529 بازار USDT برمی‌گرداند.
    # ========================================================

    data = get_json(
        "/r/api/v1/exchangeInfo",
        retries=4,
    )

    if data is None:

        print(
            "EXCHANGE INFO REQUEST FAILED"
        )

        return []

    symbols = extract_exchange_symbols(
        data
    )

    usdt_markets = []

    for symbol in symbols:

        if symbol.endswith("USDT"):

            usdt_markets.append(
                symbol
            )

    usdt_markets = list(
        dict.fromkeys(
            usdt_markets
        )
    )

    print(
        f"EXCHANGE INFO SYMBOLS: "
        f"{len(symbols)}"
    )

    print(
        f"USDT MARKETS FOUND: "
        f"{len(usdt_markets)}"
    )

    return usdt_markets[
        :MAX_MARKETS
    ]


# ============================================================
# EXTRACT TRADES
# ============================================================

def extract_trades(data):

    if isinstance(data, list):

        return data

    if isinstance(data, dict):

        for key in [
            "data",
            "result",
            "trades",
            "items",
        ]:

            value = data.get(key)

            if isinstance(value, list):

                return value

        result = data.get(
            "result"
        )

        if isinstance(
            result,
            dict,
        ):

            for key in [
                "data",
                "trades",
                "items",
            ]:

                value = result.get(
                    key
                )

                if isinstance(
                    value,
                    list,
                ):

                    return value

    return []


# ============================================================
# NORMALIZE TRADE
# ============================================================

def normalize_trade(item):

    if not isinstance(item, dict):
        return None

    price = 0.0
    quantity = 0.0
    timestamp = None
    side = ""

    # PRICE
    for key in [
        "price",
        "p",
        "trade_price",
    ]:

        if key in item:

            price = safe_float(
                item.get(key)
            )

            if price > 0:
                break

    # QUANTITY
    for key in [
        "quantity",
        "qty",
        "amount",
        "q",
        "volume",
    ]:

        if key in item:

            quantity = safe_float(
                item.get(key)
            )

            if quantity > 0:
                break

    # TIMESTAMP
    for key in [
        "timestamp",
        "time",
        "T",
        "created_at",
        "date",
    ]:

        if key in item:

            timestamp = item.get(
                key
            )

            if timestamp is not None:
                break

    # SIDE
    for key in [
        "side",
        "S",
        "type",
    ]:

        if key in item:

            side = str(
                item.get(key)
            ).lower()

            if side:
                break

    if price <= 0:
        return None

    return {
        "price": price,
        "quantity": quantity,
        "timestamp": timestamp,
        "side": side,
    }


# ============================================================
# GET SYMBOL TRADES
# ============================================================

def get_symbol_trades(symbol):

    data = get_json(
        "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": TRADE_LIMIT,
        },
    )

    if data is None:
        return []

    raw_trades = extract_trades(
        data
    )

    normalized = []

    for item in raw_trades:

        trade = normalize_trade(
            item
        )

        if trade:

            normalized.append(
                trade
            )

    return normalized


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_5m_candles(trades):

    if not trades:
        return []

    prepared = []

    now_ms = int(
        time.time() * 1000
    )

    min_time_ms = (
        now_ms
        - RECENT_MINUTES * 60 * 1000
    )

    for trade in trades:

        price = safe_float(
            trade.get("price")
        )

        quantity = safe_float(
            trade.get("quantity"),
            0.0,
        )

        timestamp = trade.get(
            "timestamp"
        )

        if price <= 0:
            continue

        ts = safe_float(
            timestamp,
            0.0,
        )

        if ts <= 0:
            continue

        # seconds -> milliseconds
        if ts < 10000000000:
            ts *= 1000

        if ts < min_time_ms:
            continue

        prepared.append(
            (
                int(ts),
                price,
                quantity,
                trade.get(
                    "side",
                    ""
                ),
            )
        )

    if not prepared:
        return []

    prepared.sort(
        key=lambda x: x[0]
    )

    candles = {}

    for (
        ts,
        price,
        qty,
        side,
    ) in prepared:

        bucket = (
            ts
            // (
                5 * 60 * 1000
            )
        ) * (
            5 * 60 * 1000
        )

        if bucket not in candles:

            candles[bucket] = {
                "timestamp": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0,
                "buy_volume": 0.0,
                "sell_volume": 0.0,
                "trades": 0,
            }

        candle = candles[
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

        candle["trades"] += 1

        side_lower = str(
            side or ""
        ).lower()

        if side_lower in [
            "buy",
            "bid",
            "b",
        ]:

            candle[
                "buy_volume"
            ] += qty

        elif side_lower in [
            "sell",
            "ask",
            "s",
        ]:

            candle[
                "sell_volume"
            ] += qty

    return list(
        sorted(
            candles.values(),
            key=lambda x: x[
                "timestamp"
            ],
        )
    )


# ============================================================
# BUY PRESSURE
# ============================================================

def calculate_buy_pressure(
    candles
):

    if not candles:
        return 0.0

    recent = candles[-3:]

    buy = 0.0
    sell = 0.0

    for candle in recent:

        buy += safe_float(
            candle.get(
                "buy_volume"
            )
        )

        sell += safe_float(
            candle.get(
                "sell_volume"
            )
        )

    total = buy + sell

    if total <= 0:
        return 0.0

    return (
        buy / total
    ) * 100.0


# ============================================================
# ANALYZE MARKET
# ============================================================

def analyze_market(symbol):

    try:

        trades = get_symbol_trades(
            symbol
        )

        if not trades:
            return None

        candles = build_5m_candles(
            trades
        )

        if len(candles) < 3:
            return None

        current = candles[-1]
        previous = candles[-2]

        close = safe_float(
            current["close"]
        )

        previous_close = safe_float(
            previous["close"]
        )

        if close <= 0:
            return None

        if previous_close <= 0:
            return None

        change_5m = (
            (
                close
                - previous_close
            )
            / previous_close
        ) * 100.0

        high = safe_float(
            current["high"]
        )

        low = safe_float(
            current["low"]
        )

        candle_range = (
            high - low
        )

        if candle_range <= 0:

            candle_position = 0.5

        else:

            candle_position = (
                close - low
            ) / candle_range

        buy_pressure = (
            calculate_buy_pressure(
                candles
            )
        )

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        lookback = candles[
            max(
                0,
                len(candles) - 6,
            ):-1
        ]

        if lookback:

            previous_high = max(
                safe_float(
                    candle["high"]
                )
                for candle in lookback
            )

        else:

            previous_high = high

        breakout = (
            close > previous_high
        )

        # ----------------------------------------------------
        # SCORE
        # ----------------------------------------------------

        score = 0

        reasons = []

        if change_5m >= 0.15:

            score += 1

            reasons.append(
                "5M MOMENTUM"
            )

        if buy_pressure >= 58:

            score += 1

            reasons.append(
                "BUY PRESSURE"
            )

        if candle_position >= 0.65:

            score += 1

            reasons.append(
                "STRONG CLOSE"
            )

        if breakout:

            score += 1

            reasons.append(
                "BREAKOUT"
            )

        if (
            change_5m >= 0.10
            and buy_pressure >= 55
        ):

            score += 1

            reasons.append(
                "EARLY MOMENTUM"
            )

        if buy_pressure >= 70:

            score += 1

            reasons.append(
                "BUYING"
            )

        # ----------------------------------------------------
        # ANTI CHASE
        # ----------------------------------------------------

        if change_5m >= (
            CHASE_LIMIT_5M
        ):

            return None

        # ----------------------------------------------------
        # CONFIRMED
        # ----------------------------------------------------

        confirmed = (
            breakout
            and change_5m > 0
            and buy_pressure
            >= MIN_BUY_PRESSURE_CONFIRMED
            and candle_position
            >= MIN_CANDLE_POSITION
            and score
            >= CONFIRMED_MIN_SCORE
        )

        # ----------------------------------------------------
        # EARLY
        # ----------------------------------------------------

        early = (
            not confirmed
            and breakout
            and buy_pressure >= 58
            and candle_position >= 0.60
            and change_5m >= 0.10
            and score >= EARLY_MIN_SCORE
        )

        # ----------------------------------------------------
        # WATCH
        # ----------------------------------------------------

        watch = (
            not confirmed
            and not early
            and breakout
            and score >= 4
        )

        if not (
            confirmed
            or early
            or watch
        ):

            return None

        sl = (
            close
            * (
                1
                - SL_PERCENT / 100
            )
        )

        tp1 = (
            close
            * (
                1
                + TP1_PERCENT / 100
            )
        )

        tp2 = (
            close
            * (
                1
                + TP2_PERCENT / 100
            )
        )

        return {
            "symbol": symbol,
            "price": close,
            "change_5m": change_5m,
            "score": score,
            "buy_pressure": buy_pressure,
            "breakout": breakout,
            "confirmed": confirmed,
            "early": early,
            "watch": watch,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "reasons": reasons,
        }

    except Exception as exc:

        print(
            f"ANALYZE ERROR "
            f"{symbol}: {exc}"
        )

        return None


# ============================================================
# FORMAT RESULT
# ============================================================

def format_result(result):

    return (
        f"🟢 {result['symbol']}\n"
        f"💰 Price: "
        f"{result['price']:.10g}\n"
        f"📈 5M: "
        f"{result['change_5m']:+.2f}%\n"
        f"🎯 Score: "
        f"{result['score']}\n"
        f"🟢 Buy Pressure: "
        f"{result['buy_pressure']:.0f}%\n"
        f"🚀 Breakout: "
        f"{'YES' if result['breakout'] else 'NO'}\n"
        f"🛡 SL: "
        f"{result['sl']:.10g}\n"
        f"🎯 TP1: "
        f"{result['tp1']:.10g}\n"
        f"🎯 TP2: "
        f"{result['tp2']:.10g}\n"
        f"🔎 "
        f"{' + '.join(result['reasons'])}"
    )


# ============================================================
# RUN SCAN
# ============================================================

def run_scan():

    print(
        "ATI V40.2.1 SCAN START"
    )

    # --------------------------------------------------------
    # API
    # --------------------------------------------------------

    if not ping_tabdeal():

        send_telegram(
            "⚠️ ATI BOT V40.2.1\n\n"
            "❌ TABDEAL API ERROR\n"
            "🔄 RETRYING NEXT SCAN"
        )

        return {
            "markets": 0,
            "data": 0,
            "confirmed": 0,
            "early": 0,
            "watch": 0,
        }

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    markets = get_usdt_markets()

    if not markets:

        send_telegram(
            "⚠️ ATI BOT V40.2.1\n\n"
            "❌ NO USDT MARKETS FOUND\n\n"
            "Endpoint:\n"
            "/r/api/v1/exchangeInfo\n\n"
            "🔄 RETRYING NEXT SCAN"
        )

        return {
            "markets": 0,
            "data": 0,
            "confirmed": 0,
            "early": 0,
            "watch": 0,
        }

    markets = markets[
        :MAX_MARKETS
    ]

    print(
        f"USDT MARKETS: "
        f"{len(markets)}"
    )

    # --------------------------------------------------------
    # PARALLEL SCAN
    # --------------------------------------------------------

    results = []

    data_count = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_market,
                symbol,
            ): symbol
            for symbol in markets
        }

        for future in as_completed(
            futures
        ):

            symbol = futures[
                future
            ]

            try:

                result = future.result()

                if result:

                    data_count += 1

                    results.append(
                        result
                    )

            except Exception as exc:

                print(
                    f"SCAN ERROR "
                    f"{symbol}: {exc}"
                )

    # --------------------------------------------------------
    # GROUP
    # --------------------------------------------------------

    confirmed = [
        r for r in results
        if r["confirmed"]
    ]

    early = [
        r for r in results
        if r["early"]
    ]

    watch = [
        r for r in results
        if r["watch"]
    ]

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    sort_key = (
        lambda x: (
            x["score"],
            x["buy_pressure"],
            x["change_5m"],
        )
    )

    confirmed.sort(
        key=sort_key,
        reverse=True,
    )

    early.sort(
        key=sort_key,
        reverse=True,
    )

    watch.sort(
        key=sort_key,
        reverse=True,
    )

    confirmed = confirmed[
        :TOP_RESULTS
    ]

    early = early[
        :TOP_RESULTS
    ]

    watch = watch[
        :TOP_RESULTS
    ]

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n"
        "🚀 CLEAN EARLY ENTRY + "
        "CONFIRMED BREAKOUT\n"
        "🛡 ANTI-FAKE BREAKOUT\n"
        "🚫 ANTI-CHASE\n\n"
        "📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: "
        f"{len(markets)}\n"
        f"🎯 MARKETS WITH DATA: "
        f"{data_count}\n"
        "⏱ TIMEFRAME: 5m\n"
        "🕯 RECENT 5M DATA: YES\n"
        "💓 HEARTBEAT: ON\n"
        "🔧 REAL ORDERS: DISABLED\n"
    )

    # --------------------------------------------------------
    # CONFIRMED
    # --------------------------------------------------------

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "🟢 CONFIRMED BUY\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if confirmed:

        for result in confirmed:

            message += (
                "\n"
                + format_result(result)
                + "\n"
            )

    else:

        message += "NONE\n"

    # --------------------------------------------------------
    # EARLY
    # --------------------------------------------------------

    message += (
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ EARLY ENTRY\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if early:

        for result in early:

            message += (
                "\n"
                + format_result(result)
                + "\n"
            )

    else:

        message += "NONE\n"

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    message += (
        "━━━━━━━━━━━━━━━━━━\n"
        "🟡 WATCH\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if watch:

        for result in watch:

            message += (
                "\n"
                + format_result(result)
                + "\n"
            )

    else:

        message += "NONE\n"

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "📊 SCAN SUMMARY\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Confirmed: "
        f"{len(confirmed)}\n"
        f"⚡ Early: "
        f"{len(early)}\n"
        f"🟡 Watch: "
        f"{len(watch)}\n\n"
        "🔄 NEXT SCAN: "
        "ABOUT 5 MINUTES\n\n"
        f"🕐 {utc_string()}"
    )

    send_long_telegram(
        message
    )

    return {
        "markets": len(markets),
        "data": data_count,
        "confirmed": len(confirmed),
        "early": len(early),
        "watch": len(watch),
    }


# ============================================================
# HEARTBEAT
# ============================================================

def send_heartbeat(stats):

    message = (
        "💓 ATI BOT HEARTBEAT\n\n"
        f"⚡ VERSION: {VERSION}\n"
        "📡 STATUS: ALIVE\n"
        "⏱ TIMEFRAME: 5m\n"
        f"📊 MARKETS: "
        f"{stats.get('markets', 0)}\n"
        f"📊 DATA: "
        f"{stats.get('data', 0)}\n"
        f"🟢 CONFIRMED: "
        f"{stats.get('confirmed', 0)}\n"
        f"⚡ EARLY: "
        f"{stats.get('early', 0)}\n"
        f"🟡 WATCH: "
        f"{stats.get('watch', 0)}\n"
        "🔧 REAL ORDERS: DISABLED\n\n"
        "🔄 NEXT SCAN: "
        "ABOUT 5 MINUTES\n"
        f"🕐 {utc_string()}"
    )

    send_telegram(
        message
    )


# ============================================================
# CONTINUOUS LOOP
# ============================================================

def run_forever():

    startup = (
        f"🟢 ATI CRYPTO BOT {VERSION}\n\n"
        "📡 TABDEAL API: CONNECTING...\n"
        "📊 SCAN: STARTING\n"
        "⏱ TIMEFRAME: 5m\n"
        "🕯 CLOSED/RECENT 5M DATA: YES\n"
        "💓 HEARTBEAT: ON\n"
        "🔧 REAL ORDERS: DISABLED\n\n"
        "🔄 CONTINUOUS MODE: ON\n"
        f"🕐 {utc_string()}"
    )

    send_telegram(
        startup
    )

    while True:

        scan_start = time.time()

        try:

            stats = run_scan()

            send_heartbeat(
                stats
            )

        except Exception as exc:

            print(
                "MAIN LOOP ERROR:",
                exc,
            )

            send_telegram(
                "⚠️ ATI BOT ERROR\n\n"
                f"VERSION: {VERSION}\n"
                f"ERROR: {str(exc)[:700]}\n\n"
                "🔄 BOT WILL RETRY"
            )

        elapsed = (
            time.time()
            - scan_start
        )

        wait_seconds = max(
            10,
            SCAN_INTERVAL_SECONDS
            - int(elapsed),
        )

        print(
            "NEXT SCAN IN "
            f"{wait_seconds} SECONDS"
        )

        remaining = wait_seconds

        while remaining > 0:

            sleep_time = min(
                30,
                remaining,
            )

            time.sleep(
                sleep_time
            )

            remaining -= sleep_time


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    run_forever()
