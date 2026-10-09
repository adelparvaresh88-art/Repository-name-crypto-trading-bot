import os
import time
import json
import math
import requests

from decimal import Decimal, ROUND_DOWN
from concurrent.futures import ThreadPoolExecutor, as_completed

from tabdeal.future import Future
from tabdeal.enums import OrderSides, OrderTypes


VERSION = "ATI FUTURES V13 REAL"

BASE_URL = os.getenv(
    "BASE_URL",
    "https://api1.tabdeal.org"
).rstrip("/")

API_KEY = os.getenv("TABDEAL_API_KEY", "")
API_SECRET = os.getenv("TABDEAL_API_SECRET", "")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

ORDER_USDT = Decimal(os.getenv("ORDER_QTY", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "false").lower() == "true"
)

TP_PCT = Decimal(os.getenv("TP_PCT", "0.02"))
SL_PCT = Decimal(os.getenv("SL_PCT", "0.01"))

MAX_MARKETS = int(os.getenv("SCAN_UNIVERSE", "75"))
WORKERS = int(os.getenv("MAX_WORKERS", "12"))
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "100"))

# برای جلوگیری از ورود چندباره در یک اجرای ربات
MAX_NEW_POSITIONS_PER_RUN = 1

# جلوگیری از استفاده از سیگنال‌های بازارهای غیر USDT
QUOTE_ASSET = "USDT"

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-Futures-V13"
})


def telegram(message):
    print(message)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=10
        )
    except Exception as exc:
        print("Telegram error:", str(exc)[:200])


def public_get(path, params=None):
    url = BASE_URL + path

    response = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:250]}"
        )

    return response.json()


def get_client():
    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDEAL_API_KEY یا TABDEAL_API_SECRET تنظیم نشده است."
        )

    return Future(
        api_key=API_KEY,
        api_secret=API_SECRET,
        base_url=BASE_URL,
        timeout=TIMEOUT,
        receive_window=5000
    )


def extract_list(data, keys):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                for nested_key in keys:
                    nested = value.get(nested_key)

                    if isinstance(nested, list):
                        return nested

    return []


def get_markets(client):
    data = client.exchange_info()

    raw = extract_list(
        data,
        ["symbols", "data", "result"]
    )

    if not raw and isinstance(data, dict):
        raise RuntimeError(
            "قالب پاسخ Futures exchangeInfo قابل شناسایی نیست: "
            + json.dumps(data, ensure_ascii=False)[:300]
        )

    markets = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        symbol = str(item.get("symbol", "")).upper()

        if not symbol.endswith(QUOTE_ASSET):
            continue

        if item.get("status") not in (None, "TRADING"):
            continue

        markets.append(item)

    # اولویت با بازارهایی است که exchangeInfo صریحاً معرفی کرده است.
    return markets[:MAX_MARKETS]


def get_klines(symbol):
    # این مسیر مربوط به API فیوچرز است.
    return public_get(
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": "5m",
            "limit": KLINE_LIMIT
        }
    )


def to_float(value):
    return float(value)


