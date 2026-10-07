import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from decimal import Decimal, ROUND_DOWN


# =========================================================
# ATI FUTURES REAL MULTI-COIN
# =========================================================

API_BASE = "https://api1.tabdeal.org"

READ_BASE = API_BASE + "/r/fapi/v1/"
WRITE_BASE = API_BASE + "/fapi/v1/"

API_KEY = (
    os.getenv("TABDIL_API_KEY")
    or os.getenv("TABDEAL_API_KEY")
    or ""
).strip()

API_SECRET = (
    os.getenv("TABDIL_API_SECRET")
    or os.getenv("TABDEAL_API_SECRET")
    or ""
).strip()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


# =========================================================
# REAL SETTINGS
# =========================================================

REAL_TRADING = True

LEVERAGE = int(os.getenv("FUTURES_LEVERAGE", "3"))

ORDER_USDT = Decimal(
    os.getenv("ORDER_USDT", "2")
)

TP_PERCENT = Decimal(
    os.getenv("TP_PERCENT", "2.0")
)

SL_PERCENT = Decimal(
    os.getenv("SL_PERCENT", "1.0")
)

RECV_WINDOW = 5000
TIMEOUT = 15

# حداکثر تعداد نماد برای بررسی
MAX_SYMBOLS = int(
    os.getenv("MAX_FUTURES_SYMBOLS", "75")
)


session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-FUTURES-REAL/1.0",
    "Accept": "application/json",
})


# =========================================================
# TELEGRAM
# =========================================================

def tg(text):

    print(text)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{TELEGRAM_TOKEN}/sendMessage"
        )

        session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
            },
            timeout=10,
        )

    except Exception as e:

        print("Telegram error:", e)


# =========================================================
# JSON
# =========================================================

def json_response(r):

    try:
        return r.json()

    except Exception:

        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:1000]}"
        )


# =========================================================
# PUBLIC GET
# =========================================================

def public_get(endpoint, params=None):

    r = session.get(
        READ_BASE + endpoint,
        params=params or {},
        timeout=TIMEOUT,
    )

    if r.status_code >= 400:

        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:1000]}"
        )

    return json_response(r)


# =========================================================
# SIGN
# =========================================================

def signature(data):

    query = urlencode(data)

    return hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()


# =========================================================
# PRIVATE GET
# =========================================================

def private_get(endpoint, params=None):

    if not API_KEY or not API_SECRET:

        raise RuntimeError(
            "TABDIL_API_KEY / TABDIL_API_SECRET missing"
        )

    data = dict(params or {})

    data["timestamp"] = int(
        time.time() * 1000
    )

    data["recvWindow"] = RECV_WINDOW

    data["signature"] = signature(data)

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    r = session.get(
        READ_BASE + endpoint,
        params=data,
        headers=headers,
        timeout=TIMEOUT,
    )

    if r.status_code >= 400:

        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:1000]}"
        )

    return json_response(r)


# =========================================================
# PRIVATE POST
# =========================================================

def private_post(endpoint, params):

    if not API_KEY or not API_SECRET:

        raise RuntimeError(
            "API KEY / SECRET missing"
        )

    data = dict(params)

    data["timestamp"] = int(
        time.time() * 1000
    )

    data["recvWindow"] = RECV_WINDOW

    data["signature"] = signature(data)

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    r = session.post(
        WRITE_BASE + endpoint,
        data=data,
        headers=headers,
        timeout=TIMEOUT,
    )

    if r.status_code >= 400:

        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:1500]}"
        )

    return json_response(r)


# =========================================================
# EXCHANGE INFO
# =========================================================

def exchange_info():

    data = public_get(
        "exchangeInfo"
    )

    if isinstance(data, dict):

        if isinstance(
            data.get("symbols"),
            list
        ):
            return data["symbols"]

        if isinstance(
            data.get("data"),
            list
        ):
            return data["data"]

        if isinstance(
            data.get("result"),
            list
        ):
            return data["result"]

        if isinstance(
            data.get("data"),
            dict
        ):

            if isinstance(
                data["data"].get("symbols"),
                list
            ):
                return data["data"]["symbols"]

        if isinstance(
            data.get("result"),
            dict
        ):

            if isinstance(
                data["result"].get("symbols"),
                list
            ):
                return data["result"]["symbols"]

    if isinstance(data, list):
        return data

    return []


# =========================================================
# SYMBOL LIST
# =========================================================

