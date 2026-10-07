name: ATI FUTURES BOT

on:
  workflow_dispatch:

  schedule:
    - cron: "*/5 * * * *"

permissions:
  contents: read

concurrency:
  group: ati-futures-bot
  cancel-in-progress: false

jobs:
  run-bot:
    runs-on: ubuntu-latest
    timeout-minutes: 4

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Upgrade pip
        run: |
          python -m pip install --upgrade pip

      - name: Install dependencies
        run: |
          pip install --upgrade tabdeal-python
          pip install requests websocket-client

      - name: Check installed Tabdeal version
        run: |
          python -m pip show tabdeal-python || true
          python -c "import tabdeal; print('TABDEAL SDK OK')"

      - name: Run ATI Futures
        env:
          TABDIL_API_KEY: ${{ secrets.TABDIL_API_KEY }}
          TABDIL_API_SECRET: ${{ secrets.TABDIL_API_SECRET }}

          TABDEAL_API_KEY: ${{ secrets.TABDEAL_API_KEY }}
          TABDEAL_API_SECRET: ${{ secrets.TABDEAL_API_SECRET }}

          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}

          LIVE_TRADING: ${{ secrets.LIVE_TRADING }}

          FUTURES_LEVERAGE: ${{ secrets.FUTURES_LEVERAGE }}
          FUTURES_ORDER_USDT: ${{ secrets.FUTURES_ORDER_USDT }}

          TP_PERCENT: ${{ secrets.TP_PERCENT }}
          SL_PERCENT: ${{ secrets.SL_PERCENT }}

        run: |
          python main.py
