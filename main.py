import os
from tabdeal.future import Future

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

print("⚡ ATI FUTURES TEST")
print()

if not API_KEY:
    print("❌ TABDEAL_API_KEY پیدا نشد")
    raise SystemExit(1)

if not API_SECRET:
    print("❌ TABDEAL_API_SECRET پیدا نشد")
    raise SystemExit(1)

print("🔑 API KEY: OK")
print("🔐 API SECRET: OK")
print("📡 در حال اتصال به Futures Tabdeal...")

try:
    client = Future(API_KEY, API_SECRET)

    client.ping()

    print("✅ FUTURES CONNECTION: OK")
    print("🛡 هیچ معامله‌ای ارسال نشد")
    print("🛡 REAL TRADING: DISABLED")

except Exception as e:
    print("❌ FUTURES CONNECTION ERROR")
    print(type(e).__name__)
    print(str(e))
    raise
