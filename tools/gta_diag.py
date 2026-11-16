import re, sys, time, random
sys.path.insert(0, ".")
from gta_alert import BLOCCO, txt
from curl_cffi import requests as R
A = "B0HHS4DKRM"
H = {"Accept": "text/html,application/xhtml+xml,*/*", "Accept-Language": "it-IT,it;q=0.9"}
for i in range(12):
    imp = random.choice(["chrome131", "firefox133", "edge101", "chrome"])
    s = R.Session(impersonate=imp)
    r = s.get("https://www.amazon.it/", headers=H, timeout=25)
    if BLOCCO.search(r.text):
        open("/tmp/l/interstitial.html", "w").write(r.text)
        f = re.search(r'<form[^>]*action="([^"]+)"(.*?)</form>', r.text, re.S)
        if f:
            fields = dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', f.group(2)))
            act = f.group(1); act = act if act.startswith("http") else "https://www.amazon.it" + act
            r2 = s.get(act, params=fields, headers=H, timeout=25)
            print(i, imp, "continue form", act, fields, r2.status_code, bool(BLOCCO.search(r2.text)), flush=True)
    time.sleep(1)
    r = s.get(f"https://www.amazon.it/dp/{A}", headers=H, timeout=25)
    b = bool(BLOCCO.search(r.text))
    print(i, imp, "dp blocked=", b, len(r.text), flush=True)
    if not b:
        open("/tmp/l/dp.html", "w").write(r.text)
        break
