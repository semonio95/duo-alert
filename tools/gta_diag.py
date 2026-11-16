import re, sys, time, random
sys.path.insert(0, ".")
from gta_alert import BLOCCO, txt
from curl_cffi import requests as R
A = "B0HHS4DKRM"
H = {"Accept": "text/html,application/xhtml+xml,*/*", "Accept-Language": "it-IT,it;q=0.9"}
def show(name, r):
    t = r.text
    b = bool(BLOCCO.search(t))
    am = re.search(r'id="availability"[^>]*>(.*?)</div>', t, re.S)
    cart = any(x in t for x in ('add-to-cart-button', 'buy-now-button'))
    print(f"{name}: HTTP {r.status_code} len={len(t)} blocked={b} cart={cart} avail={txt(am.group(1))[:80] if am else '-'} | {txt(t)[:160] if b or len(t)<3000 else ''}", flush=True)
for imp in ["chrome", "chrome131", "safari17_0", "safari_ios", "firefox133", "edge101"]:
    try:
        s = R.Session(impersonate=imp)
        show(f"[{imp}] home", s.get("https://www.amazon.it/", headers=H, timeout=25))
        time.sleep(1.5)
        show(f"[{imp}] dp", s.get(f"https://www.amazon.it/dp/{A}", headers=H, timeout=25))
        time.sleep(1.5)
        show(f"[{imp}] mobile", s.get(f"https://www.amazon.it/gp/aw/d/{A}", headers=H, timeout=25))
        time.sleep(1.5)
        show(f"[{imp}] aod", s.get(f"https://www.amazon.it/gp/product/ajax/aodAjaxMain/?asin={A}&pc=dp&experienceId=aodAjaxMain", headers=H, timeout=25))
        time.sleep(1.5)
    except Exception as e:
        print(imp, "ERR", e)
for u in [f"https://r.jina.ai/https://www.amazon.it/dp/{A}"]:
    try:
        r = R.get(u, impersonate="chrome", timeout=60)
        print("JINA", r.status_code, len(r.text), r.text[:1500].replace("\n", " | "))
    except Exception as e:
        print("JINA ERR", e)
