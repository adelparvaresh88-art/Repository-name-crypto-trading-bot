import os
import time
import json
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://api1.tabdeal.org"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ATI-Futures-Bot/18.0"})

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
MAX_MARKETS = int(os.getenv("MAX_MARKETS", "75"))
TIMEOUT = 12

# عمداً خاموش؛ این نسخه سفارش ثبت نمی‌کند.
LIVE_TRADING = False

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets are missing.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = SESSION.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message[:4000]
            },
            timeout=TIMEOUT
        )
        print("TELEGRAM:", r.status_code, r.text[:250])
    except Exception as e:
        print("TELEGRAM ERROR:", repr(e))

def get_json(url, params=None):
    try:
        r = SESSION.get(url, params=params, timeout=TIMEOUT)
        print(f"HTTP {r.status_code}: {r.url}")

        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"

        try:
            return r.json(), None
        except Exception:
            return None, "Response was not JSON"

    except Exception as e:
        return None, str(e)[:180]

def extract_markets(data):
    if isinstance(data, dict):
        rows = data.get("symbols", [])
    elif isinstance(data, list):
        rows = data
    else:
        rows = []

    markets = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        symbol = str(row.get("symbol", "")).upper()
        quote = str(row.get("quoteAsset", "")).upper()
        status = str(row.get("status", "")).upper()

        normalized = symbol.replace("_", "").replace("-", "")

        if not normalized.endswith("USDT"):
            continue
        if quote and quote != "USDT":
            continue
        if status and status not in ("TRADING", "ENABLED", "ACTIVE"):
            continue

        if normalized and normalized not in markets:
            markets.append(normalized)

    return markets

def test_endpoint(path, symbol):
    # فقط مسیرهای عمومی خواندنی را آزمایش می‌کنیم.
    variants = [
        (f"{BASE}/r/fapi/v1/{path}", {"symbol": symbol, "limit": 100}),
        (f"{BASE}/r/fapi/v1/{path}", {"symbol": symbol}),
    ]

    seen = set()
    results = []

    for url, params in variants:
        key = (url, tuple(sorted(params.items())))
        if key in seen:
            continue
        seen.add(key)

        data, error = get_json(url, params)
        if error:
            results.append({
                "path": path,
                "error": error
            })
            continue

        if isinstance(data, list):
            results.append({
                "path": path,
                "success": True,
                "type": "list",
                "rows": len(data),
                "sample": data[:1]
            })
            return results[-1]

        if isinstance(data, dict):
            results.append({
                "path": path,
                "success": True,
                "type": "dict",
                "keys": list(data.keys())[:15],
                "sample": str(data)[:300]
            })
            return results[-1]

        results.append({
            "path": path,
            "error": "Unexpected response type"
        })

    return results[-1] if results else {
        "path": path,
        "error": "No response"
    }

def main():
    print("=" * 55)
    print("ATI TABDEAL FUTURES API DIAGNOSTIC")
    print("Time:", now())
    print("MACD: 12 / 26 / 9")
    print("LIVE TRADING:", LIVE_TRADING)
    print("=" * 55)

    telegram(
        "🔎 ATI FUTURES API CHECK\n"
        f"Time: {now()}\n"
        "Checking futures markets and public data endpoints.\n"
        "REAL TRADING: OFF"
    )

    print("\nSTEP 1: Exchange information")
    data, error = get_json(f"{BASE}/r/fapi/v1/exchangeInfo")

    if error:
        message = (
            "❌ FUTURES EXCHANGE INFO FAILED\n"
            f"Error: {error}\nTime: {now()}"
        )
        print(message)
        telegram(message)
        raise RuntimeError(message)

    markets = extract_markets(data)
    print("Exchange response type:", type(data).__name__)
    print("Recognized USDT markets:", len(markets))
    print("First markets:", markets[:20])

    if not markets:
        print("ExchangeInfo sample:", json.dumps(data, ensure_ascii=False)[:1200])
        telegram(
            "❌ EXCHANGE INFO RETURNED NO ELIGIBLE USDT MARKETS\n"
            f"Response type: {type(data).__name__}\nTime: {now()}"
        )
        raise RuntimeError("No eligible USDT futures markets found.")

    # مسیرها را فقط روی یک بازار آزمایش می‌کنیم تا درخواست‌ها زیاد نشوند.
    symbol = "BTCUSDT" if "BTCUSDT" in markets else markets[0]
    print(f"\nSTEP 2: Public data endpoint test for {symbol}")

    candidate_paths = [
        "klines",
        "trades",
        "aggTrades",
        "continuousKlines",
        "markPriceKlines",
        "ticker/price",
        "depth",
    ]

    results = []
    for path in candidate_paths:
        print(f"\n--- Testing {path} ---")
        result = test_endpoint(path, symbol)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False)[:1000])

        # اگر مسیر کندل واقعاً لیست داده برگرداند، ثبت می‌کنیم.
        if (
            result.get("success")
            and result.get("path") in (
                "klines",
                "continuousKlines",
                "markPriceKlines"
            )
            and result.get("type") == "list"
            and result.get("rows", 0) > 0
        ):
            print("CANDLE ENDPOINT FOUND:", result["path"])

    working = [
        x for x in results
        if x.get("success")
    ]

    candle_paths = [
        x["path"] for x in results
        if x.get("success")
        and x.get("type") == "list"
        and x.get("rows", 0) > 0
        and x.get("path") in (
            "klines",
            "continuousKlines",
            "markPriceKlines"
        )
    ]

    print("\nSTEP 3: Summary")
    print("Markets found:", len(markets))
    print("Public endpoints returning data:", len(working))
    print("Candle endpoints found:", candle_paths)

    report = [
        "🧪 ATI FUTURES API DIAGNOSTIC",
        f"Time: {now()}",
        f"USDT markets: {len(markets)}",
        f"Test symbol: {symbol}",
        "",
        "ENDPOINT RESULTS:"
    ]

    for result in results:
        path = result.get("path", "?")
        if result.get("success"):
            report.append(
                f"✅ {path}: {result.get('type')} "
                f"rows={result.get('rows', '-')}"
            )
        else:
            report.append(f"❌ {path}: {result.get('error', 'failed')}")

    if candle_paths:
        report.extend([
            "",
            "✅ A candle endpoint returned data.",
            "Next step: validate its format and 5-minute interval."
        ])
    else:
        report.extend([
            "",
            "⚠️ No tested candle endpoint returned candle data.",
            "MACD signals were NOT calculated.",
            "REAL TRADING: OFF"
        ])

    final_message = "\n".join(report)
    print("\n" + final_message)
    telegram(final_message)

    # خطای ساختگی ایجاد نمی‌کنیم؛ گزارش تشخیصی را کامل می‌کنیم.
    print("\nDiagnostic completed at", now())

if __name__ == "__main__":
    main()
