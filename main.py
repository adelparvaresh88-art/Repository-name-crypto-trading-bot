import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.1.3
# CLEAN EARLY ENTRY + CONFIRMED BREAKOUT
# CONTINUOUS 5 MINUTE SCANNER
# TELEGRAM HEARTBEAT ENABLED
# ============================================================

VERSION = "V40.1.3"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

REQUEST_TIMEOUT = 12

# ------------------------------------------------------------
# SCAN SETTINGS
# ------------------------------------------------------------

MAX_MARKETS = 529
MAX_WORKERS = 12
TOP_RESULTS = 15
TRADE_LIMIT = 1000
RECENT_MINUTES = 15

# Scan interval
SCAN_INTERVAL_SECONDS = 300

# Telegram heartbeat
HEARTBEAT_ENABLED = True

# ------------------------------------------------------------
# SIGNAL SETTINGS
# ------------------------------------------------------------

CONFIRMED_MIN_SCORE = 8
EARLY_MIN_SCORE = 6
WATCH_MIN_SCORE = 4

CHASE_LIMIT_5M = 7.0

# Risk
SL_PERCENT = 0.60
TP1_PERCENT = 1.00
TP2_PERCENT = 1.60

# ------------------------------------------------------------
# TELEGRAM
# ------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": f"ATI-Crypto-Bot/{VERSION}",
        "Accept": "application/json",
    }
)


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
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print(
            "TELEGRAM ERROR: "
            "missing TELEGRAM_BOT_TOKEN"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "TELEGRAM ERROR: "
            "missing TELEGRAM_CHAT_ID"
        )
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

        response = SESSION.post(
            url,
            json=payload,
            timeout=15,
        )

        if response.ok:
            print("TELEGRAM: OK")
            return True

        print(
            "TELEGRAM ERROR:",
            response.status_code,
            response.text[:500],
        )

    except Exception as exc:

        print(
            "TELEGRAM EXCEPTION:",
            repr(exc),
        )

    return False


# ============================================================
# SAFE JSON
# ============================================================

def get_json(path, params=None):

    url = BASE_URL + path

    try:

        response = SESSION.get(
            url,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response.json()

    except Exception as exc:

        print(
            f"API ERROR {path}:",
            repr(exc),
        )

        return None


# ============================================================
# TABDEAL CONNECTION
# ============================================================

def ping_tabdeal():

    data = get_json(
        "/r/api/v1/ping"
    )

    return data is not None


# ============================================================
# EXCHANGE INFO
# ============================================================

def extract_symbols(data):

    symbols = []

    if data is None:
        return symbols

    if isinstance(data, dict):

        raw = data.get("symbols")

        if isinstance(raw, list):
            data_list = raw

        elif isinstance(raw, dict):
            data_list = [raw]

        else:
            data_list = []

    elif isinstance(data, list):

        data_list = data

    else:

        data_list = []

    for item in data_list:

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("market")
            or item.get("name")
        )

        if not isinstance(symbol, str):
            continue

        symbol = (
            symbol
            .upper()
            .replace("_", "")
            .replace("-", "")
        )

        if not symbol.endswith("USDT"):
            continue

        if symbol in symbols:
            continue

        status = str(
            item.get(
                "status",
                "TRADING"
            )
        ).upper()

        if status not in (
            "TRADING",
            "ACTIVE",
            "ENABLED",
            "1",
            "",
        ):
            continue

        symbols.append(symbol)

    return symbols


def get_usdt_markets():

    data = get_json(
        "/r/api/v1/exchangeInfo"
    )

    return extract_symbols(data)


# ============================================================
# TRADE DATA PARSER
# ============================================================

