#!/usr/bin/env python3
"""
duo_alert.py - Notifica push sull'iPhone quando un iPhone Duo diventa
ritirabile in un Apple Store italiano.

Requisiti: Python 3.8+. Consigliato: pip install curl_cffi (le richieste
sembrano quelle di Chrome); senza, funziona lo stesso con urllib.
Notifiche: app gratuita "ntfy" sull'iPhone, iscritta al topic NTFY_TOPIC.

Va eseguito da una connessione di casa: Apple blocca l'API di disponibilita'
quando le richieste arrivano da server cloud (GitHub, VM, ecc.).

Uso:
  Mac:      caffeinate -i python3 duo_alert.py
  Windows:  py duo_alert.py
  Opzione:  --minutes N  (gira N minuti ed esce)
Fermare: Ctrl+C
"""

import argparse
import http.cookiejar
import io
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

# ======================= CONFIGURAZIONE =======================
CAP = "00191"                       # CAP usato per cercare i negozi vicini
NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or "duo-alert-7q4k9x2mzt"
INTERVALLO_SEC = 60                 # ogni quanto controllare (+/- 15 s casuali)
SOLO_CAPACITA = ["256GB"]           # [] = qualsiasi capacita'
SOLO_COLORI = []                    # es. ["bianco"] oppure ["notturno"]; [] = entrambi
MAX_KM = None                       # es. 30 = solo negozi di Roma; None = tutti
PARTS = []                          # vuoto = li trova da solo (es. ["MK2D4QL/A"])
STATE_FILE = os.environ.get("DUO_STATE_FILE", "duo_state.json")
# ==============================================================

BUY_URL = "https://www.apple.com/it/shop/buy-iphone/iphone-duo"
FULFILL_URL = "https://www.apple.com/it/shop/fulfillment-messages"
NTFY_URL = "https://ntfy.sh/" + NTFY_TOPIC
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")

_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))

# Se installato (pip install curl_cffi), le richieste si presentano come Chrome:
# piu' difficile che Apple le scambi per un bot. Altrimenti si usa urllib.
try:
    from curl_cffi import requests as _cffi
    _session = _cffi.Session(impersonate="chrome")
except Exception:
    _session = None


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def http_get(url, accept="text/html,application/json;q=0.9,*/*;q=0.8"):
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
    """Invia una notifica push via ntfy. Il titolo resta ASCII per compatibilita'."""
    req = urllib.request.Request(
        NTFY_URL, data=body.encode("utf-8"), method="POST",
        headers={"Title": title, "Priority": priority, "Tags": tags, "Click": BUY_URL})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:  # la notifica non deve mai fermare il monitor
        log(f"ATTENZIONE: notifica non inviata ({e})")


def _norm(html):
    return html.replace("\\u002F", "/").replace("\\/", "/")


def discover_parts():
    """Trova i codici prodotto (es. MK2D4QL/A) leggendo le pagine Apple."""
    html = _norm(http_get(BUY_URL))
    pages = [html]
    links = set(re.findall(r'/it/shop/buy-iphone/iphone-duo/[^"\'\s<>?#]+', html))
    log(f"Pagina modelli letta ({len(html)} caratteri, {len(links)} configurazioni)")
    for path in sorted(links):
        try:
            pages.append(_norm(http_get("https://www.apple.com" + path)))
            time.sleep(1)
        except Exception as e:
            log(f"Pagina {path} non letta ({e})")
    text = "\n".join(pages)
    found = sorted(set(re.findall(r"\b(M[A-Z0-9]{4}QL/A)\b", text)))
    if not found:  # fallback: qualsiasi suffisso di paese
        found = sorted(set(re.findall(r"\b(M[A-Z0-9]{4}[A-Z]{2}/A)\b", text)))
    return found


def _dist_km(store):
    d = store.get("storedistance")
    if isinstance(d, (int, float)):
        return float(d)
    m = re.search(r"([\d.,]+)", str(store.get("storeDistanceWithUnit", "")))
    if m:
        try:
            return float(m.group(1).replace(".", "").replace(",", "."))
        except ValueError:
            pass
    return None


