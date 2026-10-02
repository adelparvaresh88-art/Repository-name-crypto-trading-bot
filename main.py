import os
import time
import hmac
import hashlib
from decimal import Decimal
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.24
# TABDEAL SPOT
# AUTH DIAGNOSTIC + POSTMAN STYLE SIGNATURE
# ============================================================

VERSION = "V40.2.24"

BASE_URL = "https://api1.tabdeal.org"
AUTH_ENDPOINT = "/r/api/v1/account"

# ============================================================
# CREDENTIALS
# ============================================================

API_KEY = (
    os.getenv("TABDEAL_API_KEY", "").strip()
    or os.getenv("TABDIL_API_KEY", "").strip()
)

API_SECRET = (
    os.getenv("TABDEAL_API_SECRET", "").strip()
    or os.getenv("TABDIL_API_SECRET", "").strip()
)

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()


# ============================================================
# SETTINGS
# ============================================================

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "false")
    .strip()
    .lower()
    == "true"
)

try:
    ORDER_USDT = Decimal(
        os.getenv("ORDER_USDT", "2")
    )
except Exception:
    ORDER_USDT = Decimal("2")

try:
    RECV_WINDOW = int(
        os.getenv("RECV_WINDOW", "5000")
    )
except Exception:
    RECV_WINDOW = 5000


# ============================================================
# HARD SAFETY LOCK
# ============================================================

REAL_BUY_LOCKED = True

MAX_SCAN_MARKETS = 15
TOP_RESULTS = 10

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": f"ATI-Crypto-Bot/{VERSION}",
    "Accept": "application/json",
})


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):

    if not TELEGRAM_BOT_TOKEN:
        return False

    if not TELEGRAM_CHAT_ID:
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:
        response = SESSION.post(
            url,
            json=payload,
            timeout=15,
        )

        return response.ok

    except Exception:
        return False


# ============================================================
# JSON
# ============================================================

def safe_json(response):

    try:
        return response.json()
    except Exception:
        return None


# ============================================================
# POSTMAN STYLE SIGNATURE
# ============================================================

