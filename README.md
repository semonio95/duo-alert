# duo-alert

Notifica push (app ntfy) quando un iPhone Duo diventa ritirabile in un Apple Store italiano.

- **GitHub Actions:** il workflow parte ogni 5 minuti e controlla ogni minuto per circa 4 minuti. Il topic ntfy è nel secret `NTFY_TOPIC`.
- **Computer o VM:** `python3 duo_alert.py` gira senza fermarsi e controlla ogni minuto.

Per fermarlo su GitHub: Actions → duo-alert → "Disable workflow".
