import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from decimal import Decimal
from datetime import datetime, timezone


# =========================================================
# ATI FUTURES REAL V6
# =========================================================

VERSION = "ATI-FUTURES-REAL-V6"

API_BASE = "https://api1.tabdeal.org"

PUBLIC_V1 = API_BASE + "/r/fapi/v1/"
PRIVATE_V3 = API_BASE + "/r/fapi/v3/"
WRITE_V1 = API_BASE + "/fapi/v1/"

REQUEST_TIMEOUT = 10


# =========================================================
# ENV HELPERS
# =========================================================

def env_str(name, default=""):
    value = os.getenv(name, "")
    if value and value.strip():
        return value.strip()
    return default


def env_int(name, default):
    try:
        value = os.getenv(name, "").strip()
        return int(value) if value else default
    except Exception:
        return default


def env_float(name, default):
    try:
        value = os.getenv(name, "").strip()
        return float(value) if value else default
    except Exception:
        return default


def env_bool(name, default=False):
    value = os.getenv(name, "").strip().lower()

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
    env_str("TABDEAL_API_KEY")
)

API_SECRET = env_str(
    "TABDIL_API_SECRET",
    env_str("TABDEAL_API_SECRET")
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

# 0 = کل بازار
SCAN_LIMIT = env_int(
    "SCAN_LIMIT",
    0
)

# حداقل حجم 24 ساعته
MIN_24H_QUOTE_VOLUME = env_float(
    "MIN_24H_QUOTE_VOLUME",
    10000.0
)

# فیلتر Momentum
MIN_MOMENTUM = env_float(
    "MIN_MOMENTUM",
    0.08
)

# فشار Order Book
BUY_PRESSURE = env_float(
    "BUY_PRESSURE",
    55.0
)

SELL_PRESSURE = env_float(
    "SELL_PRESSURE",
    45.0
)

# تعداد کاندیدهایی که Depth روی آنها بررسی می‌شود
TOP_CANDIDATES = env_int(
    "TOP_CANDIDATES",
    30
)

# حداکثر عمق Order Book
DEPTH_LIMIT = env_int(
    "DEPTH_LIMIT",
    10
)


# =========================================================
# HTTP SESSION
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-Bot/6.0",
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
        hashlib.sha256,
    ).hexdigest()

    params["signature"] = signature

    return params


# =========================================================
# PUBLIC GET
# =========================================================

def public_get(
    url,
    params=None,
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
    params=None,
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
    params=None,
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

        if isinstance(obj, dict):

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

        elif isinstance(obj, list):

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

        if quote not in (
            "USDT",
            "USDC",
            "USD",
        ):
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
# ALL 24H TICKERS
# =========================================================

def get_all_tickers():

    return public_get(
        PUBLIC_V1 + "ticker/24hr"
    )


# =========================================================
# TICKER NORMALIZER
# =========================================================

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

                result[symbol] = item

    elif isinstance(
        data,
        dict
    ):

        # بعض APIها ممکن است خروجی
        # را داخل data قرار دهند.

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

            result[symbol] = data

    return result


# =========================================================
# SINGLE TICKER FALLBACK
# =========================================================

def get_ticker(symbol):

    return public_get(
        PUBLIC_V1 + "ticker/24hr",
        {
            "symbol": symbol,
        },
    )


# =========================================================
# PRICE
# =========================================================

def get_price(symbol):

    data = public_get(
        PUBLIC_V1 + "ticker/price",
        {
            "symbol": symbol,
        },
    )

    if not isinstance(
        data,
        dict
    ):

        raise Exception(
            "Invalid price response"
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
            "limit": DEPTH_LIMIT,
        },
    )


# =========================================================
# PRESSURE
# =========================================================

def calculate_pressure(
    data
):

    if not isinstance(
        data,
        dict
    ):

        return 50.0

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

    for item in bids:

        try:

            bid_volume += float(
                item[1]
            )

        except Exception:
            pass

    for item in asks:

        try:

            ask_volume += float(
                item[1]
            )

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

