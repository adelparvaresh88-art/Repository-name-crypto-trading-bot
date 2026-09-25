import os

from tabdeal.future import Future
from tabdeal.enums import OrderSides, OrderTypes

API_KEY = os.getenv("TABDEAL_API_KEY")
API_SECRET = os.getenv("TABDEAL_API_SECRET")

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"
ORDER_QTY = os.getenv("ORDER_QTY", "0.001")


def execute_real_futures_order(side):
    if not LIVE_TRADING:
        return {
            "status": "DISABLED",
            "message": "REAL TRADING IS DISABLED"
        }

    if not API_KEY or not API_SECRET:
        return {
            "status": "ERROR",
            "message": "TABDEAL API KEY/SECRET MISSING"
        }

    try:
        client = Future(API_KEY, API_SECRET)

        # بررسی اتصال Futures
        client.ping()
        client.exchange_info()

        order = client.new_order(
            symbol="BTCUSDT",
            side=(
                OrderSides.BUY
                if side.upper() == "BUY"
                else OrderSides.SELL
            ),
            type=OrderTypes.MARKET,
            quantity=ORDER_QTY,
        )

        return {
            "status": "ORDER_SENT",
            "order": order
        }

    except Exception as e:
    return {
        "status": "ERROR",
        "message": f"{type(e).__name__}: {repr(e)}"
    }
