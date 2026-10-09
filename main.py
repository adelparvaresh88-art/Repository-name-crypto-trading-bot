import os
import time
import requests
import concurrent.futures
from datetime import datetime, timezone

# =========================================================
# ATI FUTURES V16
# FUTURES TRADES -> 5M CANDLES -> ICHIMOKU
# =========================================================

VERSION = "ATI FUTURES V16"

BASE_URL = os.getenv(
    "BASE_URL",
    "https://api1.tabdeal.org"
).rstrip("/")

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)

SCAN_UNIVERSE = int(
    os.getenv("SCAN_UNIVERSE", "75")
)

MAX_WORKERS = int(
    os.getenv("MAX_WORKERS", "20")
)

REQUEST_TIMEOUT = int(
    os.getenv("REQUEST_TIMEOUT", "8")
)

TRADE_LIMIT = int(
    os.getenv("TRADE_LIMIT", "5000")
)

INTERVAL_SECONDS = 300

ORDER_USDT = float(
    os.getenv("ORDER_USDT", "2")
)

LEVERAGE = int(
    os.getenv("LEVERAGE", "3")
)

# =========================================================
# SAFETY
# =========================================================

# DO NOT CHANGE THIS YET.
# This version only scans.
LIVE_TRADING = False


# =========================================================
# SESSION
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-Bot/16.0",
    "Accept": "application/json",
})


# =========================================================
# TELEGRAM
# =========================================================

def telegram_send(message):

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):

        print(
            "Telegram secrets are missing.",
            flush=True
        )

        print(
            message,
            flush=True
        )

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

        print(
            "Telegram exception:",
            repr(exc),
            flush=True
        )

        return False


# =========================================================
# TIME
# =========================================================

def utc_now():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# =========================================================
# HTTP
# =========================================================

