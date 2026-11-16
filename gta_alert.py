#!/usr/bin/env python3
"""
gta_alert.py - Notifica push (ntfy) quando il "Controller wireless DualSense -
Grand Theft Auto VI Bianco Edizione limitata" torna acquistabile su Amazon.it.

Gira su GitHub Actions (workflow "gta").
  python3 gta_alert.py --minutes 9   # gira 9 minuti ed esce
  python3 gta_alert.py --once        # un controllo, stampa tutto (diagnostica)
"""

import argparse
import html
import json
import os
import random
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or "duo-alert-7q4k9x2mzt"
NOME = "DualSense GTA VI Bianco"
QUERY = "dualsense grand theft auto vi bianco edizione limitata"
ASIN_FISSI = [a for a in os.environ.get("GTA_ASIN", "").split(",") if a]
INTERVALLO_SEC = 75
STATE_FILE = os.environ.get("GTA_STATE_FILE", "gta_state.json")
BASE = "https://www.amazon.it"
NTFY_URL = "https://ntfy.sh/" + NTFY_TOPIC

TITOLO_OK = re.compile(r"(?=.*dualsense)(?=.*grand theft auto vi|.*gta\s*(vi|6))(?=.*bianc|.*white)", re.I | re.S)
NO = re.compile(r"non disponibile|attualmente non|esaurit|non sappiamo|currently unavailable", re.I)
BLOCCO = re.compile(r"validateCaptcha|api-services-support@amazon\.com|Inserisci i caratteri|"
                    r"Type the characters|errors/validateCaptcha|To discuss automated access", re.I)

try:
    from curl_cffi import requests as _cffi
except Exception:
    _cffi = None


def ora():
    return datetime.now(timezone.utc) + timedelta(hours=1)


def log(msg):
    print(f"[{ora():%H:%M:%S}] {msg}", flush=True)


def txt(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def sessione():
    if _cffi is None:
        raise RuntimeError("curl_cffi mancante")
    return _cffi.Session(impersonate=random.choice(["chrome", "safari", "chrome124", "safari17_0"]))


def get(s, url):
    r = s.get(url, headers={"Accept": "text/html,application/xhtml+xml",
                            "Accept-Language": "it-IT,it;q=0.9,en;q=0.5"}, timeout=25)
    return r.status_code, r.text


def notify(title, body, priority="urgent", tags="video_game", click=None):
    h = {"Title": title, "Priority": priority, "Tags": tags}
    if click:
        h["Click"] = click
    try:
        urllib.request.urlopen(urllib.request.Request(
            NTFY_URL, data=body.encode("utf-8"), method="POST", headers=h), timeout=15).read()
    except Exception as e:
        log(f"ATTENZIONE: notifica non inviata ({e})")


def cerca_asin(s, verbose=False):
    code, t = get(s, f"{BASE}/s?k={urllib.request.quote(QUERY)}")
    if code >= 400 or BLOCCO.search(t):
        raise RuntimeError(f"ricerca bloccata (HTTP {code})")
    trovati = {}
    for a in dict.fromkeys(re.findall(r'data-asin="(B0[A-Z0-9]{8})"', t)):
        m = re.search(r'data-asin="%s".{0,8000}?<h2[^>]*>(.*?)</h2>' % a, t, re.S)
        titolo = txt(m.group(1)) if m else ""
        if verbose and titolo:
            log(f"  risultato {a}: {titolo[:110]}")
        if TITOLO_OK.search(titolo):
            trovati[a] = titolo
    return trovati


def controlla(s, asin):
    """Ritorna dict con stato del prodotto, oppure solleva se bloccato."""
    url = f"{BASE}/dp/{asin}"
    code, p = get(s, url)
    if code >= 400 or BLOCCO.search(p):
        raise RuntimeError(f"pagina bloccata (HTTP {code})")
    tm = re.search(r'id="productTitle"[^>]*>(.*?)</span>', p, re.S)
    titolo = txt(tm.group(1)) if tm else ""
    am = re.search(r'id="availability"[^>]*>(.*?)</div>', p, re.S)
    disp = txt(am.group(1)) if am else ""
    pm = re.search(r'id="corePrice(?:Display_desktop)?_feature_div".*?<span class="a-offscreen">([^<]+)<', p, re.S)
    prezzo = pm.group(1).strip() if pm else ""
    venditori = [txt(x) for x in re.findall(
        r'class="[^"]*offer-display-feature-text-message[^"]*"[^>]*>(.*?)</span>', p, re.S)][:2]
    carrello = any(f'id="{b}"' in p for b in ("add-to-cart-button", "buy-now-button", "preorder-button"))
    altri = re.search(r'id="buybox-see-all-buying-choices"|Vedi tutte le offerte|Disponibile presso questi venditori', p)
    acquistabile = (carrello and not NO.search(disp)) or bool(altri and not carrello and prezzo)
    return {"url": url, "titolo": titolo, "disp": disp, "prezzo": prezzo, "venditori": venditori,
            "carrello": carrello, "altri": bool(altri), "ok": acquistabile}


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        st = {}
    for k, v in {"asin": {}, "notificati": [], "avviato": False, "errori": 0, "ultima_ricerca": 0}.items():
        st.setdefault(k, v)
    return st


def save_state(st):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f)


