# ============================================================
# ATI FUTURES REAL V7.3
# FAST ICHIMOKU SCANNER
# TABDEAL FUTURES
# REAL BUY / SELL
# ============================================================

import os
import time
import hmac
import hashlib
import requests

from urllib.parse import urlencode
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, ROUND_DOWN


# ============================================================
# VERSION
# ============================================================

VERSION = "ATI-FUTURES-REAL-V7.3"


# ============================================================
# API
# ============================================================

API_BASE = "https://api1.tabdeal.org"

PUBLIC_V1 = API_BASE + "/r/fapi/v1/"
PRIVATE_V3 = API_BASE + "/r/fapi/v3/"
WRITE_V1 = API_BASE + "/fapi/v1/"

REQUEST_TIMEOUT = 8


# ============================================================
# ENV HELPERS
# ============================================================

def env_str(name, default=""):
    value = os.getenv(name, "")
    if value and value.strip():
        return value.strip()
    return default


def env_int(name, default):
    try:
        return int(env_str(name, str(default)))
    except Exception:
        return default


def env_float(name, default):
    try:
        return float(env_str(name, str(default)))
    except Exception:
        return default


def env_bool(name, default=False):
    value = env_str(name, "").lower()

    if not value:
        return default

    return value in (
        "1",
        "true",
        "yes",
        "on",
    )


# ============================================================
# SETTINGS
# ============================================================

TIMEFRAME = env_str("TIMEFRAME", "5m")

KLINE_LIMIT = env_int(
    "KLINE_LIMIT",
    100
)

SCAN_WORKERS = max(
    4,
    env_int("SCAN_WORKERS", 16)
)

SCAN_INTERVAL_SECONDS = env_int(
    "SCAN_INTERVAL_SECONDS",
    300
)

# ------------------------------------------------------------
# Ichimoku signal settings
# ------------------------------------------------------------

MIN_SIGNAL_SCORE = env_float(
    "MIN_SIGNAL_SCORE",
    5.0
)

MAX_KIJUN_DISTANCE = env_float(
    "MAX_KIJUN_DISTANCE",
    2.5
)

# ------------------------------------------------------------
# REAL TRADING
# ------------------------------------------------------------

LIVE_TRADING = env_bool(
    "LIVE_TRADING",
    True
)

ORDER_USDT = env_float(
    "ORDER_QTY",
    2.0
)

LEVERAGE = env_int(
    "LEVERAGE",
    3
)

MAX_NEW_TRADES = max(
    1,
    env_int("MAX_NEW_TRADES", 1)
)

# ------------------------------------------------------------
# SL / TP
# ------------------------------------------------------------

SL_PERCENT = env_float(
    "SL_PERCENT",
    1.0
)

TP_PERCENT = env_float(
    "TP_PERCENT",
    2.0
)


# ============================================================
# API KEYS
# ============================================================

API_KEY = env_str(
    "TABDIL_API_KEY",
    env_str("TABDEAL_API_KEY")
)

API_SECRET = env_str(
    "TABDIL_API_SECRET",
    env_str("TABDEAL_API_SECRET")
)


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = env_str(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = env_str(
    "TELEGRAM_CHAT_ID"
)


# ============================================================
# ICHIMOKU SETTINGS
# ============================================================

TENKAN_PERIOD = 9
KIJUN_PERIOD = 26
SENKOU_B_PERIOD = 52
DISPLACEMENT = 26


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-V7.3",
    "Accept": "application/json",
})


# ============================================================
# TIME
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN missing")
        return False

    if not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM_CHAT_ID missing")
        return False

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        )

        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": str(message),
            },
            timeout=12,
        )

        if response.status_code == 200:

            print("✅ TELEGRAM SENT")

            return True

        print(
            "❌ TELEGRAM ERROR:",
            response.status_code,
            response.text[:500]
        )

        return False

    except Exception as e:

        print(
            "❌ TELEGRAM EXCEPTION:",
            repr(e)
        )

        return False


# ============================================================
# TELEGRAM TEST
# ============================================================

def telegram_test():

    if not TELEGRAM_BOT_TOKEN:
        return False

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{TELEGRAM_BOT_TOKEN}/getMe"
        )

        response = requests.get(
            url,
            timeout=12
        )

        if response.status_code != 200:
            return False

        data = response.json()

        if not data.get("ok"):
            return False

        username = (
            data.get("result", {})
            .get("username", "UNKNOWN")
        )

        print(
            f"✅ TELEGRAM BOT: @{username}"
        )

        return telegram(
            "🧪 ATI TELEGRAM TEST\n\n"
            "✅ Telegram connection is working.\n"
            f"⚡ {VERSION}\n"
            f"🕐 {utc_now()}"
        )

    except Exception as e:

        print(
            "❌ TELEGRAM TEST ERROR:",
            repr(e)
        )

        return False


