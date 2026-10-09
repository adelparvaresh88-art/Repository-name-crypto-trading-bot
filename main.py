import os
import time
import math
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from tabdeal.future import Future
from tabdeal.enums import OrderSides, OrderTypes


# ============================================================
# ATI FUTURES V12
# TABDEAL OFFICIAL FUTURES SDK
# ============================================================

VERSION = "ATI FUTURES V12"

API_KEY = os.getenv("TABDIL_API_KEY") or os.getenv("TABDEAL_API_KEY")
API_SECRET = os.getenv("TABDIL_API_SECRET") or os.getenv("TABDEAL_API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ORDER_USDT = float(os.getenv("ORDER_QTY", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

# IMPORTANT:
# First test with REAL=False.
REAL = os.getenv("LIVE_TRADING", "false").lower() == "true"

MAX_MARKETS = int(os.getenv("SCAN_UNIVERSE", "75"))
WORKERS = int(os.getenv("WORKERS", "12"))

MIN_DEPTH = 5
DEPTH_LIMIT = 20

REQUEST_TIMEOUT = 8


# ============================================================
# TELEGRAM
# ============================================================

def telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(text)
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
            },
            timeout=10,
        )

    except Exception as e:
        print("Telegram error:", e)


# ============================================================
# FUTURES CLIENT
# ============================================================

def create_client():
    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDIL_API_KEY / TABDIL_API_SECRET are missing."
        )

    return Future(
        api_key=API_KEY,
        api_secret=API_SECRET,
        timeout=REQUEST_TIMEOUT,
        receive_window=5000,
    )


# ============================================================
# SAFE JSON HELPERS
# ============================================================

def as_list(value):
    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    return []


def as_dict(value):
    if isinstance(value, dict):
        return value

    return {}


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_markets(client):

    data = client.exchange_info()

    print("EXCHANGE INFO TYPE:", type(data).__name__)

    # Official API may return list or dict depending on server version.
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):

        raw = (
            data.get("symbols")
            or data.get("data")
            or data.get("result")
            or []
        )

        if isinstance(raw, dict):
            raw = (
                raw.get("symbols")
                or raw.get("data")
                or []
            )

    else:
        raw = []

    markets = []

    for item in raw:

        if not isinstance(item, dict):
            continue

        symbol = str(
            item.get("symbol")
            or item.get("s")
            or ""
        ).upper()

        if not symbol:
            continue

        # Only USDT contracts
        if not symbol.endswith("USDT"):
            continue

        status = str(
            item.get("status")
            or item.get("contractStatus")
            or ""
        ).upper()

        # Ignore obviously inactive contracts.
        if status and status not in (
            "TRADING",
            "1",
            "ACTIVE",
            "OPEN",
        ):
            continue

        markets.append(item)

    # Remove duplicates
    unique = {}

    for item in markets:
        symbol = str(item.get("symbol") or item.get("s"))
        unique[symbol] = item

    markets = list(unique.values())

    # Keep the most useful number of markets
    markets = markets[:MAX_MARKETS]

    return markets


# ============================================================
# DEPTH ANALYSIS
# ============================================================

def parse_depth(data):

    if not isinstance(data, dict):
        return None

    bids = data.get("bids") or data.get("Bids") or []
    asks = data.get("asks") or data.get("Asks") or []

    if not bids or not asks:
        return None

    parsed_bids = []
    parsed_asks = []

    for x in bids:

        try:
            if isinstance(x, dict):
                price = float(x.get("price") or x.get("p"))
                qty = float(x.get("quantity") or x.get("q"))
            else:
                price = float(x[0])
                qty = float(x[1])

            parsed_bids.append((price, qty))

        except Exception:
            continue

    for x in asks:

        try:
            if isinstance(x, dict):
                price = float(x.get("price") or x.get("p"))
                qty = float(x.get("quantity") or x.get("q"))
            else:
                price = float(x[0])
                qty = float(x[1])

            parsed_asks.append((price, qty))

        except Exception:
            continue

    if not parsed_bids or not parsed_asks:
        return None

    parsed_bids.sort(reverse=True)
    parsed_asks.sort()

    best_bid = parsed_bids[0][0]
    best_ask = parsed_asks[0][0]

    bid_volume = sum(q for _, q in parsed_bids[:DEPTH_LIMIT])
    ask_volume = sum(q for _, q in parsed_asks[:DEPTH_LIMIT])

    if ask_volume <= 0:
        imbalance = 0
    else:
        imbalance = bid_volume / ask_volume

    mid = (best_bid + best_ask) / 2

    spread = 0

    if mid > 0:
        spread = ((best_ask - best_bid) / mid) * 100

    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "bid_volume": bid_volume,
        "ask_volume": ask_volume,
        "imbalance": imbalance,
        "spread": spread,
    }