def ichimoku_signal(symbol):
    """
    فقط از کندل‌های بسته‌شده استفاده می‌کند.
    BUY: تنکان بالای کیجون و قیمت بالای ابر
    SELL: تنکان پایین کیجون و قیمت پایین ابر
    """

    data = get_klines(symbol)

    if not isinstance(data, list) or len(data) < 60:
        return {
            "symbol": symbol,
            "ready": False,
            "error": "کندل کافی دریافت نشد"
        }

    candles = []

    for row in data:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue

        candles.append({
            "time": int(row[0]),
            "high": to_float(row[2]),
            "low": to_float(row[3]),
            "close": to_float(row[4]),
            "close_time": int(row[6]) if len(row) > 6 else 0
        })

    # کندل آخر ممکن است هنوز بسته نشده باشد.
    now_ms = int(time.time() * 1000)

    if candles and candles[-1]["close_time"] > now_ms:
        candles = candles[:-1]

    if len(candles) < 60:
        return {
            "symbol": symbol,
            "ready": False,
            "error": "کندل بسته‌شده کافی نیست"
        }

    highs = [x["high"] for x in candles]
    lows = [x["low"] for x in candles]
    closes = [x["close"] for x in candles]

    def midpoint(end, period):
        start = end - period + 1

        if start < 0:
            return None

        high = max(highs[start:end + 1])
        low = min(lows[start:end + 1])

        return (high + low) / 2

    i = len(candles) - 1

    tenkan = midpoint(i, 9)
    kijun = midpoint(i, 26)

    # ابر مربوط به کندل جاری، بر اساس مقادیر محاسبه‌شده ۲۶
    # کندل قبل، محاسبه می‌شود.
    cloud_i = i - 26

    if cloud_i < 51:
        return {
            "symbol": symbol,
            "ready": False,
            "error": "داده کافی برای محاسبه ابر وجود ندارد"
        }

    tenkan_cloud = midpoint(cloud_i, 9)
    kijun_cloud = midpoint(cloud_i, 26)

    span_a = (tenkan_cloud + kijun_cloud) / 2
    span_b = midpoint(cloud_i, 52)

    close = closes[i]

    cloud_top = max(span_a, span_b)
    cloud_bottom = min(span_a, span_b)

    signal = None

    if (
        tenkan > kijun
        and close > cloud_top
    ):
        signal = "BUY"

    elif (
        tenkan < kijun
        and close < cloud_bottom
    ):
        signal = "SELL"

    return {
        "symbol": symbol,
        "ready": True,
        "signal": signal,
        "price": close,
        "tenkan": tenkan,
        "kijun": kijun,
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom
    }


def analyse_market(item):
    symbol = item.get("symbol", "")

    try:
        result = ichimoku_signal(symbol)
        result["market"] = item
        return result

    except Exception as exc:
        return {
            "symbol": symbol,
            "ready": False,
            "error": str(exc)[:200],
            "market": item
        }


def get_filters(market):
    filters = market.get("filters", [])

    result = {}

    if isinstance(filters, list):
        for item in filters:
            if isinstance(item, dict):
                result[item.get("filterType", "")] = item

    return result


def floor_to_step(value, step):
    value = Decimal(str(value))
    step = Decimal(str(step))

    if step <= 0:
        raise ValueError("گام مقدار سفارش نامعتبر است")

    return (
        (value / step).to_integral_value(
            rounding=ROUND_DOWN
        ) * step
    )


def format_quantity(market, price):
    filters = get_filters(market)

    lot = (
        filters.get("LOT_SIZE")
        or filters.get("MARKET_LOT_SIZE")
        or {}
    )

    step = lot.get("stepSize")

    if step is None:
        raise RuntimeError(
            "گام حجم قرارداد در exchangeInfo پیدا نشد"
        )

    # ORDER_USDT مبلغ مارجین هدف است؛
    # ارزش اسمی هدف موقعیت برابر مبلغ × اهرم است.
    notional = ORDER_USDT * Decimal(LEVERAGE)

    quantity = notional / Decimal(str(price))
    quantity = floor_to_step(quantity, step)

    min_qty = Decimal(str(lot.get("minQty", "0")))

    if quantity < min_qty:
        raise RuntimeError(
            f"حجم محاسبه‌شده {quantity} کمتر از حداقل {min_qty} است"
        )

    min_notional_filter = (
        filters.get("MIN_NOTIONAL")
        or filters.get("NOTIONAL")
        or {}
    )

    min_notional = min_notional_filter.get(
        "notional",
        min_notional_filter.get("minNotional")
    )

    if min_notional is not None:
        if quantity * Decimal(str(price)) < Decimal(str(min_notional)):
            raise RuntimeError(
                "ارزش سفارش از حداقل ارزش مجاز قرارداد کمتر است"
            )

    return format(quantity, "f")


def get_active_positions(client):
    data = client.get_positions()

    return extract_list(
        data,
        ["positions", "data", "result"]
    )


