import os
import time
import requests
from decimal import Decimal, ROUND_DOWN

from tabdeal.future import Future
from tabdeal.enums import OrderSides, OrderTypes


# ============================================================
# ATI FUTURES REAL BOT
# ============================================================

API_KEY = os.getenv("TABDIL_API_KEY") or os.getenv("TABDEAL_API_KEY")
API_SECRET = os.getenv("TABDIL_API_SECRET") or os.getenv("TABDEAL_API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

SYMBOL = os.getenv("FUTURES_SYMBOL", "BTCUSDT").upper()
INTERVAL = os.getenv("FUTURES_INTERVAL", "5m")

ORDER_USDT = Decimal(os.getenv("FUTURES_ORDER_USDT", "2"))
LEVERAGE = int(os.getenv("FUTURES_LEVERAGE", "3"))

TP_PERCENT = Decimal(os.getenv("TP_PERCENT", "2"))
SL_PERCENT = Decimal(os.getenv("SL_PERCENT", "1"))

BASE_URL = "https://api1.tabdeal.org"


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )
    except Exception as e:
        print("Telegram error:", e)


# ============================================================
# FUTURES CLIENT
# ============================================================

if not API_KEY or not API_SECRET:
    raise RuntimeError(
        "TABDIL_API_KEY / TABDIL_API_SECRET موجود نیست."
    )

client = Future(
    API_KEY,
    API_SECRET,
    base_url=BASE_URL,
    receive_window=5000,
    timeout=20,
)


# ============================================================
# PUBLIC KLINES
# ============================================================

def get_klines():

    url = f"{BASE_URL}/fapi/v1/klines"

    r = requests.get(
        url,
        params={
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "limit": 100,
        },
        timeout=20,
    )

    r.raise_for_status()

    data = r.json()

    if not isinstance(data, list) or len(data) < 30:
        raise RuntimeError("داده کندلی کافی دریافت نشد.")

    candles = []

    for x in data:
        candles.append(
            {
                "time": int(x[0]),
                "open": Decimal(str(x[1])),
                "high": Decimal(str(x[2])),
                "low": Decimal(str(x[3])),
                "close": Decimal(str(x[4])),
                "volume": Decimal(str(x[5])),
            }
        )

    return candles


# ============================================================
# SIMPLE PRICE ACTION SIGNAL
# ============================================================

def get_signal(candles):

    # آخرین کندل را کنار می‌گذاریم چون ممکن است هنوز بسته نشده باشد.
    closed = candles[:-1]

    if len(closed) < 25:
        return None

    c1 = closed[-1]
    c2 = closed[-2]
    c3 = closed[-3]

    # ------------------------------------------
    # BUY
    # ------------------------------------------

    previous_high = max(
        x["high"] for x in closed[-7:-1]
    )

    bullish_breakout = c1["close"] > previous_high

    bullish_candle = c1["close"] > c1["open"]

    previous_bullish = c2["close"] > c2["open"]

    higher_structure = (
        c1["close"] > c2["close"]
        and c2["close"] >= c3["close"]
    )

    if (
        bullish_breakout
        and bullish_candle
        and previous_bullish
        and higher_structure
    ):
        return "LONG"

    # ------------------------------------------
    # SELL
    # ------------------------------------------

    previous_low = min(
        x["low"] for x in closed[-7:-1]
    )

    bearish_breakdown = c1["close"] < previous_low

    bearish_candle = c1["close"] < c1["open"]

    previous_bearish = c2["close"] < c2["open"]

    lower_structure = (
        c1["close"] < c2["close"]
        and c2["close"] <= c3["close"]
    )

    if (
        bearish_breakdown
        and bearish_candle
        and previous_bearish
        and lower_structure
    ):
        return "SHORT"

    return None


# ============================================================
# POSITION
# ============================================================

def get_position():

    result = client.get_positions(
        symbol=SYMBOL
    )

    if not result:
        return None

    if isinstance(result, dict):
        positions = result.get("data", result)
    else:
        positions = result

    if not isinstance(positions, list):
        return None

    for p in positions:

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
            return p

    return None


# ============================================================
# LEVERAGE
# ============================================================

def set_leverage():

    result = client.change_leverage(
        symbol=SYMBOL,
        leverage=LEVERAGE,
    )

    print("LEVERAGE:", result)

    return result


# ============================================================
# QUANTITY
# ============================================================

def calculate_quantity(price):

    notional = ORDER_USDT * Decimal(str(LEVERAGE))

    quantity = notional / price

    # BTC Futures usually requires more precision than 2 decimals.
    # Exchange will validate final quantity.
    quantity = quantity.quantize(
        Decimal("0.000001"),
        rounding=ROUND_DOWN,
    )

    return quantity


# ============================================================
# MARKET ENTRY
# ============================================================

