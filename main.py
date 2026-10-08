import os
import json
import time
import math
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from tabdeal.future import Future
from tabdeal.enums import OrderSides, OrderTypes


# =========================================================
# ATI FUTURES V9 REAL
# =========================================================
#
# Futures:
#   Tabdeal official Future SDK
#
# Candle:
#   Futures aggregate trades -> 5M OHLCV
#
# Strategy:
#   Ichimoku 9 / 26 / 52
#
# Trading:
#   REAL_TRADING=true
#   MAX 1 active position
#   MAX 1 new order per cycle
#
# State:
#   ati_futures_state.json
# =========================================================


BASE_URL = "https://api1.tabdeal.org"

API_KEY = os.getenv("TABDEAL_API_KEY", "")
API_SECRET = os.getenv("TABDEAL_API_SECRET", "")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

REAL_TRADING = (
    os.getenv("REAL_TRADING", "true").lower()
    == "true"
)

SCAN_UNIVERSE = int(
    os.getenv("SCAN_UNIVERSE", "75")
)

MAX_WORKERS = int(
    os.getenv("MAX_WORKERS", "12")
)

ORDER_USDT = float(
    os.getenv("ORDER_USDT", "2")
)

LEVERAGE = int(
    os.getenv("LEVERAGE", "3")
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

STATE_FILE = "ati_futures_state.json"

REQUEST_TIMEOUT = 10

# Ichimoku
TENKAN = 9
KIJUN = 26
SENKOU_B = 52

# 5 minute
CANDLE_MS = 5 * 60 * 1000


http = requests.Session()

http.headers.update({
    "User-Agent": "ATI-FUTURES-V9-REAL",
    "Accept": "application/json",
})


# =========================================================
# OFFICIAL FUTURES CLIENT
# =========================================================

client = None

if API_KEY and API_SECRET:
    client = Future(
        API_KEY,
        API_SECRET,
        base_url=BASE_URL,
        timeout=REQUEST_TIMEOUT,
        receive_window=RECV_WINDOW,
    )


# =========================================================
# TELEGRAM
# =========================================================

def telegram_send(text):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:

        url = (
            "https://api.telegram.org/"
            f"bot{TELEGRAM_TOKEN}/sendMessage"
        )

        r = http.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
            },
            timeout=10,
        )

        return r.ok

    except Exception as e:

        print("Telegram error:", e)
        return False


# =========================================================
# PUBLIC HTTP
# =========================================================

def public_get(path, params=None):

    url = BASE_URL + path

    r = http.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    if r.status_code != 200:

        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:250]}"
        )

    return r.json()


# =========================================================
# SYMBOL HELPERS
# =========================================================

def normalize_symbol(symbol):

    symbol = str(symbol).upper()

    # Tabdeal exchangeInfo can expose:
    # BTC_USDT
    #
    # Futures SDK expects:
    # BTCUSDT

    if "_" in symbol:
        symbol = symbol.replace("_", "")

    return symbol


def display_symbol(symbol):

    symbol = normalize_symbol(symbol)

    if symbol.endswith("USDT"):

        return (
            symbol[:-4]
            + "_USDT"
        )

    return symbol


# =========================================================
# EXCHANGE INFO
# =========================================================

def get_markets():

    data = public_get(
        "/r/fapi/v1/exchangeInfo"
    )

    symbols = data.get(
        "symbols",
        []
    )

    markets = []

    for item in symbols:

        raw = item.get(
            "symbol",
            ""
        )

        symbol = normalize_symbol(raw)

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

        if status not in (
            "TRADING",
            "ENABLED",
        ):
            continue

        if quote != "USDT":
            continue

        markets.append({
            "symbol": symbol,
            "raw": raw,
            "info": item,
        })

    # unique
    seen = set()
    result = []

    for m in markets:

        if m["symbol"] in seen:
            continue

        seen.add(m["symbol"])
        result.append(m)

    return result[:SCAN_UNIVERSE]


# =========================================================
# STATE
# =========================================================

def load_state():

    if not os.path.exists(STATE_FILE):

        return {
            "candles": {},
            "last_signal": {},
            "last_order": None,
        }

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError()

        data.setdefault(
            "candles",
            {}
        )

        data.setdefault(
            "last_signal",
            {}
        )

        data.setdefault(
            "last_order",
            None
        )

        return data

    except Exception as e:

        print(
            "State load error:",
            e
        )

        return {
            "candles": {},
            "last_signal": {},
            "last_order": None,
        }


