import os
import json
import time
import math
import hmac
import hashlib
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# ATI FUTURES V10
# REAL FUTURES + ICHIMOKU 9/26/52
# NO EMA
# ============================================================

BASE_URL = os.getenv("BASE_URL", "https://api1.tabdeal.org").rstrip("/")

ORDER_USDT = float(os.getenv("ORDER_USDT", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

REAL_TRADING = os.getenv("REAL_TRADING", "false").lower() == "true"

TP_PCT = float(os.getenv("TP_PCT", "0.02"))
SL_PCT = float(os.getenv("SL_PCT", "0.01"))

SCAN_UNIVERSE = int(os.getenv("SCAN_UNIVERSE", "75"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "6"))

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "8"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "20"))
RECV_WINDOW = int(os.getenv("RECV_WINDOW", "5000"))

STATE_FILE = "ati_futures_state.json"

API_KEY = (
    os.getenv("TABDEAL_API_KEY")
    or os.getenv("TABDIL_API_KEY")
    or os.getenv("TABDEAL_KEY")
    or os.getenv("TABDIL_KEY")
    or ""
)

API_SECRET = (
    os.getenv("TABDEAL_API_SECRET")
    or os.getenv("TABDIL_API_SECRET")
    or os.getenv("TABDEAL_SECRET")
    or os.getenv("TABDIL_SECRET")
    or ""
)

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

session = requests.Session()


# ============================================================
# TELEGRAM
# ============================================================

def telegram(text):
    if not TG_TOKEN or not TG_CHAT_ID:
        return

    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(
            url,
            json={
                "chat_id": TG_CHAT_ID,
                "text": text,
            },
            timeout=10,
        )
    except Exception:
        pass


# ============================================================
# HTTP
# ============================================================

def public_get(path, params=None):
    url = BASE_URL + path

    r = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    r.raise_for_status()
    return r.json()


