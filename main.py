import os
import json
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

ORDER_USDT = float(os.getenv("ORDER_USDT", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

Safety: this diagnostic version never places orders.

LIVE_TRADING = False

def telegram(message):
if not BOT_TOKEN or not CHAT_ID:
print("Telegram secrets are missing.")
return

try:
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": message,
        },
        timeout=15,
    )
    response.raise_for_status()
    print("Telegram message sent.")
except Exception as exc:
    print(f"Telegram error: {exc}")

def main():
now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

telegram(
    "🔄 ATI TABDEAL FUTURES\n"
    f"Time: {now}\n"
    "Starting connection test...\n"
    "LIVE TRADING: OFF"
)

try:
    # Use the official Tabdeal Futures SDK, not Binance.
    from tabdeal.future import Future

    client = Future(
        API_KEY or None,
        API_SECRET or None,
    )

    ping_result = client.ping()
    print("Tabdeal Futures ping:", json.dumps(
        ping_result, ensure_ascii=False, default=str
    ))

    info = client.exchange_info()

    if isinstance(info, dict):
        markets = (
            info.get("symbols")
            or info.get("data")
            or info.get("markets")
            or []
        )
    elif isinstance(info, list):
        markets = info
    else:
        markets = []

    usdt_markets = []
    for market in markets:
        if not isinstance(market, dict):
            continue

        symbol = str(market.get("symbol", "")).upper()
        quote = str(market.get("quoteAsset", "")).upper()
        status = str(market.get("status", "")).upper()

        if (
            symbol.endswith("USDT")
            and (not status or status in ("TRADING", "ENABLED"))
            and (not quote or quote == "USDT")
        ):
            usdt_markets.append(symbol)

    usdt_markets = sorted(set(usdt_markets))

    # Report SDK methods so unsupported candle/leverage methods
    # are not guessed or silently treated as working.
    method_names = sorted(
        name for name in dir(client)
        if not name.startswith("_") and callable(getattr(client, name, None))
    )

    print("Markets response type:", type(info).__name__)
    print("Markets found:", len(markets))
    print("USDT markets found:", len(usdt_markets))
    print("Available SDK methods:", ", ".join(method_names))

    sample = ", ".join(usdt_markets[:15]) or "No USDT markets parsed"
    methods = ", ".join(method_names[:50]) or "No methods detected"

    telegram(
        "✅ ATI TABDEAL FUTURES CONNECTION TEST\n\n"
        f"Markets returned: {len(markets)}\n"
        f"USDT markets: {len(usdt_markets)}\n"
        f"Examples: {sample}\n\n"
        f"SDK methods: {methods}\n\n"
        f"Order size setting: {ORDER_USDT} USDT\n"
        f"Leverage setting: {LEVERAGE}x\n"
        "LIVE TRADING: OFF\n"
        "No orders were placed."
    )

except Exception as exc:
    error = f"{type(exc).__name__}: {exc}"
    print("TABDEAL FUTURES CONNECTION ERROR:", error)
    telegram(
        "❌ ATI TABDEAL FUTURES CONNECTION ERROR\n\n"
        f"{error}\n\n"
        "LIVE TRADING: OFF\n"
        "No orders were placed."
    )
    raise

if name == "main":
main()
