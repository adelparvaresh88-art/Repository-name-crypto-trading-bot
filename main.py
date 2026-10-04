import os
import time
import json
import hmac
import hashlib
import math
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

VERSION = "V40.2.48-REAL"
BASE = "https://api1.tabdeal.org"
API_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"
TIMEOUT = 12
RECV_WINDOW = int(os.getenv("RECV_WINDOW", "10000"))
SCAN_LIMIT = int(os.getenv("SCAN_LIMIT", "15"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "12"))
MIN_SCORE = float(os.getenv("MIN_SCORE", "11"))
ORDER_QTY = os.getenv("ORDER_QTY", "0.001")
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").strip().lower() in ("1", "true", "yes", "on")
MAX_REAL_BUYS_PER_RUN = 1

API_KEY = os.getenv("TABDEAL_API_KEY") or os.getenv("TABDIL_API_KEY") or ""
API_SECRET = os.getenv("TABDEAL_API_SECRET") or os.getenv("TABDIL_API_SECRET") or ""
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

session = requests.Session()
session.headers.update({"User-Agent": "ATI-Crypto-Bot/40.2.41"})


def now_text():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def tg(text):
    if not TG_TOKEN or not TG_CHAT:
        print("TELEGRAM: credentials missing")
        return False
    try:
        r = session.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT, "text": text},
            timeout=TIMEOUT,
        )
        if not r.ok:
            print("TELEGRAM ERROR", r.status_code, r.text[:500])
            return False
        return True
    except Exception as e:
        print("TELEGRAM ERROR", repr(e))
        return False


def public_get(path, params=None):
    r = session.get(f"{API_ROOT}{path}", params=params or {}, timeout=TIMEOUT)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:700]}")
    return r.json()


def server_time():
    data = public_get("/time")
    return int(data.get("serverTime", int(time.time() * 1000)))


def signed_request(method, path, params=None):
    if not API_KEY or not API_SECRET:
        raise RuntimeError("TABDEAL_API_KEY / TABDEAL_API_SECRET missing")

    p = dict(params or {})
    # Official Tabdeal signing: query-string parameters + timestamp, HMAC-SHA256.
    p["timestamp"] = server_time()
    p["recvWindow"] = RECV_WINDOW
    query = "&".join(f"{k}={p[k]}" for k in p)
    sig = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    p["signature"] = sig
    headers = {"X-MBX-APIKEY": API_KEY}

    if method.upper() == "GET":
        r = session.get(f"{API_ROOT}{path}", params=p, headers=headers, timeout=TIMEOUT)
    elif method.upper() == "POST":
        r = session.post(f"{ORDER_ROOT}{path}", data=p, headers=headers, timeout=TIMEOUT)
    elif method.upper() == "DELETE":
        r = session.delete(f"{ORDER_ROOT}{path}", data=p, headers=headers, timeout=TIMEOUT)
    else:
        raise ValueError(method)

    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}: {json.dumps(data, ensure_ascii=False)[:1000]}")
    if isinstance(data, dict) and data.get("code") not in (None, 0, "0"):
        raise RuntimeError(f"TABDEAL CODE {data.get('code')}: {data.get('msg', data)}")
    return data


def auth_test():
    account = signed_request("GET", "/account")
    if not isinstance(account, dict):
        raise RuntimeError("Invalid account response")
    if account.get("canTrade") is False:
        raise RuntimeError("Tabdeal account canTrade=false")
    return account


def balance(account, asset):
    for b in account.get("balances", []):
        if str(b.get("asset", "")).upper() == asset.upper():
            try:
                return Decimal(str(b.get("free", "0")))
            except Exception:
                return Decimal("0")
    return Decimal("0")


def symbol_from_market(item):
    s = str(item.get("symbol") or item.get("tabdealSymbol") or "").upper()
    if not s:
        return ""
    return s.replace("_", "")