def get_json(
    path,
    params=None,
    timeout=None
):

    if timeout is None:
        timeout = REQUEST_TIMEOUT

    url = (
        BASE_URL
        + path
    )

    response = session.get(
        url,
        params=params,
        timeout=timeout
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# SYMBOL
# =========================================================

def normalize_symbol(item):

    if isinstance(
        item,
        str
    ):

        return item.strip().upper()

    if not isinstance(
        item,
        dict
    ):

        return ""

    for key in (
        "symbol",
        "s",
        "market",
        "pair",
        "name",
        "instrument",
        "instrumentId",
        "instrument_id",
        "contract",
        "code",
    ):

        value = item.get(key)

        if value is None:
            continue

        value = str(
            value
        ).strip().upper()

        if value:
            return value

    return ""


def clean_symbol(symbol):

    return (
        str(symbol)
        .strip()
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
    )


# =========================================================
# EXCHANGE INFO UNWRAP
# =========================================================

def collect_lists(
    data,
    depth=0
):

    if depth > 6:
        return []

    result = []

    if isinstance(
        data,
        list
    ):

        result.append(
            data
        )

        for item in data[:100]:

            if isinstance(
                item,
                (dict, list)
            ):

                result.extend(
                    collect_lists(
                        item,
                        depth + 1
                    )
                )

    elif isinstance(
        data,
        dict
    ):

        for value in data.values():

            if isinstance(
                value,
                (dict, list)
            ):

                result.extend(
                    collect_lists(
                        value,
                        depth + 1
                    )
                )

    return result


# =========================================================
# MARKET FILTER
# =========================================================

def is_usdt_market(item):

    symbol = clean_symbol(
        normalize_symbol(item)
    )

    if not symbol:
        return False

    if not symbol.endswith(
        "USDT"
    ):
        return False

    if len(symbol) <= 4:
        return False

    if isinstance(
        item,
        dict
    ):

        status = None

        for key in (
            "status",
            "state",
            "marketStatus",
            "tradingStatus",
        ):

            if key in item:

                status = item.get(
                    key
                )

                break

        if status is not None:

            status = str(
                status
            ).upper()

            if status in (
                "CLOSED",
                "DISABLED",
                "HALTED",
                "HALT",
                "OFF",
                "INACTIVE",
                "0",
            ):

                return False

        contract = None

        for key in (
            "contractType",
            "contract_type",
            "type",
            "instrumentType",
        ):

            if key in item:

                contract = item.get(
                    key
                )

                break

        if contract is not None:

            contract = str(
                contract
            ).upper()

            if contract in (
                "SPOT",
                "MARGIN",
                "OPTION",
            ):

                return False

    return True


# =========================================================
# MARKET DISCOVERY
# =========================================================

def discover_markets():

    paths = [
        "/r/fapi/v1/exchangeInfo",
        "/fapi/v1/exchangeInfo",
    ]

    errors = []

    for path in paths:

        try:

            data = get_json(
                path
            )

            lists = collect_lists(
                data
            )

            best = []
            best_count = -1

            for candidate in lists:

                count = 0

                for item in candidate:

                    if is_usdt_market(
                        item
                    ):

                        count += 1

                if count > best_count:

                    best_count = count
                    best = candidate

            markets = []

            seen = set()

            for item in best:

                if not is_usdt_market(
                    item
                ):

                    continue

                symbol = clean_symbol(
                    normalize_symbol(item)
                )

                if (
                    not symbol
                    or symbol in seen
                ):

                    continue

                seen.add(
                    symbol
                )

                if isinstance(
                    item,
                    dict
                ):

                    copied = dict(
                        item
                    )

                    copied[
                        "symbol"
                    ] = symbol

                    markets.append(
                        copied
                    )

                else:

                    markets.append({
                        "symbol": symbol
                    })

            if not markets:

                raise ValueError(
                    "No USDT Futures markets."
                )

            markets.sort(
                key=lambda x:
                normalize_symbol(x)
            )

            print(
                "MARKET DISCOVERY OK",
                path,
                "markets:",
                len(markets),
                flush=True
            )

            print(
                "FIRST SYMBOLS:",
                ", ".join(
                    normalize_symbol(x)
                    for x in markets[:20]
                ),
                flush=True
            )

            return markets[
                :SCAN_UNIVERSE
            ]

        except Exception as exc:

            error = (
                path
                + " -> "
                + type(exc).__name__
                + ": "
                + str(exc)[:500]
            )

            errors.append(
                error
            )

            print(
                "[DISCOVERY ERROR]",
                error,
                flush=True
            )

    raise RuntimeError(
        "Market discovery failed: "
        + " || ".join(errors)
    )


# =========================================================
# FUTURES TRADES
# =========================================================

def get_futures_trades(
    symbol
):

    """
    IMPORTANT:
    V15 used /klines and got HTTP 404.

    V16 does NOT use klines.

    We try the public Futures trades endpoint.
    """

    paths = [
        "/r/fapi/v1/trades",
        "/fapi/v1/trades",
    ]

    errors = []

    params = {
        "symbol": symbol,
        "limit": TRADE_LIMIT,
    }

    for path in paths:

        try:

            data = get_json(
                path,
                params=params
            )

            trades = normalize_trades(
                data
            )

            if len(trades) < 20:

                raise ValueError(
                    "Only "
                    + str(len(trades))
                    + " trades returned."
                )

            return trades, path

        except Exception as exc:

            errors.append(
                path
                + " -> "
                + type(exc).__name__
                + ": "
                + str(exc)[:300]
            )

    raise RuntimeError(
        "No usable Futures trades endpoint. "
        + " || ".join(errors)
    )


# =========================================================
# TRADE NORMALIZATION
# =========================================================

def normalize_trades(
    data
):

    if isinstance(
        data,
        dict
    ):

        for key in (
            "data",
            "result",
            "trades",
            "rows",
            "list",
        ):

            if key in data:

                return normalize_trades(
                    data[key]
                )

        raise ValueError(
            "Unknown trades response: "
            + str(
                list(data.keys())
            )[:500]
        )

    if not isinstance(
        data,
        list
    ):

        raise ValueError(
            "Trades response is not list."
        )

    result = []

    for row in data:

        if not isinstance(
            row,
            dict
        ):

            continue

        try:

            price = (
                row.get("price")
                or row.get("p")
            )

            qty = (
                row.get("qty")
                or row.get("quantity")
                or row.get("q")
                or 0
            )

            timestamp = (
                row.get("time")
                or row.get("timestamp")
                or row.get("T")
                or row.get("tradeTime")
            )

            if (
                price is None
                or timestamp is None
            ):

                continue

            timestamp = int(
                float(timestamp)
            )

            # Some APIs may return seconds.
            if timestamp < 10_000_000_000:

                timestamp *= 1000

            result.append({
                "time": timestamp,
                "price": float(price),
                "qty": float(qty),
            })

        except (
            TypeError,
            ValueError
        ):

            continue

    result.sort(
        key=lambda x:
        x["time"]
    )

    return result


# =========================================================
# TRADES -> 5M CANDLES
# =========================================================

def trades_to_5m(
    trades
):

    candles = {}

    for trade in trades:

        timestamp = int(
            trade["time"]
        )

        bucket = (
            timestamp
            // 300000
        ) * 300000

        price = float(
            trade["price"]
        )

        qty = float(
            trade.get(
                "qty",
                0
            )
        )

        if price <= 0:
            continue

        if bucket not in candles:

            candles[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
            }

        else:

            candle = candles[
                bucket
            ]

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

    result = list(
        candles.values()
    )

    result.sort(
        key=lambda x:
        x["time"]
    )

    return result


# =========================================================
# ICHIMOKU MIDPOINT
# =========================================================

def midpoint(
    candles,
    period
):

    values = []

    for i in range(
        len(candles)
    ):

        if i + 1 < period:

            values.append(
                None
            )

            continue

        window = candles[
            i + 1 - period:
            i + 1
        ]

        highest = max(
            x["high"]
            for x in window
        )

        lowest = min(
            x["low"]
            for x in window
        )

        values.append(
            (
                highest
                + lowest
            ) / 2.0
        )

    return values


# =========================================================
# ICHIMOKU SIGNAL
# =========================================================

def ichimoku_signal(
    candles
):

    # Need at least 60 completed
    # candles after removing current.
    if len(candles) < 61:

        return {
            "signal": "NONE",
            "reason":
                "Need at least 61 "
                "5m candles."
        }

    # Remove current forming candle.
    closed = candles[
        :-1
    ]

    if len(closed) < 60:

        return {
            "signal": "NONE",
            "reason":
                "Not enough closed "
                "5m candles."
        }

    tenkan = midpoint(
        closed,
        9
    )

    kijun = midpoint(
        closed,
        26
    )

    span_b = midpoint(
        closed,
        52
    )

    i = len(
        closed
    ) - 1

    price = closed[
        i
    ]["close"]

    previous_price = closed[
        i - 1
    ]["close"]

    t = tenkan[
        i
    ]

    k = kijun[
        i
    ]

    b = span_b[
        i
    ]

    if (
        t is None
        or k is None
        or b is None
    ):

        return {
            "signal": "NONE",
            "reason":
                "Ichimoku unavailable."
        }

    span_a = (
        t + k
    ) / 2.0

    cloud_top = max(
        span_a,
        b
    )

    cloud_bottom = min(
        span_a,
        b
    )

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
            "reason":
                "Price above cloud | "
                "Tenkan > Kijun | "
                "5M momentum UP"
        }

    if bearish:

        return {
            "signal": "SELL",
            "price": price,
            "tenkan": t,
            "kijun": k,
            "cloud_top": cloud_top,
            "cloud_bottom": cloud_bottom,
            "reason":
                "Price below cloud | "
                "Tenkan < Kijun | "
                "5M momentum DOWN"
        }

    return {
        "signal": "NONE",
        "price": price,
        "tenkan": t,
        "kijun": k,
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom,
        "reason":
            "Ichimoku conditions not met"
    }