def signed_request(method, path, params=None):
    if not API_KEY or not API_SECRET:
        raise RuntimeError("API KEY/SECRET missing")

    data = dict(params or {})

    data["timestamp"] = int(time.time() * 1000)
    data["recvWindow"] = RECV_WINDOW

    query = "&".join(
        f"{k}={data[k]}"
        for k in data
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()

    data["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = BASE_URL + path

    if method.upper() == "GET":
        r = session.get(
            url,
            params=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    else:
        r = session.post(
            url,
            data=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    if r.status_code >= 400:
        raise RuntimeError(
            f"HTTP {r.status_code}: {r.text[:500]}"
        )

    return r.json()


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_markets():

    data = public_get(
        "/r/fapi/v1/exchangeInfo"
    )

    markets = []

    for s in data.get("symbols", []):

        symbol = str(
            s.get("symbol", "")
        ).upper()

        status = str(
            s.get("status", "")
        ).upper()

        quote = str(
            s.get("quoteAsset", "")
        ).upper()

        if (
            symbol
            and status in ("TRADING", "ACTIVE", "")
            and quote == "USDT"
        ):
            markets.append(s)

    markets.sort(
        key=lambda x: x.get("symbol", "")
    )

    return markets[:SCAN_UNIVERSE]


# ============================================================
# SYMBOL RULES
# ============================================================

def symbol_rules(info):

    quantity_step = 1.0
    min_qty = 0.0
    tick_size = 0.0

    for f in info.get("filters", []):

        typ = str(
            f.get("filterType", "")
        )

        if typ in ("LOT_SIZE", "MARKET_LOT_SIZE"):

            step = f.get("stepSize")

            if step:
                quantity_step = float(step)

            mq = f.get("minQty")

            if mq:
                min_qty = float(mq)

        if typ == "PRICE_FILTER":

            ts = f.get("tickSize")

            if ts:
                tick_size = float(ts)

    return quantity_step, min_qty, tick_size


def floor_step(value, step):

    if step <= 0:
        return value

    return math.floor(
        value / step
    ) * step


def round_tick(value, tick):

    if tick <= 0:
        return value

    return round(
        math.floor(value / tick) * tick,
        12,
    )


# ============================================================
# PRICE
# ============================================================

def fetch_depth(symbol):

    data = public_get(
        "/r/fapi/v1/depth",
        {
            "symbol": symbol,
            "limit": 20,
        },
    )

    bids = data.get("bids", [])
    asks = data.get("asks", [])

    if not bids or not asks:
        return None

    bid = float(bids[0][0])
    ask = float(asks[0][0])

    if bid <= 0 or ask <= 0:
        return None

    mid = (bid + ask) / 2.0

    return {
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "price": mid,
        "time": int(time.time() * 1000),
    }


# ============================================================
# OPTIONAL REAL TRADES
#
# If the Futures public trade endpoint is available on the
# current Tabdeal deployment, use it.
#
# If unavailable, we safely fall back to depth.
# ============================================================

def fetch_recent_trades(symbol):

    try:

        data = public_get(
            "/r/fapi/v1/trades",
            {
                "symbol": symbol,
                "limit": 1000,
            },
        )

        if not isinstance(data, list):
            return []

        trades = []

        for x in data:

            price = x.get("price")
            qty = x.get("qty")

            if price is None:
                price = x.get("p")

            if qty is None:
                qty = x.get("q")

            tm = x.get("time")

            if tm is None:
                tm = x.get("T")

            if (
                price is None
                or qty is None
                or tm is None
            ):
                continue

            trades.append(
                {
                    "price": float(price),
                    "qty": float(qty),
                    "time": int(tm),
                }
            )

        return trades

    except Exception:
        return []


# ============================================================
# 5M CANDLES FROM REAL TRADES
# ============================================================

def trades_to_5m(trades):

    if not trades:
        return []

    buckets = {}

    for t in trades:

        ts = int(t["time"])

        bucket = (
            ts // 300000
        ) * 300000

        price = float(t["price"])
        qty = float(t["qty"])

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
            }

        else:

            c = buckets[bucket]

            c["high"] = max(
                c["high"],
                price
            )

            c["low"] = min(
                c["low"],
                price
            )

            c["close"] = price

            c["volume"] += qty

    candles = [
        buckets[k]
        for k in sorted(buckets)
    ]

    # آخرین کندل هنوز ممکن است بسته نشده باشد
    now_bucket = (
        int(time.time() * 1000)
        // 300000
    ) * 300000

    candles = [
        c for c in candles
        if c["time"] < now_bucket
    ]

    return candles


# ============================================================
# STATE
# ============================================================

def load_state():

    if not os.path.exists(STATE_FILE):
        return {}

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            return json.load(f)

    except Exception:

        return {}


def save_state(state):

    tmp = STATE_FILE + ".tmp"

    with open(
        tmp,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            state,
            f,
            ensure_ascii=False,
        )

    os.replace(
        tmp,
        STATE_FILE,
    )


# ============================================================
# ICHIMOKU
# ============================================================

def ichimoku(candles):

    if len(candles) < 53:
        return None

    highs = [
        float(x["high"])
        for x in candles
    ]

    lows = [
        float(x["low"])
        for x in candles
    ]

    closes = [
        float(x["close"])
        for x in candles
    ]

    def midpoint(period, end):

        h = max(
            highs[end - period + 1:end + 1]
        )

        l = min(
            lows[end - period + 1:end + 1]
        )

        return (max(h) + min(l)) / 2.0

    i = len(candles) - 1

    tenkan = midpoint(9, i)
    kijun = midpoint(26, i)

    # Current cloud values
    span_a = (
        tenkan + kijun
    ) / 2.0

    span_b = midpoint(52, i)

    price = closes[i]

    cloud_top = max(
        span_a,
        span_b
    )

    cloud_bottom = min(
        span_a,
        span_b
    )

    # Previous values
    prev_tenkan = midpoint(9, i - 1)
    prev_kijun = midpoint(26, i - 1)

    prev_span_a = (
        prev_tenkan + prev_kijun
    ) / 2.0

    prev_span_b = midpoint(52, i - 1)

    score_buy = 0
    score_sell = 0

    reasons_buy = []
    reasons_sell = []

    # PRICE VS CLOUD
    if price > cloud_top:
        score_buy += 2
        reasons_buy.append(
            "PRICE_ABOVE_CLOUD"
        )

    if price < cloud_bottom:
        score_sell += 2
        reasons_sell.append(
            "PRICE_BELOW_CLOUD"
        )

    # TENKAN / KIJUN
    if tenkan > kijun:
        score_buy += 2
        reasons_buy.append(
            "TENKAN_GT_KIJUN"
        )

    if tenkan < kijun:
        score_sell += 2
        reasons_sell.append(
            "TENKAN_LT_KIJUN"
        )

    # CLOUD DIRECTION
    if span_a > span_b:
        score_buy += 1
        reasons_buy.append(
            "BULLISH_CLOUD"
        )

    if span_a < span_b:
        score_sell += 1
        reasons_sell.append(
            "BEARISH_CLOUD"
        )

    # MOMENTUM
    if closes[i] > closes[i - 1]:
        score_buy += 1
        reasons_buy.append(
            "MOMENTUM_UP"
        )

    if closes[i] < closes[i - 1]:
        score_sell += 1
        reasons_sell.append(
            "MOMENTUM_DOWN"
        )

    # KIJUN DIRECTION
    if kijun > prev_kijun:
        score_buy += 1
        reasons_buy.append(
            "KIJUN_RISING"
        )

    if kijun < prev_kijun:
        score_sell += 1
        reasons_sell.append(
            "KIJUN_FALLING"
        )

    if (
        score_buy >= MIN_SCORE
        and score_buy > score_sell
    ):

        signal = "BUY"
        score = score_buy
        reasons = reasons_buy

    elif (
        score_sell >= MIN_SCORE
        and score_sell > score_buy
    ):

        signal = "SELL"
        score = score_sell
        reasons = reasons_sell

    else:

        signal = None
        score = max(
            score_buy,
            score_sell,
        )
        reasons = []

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
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom,
        "reasons": reasons,
    }


# ============================================================
# SCAN ONE SYMBOL
# ============================================================

def scan_symbol(info, state):

    symbol = str(
        info.get("symbol", "")
    ).upper()

    if not symbol:
        return None

    trades = fetch_recent_trades(
        symbol
    )

    candles = trades_to_5m(
        trades
    )

    # If public trade endpoint isn't
    # available, preserve previous candles
    # and add current real depth snapshot.
    if len(candles) < 53:

        old = state.get(
            symbol,
            []
        )

        if old:
            candles = old[-120:]

        depth = fetch_depth(symbol)

        if depth:

            bucket = (
                depth["time"]
                // 300000
            ) * 300000

            p = depth["price"]

            if candles:

                last = candles[-1]

                if last["time"] == bucket:

                    last["high"] = max(
                        last["high"],
                        p
                    )

                    last["low"] = min(
                        last["low"],
                        p
                    )

                    last["close"] = p

                elif last["time"] < bucket:

                    candles.append(
                        {
                            "time": bucket,
                            "open": p,
                            "high": p,
                            "low": p,
                            "close": p,
                            "volume": 0,
                        }
                    )

            else:

                candles = [
                    {
                        "time": bucket,
                        "open": p,
                        "high": p,
                        "low": p,
                        "close": p,
                        "volume": 0,
                    }
                ]

    candles = candles[-120:]

    state[symbol] = candles

    if len(candles) < 53:

        return {
            "symbol": symbol,
            "ready": False,
            "candles": len(candles),
        }

    result = ichimoku(
        candles
    )

    if not result:
        return None

    result["symbol"] = symbol
    result["ready"] = True
    result["candles"] = len(candles)

    return result


# ============================================================
# REAL ORDER
# ============================================================

def place_real_trade(signal):

    symbol = signal["symbol"]
    side = signal["signal"]
    price = float(signal["price"])

    info = signal["info"]

    step, min_qty, tick = symbol_rules(
        info
    )

    # Futures notional with leverage
    quantity = (
        ORDER_USDT * LEVERAGE
    ) / price

    quantity = floor_step(
        quantity,
        step
    )

    if quantity <= 0:
        raise RuntimeError(
            "Calculated quantity is zero"
        )

    if quantity < min_qty:
        raise RuntimeError(
            f"Quantity {quantity} < minQty {min_qty}"
        )

    quantity_text = (
        f"{quantity:.12f}"
        .rstrip("0")
        .rstrip(".")
    )

    # Set leverage first
    signed_request(
        "POST",
        "/fapi/v1/leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE,
        },
    )

    order = signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity_text,
        },
    )

    time.sleep(1)

    # Find position
    positions = signed_request(
        "GET",
        "/fapi/v1/position",
        {
            "symbol": symbol,
        },
    )

    position_id = None
    entry_price = price

    if isinstance(positions, list):

        for p in positions:

            try:

                amt = float(
                    p.get("positionAmt", 0)
                )

            except Exception:

                amt = 0

            if abs(amt) > 0:

                position_id = p.get(
                    "positionId"
                )

                try:
                    entry_price = float(
                        p.get(
                            "entryPrice",
                            price
                        )
                    )
                except Exception:
                    pass

                break

    elif isinstance(positions, dict):

        try:
            position_id = positions.get(
                "positionId"
            )

            entry_price = float(
                positions.get(
                    "entryPrice",
                    price
                )
            )

        except Exception:
            pass

    # Protection
    if position_id is not None:

        if side == "BUY":

            sl = entry_price * (
                1 - SL_PCT
            )

            tp = entry_price * (
                1 + TP_PCT
            )

        else:

            sl = entry_price * (
                1 + SL_PCT
            )

            tp = entry_price * (
                1 - TP_PCT
            )

        sl = round_tick(
            sl,
            tick
        )

        tp = round_tick(
            tp,
            tick
        )

        signed_request(
            "POST",
            "/fapi/v1/positionSlTp",
            {
                "positionId": position_id,
                "symbol": symbol,
                "slPrice": str(sl),
                "tpPrice": str(tp),
            },
        )

    return order


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    print(
        "💓 ATI FUTURES V10"
    )

    print(
        "⚡ REAL FUTURES + ICHIMOKU"
    )

    print(
        "☁️ ICHIMOKU 9 / 26 / 52"
    )

    print(
        f"💵 ORDER: {ORDER_USDT} USDT"
    )

    print(
        f"⚡ LEVERAGE: {LEVERAGE}x"
    )

    print(
        f"🔒 REAL TRADING: {REAL_TRADING}"
    )

    state = load_state()

    try:

        markets = get_markets()

    except Exception as e:

        msg = (
            "❌ ATI FUTURES V10 ERROR\n\n"
            f"{e}"
        )

        print(msg)
        telegram(msg)
        return

    print(
        f"📊 Markets: {len(markets)}"
    )

    results = []

    errors = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                scan_symbol,
                info,
                state
            ): info
            for info in markets
        }

        for future in as_completed(
            futures
        ):

            info = futures[future]

            try:

                result = future.result()

                if result:
                    result["info"] = info
                    results.append(result)

            except Exception as e:

                errors += 1

                print(
                    f"ERROR {info.get('symbol')}: {e}"
                )

    save_state(state)

    ready = [
        r for r in results
        if r.get("ready")
    ]

    signals = [
        r for r in ready
        if r.get("signal")
    ]

    elapsed = (
        time.time() - started
    )

    max_candles = max(
        [
            r.get("candles", 0)
            for r in results
        ] or [0]
    )

    print(
        f"📈 Ready: {len(ready)}"
    )

    print(
        f"🔥 Signals: {len(signals)}"
    )

    print(
        f"❌ Errors: {errors}"
    )

    print(
        f"📚 Max closed candles: {max_candles}"
    )

    print(
        f"⏱️ Scan: {elapsed:.2f}s"
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    if not signals:

        msg = (
            "💓 ATI FUTURES V10\n\n"
            "☁️ NO SIGNAL THIS CYCLE\n\n"
            f"📊 Markets: {len(markets)}\n"
            f"📈 Ready: {len(ready)}\n"
            f"📚 Max candles: {max_candles}\n"
            f"❌ Errors: {errors}\n"
            f"⏱️ Scan: {elapsed:.2f}s\n\n"
            f"💵 ORDER: {ORDER_USDT} USDT\n"
            f"⚡ LEVERAGE: {LEVERAGE}x\n"
            f"🔒 REAL: {REAL_TRADING}"
        )

        print(msg)
        telegram(msg)

        return

    # Best signal first
    signals.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    best = signals[0]

    msg = (
        "🔥 ATI FUTURES V10 SIGNAL\n\n"
        f"🪙 {best['symbol']}\n"
        f"📌 {best['signal']}\n"
        f"⭐ SCORE: {best['score']}\n"
        f"💰 PRICE: {best['price']}\n\n"
        f"☁️ Tenkan: {best['tenkan']}\n"
        f"☁️ Kijun: {best['kijun']}\n"
        f"☁️ Span A: {best['span_a']}\n"
        f"☁️ Span B: {best['span_b']}\n\n"
        f"🧠 {' / '.join(best['reasons'])}\n\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"⚡ LEVERAGE: {LEVERAGE}x\n"
        f"🔒 REAL: {REAL_TRADING}"
    )

    print(msg)
    telegram(msg)

    # --------------------------------------------------------
    # REAL TRADE
    # --------------------------------------------------------

    if not REAL_TRADING:

        print(
            "🧪 TEST MODE - NO REAL ORDER"
        )

        return

    try:

        order = place_real_trade(
            best
        )

        order_msg = (
            "🚨 ATI REAL FUTURES ORDER\n\n"
            f"🪙 {best['symbol']}\n"
            f"📌 {best['signal']}\n"
            f"⭐ SCORE: {best['score']}\n"
            f"💰 ENTRY: {best['price']}\n"
            f"⚡ LEVERAGE: {LEVERAGE}x\n"
            f"💵 ORDER: {ORDER_USDT} USDT\n\n"
            f"🆔 ORDER ID: "
            f"{order.get('orderId', 'N/A')}\n\n"
            f"🛡️ TP: +{TP_PCT * 100:.2f}%\n"
            f"🛑 SL: -{SL_PCT * 100:.2f}%"
        )

        print(order_msg)
        telegram(order_msg)

    except Exception as e:

        error_msg = (
            "❌ REAL FUTURES ORDER ERROR\n\n"
            f"🪙 {best['symbol']}\n"
            f"📌 {best['signal']}\n\n"
            f"{e}"
        )

        print(error_msg)
        telegram(error_msg)


if __name__ == "__main__":
    main()
