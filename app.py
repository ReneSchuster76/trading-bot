import csv
import os
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, request
from openai import OpenAI

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

LOG_FILE = "alerts_log.csv"
LOCAL_TZ = ZoneInfo("Europe/Berlin")

# Verhalten
A_ONLY_MODE = False          # True = nur A-Setups an Telegram
SEND_B_SETUPS = True         # False = B-Setups nur loggen
COOLDOWN_MINUTES = 10        # kein erneutes Signal für gleichen Ticker im Zeitfenster

# Laufzeit-Cooldown-Speicher
last_alert_times = {}


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


def safe_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_round(value, digits=2):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def is_us_stock(ticker: str) -> bool:
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return False

    blocked = {
        "BTCUSD", "ETHUSD", "SOLUSD", "XAUUSD", "EURUSD", "GBPUSD",
        "USDJPY", "SPX", "NDX", "US30", "NAS100", "GER40", "DAX",
        "QQQ", "SPY"
    }
    if ticker in blocked:
        return False

    return ticker.isalpha() and 1 <= len(ticker) <= 5


def get_session_label() -> str:
    now = datetime.now(LOCAL_TZ)
    hm = now.hour * 60 + now.minute

    # US Markt grob in deutscher Zeit
    if 15 * 60 + 30 <= hm < 16 * 60:
        return "OPEN"
    if 16 * 60 <= hm < 18 * 60:
        return "MIDDAY"
    if 18 * 60 <= hm < 20 * 60:
        return "AFTERNOON"
    if 20 * 60 <= hm < 22 * 60:
        return "POWER_HOUR"
    return "OFF_HOURS"


def in_cooldown(ticker: str) -> tuple[bool, str]:
    now = datetime.now(timezone.utc)
    last_time = last_alert_times.get(ticker)
    if last_time is None:
        return False, ""

    minutes_since = (now - last_time).total_seconds() / 60
    if minutes_since < COOLDOWN_MINUTES:
        return True, f"Cooldown aktiv ({minutes_since:.1f}/{COOLDOWN_MINUTES} Min.)"

    return False, ""


def set_cooldown(ticker: str) -> None:
    last_alert_times[ticker] = datetime.now(timezone.utc)


def calculate_rule_score(
    signal: str,
    entry: float | None,
    stop: float | None,
    take: float | None,
    rr: float | None,
    vwap: float | None,
    volume: float | None,
    pm_high: float | None,
    pm_low: float | None,
    or_high: float | None,
    or_low: float | None,
    session_label: str,
) -> tuple[int, list[str]]:
    score = 0
    notes = []
    signal = (signal or "").upper().strip()

    if signal in {"LONG", "SHORT"}:
        score += 1
        notes.append("Signal vorhanden")

    if entry is not None and stop is not None and take is not None:
        score += 2
        notes.append("Entry/Stop/Take vollständig")

    if rr is not None:
        if rr >= 2.5:
            score += 3
            notes.append("RR >= 2.5")
        elif rr >= 2.0:
            score += 2
            notes.append("RR >= 2.0")
        elif rr >= 1.5:
            score += 1
            notes.append("RR >= 1.5")

    if volume is not None:
        if volume >= 1_000_000:
            score += 2
            notes.append("Volumen sehr stark")
        elif volume >= 300_000:
            score += 1
            notes.append("Volumen brauchbar")

    if entry is not None and vwap is not None:
        if signal == "LONG" and entry >= vwap:
            score += 1
            notes.append("LONG über VWAP")
        elif signal == "SHORT" and entry <= vwap:
            score += 1
            notes.append("SHORT unter VWAP")

    if entry is not None and or_high is not None and or_low is not None:
        if or_low <= entry <= or_high:
            score += 1
            notes.append("Entry in OR-Nähe")
        else:
            notes.append("Entry außerhalb OR")

    if entry is not None and pm_high is not None and pm_low is not None:
        if pm_low <= entry <= pm_high:
            score += 1
            notes.append("Entry in PM-Range")
        else:
            notes.append("Entry außerhalb PM-Range")

    if session_label == "OPEN":
        score += 1
        notes.append("Open-Session")
    elif session_label == "POWER_HOUR":
        score += 1
        notes.append("Power-Hour")
    elif session_label == "MIDDAY":
        score -= 1
        notes.append("Midday-Abzug")

    return score, notes


