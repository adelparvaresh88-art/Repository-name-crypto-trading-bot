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
# ATI FUTURES REAL V7.3
# FAST ICHIMOKU SCANNER
# ============================================================

API_BASE = "https://api1.tabdeal.org"

PUBLIC_V1 = API_BASE + "/r/fapi/v1/"
PRIVATE_V3 = API_BASE + "/r/fapi/v3/"
WRITE_V1 = API_BASE + "/fapi/v1/"

TIMEFRAME = "5m"
KLINE_LIMIT = 100

MAX_WORKERS = 16
SCAN_INTERVAL = 300

LEVERAGE = 3
ORDER_USDT = float(os.getenv("ORDER_QTY", "2"))

MAX_NEW_TRADES = 1

SL_PCT = 0.010
TP_PCT = 0.020

MIN_SCORE = 5.0
MAX_KIJUN_DISTANCE = 0.025

TENKAN_N = 9
KIJUN_N = 26
SENKOU_B_N = 52

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "true")
    .strip()
    .lower()
    in ("1", "true", "yes", "on")
)

BUY_LOCK = False


# ============================================================
# SECRETS
# ============================================================

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

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-FUTURES-V7.3"
})

print_lock = threading.Lock()


# ============================================================
# LOG
# ============================================================

def log(msg):
    with print_lock:
        print(msg, flush=True)


# ============================================================
# TELEGRAM
# ============================================================

def tg(msg):

    if not TG_TOKEN or not TG_CHAT_ID:
        return False

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{TG_TOKEN}/sendMessage"
        )

        r = session.post(
            url,
            data={
                "chat_id": TG_CHAT_ID,
                "text": msg
            },
            timeout=15
        )

        return r.ok

    except Exception as e:

        log(f"Telegram error: {e}")

        return False


# ============================================================
# PUBLIC API
# ============================================================

def public_get(path, params=None):

    last_error = None

    for attempt in range(3):

        try:

            r = session.get(
                PUBLIC_V1 + path.lstrip("/"),
                params=params,
                timeout=12
            )

            if r.status_code in (
                429,
                500,
                502,
                503,
                504
            ):

                last_error = f"HTTP {r.status_code}"

                time.sleep(
                    0.2 * (attempt + 1)
                )

                continue

            r.raise_for_status()

            return r.json()

        except Exception as e:

            last_error = str(e)

            if attempt < 2:
                time.sleep(
                    0.15 * (attempt + 1)
                )

    raise RuntimeError(
        last_error or "Public request failed"
    )


# ============================================================
# SIGNED API
# ============================================================

def signed_request(
    method,
    base,
    path,
    params=None
):

    if not API_KEY or not API_SECRET:

        raise RuntimeError(
            "TABDIL/TABDEAL API credentials are missing"
        )

    p = dict(params or {})

    p["timestamp"] = int(
        time.time() * 1000
    )

    p.setdefault(
        "recvWindow",
        5000
    )

    query = urlencode(
        p,
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

    r = session.request(
        method,
        url,
        headers={
            "X-MBX-APIKEY": API_KEY
        },
        timeout=15
    )

    if not r.ok:

        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:500]}"
        )

    return r.json()


def private_get(path, params=None):

    return signed_request(
        "GET",
        PRIVATE_V3,
        path,
        params
    )


def private_post(path, params=None):

    return signed_request(
        "POST",
        WRITE_V1,
        path,
        params
    )


def private_delete(path, params=None):

    return signed_request(
        "DELETE",
        WRITE_V1,
        path,
        params
    )


# ============================================================
# NUMBER HELPERS
# ============================================================

def floor_step(value, step):

    if step <= 0:
        return value

    return (
        math.floor(
            value / step + 1e-12
        )
        * step
    )


def fmt_num(value, decimals=8):

    return (
        f"{value:.{decimals}f}"
        .rstrip("0")
        .rstrip(".")
    )


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    return public_get(
        "exchangeInfo"
    )