# ============================================================
# SIGNATURE
# ============================================================

def signed_params(params=None):

    data = dict(params or {})

    data["timestamp"] = int(
        time.time() * 1000
    )

    data.setdefault(
        "recvWindow",
        5000
    )

    query = urlencode(data)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    data["signature"] = signature

    return data


# ============================================================
# PUBLIC GET
# ============================================================

def public_get(
    url,
    params=None
):

    response = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT
    )

    if response.status_code != 200:

        raise Exception(
            f"HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    return response.json()


# ============================================================
# PRIVATE GET
# ============================================================

def private_get(
    url,
    params=None
):

    response = session.get(
        url,
        params=signed_params(params),
        headers={
            "X-MBX-APIKEY": API_KEY
        },
        timeout=REQUEST_TIMEOUT
    )

    if response.status_code != 200:

        raise Exception(
            f"HTTP {response.status_code}: "
            f"{response.text[:1200]}"
        )

    return response.json()


# ============================================================
# PRIVATE POST
# ============================================================

def private_post(
    url,
    params=None
):

    response = session.post(
        url,
        params=signed_params(params),
        headers={
            "X-MBX-APIKEY": API_KEY
        },
        timeout=REQUEST_TIMEOUT
    )

    if response.status_code not in (
        200,
        201
    ):

        raise Exception(
            f"HTTP {response.status_code}: "
            f"{response.text[:1500]}"
        )

    return response.json()


# ============================================================
# ACCOUNT
# ============================================================

def get_account():

    return private_get(
        PRIVATE_V3 + "account"
    )


def get_balance():

    return private_get(
        PRIVATE_V3 + "balance"
    )


def extract_usdt(data):

    values = []

    def walk(obj):

        if isinstance(obj, dict):

            asset = str(
                obj.get("asset", "")
            ).upper()

            if asset == "USDT":

                for key in (
                    "availableBalance",
                    "available",
                    "free",
                    "walletBalance",
                    "balance",
                    "crossWalletBalance",
                ):

                    try:

                        value = obj.get(key)

                        if value is not None:
                            values.append(
                                float(value)
                            )

                    except Exception:
                        pass

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):

            for value in obj:
                walk(value)

    walk(data)

    return max(
        values,
        default=0.0
    )


def get_usdt_balance():

    try:

        return extract_usdt(
            get_balance()
        )

    except Exception as e:

        print(
            "⚠️ BALANCE ERROR 1:",
            str(e)[:300]
        )

    try:

        return extract_usdt(
            get_account()
        )

    except Exception as e:

        print(
            "⚠️ BALANCE ERROR 2:",
            str(e)[:300]
        )

    return 0.0


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    return public_get(
        PUBLIC_V1 + "exchangeInfo"
    )


def get_symbols():

    data = get_exchange_info()

    result = []

    for item in data.get(
        "symbols",
        []
    ):

        if not isinstance(
            item,
            dict
        ):
            continue

        symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).upper()

        quote = str(
            item.get(
                "quoteAsset",
                ""
            )
        ).upper()

        status = str(
            item.get(
                "status",
                ""
            )
        ).upper()

        if (
            symbol
            and quote == "USDT"
            and status in (
                "TRADING",
                "ENABLED",
                "OPEN"
            )
        ):

            result.append(item)

    return result


# ============================================================
# TICKERS
# ============================================================

def get_tickers():

    data = public_get(
        PUBLIC_V1 + "ticker/24hr"
    )

    result = {}

    if isinstance(
        data,
        list
    ):

        for item in data:

            if not isinstance(
                item,
                dict
            ):
                continue

            symbol = str(
                item.get(
                    "symbol",
                    ""
                )
            ).upper()

            if symbol:
                result[symbol] = item

    return result


# ============================================================
# KLINES
# ============================================================

def get_klines(symbol):

    return public_get(
        PUBLIC_V1 + "klines",
        {
            "symbol": symbol,
            "interval": TIMEFRAME,
            "limit": KLINE_LIMIT,
        }
    )


def parse_klines(data):

    candles = []

    if not isinstance(
        data,
        list
    ):
        return candles

    for row in data:

        try:

            if len(row) >= 6:

                candles.append({
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                })

        except Exception:
            pass

    return candles


# ============================================================
# ICHIMOKU MIDPOINT
# ============================================================

