import os
import threading
import requests
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def send_telegram_message(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram ENV fehlt.")
        return

url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        print("Telegram:", response.status_code, response.text)
    except Exception as e:
        print("Telegram Fehler:", e)


def process_alert(data: dict) -> None:
    signal = str(data.get("signal", "UNBEKANNT")).upper()
    ticker = str(data.get("ticker", "UNBEKANNT")).upper()
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

    decision = signal
    reason = "Keine AI-Bewertung"

    if OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)

            prompt = f"""
Du bist ein strenger Daytrading-Filter für US-Aktien.

Bewerte dieses Signal nur mit einem dieser Urteile:
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
"""

            response = client.responses.create(
                model="gpt-4.1-mini",
                input=prompt
            )

            output = (response.output_text or "").strip()
            lines = [line.strip() for line in output.splitlines() if line.strip()]

            if len(lines) >= 1:
                decision = lines[0].upper()
            if len(lines) >= 2:
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
    elif "NO-TRADE" in decision:
        emoji = "⛔"

    message = (
        f"{emoji} {decision}\n"
        f"Ticker: {ticker}\n"
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
