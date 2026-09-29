import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2
# DATA RECOVERY + RATE LIMIT PROTECTION
# CLEAN EARLY ENTRY + CONFIRMED BREAKOUT
# ============================================================

VERSION = "V40.2"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

# ------------------------------------------------------------
# SCAN SETTINGS
# ------------------------------------------------------------

MAX_MARKETS = 529

# مهم:
# قبلاً 12 درخواست همزمان باعث می‌شد تعداد زیادی از بازارها
# بدون DATA باقی بمانند.
MAX_WORKERS = 6

TRADE_LIMIT = 1000

REQUEST_TIMEOUT = 15

SCAN_INTERVAL_SECONDS = 300

# بین درخواست‌ها فاصله کوتاه برای کاهش Rate Limit
REQUEST_DELAY = 0.08

MAX_RETRIES = 4

RECENT_MINUTES = 15

TOP_RESULTS = 15


# ------------------------------------------------------------
# SIGNAL SETTINGS
# ------------------------------------------------------------

SL_PERCENT = 0.60
TP1_PERCENT = 1.00
TP2_PERCENT = 1.60

CHASE_LIMIT_5M = 7.0

CONFIRMED_MIN_SCORE = 8
EARLY_MIN_SCORE = 7

MIN_BUY_PRESSURE_CONFIRMED = 58.0

MIN_CANDLE_POSITION = 0.65


# ------------------------------------------------------------
# TELEGRAM
# ------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


# ------------------------------------------------------------
# HTTP SESSION
# ------------------------------------------------------------

HEADERS = {
    "User-Agent": "ATI-Crypto-Bot/40.2",
    "Accept": "application/json",
}


# ============================================================
# BASIC HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_string():
    return utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        if isinstance(value, bool):
            return default

        return float(value)

    except Exception:
        return default


