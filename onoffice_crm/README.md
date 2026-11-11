# CRM-Automatisierung onOffice (LebensWERT GmbH)

Python-Tool für Makler-Routinen auf Basis der **onOffice enterprise API**.
Modular aufgebaut. **Phase 1 ist rein lesend**: tägliches Briefing und Wochenbericht
per Mail **an mich selbst**. Es wird nichts in onOffice geändert und nichts an Kunden verschickt.

| Phase | Modul | Status |
|---|---|---|
| 1 | `briefing`: täglich 9:30, Wochentags-Stapel + Tagesthemen | ✅ |
| 1 | `wochenbericht`: Fr 15:00, Zähler Mo–Fr vs. Vorwoche, Entwurf für den Chef | ✅ |
| 1 | `verbindungstest`, `konfig-pruefen`: Hilfsbefehle, nur lesend | ✅ |
| 2 | `mpe_erfassung`, `eigentuemer_nachfass`, `verkaeufer_update` | Stub/Interface |
| 3 | `auto_versand` (inkl. Sicherungen in `core/safety.py`) | Stub/Interface |
| 4 | `kleinanzeigen_assistent` (nur IMAP-Mailordner, kein Scraping, Versand manuell) | Stub |

## Aufbau

```
onoffice_crm/
├── main.py                  CLI: python main.py <modul> [--dry-run] [--console] [--datum YYYY-MM-DD]
├── config.yaml              Aktionsarten, Merkmale, Intervalle, Wochentags-Stapel (editierbar)
├── .env.example             Vorlage für Secrets -> .env (nie einchecken)
├── core/
│   ├── onoffice_client.py   Auth (HMAC v2), Request, Retry, Rate-Limit, Fehler, Schreibsperre
│   ├── repository.py        fachliche Lesezugriffe (Maklerbuch, Adressen, Objekte, Termine, Aufgaben)
│   ├── regeln.py            reine Fachlogik (Fälligkeiten, "ohne Antwort", Stufe 1/2, Zähler)
│   ├── config.py            .env + config.yaml
│   ├── logger.py            Logging mit Maskierung (Secrets, E-Mail, Telefon)
│   ├── mailer.py            SMTP, nur an MAIL_TO
│   ├── safety.py            Versand-Sicherungen für Phase 2/3 (noch nicht verdrahtet)
│   └── timeutil.py          Europe/Berlin, Wochentage, Datumsformate
├── modules/                 je Modul eine Datei, Registry in modules/__init__.py
├── templates/               Jinja2 HTML-Mails (mobil lesbar)
└── tests/                   pytest mit Fake-API (prüft auch HMAC, sendet nie Schreib-Actions)
```

## Setup

Python 3.10+.

```bash
cd onoffice_crm
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # Windows: copy .env.example .env
```

### .env

| Variable | Bedeutung |
|---|---|
| `ONOFFICE_TOKEN`, `ONOFFICE_SECRET` | API-Benutzer in onOffice (Extras > Einstellungen > API-Benutzer). Der API-Benutzer braucht Leserechte auf **alle** Datensätze ("nur eigene" reicht laut Doku nicht). |
| `ONOFFICE_API_URL` | Standard `https://api.onoffice.de/api/stable/api.php` |
| `DRY_RUN` | `true` (Standard): schreibende onOffice-Aktionen werden nur protokolliert. In Phase 1 ist Schreiben zusätzlich hart gesperrt. |
| `AUTOMATION_ENABLED` | Kill-Switch für spätere Auto-Mails. Standard `false`. |
| `TESTMODE`, `TEST_WHITELIST` | Spätere Kunden-Mails nur an Whitelist-Adressen (kommagetrennt). |
| `SMTP_*`, `MAIL_FROM`, `MAIL_TO` | Versand des Briefings an mich. `SMTP_SECURITY` = `starttls` (587) / `ssl` (465) / `none` |
| `LOG_LEVEL`, `LOG_DIR` | Logs unter `logs/crm.log` (rotierend), personenbezogene Daten maskiert |

### Schritt für Schritt

```bash
python main.py verbindungstest       # liest je 1 Adresse/Objekt/Aktivität, gibt nur IDs aus
python main.py konfig-pruefen        # gleicht config.yaml mit Aktionsarten/Feldern im System ab
python main.py briefing --console    # Briefing als Text, keine Mail
python main.py briefing --console --datum 2026-11-10   # anderen Wochentag simulieren
python main.py briefing --dry-run    # HTML nach out/, keine Mail
python main.py briefing              # Mail an MAIL_TO
python main.py wochenbericht --console
pytest                               # Tests (ohne echte API)
```

Exit-Codes: `0` ok, `1` konfig-pruefen fand Probleme, `3` Konfiguration, `4` Authentifizierung,
`5` API-Fehler, `6` Mail-Fehler.

## config.yaml ausfüllen

1. **Aktionsarten**: deutsche Namen genau so, wie sie unter Extras > Einstellungen >
   Administration > Aktionsarten stehen. `konfig-pruefen` listet alle Aktionsarten im System
   und markiert falsche Einträge mit ✗. Eine Aktionsart kann auch mit Aktionstyp angegeben
   werden: `{aktionsart: "Email", aktionstyp: "Eingang"}`.
2. **Merkmale**: `adresse.merkmal_feld` ist der Feldname des Multiselect-Felds im Adressmodul.
   Darunter stehen die gespeicherten Werte (Schlüssel, nicht die Anzeige-Labels).
   `konfig-pruefen` zeigt alle Multiselect-Felder mit ihren Schlüsseln.
