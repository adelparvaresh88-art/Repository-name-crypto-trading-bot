import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

# =========================================================
# ATI FUTURES V8
# REAL TABDEAL FUTURES API
#
# Public market data:
#   /r/fapi/v1/exchangeInfo
#   /r/fapi/v1/depth
#
# NO fake klines endpoint
# NO fake futures trades endpoint
#
# REAL ORDERS: OFF
# =========================================================

BASE = "https://api1.tabdeal.org"

SCAN_UNIVERSE = int(os.getenv("SCAN_UNIVERSE", "75"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "20"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TIMEOUT = 8

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-FUTURES-V8",
    "Accept": "application/json",
})


# =========================================================
# TELEGRAM
# =========================================================

def telegram(text):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{TELEGRAM_TOKEN}/sendMessage"
        )

        session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
            },
            timeout=10,
        )

    except Exception as e:
        print("Telegram error:", e)


# =========================================================
# HTTP
# =========================================================

def get(path, params=None):

    url = BASE + path

    r = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT,
    )

    if r.status_code != 200:
        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:250]}"
        )

    return r.json()


# =========================================================
# FUTURES EXCHANGE INFO
# =========================================================

def futures_exchange_info():

    # Official Tabdeal Futures public endpoint
    return get(
        "/r/fapi/v1/exchangeInfo"
    )


def futures_symbols():

    data = futures_exchange_info()

    symbols = data.get("symbols", [])

    result = []

    for item in symbols:

        symbol = str(
            item.get("symbol", "")
        ).upper()

        status = str(
            item.get("status", "")
        ).upper()

        quote = str(
            item.get("quoteAsset", "")
        ).upper()

        if not symbol:
            continue

        if status not in (
            "TRADING",
            "ENABLED",
        ):
            continue

        if quote != "USDT":
            continue

        result.append(symbol)

    # unique
    result = list(dict.fromkeys(result))

    return result[:SCAN_UNIVERSE]


# =========================================================
# FUTURES ORDER BOOK
# =========================================================

def get_depth(symbol):

    data = get(
        "/r/fapi/v1/depth",
        {
            "symbol": symbol,
            "limit": 5,
        },
    )

    bids = data.get("bids", [])
    asks = data.get("asks", [])

    if not bids or not asks:
        raise RuntimeError(
            "Empty order book"
        )

    bid = float(bids[0][0])
    ask = float(asks[0][0])

    if bid <= 0 or ask <= 0:
        raise RuntimeError(
            "Invalid bid/ask"
        )

    mid = (
        bid + ask
    ) / 2.0

    spread = (
        (ask - bid) / mid
    ) * 100.0

    return {
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread": spread,
    }


# =========================================================
# SCAN ONE
# =========================================================

def scan_one(symbol):

    try:

        data = get_depth(symbol)

        return {
            "ok": True,
            "data": data,
            "error": None,
        }

    except Exception as e:

        return {
            "ok": False,
            "data": None,
            "error": str(e)[:180],
        }


# =========================================================
# MAIN
# =========================================================

def main():

    start = time.time()

    try:

        symbols = futures_symbols()

    except Exception as e:

        text = (
            "❌ ATI FUTURES V8 ERROR\n\n"
            "Futures exchangeInfo failed.\n\n"
            f"{str(e)}"
        )

        print(text)
        telegram(text)
        return

    if not symbols:

        text = (
            "❌ ATI FUTURES V8\n\n"
            "هیچ Futures USDT پیدا نشد."
        )

        print(text)
        telegram(text)
        return

    print(
        "💓 ATI FUTURES V8\n"
        "⚡ REAL FUTURES MARKET DATA\n"
        "📡 ORDER BOOK → MID PRICE\n"
    )

    ok = 0
    errors = 0

    samples = []
    error_samples = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        jobs = {
            executor.submit(
                scan_one,
                symbol
            ): symbol
            for symbol in symbols
        }

        for job in as_completed(jobs):

            result = job.result()

            if result["ok"]:

                ok += 1

                if len(samples) < 10:
                    samples.append(
                        result["data"]
                    )

            else:

                errors += 1

                if len(error_samples) < 5:

                    error_samples.append(
                        f"{jobs[job]}: "
                        f"{result['error']}"
                    )

    elapsed = time.time() - start

    print()
    print("━━━━━━━━━━━━━━━━━━━━")
    print("📊 ATI FUTURES V8")
    print("━━━━━━━━━━━━━━━━━━━━")
    print(f"📊 Markets: {len(symbols)}")
    print(f"📈 Depth OK: {ok}")
    print(f"❌ Errors: {errors}")
    print(f"⏱️ Scan: {elapsed:.2f}s")
    print("━━━━━━━━━━━━━━━━━━━━")

    text = (
        "💓 ATI FUTURES V8\n\n"
        "⚡ REAL FUTURES MARKET DATA\n"
        "📡 ORDER BOOK → MID PRICE\n\n"
        f"📊 Markets: {len(symbols)}\n"
        f"📈 Depth OK: {ok}\n"
        f"❌ Errors: {errors}\n"
        f"⏱️ Scan: {elapsed:.2f}s\n\n"
    )

    if samples:

        text += "📋 MARKET SAMPLE\n\n"

        for x in samples:

            text += (
                f"• {x['symbol']}\n"
                f"  Bid: {x['bid']:.10g}\n"
                f"  Ask: {x['ask']:.10g}\n"
                f"  Mid: {x['mid']:.10g}\n"
                f"  Spread: {x['spread']:.4f}%\n\n"
            )

    if error_samples:

        text += "🧪 ERROR SAMPLE\n\n"

        for e in error_samples:
            text += f"• {e}\n"

        text += "\n"

    text += (
        "☁️ Ichimoku: WAITING FOR 5M HISTORY\n\n"
        "🔒 REAL ORDERS: OFF\n"
        "🕐 "
        + datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    print(text)
    telegram(text)


if __name__ == "__main__":
    main()
