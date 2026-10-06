import os
import time
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests


VERSION = "V40.2.66-REAL-EXIT-FIX"

BASE = "https://api1.tabdeal.org"

PUBLIC_ROOT = BASE + "/r/api/v1"
TRADE_ROOT = BASE + "/api/v1"

ORDER_VALUE = Decimal(
    os.getenv("ORDER_QTY", "2")
)

LIVE_TRADING = os.getenv(
    "LIVE_TRADING",
    "false"
).lower() in (
    "1",
    "true",
    "yes",
    "on"
)

TP_PCT = Decimal("0.02")
SL_PCT = Decimal("0.01")

POLL_SECONDS = 10
MAX_HOLD_MINUTES = 300

SCAN_UNIVERSE = 25
MIN_CANDLES = 12
MIN_SCORE = 7

RECV_WINDOW = 5000

session = requests.Session()

server_offset_ms = 0


# =========================================================
# TIME
# =========================================================

def now_utc():
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def timestamp_ms():
    return (
        int(time.time() * 1000)
        + server_offset_ms
    )


# =========================================================
# TELEGRAM
# =========================================================

def telegram(msg):

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN",
        ""
    ).strip()

    chat = os.getenv(
        "TELEGRAM_CHAT_ID",
        ""
    ).strip()

    if not token or not chat:
        return

    try:

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat,
                "text": msg
            },
            timeout=15
        )

    except Exception:
        pass


# =========================================================
# PUBLIC API
# =========================================================

def public_get(
    path,
    params=None
):

    r = session.get(
        PUBLIC_ROOT + path,
        params=params or {},
        timeout=20
    )

    r.raise_for_status()

    return r.json()


# =========================================================
# SERVER TIME
# =========================================================

def sync_time():

    global server_offset_ms

    data = public_get(
        "/time"
    )

    server_ms = int(
        data.get(
            "serverTime",
            int(time.time() * 1000)
        )
    )

    server_offset_ms = (
        server_ms
        - int(time.time() * 1000)
    )


# =========================================================
# API CREDENTIALS
# =========================================================

def credentials():

    key = (
        os.getenv("TABDIL_API_KEY")
        or
        os.getenv("TABDEAL_API_KEY")
    )

    secret = (
        os.getenv("TABDIL_API_SECRET")
        or
        os.getenv("TABDEAL_API_SECRET")
    )

    if not key or not secret:

        raise RuntimeError(
            "API credentials missing"
        )

    return key, secret


# =========================================================
# SIGNED REQUEST
# =========================================================

def signed_request(
    method,
    path,
    params=None
):

    key, secret = credentials()

    p = dict(
        params or {}
    )

    p["timestamp"] = timestamp_ms()
    p["recvWindow"] = RECV_WINDOW

    query = urlencode(p)

    signature = hmac.new(
        secret.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "X-MBX-APIKEY": key
    }

    url = (
        TRADE_ROOT
        + path
        + "?"
        + query
        + "&signature="
        + signature
    )

    r = session.request(
        method,
        url,
        headers=headers,
        timeout=20
    )

    if r.status_code >= 400:

        raise RuntimeError(
            f"HTTP {r.status_code}: {r.text}"
        )

    return r.json()


# =========================================================
# AUTH
# =========================================================

def auth_check():

    account = signed_request(
        "GET",
        "/account"
    )

    if not account.get(
        "canTrade",
        False
    ):

        raise RuntimeError(
            "canTrade=False"
        )

    return account


# =========================================================
# BALANCES
# =========================================================

def balances(account):

    result = {}

    for b in account.get(
        "balances",
        []
    ):

        try:

            result[
                b["asset"]
            ] = Decimal(
                str(
                    b.get(
                        "free",
                        "0"
                    )
                )
            )

        except Exception:
            pass

    return result


# =========================================================
# EXCHANGE INFO
# =========================================================

def exchange_info():

    data = public_get(
        "/exchangeInfo"
    )

    # حالت 1:
    # پاسخ مستقیماً یک لیست از مارکت‌هاست
    if isinstance(
        data,
        list
    ):

        return {
            "symbols": data
        }

    # حالت 2 و 3:
    # پاسخ به شکل dictionary است
    if isinstance(
        data,
        dict
    ):

        # فرمت استاندارد
        if isinstance(
            data.get("symbols"),
            list
        ):

            return data

        # بعضی پاسخ‌ها:
        # {"data": [...]}
        if isinstance(
            data.get("data"),
            list
        ):

            return {
                "symbols": data["data"]
            }

        # اگر symbols یا data نبود
        return data

    raise RuntimeError(
        "Unexpected exchangeInfo format: "
        f"{type(data).__name__}"
    )