3. **Objekte**: `vermarktung_filter` und `reserviert_filter` werden unverändert als onOffice-Filter
   übergeben. Für die Laufzeit-Warnung muss `objekte.vermarktungsbeginn_feld` gesetzt sein
   (`konfig-pruefen` listet die Datumsfelder).
4. **Wochentage**: Welche Abschnitte an welchem Tag erscheinen, steht unter `wochentage` und
   `taeglich`. Ein Abschnitt, der noch nicht konfiguriert ist, steht trotzdem in der Mail, mit einem
   gelben Hinweis statt Daten. Das Briefing läuft also auch mit unvollständiger Konfiguration.

## Fachlogik (kurz)

- **Portal-Anfragen** gelten seit dem vorherigen Werktag (montags also seit Freitag).
  Stufe 2 heißt: Für die Adresse gibt es eine Aktivität `agreement_bestaetigt` (Lookback 365 Tage).
- **Stufe-1-Runden**: Grundlage ist die Zahl der Aktivitäten `stufe1_erinnerung` nach der Anfrage.
  Ist diese Aktionsart nicht gesetzt, wird die Runde aus dem Alter der Anfrage geschätzt.
- **MPE-Nachfass**: Ausgangspunkt ist die letzte MPE. Stufe k ist die Zahl der Nachfass-Aktivitäten danach.
  Fällig, sobald MPE-Datum + `intervalle.mpe[k]` erreicht ist.
- **Kaltakquise ohne Antwort**: Die letzte Kaltakquise liegt 10–30 Tage zurück, und seitdem gibt es
  keine `antwort_aktionsarten`.
- **Ohne nächsten Schritt**: Kontakte mit den Merkmalen MPE/Eigentümer-Lead, die weder einen Termin
  in den nächsten 90 Tagen noch eine offene Aufgabe mit künftiger Deadline haben.

## Scheduler

Das Briefing läuft Mo–Fr um 9:30, der Wochenbericht Fr um 15:00.

### Linux (cron)

```cron
CRON_TZ=Europe/Berlin
30 9 * * 1-5  cd /pfad/onoffice_crm && .venv/bin/python main.py briefing      >> logs/cron.log 2>&1
0 15 * * 5    cd /pfad/onoffice_crm && .venv/bin/python main.py wochenbericht >> logs/cron.log 2>&1
```

(`crontab -e`. Läuft der Server in Europe/Berlin, kann `CRON_TZ` entfallen.)

### Windows (Aufgabenplanung)

PowerShell:

```powershell
$dir = "C:\Pfad\onoffice_crm"
$py  = "$dir\.venv\Scripts\python.exe"
$a1 = New-ScheduledTaskAction -Execute $py -Argument "main.py briefing" -WorkingDirectory $dir
$t1 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 9:30
Register-ScheduledTask -TaskName "CRM Briefing" -Action $a1 -Trigger $t1

$a2 = New-ScheduledTaskAction -Execute $py -Argument "main.py wochenbericht" -WorkingDirectory $dir
$t2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 15:00
Register-ScheduledTask -TaskName "CRM Wochenbericht" -Action $a2 -Trigger $t2
```

Alternativ in der GUI über "Einfache Aufgabe erstellen": Programm = `...\.venv\Scripts\python.exe`,
Argumente = `main.py briefing`, "Starten in" = Projektordner. Der Rechner muss zu dieser Zeit laufen.
Unter Windows installiert `requirements.txt` zusätzlich `tzdata` für die Zeitzone.

## Sicherheit & Datenschutz

- Secrets stehen nur in `.env`. Die Datei ist per `.gitignore` ausgeschlossen. In Logs und `repr()` werden sie maskiert.
- Phase 1 ist nur lesend. Der Client lässt nur die Actions `read` und `get` zu. `create`/`modify`/`delete`/`do`
  werfen `WriteBlockedError`, solange der Client nicht mit `allow_write=True` erzeugt wird. Auch dann gilt `DRY_RUN`.
  Ein Test stellt sicher, dass im Briefing nur `read`/`get` gesendet werden.
- Logs enthalten nur IDs, Zähler und Laufzeiten. Namen und Notizen werden nicht geloggt. Zusätzlich
  maskiert ein Filter E-Mail-Adressen und Telefonnummern.
- Die Mail geht nur an `MAIL_TO`. Andere Empfänger sind im Mailer ausgeschlossen.
- Für spätere Versand-Module (`core/safety.py`, schon getestet): Agreement-Pflicht für 3D-Link, Exposé und
  Unterlagen; höchstens 1 Auto-Mail je Kontakt in 3 Tagen; Merkmal `keine_automatik` schließt den Kontakt aus;
  Kill-Switch `AUTOMATION_ENABLED`; Testmodus mit Whitelist; Protokoll jedes Versands.

## API-Grundlagen (laut apidoc.onoffice.de)

- POST an `https://api.onoffice.de/api/stable/api.php`.
  Aufbau: `{"token", "request": {"actions": [...]}}`.
- HMAC v2 = `base64(HMAC-SHA256(timestamp + token + resourcetype + actionid, secret))`, `hmac_version: "2"`.
- Genutzt werden: `read` address/estate/agentslog/task, `get` appointmentList (der alte `calendar`-Read ist
  deprecated), `get` actionkindtypes, `get` fields. `listlimit` ist höchstens 500. Die Doku nennt kein Rate-Limit;
  das Tool hält trotzdem einen Mindestabstand ein (`api.min_abstand_s`).
- Nicht in der Doku verifiziert und deshalb in config.yaml: Merkmal-Feld, Feld für den Vermarktungsbeginn,
  Status-Werte von Aufgaben und alle Aktionsart-Namen.