def extract_trades(data):

    if data is None:
        return []

    if isinstance(data, list):

        raw = data

    elif isinstance(data, dict):

        raw = None

        for key in (
            "data",
            "trades",
            "results",
            "rows",
            "items",
        ):

            candidate = data.get(key)

            if isinstance(candidate, list):

                raw = candidate
                break

        if raw is None:
            return []

    else:

        return []

    result = []

    for item in raw:

        if not isinstance(item, dict):
            continue

        try:

            price = float(
                item.get(
                    "price",
                    0
                )
            )

            qty = float(
                item.get(
                    "qty",
                    item.get(
                        "quantity",
                        0
                    ),
                )
            )

            trade_time = int(
                item.get(
                    "time",
                    item.get(
                        "timestamp",
                        item.get(
                            "T",
                            0
                        ),
                    ),
                )
            )

            if price <= 0:
                continue

            if trade_time <= 0:
                continue

            # Convert seconds to milliseconds
            if trade_time < 10_000_000_000:
                trade_time *= 1000

            is_buyer_maker = bool(
                item.get(
                    "isBuyerMaker",
                    item.get(
                        "is_buyer_maker",
                        False
                    ),
                )
            )

            result.append(
                {
                    "price": price,
                    "qty": qty,
                    "time": trade_time,
                    "buyer_maker": is_buyer_maker,
                }
            )

        except Exception:
            continue

    result.sort(
        key=lambda x: x["time"]
    )

    return result


# ============================================================
# GET TRADES
# ============================================================

