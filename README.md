# duo-alert

Notifica push (app ntfy) quando la **Custodia per iPhone Duo - Blu marino** (MKR84ZM/A, 89 €) è ritirabile **oggi** all'Apple Store **Porta di Roma**. Nessun altro negozio, niente spedizione, niente date future.

- **Cloud (GitHub Actions):** il workflow `monitor` controlla ogni ~45 secondi, a giri di 9 minuti in catena. L'ultimo log è nel branch `logs`.
- **Controllo singolo:** `python3 duo_alert.py --once`
- Su computer lo script non fa nulla e si chiude.

Per fermarlo: Actions → monitor → "Disable workflow".

## Alert DualSense GTA VI Bianco (Amazon.it)

Il workflow `gta` controlla ogni ~75 secondi la pagina Amazon.it del **Controller DualSense – Grand Theft Auto VI Bianco Edizione limitata** (ASIN B0HHS4DKRM) e manda una notifica ntfy appena torna acquistabile (anche da altri venditori: la notifica riporta prezzo e venditore). Ultimo log nel branch `gta-logs`. Per fermarlo: Actions → gta → "Disable workflow".