def calculate_momentum(
    ticker
):

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

        if (
            last <= 0
            or open_price <= 0
        ):

            return 0.0

        return (
            (
                last -
                open_price
            )
            /
            open_price
        ) * 100.0

    except Exception:

        return 0.0


# =========================================================
# 24H VOLUME
# =========================================================

def get_quote_volume(
    ticker
):

    for key in (
        "quoteVolume",
        "quoteVolume24h",
        "turnover",
        "volumeQuote",
    ):

        try:

            value = ticker.get(
                key
            )

            if value is not None:

                return float(
                    value
                )

        except Exception:
            pass

    return 0.0


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
    ) = symbol_rules(
        info
    )

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
        and qty * price
        < min_notional
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
            "quantity": quantity,
        },
    )


# =========================================================
# FIND POSITION
# =========================================================

def find_position(
    symbol
):

    for _ in range(10):

        try:

            positions = get_positions()

            if isinstance(
                positions,
                list
            ):

                for position in positions:

                    if (
                        position.get(
                            "symbol"
                        )
                        != symbol
                    ):

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
# SL / TP
# =========================================================

def set_position_sl_tp(
    position
):

    try:

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

    except Exception:

        return None

    if not symbol:
        return None

    if entry <= 0:
        return None

    if qty > 0:

        sl = entry * (
            1 -
            SL_PERCENT / 100.0
        )

        tp = entry * (
            1 +
            TP_PERCENT / 100.0
        )

    else:

        sl = entry * (
            1 +
            SL_PERCENT / 100.0
        )

        tp = entry * (
            1 -
            TP_PERCENT / 100.0
        )

    params = {
        "positionId": position_id,
        "symbol": symbol,
        "slPrice": sl,
        "tpPrice": tp,
        "workingType": "MARK_PRICE",
    }

    return private_post(
        WRITE_V1 + "positionSlTp",
        params,
    )


# =========================================================
# FAST SCANNER
# =========================================================