def has_active_position(client, symbol):
    positions = get_active_positions(client)

    for position in positions:
        if not isinstance(position, dict):
            continue

        if str(position.get("symbol", "")).upper() != symbol:
            continue

        amount = position.get(
            "positionAmt",
            position.get("quantity", position.get("positionAmount", "0"))
        )

        try:
            if Decimal(str(amount)) != 0:
                return True
        except Exception:
            pass

    return False


def order_is_accepted(order):
    if not isinstance(order, dict):
        return False

    order_id = order.get("orderId", order.get("id"))

    status = str(order.get("status", "")).upper()

    return bool(order_id) and status not in {
        "REJECTED",
        "CANCELED",
        "EXPIRED"
    }


def place_trade(client, signal):
    symbol = signal["symbol"]
    side = signal["signal"]
    price = Decimal(str(signal["price"]))
    market = signal["market"]

    if side not in ("BUY", "SELL"):
        return "NO_TRADE"

    if not LIVE_TRADING:
        return (
            f"DRY RUN: {symbol} {side}; "
            "معامله واقعی غیرفعال است."
        )

    if not API_KEY or not API_SECRET:
        raise RuntimeError("کلیدهای API تنظیم نشده‌اند")

    if price <= 0:
        raise RuntimeError("قیمت ورود نامعتبر است")

    # جلوگیری از ورود دوباره به موقعیت فعال
    if has_active_position(client, symbol):
        return f"SKIPPED: موقعیت فعال {symbol} از قبل وجود دارد."

    # اهرم را در خود صرافی تنظیم می‌کنیم.
    leverage_result = client.change_leverage(
        symbol=symbol,
        leverage=LEVERAGE
    )

    telegram(
        f"⚙️ {symbol}\n"
        f"پاسخ تنظیم اهرم {LEVERAGE}x:\n"
        f"{str(leverage_result)[:400]}"
    )

    quantity = format_quantity(market, price)

    order = client.new_order(
        symbol=symbol,
        side=OrderSides.BUY if side == "BUY" else OrderSides.SELL,
        type=OrderTypes.MARKET,
        quantity=quantity
    )

    if not order_is_accepted(order):
        raise RuntimeError(
            "پاسخ ثبت سفارش تأیید نشد: "
            + json.dumps(order, ensure_ascii=False)[:500]
        )

    order_id = order.get("orderId", order.get("id"))

    telegram(
        f"📨 سفارش ارسال شد\n"
        f"💎 {symbol}\n"
        f"📌 {side}\n"
        f"🔢 Order ID: {order_id}\n"
        f"📦 Quantity: {quantity}\n"
        f"⚠️ اکنون وضعیت موقعیت و حد سود/ضرر باید تأیید شود."
    )

    # موقعیت را پس از ثبت سفارش پیدا می‌کنیم.
    position = None

    for _ in range(8):
        time.sleep(1)

        positions = get_active_positions(client)

        for item in positions:
            if not isinstance(item, dict):
                continue

            if str(item.get("symbol", "")).upper() != symbol:
                continue

            amount = item.get(
                "positionAmt",
                item.get("quantity", item.get("positionAmount", "0"))
            )

            try:
                if Decimal(str(amount)) != 0:
                    position = item
                    break
            except Exception:
                continue

        if position:
            break

    if not position:
        raise RuntimeError(
            f"سفارش {order_id} پاسخ داشت، اما موقعیت فعال تأیید نشد. "
            "وضعیت سفارش را در صرافی بررسی کن."
        )

    position_id = position.get("positionId", position.get("id"))

    entry_price = Decimal(str(
        position.get(
            "entryPrice",
            position.get("avgPrice", price)
        )
    ))

    if not position_id:
        raise RuntimeError(
            "شناسه موقعیت برای ثبت حد سود و ضرر پیدا نشد. "
            "وضعیت حساب را فوراً بررسی کن."
        )

    if side == "BUY":
        sl_price = entry_price * (Decimal("1") - SL_PCT)
        tp_price = entry_price * (Decimal("1") + TP_PCT)
    else:
        sl_price = entry_price * (Decimal("1") + SL_PCT)
        tp_price = entry_price * (Decimal("1") - TP_PCT)

    sl_tp_result = client.position_sl_tp(
        position_id=int(position_id),
        symbol=symbol,
        sl_price=format(sl_price, "f"),
        tp_price=format(tp_price, "f")
    )

    telegram(
        f"🛡️ درخواست حد سود و ضرر ارسال شد\n"
        f"💎 {symbol}\n"
        f"🆔 Position: {position_id}\n"
        f"🛑 SL: {sl_price}\n"
        f"🎯 TP: {tp_price}\n"
        f"📩 پاسخ صرافی: {str(sl_tp_result)[:500]}"
    )

    return (
        f"ORDER SENT: {symbol} {side}; "
        f"order={order_id}; position={position_id}; "
        f"SL={sl_price}; TP={tp_price}"
    )