def get_symbols():

    info = get_exchange_info()

    symbols = []

    for s in info.get(
        "symbols",
        []
    ):

        symbol = s.get(
            "symbol",
            ""
        )

        status = str(
            s.get(
                "status",
                ""
            )
        ).upper()

        quote = str(
            s.get(
                "quoteAsset",
                ""
            )
        ).upper()

        contract = str(
            s.get(
                "contractType",
                ""
            )
        ).upper()

        if status not in (
            "TRADING",
            "BREAK"
        ):
            continue

        if quote != "USDT":
            continue

        if contract and contract not in (
            "PERPETUAL",
            "PERPETUAL_CONTRACT"
        ):
            continue

        symbols.append(symbol)

    return sorted(
        set(symbols)
    )


def get_symbol_filters():

    info = get_exchange_info()

    filters = {}

    for s in info.get(
        "symbols",
        []
    ):

        symbol = s.get(
            "symbol"
        )

        if not symbol:
            continue

        data = {
            "step": 0.0,
            "min_qty": 0.0,
            "tick": 0.0,
            "min_notional": 0.0
        }

        for f in s.get(
            "filters",
            []
        ):

            typ = f.get(
                "filterType"
            )

            if typ == "LOT_SIZE":

                data["step"] = float(
                    f.get(
                        "stepSize",
                        0
                    ) or 0
                )

                data["min_qty"] = float(
                    f.get(
                        "minQty",
                        0
                    ) or 0
                )

            elif typ == "PRICE_FILTER":

                data["tick"] = float(
                    f.get(
                        "tickSize",
                        0
                    ) or 0
                )

            elif typ in (
                "MIN_NOTIONAL",
                "NOTIONAL"
            ):

                data["min_notional"] = float(
                    f.get(
                        "notional",
                        f.get(
                            "minNotional",
                            0
                        )
                    ) or 0
                )

        filters[symbol] = data

    return filters


# ============================================================
# KLINES
# ============================================================

def get_klines(symbol):

    data = public_get(
        "klines",
        {
            "symbol": symbol,
            "interval": TIMEFRAME,
            "limit": KLINE_LIMIT
        }
    )

    candles = []

    for x in data:

        if len(x) < 6:
            continue

        candles.append({
            "t": int(x[0]),
            "o": float(x[1]),
            "h": float(x[2]),
            "l": float(x[3]),
            "c": float(x[4]),
            "v": float(x[5])
        })

    return candles


# ============================================================
# ICHIMOKU
# ============================================================

def mid_high_low(candles, n):

    if len(candles) < n:
        return None

    part = candles[-n:]

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