def midpoint(
    highs,
    lows,
    period
):

    if len(highs) < period:
        return None

    return (
        max(highs[-period:])
        +
        min(lows[-period:])
    ) / 2.0


# ============================================================
# ICHIMOKU
# ============================================================

def calculate_ichimoku(
    candles
):

    if len(candles) < 60:
        return None

    # Remove incomplete candle
    closed = candles[:-1]

    if len(closed) < 55:
        return None

    highs = [
        x["high"]
        for x in closed
    ]

    lows = [
        x["low"]
        for x in closed
    ]

    closes = [
        x["close"]
        for x in closed
    ]

    close = closes[-1]

    tenkan = midpoint(
        highs,
        lows,
        TENKAN_PERIOD
    )

    kijun = midpoint(
        highs,
        lows,
        KIJUN_PERIOD
    )

    senkou_b = midpoint(
        highs,
        lows,
        SENKOU_B_PERIOD
    )

    if (
        tenkan is None
        or kijun is None
        or senkou_b is None
    ):
        return None

    senkou_a = (
        tenkan + kijun
    ) / 2.0

    cloud_top = max(
        senkou_a,
        senkou_b
    )

    cloud_bottom = min(
        senkou_a,
        senkou_b
    )

    previous_highs = highs[:-1]
    previous_lows = lows[:-1]

    previous_tenkan = midpoint(
        previous_highs,
        previous_lows,
        TENKAN_PERIOD
    )

    previous_kijun = midpoint(
        previous_highs,
        previous_lows,
        KIJUN_PERIOD
    )

    bullish_cross = (
        previous_tenkan is not None
        and previous_kijun is not None
        and previous_tenkan <= previous_kijun
        and tenkan > kijun
    )

    bearish_cross = (
        previous_tenkan is not None
        and previous_kijun is not None
        and previous_tenkan >= previous_kijun
        and tenkan < kijun
    )

    # Chikou confirmation
    if len(closes) > DISPLACEMENT:

        reference_close = closes[
            -1 - DISPLACEMENT
        ]

    else:

        reference_close = closes[0]

    chikou_buy = (
        close > reference_close
    )

    chikou_sell = (
        close < reference_close
    )

    kijun_distance = (
        abs(close - kijun)
        / kijun
        * 100
        if kijun > 0
        else 999
    )

    last = closed[-1]

    candle_range = max(
        last["high"] - last["low"],
        1e-12
    )

    close_position = (
        last["close"] - last["low"]
    ) / candle_range

    bullish_candle = (
        last["close"] > last["open"]
        and close_position >= 0.55
    )

    bearish_candle = (
        last["close"] < last["open"]
        and close_position <= 0.45
    )

    return {

        "close": close,

        "tenkan": tenkan,

        "kijun": kijun,

        "senkou_a": senkou_a,

        "senkou_b": senkou_b,

        "cloud_top": cloud_top,

        "cloud_bottom": cloud_bottom,

        "above_cloud": (
            close > cloud_top
        ),

        "below_cloud": (
            close < cloud_bottom
        ),

        "inside_cloud": (
            cloud_bottom
            <= close
            <= cloud_top
        ),

        "bullish_cloud": (
            senkou_a > senkou_b
        ),

        "bearish_cloud": (
            senkou_a < senkou_b
        ),

        "bullish_cross": bullish_cross,

        "bearish_cross": bearish_cross,

        "chikou_buy": chikou_buy,

        "chikou_sell": chikou_sell,

        "kijun_distance": kijun_distance,

        "bullish_candle": bullish_candle,

        "bearish_candle": bearish_candle,
    }


# ============================================================
# SIGNAL ENGINE
# ============================================================

