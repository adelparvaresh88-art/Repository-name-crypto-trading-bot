import os
import json
import time
import math
import hmac
import hashlib
import requests

from datetime import datetime, timezone
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# ATI FUTURES V9.2 REAL
# ============================================================
#
# NO tabdeal package
# NO fake historical candles
# NO aggTrades guess
#
# PUBLIC:
#   /r/fapi/v1/exchangeInfo
#   /r/fapi/v1/depth
#
# TRADE:
#   /fapi/v1/order
#   /fapi/v1/leverage
#   /r/fapi/v1/position
#   /fapi/v1/positionSlTp
#
# STRATEGY:
#   5M persistent candles
#   Ichimoku 9 / 26 / 52
#
# ORDER:
#   2 USDT margin
#   3x leverage
#
# REAL TRADING:
#   TRUE
#
# ============================================================


# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

STATE_FILE = "ati_futures_state.json"

ORDER_USDT = float(
    os.getenv("ORDER_USDT", "2")
)

LEVERAGE = int(
    os.getenv("LEVERAGE", "3")
)

REAL_TRADING = (
    os.getenv(
        "REAL_TRADING",
        "true"
    ).lower()
    == "true"
)

SCAN_UNIVERSE = int(
    os.getenv("SCAN_UNIVERSE", "75")
)

MAX_WORKERS = int(
    os.getenv("MAX_WORKERS", "20")
)

MIN_SCORE = int(
    os.getenv("MIN_SCORE", "6")
)

TP_PCT = float(
    os.getenv("TP_PCT", "0.02")
)

SL_PCT = float(
    os.getenv("SL_PCT", "0.01")
)

RECV_WINDOW = int(
    os.getenv("RECV_WINDOW", "5000")
)

REQUEST_TIMEOUT = int(
    os.getenv("REQUEST_TIMEOUT", "10")
)

CANDLE_MS = 5 * 60 * 1000

MIN_CANDLES = 53


# ============================================================
# SECRET COMPATIBILITY
# ============================================================
#
# اول نام‌های قدیمی TABDIL
# سپس TABDEAL
#
# بنابراین لازم نیست Secretهای قبلی را تغییر بدهی.
# ============================================================

def env_first(*names):

    for name in names:

        value = os.getenv(
            name,
            ""
        ).strip()

        if value:
            return value

    return ""


API_KEY = env_first(
    "TABDIL_API_KEY",
    "TABDEAL_API_KEY",
    "TABDIL_KEY",
    "TABDEAL_KEY",
)

API_SECRET = env_first(
    "TABDIL_API_SECRET",
    "TABDEAL_API_SECRET",
    "TABDIL_SECRET",
    "TABDEAL_SECRET",
)