# =========================================================
# SYMBOL INFO
# =========================================================

def symbol_info(
    info,
    symbol
):

    for s in info.get(
        "symbols",
        []
    ):

        if s.get(
            "symbol"
        ) == symbol:

            return s

    return None


# =========================================================
# FILTERS
# =========================================================

def filters_for(
    symbol_data
):

    return {
        f.get("filterType"): f
        for f in symbol_data.get(
            "filters",
            []
        )
    }


# =========================================================
# ROUND QUANTITY
# =========================================================

def round_qty(
    qty,
    step
):

    if step <= 0:
        return qty

    return (
        qty / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


# =========================================================
# MARKET BUY
# =========================================================

def market_buy(
    symbol,
    qty
):

    return signed_request(
        "POST",
        "/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": format(
                qty,
                "f"
            )
        }
    )


# =========================================================
# MARKET SELL
# =========================================================

def market_sell(
    symbol,
    qty
):

    return signed_request(
        "POST",
        "/order",
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": format(
                qty,
                "f"
            )
        }
    )


# =========================================================
# ORDER STATUS
# =========================================================

def order_status(
    symbol,
    order_id
):

    return signed_request(
        "GET",
        "/order",
        {
            "symbol": symbol,
            "orderId": order_id
        }
    )


# =========================================================
# CURRENT PRICE
# =========================================================

def price(
    symbol
):

    data = public_get(
        "/ticker/price",
        {
            "symbol": symbol
        }
    )

    return Decimal(
        str(
            data["price"]
        )
    )


# =========================================================
# MY TRADES
# =========================================================

def my_trades(
    symbol,
    limit=20
):

    return signed_request(
        "GET",
        "/myTrades",
        {
            "symbol": symbol,
            "limit": limit
        }
    )


# =========================================================
# FIND FILLED ENTRY
# =========================================================

def filled_entry(
    symbol
):

    try:

        trades = my_trades(
            symbol,
            50
        )

        buys = [
            t
            for t in trades
            if t.get(
                "isBuyer"
            ) is True
        ]

        if not buys:
            return None

        buys.sort(
            key=lambda x: int(
                x.get(
                    "time",
                    0
                )
            )
        )

        trade = buys[-1]

        return Decimal(
            str(
                trade["price"]
            )
        )

    except Exception:

        return None


# =========================================================
# FIND EXISTING POSITION
# =========================================================

def find_existing_position(
    info
):

    account = auth_check()

    balances_data = balances(
        account
    )

    candidates = []

    for asset, qty in balances_data.items():

        if asset == "USDT":
            continue

        if qty <= 0:
            continue

        symbol = (
            asset
            + "USDT"
        )

        symbol_data = symbol_info(
            info,
            symbol
        )

        if not symbol_data:
            continue

        if symbol_data.get(
            "status"
        ) != "TRADING":
            continue

        entry = filled_entry(
            symbol
        )

        if entry is None:
            continue

        try:

            current = price(
                symbol
            )

        except Exception:

            continue

        candidates.append(
            {
                "symbol": symbol,
                "quantity": qty,
                "entry_price": entry,
                "current_price": current
            }
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: x["quantity"],
        reverse=True
    )

    return candidates[0]


# =========================================================
# MANAGE POSITION
# =========================================================

