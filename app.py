import os
import threading
import requests
from flask import Flask, jsonify, request
from openai import OpenAI

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram fehlt")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    })


def safe_float(x):
    try:
        return float(x)
    except:
        return None


def evaluate_leverage(decision, entry, stop, rr):
    entry = safe_float(entry)
    stop = safe_float(stop)
    rr = safe_float(rr)

    if not entry or not stop or not rr:
        return "UNBEKANNT"

    dist = abs(entry - stop) / entry

    if decision.startswith("A-") and rr >= 1.8:
        if dist < 0.015:
            return "GEEIGNET"
        elif dist < 0.025:
            return "OK"
        else:
            return "ZU WEIT"

    return "NICHT"


def calculate_ko(entry, stop, signal):
    entry = safe_float(entry)
    stop = safe_float(stop)

    if not entry or not stop:
        return None, None

    if signal == "LONG":
        ko = stop * 0.996
        dist = entry - ko
    elif signal == "SHORT":
        ko = stop * 1.004
        dist = ko - entry
    else:
        return None, None

    if dist <= 0:
        return None, None

    leverage = entry / dist
    return round(ko, 2), round(leverage, 1)


def process_alert(data):
    ticker = str(data.get("ticker", "")).upper()
    signal = str(data.get("signal", "")).upper()
    entry = data.get("entry")
    stop = data.get("stop")
    take = data.get("take")
    rr = data.get("rr")
    volume = data.get("volume")

    print("DATA:", data)

    decision = "NO-TRADE"
    reason = "Filter"

    # Hard Filter
    if not ticker or not entry or not stop:
        reason = "Fehlende Daten"

    elif safe_float(rr) and safe_float(rr) < 1.5:
        reason = "RR zu klein"

    elif OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)

            prompt = f"""
Du bist ein strenger Daytrader.

Antworte nur:
A-LONG, A-SHORT, B-LONG, B-SHORT oder NO-TRADE

Dann kurze Begründung.

Ticker: {ticker}
Signal: {signal}
Entry: {entry}
Stop: {stop}
Take: {take}
RR: {rr}
Volume: {volume}
"""

            res = client.responses.create(
                model="gpt-4.1-mini",
                input=prompt
            )

            out = res.output_text.strip().split("\n")

            if out:
                decision = out[0].strip().upper()
                if len(out) > 1:
                    reason = out[1]

        except Exception as e:
            print(e)
            reason = "AI Fehler"

    lev = evaluate_leverage(decision, entry, stop, rr)
    ko, lev_est = calculate_ko(entry, stop, signal)

    emoji = "⚪"
    if "LONG" in decision:
        emoji = "🟢"
    elif "SHORT" in decision:
        emoji = "🔴"

    msg = f"""{emoji} {decision} | {ticker}

Entry: {entry}
Stop: {stop}
Take: {take}
RR: {rr}

Hebel 12-15x: {lev}

KO: {ko}
Hebel ca: {lev_est}x

Grund:
{reason}
"""

    send_telegram(msg)


@app.route("/")
def home():
    return "Bot läuft!", 200


@app.route("/alert", methods=["POST"])
def alert():
    data = request.get_json(silent=True) or {}

    threading.Thread(
        target=process_alert,
        args=(data,),
        daemon=True
    ).start()

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