def scan_market(
    symbols
):

    print()
    print("=" * 60)
    print("⚡ ATI FAST FUTURES SCANNER")
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
        f"📊 MARKET SYMBOLS: {scanned}"
    )

    # -----------------------------------------------------
    # GET ALL 24H TICKERS
    # -----------------------------------------------------

    try:

        raw = get_all_tickers()

        tickers = normalize_tickers(
            raw
        )

        print(
            f"📡 24H TICKERS: "
            f"{len(tickers)}"
        )

    except Exception as e:

        print(
            "⚠️ ALL TICKER FAILED:"
        )

        print(
            str(e)[:500]
        )

        tickers = {}

    # -----------------------------------------------------
    # FALLBACK
    # -----------------------------------------------------

    if not tickers:

        print(
            "⚠️ FALLBACK: "
            "SINGLE TICKER MODE"
        )

        for index, info in enumerate(
            symbols
        ):

            if index >= 100:
                break

            symbol = info.get(
                "symbol"
            )

            try:

                tickers[
                    symbol
                ] = get_ticker(
                    symbol
                )

            except Exception:
                continue

    # -----------------------------------------------------
    # FIRST FILTER
    # -----------------------------------------------------

    volume_ok = 0
    momentum_ok = 0

    first_candidates = []

    for symbol, info in symbol_map.items():

        ticker = tickers.get(
            symbol
        )

        if not ticker:
            continue

        volume = get_quote_volume(
            ticker
        )

        if (
            volume <
            MIN_24H_QUOTE_VOLUME
        ):

            continue

        volume_ok += 1

        momentum = calculate_momentum(
            ticker
        )

        if abs(momentum) < MIN_MOMENTUM:

            continue

        momentum_ok += 1

        if momentum > 0:

            direction = "BUY"

        else:

            direction = "SELL"

        # preliminary score
        preliminary_score = (
            abs(momentum) * 10.0
            + min(
                volume /
                max(
                    MIN_24H_QUOTE_VOLUME,
                    1
                ),
                100
            ) * 0.05
        )

        first_candidates.append({
            "symbol": symbol,
            "side": direction,
            "momentum": momentum,
            "volume": volume,
            "score": preliminary_score,
            "info": info,
            "ticker": ticker,
        })

    # -----------------------------------------------------
    # TOP MOMENTUM
    # -----------------------------------------------------

    first_candidates.sort(
        key=lambda x:
        x["score"],
        reverse=True
    )

    first_candidates = (
        first_candidates[
            :TOP_CANDIDATES
        ]
    )

    print(
        f"💧 VOLUME OK: {volume_ok}"
    )

    print(
        f"⚡ MOMENTUM OK: {momentum_ok}"
    )

    print(
        f"🎯 DEPTH CANDIDATES: "
        f"{len(first_candidates)}"
    )

    # -----------------------------------------------------
    # DEPTH FILTER
    # -----------------------------------------------------

    final_candidates = []

    pressure_ok = 0

    for candidate in first_candidates:

        symbol = candidate[
            "symbol"
        ]

        try:

            depth = get_depth(
                symbol
            )

            pressure = calculate_pressure(
                depth
            )

        except Exception as e:

            print(
                f"⚠️ DEPTH ERROR "
                f"{symbol}: "
                f"{str(e)[:180]}"
            )

            continue

        side = candidate[
            "side"
        ]

        if side == "BUY":

            if pressure < BUY_PRESSURE:

                continue

            pressure_score = pressure

            pressure_bonus = (
                pressure -
                50.0
            )

        else:

            if pressure > SELL_PRESSURE:

                continue

            pressure_score = (
                100.0 -
                pressure
            )

            pressure_bonus = (
                50.0 -
                pressure
            )

        pressure_ok += 1

        final_score = (
            abs(
                candidate[
                    "momentum"
                ]
            ) * 10.0
            + pressure_bonus * 1.5
        )

        candidate[
            "pressure"
        ] = pressure_score

        candidate[
            "score"
        ] = final_score

        final_candidates.append(
            candidate
        )

    final_candidates.sort(
        key=lambda x:
        x["score"],
        reverse=True
    )

    print(
        f"🔥 PRESSURE OK: "
        f"{pressure_ok}"
    )

    print(
        f"🚨 FINAL SIGNALS: "
        f"{len(final_candidates)}"
    )

    # -----------------------------------------------------
    # PRINT TOP 5
    # -----------------------------------------------------

    if final_candidates:

        print()
        print(
            "🏆 TOP CANDIDATES"
        )

        for index, item in enumerate(
            final_candidates[:5],
            start=1
        ):

            print(
                f"{index}. "
                f"{item['symbol']} | "
                f"{item['side']} | "
                f"Mom={item['momentum']:.3f}% | "
                f"Pressure={item['pressure']:.2f}% | "
                f"Score={item['score']:.2f}"
            )

    return (
        final_candidates,
        scanned,
        volume_ok,
        momentum_ok,
        pressure_ok,
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("=" * 60)
    print("💓 ATI FUTURES REAL V6")
    print("=" * 60)

    print(
        f"⚡ VERSION: {VERSION}"
    )

    print(
        "📡 MARKET: TABDEAL FUTURES"
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
        f"🟢 LIVE TRADING: "
        f"{LIVE_TRADING}"
    )

    print(
        f"🕐 {now_utc()}"
    )

    print("=" * 60)

    # -----------------------------------------------------
    # TELEGRAM START
    # -----------------------------------------------------

    telegram(
        f"💓 ATI FUTURES V6\n"
        f"⚡ FAST SCANNER STARTED\n"
        f"📡 TABDEAL FUTURES\n"
        f"⚙️ LEVERAGE: {LEVERAGE}x\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"🟢 LIVE: {LIVE_TRADING}\n"
        f"🕐 {now_utc()}"
    )

    # -----------------------------------------------------
    # API CREDENTIALS
    # -----------------------------------------------------

    if not API_KEY:

        print(
            "❌ API KEY missing"
        )

        telegram(
            "❌ ATI FUTURES ERROR\n"
            "API KEY missing"
        )

        return

    if not API_SECRET:

        print(
            "❌ API SECRET missing"
        )

        telegram(
            "❌ ATI FUTURES ERROR\n"
            "API SECRET missing"
        )

        return

    # -----------------------------------------------------
    # AUTH
    # -----------------------------------------------------

    try:

        account = get_account()

        print()
        print(
            "✅ FUTURES AUTH SUCCESS"
        )

        can_trade = account.get(
            "canTrade"
        )

        print(
            f"🔓 canTrade: "
            f"{can_trade}"
        )

        if can_trade is False:

            print(
                "❌ canTrade=False"
            )

            telegram(
                "❌ ATI FUTURES\n"
                "canTrade=False"
            )

            return

    except Exception as e:

        print()
        print(
            "❌ FUTURES AUTH ERROR"
        )

        print(
            str(e)
        )

        telegram(
            "❌ ATI FUTURES AUTH ERROR\n\n"
            + str(e)[:1500]
        )

        return

    # -----------------------------------------------------
    # BALANCE
    # -----------------------------------------------------

    try:

        balance = get_usdt_balance()

    except Exception as e:

        print(
            "❌ BALANCE ERROR:",
            str(e)
        )

        telegram(
            "❌ FUTURES BALANCE ERROR\n\n"
            + str(e)[:1200]
        )

        return

    print()
    print(
        f"💰 USDT AVAILABLE: "
        f"{balance}"
    )

    if balance <= 0:

        print(
            "❌ USDT balance is zero."
        )

        telegram(
            f"❌ ATI FUTURES\n"
            f"💰 USDT AVAILABLE: "
            f"{balance}\n"
            f"🚫 NO TRADE"
        )

        return

    # -----------------------------------------------------
    # OPEN POSITIONS
    # -----------------------------------------------------

    positions = get_open_positions()

    print(
        f"📌 OPEN POSITIONS: "
        f"{len(positions)}"
    )

    if len(positions) >= MAX_NEW_TRADES:

        print(
            "⛔ MAX NEW TRADES REACHED"
        )

        telegram(
            f"⛔ ATI FUTURES\n"
            f"Open positions: "
            f"{len(positions)}\n"
            f"MAX: "
            f"{MAX_NEW_TRADES}\n"
            f"🚫 NEW TRADE SKIPPED"
        )

        return

    # -----------------------------------------------------
    # EXCHANGE INFO
    # -----------------------------------------------------

    try:

        symbols = get_symbols()

        print()
        print(
            f"📊 FUTURES MARKETS: "
            f"{len(symbols)}"
        )

    except Exception as e:

        print()
        print(
            "❌ EXCHANGE INFO ERROR"
        )

        print(
            str(e)
        )

        telegram(
            "❌ ATI FUTURES EXCHANGE INFO ERROR\n\n"
            + str(e)[:1500]
        )

        return

    if not symbols:

        print(
            "❌ NO FUTURES SYMBOLS"
        )

        telegram(
            "❌ ATI FUTURES\n"
            "No Futures symbols received."
        )

        return

    # -----------------------------------------------------
    # SCAN
    # -----------------------------------------------------

    try:

        (
            candidates,
            scanned,
            volume_ok,
            momentum_ok,
            pressure_ok,
        ) = scan_market(
            symbols
        )

    except Exception as e:

        print()
        print(
            "❌ SCANNER ERROR"
        )

        print(
            str(e)
        )

        telegram(
            "❌ ATI FUTURES SCANNER ERROR\n\n"
            + str(e)[:1500]
        )

        return

    # -----------------------------------------------------
    # NO SIGNAL
    # -----------------------------------------------------

    if not candidates:

        print()
        print(
            "=" * 60
        )

        print(
            "❌ NO FINAL SIGNAL"
        )

        print(
            f"📊 Scanned: {scanned}"
        )

        print(
            f"💧 Volume OK: {volume_ok}"
        )

        print(
            f"⚡ Momentum OK: {momentum_ok}"
        )

        print(
            f"🔥 Pressure OK: {pressure_ok}"
        )

        print(
            "=" * 60
        )

        telegram(
            f"📊 ATI FUTURES V6\n"
            f"Markets: {scanned}\n"
            f"Volume OK: {volume_ok}\n"
            f"Momentum OK: {momentum_ok}\n"
            f"Pressure OK: {pressure_ok}\n"
            f"❌ NO FINAL SIGNAL\n"
            f"💰 USDT: {balance}\n"
            f"🟢 LIVE: {LIVE_TRADING}\n"
            f"🕐 {now_utc()}"
        )

        return

    # -----------------------------------------------------
    # BEST SIGNAL
    # -----------------------------------------------------

    best = candidates[0]

    symbol = best[
        "symbol"
    ]

    side = best[
        "side"
    ]

    momentum = best[
        "momentum"
    ]

    pressure = best[
        "pressure"
    ]

    score = best[
        "score"
    ]

    volume = best[
        "volume"
    ]

    info = best[
        "info"
    ]

    print()
    print("=" * 60)
    print("🚨 BEST FUTURES SIGNAL")
    print("=" * 60)

    print(
        f"🪙 SYMBOL: {symbol}"
    )

    print(
        f"📈 SIDE: {side}"
    )

    print(
        f"⚡ MOMENTUM: "
        f"{momentum:.3f}%"
    )

    print(
        f"🔥 PRESSURE: "
        f"{pressure:.2f}%"
    )

    print(
        f"💧 24H VOLUME: "
        f"{volume:.2f}"
    )

    print(
        f"🏆 SCORE: "
        f"{score:.2f}"
    )

    print("=" * 60)

    # -----------------------------------------------------
    # PRICE
    # -----------------------------------------------------

    try:

        price = get_price(
            symbol
        )

        quantity = make_quantity(
            price,
            info
        )

    except Exception as e:

        print(
            "❌ PRICE / QUANTITY ERROR"
        )

        print(
            str(e)
        )

        telegram(
            f"❌ PRICE / QUANTITY ERROR\n"
            f"🪙 {symbol}\n\n"
            f"{str(e)[:1200]}"
        )

        return

    print(
        f"💵 PRICE: {price}"
    )

    print(
        f"📦 QTY: {quantity}"
    )

    if quantity <= 0:

        print(
            "❌ INVALID QUANTITY"
        )

        telegram(
            f"❌ INVALID QUANTITY\n"
            f"🪙 {symbol}"
        )

        return

    # -----------------------------------------------------
    # SIGNAL TELEGRAM
    # -----------------------------------------------------

    telegram(
        f"🚨 ATI FUTURES SIGNAL\n\n"
        f"🪙 {symbol}\n"
        f"📈 SIDE: {side}\n"
        f"⚡ Momentum: {momentum:.3f}%\n"
        f"🔥 Pressure: {pressure:.2f}%\n"
        f"🏆 Score: {score:.2f}\n"
        f"💧 Volume: {volume:.2f}\n"
        f"💵 Price: {price}\n"
        f"📦 Qty: {quantity}\n"
        f"⚙️ Leverage: {LEVERAGE}x\n"
        f"🟢 LIVE: {LIVE_TRADING}\n"
        f"🕐 {now_utc()}"
    )

    # -----------------------------------------------------
    # PAPER MODE
    # -----------------------------------------------------

    if not LIVE_TRADING:

        print()
        print(
            "🔴 LIVE_TRADING=False"
        )

        print(
            "🚫 REAL ORDER NOT SENT"
        )

        telegram(
            f"🟡 PAPER SIGNAL ONLY\n"
            f"🪙 {symbol}\n"
            f"📈 {side}\n"
            f"💵 {price}\n"
            f"🚫 REAL ORDER NOT SENT"
        )

        return

    # -----------------------------------------------------
    # REAL BALANCE CHECK
    # -----------------------------------------------------

    if balance < 0.5:

        print(
            "❌ BALANCE TOO LOW"
        )

        telegram(
            f"❌ BALANCE TOO LOW\n"
            f"💰 USDT: {balance}"
        )

        return

    # -----------------------------------------------------
    # LEVERAGE
    # -----------------------------------------------------

    try:

        print()
        print(
            f"⚙️ SETTING "
            f"{LEVERAGE}x LEVERAGE"
        )

        leverage_result = (
            change_leverage(
                symbol
            )
        )

        print(
            "✅ LEVERAGE OK"
        )

        print(
            leverage_result
        )

    except Exception as e:

        print()
        print(
            "❌ LEVERAGE ERROR"
        )

        print(
            str(e)
        )

        telegram(
            f"❌ LEVERAGE ERROR\n"
            f"🪙 {symbol}\n\n"
            f"{str(e)[:1500]}"
        )

        return

    # -----------------------------------------------------
    # REAL ORDER
    # -----------------------------------------------------

    try:

        print()
        print("=" * 60)
        print(
            "🚨 SENDING REAL FUTURES ORDER"
        )
        print("=" * 60)

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
            f"🚨 REAL FUTURES TRADE OPENED\n\n"
            f"🪙 {symbol}\n"
            f"📈 SIDE: {side}\n"
            f"💵 PRICE: {price}\n"
            f"📦 QTY: {quantity}\n"
            f"⚙️ LEVERAGE: {LEVERAGE}x\n"
            f"🆔 ORDER: "
            f"{order.get('orderId')}\n"
            f"🕐 {now_utc()}"
        )

    except Exception as e:

        print()
        print(
            "❌ REAL ORDER ERROR"
        )

        print(
            str(e)
        )

        telegram(
            f"❌ REAL FUTURES ORDER ERROR\n\n"
            f"🪙 {symbol}\n"
            f"📈 SIDE: {side}\n\n"
            f"{str(e)[:1800]}"
        )

        return

    # -----------------------------------------------------
    # FIND POSITION
    # -----------------------------------------------------

    print()
    print(
        "🔎 SEARCHING FOR POSITION..."
    )

    position = find_position(
        symbol
    )

    if not position:

        print(
            "⚠️ POSITION NOT FOUND"
        )

        telegram(
            f"⚠️ ORDER ACCEPTED\n"
            f"BUT POSITION NOT FOUND\n\n"
            f"🪙 {symbol}\n"
            f"🚨 SL/TP NOT CONFIRMED"
        )

        return

    entry = position.get(
        "entryPrice"
    )

    position_qty = position.get(
        "positionAmt"
    )

    print()
    print(
        "✅ POSITION OPEN"
    )

    print(
        f"🪙 SYMBOL: {symbol}"
    )

    print(
        f"📍 ENTRY: {entry}"
    )

    print(
        f"📦 POSITION QTY: "
        f"{position_qty}"
    )

    # -----------------------------------------------------
    # SL / TP
    # -----------------------------------------------------

    try:

        print()
        print(
            "🛡️ SETTING SL/TP..."
        )

        sltp_result = (
            set_position_sl_tp(
                position
            )
        )

        if sltp_result:

            print(
                "✅ SL/TP SET SUCCESS"
            )

            print(
                sltp_result
            )

            telegram(
                f"🛡️ SL/TP SET\n"
                f"🪙 {symbol}\n"
                f"📍 Entry: {entry}\n"
                f"🛑 SL: {SL_PERCENT}%\n"
                f"🎯 TP: {TP_PERCENT}%"
            )

        else:

            print(
                "⚠️ SL/TP NOT CONFIRMED"
            )

            telegram(
                f"🚨 WARNING\n"
                f"POSITION OPENED\n"
                f"🪙 {symbol}\n"
                f"⚠️ SL/TP NOT CONFIRMED"
            )

    except Exception as e:

        print()
        print(
            "❌ SL/TP ERROR"
        )

        print(
            str(e)
        )

        telegram(
            f"🚨 URGENT SL/TP ERROR\n\n"
            f"🪙 {symbol}\n"
            f"📍 Entry: {entry}\n\n"
            f"{str(e)[:1800]}"
        )

        return

    print()
    print("=" * 60)
    print(
        "✅ ATI FUTURES V6 FINISHED"
    )
    print("=" * 60)


# =========================================================
# GLOBAL RUNNER
# =========================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "STOPPED BY USER"
        )

    except Exception as e:

        print()
        print("=" * 60)
        print(
            "❌ ATI FATAL ERROR"
        )
        print("=" * 60)

        print(
            str(e)
        )

        telegram(
            "❌ ATI FUTURES FATAL ERROR\n\n"
            + str(e)[:1800]
        )
