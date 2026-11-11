# STATUS Makler-Cockpit

## P0 – Zugänge (fertig, wartet auf Antworten)

- `ZUGANG.md`: alle Zugänge mit Zweck, Bezugsweg, Kosten, Phase und Übergabe per `.env`
- Noch kein Code
- Grundlage vorhanden: `onoffice_crm/` (Phase-1-CLI: onOffice-Client mit HMAC, Briefing, Wochenbericht, 40 Tests).
  Wird in die Web-App übernommen.

### Stack-Vorschlag (für Laien wartbar)

- **Python 3.12 + FastAPI**, Seiten serverseitig mit Jinja2 + HTMX (kein JavaScript-Build, responsiv per CSS)
- **SQLite** (eine Datei: Flyer, Tracker, Parkplatz, Queue, Vorlagen, Protokoll). Backup = Datei kopieren
- **APScheduler** in der App für die Jobs (9:30, Mo/Do, Di, Vortag 15:45, Fr 15:00)
- **Docker Compose** auf dem Büro-NAS (Synology Container Manager), Zugriff und HTTPS über **Tailscale**
- Update: `git pull && docker compose up -d --build` · Backup: nächtlicher SQLite-Export in einen NAS-Ordner + NAS-Backup (Hyper Backup)

### Entschieden
- Mail: Postfach bei onOffice → Briefing per onOffice-sendmail nur an mich **oder** SMTP (beim onOffice-Support erfragen)
- Hosting: NAS im Büro + Tailscale
- Neues eigenes Repo
- Login: nur ein Nutzer

### Offen
- NAS-Modell / Docker-fähig?
- API-Modul gebucht? API-Benutzer angelegt?
- Briefing-Versand: Weg A (onOffice-API) oder B (SMTP)?
- Name des neuen Repos
- Freigabe Chef / Datenschutz
