import os
import requests
from datetime import datetime, timezone

SYMBOL = "BTCUSDT"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets missing")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print("TELEGRAM:", r.status_code)
        return r.ok

    except Exception as e:
        print("TELEGRAM ERROR:", repr(e))
        return False


def get_btc_price():

    url = (
        "https://api1.tabdeal.org/r/api/v1/depth"
        "?symbol=BTCUSDT&limit=5"
    )

    try:

        print("TABDEAL URL:", url)

        r = requests.get(
            url,
            headers={
                "User-Agent": "ATI-Crypto-Bot/1.0",
                "Accept": "application/json"
            },
            timeout=20
        )

        print("TABDEAL HTTP:", r.status_code)
        print("TABDEAL RESPONSE:", r.text[:1000])

        if r.status_code != 200:
            return None

        data = r.json()

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if not bids or not asks:
            print("No bids/asks returned")
            return None

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])

        price = (best_bid + best_ask) / 2

        print("BEST BID:", best_bid)
        print("BEST ASK:", best_ask)
        print("BTCUSDT PRICE:", price)

        return price

    except Exception as e:

        print("PRICE ERROR:", repr(e))

        return None


def main():

    print("=" * 60)
    print("ATI CRYPTO BOT")
    print("TABDEAL BTCUSDT")
    print("=" * 60)

    price = get_btc_price()

    if price is None:

        message = """🛡 ATI SAFETY

❌ BTCUSDT price could not be read.

Tabdeal API did not return a valid order book.

🚫 No trade was sent.
"""

        print(message)

        send_telegram(message)

        return

    now = datetime.now(timezone.utc)

    message = f"""⚡ ATI CRYPTO BOT

₿ BTC/USDT
⏱ Timeframe: 5m

✅ TABDEAL API CONNECTED

💰 BTCUSDT: ${price:,.2f}

🕐 UTC:
{now.strftime("%Y-%m-%d %H:%M:%S")}

📡 PRICE API: OK

🛡 MODE: PAPER / TEST
🚫 REAL TRADING DISABLED
"""

    print(message)

    if send_telegram(message):
        print("TELEGRAM MESSAGE SENT")
    else:
        print("TELEGRAM MESSAGE FAILED")


if __name__ == "__main__":
    main()
