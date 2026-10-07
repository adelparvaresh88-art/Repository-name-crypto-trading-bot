import os
import time
import math
import hmac
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode

import requests


# ============================================================
# ATI FUTURES V7.4
# ROBUST CONNECTION + FAST ICHIMOKU
# ============================================================

API_BASE = "https://api1.tabdeal.org"

PUBLIC_BASE = API_BASE + "/r/fapi/v1/"
PRIVATE_BASE = API_BASE + "/r/fapi/v3/"
WRITE_BASE = API_BASE + "/fapi/v1/"

TIMEFRAME = "5m"
KLINE_LIMIT = 100

# تعداد همزمان درخواست‌ها
MAX_WORKERS = 8

# زمان‌بندی
SCAN_INTERVAL = 300

# شبکه
CONNECT_TIMEOUT = 4
READ_TIMEOUT = 8

MAX_RETRIES = 2
RETRY_DELAY = 0.25

# Futures
LEVERAGE = 3

ORDER_USDT = float(
    os.getenv(
        "ORDER_QTY",
        "2"
    )
)

MAX_NEW_TRADES = 1

# SL / TP
SL_PCT = 0.010
TP_PCT = 0.020

# Ichimoku
TENKAN_N = 9
KIJUN_N = 26
SENKOU_B_N = 52

# Signal
MIN_SCORE = 5.0
MAX_KIJUN_DISTANCE = 0.025

# Real trading
LIVE_TRADING = (
    os.getenv(
        "LIVE_TRADING",
        "true"
    )
    .strip()
    .lower()
    in (
        "1",
        "true",
        "yes",
        "on"
    )
)

# ایمنی سفارش
BUY_LOCK = False


# ============================================================
# ENVIRONMENT
# ============================================================

API_KEY = (
    os.getenv("TABDIL_API_KEY")
    or
    os.getenv("TABDEAL_API_KEY")
    or
    ""
)

API_SECRET = (
    os.getenv("TABDIL_API_SECRET")
    or
    os.getenv("TABDEAL_API_SECRET")
    or
    ""
)

TG_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TG_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


# ============================================================
# GLOBAL
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-FUTURES-V7.4",
    "Accept": "application/json",
    "Connection": "keep-alive"
})

print_lock = threading.Lock()


# ============================================================
# LOG
# ============================================================

