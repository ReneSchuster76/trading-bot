from flask import Flask, request, jsonify
import os
import time
import requests

app = Flask(__name__)

# =========================================
# ENV VARS (Railway)
# =========================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MIN_RR = float(os.getenv("MIN_RR", 2.0))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", 300))
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

last_signal_time = {}


# =========================================
# HELPERS
# =========================================

def log(msg):
    if DEBUG:
        print(msg)


def safe_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except:
        return None


def in_cooldown(ticker):
    now = time.time()
    last = last_signal_time.get(ticker)

    if not last:
        return False

    return (now - last) < COOLDOWN_SECONDS


def set_cooldown(ticker):
    last_signal_time[ticker] = time.time()


def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("❌ Telegram Variablen fehlen")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }

    try:
        log(f"📤 Sende Telegram an {TELEGRAM_CHAT_ID}")
        r = requests.post(url, json=payload, timeout=10)

        log(f"📩 Status: {r.status_code}")
        log(f"📩 Antwort: {r.text}")

        return r.status_code == 200

    except Exception as e:
        log(f"❌ Telegram Fehler: {e}")
        return False


def build_debug_message(ticker, signal, trigger, setup_type, entry, stop, take, rr):
    return (
        f"🧪 DEBUG SIGNAL\n"
        f"{ticker} | {signal} | {setup_type}\n\n"
        f"Trigger: {trigger}\n"
        f"Entry: {entry}\n"
        f"Stop: {stop}\n"
        f"Take: {take}\n"
        f"RR: {rr}"
    )


def build_no_trade_message(ticker, signal, setup_type, reason, rr=None, quality=None):
    rr_text = "-" if rr is None else f"{rr:.2f}"

    return (
        f"⛔ NO-TRADE\n"
        f"{ticker} | {signal} | {setup_type}\n\n"
        f"RR: {rr_text}\n"
        f"Qualität: {quality or '-'}\n"
        f"Grund: {reason}"
    )


def build_risk_message(
    ticker, signal, setup_type,
    entry, stop, take, rr,
    quality, session_label, volume_status, vwap_position,
    reason
):
    return (
        f"⚠️ SIGNAL MIT RISIKO\n"
        f"{ticker} | {signal} | {setup_type}\n\n"
        f"Entry: {entry:.2f}\n"
        f"Stop: {stop:.2f}\n"
        f"Take: {take:.2f}\n"
        f"RR: {rr:.2f}\n\n"
        f"Qualität: {quality}\n"
        f"Session: {session_label}\n"
        f"Volumen: {volume_status}\n"
        f"VWAP: {vwap_position}\n\n"
        f"Fazit: {reason}"
    )


def build_signal_message(
    ticker, signal, setup_type,
    entry, stop, take, rr,
    quality, session_label, volume_status, vwap_position
):
    return (
        f"🚀 SIGNAL\n"
        f"{ticker} | {signal} | {setup_type}\n\n"
        f"Entry: {entry:.2f}\n"
        f"Stop: {stop:.2f}\n"
        f"Take: {take:.2f}\n"
        f"RR: {rr:.2f}\n\n"
        f"Qualität: {quality}\n"
        f"Session: {session_label}\n"
        f"Volumen: {volume_status}\n"
        f"VWAP: {vwap_position}\n\n"
        f"Fazit: Trade möglich"
    )


# =========================================
# ROUTE
# =========================================

@app.route("/alert", methods=["POST"])
def alert():
    try:
        log("")
        log("====== ALERT START ======")

        data = request.get_json(silent=True)
        log(f"DATA: {data}")

        if not data:
            return jsonify({"status": "no_data"}), 400

        signal = str(data.get("signal", "")).upper()
        ticker = str(data.get("ticker", "")).upper()
        trigger = str(data.get("trigger", ""))
        setup_type = str(data.get("setup_type", "UNKNOWN")).upper()

        entry = safe_float(data.get("entry"))
        stop = safe_float(data.get("stop"))
        take = safe_float(data.get("take"))
        rr = safe_float(data.get("rr"))

        session_label = str(data.get("session_label", "-"))
        volume_status = str(data.get("volume_status", "-"))
        vwap_position = str(data.get("vwap_position", "-"))
        quality_grade = str(data.get("quality_grade", "-")).upper()

        log(f"Signal={signal} | Ticker={ticker} | Setup={setup_type}")
        log(f"Entry={entry} Stop={stop} Take={take} RR={rr}")

        # COOL DOWN
        if in_cooldown(ticker):
            log("⛔ Cooldown aktiv")
            return jsonify({"status": "cooldown"}), 200

        # DEBUG
        if entry is None or stop is None or take is None:
            msg = build_debug_message(
                ticker, signal, trigger, setup_type,
                entry, stop, take, rr
            )
            send_telegram_message(msg)
            return jsonify({"status": "debug_sent"}), 200

        # RR CHECK
        if rr is None or rr < MIN_RR:
            msg = build_no_trade_message(
                ticker, signal, setup_type,
                f"RR zu klein ({rr})", rr, quality_grade
            )
            send_telegram_message(msg)
            return jsonify({"status": "rr_fail"}), 200

        # VALIDIERUNG
        if signal == "LONG" and stop >= entry:
            send_telegram_message(build_no_trade_message(ticker, signal, setup_type, "Stop falsch"))
            return jsonify({"status": "invalid_long"}), 200

        if signal == "SHORT" and stop <= entry:
            send_telegram_message(build_no_trade_message(ticker, signal, setup_type, "Stop falsch"))
            return jsonify({"status": "invalid_short"}), 200

        # RISIKO
        risks = []
        if quality_grade == "C":
            risks.append("Qualität C")
        if volume_status.upper() == "LOW":
            risks.append("Volumen niedrig")
        if "OUTSIDE" in session_label.upper():
            risks.append("außerhalb Session")

        if risks:
            msg = build_risk_message(
                ticker, signal, setup_type,
                entry, stop, take, rr,
                quality_grade, session_label,
                volume_status, vwap_position,
                ", ".join(risks)
            )
            send_telegram_message(msg)
            set_cooldown(ticker)
            return jsonify({"status": "risk_sent"}), 200

        # NORMAL
        msg = build_signal_message(
            ticker, signal, setup_type,
            entry, stop, take, rr,
            quality_grade, session_label,
            volume_status, vwap_position
        )

        send_telegram_message(msg)
        set_cooldown(ticker)

        return jsonify({"status": "sent"}), 200

    except Exception as e:
        log(f"❌ ERROR: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 500


# =========================================
# START
# =========================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