def evaluate_signal(
    symbol,
    info,
    ticker,
    candles
):

    ichi = calculate_ichimoku(
        candles
    )

    if not ichi:

        return {
            "status": "insufficient"
        }

    # No trade inside cloud
    if ichi["inside_cloud"]:

        return {
            "status": "inside_cloud"
        }

    buy_score = 0.0
    sell_score = 0.0

    buy_reasons = []
    sell_reasons = []

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    if ichi["above_cloud"]:

        buy_score += 3.0
        buy_reasons.append(
            "ABOVE_KUMO"
        )

    if (
        ichi["tenkan"]
        > ichi["kijun"]
    ):

        buy_score += 2.0
        buy_reasons.append(
            "TENKAN_GT_KIJUN"
        )

    if ichi["bullish_cloud"]:

        buy_score += 1.5
        buy_reasons.append(
            "BULLISH_KUMO"
        )

    # --------------------------------------------------------
    # SELL
    # --------------------------------------------------------

    if ichi["below_cloud"]:

        sell_score += 3.0
        sell_reasons.append(
            "BELOW_KUMO"
        )

    if (
        ichi["tenkan"]
        < ichi["kijun"]
    ):

        sell_score += 2.0
        sell_reasons.append(
            "TENKAN_LT_KIJUN"
        )

    if ichi["bearish_cloud"]:

        sell_score += 1.5
        sell_reasons.append(
            "BEARISH_KUMO"
        )

    # --------------------------------------------------------
    # CROSS = BONUS
    # --------------------------------------------------------

    if ichi["bullish_cross"]:

        buy_score += 1.5
        buy_reasons.append(
            "TK_CROSS"
        )

    if ichi["bearish_cross"]:

        sell_score += 1.5
        sell_reasons.append(
            "TK_CROSS"
        )

    # --------------------------------------------------------
    # CHIKOU = BONUS ONLY
    # --------------------------------------------------------

    if ichi["chikou_buy"]:

        buy_score += 0.5
        buy_reasons.append(
            "CHIKOU"
        )

    if ichi["chikou_sell"]:

        sell_score += 0.5
        sell_reasons.append(
            "CHIKOU"
        )

    # --------------------------------------------------------
    # CANDLE = BONUS
    # --------------------------------------------------------

    if ichi["bullish_candle"]:

        buy_score += 0.5
        buy_reasons.append(
            "BULLISH_CANDLE"
        )

    if ichi["bearish_candle"]:

        sell_score += 0.5
        sell_reasons.append(
            "BEARISH_CANDLE"
        )

    # --------------------------------------------------------
    # SIDE
    # --------------------------------------------------------

    if buy_score >= sell_score:

        side = "BUY"

        score = buy_score

        reasons = buy_reasons

        core_count = (
            int(ichi["above_cloud"])
            +
            int(
                ichi["tenkan"]
                > ichi["kijun"]
            )
            +
            int(ichi["bullish_cloud"])
        )

    else:

        side = "SELL"

        score = sell_score

        reasons = sell_reasons

        core_count = (
            int(ichi["below_cloud"])
            +
            int(
                ichi["tenkan"]
                < ichi["kijun"]
            )
            +
            int(ichi["bearish_cloud"])
        )

    # Need 2 core conditions
    if core_count < 2:

        return {
            "status": "weak_core"
        }

    # Minimum score
    if score < MIN_SIGNAL_SCORE:

        return {
            "status": "low_score"
        }

    # Don't chase price too far from Kijun
    if (
        ichi["kijun_distance"]
        > MAX_KIJUN_DISTANCE
    ):

        if not (
            ichi["bullish_cross"]
            or
            ichi["bearish_cross"]
        ):

            return {
                "status": "too_far_kijun"
            }

    try:

        change = float(
            ticker.get(
                "priceChangePercent",
                0
            )
        )

    except Exception:

        change = 0.0

    try:

        volume = float(
            ticker.get(
                "quoteVolume",
                0
            )
        )

    except Exception:

        volume = 0.0

    return {

        "status": "signal",

        "symbol": symbol,

        "side": side,

        "score": score,

        "price": ichi["close"],

        "tenkan": ichi["tenkan"],

        "kijun": ichi["kijun"],

        "senkou_a": ichi["senkou_a"],

        "senkou_b": ichi["senkou_b"],

        "kijun_distance": (
            ichi["kijun_distance"]
        ),

        "change": change,

        "volume": volume,

        "reasons": reasons,

        "info": info,
    }


# ============================================================
# ONE SYMBOL
# ============================================================

def scan_one_symbol(
    info,
    ticker
):

    symbol = str(
        info.get(
            "symbol",
            ""
        )
    ).upper()

    if not symbol:

        return {
            "status": "invalid"
        }

    try:

        raw = get_klines(
            symbol
        )

        candles = parse_klines(
            raw
        )

        if len(candles) < 60:

            return {
                "status": "insufficient"
            }

        return evaluate_signal(
            symbol,
            info,
            ticker,
            candles
        )

    except Exception as e:

        print(
            f"⚠️ {symbol} KLINE ERROR: "
            f"{str(e)[:180]}"
        )

        return {
            "status": "error"
        }


# ============================================================
# FAST MARKET SCANNER
# ============================================================