def log(message):

    with print_lock:
        print(
            message,
            flush=True
        )


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):

    if not TG_TOKEN or not TG_CHAT_ID:
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TG_TOKEN}/sendMessage"
    )

    try:

        response = session.post(
            url,
            data={
                "chat_id": TG_CHAT_ID,
                "text": message
            },
            timeout=(
                CONNECT_TIMEOUT,
                READ_TIMEOUT
            )
        )

        return response.ok

    except Exception as exc:

        log(
            "Telegram error: "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        return False


# ============================================================
# NETWORK ERROR CLASS
# ============================================================

class ApiError(Exception):

    def __init__(
        self,
        message,
        status=None,
        kind="unknown"
    ):

        super().__init__(message)

        self.status = status
        self.kind = kind


# ============================================================
# PUBLIC REQUEST
# ============================================================

def public_get(
    path,
    params=None
):

    last_error = None

    url = (
        PUBLIC_BASE
        + path.lstrip("/")
    )

    for attempt in range(
        MAX_RETRIES + 1
    ):

        try:

            response = session.get(
                url,
                params=params,
                timeout=(
                    CONNECT_TIMEOUT,
                    READ_TIMEOUT
                )
            )

            status = response.status_code

            if status == 429:

                last_error = ApiError(
                    "HTTP 429 rate limited",
                    status=429,
                    kind="rate_limit"
                )

                if attempt < MAX_RETRIES:

                    time.sleep(
                        RETRY_DELAY
                        * (attempt + 1)
                    )

                    continue

                raise last_error

            if status >= 500:

                last_error = ApiError(
                    f"HTTP {status}",
                    status=status,
                    kind="server"
                )

                if attempt < MAX_RETRIES:

                    time.sleep(
                        RETRY_DELAY
                        * (attempt + 1)
                    )

                    continue

                raise last_error

            if not response.ok:

                raise ApiError(
                    (
                        f"HTTP {status}: "
                        f"{response.text[:200]}"
                    ),
                    status=status,
                    kind="http"
                )

            try:

                return response.json()

            except Exception:

                raise ApiError(
                    "Invalid JSON response",
                    status=status,
                    kind="json"
                )

        except requests.exceptions.ConnectTimeout as exc:

            last_error = ApiError(
                "CONNECT TIMEOUT",
                kind="connect_timeout"
            )

        except requests.exceptions.ReadTimeout as exc:

            last_error = ApiError(
                "READ TIMEOUT",
                kind="read_timeout"
            )

        except requests.exceptions.ConnectionError as exc:

            last_error = ApiError(
                "CONNECTION ERROR",
                kind="connection"
            )

        except ApiError as exc:

            last_error = exc

            if exc.kind in (
                "rate_limit",
                "server",
                "connect_timeout",
                "read_timeout",
                "connection"
            ):
                pass
            else:
                raise

        except Exception as exc:

            last_error = ApiError(
                str(exc),
                kind="unknown"
            )

        if attempt < MAX_RETRIES:

            time.sleep(
                RETRY_DELAY
                * (attempt + 1)
            )

    if last_error:

        raise last_error

    raise ApiError(
        "Unknown public API failure"
    )


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(
    method,
    base,
    path,
    params=None
):

    if not API_KEY or not API_SECRET:

        raise ApiError(
            "API credentials missing",
            kind="auth"
        )

    payload = dict(
        params or {}
    )

    payload["timestamp"] = int(
        time.time() * 1000
    )

    payload.setdefault(
        "recvWindow",
        5000
    )

    query = urlencode(
        payload,
        doseq=True
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    url = (
        base
        + path.lstrip("/")
        + "?"
        + query
        + "&signature="
        + signature
    )

    try:

        response = session.request(
            method,
            url,
            headers={
                "X-MBX-APIKEY": API_KEY
            },
            timeout=(
                CONNECT_TIMEOUT,
                READ_TIMEOUT
            )
        )

    except requests.exceptions.ConnectTimeout:

        raise ApiError(
            "PRIVATE CONNECT TIMEOUT",
            kind="connect_timeout"
        )

    except requests.exceptions.ReadTimeout:

        raise ApiError(
            "PRIVATE READ TIMEOUT",
            kind="read_timeout"
        )

    except requests.exceptions.ConnectionError:

        raise ApiError(
            "PRIVATE CONNECTION ERROR",
            kind="connection"
        )

    except Exception as exc:

        raise ApiError(
            str(exc),
            kind="unknown"
        )

    if not response.ok:

        raise ApiError(
            (
                f"HTTP {response.status_code}: "
                f"{response.text[:400]}"
            ),
            status=response.status_code,
            kind="http"
        )

    try:

        return response.json()

    except Exception:

        raise ApiError(
            "Private API returned invalid JSON",
            kind="json"
        )


# ============================================================
# PRIVATE API
# ============================================================

def private_get(
    path,
    params=None
):

    return signed_request(
        "GET",
        PRIVATE_BASE,
        path,
        params
    )


def private_post(
    path,
    params=None
):

    return signed_request(
        "POST",
        WRITE_BASE,
        path,
        params
    )


# ============================================================
# FORMAT
# ============================================================

def fmt(
    value,
    decimals=12
):

    return (
        f"{value:.{decimals}f}"
        .rstrip("0")
        .rstrip(".")
    )


def floor_step(
    value,
    step
):

    if step <= 0:
        return value

    return (
        math.floor(
            value / step
        )
        * step
    )


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    return public_get(
        "exchangeInfo"
    )


def get_symbols():

    data = get_exchange_info()

    symbols = []

    for item in data.get(
        "symbols",
        []
    ):

        symbol = item.get(
            "symbol",
            ""
        )

        status = str(
            item.get(
                "status",
                ""
            )
        ).upper()

        quote = str(
            item.get(
                "quoteAsset",
                ""
            )
        ).upper()

        contract = str(
            item.get(
                "contractType",
                ""
            )
        ).upper()

        if status != "TRADING":
            continue

        if quote != "USDT":
            continue

        if contract and contract not in (
            "PERPETUAL",
            "PERPETUAL_CONTRACT"
        ):
            continue

        symbols.append(
            symbol
        )

    return sorted(
        set(symbols)
    )


def get_filters():

    data = get_exchange_info()

    result = {}

    for item in data.get(
        "symbols",
        []
    ):

        symbol = item.get(
            "symbol"
        )

        if not symbol:
            continue

        info = {
            "step": 0.0,
            "min_qty": 0.0,
            "tick": 0.0,
            "min_notional": 0.0
        }

        for f in item.get(
            "filters",
            []
        ):

            typ = f.get(
                "filterType"
            )

            if typ == "LOT_SIZE":

                info["step"] = float(
                    f.get(
                        "stepSize",
                        0
                    )
                    or 0
                )

                info["min_qty"] = float(
                    f.get(
                        "minQty",
                        0
                    )
                    or 0
                )

            elif typ == "PRICE_FILTER":

                info["tick"] = float(
                    f.get(
                        "tickSize",
                        0
                    )
                    or 0
                )

            elif typ in (
                "MIN_NOTIONAL",
                "NOTIONAL"
            ):

                info["min_notional"] = float(
                    f.get(
                        "notional",
                        f.get(
                            "minNotional",
                            0
                        )
                    )
                    or 0
                )

        result[symbol] = info

    return result


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol
):

    return public_get(
        "klines",
        {
            "symbol": symbol,
            "interval": TIMEFRAME,
            "limit": KLINE_LIMIT
        }
    )


def parse_klines(
    data
):

    candles = []

    if not isinstance(
        data,
        list
    ):
        return candles

    for row in data:

        if len(row) < 6:
            continue

        try:

            candles.append({
                "t": int(row[0]),
                "o": float(row[1]),
                "h": float(row[2]),
                "l": float(row[3]),
                "c": float(row[4]),
                "v": float(row[5])
            })

        except Exception:

            continue

    return candles


# ============================================================
# ICHIMOKU
# ============================================================

def midline(
    candles,
    period
):

    if len(candles) < period:
        return None

    part = candles[-period:]

    high = max(
        x["h"]
        for x in part
    )

    low = min(
        x["l"]
        for x in part
    )

    return (
        high + low
    ) / 2.0


def calculate_ichimoku(
    candles
):

    if len(candles) < 60:
        return None

    # آخرین کندل ممکن است هنوز باز باشد
    closed = candles[:-1]

    if len(closed) < (
        SENKOU_B_N + 2
    ):
        return None

    tenkan = midline(
        closed,
        TENKAN_N
    )

    kijun = midline(
        closed,
        KIJUN_N
    )

    span_b = midline(
        closed,
        SENKOU_B_N
    )

    if (
        tenkan is None
        or kijun is None
        or span_b is None
    ):
        return None

    span_a = (
        tenkan + kijun
    ) / 2.0

    prev_tenkan = midline(
        closed[:-1],
        TENKAN_N
    )

    prev_kijun = midline(
        closed[:-1],
        KIJUN_N
    )

    price = closed[-1]["c"]

    top = max(
        span_a,
        span_b
    )

    bottom = min(
        span_a,
        span_b
    )

    bullish_cross = (
        prev_tenkan is not None
        and prev_kijun is not None
        and prev_tenkan <= prev_kijun
        and tenkan > kijun
    )

    bearish_cross = (
        prev_tenkan is not None
        and prev_kijun is not None
        and prev_tenkan >= prev_kijun
        and tenkan < kijun
    )

    return {
        "price": price,
        "tenkan": tenkan,
        "kijun": kijun,
        "span_a": span_a,
        "span_b": span_b,
        "top": top,
        "bottom": bottom,
        "bullish_cross": bullish_cross,
        "bearish_cross": bearish_cross,
        "last": closed[-1],
        "previous": closed[-2]
    }


# ============================================================
# SIGNAL
# ============================================================

def analyze_symbol(
    symbol,
    candles
):

    if len(candles) < 60:

        return {
            "symbol": symbol,
            "status": "insufficient",
            "kline_ok": True
        }

    ichi = calculate_ichimoku(
        candles
    )

    if ichi is None:

        return {
            "symbol": symbol,
            "status": "insufficient",
            "kline_ok": True
        }

    price = ichi["price"]
    tenkan = ichi["tenkan"]
    kijun = ichi["kijun"]

    above_cloud = (
        price > ichi["top"]
    )

    below_cloud = (
        price < ichi["bottom"]
    )

    inside_cloud = (
        not above_cloud
        and not below_cloud
    )

    if inside_cloud:

        return {
            "symbol": symbol,
            "status": "inside_cloud",
            "kline_ok": True
        }

    bullish_cloud = (
        ichi["span_a"]
        >
        ichi["span_b"]
    )

    bearish_cloud = (
        ichi["span_a"]
        <
        ichi["span_b"]
    )

    bull_core = (
        int(above_cloud)
        +
        int(tenkan > kijun)
        +
        int(bullish_cloud)
    )

    bear_core = (
        int(below_cloud)
        +
        int(tenkan < kijun)
        +
        int(bearish_cloud)
    )

    # ========================================================
    # BUY
    # ========================================================

    if (
        bull_core >= 2
        and bull_core > bear_core
    ):

        side = "BUY"

        score = 0.0

        if above_cloud:
            score += 3.0

        if tenkan > kijun:
            score += 2.0

        if bullish_cloud:
            score += 1.5

        if ichi["bullish_cross"]:
            score += 1.5

        if ichi["last"]["c"] > ichi["last"]["o"]:
            score += 0.5

    # ========================================================
    # SELL
    # ========================================================

    elif (
        bear_core >= 2
        and bear_core > bull_core
    ):

        side = "SELL"

        score = 0.0

        if below_cloud:
            score += 3.0

        if tenkan < kijun:
            score += 2.0

        if bearish_cloud:
            score += 1.5

        if ichi["bearish_cross"]:
            score += 1.5

        if ichi["last"]["c"] < ichi["last"]["o"]:
            score += 0.5

    else:

        return {
            "symbol": symbol,
            "status": "weak_core",
            "kline_ok": True
        }

    distance = (
        abs(price - kijun)
        / price
        if price
        else 999
    )

    if (
        distance
        > MAX_KIJUN_DISTANCE
        and not (
            ichi["bullish_cross"]
            or ichi["bearish_cross"]
        )
    ):

        return {
            "symbol": symbol,
            "status": "too_far_kijun",
            "kline_ok": True
        }

    if score < MIN_SCORE:

        return {
            "symbol": symbol,
            "status": "low_score",
            "kline_ok": True
        }

    # کمی امتیاز برای کندل تأیید
    candle = ichi["last"]

    candle_range = max(
        candle["h"] - candle["l"],
        1e-12
    )

    close_position = (
        candle["c"] - candle["l"]
    ) / candle_range

    if (
        side == "BUY"
        and close_position >= 0.55
    ):

        score += 0.25

    if (
        side == "SELL"
        and close_position <= 0.45
    ):

        score += 0.25

    return {
        "symbol": symbol,
        "status": "signal",
        "kline_ok": True,
        "side": side,
        "score": score,
        "price": price,
        "tenkan": tenkan,
        "kijun": kijun,
        "distance_kijun": distance
    }


# ============================================================
# ONE MARKET
# ============================================================

def scan_symbol(
    symbol
):

    result = {
        "symbol": symbol,
        "status": "error",
        "kline_ok": False
    }

    try:

        raw = get_klines(
            symbol
        )

        candles = parse_klines(
            raw
        )

        if not candles:

            result["error"] = (
                "EMPTY KLINE"
            )

            return result

        result = analyze_symbol(
            symbol,
            candles
        )

        return result

    except ApiError as exc:

        result["status"] = "error"

        result["error_kind"] = (
            exc.kind
        )

        result["error"] = str(
            exc
        )[:180]

        return result

    except Exception as exc:

        result["status"] = "error"

        result["error_kind"] = (
            type(exc).__name__
        )

        result["error"] = str(
            exc
        )[:180]

        return result


# ============================================================
# FAST SCANNER
# ============================================================

def scan_market(
    symbols
):

    started = time.perf_counter()

    stats = {
        "submitted": len(symbols),
        "completed": 0,
        "kline_ok": 0,
        "signal": 0,
        "inside_cloud": 0,
        "weak_core": 0,
        "low_score": 0,
        "too_far_kijun": 0,
        "insufficient": 0,
        "error": 0,
        "timeout": 0,
        "connection": 0,
        "rate_limit": 0,
        "server": 0
    }

    signals = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                scan_symbol,
                symbol
            ): symbol
            for symbol in symbols
        }

        for future in as_completed(
            futures
        ):

            stats["completed"] += 1

            symbol = futures[
                future
            ]

            try:

                result = future.result()

            except Exception as exc:

                result = {
                    "symbol": symbol,
                    "status": "error",
                    "error": str(exc)
                }

            if result.get(
                "kline_ok",
                False
            ):

                stats["kline_ok"] += 1

            status = result.get(
                "status",
                "error"
            )

            if status in stats:

                stats[status] += 1

            if status == "signal":

                signals.append(
                    result
                )

            if status == "error":

                kind = result.get(
                    "error_kind",
                    ""
                )

                if kind in (
                    "connect_timeout",
                    "read_timeout"
                ):

                    stats["timeout"] += 1

                elif kind == "connection":

                    stats["connection"] += 1

                elif kind == "rate_limit":

                    stats["rate_limit"] += 1

                elif kind == "server":

                    stats["server"] += 1

    elapsed = (
        time.perf_counter()
        - started
    )

    signals.sort(
        key=lambda item: item.get(
            "score",
            0
        ),
        reverse=True
    )

    # نمونه خطا برای دیباگ
    first_error = None

    for symbol in symbols:

        pass

    return (
        signals,
        stats,
        elapsed
    )


