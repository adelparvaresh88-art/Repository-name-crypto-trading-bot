import os
import time
import hmac
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.32
# TABDEAL SPOT
# AUTH FIX + 5M CLOSED-CANDLE SCANNER
# ============================================================

VERSION = "V40.2.32"

BASE_URL = "https://api1.tabdeal.org"

RECV_WINDOW = int(os.getenv("RECV_WINDOW", "5000"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

TRADE_LIMIT = 1000
SCAN_UNIVERSE = 20
TOP_RESULTS = 10

TIMEFRAME_MINUTES = 5
BREAKOUT_LOOKBACK = 12
MIN_CANDLES = 30

MAX_CHASE_PCT = 1.50
MIN_VOLUME_RATIO = 1.10

# ============================================================
# HARD SAFETY
# ============================================================

LIVE_TRADING = False
REAL_ORDERS = False
BUY_LOCK = True


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


def telegram(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return

    try:

        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )

    except Exception as exc:
        print("TELEGRAM ERROR:", exc)

    print(message)


# ============================================================
# HTTP
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot-V40.2.32",
        "Accept": "application/json",
    }
)


# ============================================================
# API CREDENTIALS
#
# IMPORTANT:
# TABDIL IS FIRST BECAUSE THIS WAS THE LAST VERIFIED
# WORKING AUTH PAIR.
# ============================================================

def get_credentials():

    credentials = [
        (
            os.getenv(
                "TABDIL_API_KEY",
                ""
            ).strip(),

            os.getenv(
                "TABDIL_API_SECRET",
                ""
            ).strip(),

            "TABDIL",
        ),

        (
            os.getenv(
                "TABDEAL_API_KEY",
                ""
            ).strip(),

            os.getenv(
                "TABDEAL_API_SECRET",
                ""
            ).strip(),

            "TABDEAL",
        ),
    ]

    for api_key, api_secret, name in credentials:

        if api_key and api_secret:

            return (
                api_key,
                api_secret,
                name,
            )

    return "", "", "NONE"


API_KEY, API_SECRET, WORKING_PAIR = get_credentials()


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():

    response = SESSION.get(
        f"{BASE_URL}/r/api/v1/time",
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):

        value = data.get("serverTime")

        if value is not None:
            return int(value)

    raise RuntimeError(
        f"Invalid server time response: {data}"
    )


# ============================================================
# HMAC SIGNATURE
# ============================================================

def make_signature(query_string):

    return hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ============================================================
# SIGNED GET
# ============================================================

def signed_get(path, extra_params=None):

    if extra_params is None:
        extra_params = {}

    # --------------------------------------------------------
    # Use server timestamp.
    # This was already verified successfully in V40.2.30.
    # --------------------------------------------------------

    timestamp = get_server_time()

    # --------------------------------------------------------
    # FIXED PARAMETER ORDER
    # --------------------------------------------------------

    params = {}

    for key, value in extra_params.items():

        if value is None:
            continue

        params[key] = value

    params["timestamp"] = timestamp
    params["recvWindow"] = RECV_WINDOW

    query_parts = []

    for key, value in params.items():

        query_parts.append(
            f"{key}={value}"
        )

    query_string = "&".join(
        query_parts
    )

    signature = make_signature(
        query_string
    )

    request_params = dict(params)

    request_params["signature"] = signature

    response = SESSION.get(
        f"{BASE_URL}{path}",
        params=request_params,
        headers={
            "X-MBX-APIKEY": API_KEY,
        },
        timeout=REQUEST_TIMEOUT,
    )

    return response


# ============================================================
# AUTH TEST
# ============================================================

