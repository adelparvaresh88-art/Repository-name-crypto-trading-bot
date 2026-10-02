import os
import time
import hmac
import hashlib
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# ATI CRYPTO BOT V40.2.35
# SMART 5M CANDIDATE SCANNER
#
# LOGIC:
# - CLOSED 5M CANDLES ONLY
# - STRONG BREAKOUT
# - EARLY BREAKOUT WATCH
# - MOMENTUM
# - VOLUME AS SCORE, NOT HARD FILTER
# - BODY AS SCORE, NOT HARD FILTER
# - ANTI-CHASE
# - REAL ORDERS DISABLED
# ============================================================

VERSION = "V40.2.35"

BASE_URL = "https://api1.tabdeal.org"

RECV_WINDOW = 5000
REQUEST_TIMEOUT = 20
TRADE_LIMIT = 1000

# More markets than previous 20 so the scanner has
# a better chance of finding active candidates.
SCAN_UNIVERSE = 40
TOP_RESULTS = 10

LOOKBACK = 12
MIN_CANDLES = 30

# Maximum distance above resistance.
MAX_CHASE_PCT = 1.50

# Candidate thresholds
STRONG_SCORE = 14
EARLY_SCORE = 10
WATCH_SCORE = 7

REAL_ORDERS = False
BUY_LOCK = True

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-Crypto-Bot/40.2.35"
})

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# TELEGRAM
# ============================================================

def log_time():
    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def notify(message):

    print(message, flush=True)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:

        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message[:4000],
                "disable_web_page_preview": True,
            },
            timeout=15,
        )

        if not response.ok:
            print(
                f"TELEGRAM ERROR "
                f"{response.status_code}: "
                f"{response.text[:300]}",
                flush=True,
            )

    except Exception as exc:
        print(
            f"TELEGRAM ERROR: {exc}",
            flush=True
        )


# ============================================================
# PUBLIC API
# ============================================================

