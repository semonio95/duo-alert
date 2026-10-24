#!/usr/bin/env python3
"""
duo_alert.py - Notifica push sull'iPhone quando un iPhone Duo diventa
ritirabile in un Apple Store italiano (tutti i 17 negozi).

Gira sia su GitHub Actions (cloud, gratis) sia su un computer.
Requisiti: Python 3.8+; consigliato `pip install curl_cffi`.
Notifiche: app gratuita "ntfy" sull'iPhone, iscritta al topic NTFY_TOPIC.

Uso:
  python3 duo_alert.py               # gira per sempre, controllo ogni minuto
  python3 duo_alert.py --minutes 4   # gira 4 minuti ed esce (GitHub Actions)
  python3 duo_alert.py --once        # un solo controllo, stampa lo stato
"""

import argparse
import http.cookiejar
import io
import json
import math
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

# ======================= CONFIGURAZIONE =======================
NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or "duo-alert-7q4k9x2mzt"
INTERVALLO_SEC = 60                  # ogni quanto controllare (+/- 10 s casuali)
SOLO_CAPACITA = []                   # es. ["256GB"]; [] = qualsiasi capacita'
SOLO_COLORI = []                     # es. ["bianco"] oppure ["notturno"]; [] = entrambi
MAX_KM = None                        # es. 30 = solo negozi di Roma; None = tutta Italia
CASA = (41.94, 12.53)                # coordinate approssimative del CAP 00191
# Ricerche che insieme coprono tutti i 17 Apple Store italiani
LOCALITA = ["00191", "20121", "95131"]
STATE_FILE = os.environ.get("DUO_STATE_FILE", "duo_state.json")
# ==============================================================

MODELLI = {  # codici italiani letti dalle pagine Apple (24/10/2026)
    "MK2D4QL/A": "256GB Bianco stellare",
    "MK2E4QL/A": "256GB Cielo notturno",
    "MK2F4QL/A": "512GB Bianco stellare",
    "MK2G4QL/A": "512GB Cielo notturno",
    "MK2H4QL/A": "1TB Bianco stellare",
    "MK2J4QL/A": "1TB Cielo notturno",
    "MK2K4QL/A": "2TB Bianco stellare",
    "MK2L4QL/A": "2TB Cielo notturno",
}

BUY_URL = "https://www.apple.com/it/shop/buy-iphone/iphone-duo"
PICKUP_URL = "https://www.apple.com/it/shop/retail/pickup-message"
NTFY_URL = "https://ntfy.sh/" + NTFY_TOPIC
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")

_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))
try:
    from curl_cffi import requests as _cffi
    _session = _cffi.Session(impersonate="chrome")
