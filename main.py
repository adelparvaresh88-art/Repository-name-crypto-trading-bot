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

VERSION = "V40.2.56-REAL"
BASE = "https://api1.tabdeal.org"
API_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"
TIMEOUT = 12
RECV_WINDOW = int(os.getenv("RECV_WINDOW", "10000"))
SCAN_LIMIT = int(os.getenv("SCAN_LIMIT", "15"))
FULL_SCAN = os.getenv("FULL_SCAN", "true").strip().lower() in ("1", "true", "yes", "on")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "12"))
MIN_SCORE = float(os.getenv("MIN_SCORE", "9"))
ORDER_QTY = os.getenv("ORDER_QTY", "0.001")
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").strip().lower() in ("1", "true", "yes", "on")
MAX_REAL_BUYS_PER_RUN = 1

API_KEY = os.getenv("TABDEAL_API_KEY") or os.getenv("TABDIL_API_KEY") or ""
API_SECRET = os.getenv("TABDEAL_API_SECRET") or os.getenv("TABDIL_API_SECRET") or ""
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

session = requests.Session()
session.headers.update({"User-Agent": f"ATI/{VERSION}"})


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


SERVER_OFFSET_MS = 0


def server_time_sync():
    global SERVER_OFFSET_MS
    data = public_get("/time")
    server_ms = int(data.get("serverTime", int(time.time() * 1000)))
    SERVER_OFFSET_MS = server_ms - int(time.time() * 1000)
    print(f"🕐 SERVER OFFSET: {SERVER_OFFSET_MS} ms", flush=True)
    return server_ms


def signed_params(extra=None):
    if not API_KEY or not API_SECRET:
        raise RuntimeError("TABDEAL_API_KEY / TABDEAL_API_SECRET missing")

    params = {}
    if extra:
        for key, value in extra.items():
            if key in {"signature", "timestamp", "recvWindow"}:
                continue
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == "":
                continue
            params[key] = value

    # Tabdeal-compatible Postman-style signing: integer timestamp + raw query.
    params["timestamp"] = int(time.time() * 1000) + int(SERVER_OFFSET_MS)
    params["recvWindow"] = RECV_WINDOW
    raw_query = "&".join(f"{key}={value}" for key, value in params.items())
    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        raw_query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    params["signature"] = signature
    return params


