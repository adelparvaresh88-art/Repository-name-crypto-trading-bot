import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from decimal import Decimal
from datetime import datetime, timezone

# =========================================================
# ATI FUTURES REAL V5
# =========================================================

VERSION = "ATI-FUTURES-REAL-V5"

API_BASE = "https://api1.tabdeal.org"

PUBLIC_V1 = API_BASE + "/r/fapi/v1/"
PRIVATE_V3 = API_BASE + "/r/fapi/v3/"
WRITE_V1 = API_BASE + "/fapi/v1/"

REQUEST_TIMEOUT = 10

# =========================================================
# ENV
# =========================================================

def env_str(name, default=""):
    v = os.getenv(name, "")
    return v.strip() if v and v.strip() else default


def env_int(name, default):
    try:
        v = os.getenv(name, "").strip()
        return int(v) if v else default
    except Exception:
        return default


def env_float(name, default):
    try:
        v = os.getenv(name, "").strip()
        return float(v) if v else default
    except Exception:
        return default


def env_bool(name, default=False):
    v = os.getenv(name, "").strip().lower()

    if not v:
        return default

    return v in ("1", "true", "yes", "on")


# =========================================================
# SETTINGS
# =========================================================

API_KEY = env_str(
    "TABDIL_API_KEY",
    env_str("TABDEAL_API_KEY")
)

API_SECRET = env_str(
    "TABDIL_API_SECRET",
    env_str("TABDEAL_API_SECRET")
)

TELEGRAM_BOT_TOKEN = env_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env_str("TELEGRAM_CHAT_ID")

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
# NEW SCANNER SETTINGS
# =========================================================

# 0 = کل بازار
SCAN_LIMIT = env_int(
    "SCAN_LIMIT",
    0
)

# حداقل حجم معاملات برای حذف بازارهای مرده
MIN_24H_QUOTE_VOLUME = env_float(
    "MIN_24H_QUOTE_VOLUME",
    10000.0
)

# حداقل فشار برای ورود
BUY_PRESSURE = env_float(
    "BUY_PRESSURE",
    57.0
)

SELL_PRESSURE = env_float(
    "SELL_PRESSURE",
    43.0
)

# حداقل حرکت کوتاه مدت
MIN_MOMENTUM = env_float(
    "MIN_MOMENTUM",
    0.08
)

# تعداد کاندیدهایی که بعد از مرحله اول بررسی می‌شوند
TOP_CANDIDATES = env_int(
    "TOP_CANDIDATES",
    20
)

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-Bot/5.0"
})


# =========================================================
# TELEGRAM
# =========================================================

def telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:

        url = (
            f"https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}/sendMessage"
        )

        requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=8
        )

    except Exception:
        pass


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

    params = dict(params or {})

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
# PRIVATE GET
# =========================================================