def scan_market(
    symbols
):

    started = time.perf_counter()

    stats = {

        "submitted": 0,

        "completed": 0,

        "signal": 0,

        "inside_cloud": 0,

        "weak_core": 0,

        "low_score": 0,

        "too_far_kijun": 0,

        "insufficient": 0,

        "error": 0,

        "invalid": 0,

    }

    results = []

    # --------------------------------------------------------
    # TICKERS
    # --------------------------------------------------------

    try:

        tickers = get_tickers()

    except Exception as e:

        print(
            "❌ TICKER ERROR:",
            str(e)[:500]
        )

        elapsed = (
            time.perf_counter()
            - started
        )

        return (
            [],
            elapsed,
            stats
        )

    # --------------------------------------------------------
    # TASKS
    # --------------------------------------------------------

    tasks = []

    for info in symbols:

        symbol = info.get(
            "symbol"
        )

        ticker = tickers.get(
            symbol
        )

        if ticker:

            tasks.append(
                (
                    info,
                    ticker
                )
            )

    stats["submitted"] = len(
        tasks
    )

    print(
        f"🚀 KLINE TASKS: "
        f"{len(tasks)}"
    )

    print(
        f"⚡ WORKERS: "
        f"{SCAN_WORKERS}"
    )

    # --------------------------------------------------------
    # PARALLEL KLINE SCAN
    # --------------------------------------------------------

    with ThreadPoolExecutor(
        max_workers=SCAN_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                scan_one_symbol,
                info,
                ticker
            )
            for info, ticker in tasks
        ]

        for future in as_completed(
            futures
        ):

            stats["completed"] += 1

            try:

                result = future.result()

                status = result.get(
                    "status",
                    "invalid"
                )

                if status not in stats:

                    stats["invalid"] += 1

                else:

                    stats[status] += 1

                if status == "signal":

                    results.append(
                        result
                    )

            except Exception as e:

                stats["error"] += 1

                print(
                    "⚠️ FUTURE ERROR:",
                    str(e)[:200]
                )

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    elapsed = (
        time.perf_counter()
        - started
    )

    return (
        results,
        elapsed,
        stats
    )


# ============================================================
# POSITIONS
# ============================================================

def get_positions():

    return private_get(
        PRIVATE_V3 + "positionRisk"
    )


def get_open_positions():

    try:

        data = get_positions()

        result = []

        if not isinstance(
            data,
            list
        ):

            return result

        for position in data:

            try:

                amount = abs(
                    float(
                        position.get(
                            "positionAmt",
                            0
                        )
                    )
                )

            except Exception:

                amount = 0.0

            if amount > 0:

                result.append(
                    position
                )

        return result

    except Exception as e:

        print(
            "⚠️ POSITION ERROR:",
            str(e)[:300]
        )

        return []


# ============================================================
# PRICE
# ============================================================

def get_price(
    symbol
):

    data = public_get(
        PUBLIC_V1 + "ticker/price",
        {
            "symbol": symbol
        }
    )

    return float(
        data["price"]
    )


# ============================================================
# LEVERAGE
# ============================================================

def set_leverage(
    symbol
):

    return private_post(
        WRITE_V1 + "leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE
        }
    )


# ============================================================
# QUANTITY
# ============================================================

def make_quantity(
    price,
    info
):

    if price <= 0:
        return 0.0

    raw_quantity = (
        ORDER_USDT
        / price
    )

    step_size = 0.0

    minimum_qty = 0.0

    minimum_notional = 0.0

    for f in info.get(
        "filters",
        []
    ):

        filter_type = f.get(
            "filterType"
        )

        if filter_type == "LOT_SIZE":

            try:

                step_size = float(
                    f.get(
                        "stepSize",
                        0
                    )
                )

                minimum_qty = float(
                    f.get(
                        "minQty",
                        0
                    )
                )

            except Exception:
                pass

        elif filter_type in (
            "MIN_NOTIONAL",
            "NOTIONAL"
        ):

            try:

                minimum_notional = float(
                    f.get(
                        "notional",
                        f.get(
                            "minNotional",
                            0
                        )
                    )
                )

            except Exception:
                pass

    quantity = raw_quantity

    if step_size > 0:

        q = Decimal(
            str(quantity)
        )

        step = Decimal(
            str(step_size)
        )

        quantity = float(
            (
                q / step
            ).to_integral_value(
                rounding=ROUND_DOWN
            )
            * step
        )

    if quantity < minimum_qty:

        quantity = minimum_qty

    if (
        minimum_notional > 0
        and
        quantity * price
        < minimum_notional
    ):

        needed = (
            minimum_notional
            / price
        )

        if step_size > 0:

            q = Decimal(
                str(needed)
            )

            step = Decimal(
                str(step_size)
            )

            quantity = float(
                (
                    q / step
                ).to_integral_value(
                    rounding=ROUND_DOWN
                )
                * step
            )

            if (
                quantity * price
                < minimum_notional
            ):

                quantity += step_size

        else:

            quantity = needed

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
        WRITE_V1 + "order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        }
    )