def get_symbols():

    rows = exchange_info()

    symbols = []

    for row in rows:

        if isinstance(row, str):

            symbol = row.upper()

        elif isinstance(row, dict):

            symbol = str(
                row.get("symbol")
                or row.get("contract")
                or row.get("pair")
                or ""
            ).upper()

            status = str(
                row.get("status")
                or ""
            ).upper()

            if status:

                allowed = [
                    "TRADING",
                    "OPEN",
                    "ACTIVE",
                    "1",
                ]

                if status not in allowed:
                    continue

        else:
            continue

        if not symbol:
            continue

        if not (
            symbol.endswith("USDT")
            or symbol.endswith("USDC")
            or symbol.endswith("USD")
        ):
            continue

        blocked = [
            "INDEX",
            "MARK",
            "TEST",
        ]

        if any(
            x in symbol
            for x in blocked
        ):
            continue

        symbols.append(symbol)

    return sorted(
        set(symbols)
    )


# =========================================================
# ORDER BOOK
# =========================================================

def depth(symbol):

    return public_get(
        "depth",
        {
            "symbol": symbol,
            "limit": 5,
        },
    )


# =========================================================
# PRICE
# =========================================================

def get_price(symbol):

    data = depth(symbol)

    bids = data.get(
        "bids",
        []
    )

    asks = data.get(
        "asks",
        []
    )

    if not bids or not asks:
        return None

    bid = Decimal(
        str(bids[0][0])
    )

    ask = Decimal(
        str(asks[0][0])
    )

    return (
        bid + ask
    ) / Decimal("2")


# =========================================================
# SIMPLE PRICE-ACTION SIGNAL
# =========================================================

def signal(symbol):

    try:

        data = depth(symbol)

        bids = data.get(
            "bids",
            []
        )

        asks = data.get(
            "asks",
            []
        )

        if not bids or not asks:
            return None

        bid_price = Decimal(
            str(bids[0][0])
        )

        ask_price = Decimal(
            str(asks[0][0])
        )

        bid_qty = Decimal(
            str(bids[0][1])
        )

        ask_qty = Decimal(
            str(asks[0][1])
        )

        if bid_qty <= 0 or ask_qty <= 0:
            return None

        total = (
            bid_qty + ask_qty
        )

        bid_pressure = (
            bid_qty / total
        ) * Decimal("100")

        ask_pressure = (
            ask_qty / total
        ) * Decimal("100")

        price = (
            bid_price + ask_price
        ) / Decimal("2")

        # فقط وقتی فشار واضح باشد
        if bid_pressure >= Decimal("65"):

            return {
                "symbol": symbol,
                "side": "BUY",
                "price": price,
                "pressure": bid_pressure,
            }

        if ask_pressure >= Decimal("65"):

            return {
                "symbol": symbol,
                "side": "SELL",
                "price": price,
                "pressure": ask_pressure,
            }

    except Exception as e:

        print(
            f"{symbol} signal error:",
            e
        )

    return None


# =========================================================
# FIND OPEN POSITIONS
# =========================================================

def open_positions():

    data = private_get(
        "positionRisk"
    )

    if not isinstance(data, list):
        return []

    result = []

    for p in data:

        try:

            qty = Decimal(
                str(
                    p.get("positionAmt")
                    or p.get("quantity")
                    or p.get("qty")
                    or "0"
                )
            )

        except Exception:

            qty = Decimal("0")

        if qty != 0:

            result.append(p)

    return result


# =========================================================
# SET LEVERAGE
# =========================================================

def set_leverage(symbol):

    return private_post(
        "leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE,
        },
    )


# =========================================================
# FIND STEP SIZE
# =========================================================

def symbol_rules(symbol):

    rows = exchange_info()

    for row in rows:

        if not isinstance(row, dict):
            continue

        s = str(
            row.get("symbol")
            or ""
        ).upper()

        if s != symbol:
            continue

        step = (
            row.get("stepSize")
            or row.get("quantityStep")
            or row.get("qtyStep")
            or "0.000001"
        )

        min_qty = (
            row.get("minQty")
            or row.get("minQuantity")
            or "0"
        )

        return (
            Decimal(str(step)),
            Decimal(str(min_qty)),
        )

    return (
        Decimal("0.000001"),
        Decimal("0"),
    )


# =========================================================
# ROUND QUANTITY
# =========================================================

def round_qty(qty, step):

    if step <= 0:
        return qty

    return (
        qty / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


# =========================================================
# REAL MARKET ORDER
# =========================================================

def market_order(
    symbol,
    side,
    quantity,
):

    return private_post(
        "order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": str(quantity),
        },
    )


# =========================================================
# MAIN
# =========================================================