def ichimoku(candles):

    # فقط کندل بسته‌شده
    closed = candles[:-1]

    if len(closed) < (
        SENKOU_B_N + 3
    ):
        return None

    tenkan = mid_high_low(
        closed,
        TENKAN_N
    )

    kijun = mid_high_low(
        closed,
        KIJUN_N
    )

    span_b = mid_high_low(
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

    price = closed[-1]["c"]

    cloud_top = max(
        span_a,
        span_b
    )

    cloud_bottom = min(
        span_a,
        span_b
    )

    prev_tenkan = mid_high_low(
        closed[:-1],
        TENKAN_N
    )

    prev_kijun = mid_high_low(
        closed[:-1],
        KIJUN_N
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
        "top": cloud_top,
        "bottom": cloud_bottom,
        "bull_cross": bullish_cross,
        "bear_cross": bearish_cross,
        "last": closed[-1],
        "prev": closed[-2]
    }


# ============================================================
# SIGNAL ENGINE
# ============================================================

def signal_for(
    symbol,
    candles
):

    if len(candles) < 60:

        return {
            "symbol": symbol,
            "status": "insufficient",
            "kline_ok": False
        }

    x = ichimoku(candles)

    if not x:

        return {
            "symbol": symbol,
            "status": "insufficient",
            "kline_ok": True
        }

    price = x["price"]
    tenkan = x["tenkan"]
    kijun = x["kijun"]

    top = x["top"]
    bottom = x["bottom"]

    candle = x["last"]

    bullish_cloud = (
        x["span_a"] > x["span_b"]
    )

    bearish_cloud = (
        x["span_a"] < x["span_b"]
    )

    above_cloud = (
        price > top
    )

    below_cloud = (
        price < bottom
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

    bull_core = (
        int(above_cloud)
        + int(tenkan > kijun)
        + int(bullish_cloud)
    )

    bear_core = (
        int(below_cloud)
        + int(tenkan < kijun)
        + int(bearish_cloud)
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

        if x["bull_cross"]:
            score += 1.5

        if candle["c"] > candle["o"]:
            score += 0.5

        if (
            x["prev"]["c"]
            < x["prev"]["o"]
            and candle["c"]
            > candle["o"]
        ):
            score += 0.25

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

        if x["bear_cross"]:
            score += 1.5

        if candle["c"] < candle["o"]:
            score += 0.5

        if (
            x["prev"]["c"]
            > x["prev"]["o"]
            and candle["c"]
            < candle["o"]
        ):
            score += 0.25

    else:

        return {
            "symbol": symbol,
            "status": "weak_core",
            "kline_ok": True
        }

    # ========================================================
    # KIJUN DISTANCE
    # ========================================================

    distance_kijun = (
        abs(price - kijun)
        / price
        if price
        else 999
    )

    if (
        distance_kijun
        > MAX_KIJUN_DISTANCE
        and not (
            x["bull_cross"]
            or x["bear_cross"]
        )
    ):

        return {
            "symbol": symbol,
            "status": "too_far_kijun",
            "kline_ok": True
        }

    # ========================================================
    # SCORE FILTER
    # ========================================================

    if score < MIN_SCORE:

        return {
            "symbol": symbol,
            "status": "low_score",
            "kline_ok": True
        }

    # ========================================================
    # CANDLE CONFIRMATION BONUS
    # اجباری نیست
    # ========================================================

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
        "cloud_top": top,
        "cloud_bottom": bottom,
        "distance_kijun": distance_kijun
    }


# ============================================================
# SINGLE SCAN
# ============================================================

def scan_one(symbol):

    try:

        candles = get_klines(
            symbol
        )

        return signal_for(
            symbol,
            candles
        )

    except Exception as e:

        return {
            "symbol": symbol,
            "status": "error",
            "error": str(e)[:160],
            "kline_ok": False
        }


# ============================================================
# FAST MARKET SCAN
# ============================================================

def scan_market(symbols):

    started = time.perf_counter()

    stats = {
        "submitted": len(symbols),
        "completed": 0,
        "signal": 0,
        "inside_cloud": 0,
        "weak_core": 0,
        "low_score": 0,
        "too_far_kijun": 0,
        "insufficient": 0,
        "error": 0,
        "kline_ok": 0
    }

    signals = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                scan_one,
                symbol
            )
            for symbol in symbols
        ]

        for future in as_completed(
            futures
        ):

            result = future.result()

            stats["completed"] += 1

            if result.get(
                "kline_ok"
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

    elapsed = (
        time.perf_counter()
        - started
    )

    signals.sort(
        key=lambda x: x.get(
            "score",
            0
        ),
        reverse=True
    )

    return (
        signals,
        stats,
        elapsed
    )


# ============================================================
# BALANCE
# ============================================================

def get_balance():

    try:

        data = private_get(
            "balance"
        )

        for item in data:

            if (
                str(
                    item.get(
                        "asset",
                        ""
                    )
                ).upper()
                == "USDT"
            ):

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

    except Exception as e:

        log(
            f"Balance error: {e}"
        )

    return 0.0


# ============================================================
# POSITIONS
# ============================================================

def get_positions():

    data = private_get(
        "positionRisk"
    )

    positions = []

    for p in data:

        try:

            amount = float(
                p.get(
                    "positionAmt",
                    0
                )
                or 0
            )

            if abs(amount) > 0:

                positions.append(p)

        except Exception:
            pass

    return positions


# ============================================================
# LEVERAGE
# ============================================================

def set_leverage(symbol):

    return private_post(
        "leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE
        }
    )


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
            "quantity": fmt_num(
                quantity,
                12
            ),
            "newOrderRespType": "RESULT"
        }
    )