def tick(st):
    s = sessione()
    try:
        if not st["asin"] or time.time() - st["ultima_ricerca"] > 1800:
            nuovi = cerca_asin(s)
            st["asin"].update(nuovi)
            st["ultima_ricerca"] = time.time()
            if nuovi:
                log("ASIN trovati: " + ", ".join(nuovi))
        asins = list(dict.fromkeys(ASIN_FISSI + list(st["asin"])))
        if not asins:
            raise RuntimeError("prodotto non trovato nella ricerca Amazon")
        disponibili = {}
        for a in asins:
            r = controlla(s, a)
            if r["titolo"] and not TITOLO_OK.search(r["titolo"]):
                continue
            stato = f"{r['disp'] or '-'} | {r['prezzo'] or 'nessun prezzo'}"
            log(f"{a}: {'DISPONIBILE' if r['ok'] else 'non disponibile'} ({stato[:120]})")
            if r["ok"]:
                disponibili[a] = r
            time.sleep(random.uniform(1, 3))
        if not st["avviato"]:
            notify("Alert DualSense GTA VI attivo",
                   f"Controllo Amazon.it ogni ~{INTERVALLO_SEC}s e ti avviso qui appena il {NOME} "
                   "torna acquistabile.", priority="default", tags="white_check_mark",
                   click=f"{BASE}/dp/{asins[0]}")
            st["avviato"] = True
        for a, r in disponibili.items():
            if a not in st["notificati"]:
                vend = f"\nVenduto/spedito da: {' / '.join(r['venditori'])}" if r["venditori"] else ""
                extra = "" if r["carrello"] else "\n(Solo tramite 'Altri venditori': controlla il prezzo)"
                notify(f"{NOME} disponibile su Amazon!",
                       f"Prezzo: {r['prezzo'] or '?'}{vend}\n{r['disp'][:80]}{extra}\nTocca per comprarlo.",
                       click=r["url"])
                log(f"NOTIFICA INVIATA per {a}")
        st["notificati"] = sorted(disponibili)
        if st["errori"] >= 15:
            notify("Alert DualSense GTA VI: di nuovo operativo", "Amazon risponde di nuovo.",
                   priority="low", tags="white_check_mark")
        st["errori"] = 0
        return True
    except Exception as e:
        st["errori"] += 1
        log(f"Errore #{st['errori']}: {e}")
        if st["errori"] == 15:
            notify("Alert DualSense GTA VI: problema",
                   f"Amazon blocca i controlli da 15 tentativi ({str(e)[:100]}). Continuo a riprovare.",
                   priority="high", tags="warning")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    if a.once:
        s = sessione()
        try:
            trovati = cerca_asin(s, verbose=True)
            log(f"ASIN corrispondenti: {trovati}")
        except Exception as e:
            trovati = {}
            log(f"Ricerca: {e}")
        for asin in dict.fromkeys(ASIN_FISSI + list(trovati)):
            try:
                log(f"{asin}: {controlla(s, asin)}")
            except Exception as e:
                log(f"{asin}: {e}")
        return
    st = load_state()
    fine = time.time() + a.minutes * 60 if a.minutes else None
    attesa = INTERVALLO_SEC
    while True:
        ok = tick(st)
        save_state(st)
        attesa = INTERVALLO_SEC if ok else min(attesa * 2, 600)
        w = attesa + random.uniform(-10, 10)
        if fine and time.time() + w > fine:
            break
        time.sleep(w)


if __name__ == "__main__":
    main()
