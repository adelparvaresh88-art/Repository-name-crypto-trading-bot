import os
import time
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.57-REAL
# TABDEAL SPOT
# HMAC AUTH FIX
# ============================================================

VERSION = "V40.2.57-REAL"

BASE = "https://api1.tabdeal.org"
API_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 15
RECV_WINDOW = 5000

SCAN_UNIVERSE = 40
MIN_CANDLES = 30

# ============================================================
# ENV
# ============================================================

API_KEY = (
    os.getenv("TABDIL_API_KEY")
    or os.getenv("TABDEAL_API_KEY")
    or ""
).strip()

API_SECRET = (
    os.getenv("TABDIL_API_SECRET")
    or os.getenv("TABDIL_SECRET")
    or os.getenv("TABDEAL_API_SECRET")
    or os.getenv("TABDEAL_SECRET")
    or ""
).strip()

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "false").strip().lower() == "true"
)

ORDER_VALUE = Decimal(
    os.getenv("ORDER_QTY", "2")
)

session = requests.Session()

session.headers.update({
    "User-Agent": f"ATI-Crypto-Bot/{VERSION}",
    "Accept": "application/json",
})


SERVER_OFFSET_MS = 0


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    print(message, flush=True)

    if not TG_TOKEN or not TG_CHAT_ID:
        return

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{TG_TOKEN}/sendMessage"
        )

        requests.post(
            url,
            data={
                "chat_id": TG_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )

    except Exception as exc:

        print(
            f"TELEGRAM ERROR: {exc}",
            flush=True
        )


# ============================================================
# PUBLIC REQUEST
# ============================================================

def public_get(path, params=None):

    url = f"{BASE}{path}"

    response = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT,
    )

    if response.status_code >= 400:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:700]}"
        )

    return response.json()


# ============================================================
# SERVER TIME
# ============================================================

def sync_server_time():

    global SERVER_OFFSET_MS

    data = public_get(
        "/r/api/v1/time"
    )

    server_time = int(
        data["serverTime"]
    )

    local_time = int(
        time.time() * 1000
    )

    SERVER_OFFSET_MS = (
        server_time - local_time
    )

    return server_time


# ============================================================
# HMAC SIGNING
# ============================================================

def build_signed_params(extra=None):

    if not API_SECRET:

        raise RuntimeError(
            "API SECRET IS EMPTY"
        )

    timestamp = (
        int(time.time() * 1000)
        + SERVER_OFFSET_MS
    )

    params = {}

    if extra:

        for key, value in extra.items():

            if value is None:
                continue

            params[key] = str(value)

    params["timestamp"] = str(timestamp)
    params["recvWindow"] = str(RECV_WINDOW)

    # IMPORTANT:
    # Signature is generated ONLY from parameters
    # BEFORE adding signature itself.

    query_string = urlencode(
        params,
        doseq=True
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    signed = dict(params)
    signed["signature"] = signature

    return signed


# ============================================================
# SIGNED GET
# ============================================================

def signed_get(path, extra=None):

    params = build_signed_params(
        extra
    )

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    url = f"{BASE}{path}"

    response = session.get(
        url,
        params=params,
        headers=headers,
        timeout=TIMEOUT,
    )

    if response.status_code >= 400:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    return response.json()


# ============================================================
# SIGNED POST
# ============================================================

def signed_post(path, extra=None):

    params = build_signed_params(
        extra
    )

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type":
            "application/x-www-form-urlencoded",
    }

    url = f"{BASE}{path}"

    response = session.post(
        url,
        data=params,
        headers=headers,
        timeout=TIMEOUT,
    )

    if response.status_code >= 400:

        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    return response.json()


# ============================================================
# AUTH CHECK
# ============================================================

def auth_check():

    if not API_KEY:

        raise RuntimeError(
            "TABDIL_API_KEY is EMPTY"
        )

    if not API_SECRET:

        raise RuntimeError(
            "TABDIL_API_SECRET is EMPTY"
        )

    send_telegram(
        "🔐 AUTH TEST\n"
        "🔑 PAIR: TABDIL\n"
        f"🕐 {utc_now()}"
    )

    sync_server_time()

    account = signed_get(
        "/r/api/v1/account"
    )

    can_trade = bool(
        account.get("canTrade", False)
    )

    balances = account.get(
        "balances",
        []
    )

    usdt_free = Decimal("0")

    for balance in balances:

        if balance.get("asset") == "USDT":

            try:
                usdt_free = Decimal(
                    str(
                        balance.get(
                            "free",
                            "0"
                        )
                    )
                )
            except Exception:
                usdt_free = Decimal("0")

            break

    send_telegram(
        "✅ AUTH SUCCESS\n"
        "🔑 PAIR: TABDIL\n"
        f"🔓 canTrade={can_trade}\n"
        f"💰 USDT FREE: {usdt_free}\n"
        f"⏱ SERVER OFFSET: "
        f"{SERVER_OFFSET_MS} ms"
    )

    return can_trade, usdt_free


