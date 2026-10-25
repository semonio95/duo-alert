#!/usr/bin/env python3
"""
duo_alert.py - Notifica push sull'iPhone quando un iPhone Duo diventa
disponibile:
  - ritiro in uno dei 17 Apple Store italiani (ogni minuto circa)
  - Unieuro, MediaWorld e R-Store online (ogni ~5 minuti)
  - Amazon Italia, Germania, Francia, Spagna (a rotazione, solo da computer)

Gira sia su GitHub Actions (cloud, gratis) sia su un computer.
Requisiti: Python 3.8+; consigliato `pip install curl_cffi`.
Notifiche: app gratuita "ntfy" sull'iPhone, iscritta al topic NTFY_TOPIC.
Su un computer si aggiorna da solo quando cambia la versione su GitHub.

Uso:
  python3 duo_alert.py               # gira per sempre
  python3 duo_alert.py --minutes 9   # gira 9 minuti ed esce (GitHub Actions)
  python3 duo_alert.py --once        # un solo controllo completo, stampa lo stato
"""

import argparse
import html
import http.cookiejar
import io
import json
import math
import os
import random
import re
import sys
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
LOCALITA = ["00191", "20121", "95131"]   # insieme coprono tutti i 17 Apple Store italiani
CONTROLLA_RIVENDITORI = True         # Unieuro e MediaWorld online
RIVENDITORI_OGNI_SEC = 170
CONTROLLA_AMAZON = True              # un Paese Amazon per giro, a rotazione (solo da computer)
# Dal computer Apple va controllato meno spesso: la connessione di casa viene bloccata
# (errore 541) se interroga Apple ogni minuto. Il cloud controlla Apple ogni minuto.
APPLE_OGNI_SEC_COMPUTER = 240
# Solo gli Amazon da cui si puo' ordinare verso l'Italia (Belgio verificato: non spedisce in Italia).
# Dal cloud Amazon blocca questi domini: li controlla lo script sul computer.
AMAZON = {"it": "it-IT", "de": "de-DE", "fr": "fr-FR", "es": "es-ES"}
AUTO_AGGIORNAMENTO = True            # solo su computer: scarica la versione nuova da GitHub
UPDATE_URL = "https://raw.githubusercontent.com/semonio95/duo-alert/main/duo_alert.py"
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
# ASIN gia' noti (uguali su tutti gli Amazon europei); gli altri si trovano con la ricerca
AMAZON_ASIN_NOTI = {"B0HJB65YZK": "1TB Cielo notturno", "B0HJB23TJP": "256GB Cielo notturno",
                    "B0HJB16BGD": "256GB Bianco stellare"}

_UNIEURO = "https://www.unieuro.it/online/iPhone/iPhone-Duo-{}-pidAPLIPHONEDUO{}"
UNIEURO = {
    "256GB Bianco stellare": _UNIEURO.format("256GB-Bianco-stellare", "256W"),
    "256GB Cielo notturno": _UNIEURO.format("256GB-Cielo-notturno", "256"),
    "512GB Bianco stellare": _UNIEURO.format("512GB-Bianco-stellare", "512W"),
    "512GB Cielo notturno": _UNIEURO.format("512GB-Cielo-notturno", "512"),
    "1TB Bianco stellare": _UNIEURO.format("1TB-Bianco-stellare", "1TBW"),
    "1TB Cielo notturno": _UNIEURO.format("1TB-Cielo-notturno", "1TB"),
    "2TB Bianco stellare": _UNIEURO.format("2TB-Bianco-stellare", "2TBW"),
    "2TB Cielo notturno": _UNIEURO.format("2TB-Cielo-notturno", "2TB"),
}
MEDIAWORLD_START = "https://www.mediaworld.it/it/product/_apple-iphone-duo-256gb-star-white-596069.html"

BUY_URL = "https://www.apple.com/it/shop/buy-iphone/iphone-duo"
PICKUP_URL = "https://www.apple.com/it/shop/retail/pickup-message"
SBA_URL = "https://www.apple.com/it/shop/sba/availability-message"
NTFY_URL = "https://ntfy.sh/" + NTFY_TOPIC
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")
WHERE = "GitHub" if os.environ.get("GITHUB_ACTIONS") else "computer"

try:
    from curl_cffi import requests as _cffi
except Exception:
    _cffi = None


def new_session(imp="chrome"):
    if _cffi is not None:
        return _cffi.Session(impersonate=imp)
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


