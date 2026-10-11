import os
import json
import requests
from datetime import datetime, timezone

BASE = "https://api1.tabdeal.org"
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TIMEOUT = 12
LIVE_TRADING = False

session = requests.Session()
session.headers.update({"User-Agent": "ATI-Futures-Diagnostic/19.0"})


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def notify(text):
    print(text)
    if not TOKEN or not CHAT_ID:
        print("Telegram secrets missing.")
        return

    try:
        r = session.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text[:4000]},
            timeout=TIMEOUT
        )
        print("Telegram status:", r.status_code)
        print(r.text[:300])
    except Exception as e:
        print("Telegram error:", repr(e))


def request_test(path, params, label):
    url = BASE + path

    print("\n" + "=" * 60)
    print("TEST:", label)
    print("URL:", url)
    print("PARAMS:", params)

    try:
        response = session.get(url, params=params, timeout=TIMEOUT)
        print("HTTP:", response.status_code)
        print("FINAL URL:", response.url)
        print("BODY:", response.text[:900])

        try:
            body = response.json()
        except Exception:
            body = response.text[:500]

        return {
            "label": label,
            "path": path,
            "status": response.status_code,
            "url": response.url,
            "body": body
        }

    except Exception as e:
        print("REQUEST ERROR:", repr(e))
        return {
            "label": label,
            "path": path,
            "status": "EXCEPTION",
            "body": repr(e)
        }


def get_markets():
    result = request_test(
        "/r/fapi/v1/exchangeInfo",
        {},
        "Futures exchangeInfo"
    )

    body = result["body"]

    if result["status"] != 200 or not isinstance(body, dict):
        raise RuntimeError(
            "exchangeInfo failed: " +
            str(body)[:300]
        )

    rows = body.get("symbols", [])
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
        if status and status not in ("TRADING", "ACTIVE", "ENABLED"):
            continue

        markets.append({
            "symbol": normalized,
            "raw": symbol
        })

    # حذف نمادهای تکراری
    unique = {}
    for market in markets:
        unique[market["symbol"]] = market

    return list(unique.values())


def main():
    print("ATI FUTURES API DIAGNOSTIC V19")
    print("Time:", now())
    print("REAL TRADING:", LIVE_TRADING)

    notify(
        "🔎 ATI FUTURES API DIAGNOSTIC V19\n"
        f"Time: {now()}\n"
        "REAL TRADING: OFF"
    )

    markets = get_markets()

    if not markets:
        raise RuntimeError("No USDT futures markets found.")

    selected = next(
        (m for m in markets if m["symbol"] == "BTCUSDT"),
        markets[0]
    )

    normalized = selected["symbol"]
    raw = selected["raw"]

    print("Markets found:", len(markets))
    print("Selected normalized symbol:", normalized)
    print("Selected raw symbol:", raw)

    # نمادهای مختلف؛ فقط درخواست خواندنی
    variants = [
        ("symbol=normalized", {"symbol": normalized}),
        ("symbol=raw", {"symbol": raw}),
        ("tabdealSymbol=raw", {"tabdealSymbol": raw}),
        ("symbol=normalized+limit", {"symbol": normalized, "limit": 5}),
        ("symbol=raw+limit", {"symbol": raw, "limit": 5}),
        ("tabdealSymbol=raw+limit", {"tabdealSymbol": raw, "limit": 5}),
    ]

    results = []

    # آزمایش دفتر سفارش در دو مسیر
    for path in (
        "/r/fapi/v1/depth",
        "/fapi/v1/depth",
    ):
        for label, params in variants:
            results.append(
                request_test(
                    path,
                    params,
                    f"DEPTH {path} {label}"
                )
            )

    # تأیید می‌کنیم که مسیرهای قبلی همچنان موجود نیستند یا نه.
    for path in (
        "/r/fapi/v1/klines",
        "/r/fapi/v1/trades",
    ):
        results.append(
            request_test(
                path,
                {"symbol": normalized, "interval": "5m", "limit": 3},
                f"CHECK {path}"
            )
        )

    summary = [
        "🧪 ATI FUTURES API RESULTS V19",
        f"Time: {now()}",
        f"Markets: {len(markets)}",
        f"Test symbol: {normalized} / {raw}",
        "REAL TRADING: OFF",
        "",
        "RESULTS:"
    ]

    for item in results:
        body = item.get("body", "")
        if isinstance(body, (dict, list)):
            body_text = json.dumps(body, ensure_ascii=False)
        else:
            body_text = str(body)

        summary.append(
            f"{item['status']} | {item['label']}\n"
            f"{body_text[:350]}"
        )

    report = "\n\n".join(summary)
    print("\n" + report)

    # ارسال خلاصه‌ای که خطاهای مهم را هم حفظ کند.
    notify(report[:3900])

    print("Diagnostic finished:", now())


if __name__ == "__main__":
    main()
