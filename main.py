import os
import time
import json
import hmac
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.31
# TABDEAL SPOT
# 5M CLOSED-CANDLE MARKET SCANNER
# TOP 10 MOMENTUM / BREAKOUT
# ============================================================
#
# IMPORTANT:
# - REAL ORDERS ARE COMPLETELY DISABLED
# - NO ORDER ENDPOINT IS CALLED
# - CLOSED 5M CANDLES ONLY
# - DIRECT REST API
# - HMAC-SHA256
# - TABDIL/TABDEAL API KEY COMPATIBILITY
#
# ============================================================

VERSION = "V40.2.31"

BASE_URL = "https://api1.tabdeal.org"

RECV_WINDOW = int(os.getenv("RECV_WINDOW", "5000"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

# ------------------------------------------------------------
# SCANNER SETTINGS
# ------------------------------------------------------------

TRADE_LIMIT = 1000

# Number of markets actually inspected.
SCAN_UNIVERSE = 20

# Number displayed in Telegram.
TOP_RESULTS = 10

TIMEFRAME_MINUTES = 5

# Resistance lookback.
BREAKOUT_LOOKBACK = 12

# Minimum candles required.
MIN_CANDLES = 30

# Maximum acceptable chase above breakout.
MAX_CHASE_PCT = 1.50

# Minimum volume expansion.
MIN_VOLUME_RATIO = 1.10

# ------------------------------------------------------------
# HARD SAFETY LOCK
# ------------------------------------------------------------

LIVE_TRADING = False
REAL_ORDERS = False
BUY_LOCK = True


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as exc:
        print("TELEGRAM ERROR:", exc)

    print(message)


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot-V40.2.31",
        "Accept": "application/json",
    }
)


# ============================================================
# CREDENTIALS
# ============================================================

def get_credentials():
    pairs = [
        (
            os.getenv("TABDEAL_API_KEY", "").strip(),
            os.getenv("TABDEAL_API_SECRET", "").strip(),
            "TABDEAL",
        ),
        (
            os.getenv("TABDIL_API_KEY", "").strip(),
            os.getenv("TABDIL_API_SECRET", "").strip(),
            "TABDIL",
        ),
    ]

    for api_key, api_secret, name in pairs:
        if api_key and api_secret:
            return api_key, api_secret, name

    return "", "", "NONE"