# ============================================================
# MARKETS
# ============================================================

def get_markets():

    data = public_get(
        "/r/api/v1/exchangeInfo"
    )

    if isinstance(data, dict):

        markets = (
            data.get("symbols")
            or data.get("data")
            or []
        )

    else:

        markets = data

    result = []

    for market in markets:

        if not isinstance(
            market,
            dict
        ):
            continue

        symbol = market.get(
            "symbol"
        )

        if not symbol:
            continue

        if market.get(
            "status"
        ) != "TRADING":
            continue

        if market.get(
            "quoteAsset"
        ) != "USDT":
            continue

        result.append(
            market
        )

    return result


# ============================================================
# KLINES
# ============================================================

def get_klines(
    symbol,
    limit=40
):

    data = public_get(
        "/r/api/v1/klines",
        {
            "symbol": symbol,
            "interval": "5m",
            "limit": limit,
        },
    )

    if not isinstance(
        data,
        list
    ):
        return []

    candles = []

    for row in data:

        if len(row) < 6:
            continue

        candles.append({

            "open":
                Decimal(str(row[1])),

            "high":
                Decimal(str(row[2])),

            "low":
                Decimal(str(row[3])),

            "close":
                Decimal(str(row[4])),

            "volume":
                Decimal(str(row[5])),

            "time":
                int(row[0]),
        })

    return candles


# ============================================================
# FILTERS
# ============================================================

def get_filters(market):

    result = {

        "minQty":
            Decimal("0"),

        "stepSize":
            Decimal("0"),

        "minNotional":
            Decimal("0"),
    }

    for f in market.get(
        "filters",
        []
    ):

        filter_type = f.get(
            "filterType"
        )

        if filter_type in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE",
        ):

            min_qty = Decimal(
                str(
                    f.get(
                        "minQty",
                        "0"
                    )
                )
            )

            step = Decimal(
                str(
                    f.get(
                        "stepSize",
                        "0"
                    )
                )
            )

            if min_qty > result["minQty"]:
                result["minQty"] = min_qty

            if step > 0:
                result["stepSize"] = step

        elif filter_type == "MIN_NOTIONAL":

            result["minNotional"] = Decimal(
                str(
                    f.get(
                        "minNotional",
                        "0"
                    )
                )
            )

    return result