def auth_test():

    if not API_KEY or not API_SECRET:

        raise RuntimeError(
            "API KEY / SECRET NOT FOUND"
        )

    local_before = int(
        time.time() * 1000
    )

    server = get_server_time()

    local_after = int(
        time.time() * 1000
    )

    local_average = (
        local_before + local_after
    ) // 2

    diff = local_average - server

    telegram(
        "\n".join(
            [
                f"🕐 TABDEAL TIME CHECK {VERSION}",
                "",
                f"LOCAL: {local_average}",
                f"SERVER: {server}",
                f"DIFF: {diff} ms",
                "",
                f"🔑 AUTH PAIR: {WORKING_PAIR}",
                "",
            ]
        )
    )

    response = signed_get(
        "/r/api/v1/account"
    )

    try:
        data = response.json()
    except Exception:
        data = response.text

    if response.status_code != 200:

        raise RuntimeError(
            f"AUTH FAILED HTTP {response.status_code}: {data}"
        )

    if isinstance(data, dict):

        code = data.get("code")

        if code not in (
            None,
            0,
            "0",
        ):

            raise RuntimeError(
                f"AUTH FAILED CODE {code}: {data}"
            )

    telegram(
        "\n".join(
            [
                f"✅ ATI API AUTH SUCCESS {VERSION}",
                "",
                f"🟢 WORKING PAIR: {WORKING_PAIR}",
                "🔐 HMAC-SHA256",
                "🔢 SERVER TIMESTAMP",
                "🔢 RECVWINDOW: 5000",
                "",
                "📡 /r/api/v1/account",
                "",
                "🔒 REAL BUY: DISABLED",
                "🛑 NO ORDER WAS SENT",
            ]
        )
    )

    return True


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    response = SESSION.get(
        f"{BASE_URL}/r/api/v1/exchangeInfo",
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# EXCHANGE PARSER
# ============================================================

def extract_symbols(raw):

    if isinstance(raw, list):
        return raw

    if isinstance(raw, dict):

        if isinstance(
            raw.get("symbols"),
            list,
        ):
            return raw["symbols"]

        data = raw.get("data")

        if isinstance(data, list):
            return data

        if isinstance(data, dict):

            if isinstance(
                data.get("symbols"),
                list,
            ):
                return data["symbols"]

    return []


def normalize_symbol(value):

    if value is None:
        return ""

    return (
        str(value)
        .upper()
        .replace("_", "")
        .replace("-", "")
        .replace("/", "")
        .strip()
    )


def get_symbol_name(item):

    if not isinstance(item, dict):
        return ""

    for key in (
        "symbol",
        "tabdealSymbol",
        "market",
    ):

        value = item.get(key)

        if value:
            return normalize_symbol(value)

    return ""


def get_usdt_markets(raw):

    symbols = extract_symbols(raw)

    markets = []

    for item in symbols:

        symbol = get_symbol_name(item)

        if not symbol:
            continue

        if not symbol.endswith("USDT"):
            continue

        status = str(
            item.get(
                "status",
                "TRADING",
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

        markets.append(symbol)

    return list(
        dict.fromkeys(markets)
    )


# ============================================================
# RECENT TRADES
# ============================================================

def get_recent_trades(symbol):

    response = SESSION.get(
        f"{BASE_URL}/r/api/v1/trades",
        params={
            "tabdealSymbol": symbol,
            "limit": TRADE_LIMIT,
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# TRADE PARSER
# ============================================================

def extract_trade_list(raw):

    if isinstance(raw, list):
        return raw

    if isinstance(raw, dict):

        for key in (
            "data",
            "trades",
            "results",
        ):

            value = raw.get(key)

            if isinstance(value, list):
                return value

    return []


def parse_trade(trade):

    if not isinstance(trade, dict):
        return None

    price = (
        trade.get("price")
        if trade.get("price") is not None
        else trade.get("p")
    )

    quantity = (
        trade.get("qty")
        if trade.get("qty") is not None
        else trade.get("quantity")
    )

    if quantity is None:
        quantity = trade.get("q")

    timestamp = (
        trade.get("time")
        if trade.get("time") is not None
        else trade.get("timestamp")
    )

    if timestamp is None:
        timestamp = trade.get("T")

    if (
        price is None
        or quantity is None
        or timestamp is None
    ):
        return None

    try:

        price = float(price)
        quantity = float(quantity)
        timestamp = int(
            float(timestamp)
        )

        if timestamp < 10_000_000_000:
            timestamp *= 1000

        if (
            price <= 0
            or quantity <= 0
        ):
            return None

        return {
            "price": price,
            "qty": quantity,
            "time": timestamp,
        }

    except Exception:
        return None


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_5m_candles(raw):

    raw_trades = extract_trade_list(
        raw
    )

    trades = []

    for item in raw_trades:

        parsed = parse_trade(item)

        if parsed:
            trades.append(parsed)

    if not trades:
        return []

    trades.sort(
        key=lambda x: x["time"]
    )

    bucket_ms = (
        TIMEFRAME_MINUTES
        * 60
        * 1000
    )

    buckets = {}

    for trade in trades:

        bucket = (
            trade["time"]
            // bucket_ms
        ) * bucket_ms

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
                "trades": 0,
            }

        candle = buckets[bucket]

        candle["high"] = max(
            candle["high"],
            trade["price"],
        )

        candle["low"] = min(
            candle["low"],
            trade["price"],
        )

        candle["close"] = trade["price"]

        candle["volume"] += (
            trade["qty"]
        )

        candle["trades"] += 1

    candles = [
        buckets[key]
        for key in sorted(buckets)
    ]

    # --------------------------------------------------------
    # REMOVE OPEN 5M CANDLE
    # --------------------------------------------------------

    now_ms = int(
        time.time() * 1000
    )

    current_bucket = (
        now_ms
        // bucket_ms
    ) * bucket_ms

    return [
        candle
        for candle in candles
        if candle["time"] < current_bucket
    ]


# ============================================================
# HELPERS
# ============================================================

def average(values):

    if not values:
        return 0.0

    return sum(values) / len(values)


def body_ratio(candle):

    candle_range = max(
        candle["high"]
        - candle["low"],
        1e-12,
    )

    body = abs(
        candle["close"]
        - candle["open"]
    )

    return body / candle_range


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_market(symbol):

    try:

        raw = get_recent_trades(
            symbol
        )

        candles = build_5m_candles(
            raw
        )

        if len(candles) < MIN_CANDLES:

            return {
                "symbol": symbol,
                "valid": False,
                "reason": "NOT_ENOUGH_CANDLES",
            }

        last = candles[-1]

        history = candles[
            -(BREAKOUT_LOOKBACK + 1):-1
        ]

        if len(history) < BREAKOUT_LOOKBACK:

            return {
                "symbol": symbol,
                "valid": False,
                "reason": "SHORT_HISTORY",
            }

        resistance = max(
            c["high"]
            for c in history
        )

        average_volume = average(
            [
                c["volume"]
                for c in history[-6:]
            ]
        )

        volume_ratio = (
            last["volume"]
            / max(
                average_volume,
                1e-12,
            )
        )

        close = last["close"]

        breakout_pct = (
            (close - resistance)
            / resistance
            * 100
        )

        body = body_ratio(
            last
        )

        bullish = (
            last["close"]
            > last["open"]
        )

        # 15 MIN
        close_15m = candles[-4]["close"]

        momentum_15m = (
            (close - close_15m)
            / close_15m
            * 100
        )

        # 1 HOUR
        close_1h = candles[-13]["close"]

        momentum_1h = (
            (close - close_1h)
            / close_1h
            * 100
        )

        chase_pct = max(
            0.0,
            breakout_pct,
        )

        score = 0

        reasons = []

        if breakout_pct > 0:
            score += 5
            reasons.append(
                "BREAKOUT"
            )

        if (
            bullish
            and body >= 0.55
        ):
            score += 3
            reasons.append(
                "STRONG_CANDLE"
            )

        if volume_ratio >= MIN_VOLUME_RATIO:
            score += 4
            reasons.append(
                "VOLUME"
            )

        if momentum_15m > 0.20:
            score += 2
            reasons.append(
                "15M_UP"
            )

        if momentum_1h > 0.30:
            score += 3
            reasons.append(
                "1H_UP"
            )

        if close > resistance:
            score += 2
            reasons.append(
                "CLOSE_ABOVE_RESISTANCE"
            )

        valid = True

        if not bullish:
            valid = False

        if close <= resistance:
            valid = False

        if volume_ratio < MIN_VOLUME_RATIO:
            valid = False

        if body < 0.40:
            valid = False

        if momentum_15m <= 0:
            valid = False

        if chase_pct > MAX_CHASE_PCT:
            valid = False

        if score < 12:
            valid = False

        return {
            "symbol": symbol,
            "valid": valid,
            "score": score,
            "close": close,
            "resistance": resistance,
            "breakout_pct": breakout_pct,
            "volume_ratio": volume_ratio,
            "body_ratio": body,
            "momentum_15m": momentum_15m,
            "momentum_1h": momentum_1h,
            "candles": len(candles),
            "reasons": reasons,
        }

    except Exception as exc:

        return {
            "symbol": symbol,
            "valid": False,
            "reason": f"ERROR: {exc}",
        }


# ============================================================
# SCANNER
# ============================================================

def scan_markets(markets):

    candidates = markets[
        :SCAN_UNIVERSE
    ]

    telegram(
        "\n".join(
            [
                f"📊 ATI 5M SCANNER {VERSION}",
                "",
                f"🟢 USDT MARKETS: {len(markets)}",
                f"🔎 SCAN UNIVERSE: {len(candidates)}",
                "",
                "🕯 CLOSED 5M CANDLE: YES",
                "📈 BREAKOUT: ON",
                "📊 VOLUME: ON",
                "⚡ MOMENTUM: ON",
                "",
                "🔒 REAL ORDERS: DISABLED",
                "🛑 NO ORDER WILL BE SENT",
            ]
        )
    )

    start = time.time()

    results = []

    with ThreadPoolExecutor(
        max_workers=6
    ) as executor:

        future_map = {
            executor.submit(
                analyze_market,
                symbol,
            ): symbol
            for symbol in candidates
        }

        for future in as_completed(
            future_map
        ):

            symbol = future_map[future]

            try:

                results.append(
                    future.result()
                )

            except Exception as exc:

                results.append(
                    {
                        "symbol": symbol,
                        "valid": False,
                        "reason": str(exc),
                    }
                )

    elapsed = (
        time.time() - start
    )

    valid = [
        r
        for r in results
        if r.get("valid")
    ]

    valid.sort(
        key=lambda x: (
            x.get("score", 0),
            x.get("volume_ratio", 0),
            x.get("momentum_15m", 0),
        ),
        reverse=True,
    )

    return (
        valid[:TOP_RESULTS],
        elapsed,
        results,
    )


# ============================================================
# TELEGRAM RESULTS
# ============================================================

def send_scan_result(
    top,
    elapsed,
    total_results,
):

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    lines = [
        f"⚡ ATI CRYPTO BOT {VERSION}",
        "",
        "📊 5M MARKET SCAN COMPLETE",
        f"🕐 {now}",
        "",
        f"🔎 MARKETS CHECKED: {total_results}",
        f"⏱ SCAN TIME: {elapsed:.1f}s",
        f"🎯 SIGNALS: {len(top)}",
        "",
        "🔒 REAL ORDERS: DISABLED",
        "🛑 NO ORDER WAS SENT",
        "",
    ]

    if not top:

        lines.extend(
            [
                "⚪ NO QUALIFIED BREAKOUT",
                "",
                "🕯 CLOSED CANDLE ONLY",
                "🚫 WEAK SIGNALS FILTERED",
                "🚫 NO REAL BUY",
            ]
        )

        telegram(
            "\n".join(lines)
        )

        return

    lines.extend(
        [
            "🏆 TOP 10 CANDIDATES",
            "",
        ]
    )

    for index, item in enumerate(
        top,
        start=1,
    ):

        reasons = ",".join(
            item.get(
                "reasons",
                [],
            )
        )

        lines.extend(
            [
                f"{index}. 🟢 {item['symbol']}",
                f"   SCORE: {item['score']}/19",
                f"   PRICE: {item['close']:.8g}",
                f"   BREAKOUT: {item['breakout_pct']:.2f}%",
                f"   VOLUME: {item['volume_ratio']:.2f}x",
                f"   15M: {item['momentum_15m']:.2f}%",
                f"   1H: {item['momentum_1h']:.2f}%",
                f"   BODY: {item['body_ratio']:.2f}",
                f"   WHY: {reasons}",
                "",
            ]
        )

    telegram(
        "\n".join(lines)
    )


# ============================================================
# MAIN
# ============================================================

def main():

    telegram(
        "\n".join(
            [
                f"⚡ ATI CRYPTO BOT {VERSION}",
                "",
                "📡 TABDEAL API: CONNECTING...",
                "📊 AUTH + 5M SCANNER",
                "",
                "🔐 DIRECT REST API",
                "🔐 HMAC-SHA256",
                "🔢 SERVER TIMESTAMP",
                "🔢 RECVWINDOW: 5000",
                "",
                "🕯 CLOSED CANDLE: YES",
                "📊 5M SCANNER: ENABLED",
                "🎯 TOP 10: ENABLED",
                "",
                "🔒 REAL ORDERS: DISABLED",
                "🛑 BUY LOCK: ACTIVE",
                "",
                datetime.now(
                    timezone.utc
                ).strftime(
                    "🕐 %Y-%m-%d %H:%M:%S UTC"
                ),
            ]
        )
    )

    if not API_KEY or not API_SECRET:

        telegram(
            "🚨 API KEY / SECRET NOT FOUND"
        )

        return

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    try:

        auth_test()

    except Exception as exc:

        telegram(
            "\n".join(
                [
                    "🚨 ATI API AUTH FAILED",
                    "",
                    f"❌ {exc}",
                    "",
                    f"🔑 SELECTED PAIR: {WORKING_PAIR}",
                    "",
                    "🛑 SCANNER STOPPED",
                    "🛑 NO ORDER WAS SENT",
                ]
            )
        )

        return

    # --------------------------------------------------------
    # EXCHANGE INFO
    # --------------------------------------------------------

    try:

        raw = get_exchange_info()

        markets = get_usdt_markets(
            raw
        )

    except Exception as exc:

        telegram(
            "\n".join(
                [
                    "🚨 EXCHANGE INFO ERROR",
                    "",
                    f"❌ {exc}",
                    "",
                    "🛑 NO ORDER WAS SENT",
                ]
            )
        )

        return

    if not markets:

        telegram(
            "🚨 NO USDT MARKETS FOUND"
        )

        return

    telegram(
        "\n".join(
            [
                f"📊 EXCHANGE INFO OK {VERSION}",
                "",
                f"🟢 USDT MARKETS: {len(markets)}",
                "",
                "➡️ STARTING 5M SCAN...",
            ]
        )
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    top, elapsed, all_results = scan_markets(
        markets
    )

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    send_scan_result(
        top,
        elapsed,
        len(all_results),
    )

    telegram(
        "\n".join(
            [
                "",
                f"✅ ATI {VERSION} SCAN COMPLETE",
                "",
                f"📊 MARKETS: {len(markets)}",
                f"🔎 CHECKED: {len(all_results)}",
                f"🎯 QUALIFIED: {len(top)}",
                "",
                "🔒 REAL ORDERS: DISABLED",
                "🛑 NO ORDER WAS SENT",
            ]
        )
    )


if __name__ == "__main__":
    main()
