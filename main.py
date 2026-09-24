import os
import time
from datetime import datetime, timezone

import requests

VERSION = "V35.2"
BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"
CANDLE_LIMIT = 60
TOP_RESULTS = 2
MAX_MARKETS = 1000
MIN_SCORE = 4
MIN_MOVE_PERCENT = 0.20
REQUEST_TIMEOUT = 15
SCAN_DELAY = 0.03

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

session = requests.Session()
session.headers.update({"User-Agent": "ATI-Crypto-Bot/35.2"})


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM ERROR: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = session.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            print("TELEGRAM ERROR:", data)
            return False
        return True
    except Exception as e:
        print("TELEGRAM ERROR:", e)
        return False


def to_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_symbol(value):
    if value is None:
        return ""
    return str(value).upper().replace("/", "").replace("-", "").replace("_", "")


def api_get(path, params=None):
    url = BASE_URL + path
    r = session.get(url, params=params or {}, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def extract_market_list(data):
    # Tabdeal may return either a root list or a dict containing the list.
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []

    for key in ("symbols", "data", "result", "markets", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for subkey in ("symbols", "markets", "items", "data", "result"):
                subvalue = value.get(subkey)
                if isinstance(subvalue, list):
                    return subvalue
    return []


def get_exchange_info():
    paths = [
        "/r/api/v1/exchangeInfo",
        "/api/v1/exchangeInfo",
    ]
    last_error = None
    for path in paths:
        try:
            return api_get(path)
        except Exception as e:
            last_error = e
    raise RuntimeError(f"exchangeInfo failed: {last_error}")


def market_symbol(item):
    if isinstance(item, str):
        return clean_symbol(item)
    if not isinstance(item, dict):
        return ""
    for key in ("symbol", "s", "market", "pair", "name"):
        if key in item and item[key] is not None:
            return clean_symbol(item[key])
    return ""


def market_status(item):
    if not isinstance(item, dict):
        return ""
    for key in ("status", "state"):
        if key in item and item[key] is not None:
            return str(item[key]).upper()
    return ""


def is_usdt_market(item):
    symbol = market_symbol(item)
    if not symbol.endswith("USDT"):
        return False
    status = market_status(item)
    if status and status not in {"TRADING", "ENABLED", "ACTIVE", "ONLINE"}:
        return False
    return True


def get_usdt_markets():
    data = get_exchange_info()
    items = extract_market_list(data)
    markets = []
    seen = set()

    for item in items:
        if not is_usdt_market(item):
            continue
        symbol = market_symbol(item)
        if symbol and symbol not in seen:
            seen.add(symbol)
            markets.append(symbol)

    return markets[:MAX_MARKETS]


def extract_rows(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []

    for key in ("data", "result", "rows", "klines", "candles", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for subkey in ("data", "rows", "klines", "candles", "items"):
                subvalue = value.get(subkey)
                if isinstance(subvalue, list):
                    return subvalue
    return []


def get_klines(symbol):
    paths = [
        "/r/api/v1/klines",
        "/api/v1/klines",
        "/r/api/v1/candles",
    ]
    params_variants = [
        {"symbol": symbol, "interval": TIMEFRAME, "limit": CANDLE_LIMIT},
        {"symbol": symbol, "timeframe": TIMEFRAME, "limit": CANDLE_LIMIT},
    ]

    last_error = None
    for path in paths:
        for params in params_variants:
            try:
                data = api_get(path, params)
                rows = extract_rows(data)
                if rows:
                    return rows
            except Exception as e:
                last_error = e
    return []


def parse_candle(row):
    if isinstance(row, (list, tuple)):
        if len(row) < 6:
            return None
        return {
            "time": to_float(row[0]),
            "open": to_float(row[1]),
            "high": to_float(row[2]),
            "low": to_float(row[3]),
            "close": to_float(row[4]),
            "volume": to_float(row[5]),
        }

    if isinstance(row, dict):
        return {
            "time": to_float(row.get("openTime", row.get("time", row.get("timestamp", 0)))),
            "open": to_float(row.get("open", row.get("o"))),
            "high": to_float(row.get("high", row.get("h"))),
            "low": to_float(row.get("low", row.get("l"))),
            "close": to_float(row.get("close", row.get("c"))),
            "volume": to_float(row.get("volume", row.get("v"))),
        }
    return None


def clean_candles(rows):
    result = []
    for row in rows:
        candle = parse_candle(row)
        if not candle:
            continue
        if candle["open"] <= 0 or candle["high"] <= 0 or candle["low"] <= 0 or candle["close"] <= 0:
            continue
        result.append(candle)
    result.sort(key=lambda x: x["time"])
    return result


def average(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0


def pct_change(old, new):
    if old == 0:
        return 0.0
    return ((new - old) / old) * 100.0


def analyze_market(symbol, rows):
    candles = clean_candles(rows)
    if len(candles) < 25:
        return None

    # Always analyze a fully closed candle. The newest row can still be forming.
    closed = candles[:-1] if len(candles) >= 2 else candles
    if len(closed) < 24:
        return None

    c = closed[-1]
    prev = closed[-2]
    recent = closed[-6:]
    prior = closed[-12:-6]
    if len(prior) < 6:
        return None

    price = c["close"]
    previous_close = prev["close"]

    move = pct_change(previous_close, price)
    range_size = max(c["high"] - c["low"], 1e-12)
    body = abs(c["close"] - c["open"])
    body_ratio = body / range_size

    prior_high = max(x["high"] for x in closed[-13:-1])
    breakout = c["close"] > prior_high

    avg_volume = average(x["volume"] for x in closed[-21:-1])
    volume_expansion = avg_volume > 0 and c["volume"] >= avg_volume * 1.20

    rising_structure = all(recent[i]["close"] >= recent[i - 1]["close"] for i in range(1, len(recent)))
    recent_low = min(x["low"] for x in recent)
    recent_high = max(x["high"] for x in recent)
    structure_move = pct_change(recent_low, recent_high)

    close_near_high = c["close"] >= c["high"] - (range_size * 0.25)
    bullish_candle = c["close"] > c["open"]
    momentum = pct_change(closed[-4]["close"], price)

    score = 0
    reasons = []

    if breakout:
        score += 2
        reasons.append("BREAKOUT")
    if bullish_candle and body_ratio >= 0.45:
        score += 1
        reasons.append("STRONG BODY")
    if volume_expansion:
        score += 1
        reasons.append("VOLUME")
    if rising_structure:
        score += 1
        reasons.append("RISING STRUCTURE")
    if close_near_high:
        score += 1
        reasons.append("CLOSE NEAR HIGH")
    if momentum >= 0.20:
        score += 1
        reasons.append("MOMENTUM")
    if structure_move >= 0.25:
        score += 1
        reasons.append("UPWARD MOVE")
    if move >= MIN_MOVE_PERCENT:
        score += 1
        reasons.append("5M MOVE")

    if move < MIN_MOVE_PERCENT and not breakout:
        return None
    if not bullish_candle:
        return None
    if score < MIN_SCORE:
        return None

    # Conservative paper/test levels. No real order is sent by this version.
    entry = price
    sl = entry * 0.995
    tp = entry * 1.010

    return {
        "symbol": symbol,
        "price": price,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "score": score,
        "move": move,
        "momentum": momentum,
        "volume_ratio": (c["volume"] / avg_volume) if avg_volume > 0 else 0.0,
        "candle_time": c["time"],
        "reasons": reasons,
    }


def scan_symbol(symbol):
    try:
        rows = get_klines(symbol)
        if not rows:
            return None
        return analyze_market(symbol, rows)
    except Exception as e:
        print(f"SCAN ERROR {symbol}: {e}")
        return None


def fmt_price(value):
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:,.4f}"
    return f"{value:,.8f}".rstrip("0").rstrip(".")


def build_message(results, market_count, scan_time):
    lines = [
        f"⚡ ATI CRYPTO BOT {VERSION}",
        "🚀 UPWARD COIN SCANNER",
        f"⏱ Timeframe: {TIMEFRAME}",
        "✅ CLOSED CANDLE",
        "💥 BREAKOUT + MOMENTUM ENGINE",
        "",
        "📡 TABDEAL API: OK",
        f"📊 USDT MARKETS: {market_count}",
        f"🕐 Scan: {scan_time}",
        "",
    ]

    if not results:
        lines += [
            "⚪ NO STRONG UPWARD SETUP",
            "",
            "⏳ NO TRADE",
            "🛡 REAL TRADING: DISABLED",
        ]
        return "\n".join(lines)

    lines += [f"🔥 TOP {len(results)} UPWARD OPPORTUNITIES", ""]

    for i, r in enumerate(results, 1):
        lines += [
            f"🟢 #{i} {r['symbol']}",
            f"💰 Price: ${fmt_price(r['price'])}",
            f"📈 SCORE: {r['score']}/9",
            f"🚀 MOVE: {r['move']:.3f}%",
            f"📊 MOMENTUM: {r['momentum']:.3f}%",
            f"🔊 VOL: {r['volume_ratio']:.2f}x",
            f"🎯 Entry: ${fmt_price(r['entry'])}",
            f"🛑 SL: ${fmt_price(r['sl'])}",
            f"✅ TP: ${fmt_price(r['tp'])}",
            "🔎 " + " + ".join(r["reasons"]),
            "",
        ]

    lines += [
        "📌 MODE: PAPER/TEST",
        "🛡 REAL TRADING: DISABLED",
    ]
    return "\n".join(lines)


def main():
    print(f"ATI CRYPTO BOT {VERSION}")
    print("Starting full USDT market scan...")

    try:
        markets = get_usdt_markets()
    except Exception as e:
        msg = f"⚡ ATI CRYPTO BOT {VERSION}\n\n❌ TABDEAL API ERROR\n{e}"
        print(msg)
        send_telegram(msg)
        return

    print(f"USDT markets: {len(markets)}")

    results = []
    total = len(markets)

    for index, symbol in enumerate(markets, 1):
        result = scan_symbol(symbol)
        if result:
            results.append(result)
            results.sort(key=lambda x: (x["score"], x["momentum"], x["move"]), reverse=True)
            results = results[:TOP_RESULTS]
        if index % 50 == 0 or index == total:
            print(f"Scanned {index}/{total}")
        time.sleep(SCAN_DELAY)

    scan_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = build_message(results, len(markets), scan_time)
    print(message)
    send_telegram(message)


if __name__ == "__main__":
    main()
