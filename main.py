import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from decimal import Decimal
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed


# =========================================================
# ATI FUTURES REAL V7.2
# FAST ICHIMOKU + TELEGRAM HEARTBEAT
# SAFE ENV SETTINGS
# =========================================================

VERSION = "ATI-FUTURES-REAL-V7.2"

API_BASE = "https://api1.tabdeal.org"

PUBLIC_V1 = API_BASE + "/r/fapi/v1/"
PRIVATE_V3 = API_BASE + "/r/fapi/v3/"
WRITE_V1 = API_BASE + "/fapi/v1/"

REQUEST_TIMEOUT = 10

# =========================================================
# SAFE ENV HELPERS
# =========================================================

def env_str(name, default=""):
    try:
        value = os.getenv(name, "")
        if value is None:
            return default

        value = value.strip()

        return value if value else default

    except Exception:
        return default


def env_int(name, default):
    try:
        value = os.getenv(name, "")

        if value is None:
            return default

        value = value.strip()

        if not value:
            return default

        return int(value)

    except (ValueError, TypeError):
        print(
            f"⚠️ INVALID {name}; USING DEFAULT {default}"
        )
        return default


def env_float(name, default):
    try:
        value = os.getenv(name, "")

        if value is None:
            return default

        value = value.strip()

        if not value:
            return default

        return float(value)

    except (ValueError, TypeError):
        print(
            f"⚠️ INVALID {name}; USING DEFAULT {default}"
        )
        return default


def env_bool(name, default=False):
    try:
        value = os.getenv(
            name,
            ""
        ).strip().lower()

        if not value:
            return default

        return value in (
            "1",
            "true",
            "yes",
            "on",
        )

    except Exception:
        return default


# =========================================================
# SETTINGS
# =========================================================

TIMEFRAME = env_str(
    "TIMEFRAME",
    "5m"
)

KLINE_LIMIT = env_int(
    "KLINE_LIMIT",
    100
)

SCAN_WORKERS = env_int(
    "SCAN_WORKERS",
    12
)

MIN_SIGNAL_SCORE = env_float(
    "MIN_SIGNAL_SCORE",
    5.0
)

MAX_KIJUN_DISTANCE = env_float(
    "MAX_KIJUN_DISTANCE",
    2.5
)

SCAN_INTERVAL_SECONDS = env_int(
    "SCAN_INTERVAL_SECONDS",
    300
)

# =========================================================
# TRADING SETTINGS
# =========================================================

LIVE_TRADING = env_bool(
    "LIVE_TRADING",
    False
)

ORDER_USDT = env_float(
    "ORDER_QTY",
    2.0
)

LEVERAGE = env_int(
    "LEVERAGE",
    3
)

MAX_NEW_TRADES = env_int(
    "MAX_NEW_TRADES",
    1
)

SL_PERCENT = env_float(
    "SL_PERCENT",
    1.0
)

TP_PERCENT = env_float(
    "TP_PERCENT",
    2.0
)

# =========================================================
# API KEYS
# =========================================================

API_KEY = env_str(
    "TABDIL_API_KEY",
    env_str(
        "TABDEAL_API_KEY"
    )
)

API_SECRET = env_str(
    "TABDIL_API_SECRET",
    env_str(
        "TABDEAL_API_SECRET"
    )
)

# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_BOT_TOKEN = env_str(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = env_str(
    "TELEGRAM_CHAT_ID"
)

# =========================================================
# ICHIMOKU
# =========================================================

TENKAN_PERIOD = 9
KIJUN_PERIOD = 26
SENKOU_B_PERIOD = 52
DISPLACEMENT = 26


# =========================================================
# SESSION
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-Bot/7.2",
    "Accept": "application/json",
})


# =========================================================
# TIME
# =========================================================

def now_utc():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# =========================================================
# TELEGRAM
# =========================================================

