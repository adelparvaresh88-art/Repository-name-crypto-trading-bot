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
# ATI FUTURES REAL V7
# FAST ICHIMOKU SCANNER
# =========================================================

VERSION = "ATI-FUTURES-REAL-V7-FAST-ICHIMOKU"

API_BASE = "https://api1.tabdeal.org"

PUBLIC_V1 = API_BASE + "/r/fapi/v1/"
PRIVATE_V3 = API_BASE + "/r/fapi/v3/"
WRITE_V1 = API_BASE + "/fapi/v1/"

REQUEST_TIMEOUT = 8

# =========================================================
# FAST SCAN SETTINGS
# =========================================================

INTERVAL = os.getenv(
    "TIMEFRAME",
    "5m"
).strip()

KLINE_LIMIT = int(
    os.getenv(
        "KLINE_LIMIT",
        "100"
    )
)

MAX_WORKERS = int(
    os.getenv(
        "SCAN_WORKERS",
        "12"
    )
)

# حداقل امتیاز برای سیگنال
MIN_SIGNAL_SCORE = float(
    os.getenv(
        "MIN_SIGNAL_SCORE",
        "5.0"
    )
)

# تعداد کاندیدهای نهایی
MAX_SIGNAL_CANDIDATES = int(
    os.getenv(
        "MAX_SIGNAL_CANDIDATES",
        "5"
    )
)

# حداکثر فاصله قیمت از Kijun
MAX_KIJUN_DISTANCE = float(
    os.getenv(
        "MAX_KIJUN_DISTANCE",
        "2.5"
    )
)

# =========================================================
# ENV HELPERS
# =========================================================

def env_str(name, default=""):

    value = os.getenv(
        name,
        ""
    )

    if value and value.strip():

        return value.strip()

    return default


def env_int(name, default):

    try:

        value = os.getenv(
            name,
            ""
        ).strip()

        return int(value) if value else default

    except Exception:

        return default


def env_float(name, default):

    try:

        value = os.getenv(
            name,
            ""
        ).strip()

        return float(value) if value else default

    except Exception:

        return default


def env_bool(name, default=False):

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


# =========================================================
# SETTINGS
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

TELEGRAM_BOT_TOKEN = env_str(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = env_str(
    "TELEGRAM_CHAT_ID"
)

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

SCAN_LIMIT = env_int(
    "SCAN_LIMIT",
    0
)

# =========================================================
# ICHIMOKU
# =========================================================

TENKAN_PERIOD = 9
KIJUN_PERIOD = 26
SENKOU_B_PERIOD = 52
DISPLACEMENT = 26


# =========================================================
# HTTP SESSION
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-Bot/7.0",
    "Accept": "application/json",
})


# =========================================================
# TELEGRAM
# =========================================================

def telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        return

    if not TELEGRAM_CHAT_ID:
        return

    try:

        url = (
            "https://api.telegram.org/bot"
            + TELEGRAM_BOT_TOKEN
            + "/sendMessage"
        )

        requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": str(message),
            },
            timeout=8,
        )

    except Exception as e:

        print(
            "TELEGRAM ERROR:",
            str(e)[:300]
        )


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
        hashlib.sha256,
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
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:

        raise Exception(
            f"HTTP {response.status_code}: "
            f"{response.text[:800]}"
        )

    try:

        return response.json()

    except Exception:

        raise Exception(
            "INVALID JSON RESPONSE: "
            + response.text[:800]
        )


# =========================================================
# PRIVATE GET
# =========================================================

