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
# ATI FUTURES REAL V7.1
# FAST ICHIMOKU + TELEGRAM HEARTBEAT
# =========================================================

VERSION = "ATI-FUTURES-REAL-V7.1"

API_BASE = "https://api1.tabdeal.org"

PUBLIC_V1 = API_BASE + "/r/fapi/v1/"
PRIVATE_V3 = API_BASE + "/r/fapi/v3/"
WRITE_V1 = API_BASE + "/fapi/v1/"

TIMEFRAME = os.getenv("TIMEFRAME", "5m")
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "100"))

SCAN_WORKERS = int(os.getenv("SCAN_WORKERS", "12"))
MIN_SCORE = float(os.getenv("MIN_SIGNAL_SCORE", "5"))
MAX_KIJUN_DISTANCE = float(
    os.getenv("MAX_KIJUN_DISTANCE", "2.5")
)

# هر چند ثانیه یک بار اسکن
SCAN_INTERVAL = int(
    os.getenv("SCAN_INTERVAL_SECONDS", "300")
)

REQUEST_TIMEOUT = 10

# =========================================================
# ICHIMOKU
# =========================================================

TENKAN = 9
KIJUN = 26
SENKOU_B = 52
DISPLACEMENT = 26

# =========================================================
# TRADING
# =========================================================

LIVE_TRADING = os.getenv(
    "LIVE_TRADING",
    "false"
).lower() in (
    "true",
    "1",
    "yes",
    "on",
)

ORDER_USDT = float(
    os.getenv("ORDER_QTY", "2")
)

LEVERAGE = int(
    os.getenv("LEVERAGE", "3")
)

MAX_NEW_TRADES = int(
    os.getenv("MAX_NEW_TRADES", "1")
)

SL_PERCENT = float(
    os.getenv("SL_PERCENT", "1")
)

TP_PERCENT = float(
    os.getenv("TP_PERCENT", "2")
)

# =========================================================
# API KEYS
# =========================================================

API_KEY = os.getenv(
    "TABDIL_API_KEY",
    os.getenv("TABDEAL_API_KEY", "")
).strip()

API_SECRET = os.getenv(
    "TABDIL_API_SECRET",
    os.getenv("TABDEAL_API_SECRET", "")
).strip()

# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-Bot/7.1",
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
            "❌ TELEGRAM API ERROR"
        )

        return False

    except Exception as e:

        print(
            "❌ TELEGRAM CONNECTION ERROR:",
            repr(e)
        )

        return False


# =========================================================
# TELEGRAM BOT TEST
# =========================================================

def telegram_test():

    print()
    print("=" * 60)
    print("🧪 TELEGRAM CONNECTION TEST")
    print("=" * 60)

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
            timeout=15,
        )

        print(
            "GETME HTTP:",
            response.status_code
        )

        print(
            "GETME:",
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

        test_result = telegram(
            "🧪 ATI TELEGRAM TEST\n\n"
            "✅ Telegram connection is working.\n"
            "⚡ ATI FUTURES V7.1\n"
            f"🕐 {now_utc()}"
        )

        return test_result

    except Exception as e:

        print(
            "❌ TELEGRAM TEST ERROR:",
            repr(e)
        )

        return False


# =========================================================
# SIGN
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
# PUBLIC
# =========================================================

def public_get(
    url,
    params=None
):

    r = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT
    )

    if r.status_code != 200:

        raise Exception(
            f"HTTP {r.status_code}: "
            f"{r.text[:500]}"
        )

    return r.json()


# =========================================================
# PRIVATE
# =========================================================

def private_get(
    url,
    params=None
):

    r = session.get(
        url,
        params=signed_params(params),
        headers={
            "X-MBX-APIKEY": API_KEY
        },
        timeout=REQUEST_TIMEOUT
    )

    if r.status_code != 200:

        raise Exception(
            f"HTTP {r.status_code}: "
            f"{r.text[:1000]}"
        )

    return r.json()


def private_post(
    url,
    params=None
):

    r = session.post(
        url,
        params=signed_params(params),
        headers={
            "X-MBX-APIKEY": API_KEY
        },
        timeout=REQUEST_TIMEOUT
    )

    if r.status_code not in (
        200,
        201
    ):

        raise Exception(
            f"HTTP {r.status_code}: "
            f"{r.text[:1200]}"
        )

    return r.json()


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

            for x in obj:

                walk(x)

    walk(data)

    return max(
        values,
        default=0
    )


def get_usdt_balance():

    try:

        return extract_usdt(
            get_balance()
        )

    except Exception:

        try:

            return extract_usdt(
                get_account()
            )

        except Exception:

            return 0.0