def main():

    tg(
        "💓 ATI FUTURES REAL\n"
        "🔥 REAL TRADING = ON\n"
        "📊 MULTI-COIN\n"
        f"⚙️ LEVERAGE = {LEVERAGE}x\n"
        f"💵 ORDER = {ORDER_USDT} USDT"
    )

    if not API_KEY or not API_SECRET:

        tg(
            "❌ API KEY/SECRET موجود نیست."
        )

        return

    # -----------------------------------------------------
    # ACCOUNT
    # -----------------------------------------------------

    try:

        account = private_get(
            "account"
        )

        tg(
            "✅ FUTURES AUTH SUCCESS\n"
            f"🔓 canTrade={account.get('canTrade')}"
        )

    except Exception as e:

        tg(
            "❌ FUTURES AUTH ERROR\n\n"
            + str(e)
        )

        return

    # -----------------------------------------------------
    # POSITIONS
    # -----------------------------------------------------

    try:

        positions = open_positions()

        tg(
            "📌 OPEN POSITIONS: "
            + str(len(positions))
        )

    except Exception as e:

        tg(
            "❌ POSITION ERROR\n\n"
            + str(e)
        )

        return

    # -----------------------------------------------------
    # SYMBOLS
    # -----------------------------------------------------

    try:

        symbols = get_symbols()

    except Exception as e:

        tg(
            "❌ EXCHANGE INFO ERROR\n\n"
            + str(e)
        )

        return

    if not symbols:

        tg(
            "❌ هیچ Futures Symbol پیدا نشد."
        )

        return

    symbols = symbols[:MAX_SYMBOLS]

    tg(
        "📊 FUTURES MARKET\n"
        f"TOTAL SYMBOLS = {len(symbols)}\n"
        "🔎 SCANNING..."
    )

    # -----------------------------------------------------
    # SCAN
    # -----------------------------------------------------

    candidates = []

    open_symbols = set()

    for p in positions:

        s = str(
            p.get("symbol")
            or ""
        ).upper()

        if s:
            open_symbols.add(s)

    for symbol in symbols:

        # پوزیشن باز را دوباره وارد نکن
        if symbol in open_symbols:
            continue

        sig = signal(symbol)

        if not sig:
            continue

        candidates.append(sig)

        print(
            "SIGNAL",
            symbol,
            sig["side"],
            sig["pressure"]
        )

    if not candidates:

        tg(
            "ℹ️ فعلاً سیگنال قدرتمند پیدا نشد.\n"
            f"📊 SCANNED: {len(symbols)}\n"
            "🔒 NO ORDER"
        )

        return

    # -----------------------------------------------------
    # BEST SIGNAL
    # -----------------------------------------------------

    candidates.sort(
        key=lambda x: x["pressure"],
        reverse=True,
    )

    best = candidates[0]

    symbol = best["symbol"]
    side = best["side"]
    price = best["price"]
    pressure = best["pressure"]

    tg(
        "🚨 BEST FUTURES SIGNAL\n\n"
        f"🪙 {symbol}\n"
        f"📍 {side}\n"
        f"💰 PRICE: {price}\n"
        f"💪 PRESSURE: {pressure:.2f}%\n"
        f"⚙️ LEVERAGE: {LEVERAGE}x\n"
        f"💵 MARGIN: {ORDER_USDT} USDT\n"
        "🔥 REAL ORDER: ON"
    )

    # -----------------------------------------------------
    # LEVERAGE
    # -----------------------------------------------------

    try:

        lev = set_leverage(
            symbol
        )

        print(
            "LEVERAGE RESULT:",
            lev
        )

    except Exception as e:

        tg(
            "❌ LEVERAGE ERROR\n\n"
            + str(e)
        )

        return

    # -----------------------------------------------------
    # QUANTITY
    # -----------------------------------------------------

    try:

        step, min_qty = symbol_rules(
            symbol
        )

        if price <= 0:

            raise RuntimeError(
                "Invalid price"
            )

        # مقدار اسمی پوزیشن:
        # margin × leverage
        notional = (
            ORDER_USDT
            * Decimal(LEVERAGE)
        )

        quantity = (
            notional / price
        )

        quantity = round_qty(
            quantity,
            step,
        )

        if quantity <= 0:

            raise RuntimeError(
                "Calculated quantity is zero"
            )

        if quantity < min_qty:

            raise RuntimeError(
                f"Quantity {quantity} "
                f"< minimum {min_qty}"
            )

    except Exception as e:

        tg(
            "❌ QUANTITY ERROR\n\n"
            + str(e)
        )

        return

    # -----------------------------------------------------
    # REAL ORDER
    # -----------------------------------------------------

    try:

        order = market_order(
            symbol,
            side,
            quantity,
        )

        tg(
            "🔥🔥 REAL FUTURES ORDER SENT 🔥🔥\n\n"
            f"🪙 {symbol}\n"
            f"📍 {side}\n"
            f"💰 ENTRY ≈ {price}\n"
            f"📦 QTY = {quantity}\n"
            f"⚙️ LEVERAGE = {LEVERAGE}x\n"
            f"💵 MARGIN ≈ {ORDER_USDT} USDT\n\n"
            f"ORDER RESPONSE:\n{str(order)[:1500]}"
        )

    except Exception as e:

        tg(
            "❌ REAL ORDER FAILED\n\n"
            f"{symbol}\n"
            f"{side}\n"
            f"QTY={quantity}\n\n"
            f"{e}"
        )

        return


if __name__ == "__main__":
    main()
