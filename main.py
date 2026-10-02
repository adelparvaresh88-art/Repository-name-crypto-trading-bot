import os
import time
import hmac
import hashlib
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# ATI CRYPTO BOT V40.2.33
# DIAGNOSTIC SCANNER - NO REAL ORDERS
# ============================================================

VERSION = "V40.2.33"
BASE_URL = "https://api1.tabdeal.org"
TIMEOUT = 20
RECV_WINDOW = 5000
SCAN_UNIVERSE = 20
TOP_RESULTS = 10
TRADE_LIMIT = 1000
LOOKBACK = 12
MIN_CANDLES = 30
MAX_CHASE_PCT = 1.50
MIN_VOLUME_RATIO = 1.10
MIN_SCORE = 12

REAL_ORDERS = False
BUY_LOCK = True

session = requests.Session()
session.headers.update({"User-Agent": "ATI-Crypto-Bot/40.2.33"})

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def log_time():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def notify(message):
    print(message, flush=True)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM CONFIG MISSING", flush=True)
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message[:4000],
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if not response.ok:
            print(
                f"TELEGRAM ERROR {response.status_code}: "
                f"{response.text[:300]}",
                flush=True,
            )
    except Exception as exc:
        print(f"TELEGRAM ERROR: {exc}", flush=True)


def api_get(path, params=None):
    response = session.get(
        BASE_URL + path,
        params=params or {},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def get_server_time():
    data = api_get("/r/api/v1/time")

    if isinstance(data, dict):
        for key in ("serverTime", "server_time", "time", "timestamp"):
            if key in data:
                value = int(data[key])
                return value * 1000 if value < 10**12 else value

        nested = data.get("data")
        if isinstance(nested, dict):
            for key in ("serverTime", "server_time", "time", "timestamp"):
                if key in nested:
                    value = int(nested[key])
                    return value * 1000 if value < 10**12 else value

    raise RuntimeError(f"Cannot parse server time: {str(data)[:300]}")


def get_credentials():
    pairs = [
        (
            "TABDIL",
            os.getenv("TABDIL_API_KEY", "").strip(),
            os.getenv("TABDIL_API_SECRET", "").strip(),
        ),
        (
            "TABDEAL",
            os.getenv("TABDEAL_API_KEY", "").strip(),
            os.getenv("TABDEAL_API_SECRET", "").strip(),
        ),
    ]

    for name, key, secret in pairs:
        if key and secret:
            return name, key, secret

    raise RuntimeError(
        "API credentials missing. Check TABDIL_API_KEY and "
        "TABDIL_API_SECRET GitHub Secrets."
    )


def signed_get(path, api_key, api_secret):
    timestamp = get_server_time()
    query = f"timestamp={timestamp}&recvWindow={RECV_WINDOW}"

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
        headers={"X-MBX-APIKEY": api_key},
        timeout=TIMEOUT,
    )

    if not response.ok:
        raise RuntimeError(
            f"HTTP {response.status_code}: {response.text[:500]}"
        )

    return response.json()


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

    data = signed_get("/r/api/v1/account", key, secret)

    if isinstance(data, dict):
        code = data.get("code")
        if code not in (None, 0, "0", 200, "200"):
            raise RuntimeError(f"Account API rejected: {data}")

    notify(
        f"✅ ATI API AUTH SUCCESS {VERSION}\n"
        f"🟢 WORKING PAIR: {name}\n"
        f"📡 ACCOUNT API: OK\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🕐 {log_time()}"
    )


def get_exchange_symbols():
    data = api_get("/r/api/v1/exchangeInfo")

    if isinstance(data, list):
        symbols = data
    elif isinstance(data, dict):
        symbols = data.get("symbols")
        if not isinstance(symbols, list):
            symbols = data.get("data")
        if isinstance(symbols, dict):
            symbols = symbols.get("symbols", [])
    else:
        symbols = []

    if not isinstance(symbols, list) or not symbols:
        raise RuntimeError(
            f"Cannot parse exchangeInfo: {str(data)[:400]}"
        )

    result = []

    for item in symbols:
        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("tabdealSymbol")
            or item.get("s")
        )
        if not symbol:
            continue

        normalized = str(symbol).upper().replace("/", "").replace("-", "")
        normalized = normalized.replace("_", "")

        quote = item.get("quoteAsset") or item.get("quoteCurrency")
        status = str(item.get("status", "")).upper()

        if normalized.endswith("USDT") and not normalized.startswith("USDT"):
            if quote and str(quote).upper() != "USDT":
                continue
            if status and status not in ("TRADING", "ENABLED", "ACTIVE"):
                continue
            result.append((str(symbol), normalized))

    # Remove duplicates while preserving order.
    seen = set()
    unique = []
    for original, normalized in result:
        if normalized not in seen:
            seen.add(normalized)
            unique.append((original, normalized))

    return unique


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_trade(item):
    if not isinstance(item, dict):
        return None

    price = number(
        item.get("price", item.get("p", item.get("rate")))
    )
    qty = number(
        item.get(
            "qty",
            item.get("quantity", item.get("q", item.get("amount"))),
        )
    )
    stamp = item.get(
        "time",
        item.get("timestamp", item.get("T", item.get("createdAt"))),
    )

    try:
        stamp = int(float(stamp))
    except (TypeError, ValueError):
        return None

    if stamp < 10**12:
        stamp *= 1000

    if price <= 0 or qty <= 0:
        return None

    return stamp, price, qty


