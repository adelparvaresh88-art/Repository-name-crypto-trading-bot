import os
import time
import math
import requests
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

from tabdeal.future import Future
from tabdeal.enums import OrderSides, OrderTypes


# ============================================================
# ATI FUTURES BOT
# V1.0 - TABDEAL FUTURES
# ============================================================

VERSION = "ATI-FUTURES-V1.0"

API_KEY = os.getenv("TABDIL_API_KEY") or os.getenv("TABDEAL_API_KEY")
API_SECRET = os.getenv("TABDIL_API_SECRET") or os.getenv("TABDEAL_API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

LEVERAGE = int(os.getenv("LEVERAGE", "3"))

ORDER_USDT = float(os.getenv("ORDER_QTY", "2"))

TP_PERCENT = float(os.getenv("TP_PERCENT", "2.0"))
SL_PERCENT = float(os.getenv("SL_PERCENT", "1.0"))

SCAN_UNIVERSE = int(os.getenv("SCAN_UNIVERSE", "30"))
MIN_CANDLES = int(os.getenv("MIN_CANDLES", "25"))

# برای اینکه اولین نسخه ناخواسته وارد معامله نشود
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "1"))

API_BASE = "https://api1.tabdeal.org"

TIMEOUT = 15


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return

    try:
        url = (
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
            f"/sendMessage"
        )

        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
        }

        requests.post(url, data=data, timeout=10)

    except Exception as e:
        print("Telegram error:", e)


# ============================================================
# BASIC HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def floor_step(value, step):
    try:
        value = Decimal(str(value))
        step = Decimal(str(step))

        if step <= 0:
            return value

        return (value / step).to_integral_value(
            rounding=ROUND_DOWN
        ) * step

    except Exception:
        return Decimal(str(value))


# ============================================================
# CLIENT
# ============================================================

def create_client():
    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDIL_API_KEY / TABDIL_API_SECRET موجود نیست."
        )

    return Future(
        api_key=API_KEY,
        api_secret=API_SECRET,
        base_url=API_BASE,
        timeout=TIMEOUT,
        receive_window=5000,
    )


# ============================================================
# TELEGRAM STARTUP
# ============================================================

def send_startup():
    telegram(
        "💓 ATI FUTURES ALIVE\n"
        f"⚡ {VERSION}\n"
        "📡 TABDEAL FUTURES\n"
        f"🔒 LIVE: {LIVE_TRADING}\n"
        f"⚙️ LEVERAGE: {LEVERAGE}x\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"🎯 TP: +{TP_PERCENT}%\n"
        f"🛑 SL: -{SL_PERCENT}%\n"
        f"🕐 {now_utc()}"
    )


# ============================================================
# AUTH / ACCOUNT
# ============================================================

def check_auth(client):
    account = client.account()

    telegram(
        "✅ FUTURES AUTH SUCCESS\n"
        "🔓 Futures account accessible."
    )

    return account


def get_usdt_balance(client):
    try:
        balances = client.balance()

        if isinstance(balances, dict):
            balances = balances.get("balances", balances)

        if not isinstance(balances, list):
            return 0.0

        for item in balances:
            asset = str(item.get("asset", "")).upper()

            if asset == "USDT":
                return safe_float(
                    item.get("availableBalance")
                    or item.get("balance")
                    or item.get("free")
                    or 0
                )

    except Exception as e:
        telegram(f"⚠️ FUTURES BALANCE ERROR\n{e}")

    return 0.0


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info(client):
    return client.exchange_info()


def parse_symbol_rules(info):
    rules = {}

    if not isinstance(info, dict):
        return rules

    symbols = info.get("symbols", [])

    if not isinstance(symbols, list):
        return rules

    for s in symbols:

        symbol = str(
            s.get("symbol", "")
        ).upper()

        if not symbol:
            continue

        if s.get("status") not in (None, "TRADING"):
            continue

        qty_step = 0.0
        min_qty = 0.0
        min_notional = 0.0
        price_tick = 0.0

        filters = s.get("filters", [])

        for f in filters:

            ft = str(
                f.get("filterType", "")
            )

            if ft in ("LOT_SIZE", "MARKET_LOT_SIZE"):

                qty_step = safe_float(
                    f.get("stepSize"),
                    qty_step
                )

                min_qty = safe_float(
                    f.get("minQty"),
                    min_qty
                )

            if ft in ("MIN_NOTIONAL", "NOTIONAL"):

                min_notional = safe_float(
                    f.get("minNotional"),
                    min_notional
                )

            if ft == "PRICE_FILTER":

                price_tick = safe_float(
                    f.get("tickSize"),
                    price_tick
                )

        rules[symbol] = {
            "qty_step": qty_step,
            "min_qty": min_qty,
            "min_notional": min_notional,
            "price_tick": price_tick,
        }

    return rules


# ============================================================
# MARKET DATA
# ============================================================