# ============================================================
# FIND POSITION
# ============================================================

def find_position(
    symbol
):

    for _ in range(10):

        try:

            data = get_positions()

            if isinstance(
                data,
                list
            ):

                for position in data:

                    if (
                        position.get(
                            "symbol"
                        )
                        != symbol
                    ):
                        continue

                    try:

                        amount = float(
                            position.get(
                                "positionAmt",
                                0
                            )
                        )

                    except Exception:

                        amount = 0.0

                    if abs(amount) > 0:

                        return position

        except Exception:
            pass

        time.sleep(1)

    return None


# ============================================================
# SL / TP
# ============================================================

def set_sl_tp(
    position
):

    symbol = position.get(
        "symbol"
    )

    position_id = position.get(
        "positionId"
    )

    entry_price = float(
        position.get(
            "entryPrice",
            0
        )
    )

    position_amount = float(
        position.get(
            "positionAmt",
            0
        )
    )

    if entry_price <= 0:

        return None

    if position_amount > 0:

        sl_price = (
            entry_price
            *
            (
                1
                -
                SL_PERCENT / 100
            )
        )

        tp_price = (
            entry_price
            *
            (
                1
                +
                TP_PERCENT / 100
            )
        )

    else:

        sl_price = (
            entry_price
            *
            (
                1
                +
                SL_PERCENT / 100
            )
        )

        tp_price = (
            entry_price
            *
            (
                1
                -
                TP_PERCENT / 100
            )
        )

    return private_post(
        WRITE_V1 + "positionSlTp",
        {
            "positionId": position_id,
            "symbol": symbol,
            "slPrice": sl_price,
            "tpPrice": tp_price,
            "workingType": "MARK_PRICE",
        }
    )


# ============================================================
# RUN CYCLE
# ============================================================