def get_candles(original_symbol):
    data = api_get(
        "/r/api/v1/trades",
        params={
            "tabdealSymbol": original_symbol,
            "limit": TRADE_LIMIT,
        },
    )

    if isinstance(data, dict):
        trades = data.get("data")
        if trades is None:
            trades = data.get("trades")
        if trades is None:
            trades = data.get("result")
    else:
        trades = data

    if isinstance(trades, dict):
        trades = trades.get("trades", trades.get("items", []))

    if not isinstance(trades, list):
        return []

    buckets = {}

    for raw in trades:
        parsed = parse_trade(raw)
        if not parsed:
            continue

        stamp, price, qty = parsed
        bucket = (stamp // 300000) * 300000

        candle = buckets.get(bucket)

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
            candle["high"] = max(candle["high"], price)
            candle["low"] = min(candle["low"], price)
            candle["close"] = price
            candle["volume"] += qty

    candles = [buckets[key] for key in sorted(buckets)]

    # Exclude the currently open 5-minute candle.
    current_bucket = (int(time.time() * 1000) // 300000) * 300000
    candles = [c for c in candles if c["time"] < current_bucket]

    return candles


def pct_change(current, previous):
    if not previous:
        return 0.0
    return (current / previous - 1.0) * 100.0


def analyze_market(symbol, candles):
    if len(candles) < MIN_CANDLES:
        return {
            "symbol": symbol,
            "valid": False,
            "score": 0,
            "reason": "NOT_ENOUGH_CANDLES",
            "candles": len(candles),
        }

    last = candles[-1]
    previous = candles[:-1]

    reference = previous[-LOOKBACK:]
    resistance = max(c["high"] for c in reference)

    close = last["close"]
    open_price = last["open"]
    high = last["high"]
    low = last["low"]

    breakout_pct = pct_change(close, resistance)
    candle_range = high - low
    body_ratio = (
        abs(close - open_price) / candle_range
        if candle_range > 0 else 0.0
    )

    recent_volumes = [c["volume"] for c in previous[-6:]]
    avg_volume = (
        sum(recent_volumes) / len(recent_volumes)
        if recent_volumes else 0.0
    )
    volume_ratio = (
        last["volume"] / avg_volume
        if avg_volume > 0 else 0.0
    )

    momentum_5m = pct_change(close, candles[-2]["close"])
    momentum_15m = pct_change(close, candles[-4]["close"])
    momentum_1h = pct_change(close, candles[-13]["close"])

    chase_pct = max(0.0, pct_change(close, resistance))

    bullish = close > open_price
    above_resistance = close > resistance
    strong_body = body_ratio >= 0.40
    volume_ok = volume_ratio >= MIN_VOLUME_RATIO
    momentum_15m_ok = momentum_15m > 0
    chase_ok = chase_pct <= MAX_CHASE_PCT

    score = 0
    if bullish:
        score += 2
    if above_resistance:
        score += 5
    if strong_body:
        score += 3
    if volume_ok:
        score += 4
    if momentum_15m_ok:
        score += 2
    if momentum_1h > 0:
        score += 3
    if above_resistance:
        score += 2
    if momentum_5m > 0:
        score += 1

    reasons = []
    if not bullish:
        reasons.append("NOT_BULLISH")
    if not above_resistance:
        reasons.append("BELOW_RESISTANCE")
    if not volume_ok:
        reasons.append("LOW_VOLUME")
    if not strong_body:
        reasons.append("WEAK_BODY")
    if not momentum_15m_ok:
        reasons.append("15M_NOT_UP")
    if not chase_ok:
        reasons.append("CHASE_TOO_HIGH")
    if score < MIN_SCORE:
        reasons.append("LOW_SCORE")

    valid = (
        bullish
        and above_resistance
        and volume_ok
        and strong_body
        and momentum_15m_ok
        and chase_ok
        and score >= MIN_SCORE
    )

    return {
        "symbol": symbol,
        "valid": valid,
        "score": score,
        "price": close,
        "breakout": breakout_pct,
        "volume_ratio": volume_ratio,
        "body_ratio": body_ratio * 100.0,
        "momentum_5m": momentum_5m,
        "momentum_15m": momentum_15m,
        "momentum_1h": momentum_1h,
        "reasons": reasons,
        "candles": len(candles),
    }


def scan_one(pair):
    original, normalized = pair

    try:
        candles = get_candles(original)
        result = analyze_market(normalized, candles)
        result["original"] = original
        return result
    except Exception as exc:
        return {
            "symbol": normalized,
            "original": original,
            "valid": False,
            "score": -1,
            "reason": f"API_ERROR: {str(exc)[:100]}",
        }


def format_result(item, rank):
    if "price" not in item:
        return (
            f"{rank}. {item['symbol']}\n"
            f"   ⚠️ {item.get('reason', 'NO DATA')}\n"
            f"   Candles: {item.get('candles', 0)}"
        )

    reasons = item.get("reasons", [])
    reason_text = ", ".join(reasons) if reasons else "NONE"

    return (
        f"{rank}. {item['symbol']} | SCORE {item['score']}/22\n"
        f"   Price: {item['price']:.8g}\n"
        f"   Breakout: {item['breakout']:+.3f}%\n"
        f"   Volume Ratio: {item['volume_ratio']:.2f}x\n"
        f"   Body: {item['body_ratio']:.1f}%\n"
        f"   Momentum 5m: {item['momentum_5m']:+.2f}%\n"
        f"   Momentum 15m: {item['momentum_15m']:+.2f}%\n"
        f"   Momentum 1h: {item['momentum_1h']:+.2f}%\n"
        f"   BLOCKED: {reason_text}"
    )


def main():
    start = time.time()

    notify(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 DIAGNOSTIC SCANNER\n"
        f"🕯 CLOSED 5M CANDLE ONLY\n"
        f"🔎 SCAN UNIVERSE: {SCAN_UNIVERSE}\n"
        f"🎯 DIAGNOSTIC TOP {TOP_RESULTS}\n\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🛑 BUY LOCK: ACTIVE\n"
        f"🕐 {log_time()}"
    )

    authenticate()

    pairs = get_exchange_symbols()

    notify(
        f"📊 EXCHANGE INFO OK {VERSION}\n"
        f"🟢 USDT MARKETS: {len(pairs)}\n"
        f"🔎 STARTING DIAGNOSTIC SCAN...\n"
        f"🔒 REAL ORDERS: DISABLED"
    )

    # This is a diagnostic sample, not a volume-ranked universe.
    selected = pairs[:SCAN_UNIVERSE]

    results = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(scan_one, pair): pair
            for pair in selected
        }

        for future in as_completed(futures):
            results.append(future.result())

    elapsed = time.time() - start

    successful = [r for r in results if "price" in r]
    insufficient = sum(
        1 for r in results
        if r.get("reason") == "NOT_ENOUGH_CANDLES"
    )
    errors = sum(
        1 for r in results
        if str(r.get("reason", "")).startswith("API_ERROR")
    )
    qualified = [r for r in successful if r["valid"]]

    # Show the highest scores, including blocked candidates.
    ranked = sorted(
        successful,
        key=lambda x: (x["score"], x["momentum_15m"]),
        reverse=True,
    )[:TOP_RESULTS]

    counts = {
        "NOT_BULLISH": 0,
        "BELOW_RESISTANCE": 0,
        "LOW_VOLUME": 0,
        "WEAK_BODY": 0,
        "15M_NOT_UP": 0,
        "CHASE_TOO_HIGH": 0,
        "LOW_SCORE": 0,
    }

    for item in successful:
        for reason in item.get("reasons", []):
            if reason in counts:
                counts[reason] += 1

    summary = (
        f"📊 ATI DIAGNOSTIC SUMMARY {VERSION}\n\n"
        f"🟢 USDT MARKETS: {len(pairs)}\n"
        f"🔎 REQUESTED: {len(selected)}\n"
        f"📈 ANALYZED: {len(successful)}\n"
        f"⚠️ INSUFFICIENT CANDLES: {insufficient}\n"
        f"❌ API ERRORS: {errors}\n"
        f"🎯 QUALIFIED: {len(qualified)}\n"
        f"⏱ ELAPSED: {elapsed:.1f}s\n\n"
        f"🚫 FILTER COUNTS (overlapping):\n"
        f"Not bullish: {counts['NOT_BULLISH']}\n"
        f"Below resistance: {counts['BELOW_RESISTANCE']}\n"
        f"Low volume: {counts['LOW_VOLUME']}\n"
        f"Weak body: {counts['WEAK_BODY']}\n"
        f"15m not up: {counts['15M_NOT_UP']}\n"
        f"Chase too high: {counts['CHASE_TOO_HIGH']}\n"
        f"Low score: {counts['LOW_SCORE']}\n\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🛑 NO ORDER WAS SENT\n"
        f"🕐 {log_time()}"
    )
    notify(summary)

    if ranked:
        message = (
            f"🔬 ATI DIAGNOSTIC TOP {len(ranked)} {VERSION}\n\n"
            + "\n\n".join(
                format_result(item, index + 1)
                for index, item in enumerate(ranked)
            )
            + "\n\n🔒 REAL BUY: DISABLED"
            + "\n🛑 DIAGNOSTIC ONLY"
        )
        notify(message)
    else:
        notify(
            f"⚠️ ATI {VERSION}\n"
            f"NO ANALYZABLE MARKETS\n"
            f"Check trade response format and API errors.\n"
            f"🔒 REAL ORDERS: DISABLED"
        )

    notify(
        f"✅ ATI {VERSION} COMPLETE\n"
        f"📊 ANALYZED: {len(successful)}\n"
        f"🎯 QUALIFIED: {len(qualified)}\n"
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
            f"❌ {type(exc).__name__}: {str(exc)[:1000]}\n"
            f"🔒 REAL ORDERS: DISABLED\n"
            f"🕐 {log_time()}"
        )
        raise
