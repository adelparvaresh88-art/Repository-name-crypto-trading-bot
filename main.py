import os

# =========================================================
# ATI FUTURES V9.2
# CREDENTIAL FIX
#
# اول Secretهای قدیمی TABDIL را می‌خواند.
# اگر نبودند، TABDEAL را امتحان می‌کند.
# =========================================================

def env_first(*names):
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


API_KEY = env_first(
    "TABDIL_API_KEY",
    "TABDEAL_API_KEY",
    "TABDIL_KEY",
    "TABDEAL_KEY",
)

API_SECRET = env_first(
    "TABDIL_API_SECRET",
    "TABDEAL_API_SECRET",
    "TABDIL_SECRET",
    "TABDEAL_SECRET",
)

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()

REAL_TRADING = (
    os.getenv(
        "REAL_TRADING",
        "true"
    ).lower()
    == "true"
)

ORDER_USDT = float(
    os.getenv(
        "ORDER_USDT",
        "2"
    )
)

LEVERAGE = int(
    os.getenv(
        "LEVERAGE",
        "3"
    )
)

print(
    "🔐 API KEY:",
    "FOUND" if API_KEY else "MISSING"
)

print(
    "🔐 API SECRET:",
    "FOUND" if API_SECRET else "MISSING"
)

print(
    "💵 ORDER:",
    ORDER_USDT,
    "USDT"
)

print(
    "⚡ LEVERAGE:",
    LEVERAGE,
    "x"
)

print(
    "🔒 REAL TRADING:",
    REAL_TRADING
)
