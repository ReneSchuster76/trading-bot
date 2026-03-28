import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(text):
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }
    r = requests.post(url, json=payload)
    print("Telegram status:", r.status_code, r.text)

@app.route('/alert', methods=['POST'])
def alert():
    data = request.json
    print("ALERT:", data)

    message = f"Signal: {data.get('signal')} | {data.get('ticker')}"
    send_telegram_message(message)

    return "OK", 200

@app.route('/')
def home():
    return "Bot läuft!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
