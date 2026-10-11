import os
import time
import math
import hmac
import hashlib
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# ATI FUTURES V19
# 5M + ICHIMOKU
# MARKET DISCOVERY WITH FALLBACK
# ============================================================

VERSION = "ATI FUTURES V19"

# ---------------- CONFIG ----------------

ORDER_USDT = float(os.getenv("ORDER_USDT", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

MAX_MARKETS = int(os.getenv("MAX_MARKETS", "75"))
KLINES_LIMIT = int(os.getenv("KLINES_LIMIT", "100"))

INTERVAL = "5m"

REQUEST_TIMEOUT = 12
MAX_WORKERS = 12

MIN_SCORE = 5

TP_PCT = float(os.getenv("TP_PCT", "0.012"))
SL_PCT = float(os.getenv("SL_PCT", "0.008"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# ============================================================
# IMPORTANT
#
# fapi.binance.com is the official USD-M Futures REST base.
# We try official endpoints first.
#
# We DO NOT silently use an unofficial proxy for real trading.
# ============================================================

BASE_URLS = [
    "https://fapi.binance.com",
    "https://demo-fapi.binance.com",
]

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-V19/1.0",
    "Accept": "application/json",
})


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )

    except Exception as e:
        print("Telegram error:", e)


# ============================================================
# HTTP
# ============================================================

def http_get(base, path, params=None):

    url = base + path

    r = session.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    if r.status_code == 451:
        raise RuntimeError(
            f"HTTP 451 restricted location: {url}"
        )

    r.raise_for_status()

    return r.json()


# ============================================================
# MARKET DISCOVERY
# ============================================================

def discover_markets():

    errors = []

    for base in BASE_URLS:

        try:

            print(f"🔎 Market discovery: {base}")

            data = http_get(
                base,
                "/fapi/v1/exchangeInfo",
            )

            if not isinstance(data, dict):
                raise ValueError(
                    f"Unexpected exchangeInfo type: {type(data).__name__}"
                )

            symbols = data.get("symbols", [])

            if not isinstance(symbols, list):
                raise ValueError(
                    "exchangeInfo.symbols is not a list"
                )

            markets = []

            for s in symbols:

                if not isinstance(s, dict):
                    continue

                symbol = s.get("symbol")
                status = s.get("status")
                contract = s.get("contractType")
                quote = s.get("quoteAsset")
                margin = s.get("marginAsset")

                if not symbol:
                    continue

                if status != "TRADING":
                    continue

                if quote != "USDT":
                    continue

                if margin != "USDT":
                    continue

                if contract != "PERPETUAL":
                    continue

                markets.append({
                    "symbol": symbol,
                    "base": base,
                    "filters": s.get("filters", []),
                    "pricePrecision": s.get(
                        "pricePrecision", 8
                    ),
                    "quantityPrecision": s.get(
                        "quantityPrecision", 8
                    ),
                })

            if markets:

                print(
                    f"✅ MARKET DISCOVERY OK: "
                    f"{len(markets)} USDT PERPETUAL"
                )

                return markets

            raise RuntimeError(
                "exchangeInfo returned data, "
                "but no eligible USDT perpetual markets were found"
            )

        except Exception as e:

            msg = str(e)

            errors.append(
                f"{base}: {msg}"
            )

            print(
                f"⚠️ Discovery failed: {base}"
            )
            print(msg)

    raise RuntimeError(
        "MARKET DISCOVERY FAILED\n" +
        "\n".join(errors)
    )


# ============================================================
# KLINES
# ============================================================

def get_klines(market):

    base = market["base"]
    symbol = market["symbol"]

    data = http_get(
        base,
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": INTERVAL,
            "limit": KLINES_LIMIT,
        },
    )

    if not isinstance(data, list):
        raise ValueError("Invalid kline response")

    if len(data) < 60:
        raise ValueError(
            f"Not enough candles: {len(data)}"
        )

    candles = []

    for x in data:

        if len(x) < 6:
            continue

        candles.append({
            "open": float(x[1]),
            "high": float(x[2]),
            "low": float(x[3]),
            "close": float(x[4]),
            "volume": float(x[5]),
        })

    return candles


# ============================================================
# ICHIMOKU
# ============================================================

