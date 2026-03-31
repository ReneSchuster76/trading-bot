from flask import Flask, request, jsonify
import os
import time
import requests
from datetime import datetime, timedelta

app = Flask(__name__)

# =========================================
# ENV VARS (Railway)
# =========================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MIN_RR = float(os.getenv("MIN_RR", 2.0))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", 300))
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

USE_FINNHUB = os.getenv("USE_FINNHUB", "false").lower() == "true"
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")

last_signal_time = {}

# einfacher Cache, damit nicht bei jedem Signal neu gezogen wird
earnings_cache = {}
EARNINGS_CACHE_SECONDS = 1800  # 30 Minuten


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
    except Exception:
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


def get_earnings_label(ticker):
    """
    Finnhub Earnings-Check:
    - nutzt Cache
    - schaut auf heute bis +14 Tage
    - gibt kompakte Ausgabe für Telegram zurück
    """
    if not USE_FINNHUB:
        return "-"

    if not FINNHUB_API_KEY:
        log("⚠️ USE_FINNHUB aktiv, aber FINNHUB_API_KEY fehlt")
        return "-"

    now_ts = time.time()
    cached = earnings_cache.get(ticker)

    if cached and (now_ts - cached["ts"] < EARNINGS_CACHE_SECONDS):
        return cached["value"]

    try:
        today = datetime.utcnow().date()
        to_date = today + timedelta(days=14)

        url = "https://finnhub.io/api/v1/calendar/earnings"
        params = {
            "symbol": ticker,
            "from": today.isoformat(),
            "to": to_date.isoformat(),
            "token": FINNHUB_API_KEY
        }

        r = requests.get(url, params=params, timeout=2.5)
        data = r.json()

        log(f"📅 Finnhub Earnings Raw: {data}")

        cal = data.get("earningsCalendar", [])
        label = "-"

        if cal:
            item = cal[0]
            earnings_date_str = item.get("date")

            if earnings_date_str:
                earnings_date = datetime.strptime(earnings_date_str, "%Y-%m-%d").date()
                delta = (earnings_date - today).days

                if delta == 0:
                    label = "heute"
                elif delta == 1:
                    label = "morgen"
                else:
                    label = earnings_date_str

        earnings_cache[ticker] = {
            "ts": now_ts,
            "value": label
        }

        return label

    except Exception as e:
        log(f"❌ Finnhub Earnings Fehler: {e}")
        return "-"


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


def build_no_trade_message(ticker, signal, setup_type, reason, rr=None, quality=None, earnings_label="-"):
    rr_text = "-" if rr is None else f"{rr:.2f}"

    return (
        f"⛔ NO-TRADE\n"
        f"{ticker} | {signal} | {setup_type}\n\n"
        f"RR: {rr_text}\n"
        f"Qualität: {quality or '-'}\n"
        f"📅 Earnings: {earnings_label}\n"
        f"Grund: {reason}"
    )


def build_risk_message(
    ticker, signal, setup_type,
    entry, stop, take, rr,
    quality, session_label, volume_status, vwap_position,
    reason, earnings_label="-"
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
        f"VWAP: {vwap_position}\n"
        f"📅 Earnings: {earnings_label}\n\n"
        f"Fazit: {reason}"
    )


def build_signal_message(
    ticker, signal, setup_type,
    entry, stop, take, rr,
    quality, session_label, volume_status, vwap_position,
    earnings_label="-"
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
        f"VWAP: {vwap_position}\n"
        f"📅 Earnings: {earnings_label}\n\n"
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

        earnings_label = get_earnings_label(ticker)

        log(f"Signal={signal} | Ticker={ticker} | Setup={setup_type}")
        log(f"Entry={entry} Stop={stop} Take={take} RR={rr}")
        log(f"Earnings={earnings_label}")

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
                f"RR zu klein ({rr})" if rr is not None else "RR fehlt",
                rr, quality_grade, earnings_label
            )
            send_telegram_message(msg)
            return jsonify({"status": "rr_fail"}), 200

        # VALIDIERUNG
        if signal == "LONG" and stop >= entry:
            send_telegram_message(
                build_no_trade_message(
                    ticker, signal, setup_type,
                    "Stop falsch", rr, quality_grade, earnings_label
                )
            )
            return jsonify({"status": "invalid_long"}), 200

        if signal == "LONG" and take <= entry:
            send_telegram_message(
                build_no_trade_message(
                    ticker, signal, setup_type,
                    "Take falsch", rr, quality_grade, earnings_label
                )
            )
            return jsonify({"status": "invalid_long_take"}), 200

        if signal == "SHORT" and stop <= entry:
            send_telegram_message(
                build_no_trade_message(
                    ticker, signal, setup_type,
                    "Stop falsch", rr, quality_grade, earnings_label
                )
            )
            return jsonify({"status": "invalid_short"}), 200

        if signal == "SHORT" and take >= entry:
            send_telegram_message(
                build_no_trade_message(
                    ticker, signal, setup_type,
                    "Take falsch", rr, quality_grade, earnings_label
                )
            )
            return jsonify({"status": "invalid_short_take"}), 200

        # EARNINGS HARTER BLOCK
        if earnings_label == "heute":
            send_telegram_message(
                build_no_trade_message(
                    ticker=ticker,
                    signal=signal,
                    setup_type=setup_type,
                    reason="Earnings heute",
                    rr=rr,
                    quality=quality_grade,
                    earnings_label=earnings_label
                )
            )
            return jsonify({"status": "earnings_today_block"}), 200

        # RISIKO
        risks = []

        if quality_grade == "C":
            risks.append("Qualität C")

        if volume_status.upper() == "LOW":
            risks.append("Volumen niedrig")

        if "OUTSIDE" in session_label.upper():
            risks.append("außerhalb Session")

        if earnings_label == "morgen":
            risks.append("Earnings morgen")

        if risks:
            msg = build_risk_message(
                ticker, signal, setup_type,
                entry, stop, take, rr,
                quality_grade, session_label,
                volume_status, vwap_position,
                ", ".join(risks),
                earnings_label
            )
            sent = send_telegram_message(msg)
            if sent:
                set_cooldown(ticker)
            return jsonify({"status": "risk_sent"}), 200

        # NORMAL
        msg = build_signal_message(
            ticker, signal, setup_type,
            entry, stop, take, rr,
            quality_grade, session_label,
            volume_status, vwap_position,
            earnings_label
        )

        sent = send_telegram_message(msg)
        if sent:
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
