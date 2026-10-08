import os
import json
import time
import math
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

import requests


# ============================================================
# ATI FUTURES V9.3
# TABDEAL FUTURES
# ICHIMOKU 9 / 26 / 52
# REAL TRADING
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

STATE_FILE = "ati_futures_state.json"

ORDER_USDT = float(os.getenv("ORDER_USDT", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

REAL_TRADING = os.getenv("REAL_TRADING", "true").lower() == "true"

TP_PCT = float(os.getenv("TP_PCT", "0.02"))
SL_PCT = float(os.getenv("SL_PCT", "0.01"))

MIN_SCORE = int(os.getenv("MIN_SCORE", "6"))
MIN_CANDLES = int(os.getenv("MIN_CANDLES", "53"))

SCAN_UNIVERSE = int(os.getenv("SCAN_UNIVERSE", "75"))

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "12"))

RECV_WINDOW = int(os.getenv("RECV_WINDOW", "5000"))

MAX_SIGNALS = int(os.getenv("MAX_SIGNALS", "1"))

# ------------------------------------------------------------
# Credentials
# ------------------------------------------------------------

def env_first(*names):
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return ""


API_KEY = env_first(
    "TABDEAL_API_KEY",
    "TABDIL_API_KEY",
    "TABDEAL_KEY",
    "TABDIL_KEY",
)

API_SECRET = env_first(
    "TABDEAL_API_SECRET",
    "TABDIL_API_SECRET",
    "TABDEAL_SECRET",
    "TABDIL_SECRET",
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


# ------------------------------------------------------------
# HTTP session
# ------------------------------------------------------------

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-FUTURES-V9.3",
        "Accept": "application/json",
    }
)


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = (
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        )

        r = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )

        return r.ok

    except Exception:
        return False


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# STATE
# ============================================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception:
        pass

    return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                state,
                f,
                ensure_ascii=False,
                indent=2,
            )
    except Exception:
        pass


# ============================================================
# PUBLIC REQUEST
# ============================================================