def private_get(
    url,
    params=None
):

    if not API_KEY or not API_SECRET:

        raise Exception(
            "API KEY/SECRET missing"
        )

    params = signed_params(
        params
    )

    r = session.get(
        url,
        params=params,
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


# =========================================================
# PRIVATE POST
# =========================================================

def private_post(
    url,
    params=None
):

    if not API_KEY or not API_SECRET:

        raise Exception(
            "API KEY/SECRET missing"
        )

    params = signed_params(
        params
    )

    r = session.post(
        url,
        params=params,
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


# =========================================================
# BALANCE
# =========================================================

def get_balance():

    return private_get(
        PRIVATE_V3 + "balance"
    )


def extract_usdt(data):

    found = []

    def walk(x):

        if isinstance(x, dict):

            asset = str(
                x.get("asset", "")
            ).upper()

            if asset == "USDT":

                for key in (
                    "availableBalance",
                    "available",
                    "free",
                    "walletBalance",
                    "balance",
                    "crossWalletBalance"
                ):

                    try:

                        if x.get(key) is not None:

                            found.append(
                                float(x[key])
                            )

                    except Exception:
                        pass

            for value in x.values():
                walk(value)

        elif isinstance(x, list):

            for item in x:
                walk(item)

    walk(data)

    return max(
        [x for x in found if x >= 0],
        default=0.0
    )


def get_usdt_balance():

    values = []

    for func in (
        get_balance,
        get_account
    ):

        try:

            values.append(
                extract_usdt(
                    func()
                )
            )

        except Exception:
            pass

    return max(
        values,
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

    result = []

    for s in data.get(
        "symbols",
        []
    ):

        symbol = s.get(
            "symbol",
            ""
        )

        status = str(
            s.get("status", "")
        ).upper()

        quote = str(
            s.get("quoteAsset", "")
        ).upper()

        if not symbol:
            continue

        if quote not in (
            "USDT",
            "USDC",
            "USD"
        ):
            continue

        if status not in (
            "TRADING",
            "ENABLED",
            "OPEN"
        ):
            continue

        result.append(s)

    if SCAN_LIMIT > 0:

        return result[:SCAN_LIMIT]

    return result


# =========================================================
# 24H TICKER
# =========================================================

def get_ticker(symbol):

    return public_get(
        PUBLIC_V1 + "ticker/24hr",
        {
            "symbol": symbol
        }
    )


# =========================================================
# PRICE
# =========================================================

def get_price(symbol):

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
# DEPTH
# =========================================================

def get_depth(symbol):

    return public_get(
        PUBLIC_V1 + "depth",
        {
            "symbol": symbol,
            "limit": 10
        }
    )


def calculate_pressure(data):

    bids = data.get(
        "bids",
        []
    )

    asks = data.get(
        "asks",
        []
    )

    bid_volume = 0.0
    ask_volume = 0.0

    for x in bids[:10]:

        try:
            bid_volume += float(x[1])
        except Exception:
            pass

    for x in asks[:10]:

        try:
            ask_volume += float(x[1])
        except Exception:
            pass

    total = (
        bid_volume +
        ask_volume
    )

    if total <= 0:
        return 50.0

    return (
        bid_volume /
        total
    ) * 100.0


# =========================================================
# MOMENTUM
# =========================================================

def calculate_momentum(ticker):

    try:

        last = float(
            ticker.get(
                "lastPrice",
                0
            )
        )

        open_price = float(
            ticker.get(
                "openPrice",
                0
            )
        )

        if last <= 0 or open_price <= 0:
            return 0.0

        return (
            (last - open_price) /
            open_price
        ) * 100.0

    except Exception:

        return 0.0


# =========================================================
# POSITION
# =========================================================

def get_positions():

    return private_get(
        PRIVATE_V3 + "positionRisk"
    )


def get_open_positions():

    try:

        data = get_positions()

        result = []

        if isinstance(data, list):

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

    except Exception as e:

        print(
            "POSITION ERROR:",
            e
        )

        return []


# =========================================================
# LEVERAGE
# =========================================================

def change_leverage(symbol):

    return private_post(
        WRITE_V1 + "leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE
        }
    )


# =========================================================
# SYMBOL RULES
# =========================================================

def symbol_rules(info):

    step = 0.0
    min_qty = 0.0
    min_notional = 0.0

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

            min_qty = float(
                f.get(
                    "minQty",
                    0
                )
            )

        elif typ in (
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

    return (
        step,
        min_qty,
        min_notional
    )


# =========================================================
# QUANTITY
# =========================================================

def make_quantity(
    price,
    info
):

    step, min_qty, min_notional = (
        symbol_rules(info)
    )

    if price <= 0:
        return 0.0

    qty = (
        ORDER_USDT /
        price
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

    if qty < min_qty:

        qty = min_qty

    if (
        min_notional > 0
        and qty * price < min_notional
    ):

        qty = (
            min_notional /
            price
        )

        if step > 0:

            q = Decimal(
                str(qty)
            )

            s = Decimal(
                str(step)
            )

            qty = float(
                (q // s + 1) * s
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
# FIND POSITION
# =========================================================

def find_position(symbol):

    for _ in range(10):

        try:

            positions = get_positions()

            if isinstance(
                positions,
                list
            ):

                for p in positions:

                    if p.get(
                        "symbol"
                    ) != symbol:

                        continue

                    try:

                        qty = float(
                            p.get(
                                "positionAmt",
                                0
                            )
                        )

                    except Exception:

                        qty = 0

                    if abs(qty) > 0:

                        return p

        except Exception:
            pass

        time.sleep(1)

    return None


# =========================================================
# SL / TP
# =========================================================

def set_position_sl_tp(
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

        qty = float(
            position.get(
                "positionAmt",
                0
            )
        )

    except Exception:

        return None

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
            "workingType": "MARK_PRICE"
        }
    )


# =========================================================
# FAST MARKET SCANNER
# =========================================================

def scan_market(symbols):

    candidates = []

    scanned = 0
    volume_ok = 0
    momentum_ok = 0
    pressure_ok = 0

    print()
    print(
        "⚡ FAST FUTURES SCANNER"
    )

    for info in symbols:

        symbol = info.get(
            "symbol"
        )

        scanned += 1

        try:

            ticker = get_ticker(
                symbol
            )

            volume = float(
                ticker.get(
                    "quoteVolume",
                    0
                )
            )

            if volume < MIN_24H_QUOTE_VOLUME:
                continue

            volume_ok += 1

            momentum = calculate_momentum(
                ticker
            )

            # جهت اولیه
            if momentum >= MIN_MOMENTUM:

                direction = "BUY"

            elif momentum <= -MIN_MOMENTUM:

                direction = "SELL"

            else:

                continue

            momentum_ok += 1

            depth = get_depth(
                symbol
            )

            p = calculate_pressure(
                depth
            )

            if direction == "BUY":

                if p < BUY_PRESSURE:
                    continue

                pressure_score = p

                score = (
                    abs(momentum) * 5
                    + (p - 50)
                )

            else:

                if p > SELL_PRESSURE:
                    continue

                pressure_score = (
                    100 - p
                )

                score = (
                    abs(momentum) * 5
                    + (50 - p)
                )

            pressure_ok += 1

            candidates.append({
                "symbol": symbol,
                "side": direction,
                "momentum": momentum,
                "pressure": pressure_score,
                "volume": volume,
                "score": score,
                "info": info
            })

        except Exception:

            continue

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print(
        f"📊 SCANNED: {scanned}"
    )

    print(
        f"💧 VOLUME OK: {volume_ok}"
    )

    print(
        f"⚡ MOMENTUM OK: {momentum_ok}"
    )

    print(
        f"🎯 PRESSURE OK: {pressure_ok}"
    )

    return (
        candidates[:TOP_CANDIDATES],
        scanned,
        volume_ok,
        momentum_ok,
        pressure_ok
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("=" * 55)
    print("💓 ATI FUTURES REAL V5")
    print("=" * 55)

    print(
        f"📡 TABDEAL FUTURES"
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

    print(
        f"🎯 SL: {SL_PERCENT}%"
    )

    print(
        f"🎯 TP: {TP_PERCENT}%"
    )

    print(
        f"🕐 {now_utc()}"
    )

    print("=" * 55)

    telegram(
        f"💓 ATI FUTURES V5\n"
        f"⚡ FAST MARKET SCANNER\n"
        f"📡 TABDEAL FUTURES\n"
        f"⚙️ LEVERAGE: {LEVERAGE}x\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"🟢 LIVE: {LIVE_TRADING}\n"
        f"🕐 {now_utc()}"
    )

    # -----------------------------------------------------
    # AUTH
    # -----------------------------------------------------

    if not API_KEY or not API_SECRET:

        print(
            "❌ API KEY/SECRET missing"
        )

        telegram(
            "❌ ATI FUTURES\n"
            "API KEY/SECRET missing"
        )

        return

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
                "❌ FUTURES ACCOUNT\n"
                "canTrade=False"
            )

            return

    except Exception as e:

        print(
            "❌ AUTH ERROR:",
            e
        )

        telegram(
            "❌ ATI FUTURES AUTH ERROR\n\n"
            + str(e)[:1200]
        )

        return

    # -----------------------------------------------------
    # BALANCE
    # -----------------------------------------------------

    balance = get_usdt_balance()

    print(
        f"💰 USDT AVAILABLE: {balance}"
    )

    if balance <= 0:

        telegram(
            f"❌ ATI FUTURES\n"
            f"USDT AVAILABLE: {balance}\n"
            f"معامله انجام نشد."
        )

        return

    # -----------------------------------------------------
    # POSITIONS
    # -----------------------------------------------------

    positions = get_open_positions()

    print(
        f"📌 OPEN POSITIONS: "
        f"{len(positions)}"
    )

    if len(positions) >= MAX_NEW_TRADES:

        print(
            "⛔ MAX NEW TRADES"
        )

        telegram(
            f"⛔ ATI FUTURES\n"
            f"Open positions: {len(positions)}\n"
            f"New trade skipped."
        )

        return

    # -----------------------------------------------------
    # EXCHANGE
    # -----------------------------------------------------

    try:

        symbols = get_symbols()

        print(
            f"📊 FUTURES MARKETS: "
            f"{len(symbols)}"
        )

    except Exception as e:

        print(
            "❌ EXCHANGE INFO ERROR:",
            e
        )

        telegram(
            "❌ FUTURES EXCHANGE INFO ERROR\n\n"
            + str