def round_quantity(
    quantity,
    step
):

    if step <= 0:
        return quantity

    return (
        quantity / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


# ============================================================
# PRICE ACTION
# ============================================================

def find_signal(candles):

    if len(candles) < MIN_CANDLES:

        return None

    # Last candle may still be open.
    # Therefore remove it.
    closed = candles[:-1]

    if len(closed) < 15:
        return None

    current = closed[-1]
    previous = closed[-2]

    previous_range = closed[-10:-3]

    if not previous_range:
        return None

    previous_high = max(
        x["high"]
        for x in previous_range
    )

    bos = (
        current["close"]
        > previous_high
    )

    pullback = (
        previous["low"]
        <= previous_high
        * Decimal("1.008")
    )

    bullish = (
        current["close"]
        > current["open"]
    )

    candle_range = (
        current["high"]
        - current["low"]
    )

    if candle_range <= 0:
        return None

    close_position = (
        current["close"]
        - current["low"]
    ) / candle_range

    strong_close = (
        close_position
        >= Decimal("0.55")
    )

    continuation = (
        current["close"]
        > previous["close"]
    )

    if not (
        bos
        and pullback
        and bullish
        and strong_close
        and continuation
    ):
        return None

    entry = current["close"]

    recent_low = min(
        x["low"]
        for x in closed[-5:]
    )

    sl = (
        recent_low
        * Decimal("0.997")
    )

    risk = (
        entry - sl
    )

    if risk <= 0:
        return None

    tp1 = (
        entry
        + risk * Decimal("1.5")
    )

    tp2 = (
        entry
        + risk * Decimal("2.5")
    )

    pressure = (
        (
            current["close"]
            - current["open"]
        )
        / candle_range
    ) * Decimal("100")

    return {

        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "pressure": pressure,
    }


# ============================================================
# REAL BUY
# ============================================================

def place_real_buy(
    market,
    signal
):

    symbol = market["symbol"]

    filters = get_filters(
        market
    )

    entry = signal["entry"]

    if entry <= 0:
        raise RuntimeError(
            "Invalid entry price"
        )

    quantity = (
        ORDER_VALUE
        / entry
    )

    quantity = round_quantity(
        quantity,
        filters["stepSize"]
    )

    if quantity <= 0:

        raise RuntimeError(
            f"{symbol}: quantity became zero"
        )

    if quantity < filters["minQty"]:

        raise RuntimeError(
            f"{symbol}: quantity "
            f"{quantity} < minQty "
            f"{filters['minQty']}"
        )

    notional = (
        quantity * entry
    )

    if (
        filters["minNotional"] > 0
        and
        notional < filters["minNotional"]
    ):

        raise RuntimeError(
            f"{symbol}: notional "
            f"{notional} < minNotional "
            f"{filters['minNotional']}"
        )

    send_telegram(
        "🟠 REAL BUY PREPARED\n"
        f"💎 {symbol}\n"
        f"💵 VALUE: {ORDER_VALUE} USDT\n"
        f"📦 QTY: {quantity}\n"
        f"💰 PRICE: {entry}"
    )

    order = signed_post(
        "/api/v1/order",
        {
            "symbol":
                symbol,

            "side":
                "BUY",

            "type":
                "MARKET",

            "quantity":
                format(
                    quantity,
                    "f"
                ),
        },
    )

    return order, quantity


# ============================================================
# MAIN
# ============================================================

def main():

    send_telegram(
        f"⚡ ATI BOT {VERSION}\n"
        "🧠 BOS → PULLBACK → CLOSED CONFIRM\n"
        "🚫 EMA: OFF\n"
        f"🔓 REAL TRADING: "
        f"{'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"
        f"💵 ORDER VALUE: "
        f"{ORDER_VALUE} USDT\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    try:

        can_trade, usdt = auth_check()

    except Exception as exc:

        send_telegram(
            f"🚨 ATI AUTH FAILED "
            f"{VERSION}\n\n"
            f"❌ {exc}\n\n"
            "🛑 NO ORDER THIS RUN"
        )

        return

    if not can_trade:

        send_telegram(
            "🛑 TABDEAL API:\n"
            "canTrade=false\n\n"
            "NO REAL ORDER"
        )

        return

    # --------------------------------------------------------
    # MARKET SCAN
    # --------------------------------------------------------

    send_telegram(
        "🔎 SCAN STARTING\n"
        f"📊 MAX MARKETS: "
        f"{SCAN_UNIVERSE}\n"
        "⏱ TIMEFRAME: 5m\n"
        "🕯 CLOSED CANDLES ONLY"
    )

    try:

        markets = get_markets()

    except Exception as exc:

        send_telegram(
            "🚨 MARKET ERROR\n"
            f"❌ {exc}"
        )

        return

    markets = markets[
        :SCAN_UNIVERSE
    ]

    candidates = []

    for market in markets:

        try:

            symbol = market[
                "symbol"
            ]

            candles = get_klines(
                symbol,
                40
            )

            result = find_signal(
                candles
            )

            if result:

                candidates.append(
                    (
                        market,
                        result
                    )
                )

        except Exception:
            continue

    # --------------------------------------------------------
    # NO SIGNAL
    # --------------------------------------------------------

    if not candidates:

        send_telegram(
            "💓 ATI RUN ALIVE\n"
            "📡 SCAN FINISHED\n"
            "👀 NO BUY\n"
            f"🕐 {utc_now()}"
        )

        return

    # Strongest pressure first.
    candidates.sort(
        key=lambda item:
            item[1]["pressure"],
        reverse=True
    )

    market, signal = candidates[0]

    symbol = market[
        "symbol"
    ]

    signal_message = (
        "🚨 BUY CANDIDATE\n"
        f"💎 {symbol}\n"
        f"💵 ENTRY: "
        f"{signal['entry']}\n"
        f"🛑 SL: "
        f"{signal['sl']}\n"
        f"🎯 TP1: "
        f"{signal['tp1']}\n"
        f"🎯 TP2: "
        f"{signal['tp2']}\n"
        f"💪 PRESSURE: "
        f"{signal['pressure']:.2f}%"
    )

    # --------------------------------------------------------
    # PAPER
    # --------------------------------------------------------

    if not LIVE_TRADING:

        send_telegram(
            signal_message
            + "\n\n"
            "🟡 PAPER MODE\n"
            "LIVE_TRADING=false"
        )

        return

    # --------------------------------------------------------
    # REAL BUY
    # --------------------------------------------------------

    try:

        order, quantity = place_real_buy(
            market,
            signal
        )

        order_id = (
            order.get("orderId")
            or order.get("id")
            or "N/A"
        )

        status = order.get(
            "status",
            "N/A"
        )

        send_telegram(
            signal_message
            + "\n\n"
            "🟢 REAL BUY SUCCESS\n"
            f"📦 QTY: {quantity}\n"
            f"🆔 ORDER ID: {order_id}\n"
            f"📌 STATUS: {status}"
        )

    except Exception as exc:

        send_telegram(
            f"🚨 REAL BUY FAILED\n"
            f"💎 {symbol}\n"
            f"❌ {exc}\n"
            "🛑 NO RETRY THIS RUN"
        )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        send_telegram(
            f"🚨 ATI FATAL ERROR\n"
            f"⚡ {VERSION}\n"
            f"❌ {type(exc).__name__}: {exc}"
        )
