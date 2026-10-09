import os
import time
import requests
import concurrent.futures
from datetime import datetime, timezone

# =========================================================
# ATI FUTURES - ICHIMOKU 5M DIAGNOSTIC SCANNER
# =========================================================

VERSION = "ATI FUTURES V14"

BASE_URL = os.getenv(
    "BASE_URL",
    "https://api1.tabdeal.org"
).rstrip("/")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SCAN_UNIVERSE = int(os.getenv("SCAN_UNIVERSE", "75"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "10"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "12"))
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "100"))
INTERVAL = "5m"

ORDER_USDT = float(os.getenv("ORDER_USDT", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

# این نسخه سفارش واقعی ثبت نمی‌کند.
LIVE_TRADING = False

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-Futures-Bot/14.0"
})


# =========================================================
# TELEGRAM
# =========================================================

def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets are missing.", flush=True)
        print(message, flush=True)
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True
            },
            timeout=15
        )

        if response.status_code != 200:
            print(
                "Telegram error:",
                response.status_code,
                response.text[:500],
                flush=True
            )
            return False

        return True

    except Exception as exc:
        print("Telegram exception:", repr(exc), flush=True)
        return False


# =========================================================
# GENERAL HELPERS
# =========================================================

def utc_now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def get_json(url, params=None):
    response = session.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()
    return response.json()


def unwrap_list(data):
    """
    Exchange information may be a list or a dictionary.
    Handle both formats safely.
    """

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in (
            "symbols",
            "data",
            "result",
            "markets"
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                for nested_key in (
                    "symbols",
                    "data",
                    "markets"
                ):
                    nested = value.get(nested_key)

                    if isinstance(nested, list):
                        return nested

    raise ValueError(
        "Unknown exchangeInfo format: "
        + str(type(data).__name__)
        + " "
        + str(data)[:250]
    )


def normalize_symbol(item):
    if not isinstance(item, dict):
        return ""

    symbol = (
        item.get("symbol")
        or item.get("s")
        or item.get("market")
        or ""
    )

    return str(symbol).strip().upper()


def is_usdt_market(item):
    symbol = normalize_symbol(item)

    if not symbol.endswith("USDT"):
        return False

    if "_" in symbol:
        return False

    status = str(
        item.get("status", "TRADING")
    ).upper()

    if status not in (
        "TRADING",
        "ENABLED",
        "OPEN",
        "1"
    ):
        return False

    # Reject known non-perpetual contracts when that
    # information is available.
    contract_type = str(
        item.get("contractType", "")
    ).upper()

    if contract_type and contract_type not in (
        "PERPETUAL",
        "PERPETUAL_CONTRACT"
    ):
        return False

    return True


# =========================================================
# FUTURES MARKET DISCOVERY
# =========================================================

def discover_markets():
    paths = [
        "/r/fapi/v1/exchangeInfo",
        "/fapi/v1/exchangeInfo",
    ]

    errors = []

    for path in paths:
        url = BASE_URL + path

        try:
            data = get_json(url)

            markets = unwrap_list(data)

            valid = [
                item
                for item in markets
                if is_usdt_market(item)
            ]

            if not valid:
                raise ValueError(
                    "exchangeInfo returned data, "
                    "but no eligible USDT markets were found."
                )

            valid.sort(
                key=lambda item: normalize_symbol(item)
            )

            print(
                "Market discovery OK:",
                path,
                "total:",
                len(markets),
                "USDT:",
                len(valid),
                flush=True
            )

            return valid[:SCAN_UNIVERSE]

        except Exception as exc:
            error = (
                path
                + " -> "
                + type(exc).__name__
                + ": "
                + str(exc)[:250]
            )

            errors.append(error)

            print(
                "[MARKET ERROR]",
                error,
                flush=True
            )

    raise RuntimeError(
        "Market discovery failed: "
        + " || ".join(errors)
    )


# =========================================================
# CANDLE DATA
# =========================================================

def parse_candle_array(row):
    """
    Standard candle array:
    [
      openTime, open, high, low, close, volume,
      closeTime, quoteVolume, trades, ...
    ]
    """

    if not isinstance(row, (list, tuple)):
        return None

    if len(row) < 6:
        return None

    try:
        return {
            "time": int(float(row[0])),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }

    except (TypeError, ValueError):
        return None


def parse_candle_dict(row):
    if not isinstance(row, dict):
        return None

    try:
        return {
            "time": int(float(
                row.get("openTime")
                or row.get("open_time")
                or row.get("time")
                or row.get("t")
                or 0
            )),
            "open": float(
                row.get("open")
                or row.get("o")
            ),
            "high": float(
                row.get("high")
                or row.get("h")
            ),
            "low": float(
                row.get("low")
                or row.get("l")
            ),
            "close": float(
                row.get("close")
                or row.get("c")
            ),
            "volume": float(
                row.get("volume")
                or row.get("v")
                or 0
            ),
        }

    except (TypeError, ValueError):
        return None


def normalize_candles(data):
    if isinstance(data, dict):
        for key in (
            "data",
            "result",
            "klines",
            "candles",
            "rows"
        ):
            if key in data:
                return normalize_candles(data[key])

        raise ValueError(
            "Unknown candle dictionary format: "
            + str(list(data.keys()))[:250]
        )

    if not isinstance(data, list):
        raise ValueError(
            "Candle response is not a list: "
            + type(data).__name__
        )

    candles = []

    for row in data:
        candle = parse_candle_array(row)

        if candle is None:
            candle = parse_candle_dict(row)

        if candle is not None:
            if (
                candle["open"] > 0
                and candle["high"] > 0
                and candle["low"] > 0
                and candle["close"] > 0
            ):
                candles.append(candle)

    candles.sort(key=lambda candle: candle["time"])

    # Remove duplicate timestamps.
    unique = {}

    for candle in candles:
        unique[candle["time"]] = candle

    return list(unique.values())


def get_futures_candles(symbol):
    """
    Test known candidate futures candle endpoints.
    The first endpoint returning valid candles is used.

    If all candidates fail, preserve the exact error.
    """

    paths = [
        "/r/fapi/v1/klines",
        "/fapi/v1/klines",
        "/r/fapi/v1/candles",
        "/fapi/v1/candles",
    ]

    errors = []

    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "limit": KLINE_LIMIT
    }

    for path in paths:
        url = BASE_URL + path

        try:
            data = get_json(
                url,
                params=params
            )

            candles = normalize_candles(data)

            if len(candles) < 60:
                raise ValueError(
                    "Endpoint responded, but returned only "
                    + str(len(candles))
                    + " valid candles; need at least 60."
                )

            return candles, path

        except Exception as exc:
            error = (
                path
                + " -> "
                + type(exc).__name__
                + ": "
                + str(exc).replace("\n", " ")[:220]
            )

            errors.append(error)

    raise RuntimeError(
        "No usable 5m candle endpoint. "
        + " || ".join(errors)
    )