def main():
    start = time.time()

    telegram(
        f"💓 {VERSION}\n"
        f"📊 Futures Ichimoku Scanner\n"
        f"💵 Margin target: {ORDER_USDT} USDT\n"
        f"⚡ Leverage: {LEVERAGE}x\n"
        f"🎯 TP: {TP_PCT * 100}%\n"
        f"🛑 SL: {SL_PCT * 100}%\n"
        f"🔒 LIVE_TRADING: {LIVE_TRADING}"
    )

    try:
        client = get_client()
        markets = get_markets(client)

        if not markets:
            raise RuntimeError("هیچ قرارداد Futures معتبر پیدا نشد")

    except Exception as exc:
        telegram(
            f"❌ {VERSION}\n"
            f"راه‌اندازی یا دریافت بازار ناموفق بود:\n"
            f"{str(exc)[:700]}"
        )
        return

    results = []

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        jobs = [
            executor.submit(analyse_market, market)
            for market in markets
        ]

        for job in as_completed(jobs):
            try:
                results.append(job.result())
            except Exception as exc:
                results.append({
                    "ready": False,
                    "error": str(exc)[:200]
                })

    ready = [x for x in results if x.get("ready")]

    signals = [
        x for x in ready
        if x.get("signal") in ("BUY", "SELL")
    ]

    errors = [x for x in results if not x.get("ready")]

    elapsed = time.time() - start

    telegram(
        f"💓 {VERSION}\n\n"
        f"📊 Markets: {len(markets)}\n"
        f"📈 Ready: {len(ready)}\n"
        f"🔥 Signals: {len(signals)}\n"
        f"❌ Errors: {len(errors)}\n"
        f"⏱️ Scan: {elapsed:.2f}s\n"
        f"💵 Margin target: {ORDER_USDT} USDT\n"
        f"⚡ Leverage: {LEVERAGE}x\n"
        f"🔒 LIVE: {LIVE_TRADING}"
    )

    if not signals:
        telegram("☁️ در این دور سیگنال معتبر ایچیموکو پیدا نشد.")
        return

    # فقط یک موقعیت جدید در هر اجرا
    signal = signals[0]

    telegram(
        f"🔥 ATI FUTURES SIGNAL\n\n"
        f"💎 {signal['symbol']}\n"
        f"📌 {signal['signal']}\n"
        f"💲 Price: {signal['price']}\n"
        f"☁️ Cloud: {signal['cloud_bottom']:.8g} - "
        f"{signal['cloud_top']:.8g}\n"
        f"🔒 LIVE: {LIVE_TRADING}"
    )

    try:
        result = place_trade(client, signal)
        telegram(f"📋 نتیجه اجرا:\n{result}")

    except Exception as exc:
        telegram(
            f"❌ ATI FUTURES TRADE ERROR\n"
            f"💎 {signal['symbol']}\n"
            f"{str(exc)[:1000]}\n\n"
            f"وضعیت سفارش و موقعیت را در صرافی بررسی کن."
        )


if __name__ == "__main__":
    main()
