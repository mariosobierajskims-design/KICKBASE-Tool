# Kickbase-Tool

Automatisierte Spieleranalyse für Kickbase (inoffizielle API). Berechnet für
jeden verfügbaren Bundesliga-Spieler 15 Kennzahlen und daraus drei gewichtete
Rankings: **Aufstellung**, **Kauf**, **Verkauf**.

> Nutzt die unveröffentlichte Kickbase-API. Nicht offiziell unterstützt, kann
> jederzeit ohne Vorwarnung von Kickbase geändert werden. Nur für den
> persönlichen Gebrauch. Kennzahl 11 (Heim/Auswärts) ruft zusätzlich die
> freie [OpenLigaDB](https://www.openligadb.de/)-API für echte offizielle
> Bundesliga-Ergebnisse ab (kein API-Key nötig, siehe "Heim/Auswärts-
> Datenquelle" unten).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt      # oder requirements-dev.txt für Tests

cp .env.example .env
# .env mit echten Zugangsdaten ausfüllen (siehe unten, je nach Login-Art)
```

Die `.env`-Datei wird von `.gitignore` ausgeschlossen und nie eingecheckt.
Zugangsdaten stehen an keiner Stelle im Code — sie werden ausschließlich zur
Laufzeit über `python-dotenv` aus `.env` gelesen (`kickbase_tool/config.py`).

Eine Liga-ID ist für die Kern-Datenbank **nicht** nötig: der komplette
Bundesliga-Spielerpool, Performance-Historie, Marktwerte, Tabelle und
Spielplan kommen aus liga-unabhängigen `/v4/competitions/...`-Endpunkten.
`KICKBASE_LEAGUE_ID` wird nur für optionale, noch nicht eingebaute Extras
gebraucht (eigener Kader/Markt einer bestimmten Liga).

### Login über Apple/Google ("Sign in with")

Kickbase-Accounts, die nur über Apple/Google verknüpft sind, haben kein
Passwort — der dokumentierte Login-Endpoint akzeptiert aber ausschließlich
Email+Passwort, ein API-Weg für Social-Login ist öffentlich nicht bekannt.
Kickbase hat außerdem **keine Web-App** (nur iOS/Android); `auth.kickbase.com`
läuft über eine eigene SSO-Instanz (Authentik), nicht über eine normal
erreichbare Login-Seite. Ein Token lässt sich deshalb nicht per Browser-
DevTools abgreifen, sondern nur aus dem Netzwerkverkehr der **Handy-App**:

1. Ein HTTPS-Intercepting-Proxy-Tool installieren, z.B.
   [HTTP Toolkit](https://httptoolkit.com/) (kostenlos, mit eingebauter
   Anleitung für Android/iOS-Interception) oder alternativ Proxyman/mitmproxy.
2. Handy gemäß Tool-Anleitung verbinden (Zertifikat installieren, Proxy
   aktivieren).
3. Kickbase-App öffnen, eine Aktion ausführen (z.B. Kader öffnen), damit
   Traffic zu `api.kickbase.com` entsteht.
4. In einer der Anfragen den `Authorization: Bearer ...`-Header oder das
   Cookie `kkstrauth` finden und den Wert kopieren.
5. In `.env` statt `KICKBASE_EMAIL`/`KICKBASE_PASSWORD` eintragen:
   ```
   KICKBASE_AUTH_TOKEN=<kopierter-wert>
   ```

Der Token läuft nach einiger Zeit ab und muss dann auf demselben Weg erneuert
werden (`kickbase_tool/api/client.py:use_token()`).

## Nutzung

```bash
python -m kickbase_tool --top 20
python -m kickbase_tool --position ST --top 10
python -m kickbase_tool --csv-out out/          # vollständiger Export aller Kennzahlen
python -m kickbase_tool --refresh               # Cache ignorieren, alles neu laden
python -m kickbase_tool --weights meine_gewichte.yaml
```

Wiederholte Läufe nutzen einen lokalen Datei-Cache (`.cache/`, ebenfalls
gitignored): Tabellenstand/Marktdaten werden 1h, Spieler-Performance-Historie
24h zwischengespeichert, um die Kickbase-API nicht unnötig oft zu belasten.
`--refresh` erzwingt einen kompletten Neu-Abruf.

### Gewichtung anpassen

Alle Kategorie-Gewichte liegen in [`kickbase_tool/ranking/weights.yaml`](kickbase_tool/ranking/weights.yaml),
standardmäßig alle gleich gewichtet (1.0). Datei direkt bearbeiten oder eine
eigene Kopie über `--weights` übergeben — kein Code-Änderung nötig.

## Die Kennzahlen

1. Punkte-Ø Saison
2. Punkte-Ø letzte 5 Spiele (mit Fallback-Logik, siehe unten)
3. Minimum letzte 5 Spiele (gleiche Fallback-Logik)
4. Maximum letzte 5 Spiele (gleiche Fallback-Logik)
5. Ø aus Min/Max
6. Aktueller Marktwert — **nur Aufstellung**, höher = besser (Qualitätssignal)
7. Punkte pro Marktwert (Effizienz) — **nur Kauf/Verkauf**
8. Team-Form: Ø Team-Punkte der letzten 5 Spiele
9. Gegner-Form: gleiche Kennzahl für den nächsten Gegner
10. Tabellenplatz-Differenz zum nächsten Gegner — basiert NICHT auf der
    offiziellen Bundesliga-Tabelle, sondern auf einer selbst gebauten
    "Form-Tabelle" (alle 18 Teams nach ihrem eigenen Kennzahl-8-Wert gerankt)
11. Heim/Auswärts-Stärke zum nächsten Gegner (echte offizielle Bundesliga-
    Ergebnisse via OpenLigaDB, siehe unten), aufgeteilt in 3 einzeln
    gewichtete Spalten: Rang des eigenen Teams, Rang des Gegners (jeweils in
    der für sie zutreffenden Heim- bzw. Auswärts-Tabelle), und die Differenz
    daraus
12. Tore, Vorlagen, zu-Null-Spiele (eine kombinierte Rang-Kategorie, intern
    90:35:20 gewichtet — siehe unten)
14. Verletzt/Gesperrt-Flag (Filter, kein Rang-Kriterium)
15. Restprogramm-Schwierigkeit **des nächsten Gegners** (Ø Tabellenplatz seiner
    nächsten 5 Gegner) — ein schweres Restprogramm für ihn gilt als gut für
    unseren Spieler. Fürs **eigene** Team bleibt dieselbe Kennzahl nur eine
    Info-Spalte, kein Rang-Kriterium.
16. Formsteigerung **des nächsten Gegners** (siehe "Formsteigerung" unten) —
    ein schwacher/abfallender Gegner gilt als gut für unseren Spieler.

Kennzahl 13 (Startelf-Wahrscheinlichkeit) aus der ursprünglichen
Aufgabenstellung ist auf ausdrücklichen Wunsch weiterhin **nicht** Teil der
Rankings. Kennzahl 14 ist ein **Ausschlussfilter**: betroffene Spieler tauchen
in keinem der drei Rankings auf (harte Filterung, kein Soft-Ranking). In die
gewichtete Rang-Mittelung fließen deshalb 14 Kategorien (Aufstellung) bzw.
14 Kategorien (Kauf/Verkauf, mit Punkte-pro-Marktwert statt Marktwert) ein —
siehe `kickbase_tool/ranking/scoring.py:BASE_CATEGORIES`.

**Verkauf** verwendet dieselben Kategorien wie **Kauf**, aber mit umgekehrter
Rangfolge je Kategorie (Rang 1 in "Kauf" wird zu Rang N in "Verkauf" und
umgekehrt) und einer eigenen, deutlich stärker auf Saison-Ø fokussierten
Gewichtung (siehe `weights.yaml`).

### Heim/Auswärts-Datenquelle (Kennzahl 11)

Verwendet die **echten offiziellen** Bundesliga-Heim/Auswärts-Ergebnisse, wie
gewünscht — allerdings nicht von kicker.de (aus dieser Entwicklungsumgebung
per Egress-Proxy blockiert, sowohl direkt als auch über den WebFetch-Weg),
sondern von der freien [OpenLigaDB](https://www.openligadb.de/)-API
(`kickbase_tool/data/openligadb.py`): echte Spielergebnisse pro Spieltag,
daraus selbst berechnete Liga-Punkte (3/1/0) getrennt nach Heim- und
Auswärtsspielen, macht Punkte-pro-Spiel je Team und Spielort.

Ein erster Abgleich (season "2025" = Saison 2025/26) zeigte einen 3-Team-
Unterschied zum Kickbase-Kader (Elversberg/Paderborn/Schalke bei Kickbase
statt Heidenheim/St. Pauli/Wolfsburg). Season "2026" (2026/27, die laut
Kickbase-Tabelle aktuell laufende Saison) stimmt dagegen **exakt** mit allen
18 Kickbase-Teams überein (bestätigt live 2026-09-09). OpenLigaDB benennt
Saisons nach ihrem Startjahr; falls die von Kickbase getrackte Saison sich
mal ändert, per `KICKBASE_BL_SEASON` in `.env` anpassbar (Default: aktuelles
Jahr, vor Juli automatisch das Vorjahr).

3 Vereinsnamen unterscheiden sich zwischen den beiden Quellen und werden über
eine kleine Alias-Tabelle gemappt (`openligadb.TEAM_NAME_ALIASES`): Schalke
(Kickbase) ↔ S04 (OpenLigaDB-Kurzname), Hamburg ↔ HSV, M'gladbach ↔ Gladbach.

Schlägt der OpenLigaDB-Abruf fehl (Netzwerk) oder lässt sich ein Verein nicht
zuordnen, fällt das Tool automatisch auf eine Kickbase-interne
Fantasy-Punkte-Schätzung zurück (dieselbe Quelle, die vorher `venue_form_diff`
nutzte) — siehe `build_team_venue_ranks` in
`kickbase_tool/metrics/calculations.py`.

## Fallback-Logik für "letzte 5 Spiele" (Kennzahl 2-4)

Implementiert in [`kickbase_tool/metrics/fallback.py`](kickbase_tool/metrics/fallback.py),
mit Tests in [`tests/test_fallback.py`](tests/test_fallback.py):

| Gespielte Spiele der letzten 5 Spieltage | Verwendete Spiele |
|---|---|
| 5 von 5 | genau diese 5 |
| 4 von 5 | genau diese 4 |
| 3 von 5 | die letzten **4** tatsächlich bestrittenen Spiele (auch wenn dafür weiter zurückgegangen wird) |
| 0-2 von 5 | die letzten **5** tatsächlich bestrittenen Spiele (unabhängig davon wie weit das zurückliegt) |

## Herkunft der Gewichte

`kickbase_tool/ranking/weights.yaml` ist kalibriert an einem bereits bestehenden
Google Sheet des Nutzers (eigenes, manuell gepflegtes Rang-basiertes
Bewertungssystem, abgeglichen am 2026-09-05). Vorgehen:

- Wo das Sheet für eine Kategorie eine erkennbare Formel-Gewichtung hatte, wurde
  genau dieser Wert übernommen (z.B. Saison-Ø 20% bei Aufstellung/Kauf, aber 35%
  bei Verkauf; PPM 15-17,5% bei Kauf/Verkauf).
- Kategorien ohne erkennbare Entsprechung im Sheet (z.B. Min/Max einzeln,
  Tabellenplatz-Differenz) behalten den Standardwert 1.0.
- Die interne 90:35:20-Gewichtung von Tore:Vorlagen:Zu-Null innerhalb Kennzahl 12
  stammt direkt aus der entsprechenden Sheet-Formel
  (`=SUM(Rang_Tore*90+Rang_Vorlagen*35+Rang_ZuNull*20)/145`).
- Das Sheet selbst rankt nur unter einer kuratierten Wunschliste (~25 Spieler);
  auf ausdrücklichen Wunsch ranken die 3 Tool-Rankings stattdessen über den
  **kompletten** Bundesliga-Pool.
- Eine Abweichung der Sheet-Formeln von der ursprünglichen Aufgabenstellung
  wurde bewusst **nicht** übernommen: Verkauf verwendet weiterhin die volle
  Kauf-Kategorienliste (nur umgekehrt), statt der im Sheet enger gefassten
  Auswahl.
- Marktwert/Punkte-pro-Marktwert wurden auf spätere ausdrückliche Anweisung
  neu aufgeteilt: Marktwert (höher = besser) zählt nur noch bei Aufstellung,
  Punkte-pro-Marktwert nur noch bei Kauf/Verkauf (ursprünglich war Marktwert
  bei Kauf/Verkauf mit "günstiger = besser" gewichtet und bei Aufstellung
  komplett ausgeschlossen).

## Live-Stand der Feldnamen

Die öffentliche, inoffizielle Kickbase-v4-Doku
([kevinskyba/kickbase-api-doc](https://github.com/kevinskyba/kickbase-api-doc),
[simonsagstetter/kickbase-api-v4-docs](https://github.com/simonsagstetter/kickbase-api-v4-docs))
listet alle Endpunkt-Pfade zuverlässig, liefert aber kaum Beispiel-Response-
Bodies. Die tatsächlichen Feldnamen in `kickbase_tool/data/normalize.py` sind
deshalb **live gegen die echte API verifiziert** (per `dump_raw.py`, siehe
unten), nicht nur geraten. Wichtigste bestätigte Erkenntnisse:

- **`/v4/competitions/{id}/players` liefert NICHT den vollen Spielerpool** —
  nur die ~2 Teams des aktuellen Spieltags-Kontexts (bei uns 25 von ~500
  Spielern). Der volle Pool wird stattdessen so zusammengesetzt: Tabelle
  abrufen (18 Teams) → pro Team `/teams/{teamId}/teamprofile` (liefert den
  kompletten Kader dieses Teams) → pro Spieler
  `/players/{playerId}` (Detail: Marktwert, Saison-Ø, Status, Tore/Vorlagen/
  zu-Null) + `/players/{playerId}/performance` (Spieltag-für-Spieltag-Historie).
  Macht insgesamt ca. 18 + 2×500 Anfragen, mit Cache + Nebenläufigkeit
  handhabbar (kompletter Lauf aktuell ca. 1 Minute).
- **Bestätigte Feldnamen** (Kurzformen, wie sie die API tatsächlich benutzt):
  Spieler-Id `i`, Vorname `fn`, Nachname `ln`, Team-Id `tid`, Position `pos`,
  Status `st`, Marktwert `mv`, Saison-Punkte-Ø `ap`, Tore `g`, Vorlagen `a`,
  zu-Null-Spiele `cs`. Tabelle: Team-Id `tid`, Team-Name `tn`, Tabellenplatz
  `cpl`. Spielplan: Heimteam `t1`, Auswärtsteam `t2`, Status `st` (2 =
  beendet). Performance-Historie: Spieltag `day`, Punkte `p` (fehlt = nicht
  gespielt), Minuten `mp` (als String `"90'"`, wird geparst), Start-Flag
  `st == 5`.
- **Tore/Vorlagen/zu-Null (Kennzahl 12) sind NICHT pro Spieltag verfügbar** —
  nur als Saison-Summe auf dem Spieler-Detail-Endpunkt (`g`/`a`/`cs`). Deshalb
  kommen diese drei Werte direkt von dort, nicht durch Aufsummieren der
  Performance-Historie.
- **Verletzt/Gesperrt-Status** (Kennzahl 14): `st == 0` wurde live für gesunde
  Spieler bestätigt, `st == 2` einmalig für einen Spieler mit kleinerer
  Blessur (Gnabry). Andere Codes (1, 4, 8, 16, 32, 64, 128, 256) stammen aus
  einer älteren Community-Quelle und sind für v4 unverifiziert. Aktuell gilt:
  **jeder Status ≠ 0 führt zum Ausschluss** aus allen drei Rankings
  (`Player.is_unavailable` in `kickbase_tool/data/models.py`) — wie
  vorgegeben ("Lass die verhinderten Spieler raus"). Bei abweichenden Codes
  reicht eine Anpassung von `STATUS_LABELS`/`STATUS_NONE` in dieser Datei.
- **"letzte 5 Spiele"-Fenster**: Die Performance-Historie enthält für die
  laufende Saison auch noch nicht gespielte zukünftige Spieltage
  (vorbefüllt, Status `mdst != 2`). Diese werden beim Einlesen komplett
  herausgefiltert (`extract_current_season_performance` in `normalize.py`),
  sonst würde die Fallback-Logik versehentlich zukünftige Spiele statt
  vergangener zählen.
- **Team-Punkte pro Spieltag** (Kennzahl 8, 9, 11): Kein direkter Endpunkt
  dafür gefunden. Wie abgestimmt aus der Summe der tatsächlichen
  Kickbase-Punkte aller Spieler eines Teams an einem Spieltag abgeleitet
  (`build_team_points_by_matchday` in `kickbase_tool/metrics/calculations.py`).
- **Tabellenplatz-Differenz** (Kennzahl 10): Auf ausdrücklichen Nutzerwunsch
  NICHT `Tabellenplatz(Gegner) − Tabellenplatz(eigenes Team)` aus der
  offiziellen Tabelle, sondern `Form-Rang(Gegner) − Form-Rang(eigenes Team)`
  aus einer selbst gebauten "Form-Tabelle" (alle 18 Teams nach ihrem eigenen
  Kennzahl-8-Wert gerankt, `build_form_table_ranks` in `calculations.py`).
  Positiv = eigenes Team in der Form-Tabelle besser platziert (Favoritenrolle).
  Höherer Wert zählt als "besser" für den Spieler.
- **Heim/Auswärts** (Kennzahl 11): Auf ausdrücklichen Nutzerwunsch in 3 Spalten
  aufgeteilt (`own_venue_rank`/`opponent_venue_rank`/`venue_rank_diff`,
  `build_team_venue_ranks` in `calculations.py`) statt einer kombinierten
  Differenz, jetzt auf Basis echter offizieller Bundesliga-Ergebnisse (siehe
  "Heim/Auswärts-Datenquelle" oben), mit Kickbase-interner Fantasy-Punkte-
  Schätzung als Fallback.
- **Gegner-Restprogramm und Gegner-Formsteigerung** (Kennzahl 15/16, neu auf
  ausdrücklichen Nutzerwunsch): dieselbe Berechnung wie fürs eigene Team,
  aber für den nächsten Gegner. Ein schweres Restprogramm bzw. eine schwache/
  abfallende Form des Gegners gilt jeweils als gut für unseren Spieler
  (`opponent_remaining_schedule_difficulty`/`opponent_momentum` in
  `PlayerMetrics`).
- **Kennzahl 12** bündelt 3 Rohwerte in einer Rang-Kategorie: jeder Rohwert
  wird einzeln über den Spielerpool gerankt, die drei Ränge werden 90:35:20
  (Tore:Vorlagen:Zu-Null) gewichtet kombiniert — Gewichte aus dem Nutzer-Sheet
  übernommen (`_combined_goals_assists_cleansheets_rank` in `ranking/scoring.py`).
- **Marktwert-Richtung** (Kennzahl 6): Auf ausdrücklichen Nutzerwunsch gilt
  jetzt höher = besser (Marktwert als Qualitätssignal), und die Kategorie
  zählt nur noch bei Aufstellung — Kauf/Verkauf nutzen stattdessen Punkte pro
  Marktwert (Kennzahl 7). Ursprünglich (bis 2026-09-09) galt für Kauf/Verkauf
  günstiger = besser (Budget-Effizienz) bei gleichzeitigem Ausschluss aus
  Aufstellung — beides in
  `kickbase_tool/ranking/scoring.py:CATEGORY_DEFINITIONS["market_value"]`
  bzw. `AUFSTELLUNG_CATEGORIES`/`KAUF_CATEGORIES` weiterhin leicht umkehrbar.
- **Gewichte pro Kategorie**: aus dem Nutzer-Sheet übernommen, siehe Abschnitt
  "Herkunft der Gewichte" oben.
- **Sehr früh in der Saison** (z.B. Spieltag 2) haben viele Spieler noch kaum
  Daten (kein Saison-Ø, keine Form-Historie) — das ist keine Fehlfunktion,
  sondern echte Datensparsamkeit am Saisonanfang. Diese Spieler landen wegen
  fehlender Werte automatisch auf den hintersten Rängen der jeweiligen
  Kategorie (siehe `rank_with_ties` in `kickbase_tool/util.py`).

### Feldnamen weiter kalibrieren

Falls sich Endpunkt-Verhalten künftig ändert oder Felder unerwartet leer
aussehen: `python -m kickbase_tool.dump_raw` liefert frisches Roh-JSON nach
`raw_samples/` — dort nachsehen und in `kickbase_tool/data/normalize.py` als
zusätzlichen Alias im jeweiligen `pick(...)`-Aufruf ergänzen.

## Endpunkte

Live bestätigt, siehe `kickbase_tool/api/endpoints.py`:

| Zweck | Pfad |
|---|---|
| Login | `POST /v4/user/login` |
| Team-Kader (18× aufrufen, ein Team pro Aufruf) | `GET /v4/competitions/{competitionId}/teams/{teamId}/teamprofile` |
| Spieler-Detail (Marktwert, Ø, Status, Tore/Vorlagen/zu-Null) | `GET /v4/competitions/{competitionId}/players/{playerId}` |
| Spieler-Performance-Historie (Spieltag für Spieltag) | `GET /v4/competitions/{competitionId}/players/{playerId}/performance` |
| Liga-Tabelle (Bundesliga) | `GET /v4/competitions/{competitionId}/table` |
| Spielplan/Spieltage | `GET /v4/competitions/{competitionId}/matchdays` |
| Eigener Kader (optional, ungenutzt) | `GET /v4/leagues/{leagueId}/squad` |
| Transfermarkt (optional, ungenutzt) | `GET /v4/leagues/{leagueId}/market` |
| Liga-Rangliste, Fantasy (optional, ungenutzt) | `GET /v4/leagues/{leagueId}/ranking` |

`/v4/competitions/{competitionId}/players` (ohne Team-/Spieler-Id) ist absichtlich
**nicht** die Hauptquelle — sie liefert nur einen kleinen, spieltagsbezogenen
Ausschnitt statt des vollen Pools (siehe oben).

## Tests

Die reine Rechenlogik (Fallback-Logik, Ranking/Scoring) ist ohne Netzwerk und
ohne echte API-Daten testbar und wird per `pytest` abgedeckt:

```bash
pytest
```

Der komplette Ablauf inkl. echtem API-Zugriff wurde am 2026-09-05 gegen die
echte Kickbase-API verifiziert (kompletter Spielerpool, alle 15 Kennzahlen,
alle 3 Rankings) — kein rein synthetischer Test mehr.