def telegram(message):

    print()
    print("📨 TELEGRAM SEND START")

    if not TELEGRAM_BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN IS EMPTY"
        )

        return False

    if not TELEGRAM_CHAT_ID:

        print(
            "❌ TELEGRAM_CHAT_ID IS EMPTY"
        )

        return False

    try:

        url = (
            "https://api.telegram.org/bot"
            + TELEGRAM_BOT_TOKEN
            + "/sendMessage"
        )

        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": str(message),
            },
            timeout=15,
        )

        print(
            "📡 TELEGRAM HTTP:",
            response.status_code
        )

        print(
            "📡 TELEGRAM RESPONSE:",
            response.text[:1000]
        )

        if response.status_code != 200:

            print(
                "❌ TELEGRAM SEND FAILED"
            )

            return False

        try:

            result = response.json()

        except Exception:

            result = {}

        if result.get("ok") is True:

            print(
                "✅ TELEGRAM MESSAGE SENT"
            )

            return True

        print(
            "❌ TELEGRAM API RETURNED ERROR"
        )

        return False

    except Exception as e:

        print(
            "❌ TELEGRAM CONNECTION ERROR:",
            repr(e)
        )

        return False


# =========================================================
# TELEGRAM TEST
# =========================================================

def telegram_test():

    print()
    print("=" * 65)
    print("🧪 TELEGRAM CONNECTION TEST")
    print("=" * 65)

    if not TELEGRAM_BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN MISSING"
        )

        return False

    if not TELEGRAM_CHAT_ID:

        print(
            "❌ TELEGRAM_CHAT_ID MISSING"
        )

        return False

    try:

        url = (
            "https://api.telegram.org/bot"
            + TELEGRAM_BOT_TOKEN
            + "/getMe"
        )

        response = requests.get(
            url,
            timeout=15
        )

        print(
            "📡 GETME HTTP:",
            response.status_code
        )

        print(
            "📡 GETME RESPONSE:",
            response.text[:1000]
        )

        if response.status_code != 200:

            return False

        data = response.json()

        if data.get("ok") is not True:

            return False

        bot = data.get(
            "result",
            {}
        )

        username = bot.get(
            "username",
            "UNKNOWN"
        )

        print(
            f"✅ BOT FOUND: @{username}"
        )

        return telegram(
            "🧪 ATI TELEGRAM TEST\n\n"
            "✅ Telegram connection is working.\n"
            "⚡ ATI FUTURES V7.2\n"
            f"🕐 {now_utc()}"
        )

    except Exception as e:

        print(
            "❌ TELEGRAM TEST ERROR:",
            repr(e)
        )

        return False


# =========================================================
# SIGNATURE
# =========================================================

def signed_params(params=None):

    params = dict(
        params or {}
    )

    params["timestamp"] = int(
        time.time() * 1000
    )

    params.setdefault(
        "recvWindow",
        5000
    )

    query = urlencode(
        params
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    params["signature"] = signature

    return params


# =========================================================
# PUBLIC GET
# =========================================================

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
            f"{response.text[:800]}"
        )

    return response.json()


# =========================================================
# PRIVATE GET
# =========================================================

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


# =========================================================
# PRIVATE POST
# =========================================================

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


# =========================================================
# ACCOUNT
# =========================================================

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

        if isinstance(
            obj,
            dict
        ):

            asset = str(
                obj.get(
                    "asset",
                    ""
                )
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

                        value = obj.get(
                            key
                        )

                        if value is not None:

                            values.append(
                                float(value)
                            )

                    except Exception:

                        pass

            for value in obj.values():

                walk(value)

        elif isinstance(
            obj,
            list
        ):

            for item in obj:

                walk(item)

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
            "⚠️ BALANCE SOURCE 1:",
            str(e)[:300]
        )

    try:

        return extract_usdt(
            get_account()
        )

    except Exception as e:

        print(
            "⚠️ BALANCE SOURCE 2:",
            str(e)[:300]
        )

    return 0.0


# =========================================================
# EXCHANGE INFO
# =========================================================

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

        if not symbol:
            continue

        if quote != "USDT":
            continue

        if status not in (
            "TRADING",
            "ENABLED",
            "OPEN"
        ):

            continue

        result.append(
            item
        )

    return result


# =========================================================
# TICKERS
# =========================================================

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

                result[
                    symbol
                ] = item

    return result


# =========================================================
# KLINES
# =========================================================

def get_klines(
    symbol
):

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

            if len(row) < 6:

                continue

            candles.append({
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })

        except Exception:

            continue

    return candles


# =========================================================
# ICHIMOKU MIDPOINT
# =========================================================

def ichimoku_midpoint(
    highs,
    lows,
    period
):

    if len(highs) < period:

        return None

    highest = max(
        highs[-period:]
    )

    lowest = min(
        lows[-period:]
    )

    return (
        highest +
        lowest
    ) / 2.0


# =========================================================
# ICHIMOKU
# =========================================================

