#!/usr/bin/env python3
"""
duo_alert.py - Notifica push quando la "Custodia per iPhone Duo - Blu marino"
(MKR84ZM/A) e' ritirabile OGGI all'Apple Store Porta di Roma.

Solo quel negozio, solo ritiro in giornata: niente spedizione, niente date future.
Gira su GitHub Actions (cloud). Su computer non fa nulla e si chiude.

Uso:
  python3 duo_alert.py --minutes 9   # gira 9 minuti ed esce (GitHub Actions)
  python3 duo_alert.py --once        # un solo controllo, stampa lo stato

Nota: le versioni precedenti di questo script, avviate su computer, si aggiornano
da sole solo se il nuovo file contiene il testo "def amazon_tick": per questo
c'e' la funzione vuota in fondo, che serve a farle passare a questa versione.
"""

import argparse
import io
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

# ======================= CONFIGURAZIONE =======================
NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or "duo-alert-7q4k9x2mzt"
PARTE = "MKR84ZM/A"                      # Custodia per iPhone Duo - Blu marino (89 EUR)
NOME = "Custodia iPhone Duo Blu marino"
NEGOZIO = "Porta di Roma"                # unico negozio accettato
CAP = "00191"
INTERVALLO_SEC = 45
STATE_FILE = os.environ.get("DUO_STATE_FILE", "duo_state.json")
# ==============================================================

PICKUP_URL = "https://www.apple.com/it/shop/retail/pickup-message"
PRODUCT_URL = f"https://www.apple.com/it/shop/product/{PARTE}"
NTFY_URL = "https://ntfy.sh/" + NTFY_TOPIC
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")
WHERE = "GitHub" if os.environ.get("GITHUB_ACTIONS") else "computer"

try:
    from curl_cffi import requests as _cffi
except Exception:
    _cffi = None
_session = _cffi.Session(impersonate="chrome") if _cffi else None


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def http_get(url):
    headers = {"Accept": "application/json", "Accept-Language": "it-IT,it;q=0.9",
               "Referer": "https://www.apple.com/it/shop/iphone/accessories"}
    if _session is not None:
        r = _session.get(url, headers=headers, timeout=25)
        if r.status_code >= 400:
            raise urllib.error.HTTPError(url, r.status_code, f"HTTP {r.status_code}",
                                         None, io.BytesIO(r.content))
        return r.text
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def notify(title, body, priority="urgent", tags="shopping_bags", click=PRODUCT_URL):
    req = urllib.request.Request(
        NTFY_URL, data=body.encode("utf-8"), method="POST",
        headers={"Title": title, "Priority": priority, "Tags": tags, "Click": click})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        log(f"ATTENZIONE: notifica non inviata ({e})")


def check():
    """Ritorna (ritirabile_oggi, testo_stato) per la custodia a Porta di Roma."""
    params = {"pl": "true", "mts.0": "regular", "location": CAP, "parts.0": PARTE}
    data = json.loads(http_get(PICKUP_URL + "?" + urllib.parse.urlencode(params)))
    stores = (data.get("body") or {}).get("stores")
    if stores is None:
        raise ValueError("formato risposta Apple inatteso (manca 'stores')")
    store = next((s for s in stores if s.get("storeName") == NEGOZIO), None)
    if store is None:
        raise ValueError(f"negozio {NEGOZIO} non presente nella risposta")
    info = (store.get("partsAvailability") or {}).get(PARTE) or {}
    quote = (info.get("pickupSearchQuote") or "").strip()
    oggi = info.get("pickupDisplay") == "available" and "oggi" in quote.lower()
    return oggi, f"{info.get('pickupDisplay')} / {quote or '-'}"


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    state.setdefault("case_notified", False)
    state.setdefault("case_started", False)
    state.setdefault("case_errors", 0)
    return state


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception as e:
        log(f"Stato non salvato ({e})")


def tick(state):
    try:
        oggi, stato = check()
        if not state["case_started"]:
            notify("Nuovo alert attivo",
                   f"Ti avviso solo quando la {NOME} e' ritirabile OGGI ad Apple {NEGOZIO}. "
                   "Gli alert sull'iPhone Duo sono stati rimossi.",
                   priority="default", tags="white_check_mark")
            state["case_started"] = True
        if oggi and not state["case_notified"]:
            notify(f"{NOME}: ritiro OGGI a {NEGOZIO}!",
                   "Disponibile per il ritiro in giornata. Tocca per aprirla e prenota subito.")
            log(f"DISPONIBILE OGGI a {NEGOZIO} ({stato})")
        elif oggi:
            log(f"Ancora disponibile oggi ({stato}), gia' notificato")
        else:
            log(f"{NEGOZIO}: non ritirabile oggi ({stato})")
        state["case_notified"] = oggi
        state["case_errors"] = 0
        return True
    except Exception as e:
        state["case_errors"] += 1
        log(f"Errore #{state['case_errors']}: {type(e).__name__}: {str(e)[:200]}")
        if state["case_errors"] == 10:
            notify("Alert custodia: problema",
                   f"10 errori di fila (ultimo: {str(e)[:150]}). Continuo a riprovare.",
                   priority="high", tags="warning")
        return False


def amazon_tick(*_args, **_kwargs):
    """Vuota: serve solo all'aggiornamento automatico delle vecchie versioni."""
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    if args.once:
        oggi, stato = check()
        log(f"{NOME} a {NEGOZIO}: {'RITIRABILE OGGI' if oggi else 'non ritirabile oggi'} ({stato})")
        return
    if WHERE != "GitHub":
        log("Gli alert sull'iPhone Duo sono stati rimossi e il nuovo alert gira nel cloud.")
        log("Puoi chiudere questa finestra del Terminale.")
        return
    log(f"Avvio alert {NOME} - solo {NEGOZIO}, solo ritiro oggi")
    state = load_state()
    deadline = time.time() + args.minutes * 60 if args.minutes else None
    delay = INTERVALLO_SEC
    while True:
        ok = tick(state)
        save_state(state)
        delay = INTERVALLO_SEC if ok else min(delay * 2, 600)
        wait = delay + random.uniform(-5, 5)
        if deadline and time.time() + wait > deadline:
            break
        time.sleep(wait)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Fermato.")