# ============================================================
# BALANCE
# ============================================================

def get_balance():

    if not API_KEY or not API_SECRET:

        return None

    try:

        data = private_get(
            "balance"
        )

        for item in data:

            asset = str(
                item.get(
                    "asset",
                    ""
                )
            ).upper()

            if asset == "USDT":

                return float(
                    item.get(
                        "availableBalance",
                        item.get(
                            "balance",
                            0
                        )
                    )
                    or 0
                )

        return None

    except Exception as exc:

        log(
            "⚠️ Balance unavailable: "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        return None


# ============================================================
# POSITIONS
# ============================================================

def get_positions():

    data = private_get(
        "positionRisk"
    )

    positions = []

    for item in data:

        try:

            amount = float(
                item.get(
                    "positionAmt",
                    0
                )
                or 0
            )

            if abs(amount) > 0:

                positions.append(
                    item
                )

        except Exception:

            continue

    return positions


# ============================================================
# LEVERAGE
# ============================================================

def set_leverage(
    symbol
):

    return private_post(
        "leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE
        }
    )


# ============================================================
# QUANTITY
# ============================================================

def make_quantity(
    symbol,
    price,
    filters
):

    if price <= 0:

        raise RuntimeError(
            "Invalid price"
        )

    f = filters.get(
        symbol,
        {}
    )

    step = float(
        f.get(
            "step",
            0
        )
        or 0
    )

    min_qty = float(
        f.get(
            "min_qty",
            0
        )
        or 0
    )

    min_notional = float(
        f.get(
            "min_notional",
            0
        )
        or 0
    )

    quantity = (
        ORDER_USDT
        / price
    )

    if (
        min_notional > 0
        and quantity * price
        < min_notional
    ):

        quantity = (
            min_notional
            / price
        )

    if min_qty > 0:

        quantity = max(
            quantity,
            min_qty
        )

    if step > 0:

        quantity = floor_step(
            quantity,
            step
        )

    if quantity <= 0:

        raise RuntimeError(
            "Quantity is zero"
        )

    return quantity


