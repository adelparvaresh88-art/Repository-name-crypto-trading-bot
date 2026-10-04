import os
import time
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.48-REAL
# TABDEAL SPOT
# REAL BOS / NEAR BOS → PULLBACK → CLOSED CONFIRM
# EMA OFF
# ============================================================

VERSION = "V40.2.48-REAL"

BASE = "https://api1.tabdeal.org"
PUBLIC_ROOT = f"{BASE}/r/api/v1"
SIGNED_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 20
RECV_WINDOW = 10000

# ------------------------------------------------------------
# SIGNAL SETTINGS
# ------------------------------------------------------------

MIN_CANDLES = 20
BOS_LOOKBACK = 6

# نزدیک بودن قیمت به سقف شکست قبلی
NEAR_BOS_TOL = 0.004       # 0.4%

# محدوده Pullback
PULLBACK_TOL = 0.012       # 1.2%

# جلوگیری از خرید بعد از پامپ خیلی شدید
MAX_MOVE_5M = 0.040        # 4%

# قدرت کندل تأیید
MIN_BODY_RATIO = 0.40
MIN_CLOSE_POSITION = 0.52

# حداقل امتیاز
MIN_SCORE = 6

# تعداد بازارهای اسکن
SCAN_LIMIT = 300

# هر چند بازار یک Heartbeat
HEARTBEAT_EVERY = 25


# ------------------------------------------------------------
# API / TELEGRAM
# ------------------------------------------------------------

API_KEY = (
    os.getenv("TABDIL_API_KEY")
    or os.getenv("TABDEAL_API_KEY")
    or ""
)

API_SECRET = (
    os.getenv("TABDIL_API_SECRET")
    or os.getenv("TABDEAL_API_SECRET")
    or ""
)

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or ""
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID") or ""

REAL_TRADING = (
    os.getenv(
        "LIVE_TRADING",
        os.getenv("REAL_TRADING", "true")
    ).lower()
    == "true"
)

ORDER_USDT = float(
    os.getenv(
        "ORDER_USDT",
        os.getenv("ORDER_QTY", "2")
    )
)

RESERVE_USDT = float(
    os.getenv(
        "BALANCE_RESERVE_USDT",
        "0.02"
    )
)


session = requests.Session()


# ============================================================
# HELPERS
# ============================================================

def now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def tg(message):
    if not TG_TOKEN or not TG_CHAT:
        return False

    try:
        r = session.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={
                "chat_id": TG_CHAT,
                "text": message
            },
            timeout=15
        )

        return r.ok

    except Exception:
        return False


# ============================================================
# SIGNED API
# ============================================================

