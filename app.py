import os
import threading
from datetime import datetime, timedelta

import requests
from flask import Flask, jsonify, request
from openai import OpenAI

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

last_trade_time = {}
COOLDOWN_MINUTES = 10
DEBUG = True


def log(*args):
    if DEBUG:
        print(*args)


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram fehlt")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )
        log("Telegram Status:", r.status_code)
        log("Telegram Antwort:", r.text)
        return r.status_code == 200
    except Exception as e:
        print("Telegram Fehler:", e)
        return False


def safe_float(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None


def get_session_label():
    now = datetime.now()
    hour = now.hour
    minute = now.minute
    total_minutes = hour * 60 + minute

    if 15 * 60 + 30 <= total_minutes <= 16 * 60 + 15:
        return "OPEN"
    if 20 * 60 <= total_minutes <= 21 * 60 + 30:
        return "POWER_HOUR"
    if 16 * 60 + 15 < total_minutes < 20 * 60:
        return "BLOCKED"
    return "OFF_HOURS"


def in_cooldown(ticker):
    now = datetime.now()

    if ticker not in last_trade_time:
        return False

    diff = now - last_trade_time[ticker]
    return diff < timedelta(minutes=COOLDOWN_MINUTES)


def evaluate_leverage(decision, entry, stop, rr):
    entry = safe_float(entry)
    stop = safe_float(stop)
    rr = safe_float(rr)

    if entry is None or stop is None or rr is None:
        return "UNBEKANNT"

    if entry <= 0:
        return "UNBEKANNT"

    dist = abs(entry - stop) / entry

    if decision.startswith("A-") and rr >= 1.8:
        if dist < 0.015:
            return "GEEIGNET"
        if dist < 0.025:
            return "OK"
        return "ZU WEIT"

    return "NICHT"


def calculate_ko(entry, stop, signal):
    entry = safe_float(entry)
    stop = safe_float(stop)

    if entry is None or stop is None:
        return None, None

    if signal == "LONG":
        ko = stop * 0.995
        dist = entry - ko
    elif signal == "SHORT":
        ko = stop * 1.005
        dist = ko - entry
    else:
        return None, None

    if dist <= 0:
        return None, None

    leverage = entry / dist
    return round(ko, 2), round(leverage, 1)


def send_debug_telegram(data, ticker, signal, trigger, entry, stop, take, rr, reason):
    msg = f"""🧪 DEBUG ALERT

Ticker: {ticker}
Signal: {signal}
Trigger: {trigger}

Entry: {entry}
Stop: {stop}
Take: {take}
RR: {rr}

Grund:
{reason}

Payload:
{data}
"""
    send_telegram(msg)


def process_alert(data):
    ticker = str(data.get("ticker", "")).upper().strip()
    signal = str(data.get("signal", "")).upper().strip()
    trigger = str(data.get("trigger", "")).strip()

    entry = data.get("entry")
    stop = data.get("stop")
    take = data.get("take")
    rr = data.get("rr")
    volume = data.get("volume")
    vwap = data.get("vwap")
    pm_high = data.get("pmHigh")
    pm_low = data.get("pmLow")
    or_high = data.get("orHigh")
    or_low = data.get("orLow")

    log("====================================")
    log("ALERT EMPFANGEN")
    log("DATA:", data)

    decision = "NO-TRADE"
    reason = "Filter"
    session = get_session_label()

    entry_f = safe_float(entry)
    stop_f = safe_float(stop)
    rr_f = safe_float(rr)
    volume_f = safe_float(volume)
    vwap_f = safe_float(vwap)
    pm_high_f = safe_float(pm_high)
    pm_low_f = safe_float(pm_low)
    or_high_f = safe_float(or_high)
    or_low_f = safe_float(or_low)

    log(f"Ticker={ticker} | Signal={signal} | Trigger={trigger}")
    log(f"Entry={entry} | Stop={stop} | Take={take} | RR={rr}")
    log(f"Session={session} | VWAP={vwap} | Volume={volume}")

    # Nur NVDA
    if ticker != "NVDA":
        reason = f"Nicht NVDA: {ticker}"
        log(reason)
        return

    # Cooldown
    if in_cooldown(ticker):
        reason = "Cooldown aktiv – Signal ignoriert"
        log(reason)
        return

    # Debug-Fallback für Testsignale mit unvollständigen Daten
    if trigger.upper() == "TEST" and (not entry or not stop or not take):
        reason = "TEST Alert ohne vollständige Daten"
        log(reason)
        send_debug_telegram(data, ticker, signal, trigger, entry, stop, take, rr, reason)
        return

    # Hard Filters
    if not entry or not stop or not take:
        reason = "Fehlende Daten"
        log(reason)
        return

    if rr_f is None or rr_f < 1.8:
        reason = "RR zu klein für NVDA PRO"
        log(reason)
        return

    if session == "BLOCKED":
        reason = "Zeitfenster blockiert"
        log(reason)
        return

    if session == "OFF_HOURS":
        reason = "Außerhalb Handelszeit"
        log(reason)
        return

    if volume_f is not None and volume_f < 300000:
        reason = "Volumen zu schwach"
        log(reason)
        return

    if signal not in {"LONG", "SHORT"}:
        reason = "Ungültiges Signal"
        log(reason)
        return

    # VWAP-Richtung
    if signal == "LONG" and vwap_f is not None and entry_f is not None and entry_f < vwap_f:
        reason = "LONG unter VWAP"
        log(reason)
        return

    if signal == "SHORT" and vwap_f is not None and entry_f is not None and entry_f > vwap_f:
        reason = "SHORT über VWAP"
        log(reason)
        return

    # einfacher Chop-/Range-Filter
    if (
        entry_f is not None
        and pm_high_f is not None
        and pm_low_f is not None
        and pm_low_f < entry_f < pm_high_f
        and trigger.lower() in {"", "test", "signal"}
    ):
        reason = "Zu wenig Kontext in PM-Range"
        log(reason)
        return

    # Entry zu spät / Stop zu weit
    if entry_f is not None and stop_f is not None:
        dist = abs(entry_f - stop_f) / entry_f
        if dist > 0.03:
            reason = "Entry zu spät / Stop zu weit"
            log(reason)
            return

    # OR optional als Zusatzkontext, kein harter Filter
    _ = or_high_f, or_low_f

    if OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)

            prompt = f"""
Du bist ein extrem strenger NVDA Intraday Filter für Knockout-Trades.

Erlaubte Antworten:
A-LONG
A-SHORT
B-LONG
B-SHORT
NO-TRADE

Regeln:
- Nur sehr saubere Setups hoch bewerten
- A nur bei klarem Momentum, sauberem Trigger und guter Struktur
- B nur bei brauchbaren, aber nicht perfekten Setups
- NO-TRADE bei Unsicherheit, Chop, schwachem Druck oder spätem Entry
- Sei streng, da hoher Hebel genutzt wird

Antworte exakt in 2 Zeilen:
Zeile 1: nur das Urteil
Zeile 2: kurze deutsche Begründung

Daten:
Ticker: {ticker}
Signal: {signal}
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
Session: {session}
""".strip()

            res = client.responses.create(
                model="gpt-4.1-mini",
                input=prompt
            )

            out = (res.output_text or "").strip().split("\n")

            if out:
                decision = out[0].strip().upper()
                if len(out) > 1:
                    reason = out[1].strip()

            log("AI Entscheidung:", decision)
            log("AI Grund:", reason)

        except Exception as e:
            print("OpenAI Fehler:", e)
            reason = f"AI Fehler: {e}"
            return
    else:
        reason = "OPENAI_API_KEY fehlt"
        log(reason)
        return

    lev = evaluate_leverage(decision, entry, stop, rr)
    ko, lev_est = calculate_ko(entry, stop, signal)

    log(f"Leverage Bewertung: {lev}")
    log(f"KO: {ko} | Hebel ca: {lev_est}")

    # Nur A-Setups mit passendem Hebel
    if not decision.startswith("A-"):
        log("Kein A-Setup -> kein Telegram")
        return

    if lev not in {"GEEIGNET", "OK"}:
        log("Hebel-Bewertung nicht passend -> kein Telegram")
        return

    last_trade_time[ticker] = datetime.now()

    emoji = "⚪"
    if "LONG" in decision:
        emoji = "🟢"
    elif "SHORT" in decision:
        emoji = "🔴"

    msg = f"""{emoji} {decision} | {ticker}

Session: {session}
Trigger: {trigger}

Entry: {entry}
Stop: {stop}
Take: {take}
RR: {rr}
VWAP: {vwap}
Volume: {volume}

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

    log("POST /alert empfangen")
    log("JSON:", data)

    threading.Thread(
        target=process_alert,
        args=(data,),
        daemon=True
    ).start()

    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