def get_usdt_markets():
    data = public_get("/exchangeInfo")

    # Tabdeal may return either:
    #   {"symbols": [...]}
    # or a raw list: [...]
    if isinstance(data, dict):
        items = data.get("symbols", [])
    elif isinstance(data, list):
        items = data
    else:
        raise RuntimeError(f"Invalid exchangeInfo response type: {type(data).__name__}")

    markets = []
    for x in items:
        if not isinstance(x, dict):
            continue
        symbol = symbol_from_market(x)
        status = str(x.get("status", "TRADING")).upper()
        if symbol.endswith("USDT") and status not in ("BREAK", "HALT", "OFFLINE"):
            markets.append(x)

    return markets


def trades(symbol):
    data = public_get("/trades", {"symbol": symbol, "limit": 1000})
    if not isinstance(data, list):
        raise RuntimeError("trades response is not list")
    return data


def make_candles(raw, minutes=5):
    buckets = {}
    width = minutes * 60 * 1000
    for t in raw:
        try:
            ts = int(t.get("time"))
            p = float(t.get("price"))
        except Exception:
            continue
        b = ts - (ts % width)
        c = buckets.setdefault(b, {"t": b, "o": p, "h": p, "l": p, "c": p, "v": 0.0})
        c["h"] = max(c["h"], p)
        c["l"] = min(c["l"], p)
        c["c"] = p
        try:
            c["v"] += float(t.get("qty", 0))
        except Exception:
            pass
    return [buckets[k] for k in sorted(buckets)]


def atr(candles, n=14):
    if len(candles) < n + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        c = candles[i]
        prev = candles[i - 1]["c"]
        trs.append(max(c["h"] - c["l"], abs(c["h"] - prev), abs(c["l"] - prev)))
    return sum(trs[-n:]) / n


def analyze(symbol, market):
    raw = trades(symbol)
    candles = make_candles(raw, 5)
    # Ignore the currently forming 5m candle.
    if len(candles) < 35:
        return None
    closed = candles[:-1]
    if len(closed) < 30:
        return None

    c = closed[-1]
    prev = closed[-2]
    recent = closed[-8:]
    a = atr(closed, 14)
    if a <= 0:
        return None

    highs = [x["h"] for x in closed[-12:-2]]
    lows = [x["l"] for x in closed[-12:-2]]
    swing_high = max(highs)
    swing_low = min(lows)

    # Trend / structure
    h1 = max(x["h"] for x in closed[-6:-3])
    h2 = max(x["h"] for x in closed[-3:])
    l1 = min(x["l"] for x in closed[-6:-3])
    l2 = min(x["l"] for x in closed[-3:])
    up = h2 >= h1 and l2 >= l1
    range_ok = (max(x["h"] for x in recent) - min(x["l"] for x in recent)) <= a * 8

    bos_now = c["c"] > swing_high and c["c"] > prev["h"]
    bos_prev = prev["c"] > swing_high * 0.998 and prev["c"] > closed[-3]["h"]
    breakout = bos_now or bos_prev

    # Pullback after BOS: recent candle touched the broken area and held above it.
    broken_level = swing_high
    pullback = False
    for x in closed[-4:]:
        if x["l"] <= broken_level * 1.003 and x["c"] >= broken_level * 0.997:
            pullback = True
            break
    if bos_now:
        pullback = True

    body = abs(c["c"] - c["o"])
    upper = c["h"] - max(c["o"], c["c"])
    signal_bar = c["c"] > c["o"] and body >= a * 0.18 and upper <= body * 1.8
    continuation = c["c"] > prev["c"] and c["c"] >= c["o"]
    chase = (c["c"] - swing_low) > a * 6.0
    failed = c["c"] < swing_high and prev["h"] > swing_high and prev["c"] < swing_high

    score = 0
    score += 3 if up else 0
    score += 2 if range_ok else 0
    score += 4 if bos_now else (3 if bos_prev else 0)
    score += 2 if pullback else 0
    score += 2 if continuation else 0
    score += 2 if signal_bar else 0
    score -= 5 if failed else 0
    score -= 4 if chase else 0

    ready = (up or range_ok) and breakout and pullback and continuation and not failed and not chase and score >= MIN_SCORE

    support = min(x["l"] for x in closed[-6:])
    entry = c["c"]
    risk = entry - support
    if risk <= 0 or risk < a * 0.25:
        return None
    tp1 = entry + 1.5 * risk
    tp2 = entry + 2.2 * risk

    return {
        "symbol": symbol,
        "score": round(score, 1),
        "ready": ready,
        "entry": entry,
        "support": support,
        "tp1": tp1,
        "tp2": tp2,
        "atr": a,
        "bos": bos_now or bos_prev,
        "pullback": pullback,
        "continuation": continuation,
        "signal_bar": signal_bar,
        "chase": chase,
        "candles": len(closed),
    }


