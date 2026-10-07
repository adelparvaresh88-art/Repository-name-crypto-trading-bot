import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

# =========================================================
# ATI FUTURES V7.7
# TABDEAL FUTURES
# ICHIMOKU 5M
# KLINE DIAGNOSTIC + FAST SCANNER
# NO REAL ORDERS
# =========================================================

API_BASE = "https://api1.tabdeal.org"

FAPI_READ = API_BASE + "/r/fapi/"
FAPI_WRITE = API_BASE + "/fapi/"

INTERVAL = "5m"
KLINE_LIMIT = 100

WORKERS = 16
TIMEOUT = 8

TENKAN = 9
KIJUN = 26
SENKOU_B = 52

MIN_SCORE = 3.5
MAX_KIJUN_DISTANCE = 5.0

MAX_MARKETS = 100

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# بسیار مهم:
# این نسخه هیچ سفارش واقعی ارسال نمی‌کند.
REAL_TRADING = False


# =========================================================
# TIME
# =========================================================

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# =========================================================
# TELEGRAM
# =========================================================

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        requests.post(
            url,
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

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-FUTURES-V7.7",
    "Accept": "application/json",
})


def public_get(path, params=None):
    """
    Futures public GET.
    """
    url = FAPI_READ + path

    response = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"HTTP {response.status_code}: {response.text[:300]}"
        )

    try:
        return response.json()
    except Exception:
        raise RuntimeError(
            f"INVALID JSON: {response.text[:300]}"
        )


# =========================================================
# SERVER TIME TEST
# =========================================================

def test_server_time():

    try:
        data = public_get(
            "v1/time"
        )

        return True, str(data)

    except Exception as e:
        return False, str(e)


# =========================================================
# EXCHANGE INFO
# =========================================================

def get_exchange_info():

    return public_get(
        "v1/exchangeInfo"
    )


# =========================================================
# SYMBOL NORMALIZER
# =========================================================

def normalize_symbol(symbol):

    if not symbol:
        return ""

    symbol = str(symbol).upper().strip()

    symbol = (
        symbol
        .replace("_", "")
        .replace("-", "")
        .replace("/", "")
        .replace(" ", "")
    )

    return symbol


# =========================================================
# MARKET DISCOVERY
# =========================================================

def get_markets():

    data = get_exchange_info()

    symbols = []

    if isinstance(data, dict):

        raw = data.get("symbols", [])

    elif isinstance(data, list):

        raw = data

    else:

        raw = []

    for item in raw:

        if isinstance(item, str):

            symbol = normalize_symbol(item)

        elif isinstance(item, dict):

            symbol = normalize_symbol(
                item.get("symbol")
                or item.get("pair")
                or item.get("contract")
            )

        else:

            continue

        if not symbol:
            continue

        if not symbol.endswith("USDT"):
            continue

        symbols.append(symbol)

    # unique
    symbols = list(dict.fromkeys(symbols))

    return symbols[:MAX_MARKETS]


# =========================================================
# KLINE
# =========================================================