# ============================================================
# SL / TP
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

    params = {
        "symbol": symbol,
        "side": close_side,
        "stopLossPrice": fmt_num(
            sl,
            12
        ),
        "takeProfitPrice": fmt_num(
            tp,
            12
        )
    }

    try:

        result = private_post(
            "positionSlTp",
            params
        )

        return (
            result,
            sl,
            tp
        )

    except Exception as e:

        log(
            f"SL/TP endpoint failed "
            f"for {symbol}: {e}"
        )

        return (
            None,
            sl,
            tp
        )


# ============================================================
# ENTRY PRICE
# ============================================================

def get_entry_price(
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
# QUANTITY
# ============================================================

def make_quantity(
    symbol,
    price,
    filters
):

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

    if price <= 0:

        raise RuntimeError(
            "Invalid price"
        )

    quantity = (
        ORDER_USDT
        / price
    )

    if (
        min_notional
        and quantity * price
        < min_notional
    ):

        quantity = (
            min_notional
            / price
        )

    if min_qty:

        quantity = max(
            quantity,
            min_qty
        )

    if step:

        quantity = floor_step(
            quantity,
            step
        )

    if quantity <= 0:

        raise RuntimeError(
            "Quantity became zero"
        )

    return quantity


# ============================================================
# REAL TRADE
# ============================================================

def trade_best_signal(
    signals,
    filters
):

    if not signals:
        return None

    if BUY_LOCK:

        log(
            "BUY_LOCK=True -> "
            "No order"
        )

        return None

    # فقط یک پوزیشن باز
    try:

        positions = get_positions()

        if positions:

            log(
                f"Open positions: "
                f"{len(positions)} "
                f"-> skip new trade"
            )

            return None

    except Exception as e:

        log(
            f"Position check failed: {e}"
        )

        return None

    signal = signals[0]

    symbol = signal["symbol"]
    side = signal["side"]
    price = signal["price"]

    balance = get_balance()

    if balance <= 0:

        tg(
            "❌ ATI FUTURES\n"
            "USDT balance is zero "
            "or unavailable."
        )

        return None

    # برای جلوگیری از رد شدن سفارش به خاطر
    # نداشتن موجودی کافی
    if ORDER_USDT > balance * 0.95:

        tg(
            f"⚠️ ATI FUTURES\n"
            f"Balance: {balance:.6f} USDT\n"
            f"Order: {ORDER_USDT:.2f} USDT\n"
            f"موجودی برای سفارش کافی نیست."
        )

        return None

    quantity = make_quantity(
        symbol,
        price,
        filters
    )

    try:

        set_leverage(
            symbol
        )

        order = market_order(
            symbol,
            side,
            quantity
        )

        entry = get_entry_price(
            order,
            price
        )

        sltp_result, sl, tp = (
            place_sl_tp(
                symbol,
                side,
                entry
            )
        )

        direction = (
            "🟢 LONG / BUY"
            if side == "BUY"
            else
            "🔴 SHORT / SELL"
        )

        message = (
            "🚨 ATI FUTURES REAL TRADE\n"
            "⚡ V7.3 Ichimoku\n"
            f"📌 {symbol}\n"
            f"{direction}\n"
            f"💵 Entry: {entry:.10g}\n"
            f"📦 Qty: {quantity:.10g}\n"
            f"🎯 TP: {tp:.10g}\n"
            f"🛑 SL: {sl:.10g}\n"
            f"⭐ Score: {signal['score']:.2f}\n"
            "☁️ Ichimoku confirmed\n"
            f"🟢 LIVE: {LIVE_TRADING}"
        )

        tg(message)

        log(message)

        if sltp_result is None:

            tg(
                "⚠️ Position opened.\n"
                "SL/TP endpoint was not "
                "confirmed.\n"
                "Position should be checked."
            )

        return order

    except Exception as e:

        error_message = (
            "❌ ATI FUTURES ORDER ERROR\n"
            f"{symbol}\n"
            f"{e}"
        )

        tg(error_message)

        log(error_message)

        return None


# ============================================================
# HEARTBEAT
# ============================================================

def heartbeat(
    symbol_count,
    stats,
    elapsed,
    balance=None
):

    if balance is None:

        balance = (
            get_balance()
            if API_KEY
            else 0.0
        )

    signal_text = (
        "YES"
        if stats.get(
            "signal",
            0
        )
        else
        "NO SIGNAL"
    )

    message = (
        "💓 ATI FUTURES ALIVE\n"
        "⚡ V7.3 ICHIMOKU FAST SCANNER\n"
        f"📊 Markets: {symbol_count}\n"
        f"📡 Completed: "
        f"{stats['completed']}/"
        f"{stats['submitted']}\n"
        f"📈 Klines OK: "
        f"{stats['kline_ok']}\n"
        f"☁️ Signal: {signal_text}\n"
        f"⏱️ Scan: {elapsed:.3f}s\n"
        f"🚫 Cloud: "
        f"{stats['inside_cloud']} "
        f"| Weak: "
        f"{stats['weak_core']} "
        f"| Low: "
        f"{stats['low_score']}\n"
        f"📏 Far Kijun: "
        f"{stats['too_far_kijun']} "
        f"| Error: "
        f"{stats['error']}\n"
        f"💰 USDT: "
        f"{balance:.6f}\n"
        f"🟢 LIVE: "
        f"{LIVE_TRADING}\n"
        f"🕐 "
        f"{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
    )

    tg(message)

    log(message)


# ============================================================
# STARTUP
# ============================================================

def startup():

    log(
        "💓 ATI FUTURES V7.3 START"
    )

    log(
        "⚡ FAST ICHIMOKU SCANNER"
    )

    log(
        f"📡 TABDEAL FUTURES | "
        f"{TIMEFRAME}"
    )

    log(
        f"⚙️ LEVERAGE: "
        f"{LEVERAGE}x | "
        f"ORDER: "
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

    balance = get_balance()

    log(
        f"💰 USDT FREE: "
        f"{balance:.8f}"
    )

    tg(
        "💓 ATI FUTURES V7.3 STARTED\n"
        "⚡ Ichimoku Fast Scanner\n"
        f"📡 Tabdeal Futures {TIMEFRAME}\n"
        f"⚙️ Leverage: {LEVERAGE}x\n"
        f"💵 Order: {ORDER_USDT} USDT\n"
        f"🟢 LIVE: {LIVE_TRADING}\n"
        f"💰 USDT: {balance:.6f}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    startup()

    filters = get_symbol_filters()

    symbols = get_symbols()

    log(
        f"📊 Futures markets found: "
        f"{len(symbols)}"
    )

    if not symbols:

        raise RuntimeError(
            "No USDT futures symbols found"
        )

    while True:

        cycle_start = time.time()

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

            # ==================================================
            # SIGNAL
            # ==================================================

            if signals:

                best = signals[0]

                log(
                    f"🎯 BEST "
                    f"{best['symbol']} "
                    f"{best['side']} "
                    f"score="
                    f"{best['score']:.2f} "
                    f"price="
                    f"{best['price']:.10g}"
                )

                tg(
                    "🎯 ATI SIGNAL\n"
                    f"{best['symbol']} | "
                    f"{best['side']}\n"
                    f"💵 "
                    f"{best['price']:.10g}\n"
                    f"⭐ Score "
                    f"{best['score']:.2f}\n"
                    "☁️ Ichimoku"
                )

                if LIVE_TRADING:

                    trade_best_signal(
                        signals[
                            :MAX_NEW_TRADES
                        ],
                        filters
                    )

            else:

                log(
                    "☁️ NO SIGNAL "
                    "this cycle"
                )

        except Exception as e:

            error = (
                "❌ ATI FUTURES ERROR\n"
                f"{type(e).__name__}: "
                f"{e}"
            )

            log(error)

            tg(error)

        elapsed_cycle = (
            time.time()
            - cycle_start
        )

        sleep_for = max(
            5,
            SCAN_INTERVAL
            - elapsed_cycle
        )

        log(
            f"⏳ Next scan in "
            f"{sleep_for:.1f}s"
        )

        time.sleep(
            sleep_for
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
