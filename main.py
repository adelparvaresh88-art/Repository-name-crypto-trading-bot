import os
import time
import hmac
import hashlib
import math
import json
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

VERSION = "ATI FUTURES V3.1"
BASE_URL = os.getenv("TABDEAL_BASE_URL", "https://api1.tabdeal.org").rstrip("/")
API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()

REAL_TRADING = os.getenv("REAL_TRADING", "false").strip().lower() == "true"
LEVERAGE = int(os.getenv("LEVERAGE", "3"))
MARGIN_USDT = float(os.getenv("MARGIN_USDT", "2"))
TP_PCT = float(os.getenv("TP_PCT", "0.02"))
SL_PCT = float(os.getenv("SL_PCT", "0.01"))
MAX_SYMBOLS = max(1, min(int(os.getenv("MAX_SYMBOLS", "30")), 75))

FAST, SLOW, SIGNAL = 12, 26, 9
TIMEOUT = 15
KLINE_ROUTE = None
SESSION = requests.Session()


def log(message):
    print(
        f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] {message}",
        flush=True,
    )


def telegram(message):
    if not TG_TOKEN or not TG_CHAT:
        log("Telegram credentials missing")
        return False
    try:
        response = SESSION.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": str(message)[:4000]},
            timeout=TIMEOUT,
        )
        if not response.ok:
            log(f"TELEGRAM ERROR {response.status_code}: {response.text[:300]}")
            return False
        return True
    except Exception as exc:
        log(f"TELEGRAM ERROR: {exc}")
        return False


def public_get(path, params=None):
    response = SESSION.get(
        BASE_URL + path,
        params=params or {},
        timeout=TIMEOUT,
    )
    if not response.ok:
        raise RuntimeError(
            f"GET {response.url} -> HTTP {response.status_code}: {response.text[:300]}"
        )
    return response.json()