def api_get(path, params=None):

    response = session.get(
        BASE_URL + path,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    if not response.ok:
        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    return response.json()


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():

    data = api_get(
        "/r/api/v1/time"
    )

    if isinstance(data, dict):

        for key in (
            "serverTime",
            "server_time",
            "time",
            "timestamp",
        ):

            if key in data:

                value = int(data[key])

                if value < 10**12:
                    value *= 1000

                return value

        nested = data.get("data")

        if isinstance(nested, dict):

            for key in (
                "serverTime",
                "server_time",
                "time",
                "timestamp",
            ):

                if key in nested:

                    value = int(nested[key])

                    if value < 10**12:
                        value *= 1000

                    return value

    raise RuntimeError(
        f"Cannot parse server time: "
        f"{str(data)[:300]}"
    )


# ============================================================
# CREDENTIALS
# ============================================================

def get_credentials():

    # TABDIL = verified working pair.
    pairs = [
        (
            "TABDIL",
            os.getenv(
                "TABDIL_API_KEY",
                ""
            ).strip(),
            os.getenv(
                "TABDIL_API_SECRET",
                ""
            ).strip(),
        ),
        (
            "TABDEAL",
            os.getenv(
                "TABDEAL_API_KEY",
                ""
            ).strip(),
            os.getenv(
                "TABDEAL_API_SECRET",
                ""
            ).strip(),
        ),
    ]

    for name, key, secret in pairs:

        if key and secret:
            return name, key, secret

    raise RuntimeError(
        "API credentials missing."
    )


# ============================================================
# SIGNED API
# ============================================================

def signed_get(
    path,
    api_key,
    api_secret
):

    timestamp = get_server_time()

    query = (
        f"timestamp={timestamp}"
        f"&recvWindow={RECV_WINDOW}"
    )

    signature = hmac.new(
        api_secret.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    params = {
        "timestamp": timestamp,
        "recvWindow": RECV_WINDOW,
        "signature": signature,
    }

    response = session.get(
        BASE_URL + path,
        params=params,
        headers={
            "X-MBX-APIKEY": api_key
        },
        timeout=REQUEST_TIMEOUT,
    )

    if not response.ok:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    return response.json()


# ============================================================
# AUTH
# ============================================================

def authenticate():

    name, key, secret = get_credentials()

    notify(
        f"🔐 ATI AUTH TEST {VERSION}\n"
        f"🔑 KEY PAIR: {name}\n"
        f"🔐 HMAC-SHA256\n"
        f"🔢 SERVER TIMESTAMP\n"
        f"🔒 REAL BUY: DISABLED\n"
        f"🕐 {log_time()}"
    )

    data = signed_get(
        "/r/api/v1/account",
        key,
        secret,
    )

    if isinstance(data, dict):

        code = data.get("code")

        if code not in (
            None,
            0,
            "0",
            200,
            "200",
        ):

            raise RuntimeError(
                f"Account API rejected: {data}"
            )

    notify(
        f"✅ ATI API AUTH SUCCESS {VERSION}\n"
        f"🟢 WORKING PAIR: {name}\n"
        f"📡 ACCOUNT API: OK\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🕐 {log_time()}"
    )


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_symbols():

    data = api_get(
        "/r/api/v1/exchangeInfo"
    )

    if isinstance(data, list):

        symbols = data

    elif isinstance(data, dict):

        symbols = data.get(
            "symbols"
        )

        if not isinstance(
            symbols,
            list
        ):

            symbols = data.get(
                "data"
            )

        if isinstance(
            symbols,
            dict
        ):

            symbols = symbols.get(
                "symbols",
                []
            )

    else:

        symbols = []

    if not isinstance(
        symbols,
        list
    ) or not symbols:

        raise RuntimeError(
            "Cannot parse exchangeInfo"
        )

    result = []
    seen = set()

    for item in symbols:

        if not isinstance(
            item,
            dict
        ):
            continue

        symbol = (
            item.get("symbol")
            or item.get("tabdealSymbol")
            or item.get("s")
        )

        if not symbol:
            continue

        normalized = (
            str(symbol)
            .upper()
            .replace("/", "")
            .replace("-", "")
            .replace("_", "")
        )

        if not normalized.endswith(
            "USDT"
        ):
            continue

        if normalized.startswith(
            "USDT"
        ):
            continue

        quote = (
            item.get("quoteAsset")
            or item.get("quoteCurrency")
        )

        if quote and str(
            quote
        ).upper() != "USDT":

            continue

        status = str(
            item.get("status", "")
        ).upper()

        if status and status not in (
            "TRADING",
            "ENABLED",
            "ACTIVE",
        ):

            continue

        if normalized in seen:
            continue

        seen.add(normalized)

        result.append(
            (
                str(symbol),
                normalized
            )
        )

    return result


# ============================================================
# TRADE PARSER
# ============================================================

def number(
    value,
    default=0.0
):

    try:
        return float(value)

    except (
        TypeError,
        ValueError
    ):

        return default


def parse_trade(item):

    if not isinstance(
        item,
        dict
    ):
        return None

    price = number(
        item.get(
            "price",
            item.get(
                "p",
                item.get("rate")
            )
        )
    )

    qty = number(
        item.get(
            "qty",
            item.get(
                "quantity",
                item.get(
                    "q",
                    item.get("amount")
                )
            )
        )
    )

    stamp = item.get(
        "time",
        item.get(
            "timestamp",
            item.get(
                "T",
                item.get("createdAt")
            )
        )
    )

    try:

        stamp = int(
            float(stamp)
        )

    except (
        TypeError,
        ValueError
    ):

        return None

    if stamp < 10**12:
        stamp *= 1000

    if price <= 0 or qty <= 0:
        return None

    return (
        stamp,
        price,
        qty
    )


# ============================================================
# TRADE RESPONSE
# ============================================================

def extract_trade_list(data):

    if isinstance(
        data,
        list
    ):
        return data

    if not isinstance(
        data,
        dict
    ):
        return []

    candidates = [
        data.get("data"),
        data.get("trades"),
        data.get("result"),
        data.get("items"),
    ]

    for value in candidates:

        if isinstance(
            value,
            list
        ):
            return value

        if isinstance(
            value,
            dict
        ):

            for key in (
                "trades",
                "items",
                "data",
                "result",
            ):

                nested = value.get(
                    key
                )

                if isinstance(
                    nested,
                    list
                ):

                    return nested

    return []


def get_recent_trades(
    original_symbol
):

    attempts = [
        {
            "tabdealSymbol": original_symbol,
            "limit": TRADE_LIMIT,
        },
        {
            "symbol": original_symbol,
            "limit": TRADE_LIMIT,
        },
        {
            "market": original_symbol,
            "limit": TRADE_LIMIT,
        },
        {
            "tabdeal_symbol": original_symbol,
            "limit": TRADE_LIMIT,
        },
    ]

    errors = []

    for params in attempts:

        try:

            response = session.get(
                BASE_URL
                + "/r/api/v1/trades",
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if not response.ok:

                errors.append(
                    f"HTTP "
                    f"{response.status_code}"
                )

                continue

            try:

                data = response.json()

            except ValueError:

                errors.append(
                    "INVALID_JSON"
                )

                continue

            trades = extract_trade_list(
                data
            )

            if trades:

                return trades

            errors.append(
                "EMPTY_RESPONSE"
            )

        except Exception as exc:

            errors.append(
                str(exc)[:150]
            )

    raise RuntimeError(
        "TRADES_API_FAILED: "
        + " | ".join(errors)
    )


# ============================================================
# 5M CANDLES
# ============================================================

def get_candles(
    original_symbol
):

    trades = get_recent_trades(
        original_symbol
    )

    buckets = {}

    for raw in trades:

        parsed = parse_trade(
            raw
        )

        if not parsed:
            continue

        stamp, price, qty = parsed

        bucket = (
            stamp // 300000
        ) * 300000

        candle = buckets.get(
            bucket
        )

        if candle is None:

            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
            }

        else:

            candle["high"] = max(
                candle["high"],
                price
            )

            candle["low"] = min(
                candle["low"],
                price
            )

            candle["close"] = price
            candle["volume"] += qty

    candles = [
        buckets[key]
        for key in sorted(
            buckets
        )
    ]

    # Remove current OPEN candle.
    current_bucket = (
        int(time.time() * 1000)
        // 300000
    ) * 300000

    candles = [
        c for c in candles
        if c["time"] < current_bucket
    ]

    return candles


# ============================================================
# MATH
# ============================================================

def pct_change(
    current,
    previous
):

    if not previous:
        return 0.0

    return (
        (current / previous) - 1
    ) * 100.0


# ============================================================
# SMART LOGIC
# ============================================================

def analyze_market(
    symbol,
    candles
):

    if len(candles) < MIN_CANDLES:

        return {
            "symbol": symbol,
            "status": "NO_DATA",
            "score": 0,
            "reason": "NOT_ENOUGH_CANDLES",
            "candles": len(candles),
        }

    last = candles[-1]
    previous = candles[:-1]

    reference = previous[
        -LOOKBACK:
    ]

    resistance = max(
        c["high"]
        for c in reference
    )

    close = last["close"]
    open_price = last["open"]
    high = last["high"]
    low = last["low"]

    candle_range = (
        high - low
    )

    body_ratio = (
        abs(
            close - open_price
        ) / candle_range
        if candle_range > 0
        else 0.0
    )

    breakout_pct = pct_change(
        close,
        resistance
    )

    # Momentum
    mom_5m = pct_change(
        close,
        candles[-2]["close"]
    )

    mom_15m = pct_change(
        close,
        candles[-4]["close"]
    )

    mom_1h = pct_change(
        close,
        candles[-13]["close"]
    )

    # Volume
    volumes = [
        c["volume"]
        for c in previous[-6:]
    ]

    avg_volume = (
        sum(volumes)
        / len(volumes)
        if volumes
        else 0.0
    )

    volume_ratio = (
        last["volume"]
        / avg_volume
        if avg_volume > 0
        else 0.0
    )

    bullish = (
        close > open_price
    )

    above_resistance = (
        close > resistance
    )

    near_resistance = (
        breakout_pct >= -0.50
    )

    strong_volume = (
        volume_ratio >= 1.50
    )

    decent_volume = (
        volume_ratio >= 0.70
    )

    strong_body = (
        body_ratio >= 0.60
    )

    decent_body = (
        body_ratio >= 0.30
    )

    positive_5m = (
        mom_5m > 0
    )

    positive_15m = (
        mom_15m > 0
    )

    positive_1h = (
        mom_1h > 0
    )

    not_chasing = (
        breakout_pct <= MAX_CHASE_PCT
    )

    # ========================================================
    # SCORE
    #
    # Maximum = 20
    # ========================================================

    score = 0

    # 5m momentum
    if mom_5m > 0:
        score += 2

    if mom_5m >= 0.30:
        score += 1

    # 15m momentum
    if positive_15m:
        score += 3

    if mom_15m >= 1.00:
        score += 1

    # 1h trend
    if positive_1h:
        score += 2

    if mom_1h >= 2.00:
        score += 1

    # Resistance
    if above_resistance:
        score += 4

    elif near_resistance:
        score += 2

    # Volume
    if strong_volume:
        score += 2

    elif decent_volume:
        score += 1

    # Candle body
    if strong_body:
        score += 2

    elif decent_body:
        score += 1

    # ========================================================
    # PENALTIES
    # ========================================================

    if not bullish:
        score -= 1

    if mom_15m < -0.50:
        score -= 2

    if mom_1h < -1.00:
        score -= 2

    if breakout_pct > MAX_CHASE_PCT:
        score -= 3

    score = max(
        0,
        min(score, 20)
    )

    # ========================================================
    # CLASSIFICATION
    # ========================================================

    # STRONG:
    # Actual breakout + momentum + acceptable chase.
    strong = (
        above_resistance
        and positive_5m
        and positive_15m
        and positive_1h
        and not_chasing
        and score >= STRONG_SCORE
    )

    # EARLY:
    # Close to breakout, momentum already positive.
    early = (
        not strong
        and near_resistance
        and positive_5m
        and positive_15m
        and positive_1h
        and not_chasing
        and score >= EARLY_SCORE
    )

    # WATCH:
    # Good directional setup but not ready.
    watch = (
        not strong
        and not early
        and score >= WATCH_SCORE
        and positive_15m
        and positive_1h
        and not_chasing
    )

    if strong:
        status = "STRONG"

    elif early:
        status = "EARLY WATCH"

    elif watch:
        status = "WATCH"

    else:
        status = "FILTERED"

    reasons = []

    if not bullish:
        reasons.append(
            "RED_CANDLE"
        )

    if not above_resistance:
        if near_resistance:
            reasons.append(
                "NEAR_RESISTANCE"
            )
        else:
            reasons.append(
                "BELOW_RESISTANCE"
            )

    if volume_ratio < 0.70:
        reasons.append(
            "LOW_VOLUME"
        )

    if body_ratio < 0.30:
        reasons.append(
            "WEAK_BODY"
        )

    if mom_5m <= 0:
        reasons.append(
            "5M_NOT_UP"
        )

    if mom_15m <= 0:
        reasons.append(
            "15M_NOT_UP"
        )

    if mom_1h <= 0:
        reasons.append(
            "1H_NOT_UP"
        )

    if breakout_pct > MAX_CHASE_PCT:
        reasons.append(
            "CHASE"
        )

    return {
        "symbol": symbol,
        "status": status,
        "score": score,
        "price": close,
        "breakout": breakout_pct,
        "volume": volume_ratio,
        "body": body_ratio * 100,
        "mom5": mom_5m,
        "mom15": mom_15m,
        "mom1h": mom_1h,
        "reasons": reasons,
        "candles": len(candles),
    }


# ============================================================
# SCAN ONE
# ============================================================

def scan_one(pair):

    original, normalized = pair

    try:

        candles = get_candles(
            original
        )

        result = analyze_market(
            normalized,
            candles
        )

        result["original"] = original

        return result

    except Exception as exc:

        return {
            "symbol": normalized,
            "status": "API ERROR",
            "score": -1,
            "error": str(exc)[:500],
        }


# ============================================================
# FORMAT
# ============================================================

def format_candidate(
    item,
    rank
):

    reasons = ", ".join(
        item.get(
            "reasons",
            []
        )
    )

    if not reasons:
        reasons = "NONE"

    return (
        f"{rank}. "
        f"{item['symbol']} "
        f"🟢 {item['status']}\n"
        f"Score: {item['score']}/20\n"
        f"Price: {item['price']:.8g}\n"
        f"Breakout: "
        f"{item['breakout']:+.2f}%\n"
        f"Volume: "
        f"{item['volume']:.2f}x\n"
        f"Body: "
        f"{item['body']:.0f}%\n"
        f"5m: "
        f"{item['mom5']:+.2f}% | "
        f"15m: "
        f"{item['mom15']:+.2f}% | "
        f"1h: "
        f"{item['mom1h']:+.2f}%\n"
        f"State: {reasons}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    start = time.time()

    notify(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"🧠 SMART 5M LOGIC\n"
        f"🕯 CLOSED CANDLE ONLY\n"
        f"🔎 SCAN UNIVERSE: {SCAN_UNIVERSE}\n"
        f"🎯 TOP {TOP_RESULTS}\n\n"
        f"🟢 STRONG BREAKOUT\n"
        f"🟡 EARLY WATCH\n"
        f"⚪ WATCH\n\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🛑 BUY LOCK: ACTIVE\n"
        f"🕐 {log_time()}"
    )

    authenticate()

    pairs = get_exchange_symbols()

    notify(
        f"📊 EXCHANGE INFO OK {VERSION}\n"
        f"🟢 USDT MARKETS: {len(pairs)}\n"
        f"🔎 SMART SCAN STARTING...\n"
        f"🔒 REAL ORDERS: DISABLED"
    )

    selected = pairs[
        :SCAN_UNIVERSE
    ]

    results = []

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = {
            executor.submit(
                scan_one,
                pair
            ): pair
            for pair in selected
        }

        for future in as_completed(
            futures
        ):

            results.append(
                future.result()
            )

    elapsed = (
        time.time() - start
    )

    valid_results = [
        x for x in results
        if x.get("score", -1) >= 0
        and "price" in x
    ]

    strong = [
        x for x in valid_results
        if x["status"] == "STRONG"
    ]

    early = [
        x for x in valid_results
        if x["status"] == "EARLY WATCH"
    ]

    watch = [
        x for x in valid_results
        if x["status"] == "WATCH"
    ]

    candidates = [
        x for x in valid_results
        if x["status"] != "FILTERED"
    ]

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["mom15"],
            x["mom1h"],
        ),
        reverse=True,
    )

    top = candidates[
        :TOP_RESULTS
    ]

    notify(
        f"📊 SMART SCAN RESULT {VERSION}\n\n"
        f"🟢 MARKETS: {len(pairs)}\n"
        f"🔎 CHECKED: {len(selected)}\n"
        f"📈 ANALYZED: "
        f"{len(valid_results)}\n"
        f"🟢 STRONG: {len(strong)}\n"
        f"🟡 EARLY: {len(early)}\n"
        f"⚪ WATCH: {len(watch)}\n"
        f"❌ FILTERED: "
        f"{len(valid_results) - len(candidates)}\n"
        f"⏱ TIME: {elapsed:.1f}s\n\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🛑 NO ORDER WAS SENT\n"
        f"🕐 {log_time()}"
    )

    if top:

        message = (
            f"🎯 ATI SMART TOP {len(top)} "
            f"{VERSION}\n\n"
        )

        for index, item in enumerate(
            top,
            1
        ):

            message += (
                format_candidate(
                    item,
                    index
                )
                + "\n\n"
            )

        message += (
            "🔒 REAL BUY: DISABLED\n"
            "🛑 SCANNER ONLY"
        )

        notify(message)

    else:

        notify(
            f"⚪ ATI {VERSION}\n\n"
            f"NO EARLY/STRONG CANDIDATE\n"
            f"FOUND IN THIS SCAN.\n\n"
            f"🔒 REAL ORDERS: DISABLED\n"
            f"🛑 NO ORDER WAS SENT"
        )

    notify(
        f"✅ ATI {VERSION} COMPLETE\n"
        f"📊 CHECKED: {len(selected)}\n"
        f"🟢 STRONG: {len(strong)}\n"
        f"🟡 EARLY: {len(early)}\n"
        f"⚪ WATCH: {len(watch)}\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🛑 NO ORDER WAS SENT\n"
        f"🕐 {log_time()}"
    )


if __name__ == "__main__":

    try:
        main()

    except Exception as exc:

        notify(
            f"🚨 ATI BOT ERROR {VERSION}\n"
            f"❌ {type(exc).__name__}: "
            f"{str(exc)[:1000]}\n"
            f"🔒 REAL ORDERS: DISABLED\n"
            f"🕐 {log_time()}"
        )

        raise