def get_klines(symbol):

    """
    Official Tabdeal Futures read structure:

    /r/fapi/v1/klines

    symbol = BTCUSDT
    interval = 5m
    """

    data = public_get(
        "v1/klines",
        {
            "symbol": symbol,
            "interval": INTERVAL,
            "limit": KLINE_LIMIT,
        }
    )

    if not isinstance(data, list):
        raise RuntimeError(
            f"KLINE NOT LIST: {str(data)[:300]}"
        )

    if len(data) < 60:
        raise RuntimeError(
            f"KLINE TOO SHORT: {len(data)}"
        )

    candles = []

    for row in data:

        if not isinstance(row, list):
            continue

        if len(row) < 6:
            continue

        try:

            candles.append({
                "time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })

        except Exception:
            continue

    if len(candles) < 60:
        raise RuntimeError(
            f"VALID KLINES TOO SHORT: {len(candles)}"
        )

    return candles


# =========================================================
# ICHIMOKU
# =========================================================

def ichimoku(candles):

    if len(candles) < 60:
        return None

    # آخرین کندل بسته شده
    i = len(candles) - 2

    def highest(start, end):
        values = [
            candles[x]["high"]
            for x in range(start, end + 1)
        ]
        return max(values)

    def lowest(start, end):
        values = [
            candles[x]["low"]
            for x in range(start, end + 1)
        ]
        return min(values)

    def midpoint(start, end):
        return (
            highest(start, end)
            +
            lowest(start, end)
        ) / 2.0

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
    ) / 2.0

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

    bullish_candle = close > open_price
    bearish_candle = close < open_price

    # previous candle
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

    bullish_cloud = senkou_a > senkou_b
    bearish_cloud = senkou_a < senkou_b

    # volume
    volume_start = max(0, i - 20)

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

    current_volume = candles[i]["volume"]

    volume_ok = (
        avg_volume > 0
        and current_volume >= avg_volume * 0.8
    )

    # distance from kijun
    if kijun != 0:

        kijun_distance = (
            abs(close - kijun)
            / abs(kijun)
        ) * 100.0

    else:

        kijun_distance = 999.0

    buy_score = 0.0
    sell_score = 0.0

    # =====================================================
    # BUY
    # =====================================================

    if close > cloud_top:
        buy_score += 2.5

    elif close > cloud_bottom:
        buy_score += 1.5

    if tenkan > kijun:
        buy_score += 1.5

    if bullish_cloud:
        buy_score += 1.0

    if bullish_cross:
        buy_score += 2.0

    if bullish_candle:
        buy_score += 0.5

    if volume_ok:
        buy_score += 0.5

    # =====================================================
    # SELL
    # =====================================================

    if close < cloud_bottom:
        sell_score += 2.5

    elif close < cloud_top:
        sell_score += 1.5

    if tenkan < kijun:
        sell_score += 1.5

    if bearish_cloud:
        sell_score += 1.0

    if bearish_cross:
        sell_score += 2.0

    if bearish_candle:
        sell_score += 0.5

    if volume_ok:
        sell_score += 0.5

    # =====================================================
    # SIGNAL
    # =====================================================

    signal = None
    score = max(
        buy_score,
        sell_score
    )

    if (
        buy_score >= MIN_SCORE
        and buy_score > sell_score
        and kijun_distance <= MAX_KIJUN_DISTANCE
    ):
        signal = "BUY"

    elif (
        sell_score >= MIN_SCORE
        and sell_score > buy_score
        and kijun_distance <= MAX_KIJUN_DISTANCE
    ):
        signal = "SELL"

    return {
        "signal": signal,
        "score": score,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "close": close,
        "tenkan": tenkan,
        "kijun": kijun,
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom,
        "kijun_distance": kijun_distance,
        "volume_ok": volume_ok,
        "bullish_cross": bullish_cross,
        "bearish_cross": bearish_cross,
    }


# =========================================================
# SCAN ONE SYMBOL
# =========================================================

def scan_symbol(symbol):

    try:

        candles = get_klines(symbol)

        result = ichimoku(candles)

        if result is None:
            return {
                "symbol": symbol,
                "ok": False,
                "error": "ICHIMOKU DATA ERROR",
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
# DIAGNOSTIC TEST
# =========================================================

def diagnostic():

    tests = [
        "BTCUSDT",
        "ETHUSDT",
    ]

    results = []

    for symbol in tests:

        result = scan_symbol(symbol)

        results.append(result)

    return results


# =========================================================
# TELEGRAM HEADER
# =========================================================

telegram(
    "💓 ATI FUTURES V7.7\n\n"
    "⚡ ICHIMOKU 5M\n"
    "☁️ 9 / 26 / 52\n\n"
    "🔧 KLINE ENDPOINT FIXED\n"
    "🎯 DIAGNOSTIC + FAST SCANNER\n\n"
    "📡 TABDEAL FUTURES\n\n"
    f"🕐 {utc_now()}"
)


# =========================================================
# SERVER TEST
# =========================================================

server_ok, server_info = test_server_time()

if not server_ok:

    telegram(
        "❌ ATI FUTURES V7.7\n\n"
        "🚨 SERVER TIME FAILED\n\n"
        f"{server_info}\n\n"
        "🛑 SCAN STOPPED\n"
        "🔒 NO ORDERS"
    )

    raise SystemExit(0)


# =========================================================
# KLINE DIAGNOSTIC
# =========================================================

diag = diagnostic()

diag_text = [
    "🧪 KLINE DIAGNOSTIC",
    ""
]

for item in diag:

    symbol = item["symbol"]

    if item["ok"]:

        diag_text.append(
            f"✅ {symbol} KLINE OK"
        )

    else:

        diag_text.append(
            f"❌ {symbol}"
        )

        diag_text.append(
            f"   {item['error'][:220]}"
        )

telegram(
    "\n".join(diag_text)
)


# =========================================================
# MARKET DISCOVERY
# =========================================================

try:

    markets = get_markets()

except Exception as e:

    telegram(
        "❌ EXCHANGE INFO FAILED\n\n"
        f"{str(e)[:500]}\n\n"
        "🛑 NO SCAN\n"
        "🔒 NO ORDERS"
    )

    raise SystemExit(0)


if not markets:

    telegram(
        "❌ NO FUTURES MARKETS FOUND\n\n"
        "🛑 SCAN STOPPED\n"
        "🔒 NO ORDERS"
    )

    raise SystemExit(0)


# =========================================================
# FAST SCAN
# =========================================================

start = time.time()

results = []

with ThreadPoolExecutor(
    max_workers=WORKERS
) as executor:

    futures = {
        executor.submit(
            scan_symbol,
            symbol
        ): symbol

        for symbol in markets
    }

    for future in as_completed(futures):

        try:

            result = future.result()

            results.append(result)

        except Exception as e:

            symbol = futures[future]

            results.append({
                "symbol": symbol,
                "ok": False,
                "error": str(e),
            })


elapsed = time.time() - start


# =========================================================
# STATS
# =========================================================

ok_count = sum(
    1
    for x in results
    if x.get("ok")
)

error_count = len(results) - ok_count

signals = [
    x
    for x in results
    if x.get("ok")
    and x.get("signal")
]


signals.sort(
    key=lambda x: x.get("score", 0),
    reverse=True
)


# =========================================================
# RESULT MESSAGE
# =========================================================

message = (
    "💓 ATI FUTURES V7.7\n\n"
    "⚡ ICHIMOKU 5M\n"
    "☁️ 9 / 26 / 52\n\n"
    f"📊 Markets: {len(markets)}\n"
    f"📈 Klines OK: {ok_count}\n"
    f"🔥 Signals: {len(signals)}\n"
    f"❌ Errors: {error_count}\n"
    f"⏱️ Scan: {elapsed:.2f}s\n\n"
)


# =========================================================
# SIGNALS
# =========================================================

if signals:

    message += "🎯 STRONGEST SIGNALS\n\n"

    for item in signals[:5]:

        symbol = item["symbol"]
        signal = item["signal"]

        score = item["score"]
        close = item["close"]

        message += (
            f"{'🟢' if signal == 'BUY' else '🔴'} "
            f"{signal} {symbol}\n"
            f"💵 Price: {close:g}\n"
            f"⭐ Score: {score:.1f}\n"
            f"📐 Kijun distance: "
            f"{item['kijun_distance']:.2f}%\n"
            f"☁️ Cloud: "
            f"{item['cloud_bottom']:g} - "
            f"{item['cloud_top']:g}\n"
        )

        if item["bullish_cross"]:
            message += "🔄 Bullish TK Cross\n"

        if item["bearish_cross"]:
            message += "🔄 Bearish TK Cross\n"

        message += "\n"

else:

    message += (
        "☁️ NO SIGNAL THIS CYCLE\n\n"
        "Ichimoku scanned closed 5m candles."
    )


message += (
    "\n\n🔒 REAL ORDERS: OFF\n"
    f"🕐 {utc_now()}"
)


telegram(message)

print(message)
