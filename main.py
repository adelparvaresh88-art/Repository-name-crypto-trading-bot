import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

# =========================================================
# ATI FUTURES V7.8
# TABDEAL FUTURES
# TRADES -> 5M CANDLES -> ICHIMOKU
# NO REAL ORDERS
# =========================================================

API_BASE = "https://api1.tabdeal.org"

FAPI_READ = API_BASE + "/r/fapi/"

INTERVAL_MINUTES = 5
TRADES_LIMIT = 1000

WORKERS = 16
TIMEOUT = 8

TENKAN = 9
KIJUN = 26
SENKOU_B = 52

MIN_SCORE = 3.5
MAX_KIJUN_DISTANCE = 5.0

MAX_MARKETS = 75

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

REAL_TRADING = False

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-FUTURES-V7.8",
    "Accept": "application/json",
})


# =========================================================
# TIME
# =========================================================

def utc_now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# =========================================================
# TELEGRAM
# =========================================================

def telegram(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return

    try:

        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )

    except Exception as e:

        print("Telegram error:", e)


# =========================================================
# HTTP
# =========================================================

def public_get(path, params=None):

    url = FAPI_READ + path

    response = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT,
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:250]}"
        )

    try:

        return response.json()

    except Exception:

        raise RuntimeError(
            f"INVALID JSON: {response.text[:250]}"
        )


# =========================================================
# SERVER TIME
# =========================================================

def server_time():

    return public_get("v1/time")


# =========================================================
# EXCHANGE INFO
# =========================================================

def exchange_info():

    return public_get(
        "v1/exchangeInfo"
    )


# =========================================================
# MARKETS
# =========================================================

def get_markets():

    data = exchange_info()

    raw = []

    if isinstance(data, dict):

        raw = data.get("symbols", [])

    elif isinstance(data, list):

        raw = data

    markets = []

    for item in raw:

        if isinstance(item, str):

            symbol = item.upper()

        elif isinstance(item, dict):

            symbol = str(
                item.get("symbol")
                or item.get("pair")
                or item.get("contract")
                or ""
            ).upper()

        else:

            continue

        symbol = (
            symbol
            .replace("_", "")
            .replace("-", "")
            .replace("/", "")
            .replace(" ", "")
        )

        if symbol.endswith("USDT"):

            markets.append(symbol)

    return list(dict.fromkeys(markets))[:MAX_MARKETS]


# =========================================================
# RECENT FUTURES TRADES
# =========================================================

def get_trades(symbol):

    data = public_get(
        "v1/trades",
        {
            "symbol": symbol,
            "limit": TRADES_LIMIT,
        }
    )

    if not isinstance(data, list):

        raise RuntimeError(
            f"TRADES RESPONSE INVALID: "
            f"{str(data)[:250]}"
        )

    trades = []

    for row in data:

        try:

            # Binance-style:
            # id, price, qty, time, isBuyerMaker
            if isinstance(row, dict):

                price = float(
                    row.get("price")
                )

                qty = float(
                    row.get("qty")
                    or row.get("quantity")
                    or 0
                )

                timestamp = int(
                    row.get("time")
                    or row.get("timestamp")
                )

            elif isinstance(row, list):

                # fallback
                price = float(row[1])
                qty = float(row[2])
                timestamp = int(row[4])

            else:

                continue

            if price <= 0:
                continue

            trades.append({
                "price": price,
                "qty": qty,
                "time": timestamp,
            })

        except Exception:

            continue

    if len(trades) < 20:

        raise RuntimeError(
            f"TOO FEW TRADES: {len(trades)}"
        )

    return trades


# =========================================================
# TRADES -> 5 MIN CANDLES
# =========================================================

def trades_to_5m(trades):

    buckets = {}

    bucket_ms = INTERVAL_MINUTES * 60 * 1000

    for trade in trades:

        timestamp = trade["time"]

        bucket = (
            timestamp // bucket_ms
        ) * bucket_ms

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
            }

        candle = buckets[bucket]

        price = trade["price"]

        candle["high"] = max(
            candle["high"],
            price
        )

        candle["low"] = min(
            candle["low"],
            price
        )

        candle["close"] = price

        candle["volume"] += trade["qty"]

    candles = [
        buckets[key]
        for key in sorted(buckets)
    ]

    return candles