def clean_symbol(symbol):
    if not symbol:
        return ""

    return str(symbol).upper().replace("/", "").replace("-", "")


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM CONFIG MISSING")
        return False

    url = (
        f"https://api.telegram.org/bot"
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
        print("TELEGRAM EXCEPTION:", exc)

    return False


def send_long_telegram(message, chunk_size=3900):
    if len(message) <= chunk_size:
        send_telegram(message)
        return

    parts = []

    current = ""

    for line in message.splitlines(True):

        if len(current) + len(line) > chunk_size:
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

def get_json(path, params=None, retries=MAX_RETRIES):
    url = BASE_URL + path

    last_error = None

    for attempt in range(retries):

        try:
            time.sleep(REQUEST_DELAY)

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
                    last_error = f"JSON ERROR: {exc}"

            # ------------------------------------------------
            # RATE LIMIT
            # ------------------------------------------------

            elif status == 429:

                wait_seconds = min(
                    2.0 * (attempt + 1),
                    8.0,
                )

                print(
                    f"RATE LIMIT 429 | "
                    f"attempt={attempt + 1} | "
                    f"wait={wait_seconds}s"
                )

                time.sleep(wait_seconds)

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

                time.sleep(wait_seconds)

                last_error = f"HTTP {status}"

            # ------------------------------------------------
            # OTHER ERROR
            # ------------------------------------------------

            else:

                last_error = (
                    f"HTTP {status}: "
                    f"{response.text[:200]}"
                )

                # برای 4xxهای غیر از 429
                # Retry بی‌فایده است.
                break

        except requests.RequestException as exc:

            last_error = str(exc)

            wait_seconds = min(
                1.5 * (attempt + 1),
                6.0,
            )

            time.sleep(wait_seconds)

        except Exception as exc:

            last_error = str(exc)

            time.sleep(1)

    return None


# ============================================================
# TABDEAL PING
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
# EXTRACT SYMBOLS
# ============================================================

def extract_symbols(data):

    symbols = []

    def add_item(item):

        if isinstance(item, str):

            symbol = clean_symbol(item)

            if symbol:
                symbols.append(symbol)

            return

        if not isinstance(item, dict):
            return

        possible_keys = [
            "symbol",
            "market",
            "pair",
            "code",
            "name",
        ]

        for key in possible_keys:

            value = item.get(key)

            if value:

                symbol = clean_symbol(value)

                if symbol:
                    symbols.append(symbol)

                return

    # --------------------------------------------------------
    # LIST
    # --------------------------------------------------------

    if isinstance(data, list):

        for item in data:
            add_item(item)

    # --------------------------------------------------------
    # DICT
    # --------------------------------------------------------

    elif isinstance(data, dict):

        for key in [
            "data",
            "result",
            "markets",
            "symbols",
            "items",
        ]:

            value = data.get(key)

            if isinstance(value, list):

                for item in value:
                    add_item(item)

                if symbols:
                    break

        # اگر خود دیکشنری یک بازار باشد
        if not symbols:
            add_item(data)

    return list(dict.fromkeys(symbols))


# ============================================================
# GET MARKET LIST
# ============================================================

def get_usdt_markets():

    candidate_paths = [
        "/r/api/v1/markets",
        "/r/api/v1/tickers",
        "/r/api/v1/market",
    ]

    for path in candidate_paths:

        data = get_json(
            path,
            retries=3,
        )

        if data is None:
            continue

        symbols = extract_symbols(data)

        usdt = []

        for symbol in symbols:

            if symbol.endswith("USDT"):

                usdt.append(symbol)

        if usdt:

            # حذف تکراری
            usdt = list(dict.fromkeys(usdt))

            return usdt[:MAX_MARKETS]

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------
    #
    # اگر endpoint بازارها تغییر کرده باشد، سعی می‌کنیم
    # از endpoint اصلی موجود در نسخه‌های قبلی استفاده کنیم.
    # --------------------------------------------------------

    fallback = get_json(
        "/r/api/v1/trades",
        params={
            "limit": 1000,
        },
        retries=3,
    )

    symbols = extract_symbols(fallback)

    usdt = [
        s for s in symbols
        if s.endswith("USDT")
    ]

    return list(dict.fromkeys(usdt))[:MAX_MARKETS]


# ============================================================
# EXTRACT TRADES
# ============================================================

def extract_trades(data):

    # --------------------------------------------------------
    # مستقیم LIST
    # --------------------------------------------------------

    if isinstance(data, list):
        return data

    # --------------------------------------------------------
    # DICT
    # --------------------------------------------------------

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

        # بعضی APIها ممکن است result خودش dict باشد
        result = data.get("result")

        if isinstance(result, dict):

            for key in [
                "data",
                "trades",
                "items",
            ]:

                value = result.get(key)

                if isinstance(value, list):
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

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    for key in [
        "price",
        "p",
        "trade_price",
    ]:

        if key in item:

            price = safe_float(item.get(key))

            if price > 0:
                break

    # --------------------------------------------------------
    # QUANTITY
    # --------------------------------------------------------

    for key in [
        "quantity",
        "qty",
        "amount",
        "q",
        "volume",
    ]:

        if key in item:

            quantity = safe_float(item.get(key))

            if quantity > 0:
                break

    # --------------------------------------------------------
    # TIME
    # --------------------------------------------------------

    for key in [
        "timestamp",
        "time",
        "T",
        "created_at",
        "date",
    ]:

        if key in item:

            timestamp = item.get(key)

            if timestamp is not None:
                break

    # --------------------------------------------------------
    # SIDE
    # --------------------------------------------------------

    for key in [
        "side",
        "S",
        "type",
    ]:

        if key in item:

            side = str(item.get(key)).lower()

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

    # --------------------------------------------------------
    # مسیر اصلی Tabdeal که در نسخه‌های قبلی کار کرده
    # --------------------------------------------------------

    data = get_json(
        "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": TRADE_LIMIT,
        },
    )

    if data is None:
        return []

    raw_trades = extract_trades(data)

    normalized = []

    for item in raw_trades:

        trade = normalize_trade(item)

        if trade:
            normalized.append(trade)

    return normalized


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_5m_candles(trades):

    if not trades:
        return []

    prepared = []

    now_ms = int(time.time() * 1000)

    # فقط داده اخیر
    min_time_ms = now_ms - (
        RECENT_MINUTES * 60 * 1000
    )

    for trade in trades:

        price = safe_float(
            trade.get("price")
        )

        quantity = safe_float(
            trade.get("quantity"),
            0.0,
        )

        timestamp = trade.get("timestamp")

        if price <= 0:
            continue

        # ----------------------------------------------------
        # TIMESTAMP NORMALIZATION
        # ----------------------------------------------------

        ts = safe_float(
            timestamp,
            0.0,
        )

        if ts <= 0:
            continue

        # ثانیه یا میلی‌ثانیه
        if ts < 10000000000:
            ts *= 1000

        if ts < min_time_ms:
            continue

        prepared.append(
            (
                int(ts),
                price,
                quantity,
                trade.get("side", ""),
            )
        )

    if not prepared:
        return []

    prepared.sort(
        key=lambda x: x[0]
    )

    candles = {}

    for ts, price, qty, side in prepared:

        bucket = (
            ts // (5 * 60 * 1000)
        ) * (5 * 60 * 1000)

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

        candle = candles[bucket]

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

        # ----------------------------------------------------
        # SIDE
        # ----------------------------------------------------

        side_lower = str(
            side or ""
        ).lower()

        if side_lower in [
            "buy",
            "bid",
            "b",
        ]:

            candle["buy_volume"] += qty

        elif side_lower in [
            "sell",
            "ask",
            "s",
        ]:

            candle["sell_volume"] += qty

    return list(
        sorted(
            candles.values(),
            key=lambda x: x["timestamp"],
        )
    )