def extract_filter(market, name):
    for f in market.get("filters", []) if isinstance(market, dict) else []:
        if str(f.get("filterType", "")).upper() == name.upper():
            return f
    return {}


def normalize_qty(qty, market):
    try:
        q = Decimal(str(qty))
    except InvalidOperation:
        raise RuntimeError(f"Invalid ORDER_QTY: {qty}")
    f = extract_filter(market, "LOT_SIZE") or extract_filter(market, "MARKET_LOT_SIZE")
    step = Decimal(str(f.get("stepSize", "0"))) if f else Decimal("0")
    min_qty = Decimal(str(f.get("minQty", "0"))) if f else Decimal("0")
    max_qty = Decimal(str(f.get("maxQty", "0"))) if f else Decimal("0")
    if step > 0:
        q = (q / step).to_integral_value(rounding=ROUND_DOWN) * step
    if min_qty > 0 and q < min_qty:
        raise RuntimeError(f"ORDER_QTY {q} < exchange minQty {min_qty}")
    if max_qty > 0 and q > max_qty:
        raise RuntimeError(f"ORDER_QTY {q} > exchange maxQty {max_qty}")
    return q


def place_real_buy(signal, market, account):
    if not LIVE_TRADING:
        raise RuntimeError("LIVE_TRADING is false")
    if not account.get("canTrade", False):
        raise RuntimeError("Account canTrade=false")

    symbol = signal["symbol"]
    qty = normalize_qty(ORDER_QTY, market)
    if qty <= 0:
        raise RuntimeError("Normalized quantity is zero")

    base = symbol[:-4]
    quote = "USDT"
    free_quote = balance(account, quote)

    # Conservative pre-check using signal entry. This does not replace exchange validation.
    estimated_cost = qty * Decimal(str(signal["entry"]))
    if free_quote <= 0:
        raise RuntimeError(f"No free {quote} balance")
    if estimated_cost > free_quote:
        raise RuntimeError(f"Insufficient {quote}: need~{estimated_cost}, free={free_quote}")

    tg(
        f"🚨 ATI REAL BUY START\n\n"
        f"🪙 {symbol}\n"
        f"📌 QTY: {qty}\n"
        f"💵 ENTRY~: {signal['entry']:.8g}\n"
        f"📊 SCORE: {signal['score']}\n"
        f"🛡 SL(calc): {signal['support']:.8g}\n"
        f"🎯 TP1(calc): {signal['tp1']:.8g}\n"
        f"🎯 TP2(calc): {signal['tp2']:.8g}\n\n"
        f"⚠️ LIVE ORDER WILL BE SENT NOW"
    )

    order = signed_request(
        "POST",
        "/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": format(qty, "f"),
        },
    )
    return order