def get_symbol_trades(symbol):

    data = get_json(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": TRADE_LIMIT,
        },
    )

    return extract_trades(data)


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_5m_candles(trades):

    if not trades:
        return []

    now_ms = int(
        time.time() * 1000
    )

    start_ms = (
        now_ms
        - RECENT_MINUTES * 60 * 1000
    )

    recent = [
        trade
        for trade in trades
        if trade["time"] >= start_ms
    ]

    if not recent:
        return []

    candles = {}

    bucket_ms = (
        5 * 60 * 1000
    )

    for trade in recent:

        bucket = (
            trade["time"]
            // bucket_ms
        ) * bucket_ms

        if bucket not in candles:

            candles[bucket] = {
                "time": bucket,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
                "buy_volume": 0.0,
                "sell_volume": 0.0,
                "trades": 0,
            }

        candle = candles[bucket]

        price = trade["price"]
        qty = trade["qty"]

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

        if trade["buyer_maker"]:

            candle["sell_volume"] += qty

        else:

            candle["buy_volume"] += qty

        candle["trades"] += 1

    result = list(
        candles.values()
    )

    result.sort(
        key=lambda x: x["time"]
    )

    return result


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_market(symbol):

    try:

        trades = get_symbol_trades(
            symbol
        )

        if len(trades) < 10:
            return None

        candles = build_5m_candles(
            trades
        )

        if len(candles) < 2:
            return None

        last = candles[-1]
        previous = candles[-2]

        price = last["close"]

        if price <= 0:
            return None

        previous_close = (
            previous["close"]
        )

        if previous_close <= 0:
            return None

        # ----------------------------------------------------
        # 5M CHANGE
        # ----------------------------------------------------

        change_5m = (
            (
                price
                - previous_close
            )
            / previous_close
            * 100
        )

        # ----------------------------------------------------
        # CANDLE RANGE
        # ----------------------------------------------------

        candle_range = (
            (
                last["high"]
                - last["low"]
            )
            / price
            * 100
        )

        if candle_range <= 0:
            candle_range = 0.001

        # ----------------------------------------------------
        # CLOSE POSITION
        # ----------------------------------------------------

        if last["high"] > last["low"]:

            candle_position = (
                (
                    last["close"]
                    - last["low"]
                )
                / (
                    last["high"]
                    - last["low"]
                )
            )

        else:

            candle_position = 0.5

        # ----------------------------------------------------
        # BUY PRESSURE
        # ----------------------------------------------------

        total_volume = (
            last["buy_volume"]
            + last["sell_volume"]
        )

        if total_volume > 0:

            buy_ratio = (
                last["buy_volume"]
                / total_volume
                * 100
            )

        else:

            buy_ratio = 50.0

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        breakout = (
            last["close"]
            > previous["high"]
        )

        previous_high = (
            previous["high"]
        )

        if previous_high > 0:

            breakout_percent = (
                (
                    last["close"]
                    - previous_high
                )
                / previous_high
                * 100
            )

        else:

            breakout_percent = 0.0

        # ----------------------------------------------------
        # SCORE
        # ----------------------------------------------------

        score = 0
        reasons = []

        # Momentum
        if change_5m >= 0.30:

            score += 2
            reasons.append(
                "5M MOMENTUM"
            )

        elif change_5m >= 0.15:

            score += 1
            reasons.append(
                "EARLY MOMENTUM"
            )

        # Buy pressure
        if buy_ratio >= 65:

            score += 2
            reasons.append(
                "BUY PRESSURE"
            )

        elif buy_ratio >= 58:

            score += 1
            reasons.append(
                "BUYING"
            )

        # Strong close
        if candle_position >= 0.80:

            score += 2
            reasons.append(
                "STRONG CLOSE"
            )

        elif candle_position >= 0.65:

            score += 1
            reasons.append(
                "GOOD CLOSE"
            )

        # Breakout
        if breakout:

            score += 2
            reasons.append(
                "BREAKOUT"
            )

        elif (
            last["high"]
            >= previous["high"] * 0.997
            and change_5m > 0
        ):

            score += 1
            reasons.append(
                "PRE-BREAKOUT"
            )

        # Activity
        if last["trades"] >= 20:

            score += 1
            reasons.append(
                "ACTIVE"
            )

        # ----------------------------------------------------
        # CHASE PROTECTION
        # ----------------------------------------------------

        chase = (
            change_5m >= CHASE_LIMIT_5M
        )

        if chase:

            return {
                "symbol": symbol,
                "price": price,
                "change_5m": change_5m,
                "score": score,
                "buy_ratio": buy_ratio,
                "candle_position": candle_position,
                "breakout": breakout,
                "breakout_percent": breakout_percent,
                "signal": "CHASE",
                "sl": price * (
                    1 - SL_PERCENT / 100
                ),
                "tp1": price * (
                    1 + TP1_PERCENT / 100
                ),
                "tp2": price * (
                    1 + TP2_PERCENT / 100
                ),
                "reasons": reasons,
            }

        # ----------------------------------------------------
        # SIGNAL
        # ----------------------------------------------------

        # IMPORTANT:
        # Confirmed BUY requires real buy pressure.
        # This prevents cases like:
        # Breakout YES + Buy Pressure 0%
        # being treated as confirmed BUY.

        if (
            score >= CONFIRMED_MIN_SCORE
            and breakout
            and buy_ratio >= 58
            and candle_position >= 0.65
            and change_5m > 0
        ):

            signal = "CONFIRMED BUY"

        elif (
            score >= EARLY_MIN_SCORE
            and change_5m > 0
            and buy_ratio >= 55
            and candle_position >= 0.60
        ):

            signal = "EARLY ENTRY"

        elif (
            score >= WATCH_MIN_SCORE
            and change_5m > 0
        ):

            signal = "WATCH"

        else:

            signal = "NONE"

        # ----------------------------------------------------
        # SL / TP
        # ----------------------------------------------------

        sl = price * (
            1 - SL_PERCENT / 100
        )

        tp1 = price * (
            1 + TP1_PERCENT / 100
        )

        tp2 = price * (
            1 + TP2_PERCENT / 100
        )

        return {
            "symbol": symbol,
            "price": price,
            "change_5m": change_5m,
            "score": score,
            "buy_ratio": buy_ratio,
            "candle_position": candle_position,
            "breakout": breakout,
            "breakout_percent": breakout_percent,
            "signal": signal,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "reasons": reasons,
        }

    except Exception as exc:

        print(
            f"ANALYZE ERROR {symbol}:",
            repr(exc),
        )

        return None


# ============================================================
# FORMAT RESULT
# ============================================================

