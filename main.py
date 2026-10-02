import os
import time
import json
import hmac
import hashlib
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.23
# TABDEAL SPOT
# AUTH FIX - EXACT POSTMAN STYLE
# ============================================================

VERSION = "V40.2.23"

BASE_URL = "https://api1.tabdeal.org"

# ------------------------------------------------------------
# ENV
# ------------------------------------------------------------

API_KEY = (
    os.getenv("TABDEAL_API_KEY", "").strip()
    or os.getenv("TABDIL_API_KEY", "").strip()
)

API_SECRET = (
    os.getenv("TABDEAL_API_SECRET", "").strip()
    or os.getenv("TABDIL_API_SECRET", "").strip()
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").strip().lower() == "true"

try:
    ORDER_USDT = Decimal(os.getenv("ORDER_USDT", "2"))
except Exception:
    ORDER_USDT = Decimal("2")

try:
    RECV_WINDOW = int(os.getenv("RECV_WINDOW", "5000"))
except Exception:
    RECV_WINDOW = 5000


# ------------------------------------------------------------
# HARD SAFETY LOCK
# ------------------------------------------------------------

REAL_BUY_LOCKED = True

AUTH_ENDPOINT = "/r/api/v1/account"

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
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:
        r = SESSION.post(
            url,
            json=payload,
            timeout=15,
        )

        return r.ok

    except Exception:
        return False


# ============================================================
# SAFE JSON
# ============================================================

def safe_json(response):
    try:
        return response.json()
    except Exception:
        return None


# ============================================================
# POSTMAN-STYLE SIGNATURE
# ============================================================

def build_postman_signature():
    """
    Exact style based on Tabdeal official Postman collection:

    timestamp = Date.now()
    recvWindow = configured value

    queryString:
        timestamp=XXXXX&recvWindow=5000

    HMAC-SHA256(queryString, API_SECRET)

    IMPORTANT:
    The exact same queryString is then sent to the server.
    """

    timestamp = int(time.time() * 1000)

    params = [
        ("timestamp", str(timestamp)),
        ("recvWindow", str(RECV_WINDOW)),
    ]

    query_string = "&".join(
        f"{key}={value}"
        for key, value in params
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return timestamp, query_string, signature


# ============================================================
# AUTHENTICATED ACCOUNT REQUEST
# ============================================================

def authenticate():
    if not API_KEY or not API_SECRET:

        msg = (
            f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
            f"❌ API KEY / SECRET MISSING\n\n"
            f"CHECK:\n"
            f"• TABDEAL_API_KEY\n"
            f"• TABDEAL_API_SECRET\n"
            f"• TABDIL_API_KEY\n"
            f"• TABDIL_API_SECRET\n\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        telegram_send(msg)
        return False

    try:

        timestamp, query_string, signature = (
            build_postman_signature()
        )

        # EXACT query that was signed
        final_query = (
            f"{query_string}"
            f"&signature={signature}"
        )

        url = (
            f"{BASE_URL}"
            f"{AUTH_ENDPOINT}"
            f"?{final_query}"
        )

        response = SESSION.get(
            url,
            headers={
                "X-MBX-APIKEY": API_KEY,
            },
            timeout=20,
        )

        data = safe_json(response)

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        if response.status_code == 200:

            telegram_send(
                f"✅ ATI API AUTH OK {VERSION}\n\n"
                f"🟢 PRIVATE API CONNECTED\n"
                f"🟢 ACCOUNT ENDPOINT OK\n"
                f"🔐 HMAC-SHA256 OK\n"
                f"🔢 INTEGER TIMESTAMP\n"
                f"📡 /r/api/v1/account\n\n"
                f"🛑 REAL BUY: LOCKED\n"
                f"🕐 {utc_now()}"
            )

            return True

        # ----------------------------------------------------
        # ERROR DETAILS
        # ----------------------------------------------------

        code = ""
        server_msg = ""

        if isinstance(data, dict):
            code = data.get("code", "")
            server_msg = data.get("msg", "")

        if not server_msg:
            server_msg = response.text[:500]

        telegram_send(
            f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
            f"❌ HTTP {response.status_code}\n"
            f"❌ CODE: {code}\n"
            f"❌ MSG: {server_msg}\n\n"
            f"🔐 METHOD: HMAC-SHA256\n"
            f"🔢 TIMESTAMP: INTEGER\n"
            f"🔢 TIMESTAMP VALUE: {timestamp}\n"
            f"🔐 QUERY: timestamp + recvWindow\n"
            f"🔑 HEADER: X-MBX-APIKEY\n"
            f"📡 ENDPOINT: {AUTH_ENDPOINT}\n\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return False

    except requests.RequestException as e:

        telegram_send(
            f"🚨 ATI API AUTH NETWORK ERROR {VERSION}\n\n"
            f"❌ {str(e)[:500]}\n\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return False

    except Exception as e:

        telegram_send(
            f"🚨 ATI API AUTH CODE ERROR {VERSION}\n\n"
            f"❌ {type(e).__name__}\n"
            f"❌ {str(e)[:500]}\n\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return False


# ============================================================
# PUBLIC API
# ============================================================

def get_exchange_info():

    url = f"{BASE_URL}/r/api/v1/exchangeInfo"

    response = SESSION.get(
        url,
        timeout=20,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# MARKET EXTRACTION
# ============================================================

def get_usdt_markets(exchange_info):

    markets = []

    if not isinstance(exchange_info, dict):
        return markets

    symbols = exchange_info.get("symbols", [])

    if not isinstance(symbols, list):
        return markets

    for item in symbols:

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("tabdealSymbol")
            or ""
        )

        symbol = str(symbol).upper().strip()

        if symbol.endswith("USDT"):
            markets.append(item)

    return markets


# ============================================================
# TRADE DATA
# ============================================================

def get_recent_trades(symbol):

    url = f"{BASE_URL}/r/api/v1/trades"

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

        if isinstance(data, list):
            return data

        if isinstance(data, dict):

            for key in (
                "data",
                "trades",
                "result",
            ):
                value = data.get(key)

                if isinstance(value, list):
                    return value

        return []

    except Exception:
        return []


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(item, dict):
        return None

    price = (
        item.get("price")
        or item.get("p")
    )

    qty = (
        item.get("qty")
        or item.get("quantity")
        or item.get("q")
    )

    if price is None:
        return None

    try:

        price = float(price)

        if qty is None:
            qty = 0
        else:
            qty = float(qty)

        if price <= 0:
            return None

        return {
            "price": price,
            "qty": qty,
        }

    except Exception:
        return None


# ============================================================
# MOMENTUM SCORE
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

    recent = prices[-20:]
    old = prices[:20]

    if not recent or not old:
        return None

    first_price = old[0]
    last_price = recent[-1]

    if first_price <= 0:
        return None

    move_percent = (
        (last_price - first_price)
        / first_price
        * 100
    )

    # Recent half
    half = len(parsed) // 2

    first_half = parsed[:half]
    second_half = parsed[half:]

    buy_volume = 0.0
    sell_volume = 0.0

    for item in second_half:

        qty = abs(item["qty"])

        # Tabdeal trade APIs may expose isBuyerMaker.
        maker = item.get("isBuyerMaker")

        if maker is True:
            sell_volume += qty
        else:
            buy_volume += qty

    total_volume = buy_volume + sell_volume

    if total_volume > 0:
        pressure = (
            buy_volume
            / total_volume
            * 100
        )
    else:
        pressure = 50.0

    score = 0

    # Momentum
    if move_percent >= 0.5:
        score += 3

    if move_percent >= 1:
        score += 2

    if move_percent >= 2:
        score += 2

    if move_percent >= 4:
        score += 2

    # Buying pressure
    if pressure >= 55:
        score += 1

    if pressure >= 60:
        score += 2

    if pressure >= 65:
        score += 2

    # Price structure
    if len(prices) >= 10:

        previous = prices[-10]

        if last_price > previous:
            score += 1

        if last_price > max(prices[-10:-1]):
            score += 2

    return {
        "score": score,
        "price": last_price,
        "move": move_percent,
        "pressure": pressure,
        "trades": len(parsed),
    }


# ============================================================
# SCAN
# ============================================================

def scan_markets(markets):

    results = []

    selected = markets[:MAX_SCAN_MARKETS]

    for market in selected:

        symbol = (
            market.get("symbol")
            or market.get("tabdealSymbol")
            or ""
        )

        symbol = str(symbol).upper()

        if not symbol.endswith("USDT"):
            continue

        trades = get_recent_trades(symbol)

        if not trades:
            continue

        result = calculate_score(trades)

        if not result:
            continue

        result["symbol"] = symbol

        results.append(result)

        # Small delay protects public API
        time.sleep(0.10)

    results.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    return results[:TOP_RESULTS]


# ============================================================
# FORMAT SIGNALS
# ============================================================

def format_results(results):

    if not results:

        return (
            f"📊 ATI SCAN {VERSION}\n\n"
            f"❌ NO CANDIDATES\n\n"
            f"🛑 REAL BUY: LOCKED\n"
            f"🕐 {utc_now()}"
        )

    lines = [
        f"📊 ATI TOP {len(results)} {VERSION}",
        "",
        "🟢 MOMENTUM WATCHLIST",
        "",
    ]

    for i, item in enumerate(results, 1):

        symbol = item["symbol"]
        score = item["score"]
        price = item["price"]
        move = item["move"]
        pressure = item["pressure"]

        lines.append(
            f"{i}. {symbol}\n"
            f"   💰 {price:.10g}\n"
            f"   📊 SCORE: {score}\n"
            f"   📈 MOVE: {move:+.2f}%\n"
            f"   💪 PRESSURE: {pressure:.1f}%"
        )

    lines.extend([
        "",
        "🛑 REAL BUY: LOCKED",
        "🛑 NO ORDER WAS SENT",
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
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED CANDLE: YES\n"
        f"💵 ORDER MODE: FIXED USDT\n"
        f"💰 ORDER AMOUNT: {ORDER_USDT} USDT\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🔒 BUY LOCK: ACTIVE\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # Credentials
    # --------------------------------------------------------

    if not API_KEY or not API_SECRET:

        telegram_send(
            f"🚨 ATI STOP {VERSION}\n\n"
            f"❌ API CREDENTIALS NOT FOUND\n"
            f"❌ Check GitHub Secrets\n\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # PRIVATE AUTH
    # --------------------------------------------------------

    authenticated = authenticate()

    if not authenticated:

        telegram_send(
            f"🛑 ATI SAFE STOP {VERSION}\n\n"
            f"🚫 PRIVATE API AUTH FAILED\n"
            f"🚫 REAL BUY DISABLED\n"
            f"❌ NO ORDER WAS SENT\n\n"
            f"🔒 AUTH FAILED = SAFE STOP\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # PUBLIC EXCHANGE INFO
    # --------------------------------------------------------

    try:

        exchange_info = get_exchange_info()

        markets = get_usdt_markets(exchange_info)

        telegram_send(
            f"📡 ATI EXCHANGE INFO {VERSION}\n\n"
            f"📊 USDT MARKETS: {len(markets)}\n"
            f"🔎 DEEP SCAN: {min(len(markets), MAX_SCAN_MARKETS)}\n"
            f"🟢 PRIVATE AUTH: OK\n"
            f"🔒 REAL BUY: LOCKED\n"
            f"🕐 {utc_now()}"
        )

    except Exception as e:

        telegram_send(
            f"🚨 ATI EXCHANGE ERROR {VERSION}\n\n"
            f"❌ {type(e).__name__}\n"
            f"❌ {str(e)[:500]}\n\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    try:

        results = scan_markets(markets)

        telegram_send(
            format_results(results)
        )

    except Exception as e:

        telegram_send(
            f"🚨 ATI SCAN ERROR {VERSION}\n\n"
            f"❌ {type(e).__name__}\n"
            f"❌ {str(e)[:500]}\n\n"
            f"🛑 NO ORDER WAS SENT\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # FINAL HEARTBEAT
    # --------------------------------------------------------

    telegram_send(
        f"💓 ATI HEARTBEAT {VERSION}\n\n"
        f"✅ RUN COMPLETED\n"
        f"🔐 PRIVATE AUTH: OK\n"
        f"📊 MARKETS: {len(markets)}\n"
        f"🔎 SCANNED: {min(len(markets), MAX_SCAN_MARKETS)}\n"
        f"🔒 REAL BUY: LOCKED\n"
        f"🛑 NO ORDER SENT\n"
        f"🕐 {utc_now()}"
    )


if __name__ == "__main__":
    main()