def check(parts):
    """Ritorna (disponibili, titoli). disponibili = {(negozio, part): info}."""
    available, titles = {}, {}
    for i in range(0, len(parts), 4):  # max 4 codici per richiesta
        chunk = parts[i:i + 4]
        params = {"fae": "true", "pl": "true", "mts.0": "regular", "mts.1": "compact",
                  "location": CAP}
        for j, p in enumerate(chunk):
            params[f"parts.{j}"] = p
        raw = http_get(FULFILL_URL + "?" + urllib.parse.urlencode(params),
                       accept="application/json")
        data = json.loads(raw)
        stores = (data.get("body", {}).get("content", {})
                      .get("pickupMessage", {}).get("stores"))
        if stores is None:
            raise ValueError("formato risposta Apple inatteso (manca 'stores'): "
                             + raw[:200].replace("\n", " "))
        for s in stores:
            name = s.get("storeName", "?")
            km = _dist_km(s)
            for part, info in (s.get("partsAvailability") or {}).items():
                reg = (info.get("messageTypes") or {}).get("regular") or {}
                title = reg.get("storePickupProductTitle") or titles.get(part) or part
                titles[part] = title
                if info.get("pickupDisplay") == "available":
                    quote = (info.get("pickupSearchQuote")
                             or reg.get("storePickupQuote") or "").strip()
                    available[(name, part)] = {"km": km, "title": title, "quote": quote}
        if i + 4 < len(parts):
            time.sleep(2)
    return available, titles


def wanted(title):
    t = title.replace(" ", "").lower()
    if "duo" not in t and not re.fullmatch(r"m[a-z0-9]{4}[a-z]{2}/a", t):
        return False  # accessorio o altro prodotto
    if SOLO_CAPACITA and not any(c.replace(" ", "").lower() in t for c in SOLO_CAPACITA):
        return False
    if SOLO_COLORI and not any(c.lower() in t for c in SOLO_COLORI):
        return False
    return True


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    state.setdefault("parts", [])
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
    """Esegue un controllo. Ritorna True se e' andato a buon fine."""
    try:
        if not state["parts"]:
            state["parts"] = list(PARTS) or discover_parts()
            if not state["parts"]:
                raise ValueError("nessun codice prodotto trovato sulle pagine Apple")
            log(f"Codici controllati: {', '.join(state['parts'])}")
        available, titles = check(state["parts"])
        if not state["started"]:
            for p in state["parts"]:
                log(f"  {p} = {titles.get(p, '(nome non fornito da Apple)')}")
            notify(f"Monitor iPhone Duo avviato ({where})",
                   f"Controllo i ritiri per CAP {CAP}, {len(state['parts'])} modelli. "
                   "Se leggi questo, le notifiche funzionano.",
                   priority="default", tags="white_check_mark")
            state["started"] = True
        hits = {k: v for k, v in available.items()
                if wanted(v["title"])
                and (MAX_KM is None or v["km"] is None or v["km"] <= MAX_KM)}
        already = {tuple(x) for x in state["notified"]}
        if set(hits) - already:
            rows = sorted(hits.items(), key=lambda kv: (kv[1]["km"] is None, kv[1]["km"] or 0))
            lines = [f"{v['title']} - {store}"
                     + (f" ({v['km']:.0f} km)" if v["km"] is not None else "")
                     + (f" - {v['quote']}" if v["quote"] else "")
                     for (store, _), v in rows[:6]]
            notify("iPhone Duo DISPONIBILE al ritiro!", "\n".join(lines))
            log("DISPONIBILE -> " + " | ".join(lines))
        elif hits:
            log(f"Ancora disponibile ({len(hits)} slot, gia' notificato)")
        else:
            log("Nessuna disponibilita'")
        state["notified"] = [list(k) for k in hits]
        state["errors"] = 0
        return True
    except Exception as e:
        state["errors"] += 1
        detail = ""
        if hasattr(e, "read"):
            try:
                detail = " | risposta: " + e.read()[:300].decode("utf-8", "replace").replace("\n", " ")
            except Exception:
                pass
        if getattr(e, "code", None) == 541:
            detail = " | Apple sta bloccando le richieste da questa rete"
        log(f"Errore #{state['errors']}: {type(e).__name__}: {e}{detail}")
        if state["errors"] == 5:
            notify("Monitor iPhone Duo: problema",
                   f"5 errori di fila (ultimo: {str(e)[:150]}). Il monitor continua a riprovare.",
                   priority="high", tags="warning")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=0,
                    help="durata in minuti, poi esce (0 = per sempre)")
    args = ap.parse_args()
    where = "GitHub" if os.environ.get("GITHUB_ACTIONS") else "computer"
    log(f"Avvio monitor iPhone Duo - CAP {CAP} - {where}")
    state = load_state()
    deadline = time.time() + args.minutes * 60 if args.minutes else None
    delay = INTERVALLO_SEC
    while True:
        ok = tick(state, where)
        save_state(state)
        delay = INTERVALLO_SEC if ok else min(delay * 2, 600)
        wait = delay + random.uniform(-15, 15)
        if deadline and time.time() + wait > deadline:
            break
        time.sleep(wait)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Monitor fermato.")
