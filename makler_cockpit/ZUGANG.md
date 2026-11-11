# Zugänge für das Makler-Cockpit

Diese Liste ist für Nicht-Techniker gedacht. Jeder Zugang wird am Ende als Zeile in die Datei `.env`
auf dem Server eingetragen. **Passwörter und Schlüssel nie per Mail, Chat oder WhatsApp verschicken.**
Am besten trägst du sie selbst auf dem Server ein, oder du gibst sie über einen Passwort-Manager weiter
(z.B. Bitwarden Send oder 1Password-Freigabe).

Legende „Pflicht ab“: P1 = Login/Einstellungen/Flyer/Tracker · P2 = onOffice lesen · P3 = onOffice schreiben ·
P4 = Versand nach Freigabe · P5 = Auto-Versand

## Übersicht

| # | Zugang | Wofür | Kosten (ca.) | Pflicht ab |
|---|---|---|---|---|
| 1 | NAS im Büro (24/7) | App + Hintergrund-Jobs laufen rund um die Uhr | 0 € (vorhandenes NAS) | P1 |
| 2 | Fernzugriff + HTTPS (Tailscale) | Aufruf von PC und Handy, auch unterwegs | 0 € | P1 |
| 3 | App-Login | Schutz der App | 0 € | P1 |
| 4 | onOffice API-Benutzer | Kontakte/Objekte/Aktivitäten lesen und schreiben | API-Modul: bei onOffice erfragen | P2 (lesen), P3 (schreiben) |
| 5 | Mail für Briefing an dich (onOffice-Mail) | Morgen-Mail um 9:30, Fehlermeldungen | 0 € | P2 |
| 6 | Mail-Postfach lesen (IMAP/Graph) | Suchauftrags-Mails → Lead-Entwürfe | 0 € | optional (P5) |
| 7 | Anthropic API-Key (KI) | Diktat → MPE-Schema, Mail-Entwürfe | ca. 10–25 €/Monat | P3 |
| 8 | Freigaben Chef / Datenschutz | Erlaubnis für Kundendaten auf Server + KI | 0 € | **vor P2** |

---

## 1. Server (24/7-Hosting)

**Was:** ein kleiner Mietserver, auf dem die App und die Hintergrund-Jobs (9:30-Briefing, Entwürfe, Bestätigungen) laufen.
Dein PC kann dafür nicht genutzt werden, weil er nicht rund um die Uhr an ist.

**Optionen:**

| Option | Kosten | Vorteil | Nachteil |
|---|---|---|---|
| **Hetzner Cloud** (Rechenzentrum in DE/Nürnberg/Falkenstein) – **Empfehlung** | ca. 5–8 €/Monat (kleinster Server) + ca. 1–2 € für automatische Backups | deutscher Anbieter, AV-Vertrag per Klick, günstig, Snapshots | Einrichtung einmalig durch mich bzw. nach Anleitung |
| IONOS / Strato VPS | ca. 5–10 €/Monat | deutscher Anbieter | Oberfläche umständlicher |
| NAS im Büro (Synology mit Docker) | 0 € laufend, falls vorhanden | Daten bleiben im Büro | Strom/Internet im Büro müssen stabil sein, HTTPS von außen ist aufwendiger |
| Eigener PC / Laptop | 0 € | – | nicht 24/7, **nicht geeignet** |

**Entscheidung: NAS im Büro.** Voraussetzungen, bitte prüfen (Wen fragen: wer das NAS eingerichtet hat):
- [ ] Modell und Hersteller? (z.B. Synology DS224+) Es muss **Docker** können: bei Synology das Paket „Container Manager“, meist nur auf „+“-Modellen mit Intel/AMD-CPU
- [ ] mindestens 2 GB RAM frei
- [ ] Admin-Zugang zum NAS (DSM-Oberfläche) oder eine Person, die ihn hat
- [ ] NAS und Internet im Büro laufen nachts und am Wochenende durch (sonst fallen Jobs aus, z.B. das Briefing um 9:30 nach Stromausfall)
- [ ] Backup des NAS vorhanden (z.B. Hyper Backup auf USB-Platte oder Cloud). Die App-Datenbank wird zusätzlich nachts in einen NAS-Ordner exportiert.

**Alternativ (falls das NAS kein Docker kann), Hetzner:**
1. Auf hetzner.com/cloud registrieren. Das sollte die Firma machen (LebensWERT GmbH als Kunde, Firmen-Kreditkarte oder SEPA).
2. In der Cloud Console: Projekt „Makler-Cockpit“ anlegen → „Server hinzufügen“ → Standort Deutschland,
   Image **Ubuntu 24.04**, kleinste Größe (2 vCPU / 4 GB RAM), Häkchen bei **Backups**.
