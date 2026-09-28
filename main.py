name: Run ATI Bot

on:
  workflow_dispatch:

# ============================================================
# ATI BOT - ONLY ONE RUN AT A TIME
# اگر اجرای قبلی فعال باشد، اجرای جدید وارد صف می‌شود
# و همزمان اجرا نمی‌شود.
# ============================================================

concurrency:
  group: ati-crypto-bot
  cancel-in-progress: false

jobs:
  run-bot:

    runs-on: ubuntu-latest

    steps:

      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install requirements
        run: |
          python -m pip install --upgrade pip
          pip install requests

      - name: Run ATI Bot
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}

          TABDEAL_API_KEY: ${{ secrets.TABDEAL_API_KEY }}
          TABDIL_API_KEY: ${{ secrets.TABDIL_API_KEY }}
          TABDIL_API_SECRET: ${{ secrets.TABDIL_API_SECRET }}

          LIVE_TRADING: ${{ secrets.LIVE_TRADING }}
          ORDER_QTY: ${{ secrets.ORDER_QTY }}

        run: |
          python main.py
