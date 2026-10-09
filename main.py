import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

VERSION = "ATI FUTURES V12 FIX"

BASE_URL = "https://api1.tabdeal.org"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

ORDER_USDT = float(os.getenv("ORDER_QTY", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))
REAL = os.getenv("LIVE_TRADING", "false").lower() == "true"

MAX_MARKETS = 75
WORKERS = 12
TIMEOUT = 8


def telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(text)
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text
            },
            timeout=10
        )
    except Exception as e:
        print("Telegram:", e)


def request_json(path, params=None):
    url = BASE_URL + path

    r = requests.get(
        url,
        params=params or {},
        timeout=TIMEOUT,
        headers={
            "User-Agent": "ATI-Futures-Bot/12"
        }
    )

    if r.status_code != 200:
        raise RuntimeError(
            f"{path}: HTTP {r.status_code}: {r.text[:250]}"
        )

    try:
        return r.json()
    except Exception:
        raise RuntimeError(
            f"{path}: invalid JSON: {r.text[:250]}"
        )


def find_markets():

    # مهم:
    # اینجا دیگر /fapi/v1 استفاده نمی‌شود.
    candidates = [
        "/r/api/v1/exchangeInfo",
        "/api/v1/exchangeInfo",
    ]

    last_error = None

    for path in candidates:

        try:
            data = request_json(path)

            print(
                "EXCHANGEINFO:",
                path,
                type(data).__name__
            )

            if isinstance(data, list):
                raw = data

            elif isinstance(data, dict):
                raw = (
                    data.get("symbols")
                    or data.get("data")
                    or data.get("result")
                    or []
                )

            else:
                raw = []

            if isinstance(raw, dict):
                raw = (
                    raw.get("symbols")
                    or raw.get("data")
                    or []
                )

            markets = []

            for item in raw:

                if not isinstance(item, dict):
                    continue

                symbol = str(
                    item.get("symbol")
                    or item.get("s")
                    or ""
                ).upper()

                if not symbol:
                    continue

                if "USDT" not in symbol:
                    continue

                markets.append(symbol)

            # unique
            markets = list(dict.fromkeys(markets))

            if markets:
                return markets[:MAX_MARKETS], path

        except Exception as e:
            last_error = str(e)

    raise RuntimeError(
        f"exchangeInfo failed: {last_error}"
    )


def get_depth(symbol):

    # این endpoint را جدا از fapi بررسی می‌کنیم.
    candidates = [
        "/r/api/v1/depth",
        "/api/v1/depth",
    ]

    last_error = None

    for path in candidates:

        try:

            data = request_json(
                path,
                {
                    "symbol": symbol,
                    "limit": 20
                }
            )

            if isinstance(data, dict):

                bids = data.get("bids") or []
                asks = data.get("asks") or []

                if bids and asks:
                    return data

        except Exception as e:
            last_error = str(e)

    raise RuntimeError(
        f"{symbol}: depth failed: {last_error}"
    )


def analyse(symbol):

    try:

        data = get_depth(symbol)

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if not bids or not asks:
            return {
                "symbol": symbol,
                "ready": False,
                "error": "empty depth"
            }

        bid_volume = 0.0
        ask_volume = 0.0

        for x in bids[:20]:
            try:
                bid_volume += float(x[1])
            except Exception:
                pass

        for x in asks[:20]:
            try:
                ask_volume += float(x[1])
            except Exception:
                pass

        if ask_volume <= 0:
            return {
                "symbol": symbol,
                "ready": False,
                "error": "invalid ask volume"
            }

        imbalance = bid_volume / ask_volume

        signal = None

        if imbalance >= 1.50:
            signal = "BUY"

        elif imbalance <= 0.67:
            signal = "SELL"

        return {
            "symbol": symbol,
            "ready": True,
            "signal": signal,
            "imbalance": imbalance
        }

    except Exception as e:

        return {
            "symbol": symbol,
            "ready": False,
            "error": str(e)[:200]
        }


def main():

    start = time.time()

    telegram(
        f"💓 {VERSION}\n"
        f"⚡ DIRECT API MODE\n"
        f"📊 FUTURES DISCOVERY TEST\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"⚙️ LEVERAGE: {LEVERAGE}x\n"
        f"🔒 REAL: {REAL}"
    )

    try:

        markets, exchange_path = find_markets()

        print(
            f"FOUND {len(markets)} MARKETS "
            f"USING {exchange_path}"
        )

    except Exception as e:

        msg = (
            f"❌ {VERSION}\n\n"
            f"MARKET DISCOVERY FAILED\n\n"
            f"{e}"
        )

        print(msg)
        telegram(msg)
        return

    results = []

    with ThreadPoolExecutor(
        max_workers=WORKERS
    ) as executor:

        jobs = {
            executor.submit(analyse, s): s
            for s in markets
        }

        for job in as_completed(jobs):

            try:
                results.append(job.result())
            except Exception as e:
                results.append({
                    "symbol": jobs[job],
                    "ready": False,
                    "error": str(e)
                })

    ready = [
        x for x in results
        if x.get("ready")
    ]

    errors = [
        x for x in results
        if not x.get("ready")
    ]

    signals = [
        x for x in ready
        if x.get("signal")
    ]

    elapsed = time.time() - start

    text = (
        f"💓 {VERSION}\n\n"
        f"☁️ NO SIGNAL THIS CYCLE\n\n"
        f"📊 Markets: {len(markets)}\n"
        f"📈 Ready: {len(ready)}\n"
        f"🔥 Signals: {len(signals)}\n"
        f"❌ Errors: {len(errors)}\n"
        f"⏱️ Scan: {elapsed:.2f}s\n\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"⚡ LEVERAGE: {LEVERAGE}x\n"
        f"🔒 REAL: {REAL}"
    )

    if signals:

        best = max(
            signals,
            key=lambda x: abs(
                x.get("imbalance", 1) - 1
            )
        )

        text = (
            f"🔥 ATI FUTURES SIGNAL\n\n"
            f"💎 {best['symbol']}\n"
            f"📌 {best['signal']}\n"
            f"⚖️ IMBALANCE: "
            f"{best['imbalance']:.3f}\n\n"
            f"Markets: {len(markets)}\n"
            f"Ready: {len(ready)}\n"
            f"Signals: {len(signals)}\n"
            f"Errors: {len(errors)}\n"
            f"Scan: {elapsed:.2f}s\n\n"
            f"💵 ORDER: {ORDER_USDT} USDT\n"
            f"⚡ LEVERAGE: {LEVERAGE}x\n"
            f"🔒 REAL: {REAL}"
        )

    if errors:

        text += "\n\n❌ ERROR SAMPLE:\n"

        for item in errors[:5]:
            text += (
                f"{item['symbol']}: "
                f"{item.get('error', '')[:180]}\n"
            )

    print(text)
    telegram(text)


if __name__ == "__main__":
    main()