def evaluate_leverage_fit(decision: str, rr, entry, stop):
    try:
        rr = float(rr)
        entry = float(entry)
        stop = float(stop)
    except (TypeError, ValueError):
        return "UNBEKANNT", "Daten unvollständig"

    distance = abs(entry - stop)
    if entry <= 0 or distance <= 0:
        return "UNBEKANNT", "Ungültige Preisstruktur"

    stop_pct = distance / entry

    if decision.startswith("A-") and rr >= 1.8:
        if stop_pct <= 0.015:
            return "GEEIGNET", "Sauberer Stop, gutes RR, passend für 12-15x"
        if stop_pct <= 0.025:
            return "MITTEL", "Setup gut, Stop aber etwas weiter"
        return "EINGESCHRÄNKT", "Stop zu weit für 12-15x"

    if decision.startswith("B-"):
        return "EINGESCHRÄNKT", "B-Setup nur bedingt für 12-15x"

    return "NICHT GEEIGNET", "Setup nicht stark genug"


def calculate_knockout_plan(entry, stop, signal, decision):
    try:
        entry = float(entry)
        stop = float(stop)
    except (TypeError, ValueError):
        return None

    signal = (signal or "").upper().strip()
    decision = (decision or "").upper().strip()

    if entry <= 0 or stop <= 0:
        return None

    # Zielhebel für deinen Stil
    if decision.startswith("A-"):
        target_leverage_min = 12.0
        target_leverage_max = 15.0
        stop_buffer_pct = 0.0035
    elif decision.startswith("B-"):
        target_leverage_min = 6.0
        target_leverage_max = 10.0
        stop_buffer_pct = 0.006
    else:
        target_leverage_min = 3.0
        target_leverage_max = 5.0
        stop_buffer_pct = 0.01

    if signal == "LONG":
        if stop >= entry:
            return None
        ko_level = stop * (1 - stop_buffer_pct)
        distance = entry - ko_level

    elif signal == "SHORT":
        if stop <= entry:
            return None
        ko_level = stop * (1 + stop_buffer_pct)
        distance = ko_level - entry

    else:
        return None

    if distance <= 0:
        return None

    leverage = entry / distance
    suitability = "OK"
    warning = ""

    if leverage > 18:
        suitability = "ZU AGGRESSIV"
        warning = "Hebel sehr hoch, Produkt wahrscheinlich zu nervös."
    elif leverage > 15:
        suitability = "HOCH"
        warning = "Leicht über Zielbereich 12-15x."
    elif leverage < 8:
        suitability = "ZU NIEDRIG"
        warning = "Für deinen Stil eher niedriger Hebel."

    direction = "Long" if signal == "LONG" else "Short"
    search_hint = (
        f"{direction} Knockout, KO nahe {safe_round(ko_level)}, "
        f"Hebel ideal {int(target_leverage_min)}x-{int(target_leverage_max)}x"
    )

    return {
        "ko_level": safe_round(ko_level),
        "leverage": safe_round(leverage, 1),
        "target_leverage_min": target_leverage_min,
        "target_leverage_max": target_leverage_max,
        "suitability": suitability,
        "warning": warning,
        "search_hint": search_hint,
    }


def build_professional_prompt(
    ticker: str,
    signal: str,
    trigger: str,
    entry: str,
    stop: str,
    take: str,
    rr: str,
    vwap: str,
    volume: str,
    pm_high: str,
    pm_low: str,
    or_high: str,
    or_low: str,
    rule_score: int,
    rule_notes: list[str],
    session_label: str,
) -> str:
    notes_text = ", ".join(rule_notes) if rule_notes else "keine"

    return f"""
Du bist ein sehr strenger Intraday-Daytrading-Filter für US-Aktien.

Ziel:
Bewerte nur hochwertige Intraday-Setups. Sei konservativ.
Lieber NO-TRADE als ein mittelmäßiger Trade.

Erlaubte Urteile:
A-LONG
A-SHORT
B-LONG
B-SHORT
NO-TRADE

Bewertung:
- A nur bei sehr klarer Struktur, sauberem Trigger, gutem RR und brauchbarem Momentum
- B nur bei brauchbarem Setup mit kleinen Schwächen
- NO-TRADE bei Unsicherheit, Chop, schlechter Struktur oder schwachem Edge

Regeln:
- Nur US-Aktien bewerten
- Wenn Daten unvollständig oder unlogisch sind: NO-TRADE
- Für hohen Hebel muss das Setup präzise und sauber sein
- Sei streng und kurz

Antworte exakt in 3 Zeilen:
Zeile 1: nur das Urteil
Zeile 2: kurzer deutscher Grund
Zeile 3: kurzer Kontext-Hinweis

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
Session: {session_label}

Regel-Score: {rule_score}
Regel-Hinweise: {notes_text}
""".strip()