def calculate_ichimoku(
    candles
):

    if len(candles) < 60:

        return None

    # فقط کندل‌های بسته‌شده
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

    tenkan = ichimoku_midpoint(
        highs,
        lows,
        TENKAN_PERIOD
    )

    kijun = ichimoku_midpoint(
        highs,
        lows,
        KIJUN_PERIOD
    )

    senkou_b = ichimoku_midpoint(
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
        tenkan +
        kijun
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

    previous_tenkan = (
        ichimoku_midpoint(
            previous_highs,
            previous_lows,
            TENKAN_PERIOD
        )
    )

    previous_kijun = (
        ichimoku_midpoint(
            previous_highs,
            previous_lows,
            KIJUN_PERIOD
        )
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

    chikou_buy = False
    chikou_sell = False

    if len(closes) > 26:

        reference = closes[-27]

        chikou_buy = (
            close > reference
        )

        chikou_sell = (
            close < reference
        )

    if kijun > 0:

        kijun_distance = (
            abs(
                close - kijun
            )
            / kijun
        ) * 100.0

    else:

        kijun_distance = 999.0

    return {
        "close": close,
        "tenkan": tenkan,
        "kijun": kijun,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b,
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom,
        "above_cloud": close > cloud_top,
        "below_cloud": close < cloud_bottom,
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
    }


# =========================================================
# SIGNAL EVALUATION
# =========================================================

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

        return None

    # داخل ابر = معامله نکن
    if ichi["inside_cloud"]:

        return None

    buy_score = 0.0
    sell_score = 0.0

    buy_reasons = []
    sell_reasons = []

    # -----------------------------------------------------
    # BUY
    # -----------------------------------------------------

    if ichi["above_cloud"]:

        buy_score += 4.0

        buy_reasons.append(
            "PRICE_ABOVE_KUMO"
        )

    if ichi["tenkan"] > ichi["kijun"]:

        buy_score += 2.5

        buy_reasons.append(
            "TENKAN_GT_KIJUN"
        )

    if ichi["bullish_cloud"]:

        buy_score += 1.5

        buy_reasons.append(
            "BULLISH_KUMO"
        )

    if ichi["bullish_cross"]:

        buy_score += 3.0

        buy_reasons.append(
            "FRESH_TK_CROSS"
        )

    if ichi["chikou_buy"]:

        buy_score += 1.0

        buy_reasons.append(
            "CHIKOU_CONFIRM"
        )

    # -----------------------------------------------------
    # SELL
    # -----------------------------------------------------

    if ichi["below_cloud"]:

        sell_score += 4.0

        sell_reasons.append(
            "PRICE_BELOW_KUMO"
        )

    if ichi["tenkan"] < ichi["kijun"]:

        sell_score += 2.5

        sell_reasons.append(
            "TENKAN_LT_KIJUN"
        )

    if ichi["bearish_cloud"]:

        sell_score += 1.5

        sell_reasons.append(
            "BEARISH_KUMO"
        )

    if ichi["bearish_cross"]:

        sell_score += 3.0

        sell_reasons.append(
            "FRESH_TK_CROSS"
        )

    if ichi["chikou_sell"]:

        sell_score += 1.0

        sell_reasons.append(
            "CHIKOU_CONFIRM"
        )

    # -----------------------------------------------------
    # SELECT SIDE
    # -----------------------------------------------------

    if buy_score >= sell_score:

        side = "BUY"
        score = buy_score
        reasons = buy_reasons

    else:

        side = "SELL"
        score = sell_score
        reasons = sell_reasons

    # حداقل امتیاز
    if score < MIN_SIGNAL_SCORE:

        return None

    # جلوگیری از Chase شدید
    if (
        ichi["kijun_distance"]
        > MAX_KIJUN_DISTANCE
    ):

        if not (
            ichi["bullish_cross"]
            or
            ichi["bearish_cross"]
        ):

            return None

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
        "symbol": symbol,
        "side": side,
        "score": score,
        "price": ichi["close"],
        "tenkan": ichi["tenkan"],
        "kijun": ichi["kijun"],
        "senkou_a": ichi["senkou_a"],
        "senkou_b": ichi["senkou_b"],
        "kijun_distance": ichi[
            "kijun_distance"
        ],
        "change": change,
        "volume": volume,
        "reasons": reasons,
        "info": info,
    }


# =========================================================
# SCAN ONE SYMBOL
# =========================================================

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

        return None

    try:

        raw = get_klines(
            symbol
        )

        candles = parse_klines(
            raw
        )

        if len(candles) < 60:

            return None

        return evaluate_signal(
            symbol,
            info,
            ticker,
            candles
        )

    except Exception as e:

        print(
            f"⚠️ {symbol} SCAN ERROR: "
            f"{str(e)[:180]}"
        )

        return None


# =========================================================
# FAST MARKET SCAN
# =========================================================

def scan_market(
    symbols
):

    start = time.time()

    try:

        tickers = get_tickers()

    except Exception as e:

        print(
            "❌ TICKER ERROR:",
            str(e)
        )

        return [], 0.0

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

    print(
        f"🚀 KLINE TASKS: "
        f"{len(tasks)}"
    )

    results = []

    with ThreadPoolExecutor(
        max_workers=SCAN_WORKERS
    ) as executor:

        futures = []

        for info, ticker in tasks:

            futures.append(
                executor.submit(
                    scan_one_symbol,
                    info,
                    ticker
                )
            )

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result:

                    results.append(
                        result
                    )

            except Exception:

                pass

    results.sort(
        key=lambda x:
        x["score"],
        reverse=True
    )

    elapsed = (
        time.time() - start
    )

    return (
        results,
        elapsed
    )


# =========================================================
# POSITIONS
# =========================================================

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

                qty = abs(
                    float(
                        position.get(
                            "positionAmt",
                            0
                        )
                    )
                )

            except Exception:

                qty = 0.0

            if qty > 0:

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


# =========================================================
# PRICE
# =========================================================

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


# =========================================================
# LEVERAGE
# =========================================================

def set_leverage(
    symbol
):

    return private_post(
        WRITE_V1 + "leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE,
        }
    )