def save_state(state):

    tmp = STATE_FILE + ".tmp"

    with open(
        tmp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    os.replace(
        tmp,
        STATE_FILE
    )


# =========================================================
# BUILD 5M CANDLE FROM AGG TRADES
# =========================================================

def get_current_5m_trades(symbol):

    now = int(
        time.time() * 1000
    )

    bucket = (
        now // CANDLE_MS
    ) * CANDLE_MS

    end = bucket + CANDLE_MS - 1

    params = {
        "symbol": symbol,
        "startTime": bucket,
        "endTime": end,
        "limit": 1000,
    }

    # IMPORTANT:
    # We deliberately use the READ/Futures path that
    # corresponds to Tabdeal's Futures market API.
    data = public_get(
        "/r/fapi/v1/aggTrades",
        params,
    )

    if not isinstance(data, list):
        raise RuntimeError(
            "Invalid aggTrades response"
        )

    return bucket, data


def make_candle(
    symbol,
    bucket,
    trades
):

    if not trades:
        return None

    prices = []

    volume = 0.0

    for t in trades:

        try:

            price = float(
                t.get(
                    "p",
                    t.get(
                        "price"
                    )
                )
            )

            qty = float(
                t.get(
                    "q",
                    t.get(
                        "qty",
                        0
                    )
                )
            )

            if price <= 0:
                continue

            prices.append(price)

            volume += qty

        except Exception:
            continue

    if not prices:
        return None

    return {
        "time": bucket,
        "open": prices[0],
        "high": max(prices),
        "low": min(prices),
        "close": prices[-1],
        "volume": volume,
    }


# =========================================================
# ICHIMOKU
# =========================================================

def midpoint(candles, index, period):

    start = (
        index - period + 1
    )

    if start < 0:
        return None

    part = candles[
        start:index + 1
    ]

    highs = [
        float(x["high"])
        for x in part
    ]

    lows = [
        float(x["low"])
        for x in part
    ]

    return (
        max(highs)
        + min(lows)
    ) / 2.0


def ichimoku(candles):

    if len(candles) < SENKOU_B:

        return None

    i = len(candles) - 1

    tenkan = midpoint(
        candles,
        i,
        TENKAN
    )

    kijun = midpoint(
        candles,
        i,
        KIJUN
    )

    span_b = midpoint(
        candles,
        i,
        SENKOU_B
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

    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "span_a": span_a,
        "span_b": span_b,
    }


# =========================================================
# SIGNAL
# =========================================================

def analyze(symbol, candles):

    if len(candles) < 53:
        return None

    candles = sorted(
        candles,
        key=lambda x: x["time"]
    )

    current = ichimoku(
        candles
    )

    previous = ichimoku(
        candles[:-1]
    )

    if not current or not previous:
        return None

    last = candles[-1]
    prev = candles[-2]

    close = float(
        last["close"]
    )

    prev_close = float(
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

    buy = 0
    sell = 0

    buy_reasons = []
    sell_reasons = []

    # ---------------- BUY ----------------

    if close > cloud_top:
        buy += 2
        buy_reasons.append(
            "PRICE_ABOVE_CLOUD"
        )

    if current["tenkan"] > current["kijun"]:
        buy += 2
        buy_reasons.append(
            "TENKAN_GT_KIJUN"
        )

    if current["span_a"] > current["span_b"]:
        buy += 1
        buy_reasons.append(
            "BULLISH_CLOUD"
        )

    if close > prev_close:
        buy += 1
        buy_reasons.append(
            "MOMENTUM_UP"
        )

    if current["kijun"] > previous["kijun"]:
        buy += 1
        buy_reasons.append(
            "KIJUN_RISING"
        )

    # ---------------- SELL ----------------

    if close < cloud_bottom:
        sell += 2
        sell_reasons.append(
            "PRICE_BELOW_CLOUD"
        )

    if current["tenkan"] < current["kijun"]:
        sell += 2
        sell_reasons.append(
            "TENKAN_LT_KIJUN"
        )

    if current["span_a"] < current["span_b"]:
        sell += 1
        sell_reasons.append(
            "BEARISH_CLOUD"
        )

    if close < prev_close:
        sell += 1
        sell_reasons.append(
            "MOMENTUM_DOWN"
        )

    if current["kijun"] < previous["kijun"]:
        sell += 1
        sell_reasons.append(
            "KIJUN_FALLING"
        )

    if (
        buy >= MIN_SCORE
        and buy > sell
    ):

        return {
            "symbol": symbol,
            "signal": "BUY",
            "score": buy,
            "price": close,
            "reasons": buy_reasons,
        }

    if (
        sell >= MIN_SCORE
        and sell > buy
    ):

        return {
            "symbol": symbol,
            "signal": "SELL",
            "score": sell,
            "price": close,
            "reasons": sell_reasons,
        }

    return None


# =========================================================
# CANDLE UPDATE
# =========================================================

def update_symbol(
    market,
    state
):

    symbol = market["symbol"]

    bucket, trades = (
        get_current_5m_trades(
            symbol
        )
    )

    candle = make_candle(
        symbol,
        bucket,
        trades
    )

    if candle is None:
        raise RuntimeError(
            "No trade data"
        )

    candles = state[
        "candles"
    ].setdefault(
        symbol,
        []
    )

    # Replace same bucket
    replaced = False

    for i, old in enumerate(candles):

        if old["time"] == bucket:

            candles[i] = candle
            replaced = True
            break

    if not replaced:
        candles.append(
            candle
        )

    candles.sort(
        key=lambda x: x["time"]
    )

    # Keep enough history
    state["candles"][symbol] = (
        candles[-120:]
    )

    return (
        candle,
        len(
            state["candles"][symbol]
        )
    )


# =========================================================
# REAL ACCOUNT / POSITION
# =========================================================

def get_active_positions():

    if client is None:
        return []

    positions = client.get_positions()

    if positions is None:
        return []

    if isinstance(
        positions,
        dict
    ):

        if "positions" in positions:
            positions = positions[
                "positions"
            ]
        else:
            positions = [positions]

    active = []

    for p in positions:

        try:

            qty = float(
                p.get(
                    "positionAmt",
                    p.get(
                        "quantity",
                        0
                    )
                )
            )

            if abs(qty) > 0:
                active.append(p)

        except Exception:
            continue

    return active


# =========================================================
# SYMBOL QUANTITY
# =========================================================

def symbol_rules(market):

    info = market["info"]

    filters = info.get(
        "filters",
        []
    )

    result = {
        "step": 0.0,
        "min_qty": 0.0,
        "max_qty": 0.0,
    }

    for f in filters:

        typ = str(
            f.get(
                "filterType",
                ""
            )
        )

        if typ in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE",
        ):

            step = f.get(
                "stepSize"
            )

            minimum = f.get(
                "minQty"
            )

            maximum = f.get(
                "maxQty"
            )

            if step:
                result["step"] = float(
                    step
                )

            if minimum:
                result["min_qty"] = float(
                    minimum
                )

            if maximum:
                result["max_qty"] = float(
                    maximum
                )

    return result


def floor_step(value, step):

    if step <= 0:
        return value

    return (
        math.floor(
            value / step
        )
        * step
    )


def quantity_for_price(
    market,
    price
):

    rules = symbol_rules(
        market
    )

    raw_qty = (
        ORDER_USDT
        * LEVERAGE
        / price
    )

    qty = floor_step(
        raw_qty,
        rules["step"]
    )

    if qty < rules["min_qty"]:
        qty = rules["min_qty"]

    if (
        rules["max_qty"] > 0
        and qty > rules["max_qty"]
    ):
        qty = rules["max_qty"]

    if qty <= 0:
        raise RuntimeError(
            "Calculated quantity <= 0"
        )

    return (
        f"{qty:.12f}".rstrip("0").rstrip(".")
    )


# =========================================================
# REAL ORDER
# =========================================================

def place_real_order(
    signal,
    market
):

    if not REAL_TRADING:
        raise RuntimeError(
            "REAL_TRADING is OFF"
        )

    if client is None:
        raise RuntimeError(
            "Futures API credentials missing"
        )

    symbol = signal["symbol"]
    price = float(
        signal["price"]
    )

    side = (
        OrderSides.BUY
        if signal["signal"] == "BUY"
        else OrderSides.SELL
    )

    # Set leverage first
    leverage_result = client.change_leverage(
        symbol,
        LEVERAGE
    )

    print(
        "Leverage:",
        leverage_result
    )

    quantity = quantity_for_price(
        market,
        price
    )

    print(
        f"REAL ORDER → "
        f"{symbol} "
        f"{signal['signal']} "
        f"qty={quantity}"
    )

    order = client.new_order(
        symbol=symbol,
        side=side,
        type=OrderTypes.MARKET,
        quantity=quantity,
    )

    return {
        "order": order,
        "quantity": quantity,
    }


# =========================================================
# SET SL / TP
# =========================================================

def set_sl_tp(
    symbol,
    signal,
    order_result
):

    if client is None:
        return None

    try:

        positions = client.get_positions(
            symbol=symbol
        )

        if isinstance(
            positions,
            dict
        ):
            positions = positions.get(
                "positions",
                [positions]
            )

        position_id = None

        for p in positions or []:

            try:

                qty = float(
                    p.get(
                        "positionAmt",
                        p.get(
                            "quantity",
                            0
                        )
                    )
                )

                if abs(qty) > 0:

                    position_id = p.get(
                        "positionId"
                    )

                    break

            except Exception:
                continue

        if position_id is None:

            print(
                "No active position found "
                "for SL/TP"
            )

            return None

        entry = float(
            signal["price"]
        )

        if signal["signal"] == "BUY":

            sl = (
                entry
                * (1.0 - SL_PCT)
            )

            tp = (
                entry
                * (1.0 + TP_PCT)
            )

        else:

            sl = (
                entry
                * (1.0 + SL_PCT)
            )

            tp = (
                entry
                * (1.0 - TP_PCT)
            )

        result = client.position_sl_tp(
            position_id=int(
                position_id
            ),
            symbol=symbol,
            sl_price=str(sl),
            tp_price=str(tp),
        )

        return {
            "sl": sl,
            "tp": tp,
            "result": result,
        }

    except Exception as e:

        print(
            "SL/TP error:",
            e
        )

        return {
            "error": str(e)
        }


# =========================================================
# PROCESS MARKET
# =========================================================

def process_market(
    market,
    state
):

    try:

        candle, count = (
            update_symbol(
                market,
                state
            )
        )

        signal = analyze(
            market["symbol"],
            state["candles"][
                market["symbol"]
            ]
        )

        return {
            "ok": True,
            "symbol": market["symbol"],
            "candle": candle,
            "count": count,
            "signal": signal,
            "error": None,
        }

    except Exception as e:

        return {
            "ok": False,
            "symbol": market["symbol"],
            "candle": None,
            "count": 0,
            "signal": None,
            "error": str(e)[:200],
        }


# =========================================================
# MAIN
# =========================================================

def main():

    started = time.time()

    print(
        "💓 ATI FUTURES V9 REAL"
    )

    print(
        "⚡ AGG TRADES → 5M"
    )

    print(
        "☁️ ICHIMOKU 9 / 26 / 52"
    )

    print(
        f"🔒 REAL TRADING: "
        f"{REAL_TRADING}"
    )

    # -----------------------------------------------------
    # Credentials
    # -----------------------------------------------------

    if REAL_TRADING:

        if not API_KEY or not API_SECRET:

            text = (
                "❌ ATI FUTURES V9\n\n"
                "REAL_TRADING=true ولی "
                "TABDEAL_API_KEY / "
                "TABDEAL_API_SECRET موجود نیست."
            )

            print(text)
            telegram_send(text)
            return

    # -----------------------------------------------------
    # Markets
    # -----------------------------------------------------

    try:

        markets = get_markets()

    except Exception as e:

        text = (
            "❌ ATI FUTURES V9 ERROR\n\n"
            f"ExchangeInfo:\n{e}"
        )

        print(text)
        telegram_send(text)
        return

    # -----------------------------------------------------
    # State
    # -----------------------------------------------------

    state = load_state()

    # -----------------------------------------------------
    # Existing real positions
    # -----------------------------------------------------

    active_positions = []

    if REAL_TRADING:

        try:

            active_positions = (
                get_active_positions()
            )

        except Exception as e:

            text = (
                "❌ ATI FUTURES V9\n\n"
                "نتوانستم پوزیشن‌های باز را "
                "بررسی کنم.\n\n"
                f"{e}\n\n"
                "🚫 معامله جدید انجام نشد."
            )

            print(text)
            telegram_send(text)
            return

    # -----------------------------------------------------
    # Scan
    # -----------------------------------------------------

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        jobs = [
            executor.submit(
                process_market,
                market,
                state
            )
            for market in markets
        ]

        for job in as_completed(jobs):

            try:
                results.append(
                    job.result()
                )

            except Exception as e:

                results.append({
                    "ok": False,
                    "symbol": "?",
                    "candle": None,
                    "count": 0,
                    "signal": None,
                    "error": str(e),
                })

    ok = sum(
        1 for x in results
        if x["ok"]
    )

    errors = len(results) - ok

    ready = [
        x for x in results
        if x["ok"]
        and x["count"] >= 53
    ]

    signals = []

    for x in ready:

        if x["signal"]:

            signals.append(
                x["signal"]
            )

    signals.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    elapsed = (
        time.time()
        - started
    )

    # -----------------------------------------------------
    # Save state BEFORE order
    # -----------------------------------------------------

    save_state(state)

    # -----------------------------------------------------
    # REAL ORDER
    # -----------------------------------------------------

    order_info = None

    if signals and REAL_TRADING:

        if active_positions:

            print(
                "🔒 Existing position found."
            )

        else:

            # only ONE trade per cycle
            selected = signals[0]

            market = next(
                (
                    m for m in markets
                    if m["symbol"]
                    == selected["symbol"]
                ),
                None
            )

            if market:

                try:

                    order_info = (
                        place_real_order(
                            selected,
                            market
                        )
                    )

                    sltp = set_sl_tp(
                        selected["symbol"],
                        selected,
                        order_info
                    )

                    state[
                        "last_signal"
                    ][
                        selected["symbol"]
                    ] = {
                        "time": int(
                            time.time()
                        ),
                        "signal": selected[
                            "signal"
                        ],
                        "score": selected[
                            "score"
                        ],
                    }

                    state[
                        "last_order"
                    ] = {
                        "symbol": selected[
                            "symbol"
                        ],
                        "signal": selected[
                            "signal"
                        ],
                        "quantity": order_info[
                            "quantity"
                        ],
                        "order": order_info[
                            "order"
                        ],
                        "sltp": sltp,
                        "time": int(
                            time.time()
                        ),
                    }

                    save_state(
                        state
                    )

                except Exception as e:

                    order_info = {
                        "error": str(e)
                    }

                    print(
                        "REAL ORDER ERROR:",
                        e
                    )

    # -----------------------------------------------------
    # TELEGRAM
    # -----------------------------------------------------

    text = (
        "💓 ATI FUTURES V9 REAL\n\n"
        "⚡ AGG TRADES → 5M\n"
        "☁️ ICHIMOKU 9 / 26 / 52\n\n"
        f"📊 Markets: {len(markets)}\n"
        f"📈 5M OK: {ok}\n"
        f"🧠 Ichimoku Ready: "
        f"{len(ready)}\n"
        f"🔥 Signals: {len(signals)}\n"
        f"❌ Errors: {errors}\n"
        f"⏱️ Scan: {elapsed:.2f}s\n\n"
    )

    if signals:

        text += "🔥 SIGNALS\n\n"

        for s in signals[:5]:

            text += (
                f"{'🟢' if s['signal']=='BUY' else '🔴'} "
                f"{s['signal']} "
                f"{display_symbol(s['symbol'])}\n"
                f"💰 {s['price']:.10g}\n"
                f"⭐ Score: {s['score']}\n"
                f"📋 "
                f"{', '.join(s['reasons'])}\n\n"
            )

    else:

        text += (
            "☁️ NO SIGNAL THIS CYCLE\n\n"
        )

    if REAL_TRADING:

        if active_positions:

            text += (
                "🔒 ACTIVE POSITION EXISTS\n"
                "🚫 NEW ORDER BLOCKED\n\n"
            )

        if order_info:

            if "error" in order_info:

                text += (
                    "❌ REAL ORDER FAILED\n"
                    f"{order_info['error']}\n\n"
                )

            else:

                text += (
                    "🚨 REAL ORDER EXECUTED\n\n"
                    f"💎 "
                    f"{order_info['order'].get('symbol')}\n"
                    f"📌 "
                    f"{order_info['order'].get('side')}\n"
                    f"📦 Qty: "
                    f"{order_info['quantity']}\n"
                )

                sltp = order_info.get(
                    "sltp"
                )

                if sltp and "sl" in sltp:

                    text += (
                        f"🛑 SL: "
                        f"{sltp['sl']:.10g}\n"
                        f"🎯 TP: "
                        f"{sltp['tp']:.10g}\n"
                    )

                text += "\n"

    text += (
        f"🔒 REAL TRADING: "
        f"{REAL_TRADING}\n"
        "🕐 "
        + datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    print(text)
    telegram_send(text)


if __name__ == "__main__":
    main()