def signed_request(method, path, params=None):
    if not API_KEY or not API_SECRET:
        raise RuntimeError("Missing Tabdeal API credentials")

    values = dict(params or {})
    values["timestamp"] = int(time.time() * 1000)
    values["recvWindow"] = 10000

    query = urlencode(values)
    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()

    headers = {"X-MBX-APIKEY": API_KEY}
    url = BASE_URL + path

    if method.upper() == "GET":
        response = SESSION.get(
            url,
            params=query + "&signature=" + signature,
            headers=headers,
            timeout=TIMEOUT,
        )
    elif method.upper() == "POST":
        response = SESSION.post(
            url,
            data=query + "&signature=" + signature,
            headers={
                **headers,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=TIMEOUT,
        )
    elif method.upper() == "DELETE":
        response = SESSION.delete(
            url,
            params=query + "&signature=" + signature,
            headers=headers,
            timeout=TIMEOUT,
        )
    else:
        raise ValueError(f"Unsupported method: {method}")

    if not response.ok:
        raise RuntimeError(
            f"PRIVATE API HTTP {response.status_code}: {response.text[:400]}"
        )
    return response.json()


def discover_markets():
    data = public_get("/r/fapi/v1/exchangeInfo")
    items = data.get("symbols", []) if isinstance(data, dict) else []
    result = []

    for item in items:
        symbol = str(item.get("symbol", "")).upper()
        status = str(item.get("status", "")).upper()
        quote = str(item.get("quoteAsset") or item.get("quoteCurrency") or "").upper()

        if not symbol or not symbol.endswith("USDT"):
            continue
        if status and status != "TRADING":
            continue
        if quote and quote != "USDT":
            continue
        result.append(item)

    if not result:
        raise RuntimeError("No eligible USDT futures markets found")

    return result[:MAX_SYMBOLS]


def parse_candles(data):
    if not isinstance(data, list) or len(data) < 35:
        return None

    result = []
    for row in data:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            return None
        try:
            open_time = int(row[0])
            open_price = float(row[1])
            high = float(row[2])
            low = float(row[3])
            close = float(row[4])
            close_time = (
                int(row[6])
                if len(row) > 6
                else open_time + 300000 - 1
            )
            if min(open_price, high, low, close) <= 0:
                return None
            result.append({
                "time": open_time,
                "close_time": close_time,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
            })
        except (ValueError, TypeError, IndexError):
            return None

    return sorted(result, key=lambda item: item["time"])


def discover_kline_route(symbol):
    global KLINE_ROUTE
    routes = [
        "/r/fapi/v1/klines",
        "/fapi/v1/klines",
        "/r/api/v1/klines",
        "/api/v1/klines",
        "/r/fapi/v1/candles",
        "/fapi/v1/candles",
    ]

    for path in routes:
        try:
            data = public_get(
                path,
                {"symbol": symbol, "interval": "5m", "limit": 100},
            )
            candles = parse_candles(data)
            if candles:
                KLINE_ROUTE = path
                log(f"Verified candle route: {path}")
                return candles
            log(f"Invalid candle response from {path}")
        except Exception as exc:
            log(f"Candle route failed {path}: {exc}")

    return None


def get_candles(symbol):
    if not KLINE_ROUTE:
        return discover_kline_route(symbol)

    try:
        data = public_get(
            KLINE_ROUTE,
            {"symbol": symbol, "interval": "5m", "limit": 100},
        )
        return parse_candles(data)
    except Exception as exc:
        log(f"CANDLE ERROR {symbol}: {exc}")
        return None


def ema(values, period):
    if len(values) < period:
        return []
    alpha = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for value in values[period:]:
        result.append(result[-1] + alpha * (value - result[-1]))
    return result


def macd_cross(closes):
    if len(closes) < 60:
        return None

    fast = ema(closes, FAST)
    slow = ema(closes, SLOW)
    fast = fast[SLOW - FAST:]

    count = min(len(fast), len(slow))
    macd = [fast[i] - slow[i] for i in range(count)]
    signal = ema(macd, SIGNAL)
    aligned_macd = macd[SIGNAL - 1:]

    if len(signal) < 2 or len(aligned_macd) < 2:
        return None

    previous_macd, current_macd = aligned_macd[-2:]
    previous_signal, current_signal = signal[-2:]

    if previous_macd <= previous_signal and current_macd > current_signal:
        return "BUY"
    if previous_macd >= previous_signal and current_macd < current_signal:
        return "SELL"
    return None


def closed_candles(candles):
    now_ms = int(time.time() * 1000)
    return [c for c in candles if c["close_time"] < now_ms]


def get_filters(item):
    return {
        f.get("filterType"): f
        for f in item.get("filters", [])
        if f.get("filterType")
    }


def decimals_for_step(step):
    return max(0, -__import__("decimal").Decimal(str(step)).normalize().as_tuple().exponent)


def round_down_step(value, step):
    from decimal import Decimal, ROUND_DOWN
    value = Decimal(str(value))
    step = Decimal(str(step))
    if step <= 0:
        raise RuntimeError("Invalid exchange step")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def format_quantity(item, quantity):
    from decimal import Decimal

    filters = get_filters(item)
    lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE")
    if not lot:
        raise RuntimeError(f"{item.get('symbol')}: quantity filters missing")

    step = Decimal(str(lot.get("stepSize", "0")))
    minimum = Decimal(str(lot.get("minQty", "0")))
    maximum = Decimal(str(lot.get("maxQty", "0")))

    if step <= 0:
        raise RuntimeError("Invalid quantity stepSize")

    qty = round_down_step(quantity, step)
    if qty < minimum:
        raise RuntimeError(f"Quantity {qty} below minimum {minimum}")
    if maximum > 0 and qty > maximum:
        raise RuntimeError(f"Quantity {qty} above maximum {maximum}")

    return f"{qty:.{decimals_for_step(step)}f}"


def format_price(item, price):
    from decimal import Decimal

    price_filter = get_filters(item).get("PRICE_FILTER")
    if not price_filter:
        raise RuntimeError(f"{item.get('symbol')}: PRICE_FILTER missing")

    tick = Decimal(str(price_filter.get("tickSize", "0")))
    if tick <= 0:
        raise RuntimeError("Invalid tickSize")

    value = round_down_step(price, tick)
    return f"{value:.{decimals_for_step(tick)}f}"


def get_mid_price(symbol):
    data = public_get(
        "/r/fapi/v1/depth",
        {"symbol": symbol, "limit": 5},
    )
    bids = data.get("bids") or []
    asks = data.get("asks") or []

    if not bids or not asks:
        raise RuntimeError("Order book is empty")

    bid, ask = float(bids[0][0]), float(asks[0][0])
    if bid <= 0 or ask <= 0 or ask < bid:
        raise RuntimeError("Invalid order book prices")
    return (bid + ask) / 2


def get_position(symbol):
    errors = []

    for path in ("/fapi/v1/positionRisk", "/fapi/v1/position"):
        try:
            data = signed_request("GET", path, {"symbol": symbol})
            positions = data if isinstance(data, list) else [data]

            for position in positions:
                if not isinstance(position, dict):
                    continue
                found_symbol = str(position.get("symbol", symbol)).upper()
                if found_symbol != symbol:
                    continue
                amount = float(
                    position.get("positionAmt")
                    or position.get("quantity")
                    or position.get("qty")
                    or 0
                )
                if abs(amount) > 0:
                    return position

            if isinstance(data, list):
                return None

            if isinstance(data, dict) and any(
                key in data for key in ("positionAmt", "quantity", "qty")
            ):
                return None

            errors.append(f"{path}: unexpected response")

        except Exception as exc:
            errors.append(f"{path}: {exc}")

    raise RuntimeError("Could not verify position: " + " | ".join(errors))


def set_leverage(symbol):
    return signed_request(
        "POST",
        "/fapi/v1/leverage",
        {"symbol": symbol, "leverage": LEVERAGE},
    )


def market_order(symbol, side, quantity):
    return signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        },
    )