def ichimoku_signal(c):

    highs = [x["high"] for x in c]
    lows = [x["low"] for x in c]
    closes = [x["close"] for x in c]

    if len(c) < 60:
        return None

    # Ichimoku 9 / 26 / 52

    tenkan_high = max(highs[-9:])
    tenkan_low = min(lows[-9:])
    tenkan = (tenkan_high + tenkan_low) / 2

    kijun_high = max(highs[-26:])
    kijun_low = min(lows[-26:])
    kijun = (kijun_high + kijun_low) / 2

    span_a = (tenkan + kijun) / 2

    span_b_high = max(highs[-52:])
    span_b_low = min(lows[-52:])
    span_b = (span_b_high + span_b_low) / 2

    price = closes[-1]

    cloud_top = max(span_a, span_b)
    cloud_bottom = min(span_a, span_b)

    score_buy = 0
    score_sell = 0

    reasons_buy = []
    reasons_sell = []

    # ---------------- BUY ----------------

    if price > cloud_top:
        score_buy += 2
        reasons_buy.append("PRICE_ABOVE_CLOUD")

    if tenkan > kijun:
        score_buy += 2
        reasons_buy.append("TENKAN_GT_KIJUN")

    if span_a > span_b:
        score_buy += 1
        reasons_buy.append("BULL_CLOUD")

    if closes[-1] > closes[-2]:
        score_buy += 1
        reasons_buy.append("MOMENTUM_UP")

    # ---------------- SELL ----------------

    if price < cloud_bottom:
        score_sell += 2
        reasons_sell.append("PRICE_BELOW_CLOUD")

    if tenkan < kijun:
        score_sell += 2
        reasons_sell.append("TENKAN_LT_KIJUN")

    if span_a < span_b:
        score_sell += 1
        reasons_sell.append("BEAR_CLOUD")

    if closes[-1] < closes[-2]:
        score_sell += 1
        reasons_sell.append("MOMENTUM_DOWN")

    if score_buy >= MIN_SCORE:
        return {
            "side": "BUY",
            "score": score_buy,
            "reasons": reasons_buy,
            "price": price,
        }

    if score_sell >= MIN_SCORE:
        return {
            "side": "SELL",
            "score": score_sell,
            "reasons": reasons_sell,
            "price": price,
        }

    return None


# ============================================================
# SCAN ONE MARKET
# ============================================================

def scan_market(market):

    try:

        candles = get_klines(market)

        signal = ichimoku_signal(candles)

        return {
            "market": market,
            "signal": signal,
            "ready": True,
            "error": None,
        }

    except Exception as e:

        return {
            "market": market,
            "signal": None,
            "ready": False,
            "error": str(e),
        }


# ============================================================
# QUANTITY
# ============================================================

def get_step_size(market):

    for f in market.get("filters", []):

        if f.get("filterType") == "LOT_SIZE":

            try:
                return float(f.get("stepSize", "0.001"))
            except:
                pass

    return 0.001


def round_step(value, step):

    if step <= 0:
        return value

    return math.floor(value / step) * step


# ============================================================
# SIGNATURE
# ============================================================