# =========================================================
# MARKET ANALYSIS
# =========================================================

def analyse_market(
    item
):

    symbol = normalize_symbol(
        item
    )

    result = {
        "symbol": symbol,
        "ready": False,
        "signal": "NONE",
        "error": "",
    }

    try:

        trades, endpoint = (
            get_futures_trades(
                symbol
            )
        )

        candles = trades_to_5m(
            trades
        )

        if len(candles) < 61:

            raise RuntimeError(
                "Trades available: "
                + str(len(trades))
                + " | 5M candles built: "
                + str(len(candles))
                + " | Need >= 61."
            )

        signal = ichimoku_signal(
            candles
        )

        result.update(
            signal
        )

        result["ready"] = True

        result["trades"] = len(
            trades
        )

        result["candles"] = len(
            candles
        )

        result["endpoint"] = endpoint

        print(
            "[OK]",
            symbol,
            "| trades:",
            len(trades),
            "| 5M:",
            len(candles),
            "| signal:",
            signal.get("signal"),
            flush=True
        )

    except Exception as exc:

        result["error"] = (
            type(exc).__name__
            + ": "
            + str(exc)[:650]
        )

        print(
            "[ERROR]",
            symbol,
            result["error"],
            flush=True
        )

    return result


# =========================================================
# MAIN
# =========================================================