def get_depth(client, symbol):
    return client.depth(symbol=symbol, limit=20)


def get_price_from_depth(depth):
    try:
        bids = depth.get("bids", [])
        asks = depth.get("asks", [])

        if not bids or not asks:
            return 0.0

        bid = safe_float(bids[0][0])
        ask = safe_float(asks[0][0])

        if bid <= 0 or ask <= 0:
            return 0.0

        return (bid + ask) / 2

    except Exception:
        return 0.0


# ============================================================
# SIMPLE PRICE ACTION
# ============================================================

def price_pressure(depth):
    try:
        bids = depth.get("bids", [])
        asks = depth.get("asks", [])

        bid_volume = sum(
            safe_float(x[1])
            for x in bids[:10]
        )

        ask_volume = sum(
            safe_float(x[1])
            for x in asks[:10]
        )

        total = bid_volume + ask_volume

        if total <= 0:
            return 50.0

        return (
            bid_volume /
            total
        ) * 100

    except Exception:
        return 50.0


def make_signal(client, symbol):
    try:

        depth = get_depth(client, symbol)

        price = get_price_from_depth(depth)

        if price <= 0:
            return None

        pressure = price_pressure(depth)

        # -------------------------------
        # ساده و محافظه‌کارانه
        # -------------------------------

        if pressure >= 58:
            side = "LONG"
            score = pressure

        elif pressure <= 42:
            side = "SHORT"
            score = 100 - pressure

        else:
            return None

        return {
            "symbol": symbol,
            "side": side,
            "price": price,
            "pressure": pressure,
            "score": score,
        }

    except Exception:
        return None


# ============================================================
# POSITION
# ============================================================

def get_open_positions(client):
    try:

        result = client.get_positions(
            is_active=1
        )

        if isinstance(result, dict):
            positions = result.get(
                "positions",
                result.get("data", [])
            )
        else:
            positions = result

        if not isinstance(positions, list):
            return []

        active = []

        for p in positions:

            qty = safe_float(
                p.get("positionAmt")
                or p.get("quantity")
                or p.get("qty")
                or 0
            )

            if abs(qty) > 0:
                active.append(p)

        return active

    except Exception as e:

        telegram(
            "⚠️ FUTURES POSITION ERROR\n"
            f"{e}"
        )

        return []


# ============================================================
# QUANTITY
# ============================================================

def calculate_quantity(
    price,
    order_usdt,
    leverage,
    rule
):

    if price <= 0:
        return 0.0

    # ارزش اسمی معامله
    notional = order_usdt * leverage

    raw_qty = notional / price

    step = rule.get(
        "qty_step",
        0
    )

    min_qty = rule.get(
        "min_qty",
        0
    )

    qty = floor_step(
        raw_qty,
        step
    )

    if min_qty > 0 and float(qty) < min_qty:
        qty = Decimal(str(min_qty))

        if step > 0:
            qty = floor_step(
                qty,
                step
            )

    return float(qty)


# ============================================================
# LEVERAGE
# ============================================================

def set_leverage(client, symbol):

    if not LIVE_TRADING:
        return

    result = client.change_leverage(
        symbol=symbol,
        leverage=LEVERAGE
    )

    print(
        "LEVERAGE:",
        result
    )


# ============================================================
# OPEN POSITION
# ============================================================

def open_position(
    client,
    signal,
    rules
):

    symbol = signal["symbol"]
    side = signal["side"]
    price = signal["price"]

    rule = rules.get(
        symbol,
        {}
    )

    quantity = calculate_quantity(
        price,
        ORDER_USDT,
        LEVERAGE,
        rule
    )

    if quantity <= 0:
        telegram(
            f"❌ {symbol}\n"
            "Quantity invalid."
        )
        return None

    if side == "LONG":
        order_side = OrderSides.BUY
    else:
        order_side = OrderSides.SELL

    telegram(
        "📌 FUTURES SIGNAL\n"
        f"🪙 {symbol}\n"
        f"📈 SIDE: {side}\n"
        f"💵 PRICE: {price}\n"
        f"📦 QTY: {quantity}\n"
        f"⚡ LEVERAGE: {LEVERAGE}x\n"
        f"📊 PRESSURE: {signal['pressure']:.1f}%\n"
        f"🎯 SCORE: {signal['score']:.1f}\n"
        f"🔒 LIVE: {LIVE_TRADING}"
    )

    if not LIVE_TRADING:
        telegram(
            "🧪 PAPER MODE\n"
            "معامله واقعی باز نشد."
        )
        return None

    try:

        set_leverage(
            client,
            symbol
        )

        order = client.new_order(
            symbol=symbol,
            side=order_side,
            type=OrderTypes.MARKET,
            quantity=str(quantity),
        )

        telegram(
            "✅ FUTURES ORDER SENT\n"
            f"🪙 {symbol}\n"
            f"📈 {side}\n"
            f"📦 QTY: {quantity}\n"
            f"⚡ {LEVERAGE}x\n"
            f"🆔 {order.get('orderId', '-')}"
        )

        return order

    except Exception as e:

        telegram(
            "❌ FUTURES ORDER ERROR\n"
            f"🪙 {symbol}\n"
            f"{e}"
        )

        return None