def append_log_row(row: dict) -> None:
    file_exists = os.path.exists(LOG_FILE)
    fieldnames = [
        "timestamp_utc",
        "session_label",
        "ticker",
        "signal",
        "trigger",
        "decision",
        "reason",
        "context_hint",
        "rule_score",
        "leverage_fit",
        "leverage_reason",
        "ko_level",
        "ko_leverage",
        "entry",
        "stop",
        "take",
        "rr",
        "vwap",
        "volume",
        "pm_high",
        "pm_low",
        "or_high",
        "or_low",
    ]

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def process_alert(data: dict) -> None:
    ticker = str(data.get("ticker", "")).strip().upper()
    signal = str(data.get("signal", "")).strip().upper()
    trigger = str(data.get("trigger", "")).strip()
    entry = str(data.get("entry", "")).strip()
    stop = str(data.get("stop", "")).strip()
    take = str(data.get("take", "")).strip()
    rr = str(data.get("rr", "")).strip()
    vwap = str(data.get("vwap", "")).strip()
    volume = str(data.get("volume", "")).strip()
    pm_high = str(data.get("pmHigh", "")).strip()
    pm_low = str(data.get("pmLow", "")).strip()
    or_high = str(data.get("orHigh", "")).strip()
    or_low = str(data.get("orLow", "")).strip()

    print("ALERT DATA:", data)

    session_label = get_session_label()

    entry_f = safe_float(entry)
    stop_f = safe_float(stop)
    take_f = safe_float(take)
    rr_f = safe_float(rr)
    vwap_f = safe_float(vwap)
    volume_f = safe_float(volume)
    pm_high_f = safe_float(pm_high)
    pm_low_f = safe_float(pm_low)
    or_high_f = safe_float(or_high)
    or_low_f = safe_float(or_low)

    decision = "NO-TRADE"
    reason = "Kein Urteil"
    context_hint = "Kein Kontext"
    rule_score = 0
    leverage_fit = "UNBEKANNT"
    leverage_reason = "Nicht geprüft"
    knockout_plan = None

    # Hard Filters
    if not is_us_stock(ticker):
        reason = f"{ticker or 'Unbekannt'} ist keine US-Aktie."
    elif signal not in {"LONG", "SHORT"}:
        reason = "Signal ungültig."
    elif entry_f is None or stop_f is None or take_f is None:
        reason = "Entry/Stop/Take fehlen."
    elif rr_f is None:
        reason = "RR fehlt."
    elif rr_f < 1.5:
        reason = "RR unter Mindestwert 1.5."
    elif session_label == "OFF_HOURS":
        reason = "Außerhalb bevorzugter Session."
    else:
        cooldown_active, cooldown_reason = in_cooldown(ticker)
        if cooldown_active:
            reason = cooldown_reason
            context_hint = "Mehrfachsignal blockiert"
        else:
            rule_score, rule_notes = calculate_rule_score(
                signal=signal,
                entry=entry_f,
                stop=stop_f,
                take=take_f,
                rr=rr_f,
                vwap=vwap_f,
                volume=volume_f,
                pm_high=pm_high_f,
                pm_low=pm_low_f,
                or_high=or_high_f,
                or_low=or_low_f,
                session_label=session_label,
            )

            # Vorfilter
            minimum_score = 4
            if session_label == "MIDDAY":
                minimum_score = 5

            if rule_score < minimum_score:
                reason = f"Regel-Score zu schwach ({rule_score})."
                context_hint = "Vorfilter blockiert"
            elif OPENAI_API_KEY:
                try:
                    client = OpenAI(api_key=OPENAI_API_KEY)
                    prompt = build_professional_prompt(
                        ticker=ticker,
                        signal=signal,
                        trigger=trigger,
                        entry=entry,
                        stop=stop,
                        take=take,
                        rr=rr,
                        vwap=vwap,
                        volume=volume,
                        pm_high=pm_high,
                        pm_low=pm_low,
                        or_high=or_high,
                        or_low=or_low,
                        rule_score=rule_score,
                        rule_notes=rule_notes,
                        session_label=session_label,
                    )

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
                    if len(lines) > 2:
                        context_hint = lines[2]

                except Exception as e:
                    print("OpenAI Fehler:", e)
                    decision = "NO-TRADE"
                    reason = "OpenAI API Fehler"
                    context_hint = "Fallback aktiv"
            else:
                reason = "OPENAI_API_KEY fehlt."
                context_hint = "Fallback aktiv"

    leverage_fit, leverage_reason = evaluate_leverage_fit(decision, rr, entry, stop)

    if decision in {"A-LONG", "A-SHORT", "B-LONG", "B-SHORT"}:
        knockout_plan = calculate_knockout_plan(
            entry=entry,
            stop=stop,
            signal=signal,
            decision=decision,
        )

    # Routing / Versandlogik
    should_send = True

    if A_ONLY_MODE and not decision.startswith("A-"):
        should_send = False

    if not SEND_B_SETUPS and decision.startswith("B-"):
        should_send = False

    # Cooldown nur auf echte Trade-Signale setzen
    if decision in {"A-LONG", "A-SHORT", "B-LONG", "B-SHORT"}:
        set_cooldown(ticker)

    emoji = "⚪"
    if "LONG" in decision:
        emoji = "🟢"
    elif "SHORT" in decision:
        emoji = "🔴"

    message_lines = [
        f"{emoji} {decision} | {ticker}",
        f"Session: {session_label}",
        f"Signal: {signal}",
        f"Trigger: {trigger or '-'}",
    ]

    if entry:
        message_lines.append(f"Entry: {entry}")
    if stop:
        message_lines.append(f"Stop: {stop}")
    if take:
        message_lines.append(f"Take: {take}")
    if rr:
        message_lines.append(f"RR: {rr}")
    if vwap:
        message_lines.append(f"VWAP: {vwap}")
    if volume:
        message_lines.append(f"Volume: {volume}")

    if pm_high or pm_low:
        message_lines.append(f"PM: {pm_low or '-'} / {pm_high or '-'}")
    if or_high or or_low:
        message_lines.append(f"OR: {or_low or '-'} / {or_high or '-'}")

    message_lines.append(f"Score: {rule_score}")
    message_lines.append(f"Hebel 12-15x: {leverage_fit}")
    message_lines.append(f"Leverage-Check: {leverage_reason}")

    if knockout_plan:
        message_lines.append("KO-Plan:")
        message_lines.append(f"KO-Level: {knockout_plan['ko_level']}")
        message_lines.append(f"Hebel ca.: {knockout_plan['leverage']}x")
        message_lines.append(
            f"Zielhebel: {int(knockout_plan['target_leverage_min'])}x-"
            f"{int(knockout_plan['target_leverage_max'])}x"
        )
        message_lines.append(f"Eignung: {knockout_plan['suitability']}")
        message_lines.append(f"TR-Suche: {knockout_plan['search_hint']}")
        if knockout_plan["warning"]:
            message_lines.append(f"Warnung: {knockout_plan['warning']}")

    message_lines.append(f"Grund: {reason}")
    message_lines.append(f"Kontext: {context_hint}")

    message = "\n".join(message_lines)

    if should_send:
        send_telegram_message(message)

    append_log_row(
        {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "session_label": session_label,
            "ticker": ticker,
            "signal": signal,
            "trigger": trigger,
            "decision": decision,
            "reason": reason,
            "context_hint": context_hint,
            "rule_score": rule_score,
            "leverage_fit": leverage_fit,
            "leverage_reason": leverage_reason,
            "ko_level": knockout_plan["ko_level"] if knockout_plan else "",
            "ko_leverage": knockout_plan["leverage"] if knockout_plan else "",
            "entry": entry,
            "stop": stop,
            "take": take,
            "rr": rr,
            "vwap": vwap,
            "volume": volume,
            "pm_high": pm_high,
            "pm_low": pm_low,
            "or_high": or_high,
            "or_low": or_low,
        }
    )


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