def private_get(
    url,
    params=None
):

    if not API_KEY:

        raise Exception(
            "API KEY missing"
        )

    if not API_SECRET:

        raise Exception(
            "API SECRET missing"
        )

    signed = signed_params(
        params
    )

    response = session.get(
        url,
        params=signed,
        headers={
            "X-MBX-APIKEY": API_KEY,
        },
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:

        raise Exception(
            f"HTTP {response.status_code}: "
            f"{response.text[:1200]}"
        )

    try:

        return response.json()

    except Exception:

        raise Exception(
            "INVALID JSON RESPONSE: "
            + response.text[:1200]
        )


# =========================================================
# PRIVATE POST
# =========================================================

def private_post(
    url,
    params=None
):

    if not API_KEY:

        raise Exception(
            "API KEY missing"
        )

    if not API_SECRET:

        raise Exception(
            "API SECRET missing"
        )

    signed = signed_params(
        params
    )

    response = session.post(
        url,
        params=signed,
        headers={
            "X-MBX-APIKEY": API_KEY,
        },
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code not in (
        200,
        201,
    ):

        raise Exception(
            f"HTTP {response.status_code}: "
            f"{response.text[:1500]}"
        )

    try:

        return response.json()

    except Exception:

        raise Exception(
            "INVALID JSON RESPONSE: "
            + response.text[:1500]
        )


# =========================================================
# ACCOUNT
# =========================================================

def get_account():

    return private_get(
        PRIVATE_V3 + "account"
    )


# =========================================================
# BALANCE
# =========================================================

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

    positive = [
        x
        for x in values
        if x >= 0
    ]

    return max(
        positive,
        default=0.0
    )


def get_usdt_balance():

    results = []

    for func in (
        get_balance,
        get_account,
    ):

        try:

            results.append(
                extract_usdt(
                    func()
                )
            )

        except Exception as e:

            print(
                "BALANCE SOURCE ERROR:",
                str(e)[:300]
            )

    return max(
        results,
        default=0.0
    )


# =========================================================
# EXCHANGE INFO
# =========================================================

def get_exchange_info():

    return public_get(
        PUBLIC_V1 + "exchangeInfo"
    )


# =========================================================
# SYMBOLS
# =========================================================

def get_symbols():

    data = get_exchange_info()

    if not isinstance(
        data,
        dict
    ):

        raise Exception(
            "exchangeInfo returned invalid data"
        )

    symbols = data.get(
        "symbols",
        []
    )

    result = []

    for item in symbols:

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

        if not symbol:
            continue

        if quote != "USDT":
            continue

        if status not in (
            "TRADING",
            "ENABLED",
            "OPEN",
        ):

            continue

        result.append(
            item
        )

    if SCAN_LIMIT > 0:

        return result[
            :SCAN_LIMIT
        ]

    return result


# =========================================================
# 24H TICKERS
# =========================================================

def get_all_tickers():

    return public_get(
        PUBLIC_V1 + "ticker/24hr"
    )


def normalize_tickers(data):

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

    elif isinstance(
        data,
        dict
    ):

        nested = data.get(
            "data"
        )

        if isinstance(
            nested,
            list
        ):

            return normalize_tickers(
                nested
            )

        symbol = str(
            data.get(
                "symbol",
                ""
            )
        ).upper()

        if symbol:

            result[
                symbol
            ] = data

    return result


# =========================================================
# KLINES
# =========================================================

def get_klines(
    symbol,
    interval=INTERVAL,
    limit=KLINE_LIMIT
):

    return public_get(
        PUBLIC_V1 + "klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
    )


# =========================================================
# KLINE PARSER
# =========================================================

def parse_klines(data):

    result = []

    if not isinstance(
        data,
        list
    ):

        return result

    for row in data:

        try:

            if len(row) < 6:
                continue

            result.append({
                "open_time": int(
                    row[0]
                ),
                "open": float(
                    row[1]
                ),
                "high": float(
                    row[2]
                ),
                "low": float(
                    row[3]
                ),
                "close": float(
                    row[4]
                ),
                "volume": float(
                    row[5]
                ),
                "close_time": int(
                    row[6]
                ) if len(row) > 6 else 0,
            })

        except Exception:

            continue

    return result


# =========================================================
# ICHIMOKU
# =========================================================

def midpoint(
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


def calculate_ichimoku(
    candles
):

    minimum = (
        SENKOU_B_PERIOD
        + DISPLACEMENT
        + 5
    )

    if len(candles) < minimum:

        return None

    highs = [
        x["high"]
        for x in candles
    ]

    lows = [
        x["low"]
        for x in candles
    ]

    closes = [
        x["close"]
        for x in candles
    ]

    # Last CLOSED candle.
    # We deliberately ignore the newest candle
    # because it may still be forming.
    idx = len(candles) - 2

    if idx < SENKOU_B_PERIOD:

        return None

    # Work with data up to the closed candle.
    h = highs[
        :idx + 1
    ]

    l = lows[
        :idx + 1
    ]

    c = closes[
        :idx + 1
    ]

    tenkan = midpoint(
        h,
        l,
        TENKAN_PERIOD
    )

    kijun = midpoint(
        h,
        l,
        KIJUN_PERIOD
    )

    senkou_b = midpoint(
        h,
        l,
        SENKOU_B_PERIOD
    )

    if (
        tenkan is None
        or kijun is None
        or senkou_b is None
    ):

        return None

    # Senkou A is based on Tenkan/Kijun.
    senkou_a = (
        tenkan +
        kijun
    ) / 2.0

    close = c[-1]

    # Current Kumo
    cloud_top = max(
        senkou_a,
        senkou_b
    )

    cloud_bottom = min(
        senkou_a,
        senkou_b
    )

    # Previous CLOSED candle
    if len(c) >= 2:

        prev_h = h[:-1]
        prev_l = l[:-1]

        prev_tenkan = midpoint(
            prev_h,
            prev_l,
            TENKAN_PERIOD
        )

        prev_kijun = midpoint(
            prev_h,
            prev_l,
            KIJUN_PERIOD
        )

        prev_close = c[-2]

    else:

        prev_tenkan = tenkan
        prev_kijun = kijun
        prev_close = close

    # Chikou comparison:
    # current closed close compared with price
    # 26 candles back.
    chikou_ok_buy = False
    chikou_ok_sell = False

    chikou_index = (
        len(c) -
        1 -
        DISPLACEMENT
    )

    if chikou_index >= 0:

        chikou_reference = c[
            chikou_index
        ]

        chikou_ok_buy = (
            close >
            chikou_reference
        )

        chikou_ok_sell = (
            close <
            chikou_reference
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

    bullish_cloud = (
        senkou_a >
        senkou_b
    )

    bearish_cloud = (
        senkou_a <
        senkou_b
    )

    above_cloud = (
        close >
        cloud_top
    )

    below_cloud = (
        close <
        cloud_bottom
    )

    inside_cloud = (
        not above_cloud
        and not below_cloud
    )

    kijun_distance = 0.0

    if kijun > 0:

        kijun_distance = (
            abs(
                close -
                kijun
            )
            /
            kijun
        ) * 100.0

    return {
        "close": close,
        "tenkan": tenkan,
        "kijun": kijun,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b,
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom,
        "above_cloud": above_cloud,
        "below_cloud": below_cloud,
        "inside_cloud": inside_cloud,
        "bullish_cloud": bullish_cloud,
        "bearish_cloud": bearish_cloud,
        "bullish_cross": bullish_cross,
        "bearish_cross": bearish_cross,
        "chikou_buy": chikou_ok_buy,
        "chikou_sell": chikou_ok_sell,
        "kijun_distance": kijun_distance,
        "prev_close": prev_close,
    }


# =========================================================
# FAST ICHIMOKU SIGNAL
# =========================================================

def evaluate_ichimoku(
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

    close = ichi[
        "close"
    ]

    tenkan = ichi[
        "tenkan"
    ]

    kijun = ichi[
        "kijun"
    ]

    score_buy = 0.0
    score_sell = 0.0

    buy_reasons = []
    sell_reasons = []

    # =====================================================
    # BUY
    # =====================================================

    if ichi[
        "above_cloud"
    ]:

        score_buy += 4.0

        buy_reasons.append(
            "PRICE_ABOVE_KUMO"
        )

    elif close > kijun:

        score_buy += 1.5

        buy_reasons.append(
            "PRICE_ABOVE_KIJUN"
        )

    if tenkan > kijun:

        score_buy += 2.5

        buy_reasons.append(
            "TENKAN_GT_KIJUN"
        )

    if ichi[
        "bullish_cloud"
    ]:

        score_buy += 1.5

        buy_reasons.append(
            "BULLISH_KUMO"
        )

    if ichi[
        "bullish_cross"
    ]:

        score_buy += 3.0

        buy_reasons.append(
            "FRESH_TK_CROSS"
        )

    if ichi[
        "chikou_buy"
    ]:

        score_buy += 1.0

        buy_reasons.append(
            "CHIKOU_CONFIRM"
        )

    # =====================================================
    # SELL
    # =====================================================

    if ichi[
        "below_cloud"
    ]:

        score_sell += 4.0

        sell_reasons.append(
            "PRICE_BELOW_KUMO"
        )

    elif close < kijun:

        score_sell += 1.5

        sell_reasons.append(
            "PRICE_BELOW_KIJUN"
        )

    if tenkan < kijun:

        score_sell += 2.5

        sell_reasons.append(
            "TENKAN_LT_KIJUN"
        )

    if ichi[
        "bearish_cloud"
    ]:

        score_sell += 1.5

        sell_reasons.append(
            "BEARISH_KUMO"
        )

    if ichi[
        "bearish_cross"
    ]:

        score_sell += 3.0

        sell_reasons.append(
            "FRESH_TK_CROSS"
        )

    if ichi[
        "chikou_sell"
    ]:

        score_sell += 1.0

        sell_reasons.append(
            "CHIKOU_CONFIRM"
        )

    # =====================================================
    # SELECT SIDE
    # =====================================================

    if score_buy >= score_sell:

        side = "BUY"
        score = score_buy
        reasons = buy_reasons

    else:

        side = "SELL"
        score = score_sell
        reasons = sell_reasons

    # =====================================================
    # DO NOT TRADE INSIDE KUMO
    # =====================================================

    if ichi[
        "inside_cloud"
    ]:

        return None

    # =====================================================
    # KIJUN DISTANCE PROTECTION
    # =====================================================

    if (
        ichi["kijun_distance"]
        > MAX_KIJUN_DISTANCE
    ):

        # Still allow fresh cross because it can
        # be an early opportunity.
        if not (
            ichi["bullish_cross"]
            or
            ichi["bearish_cross"]
        ):

            return None

    # =====================================================
    # FINAL MIN SCORE
    # =====================================================

    if score < MIN_SIGNAL_SCORE:

        return None

    # =====================================================
    # 24H INFO
    # =====================================================

    try:

        volume = float(
            ticker.get(
                "quoteVolume",
                0
            )
        )

    except Exception:

        volume = 0.0

    try:

        change = float(
            ticker.get(
                "priceChangePercent",
                0
            )
        )

    except Exception:

        change = 0.0

    return {
        "symbol": symbol,
        "side": side,
        "score": score,
        "close": close,
        "tenkan": tenkan,
        "kijun": kijun,
        "senkou_a": ichi[
            "senkou_a"
        ],
        "senkou_b": ichi[
            "senkou_b"
        ],
        "kijun_distance": ichi[
            "kijun_distance"
        ],
        "volume": volume,
        "change": change,
        "reasons": reasons,
        "info": info,
        "ticker": ticker,
        "ichimoku": ichi,
    }


# =========================================================
# ONE SYMBOL SCAN
# =========================================================

def scan_one_symbol(
    item,
    ticker
):

    symbol = str(
        item.get(
            "symbol",
            ""
        )
    ).upper()

    if not symbol:

        return None

    try:

        raw = get_klines(
            symbol,
            INTERVAL,
            KLINE_LIMIT
        )

        candles = parse_klines(
            raw
        )

        if len(candles) < 80:

            return None

        return evaluate_ichimoku(
            symbol,
            item,
            ticker,
            candles
        )

    except Exception as e:

        print(
            f"⚠️ {symbol} ERROR: "
            f"{str(e)[:150]}"
        )

        return None


# =========================================================
# FAST MARKET SCANNER
# =========================================================

def scan_market(
    symbols
):

    print()
    print("=" * 60)
    print("⚡ ATI FAST ICHIMOKU SCANNER")
    print("=" * 60)

    symbol_map = {}

    for item in symbols:

        symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).upper()

        if symbol:

            symbol_map[
                symbol
            ] = item

    scanned = len(
        symbol_map
    )

    print(
        f"📊 MARKETS: {scanned}"
    )

    # =====================================================
    # 24H TICKERS
    # =====================================================

    try:

        raw = get_all_tickers()

        tickers = normalize_tickers(
            raw
        )

    except Exception as e:

        print(
            "⚠️ TICKER ERROR:",
            str(e)[:300]
        )

        tickers = {}

    print(
        f"📡 TICKERS: "
        f"{len(tickers)}"
    )

    # =====================================================
    # BUILD TASKS
    # =====================================================

    tasks = []

    for symbol, info in symbol_map.items():

        ticker = tickers.get(
            symbol
        )

        if ticker is None:

            continue

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

    # =====================================================
    # PARALLEL ICHIMOKU SCAN
    # =====================================================

    results = []

    start_time = time.time()

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {}

        for info, ticker in tasks:

            future = executor.submit(
                scan_one_symbol,
                info,
                ticker
            )

            future_map[
                future
            ] = info.get(
                "symbol"
            )

        for future in as_completed(
            future_map
        ):

            try:

                result = future.result()

                if result:

                    results.append(
                        result
                    )

            except Exception:

                pass

    elapsed = (
        time.time()
        - start_time
    )

    # =====================================================
    # SORT
    # =====================================================

    results.sort(
        key=lambda x:
        x["score"],
        reverse=True
    )

    print()
    print(
        f"⏱️ SCAN TIME: "
        f"{elapsed:.2f}s"
    )

    print(
        f"☁️ ICHIMOKU VALID: "
        f"{len(results)}"
    )

    # =====================================================
    # TOP RESULTS
    # =====================================================

    if results:

        print()
        print(
            "🏆 TOP ICHIMOKU SIGNALS"
        )

        for index, item in enumerate(
            results[
                :MAX_SIGNAL_CANDIDATES
            ],
            start=1
        ):

            print(
                f"{index}. "
                f"{item['symbol']} | "
                f"{item['side']} | "
                f"Score={item['score']:.2f} | "
                f"Price={item['close']:.8f} | "
                f"TK={item['tenkan']:.8f}/"
                f"{item['kijun']:.8f}"
            )

            print(
                "   "
                + ", ".join(
                    item[
                        "reasons"
                    ]
                )
            )

    return (
        results,
        scanned,
        elapsed,
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

        if isinstance(
            data,
            list
        ):

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
            "POSITION ERROR:",
            str(e)[:500]
        )

        return []


# =========================================================
# LEVERAGE
# =========================================================

def change_leverage(
    symbol
):

    return private_post(
        WRITE_V1 + "leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE,
        },
    )


# =========================================================
# SYMBOL RULES
# =========================================================

def symbol_rules(
    info
):

    step = 0.0
    min_qty = 0.0
    min_notional = 0.0

    filters = info.get(
        "filters",
        []
    )

    for item in filters:

        typ = item.get(
            "filterType"
        )

        if typ == "LOT_SIZE":

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

                min_qty = float(
                    item.get(
                        "minQty",
                        0
                    )
                )

            except Exception:
                pass

        elif typ in (
            "MIN_NOTIONAL",
            "NOTIONAL",
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

    return (
        step,
        min_qty,
        min_notional,
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

    (
        step,
        min_qty,
        min_notional,
    ) = symbol_rules
