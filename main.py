name: Run ATI Bot

on:
  workflow_dispatch:

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
          pip install -r requirements.txt

      - name: Show Python
        run: |
          python --version

      - name: Test Telegram
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          python - <<'PY'
          import os
          import requests

          token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
          chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

          print("Telegram token:", "FOUND" if token else "MISSING")
          print("Telegram chat ID:", "FOUND" if chat_id else "MISSING")

          if not token or not chat_id:
              raise SystemExit("TELEGRAM SECRET ERROR")

          url = f"https://api.telegram.org/bot{token}/sendMessage"

          response = requests.post(
              url,
              json={
                  "chat_id": chat_id,
                  "text": "✅ ATI BOT TELEGRAM TEST\n\nTelegram connection is working."
              },
              timeout=20
          )

          print("Telegram HTTP:", response.status_code)

          if response.status_code != 200:
              print(response.text[:500])
              raise SystemExit("TELEGRAM SEND ERROR")

          print("TELEGRAM TEST: OK")
          PY

      - name: Run ATI Bot
        env:
          TABDEAL_API_KEY: ${{ secrets.TABDEAL_API_KEY }}
          TABDEAL_API_SECRET: ${{ secrets.TABDEAL_API_SECRET }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          python main.py