TELEGRAM_TOKEN = env_first(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = env_first(
    "TELEGRAM_CHAT_ID"
)


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-FUTURES-V9.2",
    "Accept": "application/json",
})


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):

    if (
        not TELEGRAM_TOKEN
        or not TELEGRAM_CHAT_ID
    ):
        print(
            "Telegram credentials missing"
        )
        return False

    try:

        response = session.post(
            "https://api.telegram.org/"
            f"bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )

        return response.ok

    except Exception as e:

        print(
            "Telegram ERROR:",
            e
        )

        return False


# ============================================================
# PUBLIC GET
# ============================================================

def public_get(
    path,
    params=None
):

    response = session.get(
        BASE_URL + path,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )

    try:

        data = response.json()

    except Exception:

        raise RuntimeError(
            "Invalid JSON response"
        )

    if isinstance(data, dict):

        code = data.get("code")

        if (
            code is not None
            and code != 0
        ):

            raise RuntimeError(
                f"API {code}: "
                f"{data.get('msg', '')}"
            )

    return data


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(
    method,
    path,
    params=None
):

    if not API_KEY:
        raise RuntimeError(
            "API KEY missing"
        )

    if not API_SECRET:
        raise RuntimeError(
            "API SECRET missing"
        )

    data = dict(
        params or {}
    )

    data["timestamp"] = int(
        time.time() * 1000
    )

    data["recvWindow"] = (
        RECV_WINDOW
    )

    query = urlencode(
        data
    )

    signature = hmac.new(
        API_SECRET.encode(
            "utf-8"
        ),
        query.encode(
            "utf-8"
        ),
        hashlib.sha256,
    ).hexdigest()

    data["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "User-Agent": "ATI-FUTURES-V9.2",
    }

    if method == "GET":

        response = session.get(
            BASE_URL + path,
            params=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    elif method == "POST":

        response = session.post(
            BASE_URL + path,
            data=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    elif method == "DELETE":

        response = session.delete(
            BASE_URL + path,
            params=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    else:

        raise RuntimeError(
            f"Unsupported method: {method}"
        )

    if response.status_code >= 400:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    try:

        return response.json()

    except Exception:

        return {
            "raw": response.text
        }


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_markets():

    data = public_get(
        "/r/fapi/v1/exchangeInfo"
    )

    markets = data.get(
        "symbols",
        []
    )

    result = []

    for market in markets:

        symbol = str(
            market.get(
                "symbol",
                ""
            )
        ).upper()

        status = str(
            market.get(
                "status",
                ""
            )
        ).upper()

        quote = str(
            market.get(
                "quoteAsset",
                ""
            )
        ).upper()

        if not symbol:
            continue

        if status not in (
            "TRADING",
            "ENABLED",
        ):
            continue

        if quote != "USDT":
            continue

        result.append(
            market
        )

    return result[
        :SCAN_UNIVERSE
    ]


# ============================================================
# DEPTH
# ============================================================

def get_depth_price(
    symbol
):

    data = public_get(
        "/r/fapi/v1/depth",
        {
            "symbol": symbol,
            "limit": 5,
        },
    )

    bids = data.get(
        "bids",
        []
    )

    asks = data.get(
        "asks",
        []
    )

    if not bids:
        raise RuntimeError(
            "No bids"
        )

    if not asks:
        raise RuntimeError(
            "No asks"
        )

    bid = float(
        bids[0][0]
    )

    ask = float(
        asks[0][0]
    )

    if (
        bid <= 0
        or ask <= 0
    ):
        raise RuntimeError(
            "Invalid price"
        )

    mid = (
        bid + ask
    ) / 2.0

    return {
        "bid": bid,
        "ask": ask,
        "mid": mid,
    }


# ============================================================
# STATE
# ============================================================

def empty_state():

    return {
        "candles": {},
        "last_order": None,
        "last_signal": {},
    }


def load_state():

    if not os.path.exists(
        STATE_FILE
    ):
        return empty_state()

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            state = json.load(
                file
            )

        if not isinstance(
            state,
            dict
        ):
            return empty_state()

        state.setdefault(
            "candles",
            {}
        )

        state.setdefault(
            "last_order",
            None
        )

        state.setdefault(
            "last_signal",
            {}
        )

        return state

    except Exception as e:

        print(
            "STATE LOAD ERROR:",
            e
        )

        return empty_state()


def save_state(
    state
):

    temp_file = (
        STATE_FILE
        + ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            state,
            file,
            ensure_ascii=False,
            separators=(
                ",",
                ":"
            ),
        )

    os.replace(
        temp_file,
        STATE_FILE
    )


# ============================================================
# 5 MINUTE CANDLE
# ============================================================

def update_candle(
    state,
    symbol,
    price,
    timestamp_ms
):

    bucket = (
        timestamp_ms
        // CANDLE_MS
    ) * CANDLE_MS

    candles = state[
        "candles"
    ].setdefault(
        symbol,
        []
    )

    # Existing candle
    for candle in candles:

        if candle["time"] == bucket:

            candle["high"] = max(
                float(
                    candle["high"]
                ),
                price
            )

            candle["low"] = min(
                float(
                    candle["low"]
                ),
                price
            )

            candle["close"] = price

            return candle

    # New candle
    candle = {
        "time": bucket,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": 0,
    }

    candles.append(
        candle
    )

    candles.sort(
        key=lambda x:
        x["time"]
    )

    # Keep last 120 candles
    state[
        "candles"
    ][symbol] = candles[
        -120:
    ]

    return candle


# ============================================================
# ICHIMOKU
# ============================================================

def ichimoku_mid(
    candles,
    index,
    period
):

    start = (
        index
        - period
        + 1
    )

    if start < 0:
        return None

    section = candles[
        start:
        index + 1
    ]

    highs = [
        float(
            x["high"]
        )
        for x in section
    ]

    lows = [
        float(
            x["low"]
        )
        for x in section
    ]

    return (
        max(highs)
        +
        min(lows)
    ) / 2.0


def calculate_ichimoku(
    candles
):

    if len(candles) < 52:
        return None

    index = (
        len(candles)
        - 1
    )

    tenkan = ichimoku_mid(
        candles,
        index,
        9
    )

    kijun = ichimoku_mid(
        candles,
        index,
        26
    )

    span_b = ichimoku_mid(
        candles,
        index,
        52
    )

    if (
        tenkan is None
        or kijun is None
        or span_b is None
    ):
        return None

    span_a = (
        tenkan
        + kijun
    ) / 2.0

    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "span_a": span_a,
        "span_b": span_b,
    }


# ============================================================
# SIGNAL ENGINE
# ============================================================

def analyze_symbol(
    symbol,
    candles
):

    if len(candles) < MIN_CANDLES:
        return None

    candles = sorted(
        candles,
        key=lambda x:
        x["time"]
    )

    current = calculate_ichimoku(
        candles
    )

    previous = calculate_ichimoku(
        candles[:-1]
    )

    if (
        current is None
        or previous is None
    ):
        return None

    last = candles[-1]
    prev = candles[-2]

    close = float(
        last["close"]
    )

    previous_close = float(
        prev["close"]
    )

    cloud_top = max(
        current["span_a"],
        current["span_b"]
    )

    cloud_bottom = min(
        current["span_a"],
        current["span_b"]
    )

    buy_score = 0
    sell_score = 0

    buy_reasons = []
    sell_reasons = []

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    if close > cloud_top:

        buy_score += 2

        buy_reasons.append(
            "PRICE_ABOVE_CLOUD"
        )

    if (
        current["tenkan"]
        > current["kijun"]
    ):

        buy_score += 2

        buy_reasons.append(
            "TENKAN_GT_KIJUN"
        )

    if (
        current["span_a"]
        > current["span_b"]
    ):

        buy_score += 1

        buy_reasons.append(
            "BULLISH_CLOUD"
        )

    if close > previous_close:

        buy_score += 1

        buy_reasons.append(
            "MOMENTUM_UP"
        )

    if (
        current["kijun"]
        > previous["kijun"]
    ):

        buy_score += 1

        buy_reasons.append(
            "KIJUN_RISING"
        )

    # --------------------------------------------------------
    # SELL
    # --------------------------------------------------------

    if close < cloud_bottom:

        sell_score += 2

        sell_reasons.append(
            "PRICE_BELOW_CLOUD"
        )

    if (
        current["tenkan"]
        < current["kijun"]
    ):

        sell_score += 2

        sell_reasons.append(
            "TENKAN_LT_KIJUN"
        )

    if (
        current["span_a"]
        < current["span_b"]
    ):

        sell_score += 1

        sell_reasons.append(
            "BEARISH_CLOUD"
        )

    if close < previous_close:

        sell_score += 1

        sell_reasons.append(
            "MOMENTUM_DOWN"
        )

    if (
        current["kijun"]
        < previous["kijun"]
    ):

        sell_score += 1

        sell_reasons.append(
            "KIJUN_FALLING"
        )

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    if (
        buy_score >= MIN_SCORE
        and buy_score > sell_score
    ):

        return {
            "symbol": symbol,
            "signal": "BUY",
            "score": buy_score,
            "price": close,
            "reasons": buy_reasons,
        }

    if (
        sell_score >= MIN_SCORE
        and sell_score > buy_score
    ):

        return {
            "symbol": symbol,
            "signal": "SELL",
            "score": sell_score,
            "price": close,
            "reasons": sell_reasons,
        }

    return None


# ============================================================
# SYMBOL FILTER RULES
# ============================================================

def get_quantity_rules(
    market
):

    result = {
        "step": 0.0,
        "min_qty": 0.0,
        "max_qty": 0.0,
    }

    filters = market.get(
        "filters",
        []
    )

    for item in filters:

        filter_type = str(
            item.get(
                "filterType",
                ""
            )
        )

        if filter_type in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE",
        ):

            result["step"] = float(
                item.get(
                    "stepSize",
                    0
                )
            )

            result["min_qty"] = float(
                item.get(
                    "minQty",
                    0
                )
            )

            result["max_qty"] = float(
                item.get(
                    "maxQty",
                    0
                )
            )

            break

    return result


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


def make_quantity(
    market,
    price
):

    rules = get_quantity_rules(
        market
    )

    # 2 USDT margin × 3 leverage
    notional = (
        ORDER_USDT
        * LEVERAGE
    )

    raw_quantity = (
        notional
        / price
    )

    quantity = floor_step(
        raw_quantity,
        rules["step"]
    )

    if (
        rules["min_qty"] > 0
        and quantity
        < rules["min_qty"]
    ):

        quantity = (
            rules["min_qty"]
        )

    if (
        rules["max_qty"] > 0
        and quantity
        > rules["max_qty"]
    ):

        quantity = (
            rules["max_qty"]
        )

    if quantity <= 0:

        raise RuntimeError(
            "Quantity calculated as zero"
        )

    return (
        f"{quantity:.12f}"
        .rstrip("0")
        .rstrip(".")
    )


# ============================================================
# LEVERAGE
# ============================================================

def change_leverage(
    symbol
):

    return signed_request(
        "POST",
        "/fapi/v1/leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE,
        },
    )


# ============================================================
# POSITION
# ============================================================

def get_positions():

    return signed_request(
        "GET",
        "/fapi/v1/position",
        {
            "isActive": 1,
        },
    )


def find_active_position():

    data = get_positions()

    if isinstance(
        data,
        dict
    ):

        positions = data.get(
            "positions",
            []
        )

        # Some responses can be a
        # single position object
        if not positions:

            if (
                "positionAmt" in data
                or "quantity" in data
            ):

                positions = [data]

    elif isinstance(
        data,
        list
    ):

        positions = data

    else:

        positions = []

    for position in positions:

        try:

            amount = float(
                position.get(
                    "positionAmt",
                    position.get(
                        "quantity",
                        0
                    )
                )
            )

        except Exception:

            amount = 0

        if abs(amount) > 0:

            return position

    return None


# ============================================================
# REAL MARKET ORDER
# ============================================================

def place_real_order(
    market,
    signal
):

    symbol = signal[
        "symbol"
    ]

    price = float(
        signal["price"]
    )

    # Set 3x
    change_leverage(
        symbol
    )

    quantity = make_quantity(
        market,
        price
    )

    side = (
        "BUY"
        if signal["signal"]
        == "BUY"
        else "SELL"
    )

    result = signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
            "reduceOnly": "false",
        },
    )

    return {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "result": result,
    }


