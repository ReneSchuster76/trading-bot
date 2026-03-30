import os
import threading

import requests
from flask import Flask, jsonify, request
from openai import OpenAI

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def send_telegram_message(message: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram ENV fehlt.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        print("Telegram:", response.status_code, response.text)
    except Exception as e:
        print("Telegram Fehler:", e)


def process_alert(data: dict) -> None:
    ticker = str(data.get("ticker", ""))
    signal = str(data.get("signal", ""))
    trigger = str(data.get("trigger", ""))
    entry = str(data.get("entry", ""))
    stop = str(data.get("stop", ""))
    take = str(data.get("take", ""))
    rr = str(data.get("rr", ""))
    vwap = str(data.get("vwap", ""))
    volume = str(data.get("volume", ""))
    pm_high = str(data.get("pmHigh", ""))
    pm_low = str(data.get("pmLow", ""))
    or_high = str(data.get("orHigh", ""))
    or_low = str(data.get("orLow", ""))

    print("ALERT DATA:", data)

    decision = "NO-TRADE"
    reason = "Kein Urteil"

    if OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)

            prompt = f"""
Du bist ein strenger Daytrading-Filter für US-Aktien.

Bewerte das Signal nur mit einem dieser Urteile:
A-LONG
A-SHORT
B-LONG
B-SHORT
NO-TRADE

Antworte in genau 2 Zeilen:
Zeile 1: nur das Urteil
Zeile 2: kurze Begründung auf Deutsch

Daten:
Signal: {signal}
Ticker: {ticker}
Trigger: {trigger}
Entry: {entry}
Stop: {stop}
Take: {take}
RR: {rr}
VWAP: {vwap}
Volume: {volume}
PM High: {pm_high}
PM Low: {pm_low}
OR High: {or_high}
OR Low: {or_low}
""".strip()

            response = client.responses.create(
                model="gpt-4.1-mini",
                input=prompt,
            )

            output = (response.output_text or "").strip()
            lines = [line.strip() for line in output.splitlines() if line.strip()]

            if lines:
                decision = lines[0].upper()
                if len(lines) > 1:
                    reason = lines[1]

        except Exception as e:
            print("OpenAI Fehler:", e)
            decision = "NO-TRADE"
            reason = f"OpenAI Fehler: {e}"

    emoji = "⚪"
    if "LONG" in decision:
        emoji = "🟢"
    elif "SHORT" in decision:
        emoji = "🔴"

    message = (
        f"{emoji} {decision}\n"
        f"Ticker: {ticker}\n"
        f"Signal: {signal}\n"
        f"Trigger: {trigger}\n"
        f"Entry: {entry}\n"
        f"Stop: {stop}\n"
        f"Take: {take}\n"
        f"RR: {rr}\n"
        f"VWAP: {vwap}\n"
        f"Volume: {volume}\n"
        f"PM High: {pm_high}\n"
        f"PM Low: {pm_low}\n"
        f"OR High: {or_high}\n"
        f"OR Low: {or_low}\n"
        f"Grund: {reason}"
    )

    send_telegram_message(message)


@app.route("/", methods=["GET"])
def home():
    return "Bot läuft!", 200


@app.route("/alert", methods=["POST"])
def alert():
    data = request.get_json(silent=True) or {}

    threading.Thread(
        target=process_alert,
        args=(data,),
        daemon=True,
    ).start()

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