def signed_request(
    base,
    method,
    path,
    params=None,
):

    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "BINANCE_API_KEY / BINANCE_API_SECRET missing"
        )

    params = params or {}

    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000

    query = "&".join(
        f"{k}={params[k]}"
        for k in params
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()

    query += "&signature=" + signature

    url = base + path + "?" + query

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    if method == "GET":

        r = session.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    elif method == "POST":

        r = session.post(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    else:
        raise ValueError("Unsupported method")

    if r.status_code == 451:
        raise RuntimeError(
            "HTTP 451 restricted location"
        )

    r.raise_for_status()

    return r.json()


# ============================================================
# ACCOUNT
# ============================================================

def futures_balance(base):

    data = signed_request(
        base,
        "GET",
        "/fapi/v3/balance",
    )

    for item in data:

        if item.get("asset") == "USDT":

            return float(
                item.get("availableBalance", 0)
            )

    return 0.0


# ============================================================
# ORDER
# ============================================================

def place_order(signal, market):

    if not LIVE_TRADING:

        return {
            "status": "SIMULATION",
            "symbol": market["symbol"],
            "side": signal["side"],
        }

    base = market["base"]
    symbol = market["symbol"]
    price = signal["price"]

    qty = ORDER_USDT / price

    step = get_step_size(market)

    qty = round_step(qty, step)

    if qty <= 0:
        raise RuntimeError(
            f"Quantity became zero. "
            f"price={price} step={step}"
        )

    side = signal["side"]

    result = signed_request(
        base,
        "POST",
        "/fapi/v1/order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
        },
    )

    return result


# ============================================================
# FORMAT SIGNAL
# ============================================================

def signal_message(signal, market):

    symbol = market["symbol"]

    side = signal["side"]
    score = signal["score"]
    price = signal["price"]

    if side == "BUY":

        tp = price * (1 + TP_PCT)
        sl = price * (1 - SL_PCT)

        emoji = "🟢"

    else:

        tp = price * (1 - TP_PCT)
        sl = price * (1 + SL_PCT)

        emoji = "🔴"

    reasons = ", ".join(
        signal["reasons"]
    )

    return (
        f"🔥 ATI FUTURES V19 SIGNAL\n\n"
        f"💎 {symbol}\n"
        f"{emoji} {side}\n\n"
        f"📊 SCORE: {score}\n"
        f"💰 PRICE: {price:.8g}\n"
        f"🎯 TP: {tp:.8g}\n"
        f"🛑 SL: {sl:.8g}\n"
        f"⚡ LEVERAGE: {LEVERAGE}x\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n\n"
        f"☁️ ICHIMOKU 9/26/52\n"
        f"🧠 {reasons}\n\n"
        f"🔒 REAL: {LIVE_TRADING}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    now = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    print("=" * 60)
    print(VERSION)
    print("Time:", now)
    print("LIVE TRADING:", LIVE_TRADING)
    print("ORDER:", ORDER_USDT, "USDT")
    print("LEVERAGE:", LEVERAGE)
    print("=" * 60)

    telegram(
        f"💓 {VERSION}\n"
        f"🕐 {now}\n"
        f"⚡ Futures scanner started\n"
        f"☁️ Ichimoku 9/26/52\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"⚡ LEVERAGE: {LEVERAGE}x\n"
        f"🔒 REAL: {LIVE_TRADING}"
    )

    # --------------------------------------------------------
    # DISCOVERY
    # --------------------------------------------------------

    try:

        markets = discover_markets()

    except Exception as e:

        msg = (
            "❌ ATI V19 MARKET DISCOVERY ERROR\n\n"
            + str(e)
        )

        print(msg)
        telegram(msg)

        return

    # Limit scanning
    markets = markets[:MAX_MARKETS]

    print(
        f"📊 Markets selected: {len(markets)}"
    )

    # --------------------------------------------------------
    # PARALLEL SCAN
    # --------------------------------------------------------

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        jobs = [
            executor.submit(
                scan_market,
                market
            )
            for market in markets
        ]

        for job in as_completed(jobs):

            try:
                results.append(
                    job.result()
                )

            except Exception as e:

                print(
                    "Worker error:",
                    e
                )

    ready = sum(
        1
        for x in results
        if x["ready"]
    )

    errors = sum(
        1
        for x in results
        if not x["ready"]
    )

    signals = []

    for x in results:

        if x["signal"]:

            signals.append(x)

    elapsed = time.time() - started

    print(
        f"📊 Markets: {len(markets)}"
    )
    print(
        f"📈 5M Ready: {ready}"
    )
    print(
        f"🔥 Signals: {len(signals)}"
    )
    print(
        f"❌ Errors: {errors}"
    )
    print(
        f"⏱️ Scan: {elapsed:.2f}s"
    )

    # --------------------------------------------------------
    # SIGNALS
    # --------------------------------------------------------

    if not signals:

        telegram(
            f"💓 ATI FUTURES V19\n\n"
            f"☁️ NO SIGNAL THIS CYCLE\n\n"
            f"📊 Markets: {len(markets)}\n"
            f"📈 5M Ready: {ready}\n"
            f"❌ Errors: {errors}\n"
            f"⏱️ Scan: {elapsed:.2f}s\n\n"
            f"☁️ Ichimoku 9/26/52\n"
            f"💵 ORDER: {ORDER_USDT} USDT\n"
            f"⚡ LEVERAGE: {LEVERAGE}x\n"
            f"🔒 REAL: {LIVE_TRADING}"
        )

        return

    # Sort strongest first
    signals.sort(
        key=lambda x: x["signal"]["score"],
        reverse=True,
    )

    # --------------------------------------------------------
    # ONLY TOP SIGNAL
    # --------------------------------------------------------

    best = signals[0]

    market = best["market"]
    signal = best["signal"]

    msg = signal_message(
        signal,
        market,
    )

    print(msg)

    telegram(msg)

    # --------------------------------------------------------
    # REAL ORDER
    # --------------------------------------------------------

    if LIVE_TRADING:

        try:

            balance = futures_balance(
                market["base"]
            )

            telegram(
                f"💰 Futures USDT balance: "
                f"{balance:.4f}"
            )

            if balance < ORDER_USDT:

                telegram(
                    "⚠️ موجودی USDT برای "
                    "سفارش کافی نیست."
                )

                return

            order = place_order(
                signal,
                market,
            )

            telegram(
                "✅ REAL FUTURES ORDER SENT\n\n"
                f"💎 {market['symbol']}\n"
                f"📌 {signal['side']}\n"
                f"💵 {ORDER_USDT} USDT\n"
                f"⚡ {LEVERAGE}x\n\n"
                f"ORDER ID: "
                f"{order.get('orderId', 'N/A')}"
            )

        except Exception as e:

            telegram(
                "❌ REAL ORDER ERROR\n\n"
                + str(e)
            )

            print(
                "REAL ORDER ERROR:",
                e
            )


if __name__ == "__main__":
    main()