# ============================================================
# SL / TP
# ============================================================

def set_position_sl_tp(
    signal
):

    symbol = signal[
        "symbol"
    ]

    position = get_positions()

    if isinstance(
        position,
        dict
    ):

        positions = position.get(
            "positions",
            []
        )

        if not positions:

            if (
                "positionAmt" in position
                or "quantity" in position
            ):

                positions = [
                    position
                ]

    elif isinstance(
        position,
        list
    ):

        positions = position

    else:

        positions = []

    active = None

    for item in positions:

        try:

            amount = float(
                item.get(
                    "positionAmt",
                    item.get(
                        "quantity",
                        0
                    )
                )
            )

        except Exception:

            amount = 0

        if (
            abs(amount) > 0
            and str(
                item.get(
                    "symbol",
                    symbol
                )
            ) == symbol
        ):

            active = item
            break

    if active is None:

        return {
            "ok": False,
            "message":
                "Position not found yet",
        }

    position_id = active.get(
        "positionId"
    )

    if position_id is None:

        return {
            "ok": False,
            "message":
                "positionId missing",
        }

    entry_price = float(
        active.get(
            "entryPrice",
            signal["price"]
        )
    )

    if signal["signal"] == "BUY":

        sl_price = (
            entry_price
            * (1 - SL_PCT)
        )

        tp_price = (
            entry_price
            * (1 + TP_PCT)
        )

    else:

        sl_price = (
            entry_price
            * (1 + SL_PCT)
        )

        tp_price = (
            entry_price
            * (1 - TP_PCT)
        )

    result = signed_request(
        "POST",
        "/fapi/v1/positionSlTp",
        {
            "positionId":
                position_id,

            "symbol":
                symbol,

            "slPrice":
                str(sl_price),

            "tpPrice":
                str(tp_price),
        },
    )

    return {
        "ok": True,
        "entry": entry_price,
        "sl": sl_price,
        "tp": tp_price,
        "result": result,
    }