# =========================================================
# ICHIMOKU
# =========================================================

def ichimoku(candles):

    # آخرین کندل بسته شده
    if len(candles) < 60:
        return None

    i = len(candles) - 2

    def highest(a, b):

        return max(
            candles[x]["high"]
            for x in range(a, b + 1)
        )

    def lowest(a, b):

        return min(
            candles[x]["low"]
            for x in range(a, b + 1)
        )

    def midpoint(a, b):

        return (
            highest(a, b)
            +
            lowest(a, b)
        ) / 2

    tenkan = midpoint(
        i - TENKAN + 1,
        i
    )

    kijun = midpoint(
        i - KIJUN + 1,
        i
    )

    senkou_a = (
        tenkan + kijun
    ) / 2

    senkou_b = midpoint(
        i - SENKOU_B + 1,
        i
    )

    cloud_top = max(
        senkou_a,
        senkou_b
    )

    cloud_bottom = min(
        senkou_a,
        senkou_b
    )

    close = candles[i]["close"]

    open_price = candles[i]["open"]

    bullish_candle = (
        close > open_price
    )

    bearish_candle = (
        close < open_price
    )

    # previous closed candle
    p = i - 1

    prev_tenkan = midpoint(
        p - TENKAN + 1,
        p
    )

    prev_kijun = midpoint(
        p - KIJUN + 1,
        p
    )

    bullish_cross = (
        prev_tenkan <= prev_kijun
        and tenkan > kijun
    )

    bearish_cross = (
        prev_tenkan >= prev_kijun
        and tenkan < kijun
    )

    bullish_cloud = (
        senkou_a > senkou_b
    )

    bearish_cloud = (
        senkou_a < senkou_b
    )

    volume_start = max(
        0,
        i - 20
    )

    volumes = [
        candles[x]["volume"]
        for x in range(
            volume_start,
            i
        )
    ]

    avg_volume = (
        sum(volumes) / len(volumes)
        if volumes
        else 0
    )

    current_volume = (
        candles[i]["volume"]
    )

    volume_ok = (
        avg_volume > 0
        and current_volume >=
        avg_volume * 0.8
    )

    if kijun:

        kijun_distance = (
            abs(close - kijun)
            / abs(kijun)
        ) * 100

    else:

        kijun_distance = 999

    buy = 0.0
    sell = 0.0

    # =====================================================
    # BUY
    # =====================================================

    if close > cloud_top:

        buy += 2.5

    elif close > cloud_bottom:

        buy += 1.5

    if tenkan > kijun:

        buy += 1.5

    if bullish_cloud:

        buy += 1.0

    if bullish_cross:

        buy += 2.0

    if bullish_candle:

        buy += 0.5

    if volume_ok:

        buy += 0.5

    # =====================================================
    # SELL
    # =====================================================

    if close < cloud_bottom:

        sell += 2.5

    elif close < cloud_top:

        sell += 1.5

    if tenkan < kijun:

        sell += 1.5

    if bearish_cloud:

        sell += 1.0

    if bearish_cross:

        sell += 2.0

    if bearish_candle:

        sell += 0.5

    if volume_ok:

        sell += 0.5

    signal = None

    score = max(
        buy,
        sell
    )

    if (
        buy >= MIN_SCORE
        and buy > sell
        and kijun_distance <= MAX_KIJUN_DISTANCE
    ):

        signal = "BUY"

    elif (
        sell >= MIN_SCORE
        and sell > buy
        and kijun_distance <= MAX_KIJUN_DISTANCE
    ):

        signal = "SELL"

    return {
        "signal": signal,
        "score": score,
        "buy": buy,
        "sell": sell,
        "close": close,
        "kijun": kijun,
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom,
        "distance": kijun_distance,
        "candles": len(candles),
        "bull_cross": bullish_cross,
        "bear_cross": bearish_cross,
    }


# =========================================================
# ONE SYMBOL
# =========================================================