# =========================================================
# ICHIMOKU CALCULATIONS
# =========================================================

def midpoint(candles, period):
    result = []

    for index in range(len(candles)):
        if index + 1 < period:
            result.append(None)
            continue

        window = candles[
            index + 1 - period:index + 1
        ]

        highest = max(
            candle["high"] for candle in window
        )

        lowest = min(
            candle["low"] for candle in window
        )

        result.append((highest + lowest) / 2.0)

    return result


def ichimoku_signal(candles):
    """
    Uses only completed candles.
    Ichimoku: Tenkan 9, Kijun 26, Senkou B 52.
    """

    if len(candles) < 60:
        return {
            "signal": "NONE",
            "reason": "Not enough candles"
        }

    # Ignore the most recent candle because it may still
    # be forming.
    candles = candles[:-1]

    if len(candles) < 52:
        return {
            "signal": "NONE",
            "reason": "Not enough closed candles"
        }

    tenkan = midpoint(candles, 9)
    kijun = midpoint(candles, 26)
    span_b = midpoint(candles, 52)

    index = len(candles) - 1

    price = candles[index]["close"]
    previous_price = candles[index - 1]["close"]

    t = tenkan[index]
    k = kijun[index]
    b = span_b[index]

    if t is None or k is None or b is None:
        return {
            "signal": "NONE",
            "reason": "Ichimoku values unavailable"
        }

    # Approximation of the cloud using current values.
    # This is a scanner signal, not a guarantee.
    span_a = (t + k) / 2.0
    cloud_top = max(span_a, b)
    cloud_bottom = min(span_a, b)

    bullish = (
        price > cloud_top
        and t > k
        and price > previous_price
    )

    bearish = (
        price < cloud_bottom
        and t < k
        and price < previous_price
    )

    if bullish:
        return {
            "signal": "BUY",
            "price": price,
            "tenkan": t,
            "kijun": k,
            "cloud_top": cloud_top,
            "cloud_bottom": cloud_bottom,
            "reason": "Price above cloud; Tenkan > Kijun"
        }

    if bearish:
        return {
            "signal": "SELL",
            "price": price,
            "tenkan": t,
            "kijun": k,
            "cloud_top": cloud_top,
            "cloud_bottom": cloud_bottom,
            "reason": "Price below cloud; Tenkan < Kijun"
        }

    return {
        "signal": "NONE",
        "price": price,
        "tenkan": t,
        "kijun": k,
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom,
        "reason": "Ichimoku conditions not met"
    }