def format_result(item):

    return (
        f"🟢 {item['symbol']}\n"
        f"💰 Price: {item['price']:.8g}\n"
        f"📈 5M: {item['change_5m']:+.2f}%\n"
        f"🎯 Score: {item['score']}\n"
        f"🟢 Buy Pressure: "
        f"{item['buy_ratio']:.0f}%\n"
        f"🚀 Breakout: "
        f"{'YES' if item['breakout'] else 'NO'}\n"
        f"🛡 SL: {item['sl']:.8g}\n"
        f"🎯 TP1: {item['tp1']:.8g}\n"
        f"🎯 TP2: {item['tp2']:.8g}\n"
        f"🔎 {' + '.join(item['reasons'])}"
    )


# ============================================================
# SEND LONG TELEGRAM MESSAGE SAFELY
# ============================================================

def send_long_telegram(message):

    max_length = 3900

    if len(message) <= max_length:

        return send_telegram(
            message
        )

    success = True

    start = 0

    while start < len(message):

        chunk = message[
            start:start + max_length
        ]

        if not send_telegram(
            chunk
        ):
            success = False

        start += max_length

        time.sleep(1)

    return success


# ============================================================
# HEARTBEAT
# ============================================================

def send_heartbeat(
    status,
    markets=0,
    results=0,
    confirmed=0,
    early=0,
    watch=0,
):

    if not HEARTBEAT_ENABLED:
        return

    message = (
        f"💓 ATI BOT HEARTBEAT\n\n"
        f"⚡ VERSION: {VERSION}\n"
        f"📡 STATUS: {status}\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"📊 MARKETS: {markets}\n"
        f"📊 DATA: {results}\n"
        f"🟢 CONFIRMED: {confirmed}\n"
        f"⚡ EARLY: {early}\n"
        f"🟡 WATCH: {watch}\n"
        f"🔧 REAL ORDERS: DISABLED\n\n"
        f"🔄 NEXT SCAN: ABOUT 5 MINUTES\n"
        f"🕐 {utc_string()}"
    )

    send_telegram(
        message
    )


# ============================================================
# SINGLE SCAN
# ============================================================