def protective_order(symbol, side, order_type, quantity, stop_price):
    return signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
            "stopPrice": stop_price,
            "reduceOnly": "true",
            "workingType": "MARK_PRICE",
        },
    )


def save_record(record):
    path = "ati_futures_state.json"
    state = {}

    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as file:
                loaded = json.load(file)
                if isinstance(loaded, dict):
                    state = loaded
    except Exception as exc:
        log(f"State read error: {exc}")

    state.update(record)

    try:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)
    except Exception as exc:
        log(f"State write error: {exc}")


def execute_trade(item, signal, price, candle_time):
    symbol = str(item.get("symbol", "")).upper()

    if not REAL_TRADING:
        telegram(
            f"🟡 ATI PAPER SIGNAL\n\n"
            f"Symbol: {symbol}\nSignal: {signal}\n"
            f"Price: {price}\nMACD: 12/26/9\nTimeframe: 5m"
        )
        return

    if not API_KEY or not API_SECRET:
        raise RuntimeError("Missing API credentials")

    # Abort if position status cannot be verified.
    if get_position(symbol):
        log(f"{symbol}: existing position; skip")
        return

    quantity = format_quantity(
        item,
        MARGIN_USDT * LEVERAGE / price,
    )

    set_leverage(symbol)

    side = "BUY" if signal == "BUY" else "SELL"
    exit_side = "SELL" if side == "BUY" else "BUY"

    order = market_order(symbol, side, quantity)
    if not isinstance(order, dict):
        raise RuntimeError("Unexpected market order response")

    order_id = order.get("orderId")
    fill_price = float(
        order.get("avgPrice")
        or order.get("averagePrice")
        or order.get("price")
        or price
    )
    if fill_price <= 0:
        raise RuntimeError("Invalid order fill price")

    tp_price = fill_price * (1 + TP_PCT if side == "BUY" else 1 - TP_PCT)
    sl_price = fill_price * (1 - SL_PCT if side == "BUY" else 1 + SL_PCT)

    try:
        tp_order = protective_order(
            symbol,
            exit_side,
            "TAKE_PROFIT_MARKET",
            quantity,
            format_price(item, tp_price),
        )
        sl_order = protective_order(
            symbol,
            exit_side,
            "STOP_MARKET",
            quantity,
            format_price(item, sl_price),
        )
    except Exception as exc:
        log(f"PROTECTIVE ORDER FAILURE {symbol}: {exc}")
        telegram(
            f"🚨 PROTECTIVE ORDER FAILURE\n"
            f"Symbol: {symbol}\nEntry order ID: {order_id}\n"
            f"Error: {exc}\nCheck the position immediately."
        )
        raise

    save_record({
        "last_trade": {
            "symbol": symbol,
            "side": signal,
            "quantity": quantity,
            "entry": fill_price,
            "order_id": order_id,
            "tp_order_id": tp_order.get("orderId"),
            "sl_order_id": sl_order.get("orderId"),
            "candle_time": candle_time,
            "time": datetime.now(timezone.utc).isoformat(),
        }
    })

    telegram(
        f"🔴 ATI REAL TRADE\n\n"
        f"Symbol: {symbol}\nSide: {signal}\n"
        f"Entry: {fill_price}\nQuantity: {quantity}\n"
        f"Leverage: {LEVERAGE}x\n"
        f"Margin target: {MARGIN_USDT} USDT\n"
        f"TP: {format_price(item, tp_price)}\n"
        f"SL: {format_price(item, sl_price)}\n"
        f"Entry order ID: {order_id}\n"
        f"TP order ID: {tp_order.get('orderId')}\n"
        f"SL order ID: {sl_order.get('orderId')}"
    )