def format_order(order):
    return (
        f"🟢 ATI REAL BUY FILLED/ACCEPTED\n\n"
        f"🪙 {order.get('symbol', '?')}\n"
        f"🆔 ORDER ID: {order.get('orderId', '?')}\n"
        f"📦 QTY: {order.get('executedQty', order.get('origQty', '?'))}\n"
        f"💰 STATUS: {order.get('status', '?')}\n"
        f"💵 QUOTE: {order.get('cummulativeQuoteQty', order.get('cumulativeQuoteQty', '?'))}\n\n"
        f"🕐 {now_text()}"
    )


def main():
    print(f"⚡ ATI CRYPTO BOT {VERSION}")
    print("🧠 AL BROOKS PRICE ACTION")
    print("📐 Trend → REAL BOS → Pullback → Continuation → CLOSED CONFIRM")
    print("⏱ TIMEFRAME: 5m CLOSED CANDLES")
    print("🚫 EMA: OFF")
    print(f"🔓 REAL ORDERS: {'ENABLED' if LIVE_TRADING else 'DISABLED'}")
    print(f"📦 ORDER_QTY: {ORDER_QTY}")
    print(f"🕐 {now_text()}")

    tg(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"🔓 REAL ORDERS: {'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"
        f"📦 ORDER_QTY: {ORDER_QTY}\n"
        f"📊 SCAN STARTING...\n"
        f"🕐 {now_text()}"
    )

    try:
        markets = get_usdt_markets()
        print("USDT MARKETS:", len(markets))
        tg(f"📊 USDT MARKETS: {len(markets)}\n🔎 DEEP SCAN TOP {SCAN_LIMIT}")

        # Fast liquidity proxy: use the first markets returned by exchangeInfo, then score them.
        candidates = markets[: max(SCAN_LIMIT * 4, 30)]
        results = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(analyze, symbol_from_market(m), m): m for m in candidates}
            for fut in as_completed(futs):
                try:
                    r = fut.result()
                    if r:
                        results.append((r, futs[fut]))
                except Exception as e:
                    print("SCAN ERROR:", repr(e))

        results.sort(key=lambda x: x[0]["score"], reverse=True)
        top = results[:SCAN_LIMIT]
        ready = [x for x in top if x[0]["ready"]]

        if top:
            lines = ["📡 ATI SCAN RESULT"]
            for s, _ in top[:10]:
                tag = "🔥 BUY READY" if s["ready"] else "👀 WATCH"
                lines.append(f"{tag} {s['symbol']} | score {s['score']:.1f} | entry~ {s['entry']:.8g}")
            tg("\n".join(lines))
        else:
            tg("📡 ATI SCAN RESULT\n\n❌ No valid closed-candle candidates")

        if not ready:
            tg("⏳ NO BUY\nNo candidate passed V40.2.41 conditions.")
            return

        signal, market = ready[0]
        tg(
            f"🔥 BUY READY\n\n"
            f"🪙 {signal['symbol']}\n"
            f"📊 SCORE: {signal['score']}\n"
            f"📐 Trend → BOS → Pullback → Continuation → CLOSED\n"
            f"💵 ENTRY~ {signal['entry']:.8g}\n"
            f"🛡 SL(calc) {signal['support']:.8g}\n"
            f"🎯 TP1(calc) {signal['tp1']:.8g}\n"
            f"🎯 TP2(calc) {signal['tp2']:.8g}"
        )

        if not LIVE_TRADING:
            tg("🔒 REAL BUY NOT SENT\nLIVE_TRADING=false")
            return

        tg("🔐 AUTH CHECK BEFORE REAL BUY...")
        account = auth_test()
        tg("✅ AUTH OK\n✅ canTrade=true\n🚀 Sending ONE REAL BUY...")
        order = place_real_buy(signal, market, account)
        print(json.dumps(order, ensure_ascii=False, indent=2))
        tg(format_order(order))

    except Exception as e:
        msg = str(e)
        print("FATAL:", repr(e))
        tg(f"🚨 ATI ERROR {VERSION}\n\n❌ {msg[:1800]}\n\n🛑 REAL BUY LOCKED FOR THIS RUN")
        raise


if __name__ == "__main__":
    main()