# ============================================================
# MARKET ORDER
# ============================================================

def market_order(
    symbol,
    side,
    quantity
):

    return private_post(
        "order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": fmt(
                quantity
            ),
            "newOrderRespType": "RESULT"
        }
    )


# ============================================================
# SL TP
# ============================================================

def place_sl_tp(
    symbol,
    side,
    entry
):

    close_side = (
        "SELL"
        if side == "BUY"
        else "BUY"
    )

    if side == "BUY":

        sl = (
            entry
            * (1 - SL_PCT)
        )

        tp = (
            entry
            * (1 + TP_PCT)
        )

    else:

        sl = (
            entry
            * (1 + SL_PCT)
        )

        tp = (
            entry
            * (1 - TP_PCT)
        )

    try:

        response = private_post(
            "positionSlTp",
            {
                "symbol": symbol,
                "side": close_side,
                "stopLossPrice": fmt(sl),
                "takeProfitPrice": fmt(tp)
            }
        )

        return (
            response,
            sl,
            tp
        )

    except Exception as exc:

        log(
            "⚠️ SL/TP error "
            f"{symbol}: {exc}"
        )

        return (
            None,
            sl,
            tp
        )


# ============================================================
# ENTRY PRICE
# ============================================================

def extract_entry(
    order,
    fallback
):

    for key in (
        "avgPrice",
        "avgFillPrice",
        "price"
    ):

        try:

            value = float(
                order.get(
                    key,
                    0
                )
                or 0
            )

            if value > 0:

                return value

        except Exception:

            pass

    return fallback