except Exception:
    _session = None


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def http_get(url, accept="application/json"):
    headers = {"Accept": accept, "Accept-Language": "it-IT,it;q=0.9", "Referer": BUY_URL}
    if _session is not None:
        r = _session.get(url, headers=headers, timeout=25)
        if r.status_code >= 400:
            raise urllib.error.HTTPError(url, r.status_code, f"HTTP {r.status_code}",
                                         None, io.BytesIO(r.content))
        return r.text
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    with _opener.open(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def notify(title, body, priority="urgent", tags="iphone,rotating_light"):
    """Notifica push via ntfy. Il titolo resta ASCII per compatibilita'."""
    req = urllib.request.Request(
        NTFY_URL, data=body.encode("utf-8"), method="POST",
        headers={"Title": title, "Priority": priority, "Tags": tags, "Click": BUY_URL})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        log(f"ATTENZIONE: notifica non inviata ({e})")


def km_da_casa(store):
    try:
        la, lo = float(store["storelatitude"]), float(store["storelongitude"])
    except (KeyError, TypeError, ValueError):
        return None
    p1, p2 = math.radians(CASA[0]), math.radians(la)
    dp, dl = p2 - p1, math.radians(lo - CASA[1])
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def wanted(name):
    t = name.replace(" ", "").lower()
    if SOLO_CAPACITA and not any(c.replace(" ", "").lower() in t for c in SOLO_CAPACITA):
        return False
    if SOLO_COLORI and not any(c.lower() in t for c in SOLO_COLORI):
        return False
    return True


def check():
    """Ritorna (disponibili, n_negozi). disponibili = {(negozio, part): info}."""
    available, seen = {}, set()
    for loc in LOCALITA:
        params = {"pl": "true", "location": loc}
        for i, p in enumerate(MODELLI):
            params[f"parts.{i}"] = p
        data = json.loads(http_get(PICKUP_URL + "?" + urllib.parse.urlencode(params)))
        stores = (data.get("body") or {}).get("stores")
        if stores is None:
            raise ValueError("formato risposta Apple inatteso (manca 'stores')")
        for s in stores:
            name = s.get("storeName", "?")
            if name in seen:
                continue
            seen.add(name)
            km = km_da_casa(s)
            for part, info in (s.get("partsAvailability") or {}).items():
                if info.get("pickupDisplay") == "available":
                    available[(name, part)] = {
                        "km": km, "city": s.get("city", ""),
                        "model": MODELLI.get(part, part),
                        "quote": (info.get("pickupSearchQuote") or "").strip()}
        time.sleep(1)
    return available, len(seen)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    state.setdefault("notified", [])
    state.setdefault("errors", 0)
    state.setdefault("started", False)
    return state


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception as e:
        log(f"Stato non salvato ({e})")


def tick(state, where):
    try:
        available, n_stores = check()
        if not state["started"]:
            notify(f"Monitor iPhone Duo attivo ({where})",
                   f"Controllo {n_stores} Apple Store italiani ogni minuto circa. "
                   "Se leggi questo, le notifiche funzionano.",
                   priority="default", tags="white_check_mark")
            state["started"] = True
        hits = {k: v for k, v in available.items()
                if wanted(v["model"])
                and (MAX_KM is None or v["km"] is None or v["km"] <= MAX_KM)}
        other = {k: v for k, v in available.items() if k not in hits}
        already = {tuple(x) for x in state["notified"]}
        if set(hits) - already:
            rows = sorted(hits.items(), key=lambda kv: (kv[1]["km"] is None, kv[1]["km"] or 0))
            lines = [f"{v['model']} - Apple {store} ({v['city']}"
                     + (f", {v['km']:.0f} km" if v["km"] is not None else "") + ")"
                     for (store, _), v in rows[:8]]
            notify("iPhone Duo DISPONIBILE al ritiro!", "\n".join(lines) +
                   "\nApri l'app Apple Store e prenota subito il ritiro.")
            log("DISPONIBILE -> " + " | ".join(lines))
        elif hits:
            log(f"Ancora disponibile ({len(hits)} slot, gia' notificato)")
        else:
            extra = f" (altre capacita' disponibili: {len(other)})" if other else ""
            log(f"Nessuna disponibilita' in {n_stores} negozi{extra}")
        state["notified"] = [list(k) for k in hits]
        state["errors"] = 0
        return True
    except Exception as e:
        state["errors"] += 1
        detail = ""
        if hasattr(e, "read"):
            try:
                detail = " | " + e.read()[:200].decode("utf-8", "replace").replace("\n", " ")
            except Exception:
                pass
        log(f"Errore #{state['errors']}: {type(e).__name__}: {e}{detail}")
        if state["errors"] == 5:
            notify("Monitor iPhone Duo: problema",
                   f"5 errori di fila (ultimo: {str(e)[:150]}). Il monitor continua a riprovare.",
                   priority="high", tags="warning")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=0, help="durata, poi esce (0 = per sempre)")
    ap.add_argument("--once", action="store_true", help="un solo controllo con elenco completo")
    args = ap.parse_args()
    where = "GitHub" if os.environ.get("GITHUB_ACTIONS") else "computer"
    if args.once:
        available, n = check()
        log(f"Negozi controllati: {n}")
        for (store, part), v in sorted(available.items()):
            log(f"DISPONIBILE: {v['model']} - {store} ({v['city']})")
        if not available:
            log("Nessun iPhone Duo disponibile al ritiro in Italia")
        return
    log(f"Avvio monitor iPhone Duo - {where} - curl_cffi: {'si' if _session else 'no'}")
    state = load_state()
    deadline = time.time() + args.minutes * 60 if args.minutes else None
    delay = INTERVALLO_SEC
    while True:
        ok = tick(state, where)
        save_state(state)
        delay = INTERVALLO_SEC if ok else min(delay * 2, 600)
        wait = delay + random.uniform(-10, 10)
        if deadline and time.time() + wait > deadline:
            break
        time.sleep(wait)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Monitor fermato.")
