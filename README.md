# duo-alert

Notifica push (app ntfy) quando un iPhone Duo diventa ritirabile in uno dei 17 Apple Store italiani, o acquistabile subito su Unieuro, MediaWorld o Amazon (IT, DE, FR, ES, NL, BE). Su computer si aggiorna da solo.

- **Cloud (GitHub Actions):** il workflow `monitor` parte ogni 5 minuti e controlla circa ogni minuto. L'ultimo log è nel branch `logs`.
- **Computer:** `pip install curl_cffi && python3 duo_alert.py`
- **Controllo singolo:** `python3 duo_alert.py --once`

Filtri (capacità, colore, distanza) in cima a `duo_alert.py`. Per fermarlo: Actions → monitor → "Disable workflow".