def scan_symbol(symbol):

    try:

        trades = get_trades(symbol)

        candles = trades_to_5m(
            trades
        )

        if len(candles) < 60:

            return {
                "symbol": symbol,
                "ok": False,
                "error": (
                    f"ONLY {len(candles)} "
                    f"5M CANDLES"
                ),
            }

        result = ichimoku(
            candles
        )

        if result is None:

            return {
                "symbol": symbol,
                "ok": False,
                "error": "ICHIMOKU FAILED",
            }

        result["symbol"] = symbol
        result["ok"] = True

        return result

    except Exception as e:

        return {
            "symbol": symbol,
            "ok": False,
            "error": str(e),
        }


# =========================================================
# START
# =========================================================

telegram(
    "💓 ATI FUTURES V7.8\n\n"
    "⚡ TRADES → 5M CANDLES\n"
    "☁️ ICHIMOKU 9 / 26 / 52\n\n"
    "🎯 FAST FUTURES SCANNER\n"
    "📡 TABDEAL FUTURES\n\n"
    "🔒 REAL ORDERS: OFF\n\n"
    f"🕐 {utc_now()}"
)


# =========================================================
# SERVER TEST
# =========================================================

try:

    server_time()

except Exception as e:

    telegram(
        "❌ FUTURES SERVER ERROR\n\n"
        f"{str(e)[:500]}\n\n"
        "🛑 SCAN STOPPED\n"
        "🔒 NO ORDERS"
    )

    raise SystemExit(0)


# =========================================================
# MARKET LIST
# =========================================================

try:

    markets = get_markets()

except Exception as e:

    telegram(
        "❌ FUTURES MARKET ERROR\n\n"
        f"{str(e)[:500]}\n\n"
        "🛑 NO SCAN\n"
        "🔒 NO ORDERS"
    )

    raise SystemExit(0)


if not markets:

    telegram(
        "❌ NO FUTURES MARKETS\n\n"
        "🛑 STOPPED"
    )

    raise SystemExit(0)


# =========================================================
# FAST PARALLEL SCAN
# =========================================================

start = time.time()

results = []

with ThreadPoolExecutor(
    max_workers=WORKERS
) as executor:

    jobs = {
        executor.submit(
            scan_symbol,
            symbol
        ): symbol

        for symbol in markets
    }

    for job in as_completed(jobs):

        try:

            results.append(
                job.result()
            )

        except Exception as e:

            results.append({
                "symbol": jobs[job],
                "ok": False,
                "error": str(e),
            })


elapsed = time.time() - start


# =========================================================
# STATS
# =========================================================

ok = [
    x for x in results
    if x.get("ok")
]

errors = [
    x for x in results
    if not x.get("ok")
]

signals = [
    x for x in ok
    if x.get("signal")
]

signals.sort(
    key=lambda x: x["score"],
    reverse=True
)


# =========================================================
# REPORT
# =========================================================

message = (
    "💓 ATI FUTURES V7.8\n\n"
    "⚡ TRADES → 5M\n"
    "☁️ ICHIMOKU 9 / 26 / 52\n\n"
    f"📊 Markets: {len(markets)}\n"
    f"📈 5M OK: {len(ok)}\n"
    f"🔥 Signals: {len(signals)}\n"
    f"❌ Errors: {len(errors)}\n"
    f"⏱️ Scan: {elapsed:.2f}s\n\n"
)


if signals:

    message += "🎯 SIGNALS\n\n"

    for item in signals[:5]:

        icon = (
            "🟢"
            if item["signal"] == "BUY"
            else "🔴"
        )

        message += (
            f"{icon} {item['signal']} "
            f"{item['symbol']}\n"
            f"💵 {item['close']:g}\n"
            f"⭐ Score: {item['score']:.1f}\n"
            f"📐 Kijun: "
            f"{item['distance']:.2f}%\n"
            f"🕯️ Candles: "
            f"{item['candles']}\n"
        )

        if item["bull_cross"]:
            message += "🔄 Bullish TK Cross\n"

        if item["bear_cross"]:
            message += "🔄 Bearish TK Cross\n"

        message += "\n"

else:

    message += (
        "☁️ NO SIGNAL THIS CYCLE\n\n"
        "5M candles built from Futures trades."
    )


message += (
    "\n🔒 REAL ORDERS: OFF\n"
    f"🕐 {utc_now()}"
)


telegram(message)

print(message)