def manage_position(
    position
):

    symbol = position[
        "symbol"
    ]

    quantity = position[
        "quantity"
    ]

    entry = position[
        "entry_price"
    ]

    tp = (
        entry
        * (
            Decimal("1")
            + TP_PCT
        )
    )

    sl = (
        entry
        * (
            Decimal("1")
            - SL_PCT
        )
    )

    start_time = time.time()

    telegram(
        "🚨 EXISTING POSITION DETECTED\n"
        f"🪙 {symbol}\n"
        f"📦 QTY: {quantity}\n"
        f"📥 ENTRY: {entry}\n"
        f"💵 CURRENT: "
        f"{position['current_price']}\n"
        f"🎯 TP: {tp}\n"
        f"🛑 SL: {sl}\n"
        "🔍 CHECKING TP / SL..."
    )

    while (
        time.time()
        - start_time
        < MAX_HOLD_MINUTES * 60
    ):

        try:

            current = price(
                symbol
            )

            # TP
            if current >= tp:

                reason = "TP HIT ✅"

            # SL
            elif current <= sl:

                reason = "SL HIT 🛑"

            else:

                time.sleep(
                    POLL_SECONDS
                )

                continue

            telegram(
                f"🚨 {reason}\n"
                f"🪙 {symbol}\n"
                f"💵 PRICE: {current}\n"
                f"📦 SELL QTY: {quantity}"
            )

            if not LIVE_TRADING:

                telegram(
                    "🔒 LIVE TRADING OFF\n"
                    "❌ NO SELL SENT"
                )

                return

            result = market_sell(
                symbol,
                quantity
            )

            order_id = result.get(
                "orderId"
            )

            telegram(
                "✅ SELL SENT\n"
                f"🪙 {symbol}\n"
                f"🆔 ORDER: {order_id}"
            )

            return

        except Exception as e:

            telegram(
                "⚠️ EXIT CHECK ERROR\n"
                f"🪙 {symbol}\n"
                f"❌ {e}"
            )

            time.sleep(
                POLL_SECONDS
            )

    try:

        final_price = price(
            symbol
        )

    except Exception:

        final_price = "UNKNOWN"

    telegram(
        "⏰ MAX HOLD REACHED\n"
        f"🪙 {symbol}\n"
        f"💵 CURRENT: {final_price}\n"
        "⚠️ POSITION WAS NOT AUTO-CLOSED"
    )


# =========================================================
# CANDLE SIGNAL
# =========================================================

def candle_signal(
    symbol
):

    try:

        data = public_get(
            "/klines",
            {
                "symbol": symbol,
                "interval": "5m",
                "limit": MIN_CANDLES + 2
            }
        )

        if len(data) < (
            MIN_CANDLES + 1
        ):

            return None

        # آخر کندل ممکن است هنوز باز باشد
        closed = data[:-1]

        previous = closed[-2]
        last = closed[-1]

        previous_high = Decimal(
            str(
                previous[2]
            )
        )

        open_price = Decimal(
            str(
                last[1]
            )
        )

        high = Decimal(
            str(
                last[2]
            )
        )

        close = Decimal(
            str(
                last[4]
            )
        )

        if close <= open_price:
            return None

        broke = (
            close
            > previous_high
        )

        near = (
            close
            > previous_high
            * (
                Decimal("1")
                - Decimal("0.0025")
            )
        )

        if not (
            broke
            or near
        ):

            return None

        if broke:

            score = 8
            reason = "BOS"

        else:

            score = 7
            reason = "NEAR BOS"

        return {
            "symbol": symbol,
            "score": score,
            "price": close,
            "reason": reason
        }

    except Exception:

        return None


# =========================================================
# SCAN
# =========================================================

def scan(
    info
):

    symbols = []

    for s in info.get(
        "symbols",
        []
    ):

        if (
            s.get("status")
            == "TRADING"
            and
            s.get("quoteAsset")
            == "USDT"
        ):

            symbols.append(
                s["symbol"]
            )

    symbols = symbols[
        :SCAN_UNIVERSE
    ]

    best = None

    for symbol in symbols:

        signal = candle_signal(
            symbol
        )

        if not signal:
            continue

        if (
            signal["score"]
            < MIN_SCORE
        ):

            continue

        if (
            best is None
            or
            signal["score"]
            > best["score"]
        ):

            best = signal

    return best


# =========================================================
# BUY POSITION
# =========================================================