# =========================================================
# EXCHANGE
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

        for x in data:

            symbol = str(
                x.get(
                    "symbol",
                    ""
                )
            ).upper()

            if symbol:

                result[
                    symbol
                ] = x

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

    result = []

    for row in data:

        try:

            result.append({
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })

        except Exception:

            pass

    return result


# =========================================================
# ICHIMOKU
# =========================================================

def calc_mid(
    highs,
    lows,
    period
):

    if len(highs) < period:

        return None

    return (
        max(
            highs[-period:]
        )
        +
        min(
            lows[-period:]
        )
    ) / 2


def ichimoku(
    candles
):

    if len(candles) < 60:

        return None

    # حذف کندل در حال تشکیل
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

    tenkan = calc_mid(
        highs,
        lows,
        TENKAN
    )

    kijun = calc_mid(
        highs,
        lows,
        KIJUN
    )

    senkou_b = calc_mid(
        highs,
        lows,
        SENKOU_B
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
    ) / 2

    cloud_top = max(
        senkou_a,
        senkou_b
    )

    cloud_bottom = min(
        senkou_a,
        senkou_b
    )

    prev_highs = highs[:-1]
    prev_lows = lows[:-1]

    prev_tenkan = calc_mid(
        prev_highs,
        prev_lows,
        TENKAN
    )

    prev_kijun = calc_mid(
        prev_highs,
        prev_lows,
        KIJUN
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

    distance = (
        abs(
            close - kijun
        )
        / kijun
    ) * 100

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
        "distance": distance,
    }


# =========================================================
# SIGNAL
# =========================================================

def evaluate(
    symbol,
    info,
    ticker,
    candles
):

    i = ichimoku(
        candles
    )

    if not i:

        return None

    if i["inside_cloud"]:

        return None

    buy = 0
    sell = 0

    buy_reasons = []
    sell_reasons = []

    # BUY
    if i["above_cloud"]:

        buy += 4
        buy_reasons.append(
            "PRICE_ABOVE_KUMO"
        )

    if i["tenkan"] > i["kijun"]:

        buy += 2.5
        buy_reasons.append(
            "TENKAN_GT_KIJUN"
        )

    if i["bullish_cloud"]:

        buy += 1.5
        buy_reasons.append(
            "BULLISH_KUMO"
        )

    if i["bullish_cross"]:

        buy += 3
        buy_reasons.append(
            "FRESH_TK_CROSS"
        )

    if i["chikou_buy"]:

        buy += 1
        buy_reasons.append(
            "CHIKOU_CONFIRM"
        )

    # SELL
    if i["below_cloud"]:

        sell += 4
        sell_reasons.append(
            "PRICE_BELOW_KUMO"
        )

    if i["tenkan"] < i["kijun"]:

        sell += 2.5
        sell_reasons.append(
            "TENKAN_LT_KIJUN"
        )

    if i["bearish_cloud"]:

        sell += 1.5
        sell_reasons.append(
            "BEARISH_KUMO"
        )

    if i["bearish_cross"]:

        sell += 3
        sell_reasons.append(
            "FRESH_TK_CROSS"
        )

    if i["chikou_sell"]:

        sell += 1
        sell_reasons.append(
            "CHIKOU_CONFIRM"
        )

    if buy >= sell:

        side = "BUY"
        score = buy
        reasons = buy_reasons

    else:

        side = "SELL"
        score = sell
        reasons = sell_reasons

    if score < MIN_SCORE:

        return None

    if (
        i["distance"]
        > MAX_KIJUN_DISTANCE
        and not (
            i["bullish_cross"]
            or
            i["bearish_cross"]
        )
    ):

        return None

    return {
        "symbol": symbol,
        "side": side,
        "score": score,
        "price": i["close"],
        "tenkan": i["tenkan"],
        "kijun": i["kijun"],
        "senkou_a": i["senkou_a"],
        "senkou_b": i["senkou_b"],
        "distance": i["distance"],
        "change": float(
            ticker.get(
                "priceChangePercent",
                0
            )
        ),
        "volume": float(
            ticker.get(
                "quoteVolume",
                0
            )
        ),
        "reasons": reasons,
        "info": info,
    }


# =========================================================
# SINGLE SYMBOL
# =========================================================

def scan_one(
    info,
    ticker
):

    symbol = info.get(
        "symbol"
    )

    try:

        data = get_klines(
            symbol
        )

        candles = parse_klines(
            data
        )

        if len(candles) < 60:

            return None

        return evaluate(
            symbol,
            info,
            ticker,
            candles
        )

    except Exception as e:

        print(
            f"⚠️ {symbol}: "
            f"{str(e)[:150]}"
        )

        return None