def signed_request(method, path, params=None):
    p = signed_params(params)
    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }

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
    # Refresh server offset immediately before private authentication.
    server_time_sync()
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
    """Analyze one market and ALWAYS return a diagnostic record when possible."""
    base = {"symbol": symbol, "ready": False, "score": 0.0, "reason": "UNKNOWN"}
    try:
        raw = trades(symbol)
        candles = make_candles(raw, 5)
        base["raw_trades"] = len(raw)
        base["candles"] = len(candles)
        if len(candles) < 35:
            base["reason"] = "NOT_ENOUGH_CANDLES"
            return base

        closed = candles[:-1]
        if len(closed) < 30:
            base["reason"] = "NOT_ENOUGH_CLOSED"
            return base

        c = closed[-1]
        prev = closed[-2]
        recent = closed[-8:]
        a = atr(closed, 14)
        if a <= 0:
            base["reason"] = "ATR_ZERO"
            return base

        highs = [x["h"] for x in closed[-12:-2]]
        lows = [x["l"] for x in closed[-12:-2]]
        if not highs or not lows:
            base["reason"] = "NO_SWING_DATA"
            return base
        swing_high = max(highs)
        swing_low = min(lows)

        h1 = max(x["h"] for x in closed[-6:-3])
        h2 = max(x["h"] for x in closed[-3:])
        l1 = min(x["l"] for x in closed[-6:-3])
        l2 = min(x["l"] for x in closed[-3:])
        up = h2 >= h1 and l2 >= l1
        range_ok = (max(x["h"] for x in recent) - min(x["l"] for x in recent)) <= a * 8

        bos_now = c["c"] > swing_high and c["c"] > prev["h"]
        bos_prev = prev["c"] > swing_high * 0.998 and prev["c"] > closed[-3]["h"]
        breakout = bos_now or bos_prev

        broken_level = swing_high
        pullback = False
        for x in closed[-5:]:
            if x["l"] <= broken_level * 1.006 and x["c"] >= broken_level * 0.994:
                pullback = True
                break
        if bos_now:
            pullback = True

        body = abs(c["c"] - c["o"])
        upper = c["h"] - max(c["o"], c["c"])
        signal_bar = c["c"] > c["o"] and body >= a * 0.12 and upper <= body * 2.2
        continuation = c["c"] > prev["c"] and c["c"] >= c["o"]
        chase = (c["c"] - swing_low) > a * 7.0
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

        support = min(x["l"] for x in closed[-6:])
        entry = c["c"]
        risk = entry - support
        if risk <= 0:
            base.update({"score": score, "reason": "NO_POSITIVE_RISK", "bos": breakout, "pullback": pullback})
            return base
        if risk < a * 0.20:
            base.update({"score": score, "reason": "RISK_TOO_SMALL", "bos": breakout, "pullback": pullback})
            return base

        tp1 = entry + 1.5 * risk
        tp2 = entry + 2.2 * risk
        ready = (up or range_ok) and breakout and pullback and continuation and not failed and not chase and score >= MIN_SCORE

        if ready:
            reason = "BUY_READY"
        elif not (up or range_ok):
            reason = "NO_TREND_OR_RANGE"
        elif not breakout:
            reason = "NO_BOS"
        elif not pullback:
            reason = "NO_PULLBACK"
        elif not continuation:
            reason = "NO_CONTINUATION"
        elif failed:
            reason = "FAILED_BREAKOUT"
        elif chase:
            reason = "CHASE_TOO_FAR"
        elif score < MIN_SCORE:
            reason = "SCORE_LOW"
        else:
            reason = "NOT_READY"

        return {
            "symbol": symbol, "score": round(score, 1), "ready": ready,
            "reason": reason, "entry": entry, "support": support,
            "tp1": tp1, "tp2": tp2, "atr": a, "bos": breakout,
            "pullback": pullback, "continuation": continuation,
            "signal_bar": signal_bar, "chase": chase, "candles": len(closed),
            "trend": up, "range_ok": range_ok, "raw_trades": len(raw),
        }
    except Exception as e:
        base["reason"] = "ERROR"
        base["error"] = str(e)[:180]
        return base


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
    print("📐 Trend → BOS → Pullback → Continuation → CLOSED CONFIRM")
    print("⏱ TIMEFRAME: 5m CLOSED CANDLES")
    print("🚫 EMA: OFF")
    print("🔐 AUTH: RAW HMAC + SERVER OFFSET")
    print(f"🔓 REAL ORDERS: {'ENABLED' if LIVE_TRADING else 'DISABLED'}")
    print(f"📦 ORDER_QTY: {ORDER_QTY}")
    print(f"🔎 FULL SCAN: {'ON' if FULL_SCAN else 'OFF'}")
    print(f"🕐 {now_text()}")

    tg(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"🔓 REAL ORDERS: {'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"
        f"📦 ORDER_QTY: {ORDER_QTY}\n"
        f"🔐 AUTH: RAW HMAC + SERVER OFFSET\n"
        f"🔎 FULL USDT SCAN: {'ON' if FULL_SCAN else 'OFF'}\n"
        f"📊 SCAN STARTING...\n"
        f"🕐 {now_text()}"
    )

    try:
        markets = get_usdt_markets()
        scan_markets = markets if FULL_SCAN else markets[: max(SCAN_LIMIT * 4, 30)]
        tg(f"📊 USDT MARKETS: {len(markets)}\n🔎 SCANNING: {len(scan_markets)} MARKETS")

        counters = {
            "TOTAL": len(scan_markets), "ENOUGH_CANDLES": 0, "TREND_OK": 0,
            "BOS_OK": 0, "PULLBACK_OK": 0, "CONTINUATION_OK": 0,
            "CONFIRM_OK": 0, "READY": 0, "ERROR": 0,
        }
        reasons = {}
        results = []

        def consume(r):
            reason = r.get("reason", "UNKNOWN")
            reasons[reason] = reasons.get(reason, 0) + 1
            if r.get("candles", 0) >= 30:
                counters["ENOUGH_CANDLES"] += 1
            if r.get("trend") or r.get("range_ok"):
                counters["TREND_OK"] += 1
            if r.get("bos"):
                counters["BOS_OK"] += 1
            if r.get("pullback"):
                counters["PULLBACK_OK"] += 1
            if r.get("continuation"):
                counters["CONTINUATION_OK"] += 1
            if r.get("signal_bar"):
                counters["CONFIRM_OK"] += 1
            if r.get("ready"):
                counters["READY"] += 1
                results.append(r)
            elif r.get("candles", 0) >= 30 and r.get("score", 0) >= 5:
                results.append(r)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(analyze, symbol_from_market(m), m): m for m in scan_markets}
            done = 0
            for fut in as_completed(futs):
                done += 1
                try:
                    r = fut.result()
                    consume(r)
                except Exception as e:
                    counters["ERROR"] += 1
                    reasons["THREAD_ERROR"] = reasons.get("THREAD_ERROR", 0) + 1
                    print("SCAN ERROR:", repr(e))
                if done % 100 == 0 or done == len(scan_markets):
                    print(f"SCAN PROGRESS: {done}/{len(scan_markets)}")

        results.sort(key=lambda x: (x.get("ready", False), x.get("score", 0), x.get("signal_bar", False)), reverse=True)
        ready = [r for r in results if r.get("ready")]

        diag = (
            f"📊 ATI SCAN DIAGNOSTIC {VERSION}\n\n"
            f"🌐 TOTAL MARKETS: {len(markets)}\n"
            f"🔎 SCANNED: {len(scan_markets)}\n"
            f"🕯 ENOUGH CANDLES: {counters['ENOUGH_CANDLES']}\n"
            f"📈 TREND/RANGE OK: {counters['TREND_OK']}\n"
            f"🚀 BOS OK: {counters['BOS_OK']}\n"
            f"↩️ PULLBACK OK: {counters['PULLBACK_OK']}\n"
            f"➡️ CONTINUATION OK: {counters['CONTINUATION_OK']}\n"
            f"✅ CLOSED CONFIRM: {counters['CONFIRM_OK']}\n"
            f"🎯 BUY READY: {counters['READY']}\n\n"
            f"❌ NO_BOS: {reasons.get('NO_BOS', 0)}\n"
            f"❌ NO_PULLBACK: {reasons.get('NO_PULLBACK', 0)}\n"
            f"❌ NO_CONTINUATION: {reasons.get('NO_CONTINUATION', 0)}\n"
            f"❌ SCORE_LOW: {reasons.get('SCORE_LOW', 0)}\n"
            f"❌ CHASE_TOO_FAR: {reasons.get('CHASE_TOO_FAR', 0)}\n"
            f"⚠️ ERRORS: {reasons.get('ERROR', 0)}\n"
            f"🕐 {now_text()}"
        )
        print(diag)
        tg(diag)

        if not ready:
            watch = sorted(results, key=lambda x: x.get("score", 0), reverse=True)[:10]
            lines = ["👀 TOP WATCHLIST — NO BUY YET"]
            for s in watch:
                lines.append(f"{s['symbol']} | score {s['score']:.1f} | {s.get('reason','?')}")
            tg("\n".join(lines) if watch else "⏳ NO BUY\nNo market reached the current entry conditions.")
            return

        top = ready[:SCAN_LIMIT]
        lines = [f"🔥 ATI BUY CANDIDATES {VERSION}", f"🎯 READY: {len(ready)}"]
        for s in top:
            lines.append(
                f"🟢 {s['symbol']} | SCORE {s['score']:.1f} | "
                f"ENTRY {s['entry']:.8g} | SL {s['support']:.8g}"
            )
        tg("\n".join(lines))

        signal = top[0]
        market = next((m for m in markets if symbol_from_market(m) == signal["symbol"]), None)
        tg(
            f"🔥 BUY READY\n\n🪙 {signal['symbol']}\n"
            f"📊 SCORE: {signal['score']}\n"
            f"💵 ENTRY~: {signal['entry']:.8g}\n"
            f"🛡 SL: {signal['support']:.8g}\n"
            f"🎯 TP1: {signal['tp1']:.8g}\n🎯 TP2: {signal['tp2']:.8g}"
        )

        if not LIVE_TRADING:
            tg("🔒 REAL BUY NOT SENT\nLIVE_TRADING=false")
            return

        if market is None:
            raise RuntimeError("Selected market metadata not found")
        tg("🔐 AUTH CHECK BEFORE REAL BUY...")
        account = auth_test()
        free_usdt = balance(account, "USDT")
        tg(f"✅ AUTH SUCCESS\n🔓 canTrade=True\n💰 USDT FREE: {free_usdt}\n🚀 Sending ONE REAL BUY...")
        order = place_real_buy(signal, market, account)
        print(json.dumps(order, ensure_ascii=False, indent=2))
        tg(format_order(order))

    except Exception as e:
        msg = str(e)
        print("FATAL:", repr(e))
        tg(f"🚨 ATI ERROR {VERSION}\n\n❌ {msg[:1800]}\n\n🛑 NO FURTHER ORDER THIS RUN")
        raise


if __name__ == "__main__":
    main()