def public_get(path, params=None):
    url = BASE_URL + path

    r = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    if not r.ok:
        raise RuntimeError(
            f"HTTP {r.status_code}: {r.text[:250]}"
        )

    return r.json()


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(method, path, params=None):
    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDEAL/TABDIL API credentials are missing."
        )

    data = dict(params or {})

    data["timestamp"] = int(time.time() * 1000)
    data["recvWindow"] = RECV_WINDOW

    query = "&".join(
        f"{k}={data[k]}"
        for k in sorted(data)
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    data["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY,
    }

    url = BASE_URL + path

    if method.upper() == "GET":

        r = session.get(
            url,
            params=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    elif method.upper() == "POST":

        r = session.post(
            url,
            data=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    elif method.upper() == "DELETE":

        r = session.delete(
            url,
            params=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    else:
        raise RuntimeError("Unsupported HTTP method")

    if not r.ok:
        raise RuntimeError(
            f"HTTP {r.status_code}: {r.text[:500]}"
        )

    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    # This is the Futures public endpoint already proven
    # in the previous ATI versions.

    return public_get(
        "/r/fapi/v1/exchangeInfo"
    )


def get_symbols():

    data = get_exchange_info()

    result = []

    for s in data.get("symbols", []):

        symbol = s.get("symbol", "")
        status = str(s.get("status", "")).upper()

        if not symbol.endswith("USDT"):
            continue

        if status not in ("TRADING", "1", "ACTIVE"):
            continue

        result.append(s)

    return result[:SCAN_UNIVERSE]


# ============================================================
# SYMBOL FILTERS
# ============================================================

def symbol_rules(info):

    quantity_step = 0.0
    min_qty = 0.0
    max_qty = 0.0

    for f in info.get("filters", []):

        ft = f.get("filterType", "")

        if ft in ("LOT_SIZE", "MARKET_LOT_SIZE"):

            step = f.get("stepSize")

            if step:
                quantity_step = max(
                    quantity_step,
                    float(step),
                )

            if f.get("minQty"):
                min_qty = max(
                    min_qty,
                    float(f["minQty"]),
                )

            if f.get("maxQty"):
                max_qty = float(f["maxQty"])

    return quantity_step, min_qty, max_qty


def floor_step(value, step):

    if step <= 0:
        return value

    d_value = Decimal(str(value))
    d_step = Decimal(str(step))

    result = (
        d_value / d_step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * d_step

    return float(result)


def get_quantity(symbol_info, price):

    step, min_qty, max_qty = symbol_rules(
        symbol_info
    )

    # Notional:
    # 2 USDT * 3x leverage
    notional = ORDER_USDT * LEVERAGE

    raw_qty = notional / price

    qty = floor_step(
        raw_qty,
        step,
    )

    if qty < min_qty:
        qty = min_qty

    if max_qty > 0 and qty > max_qty:
        qty = max_qty

    return qty


# ============================================================
# HISTORICAL 5M DATA
# ============================================================

def normalize_kline(row):

    if not isinstance(row, list):
        return None

    if len(row) < 6:
        return None

    try:

        open_time = int(row[0])

        o = float(row[1])
        h = float(row[2])
        l = float(row[3])
        c = float(row[4])

        volume = (
            float(row[5])
            if len(row) > 5
            else 0.0
        )

        return {
            "t": open_time,
            "o": o,
            "h": h,
            "l": l,
            "c": c,
            "v": volume,
        }

    except Exception:
        return None


def fetch_historical_5m(symbol):

    # IMPORTANT:
    # Try the Futures read namespace first.
    #
    # The previous V9.2 proved:
    # /r/fapi/v1/exchangeInfo
    # /r/fapi/v1/depth
    #
    # We therefore try the matching read namespace here.

    candidates = [
        "/r/fapi/v1/klines",
        "/r/fapi/v1/kline",
        "/r/fapi/v1/candles",
    ]

    for path in candidates:

        try:

            data = public_get(
                path,
                {
                    "symbol": symbol,
                    "interval": "5m",
                    "limit": 100,
                },
            )

            if not isinstance(data, list):
                continue

            candles = []

            for row in data:

                k = normalize_kline(row)

                if k:
                    candles.append(k)

            if len(candles) >= MIN_CANDLES:

                candles.sort(
                    key=lambda x: x["t"]
                )

                # Do not use the currently-forming candle.
                now_ms = int(time.time() * 1000)

                closed = [
                    x for x in candles
                    if x["t"] + 300000 <= now_ms
                ]

                if len(closed) >= MIN_CANDLES:

                    return closed[-100:]

        except Exception:
            continue

    return []


# ============================================================
# DEPTH FALLBACK
# ============================================================

def fetch_depth(symbol):

    data = public_get(
        "/r/fapi/v1/depth",
        {
            "symbol": symbol,
            "limit": 5,
        },
    )

    bids = data.get("bids", [])
    asks = data.get("asks", [])

    if not bids or not asks:
        raise RuntimeError("Empty order book")

    bid = float(bids[0][0])
    ask = float(asks[0][0])

    return (bid + ask) / 2.0


# ============================================================
# PERSISTENT CANDLE FALLBACK
# ============================================================

def build_fallback_candle(
    state,
    symbol,
    price,
):

    now_ms = int(time.time() * 1000)

    bucket = (
        now_ms // 300000
    ) * 300000

    old = state.get(symbol, [])

    if not isinstance(old, list):
        old = []

    if old and old[-1].get("t") == bucket:

        k = old[-1]

        k["h"] = max(
            float(k["h"]),
            price,
        )

        k["l"] = min(
            float(k["l"]),
            price,
        )

        k["c"] = price

    else:

        old.append(
            {
                "t": bucket,
                "o": price,
                "h": price,
                "l": price,
                "c": price,
                "v": 0,
            }
        )

    old = old[-120:]

    state[symbol] = old

    return old


# ============================================================
# ICHIMOKU
# ============================================================

def ichimoku(candles):

    closes = [
        float(x["c"])
        for x in candles
    ]

    highs = [
        float(x["h"])
        for x in candles
    ]

    lows = [
        float(x["l"])
        for x in candles
    ]

    if len(closes) < 53:
        return None

    def mid(length, index=-1):

        h = highs[index - length + 1:index + 1]
        l = lows[index - length + 1:index + 1]

        if len(h) < length:
            return None

        return (
            max(h) + min(l)
        ) / 2.0

    i = len(closes) - 1

    tenkan = mid(9, i)
    kijun = mid(26, i)

    tenkan_prev = mid(9, i - 1)
    kijun_prev = mid(26, i - 1)

    high52 = max(
        highs[i - 51:i + 1]
    )

    low52 = min(
        lows[i - 51:i + 1]
    )

    span_a = (
        tenkan + kijun
    ) / 2.0

    span_b = (
        high52 + low52
    ) / 2.0

    price = closes[i]

    cloud_top = max(
        span_a,
        span_b,
    )

    cloud_bottom = min(
        span_a,
        span_b,
    )

    # Momentum over 3 candles
    momentum_up = (
        closes[i] > closes[i - 3]
    )

    momentum_down = (
        closes[i] < closes[i - 3]
    )

    score_buy = 0
    score_sell = 0

    buy_reasons = []
    sell_reasons = []

    # Price vs cloud
    if price > cloud_top:
        score_buy += 2
        buy_reasons.append(
            "PRICE_ABOVE_CLOUD"
        )

    if price < cloud_bottom:
        score_sell += 2
        sell_reasons.append(
            "PRICE_BELOW_CLOUD"
        )

    # Tenkan / Kijun
    if tenkan > kijun:
        score_buy += 2
        buy_reasons.append(
            "TENKAN_GT_KIJUN"
        )

    if tenkan < kijun:
        score_sell += 2
        sell_reasons.append(
            "TENKAN_LT_KIJUN"
        )

    # Cloud direction
    if span_a > span_b:
        score_buy += 1
        buy_reasons.append(
            "BULLISH_CLOUD"
        )

    if span_a < span_b:
        score_sell += 1
        sell_reasons.append(
            "BEARISH_CLOUD"
        )

    # Momentum
    if momentum_up:
        score_buy += 1
        buy_reasons.append(
            "MOMENTUM_UP"
        )

    if momentum_down:
        score_sell += 1
        sell_reasons.append(
            "MOMENTUM_DOWN"
        )

    # Kijun slope
    if (
        kijun_prev is not None
        and kijun > kijun_prev
    ):
        score_buy += 1
        buy_reasons.append(
            "KIJUN_RISING"
        )

    if (
        kijun_prev is not None
        and kijun < kijun_prev
    ):
        score_sell += 1
        sell_reasons.append(
            "KIJUN_FALLING"
        )

    signal = None
    score = 0
    reasons = []

    if (
        score_buy >= MIN_SCORE
        and score_buy > score_sell
    ):
        signal = "BUY"
        score = score_buy
        reasons = buy_reasons

    elif (
        score_sell >= MIN_SCORE
        and score_sell > score_buy
    ):
        signal = "SELL"
        score = score_sell
        reasons = sell_reasons

    return {
        "signal": signal,
        "score": score,
        "buy_score": score_buy,
        "sell_score": score_sell,
        "price": price,
        "tenkan": tenkan,
        "kijun": kijun,
        "span_a": span_a,
        "span_b": span_b,
        "reasons": reasons,
    }


# ============================================================
# AUTH TEST
# ============================================================

def test_account():

    if not API_KEY or not API_SECRET:
        return {
            "ok": False,
            "message": "API credentials missing",
        }

    paths = [
        "/fapi/v1/account",
        "/api/v1/account",
    ]

    for path in paths:

        try:

            data = signed_request(
                "GET",
                path,
                {},
            )

            return {
                "ok": True,
                "data": data,
            }

        except Exception:
            continue

    return {
        "ok": False,
        "message": "Futures account authentication failed",
    }


# ============================================================
# LEVERAGE
# ============================================================

def set_leverage(symbol):

    paths = [
        "/fapi/v1/leverage",
        "/api/v1/leverage",
    ]

    for path in paths:

        try:

            return signed_request(
                "POST",
                path,
                {
                    "symbol": symbol,
                    "leverage": LEVERAGE,
                },
            )

        except Exception:
            continue

    raise RuntimeError(
        "Unable to set Futures leverage"
    )


# ============================================================
# MARKET ORDER
# ============================================================

def place_market_order(
    symbol,
    side,
    quantity,
):

    paths = [
        "/fapi/v1/order",
        "/api/v1/order",
    ]

    for path in paths:

        try:

            return signed_request(
                "POST",
                path,
                {
                    "symbol": symbol,
                    "side": side,
                    "type": "MARKET",
                    "quantity": quantity,
                },
            )

        except Exception as exc:

            last_error = exc

    raise RuntimeError(
        f"Market order failed: {last_error}"
    )


# ============================================================
# PROTECTION ORDERS
# ============================================================

def place_protection(
    symbol,
    side,
    stop_price,
):

    close_side = (
        "SELL"
        if side == "BUY"
        else "BUY"
    )

    paths = [
        "/fapi/v1/order",
        "/api/v1/order",
    ]

    params = {
        "symbol": symbol,
        "side": close_side,
        "type": "STOP_MARKET",
        "stopPrice": stop_price,
        "closePosition": "true",
    }

    for path in paths:

        try:

            return signed_request(
                "POST",
                path,
                params,
            )

        except Exception as exc:

            last_error = exc

    raise RuntimeError(
        f"Protection order failed: {last_error}"
    )


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def signal_message(
    symbol,
    analysis,
    entry,
):

    side = analysis["signal"]

    if side == "BUY":

        tp = entry * (1 + TP_PCT)
        sl = entry * (1 - SL_PCT)

    else:

        tp = entry * (1 - TP_PCT)
        sl = entry * (1 + SL_PCT)

    return (
        "🔥 ATI FUTURES SIGNAL V9.3\n\n"
        f"💰 {symbol}\n"
        f"📌 {side}\n"
        f"📊 SCORE: {analysis['score']}\n"
        f"💵 ENTRY: {entry:.10g}\n"
        f"🎯 TP: {tp:.10g}\n"
        f"🛑 SL: {sl:.10g}\n\n"
        "☁️ ICHIMOKU 9 / 26 / 52\n"
        f"• Tenkan: {analysis['tenkan']:.10g}\n"
        f"• Kijun: {analysis['kijun']:.10g}\n"
        f"• Cloud A: {analysis['span_a']:.10g}\n"
        f"• Cloud B: {analysis['span_b']:.10g}\n\n"
        "🧠 "
        + ", ".join(analysis["reasons"])
    )


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    state = load_state()

    errors = 0
    historical_ok = 0
    fallback_ok = 0

    signals = []

    print("")
    print("💓 ATI FUTURES V9.3")
    print("")
    print("⚡ REAL 5M DATA + PERSISTENT FALLBACK")
    print("☁️ ICHIMOKU 9 / 26 / 52")
    print("")

    # --------------------------------------------------------
    # Exchange information
    # --------------------------------------------------------

    try:

        symbols_info = get_symbols()

    except Exception as exc:

        msg = (
            "❌ ATI FUTURES ERROR\n\n"
            f"{exc}"
        )

        print(msg)
        telegram(msg)
        return

    print(
        f"📊 Markets: {len(symbols_info)}"
    )

    # --------------------------------------------------------
    # Account
    # --------------------------------------------------------

    account = test_account()

    if account["ok"]:

        print("🔐 FUTURES AUTH: OK")

    else:

        print(
            "⚠️ FUTURES AUTH: "
            + account["message"]
        )

    # --------------------------------------------------------
    # Scan
    # --------------------------------------------------------

    for info in symbols_info:

        symbol = info.get("symbol")

        if not symbol:
            continue

        try:

            candles = fetch_historical_5m(
                symbol
            )

            if len(candles) >= MIN_CANDLES:

                historical_ok += 1

                # Save official historical data
                state[symbol] = candles[-120:]

            else:

                # Fallback to persistent state
                price = fetch_depth(symbol)

                candles = build_fallback_candle(
                    state,
                    symbol,
                    price,
                )

                fallback_ok += 1

        except Exception:

            errors += 1
            continue

        # ----------------------------------------------------
        # Only closed candles
        # ----------------------------------------------------

        if len(candles) < MIN_CANDLES:
            continue

        try:

            analysis = ichimoku(
                candles
            )

        except Exception:

            errors += 1
            continue

        if not analysis:
            continue

        signal = analysis["signal"]

        if not signal:
            continue

        entry = analysis["price"]

        signals.append(
            {
                "symbol": symbol,
                "signal": signal,
                "score": analysis["score"],
                "entry": entry,
                "analysis": analysis,
                "info": info,
            }
        )

        # Stop after enough candidates
        if len(signals) >= MAX_SIGNALS:
            break

    # --------------------------------------------------------
    # Save state
    # --------------------------------------------------------

    save_state(state)

    elapsed = time.time() - started

    print(
        f"📈 Historical 5M OK: {historical_ok}"
    )

    print(
        f"💾 Persistent fallback: {fallback_ok}"
    )

    print(
        f"🔥 Signals: {len(signals)}"
    )

    print(
        f"❌ Errors: {errors}"
    )

    print(
        f"⏱️ Scan: {elapsed:.2f}s"
    )

    # --------------------------------------------------------
    # Signal execution
    # --------------------------------------------------------

    if not signals:

        msg = (
            "💓 ATI FUTURES V9.3\n\n"
            "☁️ ICHIMOKU 9 / 26 / 52\n\n"
            f"📊 Markets: {len(symbols_info)}\n"
            f"📈 Historical 5M OK: {historical_ok}\n"
            f"💾 Fallback: {fallback_ok}\n"
            f"🔥 Signals: 0\n"
            f"❌ Errors: {errors}\n"
            f"⏱️ Scan: {elapsed:.2f}s\n\n"
            "☁️ NO SIGNAL THIS CYCLE\n\n"
            f"💵 ORDER: {ORDER_USDT} USDT\n"
            f"⚡ LEVERAGE: {LEVERAGE}x\n"
            f"🔒 REAL TRADING: {REAL_TRADING}\n"
            f"🕐 {utc_now()}"
        )

        print("")
        print(msg)
        telegram(msg)
        return

    # --------------------------------------------------------
    # Execute best signal
    # --------------------------------------------------------

    best = sorted(
        signals,
        key=lambda x: x["score"],
        reverse=True,
    )[0]

    symbol = best["symbol"]
    side = best["signal"]
    entry = best["entry"]
    info = best["info"]
    analysis = best["analysis"]

    qty = get_quantity(
        info,
        entry,
    )

    print("")
    print(
        f"🔥 BEST SIGNAL: {symbol} {side}"
    )

    print(
        f"📊 SCORE: {analysis['score']}"
    )

    print(
        f"💵 ENTRY: {entry}"
    )

    print(
        f"📦 QTY: {qty}"
    )

    # --------------------------------------------------------
    # Alert first
    # --------------------------------------------------------

    telegram(
        signal_message(
            symbol,
            analysis,
            entry,
        )
    )

    if not REAL_TRADING:

        print(
            "🔒 REAL TRADING DISABLED"
        )

        return

    if not API_KEY or not API_SECRET:

        error_msg = (
            "❌ SIGNAL FOUND BUT TRADE BLOCKED\n\n"
            f"{symbol} {side}\n"
            "🔐 Futures API credentials missing."
        )

        print(error_msg)
        telegram(error_msg)
        return

    # --------------------------------------------------------
    # Set leverage
    # --------------------------------------------------------

    try:

        set_leverage(symbol)

        print(
            f"⚡ LEVERAGE SET: {LEVERAGE}x"
        )

    except Exception as exc:

        msg = (
            "❌ LEVERAGE ERROR\n\n"
            f"{symbol}\n"
            f"{exc}"
        )

        print(msg)
        telegram(msg)
        return

    # --------------------------------------------------------
    # Market order
    # --------------------------------------------------------

    try:

        order = place_market_order(
            symbol,
            side,
            qty,
        )

        print("")
        print("✅ REAL FUTURES ORDER SENT")
        print(order)

    except Exception as exc:

        msg = (
            "❌ REAL FUTURES ORDER FAILED\n\n"
            f"💰 {symbol}\n"
            f"📌 {side}\n"
            f"📦 QTY: {qty}\n\n"
            f"{exc}"
        )

        print(msg)
        telegram(msg)
        return

    # --------------------------------------------------------
    # TP / SL
    # --------------------------------------------------------

    if side == "BUY":

        tp = entry * (1 + TP_PCT)
        sl = entry * (1 - SL_PCT)

    else:

        tp = entry * (1 - TP_PCT)
        sl = entry * (1 + SL_PCT)

    protection_errors = []

    try:

        place_protection(
            symbol,
            side,
            sl,
        )

        print(
            f"🛑 SL ORDER SENT: {sl}"
        )

    except Exception as exc:

        protection_errors.append(
            f"SL: {exc}"
        )

    try:

        # Take profit uses TAKE_PROFIT_MARKET
        close_side = (
            "SELL"
            if side == "BUY"
            else "BUY"
        )

        tp_paths = [
            "/fapi/v1/order",
            "/api/v1/order",
        ]

        sent = False

        for path in tp_paths:

            try:

                signed_request(
                    "POST",
                    path,
                    {
                        "symbol": symbol,
                        "side": close_side,
                        "type": "TAKE_PROFIT_MARKET",
                        "stopPrice": tp,
                        "closePosition": "true",
                    },
                )

                sent = True
                break

            except Exception:
                continue

        if not sent:
            raise RuntimeError(
                "TP order was rejected"
            )

        print(
            f"🎯 TP ORDER SENT: {tp}"
        )

    except Exception as exc:

        protection_errors.append(
            f"TP: {exc}"
        )

    # --------------------------------------------------------
    # Final Telegram
    # --------------------------------------------------------

    final_msg = (
        "🚀 ATI FUTURES V9.3 — REAL TRADE\n\n"
        f"💰 {symbol}\n"
        f"📌 {side}\n"
        f"📊 SCORE: {analysis['score']}\n"
        f"💵 ENTRY: {entry:.10g}\n"
        f"📦 QTY: {qty}\n"
        f"⚡ LEVERAGE: {LEVERAGE}x\n\n"
        f"🎯 TP: {tp:.10g}\n"
        f"🛑 SL: {sl:.10g}\n\n"
        "☁️ ICHIMOKU 9 / 26 / 52\n"
        "✅ MARKET ORDER SENT\n"
    )

    if protection_errors:

        final_msg += (
            "\n⚠️ PROTECTION WARNING:\n"
            + "\n".join(protection_errors)
        )

    else:

        final_msg += (
            "✅ TP/SL ORDERS SENT"
        )

    telegram(final_msg)

    print("")
    print(final_msg)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:

        error = (
            "❌ ATI FUTURES V9.3 CRITICAL ERROR\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            f"🕐 {utc_now()}"
        )

        print(error)
        telegram(error)
        raise
