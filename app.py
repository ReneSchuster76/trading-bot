import os
import requests
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)

# ENV Variablen
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    requests.post(url, json=payload, timeout=20)


@app.route("/")
def home():
    return "Bot läuft!", 200


@app.route("/alert", methods=["POST"])
def alert():
    data = request.get_json(silent=True) or {}
    print("ALERT:", data)

    signal = str(data.get("signal", "")).upper()
    ticker = str(data.get("ticker", "UNBEKANNT"))
    trigger = str(data.get("trigger", ""))
    vwap = str(data.get("vwap", ""))
    volume = str(data.get("volume", ""))

    prompt = f"""
Du bist ein strenger Trading-Filter für US-Aktien.

Regeln:
Antworte NUR mit genau einem dieser Werte:
A-LONG
A-SHORT
B-LONG
B-SHORT
NO-TRADE

Daten:
Ticker: {ticker}
Signal: {signal}
Trigger: {trigger}
VWAP: {vwap}
Volume: {volume}
"""

    decision = "NO-TRADE"

    if OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)

            response = client.responses.create(
                model="gpt-4.1-mini",
                input=prompt
            )

            decision = (response.output_text or "").strip().upper()

        except Exception as e:
            print("OpenAI Fehler:", e)
            decision = "NO-TRADE"

    message = (
        f"{decision}\n"
        f"{ticker}\n"
        f"{trigger}\n"
        f"VWAP: {vwap}\n"
        f"Volume: {volume}"
    )

    send_telegram_message(message)

    return {"status": "ok"}, 200
