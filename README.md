# duo-alert

Notifica push (app ntfy) quando un iPhone Duo diventa ritirabile in un Apple Store italiano.

Va eseguito da un computer sulla connessione di casa: Apple blocca l'API di disponibilità per le richieste che arrivano da server cloud (verificato da GitHub Actions, anche con un browser Chromium vero).

```
pip install curl_cffi        # consigliato, non obbligatorio
python3 duo_alert.py         # Mac: caffeinate -i python3 duo_alert.py
```

I codici prodotto italiani (MK2D4QL/A … MK2L4QL/A) vengono letti in automatico dalle pagine Apple.