# =========================================================
# QUANTITY
# =========================================================

def make_quantity(
    price,
    info
):

    if price <= 0:

        return 0.0

    quantity = (
        ORDER_USDT /
        price
    )

    step = 0.0
    minimum = 0.0
    min_notional = 0.0

    for item in info.get(
        "filters",
        []
    ):

        filter_type = item.get(
            "filterType"
        )

        if filter_type == "LOT_SIZE":

            try:

                step = float(
                    item.get(
                        "stepSize",
                        0
                    )
                )

            except Exception:

                pass

            try:

                minimum = float(
                    item.get(
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

                min_notional = float(
                    item.get(
                        "notional",
                        item.get(
                            "minNotional",
                            0
                        )
                    )
                )

            except Exception:

                pass

    if step > 0:

        q = Decimal(
            str(quantity)
        )

        s = Decimal(
            str(step)
        )

        quantity = float(
            (q // s) * s
        )

    if quantity < minimum:

        quantity = minimum

    if (
        min_notional > 0
        and
        quantity * price
        < min_notional
    ):

        quantity = (
            min_notional /
            price
        )

        if step > 0:

            q = Decimal(
                str(quantity)
            )

            s = Decimal(
                str(step)
            )

            quantity = float(
                (q // s + 1) * s
            )

    return quantity


# =========================================================
# MARKET ORDER
# =========================================================

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


# =========================================================
# FIND POSITION
# =========================================================

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

                    if position.get(
                        "symbol"
                    ) != symbol:

                        continue

                    try:

                        qty = float(
                            position.get(
                                "positionAmt",
                                0
                            )
                        )

                    except Exception:

                        qty = 0.0

                    if abs(qty) > 0:

                        return position

        except Exception:

            pass

        time.sleep(1)

    return None


# =========================================================
# SL TP
# =========================================================

def set_sl_tp(
    position
):

    symbol = position.get(
        "symbol"
    )

    position_id = position.get(
        "positionId"
    )

    try:

        entry = float(
            position.get(
                "entryPrice",
                0
            )
        )

        quantity = float(
            position.get(
                "positionAmt",
                0
            )
        )

    except Exception:

        return None

    if entry <= 0:

        return None

    if quantity > 0:

        sl = entry * (
            1 -
            SL_PERCENT / 100
        )

        tp = entry * (
            1 +
            TP_PERCENT / 100
        )

    else:

        sl = entry * (
            1 +
            SL_PERCENT / 100
        )

        tp = entry * (
            1 -
            TP_PERCENT / 100
        )

    return private_post(
        WRITE_V1 + "positionSlTp",
        {
            "positionId": position_id,
            "symbol": symbol,
            "slPrice": sl,
            "tpPrice": tp,
            "workingType": "MARK_PRICE",
        }
    )


# =========================================================
# RUN ONE CYCLE
# =========================================================

def run_cycle():

    print()
    print("=" * 70)
    print(
        f"⚡ ATI FUTURES V7.2 | "
        f"{now_utc()}"
    )
    print("=" * 70)

    print(
        f"☁️ ICHIMOKU: "
        f"{TENKAN_PERIOD}/"
        f"{KIJUN_PERIOD}/"
        f"{SENKOU_B_PERIOD}"
    )

    print(
        f"🕯️ TIMEFRAME: {TIMEFRAME}"
    )

    print(
        f"🚀 WORKERS: {SCAN_WORKERS}"
    )

    print(
        f"🏆 MIN SCORE: "
        f"{MIN_SIGNAL_SCORE}"
    )

    print(
        f"⚙️ LEVERAGE: {LEVERAGE}x"
    )

    print(
        f"💵 ORDER: {ORDER_USDT} USDT"
    )

    print(
        f"🟢 LIVE: {LIVE_TRADING}"
    )

    # -----------------------------------------------------
    # BALANCE
    # -----------------------------------------------------

    balance = get_usdt_balance()

    print(
        f"💰 USDT: {balance}"
    )

    # -----------------------------------------------------
    # POSITIONS
    # -----------------------------------------------------

    positions = get_open_positions()

    print(
        f"📌 OPEN POSITIONS: "
        f"{len(positions)}"
    )

    if len(positions) >= MAX_NEW_TRADES:

        telegram(
            "⛔ ATI FUTURES\n"
            "MAX OPEN POSITIONS REACHED\n"
            f"📌 Positions: {len(positions)}\n"
            f"💰 USDT: {balance}\n"
            f"🕐 {now_utc()}"
        )

        return

    # -----------------------------------------------------
    # SYMBOLS
    # -----------------------------------------------------

    symbols = get_symbols()

    print(
        f"📊 FUTURES MARKETS: "
        f"{len(symbols)}"
    )

    if not symbols:

        telegram(
            "❌ ATI FUTURES\n"
            "No Futures symbols found."
        )

        return

    # -----------------------------------------------------
    # SCAN
    # -----------------------------------------------------

    results, elapsed = scan_market(
        symbols
    )

    print()
    print(
        f"⏱️ SCAN TIME: "
        f"{elapsed:.2f}s"
    )

    # -----------------------------------------------------
    # NO SIGNAL
    # -----------------------------------------------------

    if not results:

        print(
            "❌ NO ICHIMOKU SIGNAL"
        )

        telegram(
            "💓 ATI FUTURES ALIVE\n"
            f"📊 Markets: {len(symbols)}\n"
            "☁️ Ichimoku: NO SIGNAL\n"
            f"⏱️ Scan: {elapsed:.2f}s\n"
            f"💰 USDT: {balance}\n"
            f"🟢 LIVE: {LIVE_TRADING}\n"
            f"🕐 {now_utc()}"
        )

        return

    # -----------------------------------------------------
    # BEST SIGNAL
    # -----------------------------------------------------

    best = results[0]

    symbol = best[
        "symbol"
    ]

    side = best[
        "side"
    ]

    score = best[
        "score"
    ]

    price = best[
        "price"
    ]

    print()
    print("=" * 70)
    print(
        "🚨 BEST ICHIMOKU SIGNAL"
    )
    print("=" * 70)

    print(
        f"🪙 SYMBOL: {symbol}"
    )

    print(
        f"📈 SIDE: {side}"
    )

    print(
        f"🏆 SCORE: {score:.2f}"
    )

    print(
        f"💵 PRICE: {price}"
    )

    print(
        f"〽️ TENKAN: "
        f"{best['tenkan']}"
    )

    print(
        f"〽️ KIJUN: "
        f"{best['kijun']}"
    )

    print(
        f"☁️ SENKOU A: "
        f"{best['senkou_a']}"
    )

    print(
        f"☁️ SENKOU B: "
        f"{best['senkou_b']}"
    )

    print(
        f"📊 24H CHANGE: "
        f"{best['change']:.2f}%"
    )

    print(
        "🧠 REASONS:"
    )

    for reason in best[
        "reasons"
    ]:

        print(
            "   ✅",
            reason
        )

    # -----------------------------------------------------
    # TELEGRAM SIGNAL
    # -----------------------------------------------------

    telegram(
        "🚨 ATI FAST ICHIMOKU SIGNAL\n\n"
        f"🪙 {symbol}\n"
        f"📈 SIDE: {side}\n"
        f"🏆 SCORE: {score:.2f}\n"
        f"💵 PRICE: {price}\n\n"
        f"☁️ Tenkan: "
        f"{best['tenkan']}\n"
        f"☁️ Kijun: "
        f"{best['kijun']}\n"
        f"☁️ Senkou A: "
        f"{best['senkou_a']}\n"
        f"☁️ Senkou B: "
        f"{best['senkou_b']}\n\n"
        f"📊 24H: "
        f"{best['change']:.2f}%\n"
        f"🧠 "
        + ", ".join(
            best["reasons"]
        )
        + "\n\n"
        f"⏱️ Scan: "
        f"{elapsed:.2f}s\n"
        f"🟢 LIVE: "
        f"{LIVE_TRADING}\n"
        f"🕐 {now_utc()}"
    )

    # -----------------------------------------------------
    # PAPER MODE
    # -----------------------------------------------------

    if not LIVE_TRADING:

        print(
            "🟡 PAPER MODE - "
            "NO REAL ORDER"
        )

        return

    # -----------------------------------------------------
    # BALANCE
    # -----------------------------------------------------

    if balance < 0.5:

        telegram(
            "❌ BALANCE TOO LOW\n"
            f"💰 USDT: {balance}"
        )

        return

    # -----------------------------------------------------
    # PRICE + QUANTITY
    # -----------------------------------------------------

    try:

        current_price = get_price(
            symbol
        )

        quantity = make_quantity(
            current_price,
            best["info"]
        )

    except Exception as e:

        print(
            "❌ QUANTITY ERROR:",
            str(e)
        )

        telegram(
            "❌ PRICE / QUANTITY ERROR\n\n"
            + str(e)[:1500]
        )

        return

    print(
        f"📦 QUANTITY: "
        f"{quantity}"
    )

    if quantity <= 0:

        telegram(
            f"❌ INVALID QUANTITY\n"
            f"🪙 {symbol}"
        )

        return

    # -----------------------------------------------------
    # LEVERAGE
    # -----------------------------------------------------

    try:

        print(
            f"⚙️ SET LEVERAGE "
            f"{LEVERAGE}x"
        )

        set_leverage(
            symbol
        )

        print(
            "✅ LEVERAGE SET"
        )

    except Exception as e:

        print(
            "❌ LEVERAGE ERROR:",
            str(e)
        )

        telegram(
            "❌ LEVERAGE ERROR\n\n"
            f"🪙 {symbol}\n"
            f"⚙️ {LEVERAGE}x\n\n"
            + str(e)[:1500]
        )

        return

    # -----------------------------------------------------
    # REAL ORDER
    # -----------------------------------------------------

    try:

        print()
        print(
            "🚨 SENDING REAL FUTURES ORDER"
        )

        order = market_order(
            symbol,
            side,
            quantity
        )

        print(
            "✅ REAL ORDER SUCCESS"
        )

        print(
            order
        )

        telegram(
            "🚨 REAL FUTURES TRADE OPENED\n\n"
            f"🪙 {symbol}\n"
            f"📈 {side}\n"
            f"🏆 Score: {score:.2f}\n"
            f"💵 Price: {current_price}\n"
            f"📦 Qty: {quantity}\n"
            f"⚙️ Leverage: {LEVERAGE}x\n"
            f"🆔 Order: "
            f"{order.get('orderId')}\n"
            f"🕐 {now_utc()}"
        )

    except Exception as e:

        print(
            "❌ REAL ORDER ERROR:",
            str(e)
        )

        telegram(
            "❌ REAL FUTURES ORDER ERROR\n\n"
            f"🪙 {symbol}\n"
            f"📈 {side}\n\n"
            + str(e)[:1800]
        )

        return

    # -----------------------------------------------------
    # FIND POSITION
    # -----------------------------------------------------

    print(
        "🔎 FINDING POSITION..."
    )

    position = find_position(
        symbol
    )

    if not position:

        print(
            "⚠️ POSITION NOT FOUND"
        )

        telegram(
            "⚠️ ORDER ACCEPTED\n"
            "BUT POSITION NOT FOUND\n\n"
            f"🪙 {symbol}\n"
            "🚨 SL/TP NOT CONFIRMED"
        )

        return

    entry = position.get(
        "entryPrice"
    )

    print(
        f"✅ POSITION OPEN"
    )

    print(
        f"📍 ENTRY: {entry}"
    )

    # -----------------------------------------------------
    # SL / TP
    # -----------------------------------------------------

    try:

        result = set_sl_tp(
            position
        )

        print(
            "✅ SL/TP SET"
        )

        print(
            result
        )

        telegram(
            "🛡️ SL/TP SET\n\n"
            f"🪙 {symbol}\n"
            f"📍 Entry: {entry}\n"
            f"🛑 SL: {SL_PERCENT}%\n"
            f"🎯 TP: {TP_PERCENT}%"
        )

    except Exception as e:

        print(
            "❌ SL/TP ERROR:",
            str(e)
        )

        telegram(
            "🚨 URGENT SL/TP ERROR\n\n"
            f"🪙 {symbol}\n"
            f"📍 Entry: {entry}\n\n"
            + str(e)[:1800]
        )


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("=" * 70)
    print(
        "💓 ATI FUTURES V7.2 STARTING"
    )
    print("=" * 70)

    print(
        f"⚡ VERSION: {VERSION}"
    )

    print(
        f"☁️ STRATEGY: FAST ICHIMOKU"
    )

    print(
        f"🕯️ TIMEFRAME: {TIMEFRAME}"
    )

    print(
        f"⚙️ LEVERAGE: {LEVERAGE}x"
    )

    print(
        f"💵 ORDER: {ORDER_USDT} USDT"
    )

    print(
        f"🛑 SL: {SL_PERCENT}%"
    )

    print(
        f"🎯 TP: {TP_PERCENT}%"
    )

    print(
        f"🟢 LIVE: {LIVE_TRADING}"
    )

    print(
        f"🚀 WORKERS: {SCAN_WORKERS}"
    )

    print(
        f"⏱️ LOOP: "
        f"{SCAN_INTERVAL_SECONDS}s"
    )

    # =====================================================
    # TELEGRAM TEST
    # =====================================================

    telegram_ok = telegram_test()

    if telegram_ok:

        print(
            "✅ TELEGRAM READY"
        )

    else:

        print(
            "⚠️ TELEGRAM TEST FAILED"
        )

    # =====================================================
    # API CHECK
    # =====================================================

    if not API_KEY:

        print(
            "❌ API KEY MISSING"
        )

        telegram(
            "❌ ATI FUTURES ERROR\n"
            "TABDIL/TABDEAL API KEY missing."
        )

        return

    if not API_SECRET:

        print(
            "❌ API SECRET MISSING"
        )

        telegram(
            "❌ ATI FUTURES ERROR\n"
            "TABDIL/TABDEAL API SECRET missing."
        )

        return

    # =====================================================
    # AUTH
    # =====================================================

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

        if account.get(
            "canTrade"
        ) is False:

            telegram(
                "❌ FUTURES canTrade=False"
            )

            return

    except Exception as e:

        print(
            "❌ AUTH ERROR:",
            str(e)
        )

        telegram(
            "❌ ATI FUTURES AUTH ERROR\n\n"
            + str(e)[:1800]
        )

        return

    # =====================================================
    # CONTINUOUS LOOP
    # =====================================================

    cycle = 0

    while True:

        cycle += 1

        print()
        print("=" * 70)
        print(
            f"🔄 CYCLE #{cycle}"
        )
        print(
            f"🕐 {now_utc()}"
        )
        print("=" * 70)

        try:

            run_cycle()

        except Exception as e:

            print()
            print(
                "❌ CYCLE ERROR"
            )

            print(
                repr(e)
            )

            telegram(
                "❌ ATI CYCLE ERROR\n\n"
                + str(e)[:1800]
                + "\n\n"
                f"🔄 Cycle: {cycle}\n"
                f"🕐 {now_utc()}"
            )

        print()
        print(
            f"💓 NEXT SCAN IN "
            f"{SCAN_INTERVAL_SECONDS} SECONDS"
        )

        time.sleep(
            SCAN_INTERVAL_SECONDS
        )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "🛑 BOT STOPPED"
        )

    except Exception as e:

        print(
            "❌ FATAL ERROR:",
            repr(e)
        )

        telegram(
            "❌ ATI FUTURES FATAL ERROR\n\n"
            + str(e)[:1800]
        )