# ============================================================
# MARKET SCAN
# ============================================================

def scan_symbol(symbol):

    client = create_client()

    try:

        depth = client.depth(
            symbol=symbol,
            limit=DEPTH_LIMIT,
        )

        parsed = parse_depth(depth)

        if not parsed:
            return {
                "symbol": symbol,
                "ready": False,
                "signal": None,
                "error": "invalid depth",
            }

        imbalance = parsed["imbalance"]

        signal = None
        score = 0

        # ----------------------------------------------------
        # BUY
        # ----------------------------------------------------

        if imbalance >= 1.35:

            signal = "BUY"

            if imbalance >= 1.50:
                score += 2
            else:
                score += 1

        # ----------------------------------------------------
        # SELL
        # ----------------------------------------------------

        elif imbalance <= 0.74:

            signal = "SELL"

            if imbalance <= 0.67:
                score += 2
            else:
                score += 1

        return {
            "symbol": symbol,
            "ready": True,
            "signal": signal,
            "score": score,
            **parsed,
        }

    except Exception as e:

        return {
            "symbol": symbol,
            "ready": False,
            "signal": None,
            "error": str(e)[:250],
        }


# ============================================================
# ORDER QUANTITY
# ============================================================

def calculate_quantity(price):

    if price <= 0:
        return 0

    qty = ORDER_USDT / price

    return qty


# ============================================================
# REAL FUTURES ORDER
# ============================================================