3. AV-Vertrag (Auftragsverarbeitung): in der Console unter Konto/Datenschutz abschließen.

**Übergabe:** Die Server-IP schickst du mir. Den Zugang zum Server (SSH-Schlüssel) richten wir zusammen ein, ohne Passwort im Chat.

## 2. Fernzugriff + HTTPS (Tailscale, Empfehlung beim NAS)

**Was:** sicherer Zugriff auf die App von PC und Handy, auch außerhalb des Büros, **ohne** das NAS ins offene Internet
zu stellen und ohne Portfreigabe am Router. Tailscale baut ein privates Netz zwischen deinen Geräten auf und
liefert ein HTTPS-Zertifikat für eine Adresse wie `https://nas.<name>.ts.net`.

**Wo bekommen:**
1. Auf tailscale.com mit einem Firmen-Konto anmelden. Der kostenlose Plan reicht für wenige Nutzer und Geräte.
2. Tailscale auf dem NAS installieren (Synology: Paket-Zentrum → „Tailscale“), auf deinem PC und auf dem Handy (App Store / Play Store).
3. In der Tailscale-Verwaltung **MagicDNS** und **HTTPS-Zertifikate** einschalten.

**Kosten:** 0 €.
**Übergabe:** `.env` → `APP_DOMAIN=<nas-name>.<tailnet>.ts.net`

*Alternative:* Synology-DDNS + Let's Encrypt + Portfreigabe 443. Davon rate ich ab, weil die App dann im offenen Internet steht.

## 3. App-Login

**Was:** Benutzername und Passwort für die App (PC und Handy). Optional Zwei-Faktor-Code per Authenticator-App.
**Wo:** wird beim ersten Start der App angelegt, du brauchst vorher nichts zu besorgen.
**Übergabe:** `.env` → `APP_SECRET_KEY` (erzeuge ich automatisch). Dein Passwort setzt du selbst beim ersten Login.

## 4. onOffice API-Benutzer (Token + Secret)

**Was:** ein eigener technischer Benutzer, mit dem die App auf onOffice zugreift.
onOffice bleibt die einzige Wahrheit für Kontakte und Objekte. Die App speichert lokal nur ihre eigenen Daten
(Flyer, Tracker, Parkplatz, Entwürfe, Protokoll).

**Vorher prüfen:** Ist das **API-Modul** in eurem onOffice-Vertrag gebucht? Laut onOffice-Doku ist es ein
kostenpflichtiges Zusatzmodul. **Wen fragen:** Chef bzw. onOffice-Administrator. Falls nicht gebucht: euren
onOffice-Ansprechpartner (Vertrieb) nach Preis fragen.

**Wo bekommen (Administrator):**
1. In onOffice enterprise einen API-Benutzer anlegen (Extras → Einstellungen → Benutzer bzw. API-Benutzer;
   der genaue Pfad hängt von der Version ab, im Zweifel den onOffice-Support fragen).
2. Beim Anlegen erzeugt onOffice einen **Token** und ein **Secret**.
3. **Rechte** des API-Benutzers. Laut Doku reicht „nur eigene Datensätze“ nicht.
   - Lesen: Adressen, Objekte, Maklerbuch (Aktivitäten), Aufgaben, Termine, Feldkonfiguration
   - Schreiben (ab P3): Adressen, Objekte, Aktivitäten, Aufgaben
   - Mailversand (ab P4): dem API-Benutzer eine **E-Mail-Identität** (Absenderadresse) zuweisen. Ohne diese
     Zuweisung kann über onOffice keine Mail verschickt werden.
4. Für Phase 2 reichen Leserechte. Schreibrechte erst vor Phase 3 freischalten.

**Kosten:** API-Modul laut onOffice-Vertrag. Der Benutzer selbst kostet in der Regel nichts extra; bitte bestätigen lassen.

**Übergabe:** `.env` → `ONOFFICE_TOKEN=…`, `ONOFFICE_SECRET=…`, später `ONOFFICE_EMAIL_IDENTITY=…`

**Gut zu wissen:** Kunden-Mails sollen über onOffice verschickt werden. Dann landen sie automatisch im Maklerbuch,
und Makros wie `_agreementLink` funktionieren. Ein eigener Mailserver wird dafür nicht gebraucht.

## 5. Mail für das Briefing an dich (Postfach bei onOffice)

**Was:** Die App schickt dir um 9:30 das Briefing und meldet Fehler. Die Mail geht nur an dich, nie an Kunden.

Euer Postfach liegt bei onOffice. Es gibt zwei Wege:

| Weg | Was nötig ist | Bewertung |
|---|---|---|
| **A: Versand über die onOffice-API** (`sendmail`, Empfänger fest = deine Adresse) | Dem API-Benutzer eine E-Mail-Identität zuweisen (siehe Punkt 4) | Kein zusätzliches Passwort. Technisch ist das aber ein schreibender API-Aufruf; ich würde ihn ab P2 **nur für Mails an dich** freischalten. |
| **B: SMTP/IMAP des onOffice-Postfachs** | Beim **onOffice-Support** fragen: „Bieten Sie SMTP/IMAP-Zugang für unsere Postfächer? Server, Port, Verschlüsselung, Benutzername?“ | Funktioniert unabhängig von der API. Wird außerdem für Punkt 6 (Postfach lesen) gebraucht. |

**Kosten:** 0 €.
**Übergabe:** A: `ONOFFICE_EMAIL_IDENTITY`, `MAIL_TO` · B: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`, `MAIL_TO` (für Punkt 6 zusätzlich `IMAP_HOST`, `IMAP_PORT`)

## 6. Postfach lesen (optional, Suchauftrags-Mails)

**Was:** Die App liest einen **eigenen Ordner** (z.B. „Suchaufträge“), in den die Portal-Benachrichtigungen per Regel
einsortiert werden. Daraus macht sie Lead-Entwürfe und filtert Anzeigen mit „keine Makler“ heraus.
**Kein Scraping**: Portale werden nicht direkt abgefragt. Nachrichten verschickst du immer selbst.
**Wo/Übergabe:** IMAP-Zugang wie Punkt 5 Weg B (beim onOffice-Support erfragen), plus `.env` → `IMAP_FOLDER=Suchaufträge`.
**Pflicht:** nein, optional.

## 7. Anthropic API-Key (KI)

**Was:** wandelt Diktate in das MPE-Schema um und schreibt Mail-Entwürfe. Die KI verschickt nichts selbst:
jeder Entwurf geht zuerst in die Freigabe-Queue.

**Wo bekommen:**
1. platform.claude.com (früher console.anthropic.com) → als Firma registrieren.
2. Settings → Billing → Guthaben aufladen (Prepaid, z.B. 20 €) und ein **Ausgabenlimit** setzen (z.B. 30 €/Monat).
3. Settings → API Keys → „Create Key“ (Name: Makler-Cockpit).
4. Unter Settings / Legal den **Datenverarbeitungsvertrag (DPA)** prüfen bzw. akzeptieren (siehe Punkt 8).

**Kosten:** Abrechnung nach Nutzung. Schätzung mit dem aktuellen Modell (Claude Opus 5.5) bei ca. 10 Diktaten pro Tag
und ca. 30 Mail-Entwürfen pro Woche: **ca. 10–25 € im Monat**. Mit einem kleineren Modell geht es auch für etwa die Hälfte.
Das Ausgabenlimit verhindert Überraschungen.

**Übergabe:** `.env` → `ANTHROPIC_API_KEY=sk-ant-…`

## 8. Freigaben: Chef und Datenschutz (DSGVO) – vor Phase 2 klären

Ich kann keine Rechtsberatung geben. Diese Punkte sollten Chef und, falls vorhanden, Datenschutzbeauftragter abhaken:

- [ ] **Chef einverstanden**, dass ein Tool per API mit onOffice arbeitet (Lesen ab P2, Schreiben ab P3, Versand ab P4)
- [ ] **Hosting auf dem eigenen NAS:** kein externer Hoster nötig. Tailscale überträgt nur verschlüsselt und speichert keine App-Daten; trotzdem prüfen, ob ein AV-Vertrag nötig ist
- [ ] **KI-Anbieter (Anthropic, USA):** Datenverarbeitungsvertrag (DPA mit Standardvertragsklauseln) akzeptiert?
      Dürfen Diktate mit Eigentümerdaten dorthin? Alternative: Namen und Telefonnummern vor dem KI-Aufruf entfernen.
- [ ] **onOffice:** erlaubt euer Vertrag die API-Nutzung durch ein selbst betriebenes Tool? (normalerweise ja)
- [ ] **Verzeichnis der Verarbeitungstätigkeiten** um „Makler-Cockpit“ ergänzen
- [ ] **Werbe-Mails:** MPE-Angebote an Interessenten nur mit dokumentiertem Opt-in (im Tool bereits als Regel vorgesehen)
- [ ] **Auto-Versand (P5):** Chef gibt jeden Mailtyp einzeln frei. Im Tool gibt es einen Schalter pro Mailtyp, einen Kill-Switch und einen Testmodus.

## Was ich (Claude) hier im Cloud-Container NICHT brauche

Keine echten Zugangsdaten. Gebaut und getestet wird mit einer nachgebauten onOffice-API.
Die echten Werte kommen erst auf dem Server in die `.env`.