def main():

    started = time.time()

    telegram_send(
        "🚀 ATI FUTURES V16\n"
        "Trades → 5M → Ichimoku\n\n"
        "☁️ Ichimoku: 9 / 26 / 52\n"
        "⏱️ Timeframe: 5M\n"
        "💵 Margin target: "
        + str(ORDER_USDT)
        + " USDT\n"
        "⚡ Leverage: "
        + str(LEVERAGE)
        + "x\n"
        "🔒 REAL TRADING: OFF\n"
        "🕐 "
        + utc_now()
    )

    # -----------------------------------------------------
    # DISCOVERY
    # -----------------------------------------------------

    try:

        markets = discover_markets()

    except Exception as exc:

        message = (
            "❌ ATI FUTURES V16\n\n"
            "MARKET DISCOVERY FAILED\n\n"
            + type(exc).__name__
            + ": "
            + str(exc)[:5000]
        )

        print(
            message,
            flush=True
        )

        telegram_send(
            message
        )

        return

    # -----------------------------------------------------
    # ANALYSIS
    # -----------------------------------------------------

    results = []

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                analyse_market,
                item
            )
            for item in markets
        ]

        for future in concurrent.futures.as_completed(
            futures
        ):

            try:

                results.append(
                    future.result()
                )

            except Exception as exc:

                results.append({
                    "symbol": "UNKNOWN",
                    "ready": False,
                    "signal": "NONE",
                    "error":
                        type(exc).__name__
                        + ": "
                        + str(exc)[:300]
                })

    elapsed = (
        time.time()
        - started
    )

    ready = [
        x for x in results
        if x.get("ready")
    ]

    errors = [
        x for x in results
        if x.get("error")
    ]

    buys = [
        x for x in ready
        if x.get("signal")
        == "BUY"
    ]

    sells = [
        x for x in ready
        if x.get("signal")
        == "SELL"
    ]

    lines = [

        "💓 ATI FUTURES V16",

        "",

        "🕐 "
        + utc_now(),

        "",

        "📊 Markets: "
        + str(len(markets)),

        "📈 5M Ready: "
        + str(len(ready)),

        "🟢 BUY: "
        + str(len(buys)),

        "🔴 SELL: "
        + str(len(sells)),

        "❌ Errors: "
        + str(len(errors)),

        "⏱️ Scan: "
        + str(round(
            elapsed,
            2
        ))
        + "s",

        "",

        "💵 ORDER: "
        + str(ORDER_USDT)
        + " USDT",

        "⚡ LEVERAGE: "
        + str(LEVERAGE)
        + "x",

        "🔒 REAL: OFF",
    ]

    # -----------------------------------------------------
    # BUY
    # -----------------------------------------------------

    if buys:

        lines.extend([
            "",
            "🟢 BUY CANDIDATES"
        ])

        for item in sorted(
            buys,
            key=lambda x:
            x.get(
                "symbol",
                ""
            )
        )[:10]:

            lines.append(
                "• "
                + item["symbol"]
                + " | Price: "
                + str(
                    round(
                        item["price"],
                        8
                    )
                )
                + "\n  "
                + item.get(
                    "reason",
                    ""
                )
            )

    # -----------------------------------------------------
    # SELL
    # -----------------------------------------------------

    if sells:

        lines.extend([
            "",
            "🔴 SELL CANDIDATES"
        ])

        for item in sorted(
            sells,
            key=lambda x:
            x.get(
                "symbol",
                ""
            )
        )[:10]:

            lines.append(
                "• "
                + item["symbol"]
                + " | Price: "
                + str(
                    round(
                        item["price"],
                        8
                    )
                )
                + "\n  "
                + item.get(
                    "reason",
                    ""
                )
            )

    # -----------------------------------------------------
    # NO SIGNAL
    # -----------------------------------------------------

    if (
        not buys
        and not sells
    ):

        lines.extend([
            "",
            "☁️ No confirmed "
            "Ichimoku signal."
        ])

    # -----------------------------------------------------
    # ERRORS
    # -----------------------------------------------------

    if errors:

        lines.extend([
            "",
            "🧪 ERROR SAMPLE"
        ])

        for item in errors[:5]:

            lines.append(
                "• "
                + item.get(
                    "symbol",
                    "UNKNOWN"
                )
                + "\n"
                + item.get(
                    "error",
                    "Unknown error"
                )[:700]
            )

    # -----------------------------------------------------
    # REPORT
    # -----------------------------------------------------

    report = "\n".join(
        lines
    )

    print(
        report,
        flush=True
    )

    telegram_send(
        report
    )


# =========================================================
# ENTRY
# =========================================================

if __name__ == "__main__":

    main()
