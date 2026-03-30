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

MIN_RR = 1.8
COOLDOWN_SECONDS = 300
DEBUG = True

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
        trigger = data.get("trigger")

        entry = safe_float(data.get("entry"))
        stop = safe_float(data.get("stop"))
        take = safe_float(data.get("take"))
        rr = safe_float(data.get("rr"))

        log(f"Signal={signal} | Ticker={ticker}")
        log(f"Entry={entry} Stop={stop} Take={take} RR={rr}")

        # =========================
        # COOL DOWN
        # =========================
        if in_cooldown(ticker):
            log("⛔ Cooldown aktiv")
            return jsonify({"status": "cooldown"}), 200

        # =========================
        # DEBUG FALLBACK (WICHTIG)
        # =========================
        if entry is None or stop is None or take is None:
            log("⚠️ FEHLENDE DATEN → DEBUG TELEGRAM")

            msg = (
                f"🧪 DEBUG SIGNAL\n"
                f"Ticker: {ticker}\n"
                f"Signal: {signal}\n"
                f"Trigger: {trigger}\n"
                f"Entry: {entry}\n"
                f"Stop: {stop}\n"
                f"Take: {take}\n"
                f"RR: {rr}"
            )

            send_telegram_message(msg)
            return jsonify({"status": "debug_sent"}), 200

        # =========================
        # VALIDIERUNG
        # =========================
        if rr is None or rr < MIN_RR:
            log("⛔ RR zu klein")
            return jsonify({"status": "rr_fail"}), 200

        if signal == "LONG" and stop >= entry:
            log("⛔ LONG ungültig")
            return jsonify({"status": "invalid_long"}), 200

        if signal == "SHORT" and stop <= entry:
            log("⛔ SHORT ungültig")
            return jsonify({"status": "invalid_short"}), 200

        # =========================
        # TELEGRAM SENDEN
        # =========================
        msg = (
            f"🚀 SIGNAL\n"
            f"Ticker: {ticker}\n"
            f"Signal: {signal}\n"
            f"Entry: {entry}\n"
            f"Stop: {stop}\n"
            f"Take: {take}\n"
            f"RR: {rr}"
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
