import os
import requests
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("8632160667:AAEih9W4KkpUMSk0eyeC_ycMGs2yEGKCRgM")
TELEGRAM_CHAT_ID = os.getenv("61941031")


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

    signal = str(data.get("signal", "")).upper()
    ticker = str(data.get("ticker", "UNBEKANNT"))
    trigger = str(data.get("trigger", ""))
    vwap = str(data.get("vwap", ""))
    volume = str(data.get("volume", ""))

    prompt = f"""
Antworte nur mit:
A-LONG, A-SHORT, B-LONG, B-SHORT oder NO-TRADE

Ticker: {ticker}
Signal: {signal}
Trigger: {trigger}
VWAP: {vwap}
Volume: {volume}
"""

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        decision = "NO-TRADE"
    else:
        try:
            client = OpenAI(api_key=api_key)
            response = client.responses.create(
                model="gpt-4.1-mini",
                input=prompt
            )
            decision = (response.output_text or "").strip().upper()
        except Exception as e:
            print("Fehler:", e)
            decision = "NO-TRADE"

    message = f"{decision}\n{ticker}\n{trigger}\nVWAP: {vwap}\nVolume: {volume}"
    send_telegram_message(message)

    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
