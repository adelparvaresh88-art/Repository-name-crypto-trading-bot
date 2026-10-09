import os
import time
import requests
import concurrent.futures
from datetime import datetime, timezone

# =========================================================
# ATI FUTURES V15
# MARKET DISCOVERY FIX + ICHIMOKU 5M
# =========================================================

VERSION = "ATI FUTURES V15"

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

# SAFETY:
# This version does NOT place real orders.
LIVE_TRADING = False

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-Bot/15.0",
    "Accept": "application/json",
})


# =========================================================
# TELEGRAM
# =========================================================

def telegram_send(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:

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

def get_json(url, params=None):

    response = session.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# GENERIC LIST EXTRACTION
# =========================================================

def find_lists(data, depth=0):

    """
    Recursively searches nested dictionaries/lists
    for market-like lists.

    This avoids assuming a single exchangeInfo structure.
    """

    if depth > 5:
        return []

    found = []

    if isinstance(data, list):

        if data:
            found.append(data)

        for item in data[:20]:

            if isinstance(item, (dict, list)):

                found.extend(
                    find_lists(
                        item,
                        depth + 1
                    )
                )

    elif isinstance(data, dict):

        for key, value in data.items():

            if isinstance(value, (dict, list)):

                found.extend(
                    find_lists(
                        value,
                        depth + 1
                    )
                )

    return found


# =========================================================
# SYMBOL EXTRACTION
# =========================================================

def normalize_symbol(item):

    if isinstance(item, str):

        return item.strip().upper()

    if not isinstance(item, dict):

        return ""

    possible_keys = (
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
    )

    for key in possible_keys:

        value = item.get(key)

        if value is None:
            continue

        value = str(value).strip().upper()

        if value:
            return value

    return ""


def clean_symbol(symbol):

    symbol = str(symbol).strip().upper()

    symbol = symbol.replace(
        "/",
        ""
    )

    symbol = symbol.replace(
        "-",
        ""
    )

    symbol = symbol.replace(
        "_",
        ""
    )

    return symbol


# =========================================================
# MARKET ELIGIBILITY
# =========================================================

def is_usdt_market(item):

    symbol = normalize_symbol(item)

    if not symbol:
        return False

    clean = clean_symbol(symbol)

    # We need USDT quoted markets.
    if not clean.endswith("USDT"):
        return False

    # Avoid weird empty/base-only values.
    if len(clean) <= 4:
        return False

    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    if isinstance(item, dict):

        status_value = None

        for key in (
            "status",
            "state",
            "marketStatus",
            "tradingStatus",
        ):

            if key in item:

                status_value = item.get(key)

                break

        # IMPORTANT:
        # If status does not exist, DO NOT reject market.
        if status_value is not None:

            status = str(
                status_value
            ).strip().upper()

            disabled_values = (
                "CLOSED",
                "DISABLED",
                "OFF",
                "HALT",
                "HALTED",
                "BREAK",
                "INACTIVE",
                "0",
            )

            if status in disabled_values:

                return False

    # -----------------------------------------------------
    # CONTRACT TYPE
    # -----------------------------------------------------

    if isinstance(item, dict):

        contract_value = None

        for key in (
            "contractType",
            "contract_type",
            "contractTypeName",
            "type",
            "instrumentType",
        ):

            if key in item:

                contract_value = item.get(key)

                break

        # IMPORTANT:
        # If contract type does not exist,
        # DO NOT reject the market.
        if contract_value is not None:

            contract = str(
                contract_value
            ).strip().upper()

            # Reject obvious spot/non-futures types
            # only when explicitly reported.
            reject_types = (
                "SPOT",
                "MARGIN",
                "OPTION",
            )

            if contract in reject_types:

                return False

    return True


# =========================================================
# EXCHANGE INFO
# =========================================================

def discover_markets():

    paths = [
        "/r/fapi/v1/exchangeInfo",
        "/fapi/v1/exchangeInfo",
    ]

    errors = []

    diagnostic_samples = []

    for path in paths:

        url = BASE_URL + path

        try:

            data = get_json(url)

            print(
                "\n========== EXCHANGE INFO ==========",
                flush=True
            )

            print(
                "PATH:",
                path,
                flush=True
            )

            print(
                "TYPE:",
                type(data).__name__,
                flush=True
            )

            print(
                "RAW SAMPLE:",
                str(data)[:2000],
                flush=True
            )

            print(
                "===================================\n",
                flush=True
            )

            # -------------------------------------------------
            # Direct list
            # -------------------------------------------------

            candidate_lists = find_lists(data)

            # If root itself is a list, guarantee it is tested.
            if isinstance(data, list):

                candidate_lists.insert(
                    0,
                    data
                )

            # -------------------------------------------------
            # Find best market list
            # -------------------------------------------------

            best_markets = []
            best_score = -1

            for candidate in candidate_lists:

                if not isinstance(candidate, list):
                    continue

                score = 0
                valid_count = 0

                for item in candidate[:3000]:

                    symbol = normalize_symbol(item)

                    if symbol:

                        score += 1

                    if is_usdt_market(item):

                        valid_count += 1

                # Prefer lists containing USDT symbols.
                combined_score = (
                    valid_count * 10000
                    + score
                )

                if combined_score > best_score:

                    best_score = combined_score

                    best_markets = candidate

            # -------------------------------------------------
            # Extract USDT markets
            # -------------------------------------------------

            valid = []

            seen = set()

            for item in best_markets:

                symbol = normalize_symbol(item)

                if not symbol:
                    continue

                clean = clean_symbol(symbol)

                if clean in seen:
                    continue

                if not is_usdt_market(item):
                    continue

                seen.add(clean)

                # Preserve original item.
                if isinstance(item, dict):

                    copied = dict(item)

                    # Guarantee normalized symbol.
                    copied["symbol"] = clean

                    valid.append(copied)

                else:

                    valid.append({
                        "symbol": clean
                    })

            # -------------------------------------------------
            # Fallback recursive extraction
            # -------------------------------------------------

            if not valid:

                print(
                    "Primary market list produced 0 markets.",
                    flush=True
                )

                all_symbols = []

                def recursive_extract(obj):

                    if isinstance(obj, dict):

                        symbol = normalize_symbol(obj)

                        if symbol:

                            all_symbols.append(obj)

                        for value in obj.values():

                            if isinstance(
                                value,
                                (dict, list)
                            ):

                                recursive_extract(value)

                    elif isinstance(obj, list):

                        for value in obj:

                            if isinstance(
                                value,
                                (dict, list)
                            ):

                                recursive_extract(value)

                recursive_extract(data)

                for item in all_symbols:

                    symbol = normalize_symbol(item)

                    clean = clean_symbol(symbol)

                    if (
                        clean.endswith("USDT")
                        and clean not in seen
                        and is_usdt_market(item)
                    ):

                        seen.add(clean)

                        copied = dict(item)

                        copied["symbol"] = clean

                        valid.append(copied)

            # -------------------------------------------------
            # SUCCESS
            # -------------------------------------------------

            if valid:

                valid.sort(
                    key=lambda x:
                    normalize_symbol(x)
                )

                print(
                    "====================================",
                    flush=True
                )

                print(
                    "MARKET DISCOVERY SUCCESS",
                    flush=True
                )

                print(
                    "Endpoint:",
                    path,
                    flush=True
                )

                print(
                    "Markets:",
                    len(valid),
                    flush=True
                )

                print(
                    "Symbols:",
                    ", ".join(
                        normalize_symbol(x)
                        for x in valid[:30]
                    ),
                    flush=True
                )

                print(
                    "====================================",
                    flush=True
                )

                return valid[:SCAN_UNIVERSE]

            # -------------------------------------------------
            # Diagnostic sample
            # -------------------------------------------------

            sample = str(data)[:1800]

            diagnostic_samples.append(
                path
                + "\n"
                + sample
            )

            raise ValueError(
                "exchangeInfo returned data, "
                "but no USDT Futures markets "
                "could be identified."
            )

        except Exception as exc:

            error = (
                path
                + " -> "
                + type(exc).__name__
                + ": "
                + str(exc).replace(
                    "\n",
                    " "
                )[:500]
            )

            errors.append(error)

            print(
                "[MARKET ERROR]",
                error,
                flush=True
            )

    # ---------------------------------------------------------
    # FINAL FAILURE
    # ---------------------------------------------------------

    diagnostic_text = ""

    if diagnostic_samples:

        diagnostic_text = (
            "\n\nRAW API SAMPLE:\n"
            + diagnostic_samples[0][:3500]
        )

    raise RuntimeError(
        "Market discovery failed:\n"
        + "\n".join(errors)
        + diagnostic_text
    )


# =========================================================
# CANDLE PARSING
# =========================================================

def parse_candle_array(row):

    if not isinstance(
        row,
        (list, tuple)
    ):
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

    except (
        TypeError,
        ValueError
    ):

        return None


def parse_candle_dict(row):

    if not isinstance(row, dict):
        return None

    try:

        time_value = (
            row.get("openTime")
            or row.get("open_time")
            or row.get("timestamp")
            or row.get("time")
            or row.get("t")
            or 0
        )

        open_value = (
            row.get("open")
            if row.get("open") is not None
            else row.get("o")
        )

        high_value = (
            row.get("high")
            if row.get("high") is not None
            else row.get("h")
        )

        low_value = (
            row.get("low")
            if row.get("low") is not None
            else row.get("l")
        )

        close_value = (
            row.get("close")
            if row.get("close") is not None
            else row.get("c")
        )

        volume_value = (
            row.get("volume")
            if row.get("volume") is not None
            else row.get("v", 0)
        )

        return {
            "time": int(float(time_value)),
            "open": float(open_value),
            "high": float(high_value),
            "low": float(low_value),
            "close": float(close_value),
            "volume": float(volume_value),
        }

    except (
        TypeError,
        ValueError
    ):

        return None


def normalize_candles(data):

    if isinstance(data, dict):

        for key in (
            "data",
            "result",
            "klines",
            "candles",
            "rows",
            "list",
        ):

            if key in data:

                return normalize_candles(
                    data[key]
                )

        raise ValueError(
            "Unknown candle dictionary format: "
            + str(
                list(data.keys())
            )[:500]
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

        if candle is None:
            continue

        if (
            candle["open"] > 0
            and candle["high"] > 0
            and candle["low"] > 0
            and candle["close"] > 0
        ):

            candles.append(candle)

    candles.sort(
        key=lambda x:
        x["time"]
    )

    unique = {}

    for candle in candles:

        unique[
            candle["time"]
        ] = candle

    return list(
        unique.values()
    )


# =========================================================
# FUTURES CANDLES
# =========================================================

def get_futures_candles(symbol):

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
        "limit": KLINE_LIMIT,
    }

    for path in paths:

        try:

            data = get_json(
                BASE_URL + path,
                params=params
            )

            candles = normalize_candles(
                data
            )

            if len(candles) < 60:

                raise ValueError(
                    "Only "
                    + str(len(candles))
                    + " valid candles returned."
                )

            return candles, path

        except Exception as exc:

            errors.append(
                path
                + " -> "
                + type(exc).__name__
                + ": "
                + str(exc).replace(
                    "\n",
                    " "
                )[:250]
            )

    raise RuntimeError(
        "No usable 5m candle endpoint. "
        + " || ".join(errors)
    )


# =========================================================
# ICHIMOKU
# =========================================================

def midpoint(candles, period):

    result = []

    for index in range(
        len(candles)
    ):

        if index + 1 < period:

            result.append(None)

            continue

        window = candles[
            index + 1 - period:
            index + 1
        ]

        highest = max(
            x["high"]
            for x in window
        )

        lowest = min(
            x["low"]
            for x in window
        )

        result.append(
            (highest + lowest) / 2.0
        )

    return result


def ichimoku_signal(candles):

    if len(candles) < 60:

        return {
            "signal": "NONE",
            "reason": "Not enough candles"
        }

    # Ignore currently forming candle.
    closed = candles[:-1]

    if len(closed) < 52:

        return {
            "signal": "NONE",
            "reason": "Not enough closed candles"
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

    index = len(closed) - 1

    price = closed[index]["close"]

    previous_price = closed[
        index - 1
    ]["close"]

    t = tenkan[index]
    k = kijun[index]
    b = span_b[index]

    if (
        t is None
        or k is None
        or b is None
    ):

        return {
            "signal": "NONE",
            "reason": "Ichimoku values unavailable"
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
                "Price above cloud; "
                "Tenkan > Kijun"
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
                "Price below cloud; "
                "Tenkan < Kijun"
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
# ANALYSE
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
                "Market has no symbol."
            )

        candles, endpoint = (
            get_futures_candles(
                symbol
            )
        )

        signal = ichimoku_signal(
            candles
        )

        result.update(
            signal
        )

        result["ready"] = True
        result["candles"] = len(
            candles
        )

        result["endpoint"] = endpoint

        print(
            "[MARKET OK]",
            symbol,
            "candles:",
            len(candles),
            "signal:",
            signal.get("signal"),
            flush=True
        )

    except Exception as exc:

        error = (
            type(exc).__name__
            + ": "
            + str(exc).replace(
                "\n",
                " "
            )
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
        "🚀 ATI FUTURES V15\n"
        "Market Discovery FIX\n\n"
        "☁️ Ichimoku 9 / 26 / 52\n"
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

    try:

        markets = discover_markets()

    except Exception as exc:

        message = (
            "❌ ATI FUTURES MARKET DISCOVERY ERROR\n\n"
            + type(exc).__name__
            + ":\n"
            + str(exc)[:5000]
            + "\n\nTime: "
            + utc_now()
        )

        print(
            message,
            flush=True
        )

        telegram_send(
            message
        )

        return

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
        x
        for x in results
        if x.get("ready")
    ]

    errors = [
        x
        for x in results
        if x.get("error")
    ]

    buys = [
        x
        for x in ready
        if x.get("signal") == "BUY"
    ]

    sells = [
        x
        for x in ready
        if x.get("signal") == "SELL"
    ]

    lines = [

        "💓 ATI FUTURES V15",

        "",

        "🕐 "
        + utc_now(),

        "",

        "📊 Markets: "
        + str(len(markets)),

        "📈 Ready: "
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
                + " | "
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
                + " | "
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
    # NONE
    # -----------------------------------------------------

    if (
        not buys
        and not sells
    ):

        lines.extend([
            "",
            "☁️ No confirmed Ichimoku signal."
        ])

    # -----------------------------------------------------
    # ERRORS
    # -----------------------------------------------------

    if errors:

        lines.extend([
            "",
            "🧪 ERROR SAMPLE"
        ])

        for item in errors[:3]:

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
                )[:600]
            )

    # -----------------------------------------------------
    # FINAL
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