def signed_get(path, params=None):

    params = dict(params or {})

    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = RECV_WINDOW

    query = "&".join(
        f"{key}={params[key]}"
        for key in sorted(params)
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    return session.get(
        f"{SIGNED_ROOT}{path}?{query}&signature={signature}",
        headers=headers,
        timeout=TIMEOUT
    )


def signed_post(path, params):

    params = dict(params)

    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = RECV_WINDOW

    query = "&".join(
        f"{key}={params[key]}"
        for key in sorted(params)
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    return session.post(
        f"{ORDER_ROOT}{path}",
        data=f"{query}&signature={signature}",
        headers=headers,
        timeout=TIMEOUT
    )


def public_get(path, params=None):

    return session.get(
        f"{PUBLIC_ROOT}{path}",
        params=params or {},
        timeout=TIMEOUT
    )


# ============================================================
# ACCOUNT
# ============================================================

def auth_test():

    try:

        r = signed_get("/account")

        if r.ok:
            return r.json()

        print(
            "AUTH ERROR:",
            r.status_code,
            r.text[:500]
        )

    except Exception as e:

        print(
            "AUTH EXCEPTION:",
            e
        )

    return None


def get_balance():

    data = auth_test()

    if not data:
        return 0.0

    for balance in data.get("balances", []):

        if balance.get("asset") == "USDT":

            return float(
                balance.get("free", 0)
            )

    return 0.0


# ============================================================
# MARKETS
# ============================================================

def get_markets():

    r = public_get("/exchangeInfo")

    r.raise_for_status()

    data = r.json()

    markets = []

    for symbol in data.get("symbols", []):

        if symbol.get("status") not in (
            "TRADING",
            "ACTIVE",
            None
        ):
            continue

        if symbol.get("quoteAsset") != "USDT":
            continue

        if symbol.get("baseAsset") == "USDT":
            continue

        markets.append(symbol)

    return markets[:SCAN_LIMIT]


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):

    try:

        r = public_get(
            "/trades",
            {
                "symbol": symbol,
                "limit": 1000
            }
        )

        if not r.ok:
            return []

        return r.json()

    except Exception:

        return []


# ============================================================
# BUILD 5M CLOSED CANDLES
# ============================================================

def candles_from_trades(trades):

    buckets = {}

    for trade in trades:

        try:

            timestamp = int(
                trade.get(
                    "time",
                    trade.get("T", 0)
                )
            )

            price = float(
                trade.get(
                    "price",
                    trade.get("p")
                )
            )

            quantity = float(
                trade.get(
                    "qty",
                    trade.get("q", 0)
                )
            )

            if timestamp <= 0:
                continue

            if price <= 0:
                continue

            bucket = (
                timestamp // 300000
            ) * 300000

            if bucket not in buckets:

                buckets[bucket] = [
                    price,   # open
                    price,   # high
                    price,   # low
                    price,   # close
                    0.0      # volume
                ]

            candle = buckets[bucket]

            candle[1] = max(
                candle[1],
                price
            )

            candle[2] = min(
                candle[2],
                price
            )

            candle[3] = price

            candle[4] += quantity

        except Exception:

            continue

    keys = sorted(buckets)

    # حذف کندل 5 دقیقه‌ای در حال تشکیل
    current_bucket = (
        int(time.time() * 1000) // 300000
    ) * 300000

    keys = [
        key
        for key in keys
        if key < current_bucket
    ]

    return [
        buckets[key]
        for key in keys
    ]


# ============================================================
# SIGNAL ENGINE
# ============================================================

def build_signal(candles):

    result = {
        "reason": "NO_SIGNAL"
    }

    if len(candles) < MIN_CANDLES:

        result["reason"] = "CANDLES"

        return None, result


    last = candles[-1]

    recent = candles[
        -(BOS_LOOKBACK + 1):-1
    ]

    swing_high = max(
        candle[1]
        for candle in recent
    )

    previous_close = candles[-2][3]

    close = last[3]
    high = last[1]
    low = last[2]
    open_price = last[0]


    # --------------------------------------------------------
    # TREND SCORE
    # --------------------------------------------------------

    trend_score = 0

    if candles[-1][3] > candles[-3][3]:
        trend_score += 1

    if candles[-3][3] > candles[-6][3]:
        trend_score += 1


    # --------------------------------------------------------
    # REAL BOS
    # --------------------------------------------------------

    real_bos = close > swing_high


    # --------------------------------------------------------
    # NEAR BOS
    # --------------------------------------------------------

    distance_to_bos = (
        swing_high - close
    ) / max(
        swing_high,
        1e-12
    )

    near_bos = (
        distance_to_bos <= NEAR_BOS_TOL
        and close >= previous_close
    )


    if not (real_bos or near_bos):

        result["reason"] = "BOS"

        return None, result


    # --------------------------------------------------------
    # PULLBACK
    # --------------------------------------------------------

    broken_level = swing_high

    pullback = (
        abs(close - broken_level)
        / max(broken_level, 1e-12)
        <= PULLBACK_TOL
        or
        low <= broken_level * (
            1 + PULLBACK_TOL
        )
    )


    if not pullback:

        result["reason"] = "PULLBACK"

        return None, result


    # --------------------------------------------------------
    # CLOSED CANDLE CONFIRMATION
    # --------------------------------------------------------

    candle_body = abs(
        close - open_price
    )

    candle_range = max(
        high - low,
        1e-12
    )

    body_ratio = (
        candle_body / candle_range
    )

    close_position = (
        (close - low)
        / candle_range
    )

    bullish = close > open_price

    confirmation = (
        bullish
        and body_ratio >= MIN_BODY_RATIO
        and close_position >= MIN_CLOSE_POSITION
    )


    if not confirmation:

        result["reason"] = "CONFIRM"

        return None, result


    # --------------------------------------------------------
    # 5M MOVE FILTER
    # --------------------------------------------------------

    move_5m = abs(
        close - candles[-2][3]
    ) / max(
        candles[-2][3],
        1e-12
    )


    if move_5m > MAX_MOVE_5M:

        result["reason"] = "MOVE"

        return None, result


    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = trend_score

    # REAL BOS قوی‌تر از NEAR BOS
    if real_bos:
        score += 3
    else:
        score += 2

    # Pullback
    score += 2

    # Closed candle confirmation
    score += 2

    # Close higher than previous candle
    if close > candles[-2][3]:
        score += 1


    if score < MIN_SCORE:

        result["reason"] = "SCORE"

        return None, result


    # --------------------------------------------------------
    # STOP LOSS
    # --------------------------------------------------------

    stop_loss = min(
        candle[2]
        for candle in candles[-5:]
    )

    risk = close - stop_loss

    if risk <= 0:

        result["reason"] = "SL"

        return None, result


    take_profit_1 = (
        close + risk * 1.5
    )

    take_profit_2 = (
        close + risk * 2.0
    )


    signal = {

        "reason": "OK",

        "type": (
            "REAL BOS"
            if real_bos
            else "NEAR BOS"
        ),

        "entry": close,

        "sl": stop_loss,

        "tp1": take_profit_1,

        "tp2": take_profit_2,

        "score": score,

        "body_ratio": body_ratio,

        "close_pos": close_position
    }


    return signal, signal


# ============================================================
# ORDER RULES
# ============================================================

def symbol_rules(symbol_info):

    filters = {
        item.get("filterType"): item
        for item in symbol_info.get(
            "filters",
            []
        )
    }

    lot = filters.get(
        "LOT_SIZE",
        {}
    )

    notional = filters.get(
        "MIN_NOTIONAL",
        filters.get(
            "NOTIONAL",
            {}
        )
    )

    min_qty = float(
        lot.get("minQty", 0) or 0
    )

    step_size = float(
        lot.get("stepSize", 0) or 0
    )

    min_notional = float(
        notional.get(
            "minNotional",
            0
        ) or 0
    )

    return (
        min_qty,
        step_size,
        min_notional
    )


def floor_step(
    value,
    step
):

    if step <= 0:
        return value

    value_decimal = Decimal(
        str(value)
    )

    step_decimal = Decimal(
        str(step)
    )

    result = (
        value_decimal
        / step_decimal
    ).to_integral_value(
        rounding=ROUND_DOWN
    )

    return float(
        result * step_decimal
    )


# ============================================================
# REAL MARKET BUY
# ============================================================

def place_buy(
    symbol_info,
    signal,
    available_usdt
):

    symbol = symbol_info["symbol"]

    price = signal["entry"]


    # موجودی واقعی قابل استفاده
    budget = min(
        ORDER_USDT,
        max(
            0.0,
            available_usdt
            - RESERVE_USDT
        )
    )


    if budget <= 0:

        return (
            False,
            "AVAILABLE_USDT_TOO_LOW"
        )


    min_qty, step_size, min_notional = (
        symbol_rules(symbol_info)
    )


    quantity = (
        budget / price
    )


    quantity = floor_step(
        quantity,
        step_size
    )


    if quantity <= 0:

        return (
            False,
            f"QTY_TOO_SMALL qty={quantity}"
        )


    if quantity < min_qty:

        return (
            False,
            f"QTY_TOO_SMALL "
            f"qty={quantity} "
            f"minQty={min_qty}"
        )


    notional = (
        quantity * price
    )


    if (
        min_notional
        and notional < min_notional
    ):

        return (
            False,
            f"MIN_NOTIONAL "
            f"{notional:.8f}"
            f"<{min_notional}"
        )


    if not REAL_TRADING:

        return (
            False,
            "REAL_TRADING_DISABLED"
        )


    order_quantity = (
        f"{quantity:.12f}"
        .rstrip("0")
        .rstrip(".")
    )


    response = signed_post(
        "/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": order_quantity
        }
    )


    if response.ok:

        return (
            True,
            response.text[:500]
        )


    return (
        False,
        f"ORDER_ERROR "
        f"{response.status_code}: "
        f"{response.text[:500]}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        f"⚡ ATI BOT {VERSION}"
    )

    print(
        "🧠 REAL BOS / NEAR BOS "
        "→ PULLBACK → CLOSED CONFIRM"
    )

    print(
        "🚫 EMA: OFF"
    )

    print(
        "🔓 REAL TRADING:",
        "ENABLED"
        if REAL_TRADING
        else "DISABLED"
    )

    print(
        f"💵 ORDER TARGET: "
        f"{ORDER_USDT} USDT"
    )

    print(
        "🕐",
        now()
    )


    tg(
        f"🔎 SCAN STARTING\n"
        f"⚡ ATI BOT {VERSION}\n"
        f"🧠 REAL BOS / NEAR BOS "
        f"→ PULLBACK → CLOSED CONFIRM\n"
        f"⏱ 5m CLOSED CANDLES\n"
        f"🚫 EMA OFF\n"
        f"🔓 REAL TRADING: "
        f"{'ENABLED' if REAL_TRADING else 'DISABLED'}\n"
        f"🕐 {now()}"
    )


    if not API_KEY or not API_SECRET:

        tg(
            "❌ API KEY/SECRET MISSING"
        )

        return


    account = auth_test()

    if not account:

        tg(
            "❌ AUTH FAILED"
        )

        return


    balance = get_balance()


    tg(
        f"💰 BALANCE\n"
        f"USDT FREE: {balance:.6f}\n"
        f"🎯 TARGET: {ORDER_USDT:g} USDT\n"
        f"🔒 RESERVE: {RESERVE_USDT:g} USDT"
    )


    markets = get_markets()


    checked = 0
    signals = 0
    attempts = 0
    successful_orders = 0


    stats = {

        "CANDLES": 0,

        "BOS": 0,

        "PULLBACK": 0,

        "CONFIRM": 0,

        "MOVE": 0,

        "SCORE": 0,

        "SL": 0,

        "ERROR": 0
    }


    for symbol_info in markets:

        checked += 1

        symbol = symbol_info["symbol"]


        try:

            trades = get_trades(
                symbol
            )

            candles = candles_from_trades(
                trades
            )


            signal, detail = build_signal(
                candles
            )


            if signal is None:

                reason = detail.get(
                    "reason",
                    "ERROR"
                )

                stats[reason] = (
                    stats.get(reason, 0)
                    + 1
                )


            else:

                signals += 1


                tg(
                    f"🚨 SIGNAL DETECTED\n"
                    f"🪙 {symbol}\n"
                    f"📐 {signal['type']}\n"
                    f"💵 ENTRY: "
                    f"{signal['entry']:.12g}\n"
                    f"🛑 SL: "
                    f"{signal['sl']:.12g}\n"
                    f"🎯 TP1: "
                    f"{signal['tp1']:.12g}\n"
                    f"🎯 TP2: "
                    f"{signal['tp2']:.12g}\n"
                    f"⭐ SCORE: "
                    f"{signal['score']}"
                )


                attempts += 1


                success, message = place_buy(
                    symbol_info,
                    signal,
                    balance
                )


                if success:

                    successful_orders += 1


                    tg(
                        f"✅ REAL BUY SUCCESS\n"
                        f"🪙 {symbol}\n"
                        f"💵 TARGET: "
                        f"{ORDER_USDT:g} USDT\n"
                        f"{message}"
                    )


                    # فقط یک خرید در هر اجرای بات
                    break


                else:

                    tg(
                        f"⚠️ BUY NOT EXECUTED\n"
                        f"🪙 {symbol}\n"
                        f"{message}"
                    )


        except Exception as error:

            stats["ERROR"] += 1

            print(
                "PROCESS ERROR",
                symbol,
                repr(error)
            )


        # ----------------------------------------------------
        # HEARTBEAT
        # ----------------------------------------------------

        if checked % HEARTBEAT_EVERY == 0:

            tg(
                f"📡 SCAN HEARTBEAT\n"
                f"🔎 CHECKED: {checked}\n"
                f"🟢 SIGNALS: {signals}\n"
                f"🎯 ATTEMPTS: {attempts}\n"
                f"✅ SUCCESSFUL ORDERS: "
                f"{successful_orders}\n"
                f"💰 USDT: {balance:.6f}\n"
                f"🕐 {now()}"
            )


    # ========================================================
    # FINAL DIAGNOSTIC
    # ========================================================

    tg(
        f"📊 SCAN SUMMARY\n"
        f"🔎 CHECKED: {checked}\n"
        f"🟢 SIGNALS: {signals}\n"
        f"🎯 ATTEMPTS: {attempts}\n"
        f"✅ SUCCESSFUL ORDERS: "
        f"{successful_orders}\n\n"

        f"❌ REJECTED\n"
        f"CANDLES: "
        f"{stats.get('CANDLES', 0)}\n"
        f"BOS: "
        f"{stats.get('BOS', 0)}\n"
        f"PULLBACK: "
        f"{stats.get('PULLBACK', 0)}\n"
        f"CONFIRM: "
        f"{stats.get('CONFIRM', 0)}\n"
        f"MOVE: "
        f"{stats.get('MOVE', 0)}\n"
        f"SCORE: "
        f"{stats.get('SCORE', 0)}\n"
        f"SL: "
        f"{stats.get('SL', 0)}\n"
        f"ERROR: "
        f"{stats.get('ERROR', 0)}"
    )


    tg(
        f"✅ ATI BOT RUN COMPLETED\n"
        f"⚡ {VERSION}\n"
        f"🕐 {now()}"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