# ============================================================
# SL / TP
# ============================================================

def attach_sl_tp(client, position):
    try:

        symbol = position.get(
            "symbol"
        )

        position_id = position.get(
            "positionId"
            or position.get("id")
        )

        entry = safe_float(
            position.get(
                "entryPrice"
                or position.get("avgPrice")
            )
        )

        side = str(
            position.get(
                "side"
                or position.get("positionSide")
                or ""
            )
        ).upper()

        if entry <= 0 or not position_id:
            return False

        if side in ("LONG", "BUY"):

            sl = entry * (
                1 - SL_PERCENT / 100
            )

            tp = entry * (
                1 + TP_PERCENT / 100
            )

        else:

            sl = entry * (
                1 + SL_PERCENT / 100
            )

            tp = entry * (
                1 - TP_PERCENT / 100
            )

        if not LIVE_TRADING:
            return False

        result = client.position_sl_tp(
            position_id=int(position_id),
            symbol=symbol,
            sl_price=str(sl),
            tp_price=str(tp),
        )

        telegram(
            "🛡️ SL/TP SET\n"
            f"🪙 {symbol}\n"
            f"🛑 SL: {sl}\n"
            f"🎯 TP: {tp}"
        )

        return bool(result)

    except Exception as e:

        telegram(
            "⚠️ SL/TP ERROR\n"
            f"{e}"
        )

        return False


# ============================================================
# SCANNER
# ============================================================

def get_futures_symbols(info):

    symbols = []

    if not isinstance(info, dict):
        return symbols

    data = info.get(
        "symbols",
        []
    )

    for item in data:

        symbol = str(
            item.get("symbol", "")
        ).upper()

        if not symbol:
            continue

        status = item.get(
            "status"
        )

        if status not in (
            None,
            "TRADING"
        ):
            continue

        # فقط USDT futures
        if not symbol.endswith("USDT"):
            continue

        symbols.append(symbol)

    return symbols


def scan_market(
    client,
    symbols
):

    best = None

    checked = 0

    for symbol in symbols:

        if checked >= SCAN_UNIVERSE:
            break

        checked += 1

        signal = make_signal(
            client,
            symbol
        )

        if not signal:
            continue

        if best is None:
            best = signal
            continue

        if signal["score"] > best["score"]:
            best = signal

    return best


# ============================================================
# MAIN
# ============================================================

def main():

    send_startup()

    try:

        client = create_client()

        telegram(
            "🔌 Connecting to TABDEAL FUTURES..."
        )

        check_auth(client)

        balance = get_usdt_balance(
            client
        )

        telegram(
            "💰 FUTURES USDT\n"
            f"FREE: {balance:.8f}"
        )

        info = get_exchange_info(
            client
        )

        rules = parse_symbol_rules(
            info
        )

        symbols = get_futures_symbols(
            info
        )

        telegram(
            "📊 FUTURES EXCHANGE INFO OK\n"
            f"📈 USDT MARKETS: {len(symbols)}"
        )

        positions = get_open_positions(
            client
        )

        telegram(
            "📌 OPEN POSITIONS\n"
            f"{len(positions)}"
        )

        # اگر پوزیشن باز وجود دارد،
        # پوزیشن جدید باز نمی‌کنیم.
        if len(positions) >= MAX_OPEN_POSITIONS:

            telegram(
                "⏸️ NO NEW ENTRY\n"
                "پوزیشن Futures باز است."
            )

            for p in positions:
                attach_sl_tp(
                    client,
                    p
                )

            return

        if balance <= 0:

            telegram(
                "⚠️ FUTURES USDT BALANCE = 0"
            )

            return

        signal = scan_market(
            client,
            symbols
        )

        if not signal:

            telegram(
                "🔎 NO FUTURES SIGNAL\n"
                "شرایط ورود مناسب پیدا نشد."
            )

            return

        telegram(
            "🎯 BEST FUTURES SIGNAL\n"
            f"🪙 {signal['symbol']}\n"
            f"📈 {signal['side']}\n"
            f"💵 {signal['price']}\n"
            f"📊 PRESSURE: {signal['pressure']:.1f}%\n"
            f"⭐ SCORE: {signal['score']:.1f}"
        )

        open_position(
            client,
            signal,
            rules
        )

    except Exception as e:

        telegram(
            "❌ ATI FUTURES ERROR\n\n"
            f"{e}\n\n"
            f"🕐 {now_utc()}"
        )

        raise


if __name__ == "__main__":
    main()