def analyze_market(item):
    symbol = str(item.get("symbol", "")).upper()
    candles = get_candles(symbol)

    if not candles:
        log(f"{symbol}: no valid candles")
        return

    closed = closed_candles(candles)
    if len(closed) < 60:
        log(f"{symbol}: only {len(closed)} closed candles")
        return

    signal = macd_cross([c["close"] for c in closed])
    if not signal:
        return

    latest = closed[-1]
    key = f"{symbol}:{latest['time']}:{signal}"

    # Skip a repeated signal from the same candle.
    try:
        with open("ati_futures_state.json", "r", encoding="utf-8") as file:
            state = json.load(file)
        if state.get("last_signal_key") == key:
            return
    except (OSError, ValueError):
        pass

    execute_trade(item, signal, latest["close"], latest["time"])
    save_record({"last_signal_key": key})


def main():
    log("=" * 55)
    log(VERSION)
    log(f"Mode: {'REAL' if REAL_TRADING else 'PAPER'}")
    log(f"MACD: {FAST}/{SLOW}/{SIGNAL}")
    log(f"Timeframe: 5m | Leverage: {LEVERAGE}x")
    log(f"Margin: {MARGIN_USDT} USDT | TP: {TP_PCT} | SL: {SL_PCT}")

    telegram(
        f"🤖 {VERSION}\n"
        f"Mode: {'REAL' if REAL_TRADING else 'PAPER'}\n"
        f"MACD: 12/26/9\nTimeframe: 5m\n"
        f"Leverage: {LEVERAGE}x\nMargin: {MARGIN_USDT} USDT"
    )

    markets = discover_markets()
    log(f"Markets found: {len(markets)}")

    if not KLINE_ROUTE:
        for item in markets:
            symbol = str(item.get("symbol", "")).upper()
            if discover_kline_route(symbol):
                break

    if not KLINE_ROUTE:
        message = "🚨 No working candle endpoint found. No trades submitted."
        log(message)
        telegram(message)
        return

    processed = 0

    for item in markets:
        try:
            analyze_market(item)
            processed += 1
        except Exception as exc:
            log(f"MARKET ERROR {item.get('symbol')}: {exc}")

        time.sleep(0.2)

    log(f"Scan complete: {processed} markets processed")
    telegram(
        f"📊 ATI FUTURES SCAN COMPLETE\n"
        f"Markets: {len(markets)}\n"
        f"Processed: {processed}\n"
        f"Candle route: {KLINE_ROUTE}\n"
        f"Mode: {'REAL' if REAL_TRADING else 'PAPER'}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"FATAL ERROR: {exc}")
        telegram(f"🚨 {VERSION} FATAL ERROR\n{exc}")
        raise