def open_position(signal, price):

    quantity = calculate_quantity(price)

    if quantity <= 0:
        raise RuntimeError("Quantity محاسبه‌شده صفر است.")

    if signal == "LONG":
        side = OrderSides.BUY
    else:
        side = OrderSides.SELL

    print(
        f"ENTRY {signal} "
        f"SYMBOL={SYMBOL} "
        f"PRICE={price} "
        f"QTY={quantity}"
    )

    # --------------------------------------------------------
    # REAL TRADING
    # --------------------------------------------------------

    if not LIVE_TRADING:

        msg = (
            "🧪 ATI FUTURES PAPER\n\n"
            f"SYMBOL: {SYMBOL}\n"
            f"SIGNAL: {signal}\n"
            f"PRICE: {price}\n"
            f"QTY: {quantity}\n"
            f"LEVERAGE: {LEVERAGE}\n"
            "LIVE: OFF\n"
            "❌ سفارش واقعی ارسال نشد."
        )

        print(msg)
        telegram(msg)

        return None

    order = client.new_order(
        symbol=SYMBOL,
        side=side,
        type=OrderTypes.MARKET,
        quantity=str(quantity),
    )

    print("REAL ORDER:", order)

    msg = (
        "🚨 ATI FUTURES REAL ORDER\n\n"
        f"SYMBOL: {SYMBOL}\n"
        f"SIDE: {signal}\n"
        f"PRICE: {price}\n"
        f"QTY: {quantity}\n"
        f"LEVERAGE: {LEVERAGE}X\n"
        f"TP: +{TP_PERCENT}%\n"
        f"SL: -{SL_PERCENT}%\n"
        "🔴 LIVE TRADING: ON"
    )

    telegram(msg)

    return order


# ============================================================
# SL / TP
# ============================================================

def set_sl_tp(position):

    try:

        position_id = int(
            position.get("positionId")
            or position.get("id")
        )

        entry = Decimal(
            str(
                position.get("entryPrice")
                or position.get("avgPrice")
                or position.get("price")
            )
        )

        side = str(
            position.get("side")
            or position.get("positionSide")
            or ""
        ).upper()

        if "SHORT" in side or side == "SELL":

            tp = entry * (
                Decimal("1") - TP_PERCENT / Decimal("100")
            )

            sl = entry * (
                Decimal("1") + SL_PERCENT / Decimal("100")
            )

        else:

            tp = entry * (
                Decimal("1") + TP_PERCENT / Decimal("100")
            )

            sl = entry * (
                Decimal("1") - SL_PERCENT / Decimal("100")
            )

        tp = tp.quantize(Decimal("0.01"))
        sl = sl.quantize(Decimal("0.01"))

        result = client.position_sl_tp(
            position_id=position_id,
            symbol=SYMBOL,
            sl_price=str(sl),
            tp_price=str(tp),
        )

        print("SL/TP:", result)

        telegram(
            "🛡 ATI FUTURES SL/TP SET\n\n"
            f"SYMBOL: {SYMBOL}\n"
            f"ENTRY: {entry}\n"
            f"TP: {tp}\n"
            f"SL: {sl}"
        )

        return result

    except Exception as e:

        print("SL/TP ERROR:", e)

        telegram(
            "⚠️ ATI FUTURES SL/TP ERROR\n\n"
            f"{e}"
        )

        return None


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 50)
    print("ATI FUTURES REAL BOT")
    print("=" * 50)

    telegram(
        "💓 ATI FUTURES ALIVE\n\n"
        f"SYMBOL: {SYMBOL}\n"
        f"INTERVAL: {INTERVAL}\n"
        f"LEVERAGE: {LEVERAGE}X\n"
        f"ORDER: {ORDER_USDT} USDT\n"
        f"TP: +{TP_PERCENT}%\n"
        f"SL: -{SL_PERCENT}%\n"
        f"LIVE: {LIVE_TRADING}"
    )

    # ------------------------------------------
    # FUTURES PING
    # ------------------------------------------

    print("PING:", client.ping())

    # ------------------------------------------
    # EXCHANGE INFO
    # ------------------------------------------

    info = client.exchange_info(
        symbol=SYMBOL
    )

    print("EXCHANGE INFO OK")

    # ------------------------------------------
    # LEVERAGE
    # ------------------------------------------

    if LIVE_TRADING:
        set_leverage()

    # ------------------------------------------
    # EXISTING POSITION
    # ------------------------------------------

    position = get_position()

    if position:

        print("OPEN POSITION FOUND")

        telegram(
            "⏸ ATI FUTURES\n\n"
            f"پوزیشن باز برای {SYMBOL} وجود دارد.\n"
            "ورود جدید انجام نشد."
        )

        return

    # ------------------------------------------
    # MARKET DATA
    # ------------------------------------------

    candles = get_klines()

    price = candles[-2]["close"]

    print("LAST CLOSED PRICE:", price)

    # ------------------------------------------
    # SIGNAL
    # ------------------------------------------

    signal = get_signal(candles)

    print("SIGNAL:", signal)

    if not signal:

        telegram(
            "📊 ATI FUTURES\n\n"
            f"{SYMBOL}\n"
            f"PRICE: {price}\n\n"
            "⏳ سیگنال معتبر وجود ندارد.\n"
            "❌ معامله‌ای انجام نشد."
        )

        return

    # ------------------------------------------
    # ENTRY
    # ------------------------------------------

    order = open_position(
        signal,
        price,
    )

    if not order:
        return

    # ------------------------------------------
    # WAIT FOR POSITION
    # ------------------------------------------

    time.sleep(2)

    position = get_position()

    if position:
        set_sl_tp(position)

    print("DONE")


if __name__ == "__main__":
    try:
        main()

    except Exception as e:

        print("ATI FUTURES ERROR:", repr(e))

        telegram(
            "❌ ATI FUTURES ERROR\n\n"
            f"{repr(e)}"
        )

        raise