def execute_order(signal):

    if not REAL:
        return "TEST MODE"

    if not API_KEY or not API_SECRET:
        return "API credentials missing"

    symbol = signal["symbol"]
    price = signal["mid"]

    quantity = calculate_quantity(price)

    if quantity <= 0:
        return "invalid quantity"

    client = create_client()

    try:

        # Set leverage
        client.change_leverage(
            symbol=symbol,
            leverage=LEVERAGE,
        )

        if signal["signal"] == "BUY":
            side = OrderSides.BUY
        else:
            side = OrderSides.SELL

        result = client.new_order(
            symbol=symbol,
            side=side,
            type=OrderTypes.MARKET,
            quantity=str(quantity),
        )

        return str(result)

    except Exception as e:
        return f"ORDER ERROR: {e}"


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    telegram(
        f"💓 {VERSION}\n"
        f"⚡ OFFICIAL TABDEAL FUTURES API\n"
        f"📊 DEPTH SCANNER\n"
        f"⚙️ LEVERAGE: {LEVERAGE}x\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"🔒 REAL: {REAL}"
    )

    print("=" * 60)
    print(VERSION)
    print("=" * 60)

    try:

        client = create_client()

        # ----------------------------------------------------
        # TEST CONNECTION
        # ----------------------------------------------------

        try:
            ping = client.ping()
            print("PING:", ping)
        except Exception as e:
            print("PING ERROR:", e)

        # ----------------------------------------------------
        # MARKET DISCOVERY
        # ----------------------------------------------------

        try:
            markets = get_markets(client)

        except Exception as e:

            msg = (
                f"❌ {VERSION}\n\n"
                f"MARKET DISCOVERY FAILED\n\n"
                f"{str(e)[:700]}"
            )

            print(msg)
            telegram(msg)
            return

        if not markets:

            msg = (
                f"❌ {VERSION}\n\n"
                f"NO FUTURES MARKETS FOUND\n\n"
                f"ExchangeInfo returned no USDT contracts."
            )

            print(msg)
            telegram(msg)
            return

        symbols = []

        for m in markets:

            symbol = str(
                m.get("symbol")
                or m.get("s")
                or ""
            ).upper()

            if symbol:
                symbols.append(symbol)

        print("MARKETS:", len(symbols))

        # ----------------------------------------------------
        # PARALLEL SCAN
        # ----------------------------------------------------

        results = []

        with ThreadPoolExecutor(max_workers=WORKERS) as executor:

            futures = {
                executor.submit(scan_symbol, symbol): symbol
                for symbol in symbols
            }

            for future in as_completed(futures):

                try:
                    result = future.result()
                    results.append(result)

                except Exception as e:

                    symbol = futures[future]

                    results.append({
                        "symbol": symbol,
                        "ready": False,
                        "signal": None,
                        "error": str(e),
                    })

        # ----------------------------------------------------
        # STATS
        # ----------------------------------------------------

        ready = [
            r for r in results
            if r.get("ready")
        ]

        errors = [
            r for r in results
            if not r.get("ready")
        ]

        signals = [
            r for r in ready
            if r.get("signal")
        ]

        elapsed = time.time() - started

        # ----------------------------------------------------
        # SELECT BEST SIGNAL
        # ----------------------------------------------------

        best = None

        if signals:

            # Strongest imbalance
            best = max(
                signals,
                key=lambda x: (
                    x.get("score", 0),
                    abs(
                        math.log(
                            max(
                                x.get("imbalance", 1),
                                0.000001
                            )
                        )
                    )
                )
            )

        # ----------------------------------------------------
        # TELEGRAM RESULT
        # ----------------------------------------------------

        if best:

            text = (
                f"🔥 ATI FUTURES SIGNAL\n\n"
                f"💎 {best['symbol']}\n"
                f"📌 {best['signal']}\n"
                f"📊 SCORE: {best.get('score', 0)}\n"
                f"⚖️ IMBALANCE: {best.get('imbalance', 0):.3f}\n"
                f"💰 PRICE: {best.get('mid', 0):.8f}\n"
                f"📉 SPREAD: {best.get('spread', 0):.4f}%\n\n"
                f"Markets: {len(symbols)}\n"
                f"Ready: {len(ready)}\n"
                f"Signals: {len(signals)}\n"
                f"Errors: {len(errors)}\n"
                f"Scan: {elapsed:.2f}s\n\n"
                f"ORDER: {ORDER_USDT} USDT\n"
                f"LEVERAGE: {LEVERAGE}x\n"
                f"REAL: {REAL}"
            )

            print(text)

            if REAL:
                order_result = execute_order(best)

                text += (
                    f"\n\n🚀 ORDER RESULT:\n"
                    f"{order_result}"
                )

            telegram(text)

        else:

            sample_error = ""

            if errors:

                sample_error = (
                    "\n\n❌ ERROR SAMPLE:\n"
                    + "\n".join(
                        f"{r['symbol']}: {r.get('error', '')[:180]}"
                        for r in errors[:5]
                    )
                )

            text = (
                f"💓 {VERSION}\n\n"
                f"☁️ NO SIGNAL THIS CYCLE\n\n"
                f"Markets: {len(symbols)}\n"
                f"Ready: {len(ready)}\n"
                f"Signals: {len(signals)}\n"
                f"Errors: {len(errors)}\n"
                f"Scan: {elapsed:.2f}s\n\n"
                f"ORDER: {ORDER_USDT} USDT\n"
                f"LEVERAGE: {LEVERAGE}x\n"
                f"REAL: {REAL}"
                f"{sample_error}"
            )

            print(text)
            telegram(text)

    except Exception as e:

        error = traceback.format_exc()

        print(error)

        telegram(
            f"❌ {VERSION} ERROR\n\n"
            f"{str(e)[:1000]}"
        )


if __name__ == "__main__":
    main()