# ============================================================
# BUY PRESSURE
# ============================================================

def calculate_buy_pressure(candles):

    if not candles:
        return 0.0

    recent = candles[-3:]

    buy = 0.0
    sell = 0.0

    for candle in recent:

        buy += safe_float(
            candle.get("buy_volume")
        )

        sell += safe_float(
            candle.get("sell_volume")
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

        if close <= 0:
            return None

        previous_close = safe_float(
            previous["close"]
        )

        if previous_close <= 0:
            return None

        change_5m = (
            (close - previous_close)
            / previous_close
        ) * 100.0

        high = safe_float(
            current["high"]
        )

        low = safe_float(
            current["low"]
        )

        candle_range = high - low

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
            max(0, len(candles) - 6):-1
        ]

        if lookback:

            previous_high = max(
                safe_float(c["high"])
                for c in lookback
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

        # 5M MOMENTUM
        if change_5m >= 0.15:

            score += 1

            reasons.append(
                "5M MOMENTUM"
            )

        # BUY PRESSURE
        if buy_pressure >= 58:

            score += 1

            reasons.append(
                "BUY PRESSURE"
            )

        # STRONG CLOSE
        if candle_position >= 0.65:

            score += 1

            reasons.append(
                "STRONG CLOSE"
            )

        # BREAKOUT
        if breakout:

            score += 1

            reasons.append(
                "BREAKOUT"
            )

        # EARLY MOMENTUM
        if (
            change_5m >= 0.10
            and buy_pressure >= 55
        ):

            score += 1

            reasons.append(
                "EARLY MOMENTUM"
            )

        # BUYING
        if buy_pressure >= 70:

            score += 1

            reasons.append(
                "BUYING"
            )

        # ----------------------------------------------------
        # ANTI CHASE
        # ----------------------------------------------------

        if change_5m >= CHASE_LIMIT_5M:

            return None

        # ----------------------------------------------------
        # CONFIRMED
        # ----------------------------------------------------

        confirmed = (
            breakout
            and change_5m > 0
            and buy_pressure >= MIN_BUY_PRESSURE_CONFIRMED
            and candle_position >= MIN_CANDLE_POSITION
            and score >= CONFIRMED_MIN_SCORE
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

        sl = close * (
            1 - SL_PERCENT / 100
        )

        tp1 = close * (
            1 + TP1_PERCENT / 100
        )

        tp2 = close * (
            1 + TP2_PERCENT / 100
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
            f"ANALYZE ERROR {symbol}: {exc}"
        )

        return None


# ============================================================
# FORMAT RESULT
# ============================================================

def format_result(result):

    symbol = result["symbol"]

    price = result["price"]

    change = result["change_5m"]

    score = result["score"]

    pressure = result["buy_pressure"]

    sl = result["sl"]

    tp1 = result["tp1"]

    tp2 = result["tp2"]

    reasons = " + ".join(
        result["reasons"]
    )

    return (
        f"🟢 {symbol}\n"
        f"💰 Price: {price:.10g}\n"
        f"📈 5M: {change:+.2f}%\n"
        f"🎯 Score: {score}\n"
        f"🟢 Buy Pressure: {pressure:.0f}%\n"
        f"🚀 Breakout: "
        f"{'YES' if result['breakout'] else 'NO'}\n"
        f"🛡 SL: {sl:.10g}\n"
        f"🎯 TP1: {tp1:.10g}\n"
        f"🎯 TP2: {tp2:.10g}\n"
        f"🔎 {reasons}"
    )


# ============================================================
# SCAN ONE MARKET
# ============================================================

def scan_one(symbol):
    return analyze_market(symbol)


# ============================================================
# SCAN ALL MARKETS
# ============================================================

def run_scan():

    print(
        "ATI V40.2 SCAN START"
    )

    if not ping_tabdeal():

        send_telegram(
            "⚠️ ATI BOT V40.2\n\n"
            "❌ TABDEAL API ERROR\n"
            "Retrying on next scan."
        )

        return {
            "markets": 0,
            "data": 0,
            "confirmed": 0,
            "early": 0,
            "watch": 0,
        }

    markets = get_usdt_markets()

    if not markets:

        send_telegram(
            "⚠️ ATI BOT V40.2\n\n"
            "❌ NO USDT MARKETS FOUND\n"
            "Retrying on next scan."
        )

        return {
            "markets": 0,
            "data": 0,
            "confirmed": 0,
            "early": 0,
            "watch": 0,
        }

    markets = markets[:MAX_MARKETS]

    print(
        f"MARKETS: {len(markets)}"
    )

    results = []

    data_count = 0

    # --------------------------------------------------------
    # IMPORTANT:
    # فقط 6 درخواست همزمان
    # --------------------------------------------------------

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                scan_one,
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

                    data_count += 1

                    results.append(
                        result
                    )

            except Exception as exc:

                print(
                    f"SCAN ERROR {symbol}: "
                    f"{exc}"
                )

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

    confirmed.sort(
        key=lambda x: (
            x["score"],
            x["buy_pressure"],
            x["change_5m"],
        ),
        reverse=True,
    )

    early.sort(
        key=lambda x: (
            x["score"],
            x["buy_pressure"],
            x["change_5m"],
        ),
        reverse=True,
    )

    watch.sort(
        key=lambda x: (
            x["score"],
            x["buy_pressure"],
            x["change_5m"],
        ),
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
    # TELEGRAM MESSAGE
    # --------------------------------------------------------

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n"
        f"🚀 CLEAN EARLY ENTRY + CONFIRMED BREAKOUT\n"
        f"🛡 ANTI-FAKE BREAKOUT\n"
        f"🚫 ANTI-CHASE\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n"
        f"🎯 MARKETS WITH DATA: {data_count}\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 RECENT 5M DATA: YES\n"
        f"💓 HEARTBEAT: ON\n"
        f"🔧 REAL ORDERS: DISABLED\n"
    )

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

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "📊 SCAN SUMMARY\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Confirmed: {len(confirmed)}\n"
        f"⚡ Early: {len(early)}\n"
        f"🟡 Watch: {len(watch)}\n\n"
        "🔄 NEXT SCAN: ABOUT 5 MINUTES\n\n"
        f"🕐 {utc_string()}"
    )

    send_long_telegram(
        message
    )

    print(
        f"DATA={data_count} "
        f"CONFIRMED={len(confirmed)} "
        f"EARLY={len(early)} "
        f"WATCH={len(watch)}"
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
        f"📊 MARKETS: {stats.get('markets', 0)}\n"
        f"📊 DATA: {stats.get('data', 0)}\n"
        f"🟢 CONFIRMED: "
        f"{stats.get('confirmed', 0)}\n"
        f"⚡ EARLY: "
        f"{stats.get('early', 0)}\n"
        f"🟡 WATCH: "
        f"{stats.get('watch', 0)}\n"
        "🔧 REAL ORDERS: DISABLED\n\n"
        "🔄 NEXT SCAN: ABOUT 5 MINUTES\n"
        f"🕐 {utc_string()}"
    )

    send_telegram(
        message
    )


# ============================================================
# FOREVER LOOP
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

            # ------------------------------------------------
            # HEARTBEAT
            # ------------------------------------------------

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

        # ----------------------------------------------------
        # دقیقاً حدود 5 دقیقه بین شروع اسکن‌ها
        # ----------------------------------------------------

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
            f"NEXT SCAN IN "
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