# =========================================================
# FAST SCAN
# =========================================================

def scan_market(
    symbols
):

    started = time.time()

    tickers = get_tickers()

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

    results = []

    with ThreadPoolExecutor(
        max_workers=SCAN_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                scan_one,
                info,
                ticker
            )
            for info, ticker
            in tasks
        ]

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
        key=lambda x: x["score"],
        reverse=True
    )

    elapsed = (
        time.time()
        - started
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

        for p in data:

            try:

                qty = abs(
                    float(
                        p.get(
                            "positionAmt",
                            0
                        )
                    )
                )

            except Exception:

                qty = 0

            if qty > 0:

                result.append(p)

        return result

    except Exception:

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
            "leverage": LEVERAGE
        }
    )


# =========================================================
# QUANTITY
# =========================================================

def make_quantity(
    price,
    info
):

    qty = (
        ORDER_USDT /
        price
    )

    step = 0
    minimum = 0
    min_notional = 0

    for f in info.get(
        "filters",
        []
    ):

        typ = f.get(
            "filterType"
        )

        if typ == "LOT_SIZE":

            step = float(
                f.get(
                    "stepSize",
                    0
                )
            )

            minimum = float(
                f.get(
                    "minQty",
                    0
                )
            )

        if typ in (
            "MIN_NOTIONAL",
            "NOTIONAL"
        ):

            min_notional = float(
                f.get(
                    "notional",
                    f.get(
                        "minNotional",
                        0
                    )
                )
            )

    if step > 0:

        q = Decimal(
            str(qty)
        )

        s = Decimal(
            str(step)
        )

        qty = float(
            (q // s) * s
        )

    if qty < minimum:

        qty = minimum

    if (
        min_notional > 0
        and qty * price
        < min_notional
    ):

        qty = (
            min_notional /
            price
        )

    return qty


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
            "quantity": quantity
        }
    )


# =========================================================
# POSITION
# =========================================================

def find_position(
    symbol
):

    for _ in range(10):

        try:

            data = get_positions()

            for p in data:

                if p.get(
                    "symbol"
                ) != symbol:

                    continue

                qty = float(
                    p.get(
                        "positionAmt",
                        0
                    )
                )

                if abs(qty) > 0:

                    return p

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

    entry = float(
        position.get(
            "entryPrice",
            0
        )
    )

    qty = float(
        position.get(
            "positionAmt",
            0
        )
    )

    if entry <= 0:

        return None

    if qty > 0:

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
# ONE SCAN CYCLE
# =========================================================

