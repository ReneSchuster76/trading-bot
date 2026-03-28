import os
import requests
from flask import Flask, request

app = Flask(__name__)

# Umgebungsvariablen (Railway -> Variables setzen!)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    try:
        r = requests.post(url, json=payload, timeout=20)
        print("Telegram status:", r.status_code, r.text)
    except Exception as e:
        print("Telegram error:", e)

@app.route("/", methods=["GET"])
def home():
    return "Bot läuft!", 200

@app.route("/alert", methods=["POST"])
def alert():
    data = request.get_json(silent=True) or {}
    print("ALERT:",