# ============================================================
# REAL TRADE
# ============================================================

def execute_trade(
    signals,
    filters
):

    if not signals:

        return None

    if not LIVE_TRADING:

        log(
            "🔒 LIVE_TRADING=False"
        )

        return None

    if BUY_LOCK:

        log(
            "🔒 BUY_LOCK=True"
        )

        return None

    signal = signals[0]

    symbol = signal[
        "symbol"
    ]

    side = signal[
        "side"
    ]

    price = signal[
        "price"
    ]

    # --------------------------------------------------------
    # Balance
    # --------------------------------------------------------

    balance = get_balance()

    if balance is None:

        telegram(
            "⚠️ ATI FUTURES\n"
            "Balance API unavailable.\n"
            "🚫 Real order blocked."
        )

        log(
            "🚫 Balance unavailable "
            "-> real order blocked"
        )

        return None

    if balance <= 0:

        telegram(
            "⚠️ ATI FUTURES\n"
            f"USDT balance: {balance:.8f}\n"
            "🚫 Real order blocked."
        )

        return None

    # --------------------------------------------------------
    # Safety balance
    # --------------------------------------------------------

    if ORDER_USDT > (
        balance * 0.95
    ):

        telegram(
            "⚠️ ATI FUTURES\n"
            f"💰 USDT: {balance:.6f}\n"
            f"💵 Order: {ORDER_USDT:.2f}\n"
            "🚫 موجودی کافی برای سفارش نیست."
        )

        return None

    # --------------------------------------------------------
    # Existing position
    # --------------------------------------------------------

    try:

        positions = get_positions()

    except Exception as exc:

        telegram(
            "⚠️ ATI FUTURES\n"
            "Position check failed.\n"
            "🚫 Real order blocked."
        )

        log(
            f"Position check error: {exc}"
        )

        return None

    if positions:

        log(
            f"🚫 Existing positions: "
            f"{len(positions)}"
        )

        return None

    # --------------------------------------------------------
    # Quantity
    # --------------------------------------------------------

    try:

        quantity = make_quantity(
            symbol,
            price,
            filters
        )

    except Exception as exc:

        telegram(
            "❌ ATI FUTURES\n"
            f"Quantity error:\n{exc}"
        )

        return None

    # --------------------------------------------------------
    # Leverage
    # --------------------------------------------------------

    try:

        set_leverage(
            symbol
        )

    except Exception as exc:

        telegram(
            "❌ ATI FUTURES\n"
            f"Leverage error:\n{exc}\n"
            "🚫 Order blocked."
        )

        return None

    # --------------------------------------------------------
    # REAL ORDER
    # --------------------------------------------------------

    try:

        log(
            "🚨 REAL FUTURES ORDER"
        )

        log(
            f"{symbol} "
            f"{side} "
            f"qty={quantity}"
        )

        order = market_order(
            symbol,
            side,
            quantity
        )

        entry = extract_entry(
            order,
            price
        )

        sltp, sl, tp = (
            place_sl_tp(
                symbol,
                side,
                entry
            )
        )

        direction = (
            "🟢 LONG"
            if side == "BUY"
            else
            "🔴 SHORT"
        )

        message = (
            "🚨 ATI FUTURES REAL TRADE\n"
            "⚡ V7.4\n"
            f"📌 {symbol}\n"
            f"{direction}\n"
            f"💵 Entry: {entry:.10g}\n"
            f"📦 Qty: {quantity:.10g}\n"
            f"⭐ Score: {signal['score']:.2f}\n"
            f"🎯 TP: {tp:.10g}\n"
            f"🛑 SL: {sl:.10g}\n"
            f"☁️ Ichimoku\n"
            f"⚙️ {LEVERAGE}x\n"
            "🟢 LIVE: True"
        )

        telegram(
            message
        )

        log(message)

        if sltp is None:

            telegram(
                "⚠️ WARNING\n"
                "Position opened but "
                "SL/TP was not confirmed."
            )

        return order

    except Exception as exc:

        message = (
            "❌ ATI FUTURES ORDER ERROR\n"
            f"{symbol}\n"
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        telegram(
            message
        )

        log(message)

        return None


# ============================================================
# HEARTBEAT
# ============================================================

def heartbeat(
    symbol_count,
    stats,
    elapsed,
    balance
):

    if balance is None:

        balance_text = (
            "UNAVAILABLE"
        )

    else:

        balance_text = (
            f"{balance:.6f}"
        )

    message = (
        "💓 ATI FUTURES ALIVE\n"
        "⚡ V7.4 ROBUST ICHIMOKU\n"
        f"📊 Markets: {symbol_count}\n"
        f"📡 Completed: "
        f"{stats['completed']}/"
        f"{stats['submitted']}\n"
        f"📈 Klines OK: "
        f"{stats['kline_ok']}\n"
        f"☁️ Signals: "
        f"{stats['signal']}\n"
        f"🚫 Cloud: "
        f"{stats['inside_cloud']}\n"
        f"⚠️ Weak: "
        f"{stats['weak_core']}\n"
        f"📉 Low: "
        f"{stats['low_score']}\n"
        f"📏 Far Kijun: "
        f"{stats['too_far_kijun']}\n"
        f"🌐 Timeout: "
        f"{stats['timeout']}\n"
        f"🔌 Connection: "
        f"{stats['connection']}\n"
        f"🚦 429: "
        f"{stats['rate_limit']}\n"
        f"💥 Server: "
        f"{stats['server']}\n"
        f"❌ Errors: "
        f"{stats['error']}\n"
        f"⏱️ Scan: "
        f"{elapsed:.3f}s\n"
        f"💰 USDT: "
        f"{balance_text}\n"
        f"🟢 LIVE: "
        f"{LIVE_TRADING}\n"
        f"🕐 "
        f"{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
    )

    telegram(
        message
    )

    log(message)


# ============================================================
# STARTUP
# ============================================================

def startup():

    log(
        "💓 ATI FUTURES V7.4 START"
    )

    log(
        "⚡ ROBUST CONNECTION + "
        "ICHIMOKU"
    )

    log(
        "📡 TABDEAL FUTURES | 5m"
    )

    log(
        f"⚙️ LEVERAGE: "
        f"{LEVERAGE}x"
    )

    log(
        f"💵 ORDER: "
        f"{ORDER_USDT} USDT"
    )

    log(
        f"🟢 LIVE: "
        f"{LIVE_TRADING}"
    )

    if not API_KEY or not API_SECRET:

        raise RuntimeError(
            "TABDIL_API_KEY / "
            "TABDIL_API_SECRET missing"
        )

    # تست عمومی
    try:

        info = get_exchange_info()

        count = len(
            info.get(
                "symbols",
                []
            )
        )

        log(
            f"✅ Public Futures API OK "
            f"({count} symbols)"
        )

    except Exception as exc:

        log(
            "❌ Public Futures API failed: "
            f"{exc}"
        )

        telegram(
            "❌ ATI FUTURES V7.4\n"
            "Public Futures API unavailable.\n"
            f"{exc}\n"
            "🚫 Trading blocked."
        )

        raise

    # تست خصوصی
    balance = get_balance()

    if balance is None:

        log(
            "⚠️ Private balance unavailable."
        )

        telegram(
            "⚠️ ATI FUTURES V7.4\n"
            "Public API is OK.\n"
            "Private Balance API unavailable.\n"
            "🚫 Real orders will stay blocked "
            "until balance is reachable."
        )

    else:

        log(
            f"💰 USDT FREE: "
            f"{balance:.8f}"
        )

        telegram(
            "💓 ATI FUTURES V7.4 STARTED\n"
            "⚡ Robust Futures Connection\n"
            "☁️ Ichimoku 5m\n"
            f"⚙️ Leverage: {LEVERAGE}x\n"
            f"💵 Order: {ORDER_USDT} USDT\n"
            f"💰 USDT: {balance:.6f}\n"
            f"🟢 LIVE: {LIVE_TRADING}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    startup()

    filters = get_filters()

    symbols = get_symbols()

    log(
        f"📊 Futures markets found: "
        f"{len(symbols)}"
    )

    if not symbols:

        raise RuntimeError(
            "No USDT Futures markets found"
        )

    cycle = 0

    while True:

        cycle += 1

        log(
            ""
        )

        log(
            "================================================"
        )

        log(
            f"🔄 SCAN CYCLE #{cycle}"
        )

        log(
            "================================================"
        )

        try:

            signals, stats, elapsed = (
                scan_market(
                    symbols
                )
            )

            balance = get_balance()

            heartbeat(
                len(symbols),
                stats,
                elapsed,
                balance
            )

            # ------------------------------------------------
            # REAL SIGNAL
            # ------------------------------------------------

            if signals:

                best = signals[0]

                log(
                    "🎯 BEST SIGNAL"
                )

                log(
                    f"📌 {best['symbol']}"
                )

                log(
                    f"📈 {best['side']}"
                )

                log(
                    f"⭐ Score: "
                    f"{best['score']:.2f}"
                )

                log(
                    f"💵 Price: "
                    f"{best['price']:.10g}"
                )

                telegram(
                    "🎯 ATI FUTURES SIGNAL\n"
                    f"📌 {best['symbol']}\n"
                    f"📈 {best['side']}\n"
                    f"💵 {best['price']:.10g}\n"
                    f"⭐ Score: "
                    f"{best['score']:.2f}\n"
                    "☁️ Ichimoku"
                )

                if LIVE_TRADING:

                    execute_trade(
                        signals[
                            :MAX_NEW_TRADES
                        ],
                        filters
                    )

            else:

                log(
                    "☁️ NO SIGNAL"
                )

        except Exception as exc:

            message = (
                "❌ ATI FUTURES CYCLE ERROR\n"
                f"{type(exc).__name__}: "
                f"{exc}"
            )

            log(
                message
            )

            telegram(
                message
            )

        # ----------------------------------------------------
        # WAIT
        # ----------------------------------------------------

        wait = SCAN_INTERVAL

        log(
            f"⏳ Next scan in "
            f"{wait}s"
        )

        for _ in range(wait):

            time.sleep(1)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