# ============================================================
# ONE SYMBOL SCAN
# ============================================================

def scan_one(
    market,
    state
):

    symbol = market.get(
        "symbol",
        ""
    )

    try:

        price_data = (
            get_depth_price(
                symbol
            )
        )

        price = float(
            price_data["mid"]
        )

        timestamp_ms = int(
            time.time()
            * 1000
        )

        candle = (
            update_candle(
                state,
                symbol,
                price,
                timestamp_ms,
            )
        )

        candles = state[
            "candles"
        ][symbol]

        signal = (
            analyze_symbol(
                symbol,
                candles
            )
        )

        return {
            "ok": True,
            "symbol": symbol,
            "price": price,
            "candle": candle,
            "candle_count":
                len(candles),
            "signal": signal,
            "error": None,
        }

    except Exception as e:

        return {
            "ok": False,
            "symbol": symbol,
            "price": None,
            "candle": None,
            "candle_count": 0,
            "signal": None,
            "error":
                str(e)[:200],
        }


# ============================================================
# MAIN
# ============================================================

def main():

    start_time = time.time()

    print(
        "💓 ATI FUTURES V9.2 REAL"
    )

    print(
        "⚡ FAST FUTURES SCANNER"
    )

    print(
        "☁️ ICHIMOKU 9 / 26 / 52"
    )

    print(
        f"💵 ORDER: "
        f"{ORDER_USDT} USDT"
    )

    print(
        f"⚡ LEVERAGE: "
        f"{LEVERAGE}x"
    )

    print(
        f"🔒 REAL TRADING: "
        f"{REAL_TRADING}"
    )

    print(
        "🔐 API KEY:",
        "FOUND"
        if API_KEY
        else "MISSING"
    )

    print(
        "🔐 API SECRET:",
        "FOUND"
        if API_SECRET
        else "MISSING"
    )

    # --------------------------------------------------------
    # Credentials
    # --------------------------------------------------------

    if REAL_TRADING:

        if not API_KEY:

            message = (
                "❌ ATI FUTURES V9.2\n\n"
                "API KEY پیدا نشد.\n"
                "Secretهای TABDIL/TABDEAL بررسی شد."
            )

            print(message)
            telegram(message)
            return

        if not API_SECRET:

            message = (
                "❌ ATI FUTURES V9.2\n\n"
                "API SECRET پیدا نشد.\n"
                "Secretهای TABDIL/TABDEAL بررسی شد."
            )

            print(message)
            telegram(message)
            return

    # --------------------------------------------------------
    # Markets
    # --------------------------------------------------------

    try:

        markets = get_markets()

    except Exception as e:

        message = (
            "❌ ATI FUTURES ERROR\n\n"
            "ExchangeInfo failed:\n"
            f"{e}"
        )

        print(message)
        telegram(message)
        return

    # --------------------------------------------------------
    # State
    # --------------------------------------------------------

    state = load_state()

    # --------------------------------------------------------
    # Scan
    # --------------------------------------------------------

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        jobs = [
            executor.submit(
                scan_one,
                market,
                state
            )
            for market in markets
        ]

        for job in as_completed(
            jobs
        ):

            try:

                results.append(
                    job.result()
                )

            except Exception as e:

                results.append({
                    "ok": False,
                    "symbol": "?",
                    "error": str(e),
                    "signal": None,
                    "candle_count": 0,
                })

    ok_count = sum(
        1
        for item in results
        if item["ok"]
    )

    error_count = (
        len(results)
        - ok_count
    )

    ready = [
        item
        for item in results
        if item["ok"]
        and item[
            "candle_count"
        ] >= MIN_CANDLES
    ]

    signals = []

    for item in ready:

        signal = item.get(
            "signal"
        )

        if signal:

            signals.append(
                signal
            )

    signals.sort(
        key=lambda x:
        x["score"],
        reverse=True,
    )

    # --------------------------------------------------------
    # Save state
    # --------------------------------------------------------

    save_state(
        state
    )

    # --------------------------------------------------------
    # REAL TRADE
    # --------------------------------------------------------

    order_result = None
    sltp_result = None

    if (
        REAL_TRADING
        and signals
    ):

        try:

            active_position = (
                find_active_position()
            )

            if active_position:

                print(
                    "🔒 ACTIVE POSITION"
                )

            else:

                selected = signals[0]

                selected_market = None

                for market in markets:

                    if (
                        market.get(
                            "symbol"
                        )
                        ==
                        selected[
                            "symbol"
                        ]
                    ):

                        selected_market = (
                            market
                        )

                        break

                if selected_market:

                    print(
                        "🚨 REAL SIGNAL:",
                        selected
                    )

                    order_result = (
                        place_real_order(
                            selected_market,
                            selected
                        )
                    )

                    print(
                        "ORDER:",
                        order_result
                    )

                    # Give exchange a moment
                    # to register the position
                    time.sleep(2)

                    sltp_result = (
                        set_position_sl_tp(
                            selected
                        )
                    )

                    print(
                        "SLTP:",
                        sltp_result
                    )

                    state[
                        "last_order"
                    ] = {
                        "time":
                            int(
                                time.time()
                            ),
                        "signal":
                            selected,
                        "order":
                            order_result,
                        "sltp":
                            sltp_result,
                    }

                    state[
                        "last_signal"
                    ][
                        selected[
                            "symbol"
                        ]
                    ] = selected

                    save_state(
                        state
                    )

        except Exception as e:

            order_result = {
                "error":
                    str(e)
            }

            print(
                "❌ REAL ORDER ERROR:",
                e
            )

    # --------------------------------------------------------
    # REPORT
    # --------------------------------------------------------

    elapsed = (
        time.time()
        - start_time
    )

    message = (
        "💓 ATI FUTURES V9.2\n\n"
        "⚡ DEPTH → 5M PERSISTENT\n"
        "☁️ ICHIMOKU 9 / 26 / 52\n\n"
        f"📊 Markets: "
        f"{len(markets)}\n"
        f"📈 5M OK: "
        f"{ok_count}\n"
        f"🧠 Ready: "
        f"{len(ready)}\n"
        f"🔥 Signals: "
        f"{len(signals)}\n"
        f"❌ Errors: "
        f"{error_count}\n"
        f"⏱️ Scan: "
        f"{elapsed:.2f}s\n\n"
    )

    if signals:

        message += (
            "🔥 TOP SIGNALS\n\n"
        )

        for signal in signals[:5]:

            if (
                signal["signal"]
                == "BUY"
            ):

                emoji = "🟢"

            else:

                emoji = "🔴"

            message += (
                f"{emoji} "
                f"{signal['signal']} "
                f"{signal['symbol']}\n"
                f"💰 "
                f"{signal['price']:.10g}\n"
                f"⭐ Score: "
                f"{signal['score']}\n"
                f"📋 "
                f"{', '.join(signal['reasons'])}\n\n"
            )

    else:

        message += (
            "☁️ NO SIGNAL THIS CYCLE\n\n"
        )

    # --------------------------------------------------------
    # ORDER REPORT
    # --------------------------------------------------------

    if order_result:

        if "error" in order_result:

            message += (
                "❌ REAL ORDER FAILED\n"
                f"{order_result['error']}\n\n"
            )

        else:

            message += (
                "🚨 REAL ORDER EXECUTED\n\n"
                f"💎 Symbol: "
                f"{order_result['symbol']}\n"
                f"📌 Side: "
                f"{order_result['side']}\n"
                f"📦 Qty: "
                f"{order_result['quantity']}\n"
            )

            if (
                sltp_result
                and sltp_result.get(
                    "ok"
                )
            ):

                message += (
                    f"💰 Entry: "
                    f"{sltp_result['entry']:.10g}\n"
                    f"🛑 SL: "
                    f"{sltp_result['sl']:.10g}\n"
                    f"🎯 TP: "
                    f"{sltp_result['tp']:.10g}\n"
                )

            elif sltp_result:

                message += (
                    "⚠️ SL/TP:\n"
                    f"{sltp_result.get('message', '')}\n"
                )

            message += "\n"

    message += (
        f"💵 ORDER: "
        f"{ORDER_USDT} USDT\n"
        f"⚡ LEVERAGE: "
        f"{LEVERAGE}x\n"
        f"🔒 REAL TRADING: "
        f"{REAL_TRADING}\n"
        "🕐 "
        +
        datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    print(
        message
    )

    telegram(
        message
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
