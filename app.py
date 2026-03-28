import os
import requests
from flask import Flask, request

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }
    r = requests.post(url, json=payload, timeout=20)
    print("Telegram status:", r.status_code, r.text)

@app.route('/alert', methods=['POST'])
def alert():
    data = request.get_json(silent=True) or {}
    print("ALERT:", data)

    message = f"Signal: {data.get('signal')} | {data.get('ticker')}"
    send_telegram_message(message)

    return "OK", 200

@app.route('/')
def home():
    return "Bot läuft!", 200

import os

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