def run_scan():

    print("=" * 60)

    print(
        f"ATI CRYPTO BOT {VERSION}"
    )

    print(
        "CONTINUOUS 5 MINUTE SCANNER"
    )

    print(
        "TELEGRAM HEARTBEAT: ON"
    )

    print("=" * 60)

    print(
        "📡 TABDEAL API: CONNECTING..."
    )

    # --------------------------------------------------------
    # API
    # --------------------------------------------------------

    if not ping_tabdeal():

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ TABDEAL API ERROR\n"
            f"Unable to connect to Tabdeal.\n\n"
            f"🔄 BOT WILL RETRY IN 5 MINUTES\n"
            f"🕐 {utc_string()}"
        )

        send_telegram(
            message
        )

        return {
            "markets": 0,
            "results": 0,
            "confirmed": 0,
            "early": 0,
            "watch": 0,
        }

    print(
        "📡 TABDEAL API: OK"
    )

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    markets = get_usdt_markets()

    if not markets:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ MARKET DATA ERROR\n"
            f"No USDT markets found.\n\n"
            f"🔄 BOT WILL RETRY IN 5 MINUTES\n"
            f"🕐 {utc_string()}"
        )

        send_telegram(
            message
        )

        return {
            "markets": 0,
            "results": 0,
            "confirmed": 0,
            "early": 0,
            "watch": 0,
        }

    print(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
    )

    markets = markets[
        :MAX_MARKETS
    ]

    print(
        f"🎯 DEEP SCAN: "
        f"{len(markets)}"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    results = []

    completed = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {
            executor.submit(
                analyze_market,
                symbol,
            ): symbol
            for symbol in markets
        }

        for future in as_completed(
            future_map
        ):

            completed += 1

            try:

                result = (
                    future.result()
                )

                if result is not None:

                    results.append(
                        result
                    )

            except Exception as exc:

                symbol = (
                    future_map[future]
                )

                print(
                    f"SCAN ERROR {symbol}:",
                    repr(exc),
                )

            if completed % 50 == 0:

                print(
                    f"📡 SCAN PROGRESS: "
                    f"{completed}/"
                    f"{len(markets)}"
                )

    # --------------------------------------------------------
    # SORT RESULTS
    # --------------------------------------------------------

    confirmed = sorted(
        [
            x
            for x in results
            if x["signal"]
            == "CONFIRMED BUY"
        ],
        key=lambda x: (
            x["score"],
            x["change_5m"],
            x["buy_ratio"],
        ),
        reverse=True,
    )

    early = sorted(
        [
            x
            for x in results
            if x["signal"]
            == "EARLY ENTRY"
        ],
        key=lambda x: (
            x["score"],
            x["change_5m"],
            x["buy_ratio"],
        ),
        reverse=True,
    )

    watch = sorted(
        [
            x
            for x in results
            if x["signal"]
            == "WATCH"
        ],
        key=lambda x: (
            x["score"],
            x["change_5m"],
            x["buy_ratio"],
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

    message_parts = []

    message_parts.append(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )

    message_parts.append(
        "🚀 CLEAN EARLY ENTRY + "
        "CONFIRMED BREAKOUT"
    )

    message_parts.append(
        "🛡 ANTI-FAKE BREAKOUT"
    )

    message_parts.append(
        "🚫 ANTI-CHASE"
    )

    message_parts.append("")

    message_parts.append(
        "📡 TABDEAL API: OK"
    )

    message_parts.append(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
    )

    message_parts.append(
        f"🎯 MARKETS WITH DATA: "
        f"{len(results)}"
    )

    message_parts.append(
        "⏱ TIMEFRAME: 5m"
    )

    message_parts.append(
        "🕯 RECENT 5M DATA: YES"
    )

    message_parts.append(
        "💓 HEARTBEAT: ON"
    )

    message_parts.append(
        "🔧 REAL ORDERS: DISABLED"
    )

    # --------------------------------------------------------
    # CONFIRMED
    # --------------------------------------------------------

    message_parts.extend(
        [
            "",
            "━━━━━━━━━━━━━━━━━━",
            "🟢 CONFIRMED BUY",
            "━━━━━━━━━━━━━━━━━━",
        ]
    )

    if confirmed:

        for item in confirmed:

            message_parts.append(
                format_result(item)
            )

            message_parts.append("")

    else:

        message_parts.append(
            "NONE"
        )

    # --------------------------------------------------------
    # EARLY
    # --------------------------------------------------------

    message_parts.extend(
        [
            "━━━━━━━━━━━━━━━━━━",
            "⚡ EARLY ENTRY",
            "━━━━━━━━━━━━━━━━━━",
        ]
    )

    if early:

        for item in early:

            message_parts.append(
                format_result(item)
            )

            message_parts.append("")

    else:

        message_parts.append(
            "NONE"
        )

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    message_parts.extend(
        [
            "━━━━━━━━━━━━━━━━━━",
            "🟡 WATCH",
            "━━━━━━━━━━━━━━━━━━",
        ]
    )

    if watch:

        for item in watch:

            message_parts.append(
                format_result(item)
            )

            message_parts.append("")

    else:

        message_parts.append(
            "NONE"
        )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    message_parts.extend(
        [
            "━━━━━━━━━━━━━━━━━━",
            "📊 SCAN SUMMARY",
            "━━━━━━━━━━━━━━━━━━",
            f"🟢 Confirmed: "
            f"{len(confirmed)}",
            f"⚡ Early: "
            f"{len(early)}",
            f"🟡 Watch: "
            f"{len(watch)}",
            "",
            "🔄 NEXT SCAN: "
            "ABOUT 5 MINUTES",
            "",
            f"🕐 {utc_string()}",
        ]
    )

    message = "\n".join(
        message_parts
    )

    send_long_telegram(
        message
    )

    print("")
    print(
        "✅ SCAN FINISHED"
    )

    print(
        f"📊 RESULTS: "
        f"{len(results)}"
    )

    print(
        f"🟢 CONFIRMED: "
        f"{len(confirmed)}"
    )

    print(
        f"⚡ EARLY: "
        f"{len(early)}"
    )

    print(
        f"🟡 WATCH: "
        f"{len(watch)}"
    )

    return {
        "markets": len(markets),
        "results": len(results),
        "confirmed": len(confirmed),
        "early": len(early),
        "watch": len(watch),
    }


# ============================================================
# CONTINUOUS BOT LOOP
# ============================================================

def run_forever():

    print("")
    print("=" * 60)
    print(
        f"🚀 ATI BOT {VERSION}"
    )
    print(
        "🔄 CONTINUOUS MODE ENABLED"
    )
    print(
        "⏱ SCAN EVERY 5 MINUTES"
    )
    print(
        "💓 HEARTBEAT ENABLED"
    )
    print("=" * 60)
    print("")

    # --------------------------------------------------------
    # START MESSAGE
    # --------------------------------------------------------

    send_telegram(
        f"🟢 ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED/RECENT 5M DATA: YES\n"
        f"💓 HEARTBEAT: ON\n"
        f"🔧 REAL ORDERS: DISABLED\n\n"
        f"🔄 CONTINUOUS MODE: ON\n"
        f"🕐 {utc_string()}"
    )

    while True:

        scan_start = time.time()

        try:

            stats = run_scan()

            send_heartbeat(
                "ALIVE",
                markets=stats[
                    "markets"
                ],
                results=stats[
                    "results"
                ],
                confirmed=stats[
                    "confirmed"
                ],
                early=stats[
                    "early"
                ],
                watch=stats[
                    "watch"
                ],
            )

        except Exception as exc:

            print(
                "❌ SCAN LOOP ERROR:",
                repr(exc),
            )

            send_telegram(
                f"⚠️ ATI CRYPTO BOT "
                f"{VERSION}\n\n"
                f"❌ SCAN ERROR\n"
                f"{repr(exc)}\n\n"
                f"🔄 RETRY IN 5 MINUTES\n"
                f"🕐 {utc_string()}"
            )

        # ----------------------------------------------------
        # IMPORTANT:
        # Wait exactly enough so scans are approximately
        # 5 minutes apart.
        # ----------------------------------------------------

        elapsed = (
            time.time()
            - scan_start
        )

        wait_seconds = max(
            5,
            SCAN_INTERVAL_SECONDS
            - int(elapsed)
        )

        print("")
        print(
            f"💓 BOT ALIVE"
        )

        print(
            f"⏳ NEXT SCAN IN "
            f"{wait_seconds} SECONDS"
        )

        print(
            f"🕐 {utc_string()}"
        )

        # Small countdown messages in GitHub log
        # without Telegram spam.

        remaining = wait_seconds

        while remaining > 0:

            sleep_time = min(
                30,
                remaining
            )

            time.sleep(
                sleep_time
            )

            remaining -= sleep_time

            if remaining > 0:

                print(
                    f"⏳ NEXT SCAN: "
                    f"{remaining}s"
                )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        run_forever()

    except KeyboardInterrupt:

        print(
            "🛑 BOT INTERRUPTED"
        )

        send_telegram(
            f"🛑 ATI CRYPTO BOT "
            f"{VERSION}\n\n"
            f"BOT STOPPED MANUALLY\n"
            f"🕐 {utc_string()}"
        )

        raise SystemExit(130)

    except Exception as exc:

        print(
            "❌ FATAL ERROR:",
            repr(exc),
        )

        send_telegram(
            f"⚠️ ATI CRYPTO BOT "
            f"{VERSION}\n\n"
            f"❌ FATAL ERROR\n"
            f"{repr(exc)}\n\n"
            f"🕐 {utc_string()}"
        )

        raise SystemExit(1)