# =========================================================
# MARKET ANALYSIS
# =========================================================

def analyse_market(item):
    symbol = normalize_symbol(item)

    result = {
        "symbol": symbol,
        "ready": False,
        "signal": "NONE",
        "error": ""
    }

    try:
        if not symbol:
            raise ValueError(
                "Market has no valid symbol field."
            )

        candles, endpoint = get_futures_candles(symbol)

        signal = ichimoku_signal(candles)

        result.update(signal)
        result["ready"] = True
        result["candles"] = len(candles)
        result["endpoint"] = endpoint

        print(
            "[MARKET OK]",
            symbol,
            "candles:",
            len(candles),
            "signal:",
            signal.get("signal"),
            "endpoint:",
            endpoint,
            flush=True
        )

    except Exception as exc:
        error = (
            type(exc).__name__
            + ": "
            + str(exc).replace("\n", " ")
        )[:700]

        result["error"] = error

        print(
            "[ANALYSIS ERROR]",
            symbol,
            error,
            flush=True
        )

    return result


# =========================================================
# MAIN
# =========================================================

def main():
    started = time.time()

    telegram_send(
        "🚀 "
        + VERSION
        + "\n"
        + "Futures Ichimoku scanner started."
        + "\n"
        + "Time: "
        + utc_now()
        + "\n"
        + "REAL TRADING: OFF"
    )

    try:
        markets = discover_markets()

    except Exception as exc:
        message = (
            "❌ ATI FUTURES MARKET DISCOVERY ERROR\n\n"
            + type(exc).__name__
            + ": "
            + str(exc)[:2500]
            + "\n\nTime: "
            + utc_now()
        )

        print(message, flush=True)
        telegram_send(message)
        return

    results = []

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(analyse_market, item)
            for item in markets
        ]

        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())

            except Exception as exc:
                results.append({
                    "symbol": "UNKNOWN",
                    "ready": False,
                    "signal": "NONE",
                    "error": (
                        type(exc).__name__
                        + ": "
                        + str(exc)[:300]
                    )
                })

    elapsed = time.time() - started

    ready = [
        result
        for result in results
        if result.get("ready")
    ]

    errors = [
        result
        for result in results
        if result.get("error")
    ]

    buy_signals = [
        result
        for result in ready
        if result.get("signal") == "BUY"
    ]

    sell_signals = [
        result
        for result in ready
        if result.get("signal") == "SELL"
    ]

    lines = [
        "💓 ATI FUTURES V14",
        "",
        "🕐 " + utc_now(),
        "",
        "📊 Markets: " + str(len(markets)),
        "📈 Ready: " + str(len(ready)),
        "🔥 BUY signals: " + str(len(buy_signals)),
        "🔻 SELL signals: " + str(len(sell_signals)),
        "❌ Errors: " + str(len(errors)),
        "⏱️ Scan: " + str(round(elapsed, 2)) + "s",
        "",
        "💵 Margin target: " + str(ORDER_USDT) + " USDT",
        "⚡ Requested leverage: " + str(LEVERAGE) + "x",
        "🔒 REAL TRADING: OFF",
        "",
        "⚠️ This version scans signals only."
    ]

    if buy_signals:
        lines.extend([
            "",
            "🟢 BUY CANDIDATES"
        ])

        for item in sorted(
            buy_signals,
            key=lambda x: x.get("symbol", "")
        )[:10]:

            lines.append(
                "• "
                + item["symbol"]
                + " | Price: "
                + str(round(item["price"], 8))
                + "\n  "
                + item.get("reason", "")
            )

    if sell_signals:
        lines.extend([
            "",
            "🔴 SELL CANDIDATES"
        ])

        for item in sorted(
            sell_signals,
            key=lambda x: x.get("symbol", "")
        )[:10]:

            lines.append(
                "• "
                + item["symbol"]
                + " | Price: "
                + str(round(item["price"], 8))
                + "\n  "
                + item.get("reason", "")
            )

    if not buy_signals and not sell_signals:
        lines.extend([
            "",
            "☁️ No confirmed Ichimoku signal this cycle."
        ])

    # Send exact diagnostic examples if markets fail.
    if errors:
        lines.extend([
            "",
            "🧪 ERROR SAMPLE"
        ])

        for item in errors[:3]:
            lines.append(
                "• "
                + item.get("symbol", "UNKNOWN")
                + "\n"
                + item.get("error", "Unknown error")[:650]
            )

    if not ready:
        lines.extend([
            "",
            "🚨 No market had usable candle data.",
            "The error samples above show why."
        ])

    report = "\n".join(lines)

    print(report, flush=True)
    telegram_send(report)


if __name__ == "__main__":
    main()