API_KEY, API_SECRET, WORKING_PAIR = get_credentials()


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():
    url = f"{BASE_URL}/r/api/v1/time"

    response = SESSION.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):
        value = data.get("serverTime")

        if value is not None:
            return int(value)

    raise RuntimeError(f"Invalid server time response: {data}")


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_get(path, params=None):
    if params is None:
        params = {}

    server_time = get_server_time()

    params = dict(params)

    params["timestamp"] = server_time
    params["recvWindow"] = RECV_WINDOW

    query_string = "&".join(
        f"{key}={params[key]}"
        for key in params
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    params["signature"] = signature

    url = f"{BASE_URL}{path}"

    headers = {
        "X-MBX-APIKEY": API_KEY,
    }

    response = SESSION.get(
        url,
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )

    return response


# ============================================================
# AUTH TEST
# ============================================================

def auth_test():

    if not API_KEY or not API_SECRET:
        raise RuntimeError("API KEY / SECRET NOT FOUND")

    local_ms = int(time.time() * 1000)

    server_ms = get_server_time()

    diff = local_ms - server_ms

    telegram(
        "\n".join(
            [
                f"🕐 TABDEAL TIME CHECK {VERSION}",
                "",
                f"LOCAL: {local_ms}",
                f"SERVER: {server_ms}",
                f"DIFF: {diff} ms",
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

        if code not in (None, 0, "0"):
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

    url = f"{BASE_URL}/r/api/v1/exchangeInfo"

    response = SESSION.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# EXCHANGE INFO PARSER
# ============================================================

def extract_symbols(raw):

    if isinstance(raw, list):
        return raw

    if isinstance(raw, dict):

        if isinstance(raw.get("symbols"), list):
            return raw["symbols"]

        data = raw.get("data")

        if isinstance(data, list):
            return data

        if isinstance(data, dict):

            if isinstance(data.get("symbols"), list):
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
            item.get("status", "TRADING")
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

    # remove duplicates
    markets = list(dict.fromkeys(markets))

    return markets


# ============================================================
# RECENT TRADES
# ============================================================

def get_recent_trades(symbol):

    url = f"{BASE_URL}/r/api/v1/trades"

    params = {
        "tabdealSymbol": symbol,
        "limit": TRADE_LIMIT,
    }

    response = SESSION.get(
        url,
        params=params,
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


def trade_value(trade, *keys):

    if not isinstance(trade, dict):
        return None

    for key in keys:

        if key in trade:
            return trade[key]

    return None


def parse_trade(trade):

    price = trade_value(
        trade,
        "price",
        "p",
    )

    qty = trade_value(
        trade,
        "qty",
        "quantity",
        "q",
    )

    timestamp = trade_value(
        trade,
        "time",
        "timestamp",
        "T",
    )

    if price is None or qty is None or timestamp is None:
        return None

    try:

        price = float(price)
        qty = float(qty)
        timestamp = int(float(timestamp))

        if timestamp < 10_000_000_000:
            timestamp *= 1000

        if price <= 0 or qty <= 0:
            return None

        return {
            "price": price,
            "qty": qty,
            "time": timestamp,
        }

    except Exception:
        return None


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_5m_candles(raw):

    trades = extract_trade_list(raw)

    parsed = []

    for trade in trades:

        item = parse_trade(trade)

        if item:
            parsed.append(item)

    if not parsed:
        return []

    parsed.sort(
        key=lambda x: x["time"]
    )

    buckets = {}

    bucket_ms = TIMEFRAME_MINUTES * 60 * 1000

    for trade in parsed:

        bucket = (
            trade["time"] // bucket_ms
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
    # REMOVE CURRENT OPEN CANDLE
    # --------------------------------------------------------

    now_ms = int(time.time() * 1000)

    current_bucket = (
        now_ms // bucket_ms
    ) * bucket_ms

    closed = [
        candle
        for candle in candles
        if candle["time"] < current_bucket
    ]

    return closed


# ============================================================
# INDICATOR HELPERS
# ============================================================

def average(values):

    if not values:
        return 0.0

    return sum(values) / len(values)


def candle_body(candle):

    return abs(
        candle["close"] - candle["open"]
    )


def candle_range(candle):

    return max(
        candle["high"] - candle["low"],
        1e-12,
    )


def body_ratio(candle):

    return (
        candle_body(candle)
        / candle_range(candle)
    )


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_market(symbol):

    try:

        raw = get_recent_trades(symbol)

        candles = build_5m_candles(raw)

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
            / max(average_volume, 1e-12)
        )

        close = last["close"]

        breakout_pct = (
            (close - resistance)
            / resistance
            * 100
        )

        body_pct = body_ratio(last)

        bullish = (
            last["close"]
            > last["open"]
        )

        # ----------------------------------------------------
        # SHORT MOMENTUM
        # ----------------------------------------------------

        close_3 = candles[-4]["close"]

        momentum_15m = (
            (close - close_3)
            / close_3
            * 100
        )

        close_12 = candles[-13]["close"]

        momentum_1h = (
            (close - close_12)
            / close_12
            * 100
        )

        # ----------------------------------------------------
        # CHASE PROTECTION
        # ----------------------------------------------------

        chase_pct = max(
            0.0,
            breakout_pct,
        )

        # ----------------------------------------------------
        # SCORE
        # ----------------------------------------------------

        score = 0

        reasons = []

        # Breakout
        if breakout_pct > 0:
            score += 5
            reasons.append("BREAKOUT")

        # Strong candle
        if bullish and body_pct >= 0.55:
            score += 3
            reasons.append("STRONG_CANDLE")

        # Volume
        if volume_ratio >= MIN_VOLUME_RATIO:
            score += 4
            reasons.append("VOLUME")

        # 15m momentum
        if momentum_15m > 0.20:
            score += 2
            reasons.append("15M_UP")

        # 1h momentum
        if momentum_1h > 0.30:
            score += 3
            reasons.append("1H_UP")

        # Close above resistance
        if close > resistance:
            score += 2
            reasons.append("CLOSE_ABOVE_RESISTANCE")

        # ----------------------------------------------------
        # HARD FILTERS
        # ----------------------------------------------------

        valid = True

        if not bullish:
            valid = False

        if close <= resistance:
            valid = False

        if volume_ratio < MIN_VOLUME_RATIO:
            valid = False

        if body_pct < 0.40:
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
            "body_ratio": body_pct,
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
# SCAN
# ============================================================

def scan_markets(markets):

    # --------------------------------------------------------
    # First pass:
    # inspect a limited universe to keep GitHub fast.
    # --------------------------------------------------------

    candidates = markets[:SCAN_UNIVERSE]

    results = []

    telegram(
        "\n".join(
            [
                f"📊 ATI 5M SCANNER {VERSION}",
                "",
                f"🟢 USDT MARKETS: {len(markets)}",
                f"🔎 SCAN UNIVERSE: {len(candidates)}",
                f"🎯 TOP RESULTS: {TOP_RESULTS}",
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

                result = future.result()

                results.append(result)

            except Exception as exc:

                results.append(
                    {
                        "symbol": symbol,
                        "valid": False,
                        "reason": str(exc),
                    }
                )

    elapsed = time.time() - start

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

    return valid[:TOP_RESULTS], elapsed, results


# ============================================================
# TELEGRAM RESULT
# ============================================================

def send_scan_result(top, elapsed, total_results):

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
                "فقط کندل بسته‌شده بررسی شد.",
                "سیگنال ضعیف حذف شد.",
                "فعلاً خرید انجام نمی‌شود.",
            ]
        )

        telegram(
            "\n".join(lines)
        )

        return

    lines.append(
        "🏆 TOP 10 CANDIDATES"
    )
    lines.append("")

    for index, item in enumerate(
        top,
        start=1,
    ):

        reasons = ",".join(
            item.get("reasons", [])
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

    startup = "\n".join(
        [
            f"⚡ ATI CRYPTO BOT {VERSION}",
            "",
            "📡 TABDEAL API: CONNECTING...",
            "📊 AUTH + 5M SCANNER",
            "",
            "🔐 DIRECT REST API",
            "🔐 HMAC-SHA256",
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

    telegram(startup)

    # --------------------------------------------------------
    # Credentials
    # --------------------------------------------------------

    if not API_KEY or not API_SECRET:

        telegram(
            "\n".join(
                [
                    "🚨 ATI CONFIG ERROR",
                    "",
                    "❌ API KEY / SECRET NOT FOUND",
                    "",
                    "Checked:",
                    "TABDEAL_API_KEY",
                    "TABDEAL_API_SECRET",
                    "TABDIL_API_KEY",
                    "TABDIL_API_SECRET",
                ]
            )
        )

        return

    # --------------------------------------------------------
    # Authentication
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
                    "🛑 SCANNER STOPPED",
                    "🛑 NO ORDER WAS SENT",
                ]
            )
        )

        return

    # --------------------------------------------------------
    # Exchange info
    # --------------------------------------------------------

    try:

        raw_exchange = get_exchange_info()

        markets = get_usdt_markets(
            raw_exchange
        )

    except Exception as exc:

        telegram(
            "\n".join(
                [
                    "🚨 EXCHANGE INFO ERROR",
                    "",
                    f"❌ {exc}",
                    "",
                    "🛑 SCANNER STOPPED",
                    "🛑 NO ORDER WAS SENT",
                ]
            )
        )

        return

    if not markets:

        telegram(
            "\n".join(
                [
                    "🚨 NO USDT MARKETS",
                    "",
                    "❌ exchangeInfo parser returned 0 markets",
                    "",
                    "🛑 NO ORDER WAS SENT",
                ]
            )
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
    # Scanner
    # --------------------------------------------------------

    top, elapsed, all_results = scan_markets(
        markets
    )

    # --------------------------------------------------------
    # Final result
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
