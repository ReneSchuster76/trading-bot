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
    r = requests.post(url, json=payload, timeout=20)
    print("Telegram:", r.status_code, r.text)


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
- Antworte NUR mit genau einem dieser Werte:
A-LONG
A-SHORT
B-LONG
B-SHORT
NO-TRADE

Signal-Daten:
Ticker: {ticker}
Signal: {signal}
Trigger: {trigger}
VWAP: {vwap}
Volume: {volume}
"""

    api_key = os.getenv("OPENAI_API_KEY")
    print("OPENAI KEY vorhanden:", bool(api_key))

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
            print("OpenAI Fehler:", e)
            decision = "NO-TRADE"

    print("Decision:", decision)

    message = (
        f"{decision}\n"
        f"{ticker}\n"
        f"{trigger}\n"
        f"VWAP: {vwap}\n"
        f"Volume: {volume}"
    )

    send_telegram_message(message)
    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