def make_signature():

    # EXACT INTEGER MILLISECOND TIMESTAMP
    timestamp = int(
        time.time() * 1000
    )

    # IMPORTANT:
    # Order is exactly:
    # timestamp -> recvWindow

    query_string = (
        f"timestamp={timestamp}"
        f"&recvWindow={RECV_WINDOW}"
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return (
        timestamp,
        query_string,
        signature,
    )


# ============================================================
# AUTHENTICATION
# ============================================================

def authenticate():

    if not API_KEY or not API_SECRET:

        return {
            "ok": False,
            "http": 0,
            "code": "MISSING",
            "msg": "API KEY OR API SECRET IS MISSING",
            "timestamp": 0,
        }

    try:

        timestamp, query_string, signature = (
            make_signature()
        )

        # The exact signed string is sent.
        final_query = (
            query_string
            + "&signature="
            + signature
        )

        url = (
            BASE_URL
            + AUTH_ENDPOINT
            + "?"
            + final_query
        )

        response = SESSION.get(
            url,
            headers={
                "X-MBX-APIKEY": API_KEY,
            },
            timeout=20,
        )

        data = safe_json(response)

        if response.status_code == 200:

            return {
                "ok": True,
                "http": 200,
                "code": "",
                "msg": "OK",
                "timestamp": timestamp,
            }

        code = ""

        if isinstance(data, dict):
            code = data.get(
                "code",
                ""
            )

        msg = ""

        if isinstance(data, dict):
            msg = data.get(
                "msg",
                ""
            )

        if not msg:
            msg = response.text[:500]

        return {
            "ok": False,
            "http": response.status_code,
            "code": code,
            "msg": msg,
            "timestamp": timestamp,
        }

    except requests.RequestException as e:

        return {
            "ok": False,
            "http": 0,
            "code": "NETWORK",
            "msg": str(e)[:500],
            "timestamp": 0,
        }

    except Exception as e:

        return {
            "ok": False,
            "http": 0,
            "code": "PYTHON",
            "msg": (
                f"{type(e).__name__}: "
                f"{str(e)[:450]}"
            ),
            "timestamp": 0,
        }


# ============================================================
# AUTH RESULT MESSAGE
# ============================================================

def send_auth_failure(result):

    telegram_send(
        f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
        f"❌ HTTP: {result.get('http')}\n"
        f"❌ CODE: {result.get('code')}\n"
        f"❌ MSG: {result.get('msg')}\n\n"
        f"🔐 METHOD: HMAC-SHA256\n"
        f"🔢 TIMESTAMP: INTEGER\n"
        f"🔢 TIMESTAMP: {result.get('timestamp')}\n"
        f"🔐 PARAM ORDER:\n"
        f"timestamp → recvWindow\n"
        f"🔑 HEADER: X-MBX-APIKEY\n"
        f"📡 ENDPOINT:\n"
        f"{AUTH_ENDPOINT}\n\n"
        f"🛑 REAL BUY LOCKED\n"
        f"🛑 NO ORDER WAS SENT\n"
        f"🕐 {utc_now()}"
    )


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    url = (
        BASE_URL
        + "/r/api/v1/exchangeInfo"
    )

    response = SESSION.get(
        url,
        timeout=20,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# MARKET LIST
# ============================================================

def get_usdt_markets(exchange_info):

    markets = []

    if not isinstance(
        exchange_info,
        dict
    ):
        return markets

    symbols = exchange_info.get(
        "symbols",
        []
    )

    if not isinstance(
        symbols,
        list
    ):
        return markets

    for item in symbols:

        if not isinstance(
            item,
            dict
        ):
            continue

        symbol = (
            item.get("symbol")
            or item.get("tabdealSymbol")
            or ""
        )

        symbol = str(
            symbol
        ).upper().strip()

        if symbol.endswith("USDT"):
            markets.append(item)

    return markets


# ============================================================
# RECENT TRADES
# ============================================================

def get_recent_trades(symbol):

    url = (
        BASE_URL
        + "/r/api/v1/trades"
    )

    params = {
        "symbol": symbol,
        "limit": 1000,
    }

    try:

        response = SESSION.get(
            url,
            params=params,
            timeout=20,
        )

        if response.status_code != 200:
            return []

        data = response.json()

        if isinstance(
            data,
            list
        ):
            return data

        if isinstance(
            data,
            dict
        ):

            for key in (
                "data",
                "trades",
                "result",
            ):

                value = data.get(
                    key
                )

                if isinstance(
                    value,
                    list
                ):
                    return value

        return []

    except Exception:
        return []


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(
        item,
        dict
    ):
        return None

    price = (
        item.get("price")
        or item.get("p")
    )

    quantity = (
        item.get("qty")
        or item.get("quantity")
        or item.get("q")
    )

    if price is None:
        return None

    try:

        price = float(price)

        if quantity is None:
            quantity = 0
        else:
            quantity = float(quantity)

        if price <= 0:
            return None

        return {
            "price": price,
            "qty": quantity,
        }

    except Exception:
        return None


# ============================================================
# MOMENTUM
# ============================================================

def calculate_score(trades):

    parsed = []

    for item in trades:

        trade = parse_trade(item)

        if trade:
            parsed.append(trade)

    if len(parsed) < 20:
        return None

    prices = [
        x["price"]
        for x in parsed
    ]

    if len(prices) < 20:
        return None

    first_price = prices[0]
    last_price = prices[-1]

    if first_price <= 0:
        return None

    move = (
        (last_price - first_price)
        / first_price
        * 100
    )

    score = 0

    if move >= 0.5:
        score += 3

    if move >= 1:
        score += 2

    if move >= 2:
        score += 2

    if move >= 4:
        score += 2

    if last_price > max(
        prices[-10:-1]
    ):
        score += 2

    if last_price > prices[-10]:
        score += 1

    # Simple pressure estimate
    # based on isBuyerMaker when available.

    buy_volume = 0.0
    sell_volume = 0.0

    for item in trades[-100:]:

        if not isinstance(
            item,
            dict
        ):
            continue

        qty = (
            item.get("qty")
            or item.get("quantity")
            or item.get("q")
            or 0
        )

        try:
            qty = abs(float(qty))
        except Exception:
            qty = 0

        maker = item.get(
            "isBuyerMaker"
        )

        if maker is True:
            sell_volume += qty
        else:
            buy_volume += qty

    total = (
        buy_volume
        + sell_volume
    )

    if total > 0:

        pressure = (
            buy_volume
            / total
            * 100
        )

    else:
        pressure = 50.0

    if pressure >= 55:
        score += 1

    if pressure >= 60:
        score += 2

    if pressure >= 65:
        score += 2

    return {
        "score": score,
        "price": last_price,
        "move": move,
        "pressure": pressure,
        "trades": len(parsed),
    }


# ============================================================
# SCAN
# ============================================================

def scan_markets(markets):

    results = []

    selected = markets[
        :MAX_SCAN_MARKETS
    ]

    for market in selected:

        symbol = (
            market.get("symbol")
            or market.get("tabdealSymbol")
            or ""
        )

        symbol = str(
            symbol
        ).upper()

        if not symbol.endswith("USDT"):
            continue

        trades = get_recent_trades(
            symbol
        )

        if not trades:
            continue

        result = calculate_score(
            trades
        )

        if not result:
            continue

        result["symbol"] = symbol

        results.append(result)

        time.sleep(0.10)

    results.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    return results[
        :TOP_RESULTS
    ]


# ============================================================
# RESULT MESSAGE
# ============================================================

def format_results(results):

    if not results:

        return (
            f"📊 ATI SCAN {VERSION}\n\n"
            f"❌ NO CANDIDATES\n\n"
            f"🔒 REAL BUY: LOCKED\n"
            f"🛑 NO ORDER SENT\n"
            f"🕐 {utc_now()}"
        )

    lines = [
        f"📊 ATI TOP {len(results)} "
        f"{VERSION}",
        "",
        "🟢 MOMENTUM WATCHLIST",
        "",
    ]

    for index, item in enumerate(
        results,
        1
    ):

        lines.append(
            f"{index}. "
            f"{item['symbol']}\n"
            f"   💰 PRICE: "
            f"{item['price']:.10g}\n"
            f"   📊 SCORE: "
            f"{item['score']}\n"
            f"   📈 MOVE: "
            f"{item['move']:+.2f}%\n"
            f"   💪 PRESSURE: "
            f"{item['pressure']:.1f}%"
        )

    lines.extend([
        "",
        "🔒 REAL BUY: LOCKED",
        "🛑 NO ORDER SENT",
        f"🕐 {utc_now()}",
    ])

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():

    telegram_send(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 AUTH DIAGNOSTIC: STARTING\n"
        f"🔐 HMAC-SHA256\n"
        f"🔢 INTEGER TIMESTAMP\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🔒 BUY LOCK: ACTIVE\n"
        f"🕐 {utc_now()}"
    )

    # ========================================================
    # AUTH
    # ========================================================

    auth = authenticate()

    if not auth["ok"]:

        # IMPORTANT:
        # The actual error is included here.
        send_auth_failure(auth)

        # SAFE STOP contains the same information.
        telegram_send(
            f"🛑 ATI SAFE STOP {VERSION}\n\n"
            f"🚫 PRIVATE API AUTH FAILED\n"
            f"❌ HTTP: {auth.get('http')}\n"
            f"❌ CODE: {auth.get('code')}\n"
            f"❌ MSG: {auth.get('msg')}\n\n"
            f"🔒 REAL BUY DISABLED\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return

    # ========================================================
    # AUTH SUCCESS
    # ========================================================

    telegram_send(
        f"✅ ATI API AUTH OK {VERSION}\n\n"
        f"🟢 PRIVATE API CONNECTED\n"
        f"🟢 ACCOUNT ENDPOINT OK\n"
        f"🔐 HMAC-SHA256 OK\n"
        f"📡 {AUTH_ENDPOINT}\n\n"
        f"🔒 REAL BUY: LOCKED\n"
        f"🛑 NO ORDER SENT\n"
        f"🕐 {utc_now()}"
    )

    # ========================================================
    # EXCHANGE INFO
    # ========================================================

    try:

        exchange_info = (
            get_exchange_info()
        )

        markets = (
            get_usdt_markets(
                exchange_info
            )
        )

    except Exception as e:

        telegram_send(
            f"🚨 ATI EXCHANGE ERROR "
            f"{VERSION}\n\n"
            f"❌ {type(e).__name__}\n"
            f"❌ {str(e)[:500]}\n\n"
            f"🔒 REAL BUY LOCKED\n"
            f"🛑 NO ORDER SENT\n"
            f"🕐 {utc_now()}"
        )

        return

    telegram_send(
        f"📊 ATI EXCHANGE INFO "
        f"{VERSION}\n\n"
        f"🟢 AUTH: OK\n"
        f"📊 USDT MARKETS: "
        f"{len(markets)}\n"
        f"🔎 SCAN: "
        f"{min(len(markets), MAX_SCAN_MARKETS)}\n"
        f"🔒 REAL BUY: LOCKED\n"
        f"🕐 {utc_now()}"
    )

    # ========================================================
    # SCAN
    # ========================================================

    try:

        results = scan_markets(
            markets
        )

        telegram_send(
            format_results(
                results
            )
        )

    except Exception as e:

        telegram_send(
            f"🚨 ATI SCAN ERROR "
            f"{VERSION}\n\n"
            f"❌ {type(e).__name__}\n"
            f"❌ {str(e)[:500]}\n\n"
            f"🔒 REAL BUY LOCKED\n"
            f"🛑 NO ORDER SENT\n"
            f"🕐 {utc_now()}"
        )

        return

    # ========================================================
    # HEARTBEAT
    # ========================================================

    telegram_send(
        f"💓 ATI HEARTBEAT "
        f"{VERSION}\n\n"
        f"✅ RUN COMPLETED\n"
        f"🔐 AUTH: OK\n"
        f"📊 MARKETS: {len(markets)}\n"
        f"🔎 SCANNED: "
        f"{min(len(markets), MAX_SCAN_MARKETS)}\n"
        f"🔒 REAL BUY: LOCKED\n"
        f"🛑 NO ORDER SENT\n"
        f"🕐 {utc_now()}"
    )


if __name__ == "__main__":
    main()