def run_cycle():

    print()
    print("=" * 70)
    print(
        f"⚡ {VERSION}"
    )
    print(
        f"🕐 {utc_now()}"
    )
    print("=" * 70)

    # --------------------------------------------------------
    # BALANCE
    # --------------------------------------------------------

    balance = get_usdt_balance()

    # --------------------------------------------------------
    # OPEN POSITIONS
    # --------------------------------------------------------

    open_positions = (
        get_open_positions()
    )

    print(
        f"💰 USDT: "
        f"{balance:.6f}"
    )

    print(
        f"📌 OPEN POSITIONS: "
        f"{len(open_positions)}"
    )

    if (
        len(open_positions)
        >= MAX_NEW_TRADES
    ):

        telegram(
            "⛔ ATI FUTURES\n"
            "MAX OPEN POSITIONS\n\n"
            f"📌 Positions: "
            f"{len(open_positions)}\n"
            f"💰 USDT: "
            f"{balance:.6f}\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    symbols = get_symbols()

    print(
        f"📊 FUTURES MARKETS: "
        f"{len(symbols)}"
    )

    if not symbols:

        telegram(
            "❌ ATI FUTURES\n"
            "NO FUTURES MARKETS FOUND"
        )

        return

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    results, elapsed, stats = (
        scan_market(
            symbols
        )
    )

    print()
    print(
        "================ SCAN REPORT ================"
    )

    print(
        f"📊 MARKETS: "
        f"{len(symbols)}"
    )

    print(
        f"📥 KLINE TASKS: "
        f"{stats['submitted']}"
    )

    print(
        f"✅ COMPLETED: "
        f"{stats['completed']}"
    )

    print(
        f"🎯 FINAL SIGNALS: "
        f"{stats['signal']}"
    )

    print(
        f"☁️ INSIDE CLOUD: "
        f"{stats['inside_cloud']}"
    )

    print(
        f"🧩 WEAK CORE: "
        f"{stats['weak_core']}"
    )

    print(
        f"🏆 LOW SCORE: "
        f"{stats['low_score']}"
    )

    print(
        f"📏 FAR KIJUN: "
        f"{stats['too_far_kijun']}"
    )

    print(
        f"⚠️ INSUFFICIENT: "
        f"{stats['insufficient']}"
    )

    print(
        f"❌ ERRORS: "
        f"{stats['error']}"
    )

    print(
        f"⏱️ REAL SCAN TIME: "
        f"{elapsed:.2f}s"
    )

    print(
        "=============================================="
    )

    # --------------------------------------------------------
    # NO SIGNAL
    # --------------------------------------------------------

    if not results:

        telegram(
            "💓 ATI FUTURES ALIVE\n\n"

            f"📊 Markets: "
            f"{len(symbols)}\n"

            f"📥 Kline tasks: "
            f"{stats['submitted']}\n"

            f"✅ Completed: "
            f"{stats['completed']}\n"

            f"☁️ Inside cloud: "
            f"{stats['inside_cloud']}\n"

            f"🧩 Weak core: "
            f"{stats['weak_core']}\n"

            f"🏆 Low score: "
            f"{stats['low_score']}\n"

            f"📏 Far Kijun: "
            f"{stats['too_far_kijun']}\n"

            f"⚠️ Errors: "
            f"{stats['error']}\n"

            f"🎯 Final signals: 0\n"

            f"⏱️ Scan: "
            f"{elapsed:.2f}s\n"

            f"💰 USDT: "
            f"{balance:.6f}\n"

            f"🟢 LIVE: "
            f"{LIVE_TRADING}\n"

            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # BEST SIGNAL
    # --------------------------------------------------------

    best = results[0]

    symbol = best["symbol"]

    side = best["side"]

    score = best["score"]

    price = best["price"]

    print()
    print(
        "🚨 BEST SIGNAL"
    )

    print(
        f"🪙 {symbol}"
    )

    print(
        f"📈 {side}"
    )

    print(
        f"🏆 SCORE: {score:.2f}"
    )

    print(
        f"💵 PRICE: {price}"
    )

    print(
        "🧠 "
        +
        ", ".join(
            best["reasons"]
        )
    )

    # --------------------------------------------------------
    # SIGNAL TELEGRAM
    # --------------------------------------------------------

    telegram(
        "🚨 ATI FAST ICHIMOKU SIGNAL\n\n"

        f"🪙 {symbol}\n"

        f"📈 SIDE: {side}\n"

        f"🏆 SCORE: "
        f"{score:.2f}\n"

        f"💵 PRICE: "
        f"{price}\n"

        f"☁️ Tenkan: "
        f"{best['tenkan']}\n"

        f"☁️ Kijun: "
        f"{best['kijun']}\n"

        f"☁️ Senkou A: "
        f"{best['senkou_a']}\n"

        f"☁️ Senkou B: "
        f"{best['senkou_b']}\n"

        f"📊 24H: "
        f"{best['change']:.2f}%\n"

        f"🧠 "
        +
        ", ".join(
            best["reasons"]
        )

        +

        f"\n\n🎯 Candidates: "
        f"{len(results)}"

        +

        f"\n⏱️ Scan: "
        f"{elapsed:.2f}s"

        +

        f"\n🟢 LIVE: "
        f"{LIVE_TRADING}"

        +

        f"\n🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # PAPER MODE
    # --------------------------------------------------------

    if not LIVE_TRADING:

        print(
            "🟡 PAPER MODE"
        )

        return

    # --------------------------------------------------------
    # BALANCE SAFETY
    # --------------------------------------------------------

    if balance < 0.5:

        telegram(
            "❌ ATI FUTURES\n"
            "BALANCE TOO LOW\n\n"
            f"💰 USDT: "
            f"{balance:.6f}"
        )

        return

    # --------------------------------------------------------
    # PRICE + QUANTITY
    # --------------------------------------------------------

    try:

        current_price = get_price(
            symbol
        )

        quantity = make_quantity(
            current_price,
            best["info"]
        )

    except Exception as e:

        telegram(
            "❌ PRICE / QUANTITY ERROR\n\n"
            +
            str(e)[:1500]
        )

        return

    if quantity <= 0:

        telegram(
            f"❌ INVALID QUANTITY\n"
            f"🪙 {symbol}"
        )

        return

    print(
        f"📦 ORDER QUANTITY: "
        f"{quantity}"
    )

    # --------------------------------------------------------
    # SET LEVERAGE
    # --------------------------------------------------------

    try:

        set_leverage(
            symbol
        )

    except Exception as e:

        telegram(
            "❌ LEVERAGE ERROR\n\n"
            f"🪙 {symbol}\n"
            f"⚙️ {LEVERAGE}x\n\n"
            +
            str(e)[:1500]
        )

        return

    # --------------------------------------------------------
    # REAL MARKET ORDER
    # --------------------------------------------------------

    try:

        print(
            "🚨 REAL FUTURES ORDER"
        )

        order = market_order(
            symbol,
            side,
            quantity
        )

        order_id = order.get(
            "orderId",
            "UNKNOWN"
        )

        telegram(
            "🚨 REAL FUTURES TRADE OPENED\n\n"

            f"🪙 {symbol}\n"

            f"📈 {side}\n"

            f"🏆 Score: "
            f"{score:.2f}\n"

            f"💵 Price: "
            f"{current_price}\n"

            f"📦 Qty: "
            f"{quantity}\n"

            f"⚙️ Leverage: "
            f"{LEVERAGE}x\n"

            f"🆔 Order: "
            f"{order_id}\n"

            f"🕐 {utc_now()}"
        )

    except Exception as e:

        telegram(
            "❌ REAL FUTURES ORDER ERROR\n\n"

            f"🪙 {symbol}\n"

            f"📈 {side}\n\n"

            +
            str(e)[:1800]
        )

        return

    # --------------------------------------------------------
    # FIND POSITION
    # --------------------------------------------------------

    position = find_position(
        symbol
    )

    if not position:

        telegram(
            "⚠️ ORDER ACCEPTED\n"
            "BUT POSITION NOT FOUND\n\n"

            f"🪙 {symbol}\n"

            "🚨 SL/TP NOT CONFIRMED"
        )

        return

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    try:

        set_sl_tp(
            position
        )

        telegram(
            "🛡️ SL/TP SET\n\n"

            f"🪙 {symbol}\n"

            f"📍 Entry: "
            f"{position.get('entryPrice')}\n"

            f"🛑 SL: "
            f"{SL_PERCENT}%\n"

            f"🎯 TP: "
            f"{TP_PERCENT}%"
        )

    except Exception as e:

        telegram(
            "🚨 URGENT SL/TP ERROR\n\n"

            f"🪙 {symbol}\n"

            +
            str(e)[:1800]
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)

    print(
        f"💓 {VERSION} STARTING"
    )

    print("=" * 70)

    print(
        "☁️ STRATEGY: FAST ICHIMOKU"
    )

    print(
        f"🕯️ TIMEFRAME: "
        f"{TIMEFRAME}"
    )

    print(
        f"🚀 WORKERS: "
        f"{SCAN_WORKERS}"
    )

    print(
        f"⚙️ LEVERAGE: "
        f"{LEVERAGE}x"
    )

    print(
        f"💵 ORDER: "
        f"{ORDER_USDT} USDT"
    )

    print(
        f"🛑 SL: "
        f"{SL_PERCENT}%"
    )

    print(
        f"🎯 TP: "
        f"{TP_PERCENT}%"
    )

    print(
        f"🟢 LIVE: "
        f"{LIVE_TRADING}"
    )

    print(
        f"⏱️ LOOP: "
        f"{SCAN_INTERVAL_SECONDS}s"
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    telegram_test()

    # --------------------------------------------------------
    # KEYS
    # --------------------------------------------------------

    if not API_KEY or not API_SECRET:

        print(
            "❌ API KEY / SECRET MISSING"
        )

        telegram(
            "❌ ATI FUTURES ERROR\n"
            "TABDIL/TABDEAL API credentials missing."
        )

        return

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    try:

        account = get_account()

        print(
            "✅ FUTURES AUTH SUCCESS"
        )

        print(
            "🔓 canTrade:",
            account.get(
                "canTrade"
            )
        )

        if (
            account.get(
                "canTrade"
            )
            is False
        ):

            telegram(
                "❌ ATI FUTURES\n"
                "canTrade=False"
            )

            return

    except Exception as e:

        print(
            "❌ AUTH ERROR:",
            str(e)
        )

        telegram(
            "❌ ATI FUTURES AUTH ERROR\n\n"
            +
            str(e)[:1800]
        )

        return

    # --------------------------------------------------------
    # LOOP
    # --------------------------------------------------------

    cycle_number = 0

    while True:

        cycle_number += 1

        print()
        print("=" * 70)

        print(
            f"🔄 CYCLE #{cycle_number}"
        )

        print(
            f"🕐 {utc_now()}"
        )

        print("=" * 70)

        try:

            run_cycle()

        except Exception as e:

            print(
                "❌ CYCLE ERROR:",
                repr(e)
            )

            telegram(
                "❌ ATI CYCLE ERROR\n\n"
                +
                str(e)[:1800]
                +
                f"\n\n🔄 Cycle: "
                f"{cycle_number}"
                +
                f"\n🕐 {utc_now()}"
            )

        print(
            f"💓 NEXT SCAN IN "
            f"{SCAN_INTERVAL_SECONDS} SECONDS"
        )

        time.sleep(
            SCAN_INTERVAL_SECONDS
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "🛑 BOT STOPPED"
        )

    except Exception as e:
