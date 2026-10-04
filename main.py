import os
import time
import json
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN, ROUND_UP, InvalidOperation
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.49-REAL
# TABDEAL SPOT
#
# AL BROOKS PRICE ACTION
# Trend → REAL BOS → Pullback → Continuation → CLOSED CONFIRM
#
# IMPORTANT:
# ORDER_USDT = desired quote value per real BUY.
# The bot calculates coin quantity from the signal price.
#
# SAFETY:
# - Never increases order above ORDER_USDT just to satisfy minQty.
# - If minQty / minNotional requires more than ORDER_USDT,
#   the candidate is SKIPPED.
# - stepSize is always respected.
# - A quantity error will NOT crash the whole run.
# ============================================================


VERSION = "V40.2.49-REAL"

BASE = "https://api1.tabdeal.org"
API_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 12

RECV_WINDOW = int(os.getenv("RECV_WINDOW", "10000"))

SCAN_LIMIT = int(os.getenv("SCAN_LIMIT", "15"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "12"))

MIN_SCORE = float(os.getenv("MIN_SCORE", "11"))

# ------------------------------------------------------------
# REAL ORDER VALUE
# Default = 2 USDT
# ------------------------------------------------------------
ORDER_USDT = Decimal(os.getenv("ORDER_USDT", "2"))

# Backward compatibility:
# If old GitHub secret ORDER_QTY exists, do NOT treat it as
# coin quantity anymore. The bot uses ORDER_USDT.
#
# You should set:
# ORDER_USDT = 2
#
# LIVE_TRADING=true
# ------------------------------------------------------------

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "false")
    .strip()
    .lower()
    in ("1", "true", "yes", "on")
)

MAX_REAL_BUYS_PER_RUN = 1

API_KEY = (
    os.getenv("TABDEAL_API_KEY")
    or os.getenv("TABDIL_API_KEY")
    or ""
)

API_SECRET = (
    os.getenv("TABDEAL_API_SECRET")
    or os.getenv("TABDIL_API_SECRET")
    or ""
)

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

session = requests.Session()
session.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/40.2.49"
    }
)


# ============================================================
# TIME / TELEGRAM
# ============================================================

def now_text():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def tg(text):
    if not TG_TOKEN or not TG_CHAT:
        print("TELEGRAM: credentials missing")
        return False

    try:
        r = session.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={
                "chat_id": TG_CHAT,
                "text": text,
            },
            timeout=TIMEOUT,
        )

        if not r.ok:
            print(
                "TELEGRAM ERROR",
                r.status_code,
                r.text[:500],
            )
            return False

        return True

    except Exception as e:
        print("TELEGRAM ERROR", repr(e))
        return False


# ============================================================
# PUBLIC API
# ============================================================

def public_get(path, params=None):
    r = session.get(
        f"{API_ROOT}{path}",
        params=params or {},
        timeout=TIMEOUT,
    )

    if not r.ok:
        raise RuntimeError(
            f"HTTP {r.status_code}: {r.text[:700]}"
        )

    return r.json()


def server_time():
    data = public_get("/time")

    return int(
        data.get(
            "serverTime",
            int(time.time() * 1000),
        )
    )


# ============================================================
# SIGNED API
# ============================================================

def signed_request(method, path, params=None):

    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDEAL_API_KEY / TABDEAL_API_SECRET missing"
        )

    p = dict(params or {})

    p["timestamp"] = server_time()
    p["recvWindow"] = RECV_WINDOW

    query = "&".join(
        f"{k}={p[k]}"
        for k in p
    )

    sig = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()

    p["signature"] = sig

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    method = method.upper()

    if method == "GET":

        r = session.get(
            f"{API_ROOT}{path}",
            params=p,
            headers=headers,
            timeout=TIMEOUT,
        )

    elif method == "POST":

        r = session.post(
            f"{ORDER_ROOT}{path}",
            data=p,
            headers=headers,
            timeout=TIMEOUT,
        )

    elif method == "DELETE":

        r = session.delete(
            f"{ORDER_ROOT}{path}",
            data=p,
            headers=headers,
            timeout=TIMEOUT,
        )

    else:
        raise ValueError(method)

    try:
        data = r.json()
    except Exception:
        data = {
            "raw": r.text
        }

    if not r.ok:
        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{json.dumps(data, ensure_ascii=False)[:1000]}"
        )

    if (
        isinstance(data, dict)
        and data.get("code") not in (None, 0, "0")
    ):
        raise RuntimeError(
            f"TABDEAL CODE {data.get('code')}: "
            f"{data.get('msg', data)}"
        )

    return data


# ============================================================
# ACCOUNT
# ============================================================

def auth_test():

    account = signed_request(
        "GET",
        "/account",
    )

    if not isinstance(account, dict):
        raise RuntimeError(
            "Invalid account response"
        )

    if account.get("canTrade") is False:
        raise RuntimeError(
            "Tabdeal account canTrade=false"
        )

    return account


def balance(account, asset):

    for b in account.get("balances", []):

        if (
            str(b.get("asset", "")).upper()
            == asset.upper()
        ):
            try:
                return Decimal(
                    str(
                        b.get(
                            "free",
                            "0",
                        )
                    )
                )
            except Exception:
                return Decimal("0")

    return Decimal("0")


# ============================================================
# MARKET HELPERS
# ============================================================

def symbol_from_market(item):

    s = str(
        item.get("symbol")
        or item.get("tabdealSymbol")
        or ""
    ).upper()

    if not s:
        return ""

    return s.replace("_", "")


def get_usdt_markets():

    data = public_get(
        "/exchangeInfo"
    )

    if isinstance(data, dict):
        items = data.get(
            "symbols",
            [],
        )

    elif isinstance(data, list):
        items = data

    else:
        raise RuntimeError(
            "Invalid exchangeInfo response type: "
            f"{type(data).__name__}"
        )

    markets = []

    for x in items:

        if not isinstance(x, dict):
            continue

        symbol = symbol_from_market(x)

        status = str(
            x.get(
                "status",
                "TRADING",
            )
        ).upper()

        if (
            symbol.endswith("USDT")
            and status not in (
                "BREAK",
                "HALT",
                "OFFLINE",
            )
        ):
            markets.append(x)

    return markets


# ============================================================
# TRADES / CANDLES
# ============================================================

def trades(symbol):

    data = public_get(
        "/trades",
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if not isinstance(data, list):
        raise RuntimeError(
            "trades response is not list"
        )

    return data


def make_candles(raw, minutes=5):

    buckets = {}

    width = (
        minutes
        * 60
        * 1000
    )

    for t in raw:

        try:
            ts = int(
                t.get("time")
            )

            p = float(
                t.get("price")
            )

        except Exception:
            continue

        b = ts - (
            ts % width
        )

        c = buckets.setdefault(
            b,
            {
                "t": b,
                "o": p,
                "h": p,
                "l": p,
                "c": p,
                "v": 0.0,
            },
        )

        c["h"] = max(
            c["h"],
            p,
        )

        c["l"] = min(
            c["l"],
            p,
        )

        c["c"] = p

        try:
            c["v"] += float(
                t.get(
                    "qty",
                    0,
                )
            )
        except Exception:
            pass

    return [
        buckets[k]
        for k in sorted(buckets)
    ]


def atr(candles, n=14):

    if len(candles) < n + 1:
        return 0.0

    trs = []

    for i in range(
        1,
        len(candles),
    ):

        c = candles[i]

        prev = candles[
            i - 1
        ]["c"]

        trs.append(
            max(
                c["h"] - c["l"],
                abs(
                    c["h"] - prev
                ),
                abs(
                    c["l"] - prev
                ),
            )
        )

    return sum(
        trs[-n:]
    ) / n


# ============================================================
# PRICE ACTION
# ============================================================

def analyze(symbol, market):

    raw = trades(symbol)

    candles = make_candles(
        raw,
        5,
    )

    if len(candles) < 35:
        return None

    # Ignore current forming candle.
    closed = candles[:-1]

    if len(closed) < 30:
        return None

    c = closed[-1]
    prev = closed[-2]

    recent = closed[-8:]

    a = atr(
        closed,
        14,
    )

    if a <= 0:
        return None

    highs = [
        x["h"]
        for x in closed[-12:-2]
    ]

    lows = [
        x["l"]
        for x in closed[-12:-2]
    ]

    swing_high = max(highs)
    swing_low = min(lows)

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    h1 = max(
        x["h"]
        for x in closed[-6:-3]
    )

    h2 = max(
        x["h"]
        for x in closed[-3:]
    )

    l1 = min(
        x["l"]
        for x in closed[-6:-3]
    )

    l2 = min(
        x["l"]
        for x in closed[-3:]
    )

    up = (
        h2 >= h1
        and l2 >= l1
    )

    range_ok = (
        max(
            x["h"]
            for x in recent
        )
        -
        min(
            x["l"]
            for x in recent
        )
        <= a * 8
    )

    # --------------------------------------------------------
    # BOS
    # --------------------------------------------------------

    bos_now = (
        c["c"] > swing_high
        and c["c"] > prev["h"]
    )

    bos_prev = (
        prev["c"]
        > swing_high * 0.998
        and prev["c"]
        > closed[-3]["h"]
    )

    breakout = (
        bos_now
        or bos_prev
    )

    # --------------------------------------------------------
    # PULLBACK
    # --------------------------------------------------------

    broken_level = swing_high

    pullback = False

    for x in closed[-4:]:

        if (
            x["l"]
            <= broken_level * 1.003
            and
            x["c"]
            >= broken_level * 0.997
        ):
            pullback = True
            break

    if bos_now:
        pullback = True

    # --------------------------------------------------------
    # SIGNAL BAR
    # --------------------------------------------------------

    body = abs(
        c["c"] - c["o"]
    )

    upper = (
        c["h"]
        - max(
            c["o"],
            c["c"],
        )
    )

    signal_bar = (
        c["c"] > c["o"]
        and body >= a * 0.18
        and upper <= body * 1.8
    )

    continuation = (
        c["c"] > prev["c"]
        and c["c"] >= c["o"]
    )

    chase = (
        c["c"] - swing_low
        > a * 6.0
    )

    failed = (
        c["c"] < swing_high
        and prev["h"] > swing_high
        and prev["c"] < swing_high
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0

    score += 3 if up else 0
    score += 2 if range_ok else 0

    score += (
        4
        if bos_now
        else (
            3
            if bos_prev
            else 0
        )
    )

    score += (
        2
        if pullback
        else 0
    )

    score += (
        2
        if continuation
        else 0
    )

    score += (
        2
        if signal_bar
        else 0
    )

    score -= (
        5
        if failed
        else 0
    )

    score -= (
        4
        if chase
        else 0
    )

    ready = (
        (up or range_ok)
        and breakout
        and pullback
        and continuation
        and not failed
        and not chase
        and score >= MIN_SCORE
    )

    support = min(
        x["l"]
        for x in closed[-6:]
    )

    entry = c["c"]

    risk = (
        entry - support
    )

    if (
        risk <= 0
        or risk < a * 0.25
    ):
        return None

    tp1 = (
        entry
        + 1.5 * risk
    )

    tp2 = (
        entry
        + 2.2 * risk
    )

    return {
        "symbol": symbol,
        "score": round(
            score,
            1,
        ),
        "ready": ready,
        "entry": entry,
        "support": support,
        "tp1": tp1,
        "tp2": tp2,
        "atr": a,
        "bos": (
            bos_now
            or bos_prev
        ),
        "pullback": pullback,
        "continuation": continuation,
        "signal_bar": signal_bar,
        "chase": chase,
        "candles": len(closed),
    }


# ============================================================
# EXCHANGE FILTERS
# ============================================================

def extract_filter(
    market,
    name,
):

    filters = (
        market.get(
            "filters",
            []
        )
        if isinstance(
            market,
            dict,
        )
        else []
    )

    for f in filters:

        if (
            str(
                f.get(
                    "filterType",
                    "",
                )
            ).upper()
            == name.upper()
        ):
            return f

    return {}


def dec(value, default="0"):

    try:
        return Decimal(
            str(value)
        )
    except Exception:
        return Decimal(default)


def decimal_places(step):

    if step <= 0:
        return 0

    normalized = step.normalize()

    return max(
        0,
        -normalized.as_tuple().exponent,
    )


def floor_step(
    value,
    step,
):

    if step <= 0:
        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


def ceil_step(
    value,
    step,
):

    if step <= 0:
        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_UP
    ) * step


# ============================================================
# MARKET ORDER QUANTITY CALCULATION
# ============================================================

def get_market_limits(market):

    lot = (
        extract_filter(
            market,
            "MARKET_LOT_SIZE",
        )
    )

    if not lot:
        lot = extract_filter(
            market,
            "LOT_SIZE",
        )

    min_qty = dec(
        lot.get(
            "minQty",
            "0",
        )
    )

    max_qty = dec(
        lot.get(
            "maxQty",
            "0",
        )
    )

    step_size = dec(
        lot.get(
            "stepSize",
            "0",
        )
    )

    notional = extract_filter(
        market,
        "MIN_NOTIONAL",
    )

    if not notional:
        notional = extract_filter(
            market,
            "NOTIONAL",
        )

    min_notional = dec(
        notional.get(
            "minNotional",
            "0",
        )
    )

    return (
        min_qty,
        max_qty,
        step_size,
        min_notional,
    )


def prepare_market_buy(
    signal,
    market,
):

    symbol = signal["symbol"]

    price = Decimal(
        str(signal["entry"])
    )

    if price <= 0:
        raise RuntimeError(
            "Invalid signal price"
        )

    desired_usdt = ORDER_USDT

    if desired_usdt <= 0:
        raise RuntimeError(
            "ORDER_USDT must be > 0"
        )

    (
        min_qty,
        max_qty,
        step_size,
        min_notional,
    ) = get_market_limits(
        market
    )

    # --------------------------------------------------------
    # Convert desired USDT to coin quantity.
    # Example:
    # ORDER_USDT = 2
    # price = 0.50
    # qty = 4
    # --------------------------------------------------------

    raw_qty = (
        desired_usdt / price
    )

    # Always round DOWN first.
    qty = floor_step(
        raw_qty,
        step_size,
    )

    # --------------------------------------------------------
    # Minimum quantity
    #
    # IMPORTANT:
    # We DO NOT automatically increase qty if that means
    # spending more than ORDER_USDT.
    # --------------------------------------------------------

    if (
        min_qty > 0
        and qty < min_qty
    ):

        required_usdt = (
            min_qty * price
        )

        raise RuntimeError(
            f"MARKET SKIPPED: {symbol} "
            f"minQty={min_qty}, "
            f"needed~{required_usdt:.8f} USDT, "
            f"target={desired_usdt} USDT"
        )

    # --------------------------------------------------------
    # Minimum notional
    # --------------------------------------------------------

    estimated_notional = (
        qty * price
    )

    if (
        min_notional > 0
        and estimated_notional
        < min_notional
    ):

        raise RuntimeError(
            f"MARKET SKIPPED: {symbol} "
            f"minNotional={min_notional}, "
            f"estimated={estimated_notional:.8f} USDT, "
            f"target={desired_usdt} USDT"
        )

    # --------------------------------------------------------
    # Maximum quantity
    # --------------------------------------------------------

    if (
        max_qty > 0
        and qty > max_qty
    ):

        qty = floor_step(
            max_qty,
            step_size,
        )

        estimated_notional = (
            qty * price
        )

    if qty <= 0:
        raise RuntimeError(
            f"MARKET SKIPPED: {symbol} "
            f"normalized quantity is zero"
        )

    # --------------------------------------------------------
    # Final minimum check
    # --------------------------------------------------------

    if (
        min_qty > 0
        and qty < min_qty
    ):
        raise RuntimeError(
            f"MARKET SKIPPED: {symbol} "
            f"final qty {qty} < minQty {min_qty}"
        )

    if (
        min_notional > 0
        and estimated_notional
        < min_notional
    ):
        raise RuntimeError(
            f"MARKET SKIPPED: {symbol} "
            f"final notional "
            f"{estimated_notional:.8f} "
            f"< minNotional {min_notional}"
        )

    places = max(
        decimal_places(step_size),
        8,
    )

    qty_text = (
        f"{qty:.{places}f}"
        .rstrip("0")
        .rstrip(".")
    )

    return {
        "symbol": symbol,
        "qty": qty,
        "qty_text": qty_text,
        "estimated_usdt": estimated_notional,
        "min_qty": min_qty,
        "max_qty": max_qty,
        "step_size": step_size,
        "min_notional": min_notional,
    }


# ============================================================
# REAL BUY
# ============================================================

def place_real_buy(
    signal,
    market,
    account,
):

    if not LIVE_TRADING:
        raise RuntimeError(
            "LIVE_TRADING is false"
        )

    if not account.get(
        "canTrade",
        False,
    ):
        raise RuntimeError(
            "Account canTrade=false"
        )

    symbol = signal["symbol"]

    # --------------------------------------------------------
    # Calculate valid quantity using exchange rules.
    # --------------------------------------------------------

    order_info = prepare_market_buy(
        signal,
        market,
    )

    qty = order_info["qty"]
    qty_text = order_info["qty_text"]

    quote = "USDT"

    free_quote = balance(
        account,
        quote,
    )

    estimated_cost = (
        qty
        * Decimal(
            str(signal["entry"])
        )
    )

    if free_quote <= 0:
        raise RuntimeError(
            f"No free {quote} balance"
        )

    # Keep a small safety margin for fees/slippage.
    if estimated_cost > free_quote:
        raise RuntimeError(
            f"Insufficient {quote}: "
            f"need~{estimated_cost}, "
            f"free={free_quote}"
        )

    tg(
        f"🚨 ATI REAL BUY START\n\n"
        f"🪙 {symbol}\n"
        f"📦 QTY: {qty_text}\n"
        f"💵 TARGET: {ORDER_USDT} USDT\n"
        f"💰 ESTIMATE: {estimated_cost:.8f} USDT\n"
        f"📏 minQty: {order_info['min_qty']}\n"
        f"📐 stepSize: {order_info['step_size']}\n"
        f"📊 SCORE: {signal['score']}\n"
        f"💵 ENTRY~: {signal['entry']:.8g}\n"
        f"🛡 SL(calc): {signal['support']:.8g}\n"
        f"🎯 TP1(calc): {signal['tp1']:.8g}\n"
        f"🎯 TP2(calc): {signal['tp2']:.8g}\n\n"
        f"⚠️ LIVE MARKET BUY WILL BE SENT NOW"
    )

    order = signed_request(
        "POST",
        "/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": qty_text,
        },
    )

    return order


# ============================================================
# ORDER RESULT
# ============================================================

def format_order(order):

    return (
        f"🟢 ATI REAL BUY ACCEPTED\n\n"
        f"🪙 {order.get('symbol', '?')}\n"
        f"🆔 ORDER ID: "
        f"{order.get('orderId', '?')}\n"
        f"📦 QTY: "
        f"{order.get('executedQty', order.get('origQty', '?'))}\n"
        f"💰 STATUS: "
        f"{order.get('status', '?')}\n"
        f"💵 QUOTE: "
        f"{order.get('cummulativeQuoteQty', order.get('cumulativeQuoteQty', '?'))}\n\n"
        f"🕐 {now_text()}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )

    print(
        "🧠 AL BROOKS PRICE ACTION"
    )

    print(
        "📐 Trend → REAL BOS → Pullback → "
        "Continuation → CLOSED CONFIRM"
    )

    print(
        "⏱ TIMEFRAME: 5m CLOSED CANDLES"
    )

    print(
        "🚫 EMA: OFF"
    )

    print(
        f"🔓 REAL ORDERS: "
        f"{'ENABLED' if LIVE_TRADING else 'DISABLED'}"
    )

    print(
        f"💵 ORDER TARGET: "
        f"{ORDER_USDT} USDT"
    )

    print(
        f"🕐 {now_text()}"
    )

    tg(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"🔓 REAL ORDERS: "
        f"{'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"
        f"💵 ORDER TARGET: "
        f"{ORDER_USDT} USDT\n"
        f"📊 SCAN STARTING...\n"
        f"🕐 {now_text()}"
    )

    try:

        # ----------------------------------------------------
        # MARKET LIST
        # ----------------------------------------------------

        markets = get_usdt_markets()

        print(
            "USDT MARKETS:",
            len(markets),
        )

        tg(
            f"📊 USDT MARKETS: {len(markets)}\n"
            f"🔎 DEEP SCAN TOP {SCAN_LIMIT}"
        )

        # ----------------------------------------------------
        # CANDIDATES
        # ----------------------------------------------------

        candidates = markets[
            :max(
                SCAN_LIMIT * 4,
                30,
            )
        ]

        results = []

        with ThreadPoolExecutor(
            max_workers=MAX_WORKERS
        ) as ex:

            futs = {
                ex.submit(
                    analyze,
                    symbol_from_market(m),
                    m,
                ): m
                for m in candidates
            }

            for fut in as_completed(futs):

                try:

                    r = fut.result()

                    if r:
                        results.append(
                            (
                                r,
                                futs[fut],
                            )
                        )

                except Exception as e:

                    print(
                        "SCAN ERROR:",
                        repr(e),
                    )

        # ----------------------------------------------------
        # SORT
        # ----------------------------------------------------

        results.sort(
            key=lambda x:
            x[0]["score"],
            reverse=True,
        )

        top = results[
            :SCAN_LIMIT
        ]

        ready = [
            x
            for x in top
            if x[0]["ready"]
        ]

        # ----------------------------------------------------
        # TELEGRAM SCAN
        # ----------------------------------------------------

        if top:

            lines = [
                "📡 ATI SCAN RESULT"
            ]

            for s, _ in top[:10]:

                tag = (
                    "🔥 BUY READY"
                    if s["ready"]
                    else "👀 WATCH"
                )

                lines.append(
                    f"{tag} "
                    f"{s['symbol']} | "
                    f"score {s['score']:.1f} | "
                    f"entry~ "
                    f"{s['entry']:.8g}"
                )

            tg(
                "\n".join(lines)
            )

        else:

            tg(
                "📡 ATI SCAN RESULT\n\n"
                "❌ No valid closed-candle candidates"
            )

        # ----------------------------------------------------
        # NO SIGNAL
        # ----------------------------------------------------

        if not ready:

            tg(
                "⏳ NO BUY\n"
                "No candidate passed "
                "V40.2.49 conditions."
            )

            return

        # ----------------------------------------------------
        # BEST SIGNAL
        # ----------------------------------------------------

        signal, market = ready[0]

        tg(
            f"🔥 BUY READY\n\n"
            f"🪙 {signal['symbol']}\n"
            f"📊 SCORE: {signal['score']}\n"
            f"📐 Trend → BOS → Pullback → "
            f"Continuation → CLOSED\n"
            f"💵 ENTRY~ {signal['entry']:.8g}\n"
            f"🛡 SL(calc) {signal['support']:.8g}\n"
            f"🎯 TP1(calc) {signal['tp1']:.8g}\n"
            f"🎯 TP2(calc) {signal['tp2']:.8g}\n"
            f"💵 ORDER TARGET: "
            f"{ORDER_USDT} USDT"
        )

        # ----------------------------------------------------
        # PAPER MODE
        # ----------------------------------------------------

        if not LIVE_TRADING:

            tg(
                "🔒 REAL BUY NOT SENT\n"
                "LIVE_TRADING=false"
            )

            return

        # ----------------------------------------------------
        # AUTH
        # ----------------------------------------------------

        tg(
            "🔐 AUTH CHECK BEFORE REAL BUY..."
        )

        account = auth_test()

        free_usdt = balance(
            account,
            "USDT",
        )

        tg(
            f"✅ AUTH OK\n"
            f"✅ canTrade=true\n"
            f"💰 FREE USDT: {free_usdt}\n"
            f"🔎 CHECKING MARKET LIMITS..."
        )

        # ----------------------------------------------------
        # CHECK ORDER LIMITS BEFORE SENDING
        # ----------------------------------------------------

        try:

            order_info = prepare_market_buy(
                signal,
                market,
            )

        except Exception as e:

            # This is NOT a fatal bot error.
            # The market is simply unsuitable
            # for the configured order value.

            reason = str(e)

            print(
                "BUY SKIPPED:",
                reason,
            )

            tg(
                f"⏭ BUY SKIPPED\n\n"
                f"🪙 {signal['symbol']}\n"
                f"💵 TARGET: {ORDER_USDT} USDT\n"
                f"❌ {reason}\n\n"
                f"🛡 NO ORDER SENT"
            )

            return

        tg(
            f"✅ ORDER SIZE VALID\n\n"
            f"🪙 {signal['symbol']}\n"
            f"📦 QTY: "
            f"{order_info['qty_text']}\n"
            f"💵 EST. VALUE: "
            f"{order_info['estimated_usdt']:.8f} USDT\n"
            f"📏 minQty: "
            f"{order_info['min_qty']}\n"
            f"📐 stepSize: "
            f"{order_info['step_size']}\n\n"
            f"🚀 Sending ONE REAL BUY..."
        )

        # ----------------------------------------------------
        # ONE REAL BUY
        # ----------------------------------------------------

        order = place_real_buy(
            signal,
            market,
            account,
        )

        print(
            json.dumps(
                order,
                ensure_ascii=False,
                indent=2,
            )
        )

        tg(
            format_order(order)
        )

    except Exception as e:

        msg = str(e)

        print(
            "FATAL:",
            repr(e),
        )

        tg(
            f"🚨 ATI ERROR {VERSION}\n\n"
            f"❌ {msg[:1800]}\n\n"
            f"🛑 REAL BUY LOCKED FOR THIS RUN"
        )

        raise


if __name__ == "__main__":
    main()