def buy_position(
    signal,
    info
):

    symbol = signal[
        "symbol"
    ]

    symbol_data = symbol_info(
        info,
        symbol
    )

    if not symbol_data:

        raise RuntimeError(
            f"Symbol info not found: "
            f"{symbol}"
        )

    filters = filters_for(
        symbol_data
    )

    lot_filter = filters.get(
        "LOT_SIZE",
        {}
    )

    step = Decimal(
        str(
            lot_filter.get(
                "stepSize",
                "0.00000001"
            )
        )
    )

    min_qty = Decimal(
        str(
            lot_filter.get(
                "minQty",
                "0"
            )
        )
    )

    quantity = round_qty(
        ORDER_VALUE
        / signal["price"],
        step
    )

    if quantity < min_qty:

        raise RuntimeError(
            "Quantity below minQty: "
            f"{quantity} < {min_qty}"
        )

    telegram(
        "🚨 BUY SIGNAL\n"
        f"🪙 {symbol}\n"
        f"📊 {signal['reason']}\n"
        f"💵 PRICE: "
        f"{signal['price']}\n"
        f"⭐ SCORE: "
        f"{signal['score']}\n"
        f"📦 QTY: {quantity}\n"
        f"🔓 LIVE: {LIVE_TRADING}"
    )

    if not LIVE_TRADING:

        telegram(
            "🔒 LIVE TRADING OFF\n"
            "❌ NO BUY SENT"
        )

        return

    order = market_buy(
        symbol,
        quantity
    )

    telegram(
        "✅ BUY SENT\n"
        f"🪙 {symbol}\n"
        f"🆔 ORDER: "
        f"{order.get('orderId')}"
    )

    time.sleep(2)

    entry = (
        filled_entry(symbol)
        or signal["price"]
    )

    current = price(
        symbol
    )

    position = {
        "symbol": symbol,
        "quantity": quantity,
        "entry_price": entry,
        "current_price": current
    }

    telegram(
        "📌 POSITION ACTIVE\n"
        f"🪙 {symbol}\n"
        f"📥 ENTRY: {entry}\n"
        f"🎯 TP: "
        f"{entry * (Decimal('1') + TP_PCT)}\n"
        f"🛑 SL: "
        f"{entry * (Decimal('1') - SL_PCT)}"
    )

    manage_position(
        position
    )


# =========================================================
# MAIN
# =========================================================

def main():

    telegram(
        f"💓 ATI ALIVE\n"
        f"⚡ {VERSION}\n"
        "📡 TABDEAL SPOT\n"
        f"🔓 LIVE: {LIVE_TRADING}\n"
        f"💵 ORDER: "
        f"{ORDER_VALUE} USDT\n"
        "🎯 TP: +2.0%\n"
        "🛑 SL: -1.0%"
    )

    # همگام‌سازی ساعت با سرور
    sync_time()

    # بررسی احراز هویت
    account = auth_check()

    balance_data = balances(
        account
    )

    usdt_free = balance_data.get(
        "USDT",
        Decimal("0")
    )

    telegram(
        "✅ AUTH SUCCESS\n"
        "🔓 canTrade=True\n"
        f"💰 USDT FREE: {usdt_free}"
    )

    # دریافت اطلاعات بازار
    info = exchange_info()

    symbols_count = len(
        info.get(
            "symbols",
            []
        )
    )

    telegram(
        "📊 EXCHANGE INFO OK\n"
        f"📈 MARKETS: {symbols_count}"
    )

    # =====================================================
    # اول پوزیشن قبلی بررسی می‌شود
    # =====================================================

    existing = find_existing_position(
        info
    )

    if existing:

        telegram(
            "🔄 EXISTING POSITION FOUND\n"
            f"🪙 {existing['symbol']}\n"
            f"📥 ENTRY: "
            f"{existing['entry_price']}\n"
            f"💵 CURRENT: "
            f"{existing['current_price']}"
        )

        manage_position(
            existing
        )

        return

    # =====================================================
    # بررسی موجودی برای خرید جدید
    # =====================================================

    if usdt_free < ORDER_VALUE:

        telegram(
            "❌ USDT BALANCE TOO LOW\n"
            f"💰 FREE: {usdt_free}\n"
            f"💵 REQUIRED: "
            f"{ORDER_VALUE}"
        )

        return

    # =====================================================
    # اسکن بازار
    # =====================================================

    telegram(
        "🔎 SCANNING MARKET..."
    )

    signal = scan(
        info
    )

    if not signal:

        telegram(
            "🔎 NO VALID BUY SIGNAL\n"
            "🚫 NO TRADE"
        )

        return

    telegram(
        "🎯 BEST SIGNAL FOUND\n"
        f"🪙 {signal['symbol']}\n"
        f"📊 {signal['reason']}\n"
        f"💵 PRICE: "
        f"{signal['price']}\n"
        f"⭐ SCORE: "
        f"{signal['score']}"
    )

    # =====================================================
    # خرید
    # =====================================================

    buy_position(
        signal,
        info
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        telegram(
            f"🚨 ATI ERROR {VERSION}\n"
            f"❌ {e}"
        )

        raise
