import os
import requests
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)


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
- Beurteile nur das eingehende Signal.
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

Logik:
- BUY kann nur LONG sein
- SELL kann nur SHORT sein
- Wenn VWAP oder Volume nicht passt, eher B oder NO-TRADE
- Wenn Trigger stark ist und VWAP + Volume passen, eher A
"""

    try:
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt
        )
        decision = (response.output_text or "").strip().upper()
        print("OpenAI decision:", decision)
    except Exception as e:
        print("OpenAI error:", e)
        decision = "NO-TRADE"

    if decision == "A-LONG":
        message = (
            f"🚀 A-LONG\n"
            f"📊 {ticker}\n"
            f"🎯 {trigger}\n"
            f"VWAP: {vwap}\n"
            f"Volumen: {volume}"
        )
        send_telegram_message(message)

    elif decision == "A-SHORT":
        message = (
            f"🔻 A-SHORT\n"
            f"📊 {ticker}\n"
            f"🎯 {trigger}\n"
            f"VWAP: {vwap}\n"
            f"Volumen: {volume}"
        )
        send_telegram_message(message)

    elif decision == "B-LONG":
        message = (
            f"🟡 B-LONG\n"
            f"📊 {ticker}\n"
            f"🎯 {trigger}\n"
            f"VWAP: {vwap}\n"
            f"Volumen: {volume}"
        )
        send_telegram_message(message)

    elif decision == "B-SHORT":
        message = (
            f"🟠 B-SHORT\n"
            f"📊 {ticker}\n"
            f"🎯 {trigger}\n"
            f"VWAP: {vwap}\n"
            f"Volumen: {volume}"
        )
        send_telegram_message(message)

    else:
        print("NO-TRADE")

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