_apple = new_session()
_other = new_session()


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def http_get(url, accept="application/json", lang="it-IT,it;q=0.9", referer=BUY_URL, session=None):
    s = session or _other
    headers = {"Accept": accept, "Accept-Language": lang}
    if referer:
        headers["Referer"] = referer
    if _cffi is not None:
        r = s.get(url, headers=headers, timeout=25)
        if r.status_code >= 400:
            raise urllib.error.HTTPError(url, r.status_code, f"HTTP {r.status_code}",
                                         None, io.BytesIO(r.content))
        return r.text
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    with s.open(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def notify(title, body, priority="urgent", tags="iphone,rotating_light", click=BUY_URL):
    """Notifica push via ntfy. Il titolo resta ASCII per compatibilita'."""
    req = urllib.request.Request(
        NTFY_URL, data=body.encode("utf-8"), method="POST",
        headers={"Title": title, "Priority": priority, "Tags": tags, "Click": click})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        log(f"ATTENZIONE: notifica non inviata ({e})")


def wanted(name):
    t = re.sub(r"(\d)to\b", r"\1tb", re.sub(r"(\d)go\b", r"\1gb", name.replace(" ", "").lower()))
    if SOLO_CAPACITA and not any(c.replace(" ", "").lower() in t for c in SOLO_CAPACITA):
        return False
    if SOLO_COLORI and not any(c.lower() in t for c in SOLO_COLORI):
        return False
    return True


# ---------------------------- Apple ----------------------------

def km_da_casa(store):
    try:
        la, lo = float(store["storelatitude"]), float(store["storelongitude"])
    except (KeyError, TypeError, ValueError):
        return None
    p1, p2 = math.radians(CASA[0]), math.radians(la)
    dp, dl = p2 - p1, math.radians(lo - CASA[1])
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def _check_pickup():
    available, seen = {}, set()
    for loc in LOCALITA:
        params = {"pl": "true", "location": loc}
        for i, p in enumerate(MODELLI):
            params[f"parts.{i}"] = p
        data = json.loads(http_get(PICKUP_URL + "?" + urllib.parse.urlencode(params), session=_apple))
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
                    available[(name, part)] = {"km": km, "city": s.get("city", ""),
                                               "model": MODELLI.get(part, part)}
        time.sleep(1)
    return available, f"{len(seen)} negozi"


def _check_sba():
    """Riserva: conteggio negozi con disponibilita' per ogni modello."""
    available = {}
    for part, model in MODELLI.items():
        data = json.loads(http_get(SBA_URL + "?" + urllib.parse.urlencode(
            {"parts.0": part, "location": "00191"}), session=_apple))
        c = ((data.get("body") or {}).get("content") or [{}])[0]
        n = int(c.get("partAvailableStoresCount") or 0)
        if n > 0 or c.get("availableAtAnyStore"):
            available[(f"disponibile in {max(n, 1)} Apple Store", part)] = {
                "km": None, "city": "", "model": model, "raw": True}
        time.sleep(1)
    return available, "Apple Store (metodo di riserva)"


_pickup_pausa_fino = 0


def check():
    """Ritorna (disponibili, descrizione). disponibili = {(negozio, part): info}."""
    global _apple, _pickup_pausa_fino
    if time.time() < _pickup_pausa_fino:
        return _check_sba()
    try:
        return _check_pickup()
    except urllib.error.HTTPError as e:
        if e.code not in (403, 429, 503, 541):
            raise
        log(f"Apple ha risposto {e.code}: nuova sessione e riprovo")
        _apple = new_session(random.choice(["chrome", "safari"]) if _cffi else "chrome")
        time.sleep(3)
        try:
            return _check_pickup()
        except urllib.error.HTTPError as e2:
            if e2.code not in (403, 429, 503, 541):
                raise
            log(f"Apple ha risposto ancora {e2.code}: metodo di riserva per 10 minuti")
            _pickup_pausa_fino = time.time() + 600
            return _check_sba()


# ------------------------ Unieuro / MediaWorld ------------------------

_IN_STOCK = {"instock", "lowstock", "limitedavailability", "instoreonly"}


def check_retailers():
    """Prodotti acquistabili subito online. Ritorna {chiave: (descrizione, url)}."""
    found = {}
    for model, url in UNIEURO.items():
        if not wanted(model):
            continue
        try:
            t = http_get(url, accept="text/html", referer=None)
        except Exception as e:
            log(f"Unieuro {model}: pagina non letta ({getattr(e, 'code', e)})")
            continue
        m = re.search(r'"stock":\{"stockLevel":(\d+),"stockLevelStatus":"(\w+)"', t)
        if m and (int(m.group(1)) > 0 or m.group(2).lower() in _IN_STOCK):
            found["unieuro|" + model] = (f"Unieuro online: {model}", url)
        time.sleep(1)
    try:
        start = http_get(MEDIAWORLD_START, accept="text/html", referer=None)
        pages = {MEDIAWORLD_START} | set(re.findall(
            r"https://www\.mediaworld\.it/it/product/_apple-iphone-duo-[a-z0-9\-]+\.html", start))
    except Exception as e:
        log(f"MediaWorld: pagina non letta ({getattr(e, 'code', e)})")
        start, pages = "", set()
    for url in sorted(pages):
        label = url.rsplit("/_apple-iphone-duo-", 1)[-1].rsplit("-", 1)[0].replace("-", " ")
        if not wanted(label):
            continue
        try:
            t = start if url == MEDIAWORLD_START else http_get(url, accept="text/html", referer=None)
        except Exception as e:
            log(f"MediaWorld {label}: pagina non letta ({getattr(e, 'code', e)})")
            continue
        m = re.search(r'"availability":"https://schema\.org/(\w+)","url":"' + re.escape(url), t)
        if m and m.group(1).lower() in _IN_STOCK:
            found["mediaworld|" + label] = (f"MediaWorld online: {label}", url)
        time.sleep(1)
    for part, model in MODELLI.items():
        if not wanted(model):
            continue
        url = f"https://www.rstore.it/products/iphone-duo-{part[:5].lower()}ql-a"
        try:
            j = json.loads(http_get(url + ".js", accept="application/json", referer=None))
        except Exception as e:
            log(f"R-Store {model}: pagina non letta ({getattr(e, 'code', e)})")
            continue
        if j.get("available") or any(v.get("available") for v in j.get("variants", [])):
            price = (j.get("price") or 0) / 100
            found["rstore|" + part] = (f"R-Store online: {model} - {price:,.0f} EUR".replace(",", "."), url)
        time.sleep(0.5)
    return found


# ---------------------------- Amazon ----------------------------

_AMZ_NO = re.compile(r"(?i)(non disponibile|nicht verf[üu]gbar|nicht auf lager|rupture de stock|"
                     r"indisponible|no disponible|sin stock|niet op voorraad|niet beschikbaar|"
                     r"currently unavailable|out of stock|temporarily)")
_AMZ_PRE = re.compile(r"(?i)(pre-?ordin|preordine|vorbestell|erscheint am|pr[ée]commande|"
                      r"sera disponible le|reserva|pre-?order|disponibile dal|disponibile a partire|"
                      r"verschijnt op|vooruitbestel)")
_AMZ_SI = re.compile(r"(?i)(disponibilit[aà] immediata|\bdisponibile\b|auf lager|en stock|op voorraad|"
                     r"in stock|il n'en reste|ne rimangono|solo \d+ |nur noch|quedan solo|nog maar|"
                     r"\bdisponible\b)")
_AMZ_TITLE = re.compile(r"(?i)apple iphone duo\s+(\d+)\s*(gb|go|tb|to)\b")


def _txt(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()


def _amz_blocked(t):
    return len(t) < 30000 or "captcha" in t.lower() or "/errors/validateCaptcha" in t


def amazon_domain(dom, state):
    """Controlla un dominio Amazon. Ritorna {chiave: (descrizione, url)} o None se bloccato."""
    lang = AMAZON[dom]
    al = f"{lang},{lang[:2]};q=0.9"
    s = new_session(random.choice(["chrome", "safari"]) if _cffi else "chrome")
    base = f"https://www.amazon.{dom}"
    asins = dict(AMAZON_ASIN_NOTI)
    asins.update(state["amz_asins"])
    try:
        t = http_get(f"{base}/s?k=apple+iphone+duo", accept="text/html", lang=al, referer=None, session=s)
        if not _amz_blocked(t):
            for a in dict.fromkeys(re.findall(
                    r'data-asin="(B0[A-Z0-9]{8})"[^>]*data-component-type="s-search-result"', t)):
                m = re.search(r'data-asin="%s".{0,6000}?<h2[^>]*>(.*?)</h2>' % a, t, re.S)
                title = _txt(m.group(1)) if m else ""
                if _AMZ_TITLE.search(title):
                    asins[a] = title
                    state["amz_asins"][a] = title
    except Exception:
        pass
    found, blocked = {}, 0
    for asin, label in asins.items():
        url = f"{base}/dp/{asin}"
        try:
            p = http_get(url, accept="text/html", lang=al, referer=None, session=s)
        except Exception:
            blocked += 1
            continue
        if _amz_blocked(p):
            blocked += 1
            continue
        title_m = re.search(r'id="productTitle"[^>]*>(.*?)</span>', p, re.S)
        title = _txt(title_m.group(1)) if title_m else label
        if not _AMZ_TITLE.search(title) or not wanted(title):
            continue
        av_m = re.search(r'id="availability"[^>]*>(.*?)</div>', p, re.S)
        avail = _txt(av_m.group(1)) if av_m else ""
        cart = 'id="add-to-cart-button"' in p or 'id="buy-now-button"' in p
        ok = cart and not _AMZ_NO.search(avail) and not _AMZ_PRE.search(avail) and \
            (_AMZ_SI.search(avail) or (not avail and 'id="buy-now-button"' in p))
        if not ok:
            continue
        price_m = re.search(r'id="corePrice(?:Display_desktop)?_feature_div".*?<span class="a-offscreen">([^<]+)<', p, re.S)
        sellers = [_txt(x) for x in re.findall(
            r'class="[^"]*offer-display-feature-text-message[^"]*"[^>]*>(.*?)</span>', p, re.S)][:2]
        model = _AMZ_TITLE.search(title).group(0)[len("apple iphone duo"):].strip()
        color = title.split("-")[-1].split("–")[-1].strip()[:30]
        desc = (f"Amazon.{dom}: iPhone Duo {model} {color} - {price_m.group(1).strip() if price_m else '?'}"
                + (f"\nSpedito/venduto da: {' / '.join(sellers)}" if sellers else "")
                + (f"\n{avail[:80]}" if avail else ""))
        found[f"amz|{dom}|{asin}"] = (desc, url)
        time.sleep(1.5)
    if blocked and blocked == len(asins):
        return None
    return found


def amazon_tick(state, all_domains=False):
    if not CONTROLLA_AMAZON:
        return
    doms = list(AMAZON)
    todo = doms if all_domains else [doms[state["amz_idx"] % len(doms)]]
    state["amz_idx"] = (state["amz_idx"] + 1) % len(doms)
    for dom in todo:
        try:
            found = amazon_domain(dom, state)
        except Exception as e:
            log(f"Amazon.{dom}: errore ({e})")
            continue
        if found is None:
            log(f"Amazon.{dom}: non raggiungibile da qui (anti-bot)")
            continue
        prev = {k for k in state["notified_amz"] if k.startswith(f"amz|{dom}|")}
        for k in sorted(set(found) - prev):
            desc, url = found[k]
            notify("iPhone Duo DISPONIBILE su Amazon!", desc + "\nControlla venditore e spedizione in Italia.",
                   click=url)
            log("AMAZON DISPONIBILE -> " + desc.replace("\n", " | ") + " " + url)
        if not found:
            log(f"Amazon.{dom}: niente disponibile")
        state["notified_amz"] = sorted(({k for k in state["notified_amz"] if not k.startswith(f"amz|{dom}|")}
                                        | set(found)))


# ---------------------------- Stato e ciclo ----------------------------

def retail_tick(state):
    if not CONTROLLA_RIVENDITORI or time.time() - state["last_retail"] < RIVENDITORI_OGNI_SEC:
        return
    state["last_retail"] = time.time()
    try:
        found = check_retailers()
    except Exception as e:
        log(f"Rivenditori: errore ({e})")
        return
    for k in sorted(set(found) - set(state["notified_retail"])):
        desc, url = found[k]
        notify("iPhone Duo DISPONIBILE online!", desc + "\nCompra subito dal link.", click=url)
        log("RIVENDITORE DISPONIBILE -> " + desc + " " + url)
    if not found:
        log("Rivenditori (Unieuro, MediaWorld, R-Store): niente disponibile")
    state["notified_retail"] = sorted(found)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    for k, v in {"notified": [], "errors": 0, "started": False, "last_retail": 0,
                 "notified_retail": [], "notified_amz": [], "amz_idx": 0, "amz_asins": {},
                 "last_update_check": 0, "last_apple": 0}.items():
        state.setdefault(k, v)
    return state


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception as e:
        log(f"Stato non salvato ({e})")


def tick(state):
    retail_tick(state)
    if WHERE != "GitHub":
        amazon_tick(state)
        if time.time() - state["last_apple"] < APPLE_OGNI_SEC_COMPUTER:
            return True
    state["last_apple"] = time.time()
    try:
        available, desc = check()
        if not state["started"]:
            notify(f"Monitor iPhone Duo attivo ({WHERE})",
                   "Controllo Apple Store, Unieuro, MediaWorld e Amazon. "
                   "Se leggi questo, le notifiche funzionano.",
                   priority="default", tags="white_check_mark")
            state["started"] = True
        hits = {k: v for k, v in available.items()
                if wanted(v["model"])
                and (MAX_KM is None or v["km"] is None or v["km"] <= MAX_KM)}
        already = {tuple(x) for x in state["notified"]}
        if set(hits) - already:
            rows = sorted(hits.items(), key=lambda kv: (kv[1]["km"] is None, kv[1]["km"] or 0))
            lines = [f"{v['model']} - {store}" if v.get("raw") else
                     f"{v['model']} - Apple {store} ({v['city']}"
                     + (f", {v['km']:.0f} km" if v["km"] is not None else "") + ")"
                     for (store, _), v in rows[:8]]
            first_part = rows[0][0][1]
            slug = MODELLI.get(first_part, "").lower().replace(" ", "-")
            click = f"{BUY_URL}/display-da-7,6%22-{slug}" if slug else BUY_URL
            notify("iPhone Duo DISPONIBILE al ritiro!", "\n".join(lines) +
                   "\nTocca per aprire il modello e prenota subito il ritiro.", click=click)
            log("DISPONIBILE -> " + " | ".join(lines))
        elif hits:
            log(f"Ancora disponibile ({len(hits)} slot, gia' notificato)")
        else:
            log(f"Nessuna disponibilita' in {desc}")
        state["notified"] = [list(k) for k in hits]
        state["errors"] = 0
        return True
    except Exception as e:
        state["errors"] += 1
        log(f"Errore #{state['errors']}: {type(e).__name__}: {str(e)[:200]}")
        if state["errors"] == 5:
            notify(f"Monitor iPhone Duo: problema ({WHERE})",
                   f"5 errori di fila (ultimo: {str(e)[:150]}). Il monitor continua a riprovare.",
                   priority="high", tags="warning")
        return False


def self_update(state):
    """Su computer: se su GitHub c'e' una versione nuova, la scarica e si riavvia."""
    if WHERE == "GitHub" or not AUTO_AGGIORNAMENTO or time.time() - state["last_update_check"] < 600:
        return
    state["last_update_check"] = time.time()
    try:
        new = http_get(UPDATE_URL + f"?t={int(time.time())}", accept="text/plain", referer=None)
        path = os.path.abspath(__file__)
        with open(path, encoding="utf-8") as f:
            cur = f.read()
        if new.strip() == cur.strip() or "def amazon_tick" not in new:
            return
        compile(new, path, "exec")
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
        save_state(state)
        log("Nuova versione scaricata da GitHub: riavvio")
        os.execv(sys.executable, [sys.executable, path] + sys.argv[1:])
    except Exception as e:
        log(f"Aggiornamento non riuscito ({e})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=0, help="durata, poi esce (0 = per sempre)")
    ap.add_argument("--once", action="store_true", help="un solo controllo completo")
    args = ap.parse_args()
    if args.once:
        available, desc = check()
        log(f"Controllati: {desc}")
        for (store, part), v in sorted(available.items()):
            log(f"DISPONIBILE: {v['model']} - {store} ({v['city']})")
        if not available:
            log("Nessun iPhone Duo disponibile al ritiro in Italia")
        for desc, url in check_retailers().values():
            log(f"DISPONIBILE: {desc} {url}")
        st = load_state()
        st["notified_amz"] = []
        for dom in AMAZON:
            found = amazon_domain(dom, st)
            if found is None:
                log(f"Amazon.{dom}: non raggiungibile da qui (anti-bot)")
            for desc, url in (found or {}).values():
                log("DISPONIBILE: " + desc.replace("\n", " | ") + " " + url)
            if found == {}:
                log(f"Amazon.{dom}: niente disponibile")
        return
    log(f"Avvio monitor iPhone Duo - {WHERE} - curl_cffi: {'si' if _cffi else 'no'}")
    state = load_state()
    deadline = time.time() + args.minutes * 60 if args.minutes else None
    delay = INTERVALLO_SEC
    while True:
        ok = tick(state)
        save_state(state)
        self_update(state)
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