def run_cycle():

    print()
    print("=" * 65)
    print(
        f"⚡ ATI FUTURES V7.1 | "
        f"{now_utc()}"
    )
    print("=" * 65)

    print(
        f"☁️ ICHIMOKU "
        f"{TENKAN}/{KIJUN}/{SENKOU_B}"
    )

    print(
        f"🕯️ TIMEFRAME: {TIMEFRAME}"
    )

    print(
        f"🚀 WORKERS: {SCAN_WORKERS}"
    )

    print(
        f"🟢 LIVE: {LIVE_TRADING}"
    )

    balance = get_usdt_balance()

    print(
        f"💰 USDT: {balance}"
    )

    positions = get_open_positions()

    print(
        f"📌 OPEN POSITIONS: "
        f"{len(positions)}"
    )

    if len(positions) >= MAX_NEW_TRADES:

        telegram(
            "⛔ ATI FUTURES\n"
            "Maximum open positions reached.\n"
            f"📌 Positions: {len(positions)}\n"
            f"💰 USDT: {balance}\n"
            f"🕐 {now_utc()}"
        )

        return

    symbols = get_symbols()

    print(
        f"📊 FUTURES MARKETS: "
        f"{len(symbols)}"
    )

    results, elapsed = scan_market(
        symbols
    )

    print()
    print(
        f"⏱️ SCAN TIME: "
        f"{elapsed:.2f}s"
    )

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

    best = results[0]

    symbol = best["symbol"]
    side = best["side"]
    score = best["score"]
    price = best["price"]

    print()
    print("🚨 BEST SIGNAL")
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
        + ", ".join(
            best["reasons"]
        )
    )

    telegram(
        "🚨 ATI FAST ICHIMOKU\n\n"
        f"🪙 {symbol}\n"
        f"📈 SIDE: {side}\n"
        f"🏆 SCORE: {score:.2f}\n"
        f"💵 PRICE: {price}\n\n"
        f"☁️ Tenkan: {best['tenkan']}\n"
        f"☁️ Kijun: {best['kijun']}\n"
        f"☁️ Senkou A: {best['senkou_a']}\n"
        f"☁️ Senkou B: {best['senkou_b']}\n\n"
        f"📊 24H: {best['change']:.2f}%\n"
        f"🧠 "
        + ", ".join(
            best["reasons"]
        )
        + "\n\n"
        f"⏱️ Scan: {elapsed:.2f}s\n"
        f"🟢 LIVE: {LIVE_TRADING}\n"
        f"🕐 {now_utc()}"
    )

    # =====================================================
    # PAPER
    # =====================================================

    if not LIVE_TRADING:

        print(
            "🟡 PAPER MODE"
        )

        return

    # =====================================================
    # REAL TRADE
    # =====================================================

    if balance < 0.5:

        telegram(
            f"❌ BALANCE TOO LOW\n"
            f"💰 USDT: {balance}"
        )

        return

    price_now = get_price(
        symbol
    )

    quantity = make_quantity(
        price_now,
        best["info"]
    )

    print(
        f"📦 QTY: {quantity}"
    )

    if quantity <= 0:

        return

    set_leverage(
        symbol
    )

    telegram(
        "🚨 REAL FUTURES ORDER\n\n"
        f"🪙 {symbol}\n"
        f"📈 {side}\n"
        f"💵 {price_now}\n"
        f"📦 QTY: {quantity}\n"
        f"⚙️ LEVERAGE: {LEVERAGE}x"
    )

    try:

        order = market_order(
            symbol,
            side,
            quantity
        )

        print(
            "✅ ORDER SUCCESS"
        )

        print(
            order
        )

    except Exception as e:

        print(
            "❌ ORDER ERROR:",
            str(e)
        )

        telegram(
            "❌ REAL ORDER ERROR\n\n"
            + str(e)[:1500]
        )

        return

    position = find_position(
        symbol
    )

    if not position:

        telegram(
            "⚠️ POSITION NOT FOUND\n"
            f"🪙 {symbol}\n"
            "SL/TP NOT CONFIRMED"
        )

        return

    try:

        set_sl_tp(
            position
        )

        entry = position.get(
            "entryPrice"
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
            + str(e)[:1500]
        )


# =========================================================
# MAIN LOOP
# =========================================================

def main():

    print()
    print("=" * 65)
    print(
        "💓 ATI FUTURES V7.1 STARTING"
    )
    print("=" * 65)

    # اول Telegram را تست کن
    telegram_ok = telegram_test()

    if not telegram_ok:

        print()
        print(
            "🚨 TELEGRAM TEST FAILED"
        )

        print(
            "⚠️ BOT WILL CONTINUE,"
            " BUT TELEGRAM IS NOT WORKING."
        )

    # API
    if not API_KEY:

        print(
            "❌ TABDIL/TABDEAL API KEY MISSING"
        )

        telegram(
            "❌ ATI ERROR\n"
            "Futures API KEY missing."
        )

        return

    if not API_SECRET:

        print(
            "❌ API SECRET MISSING"
        )

        telegram(
            "❌ ATI ERROR\n"
            "Futures API SECRET missing."
        )

        return

    # Auth
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

    except Exception as e:

        print(
            "❌ AUTH ERROR:",
            str(e)
        )

        telegram(
            "❌ ATI FUTURES AUTH ERROR\n\n"
            + str(e)[:1500]
        )

        return

    # =====================================================
    # CONTINUOUS LOOP
    # =====================================================

    cycle = 0

    while True:

        cycle += 1

        print()
        print(
            "=" * 65
        )

        print(
            f"🔄 SCAN CYCLE #{cycle}"
        )

        print(
            f"🕐 {now_utc()}"
        )

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
                + str(e)[:1500]
                + "\n\n"
                f"🔄 Cycle: {cycle}\n"
                f"🕐 {now_utc()}"
            )

        # =================================================
        # HEARTBEAT
        # =================================================

        print()
        print(
            f"💓 NEXT HEARTBEAT/SCAN "
            f"IN {SCAN_INTERVAL} SECONDS"
        )

        time.sleep(
            SCAN_INTERVAL
        )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "🛑 STOPPED"
        )

    except Exception as e:

        print(
            "❌ FATAL:",
            repr(e)
        )

        telegram(
            "❌ ATI FATAL ERROR\n\n"
            + str(e)[:1500]
        )
