# Kickbase-Tool

Automatisierte Spieleranalyse für Kickbase (inoffizielle API). Berechnet für
jeden verfügbaren Bundesliga-Spieler 15 Kennzahlen und daraus drei gewichtete
Rankings: **Aufstellung**, **Kauf**, **Verkauf**.

> Nutzt die unveröffentlichte Kickbase-API. Nicht offiziell unterstützt, kann
> jederzeit ohne Vorwarnung von Kickbase geändert werden. Nur für den
> persönlichen Gebrauch.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt      # oder requirements-dev.txt für Tests

cp .env.example .env
# .env mit echter E-Mail/Passwort/Liga-ID ausfüllen
```

Die `.env`-Datei wird von `.gitignore` ausgeschlossen und nie eingecheckt.
Zugangsdaten stehen an keiner Stelle im Code — sie werden ausschließlich zur
Laufzeit über `python-dotenv` aus `.env` gelesen (`kickbase_tool/config.py`).

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

## Die 15 Kennzahlen

1. Punkte-Ø Saison
2. Punkte-Ø letzte 5 Spiele (mit Fallback-Logik, siehe unten)
3. Minimum letzte 5 Spiele (gleiche Fallback-Logik)
4. Maximum letzte 5 Spiele (gleiche Fallback-Logik)
5. Ø aus Min/Max
6. Aktueller Marktwert
7. Punkte pro Marktwert (Effizienz)
8. Team-Form: Ø Team-Punkte der letzten 5 Spiele
9. Gegner-Form: gleiche Kennzahl für den nächsten Gegner
10. Tabellenplatz-Differenz zum nächsten Gegner
11. Heim/Auswärts-adjustierte Stärke-Differenz zum nächsten Gegner
12. Tore, Vorlagen, zu-Null-Spiele (eine kombinierte Rang-Kategorie, s.u.)
13. Startelf-Wahrscheinlichkeit (über dieselben Spiele wie 2-5)
14. Verletzt/Gesperrt-Flag (Filter, kein Rang-Kriterium)
15. Restprogramm-Schwierigkeit (Ø Tabellenplatz der nächsten 5 Gegner)

Kennzahl 14 ist laut Vorgabe ein **Ausschlussfilter**: betroffene Spieler
tauchen in keinem der drei Rankings auf (harte Filterung, kein Soft-Ranking).
Deshalb fließen in die gewichtete Rang-Mittelung 11 Kategorien (Aufstellung)
bzw. 14 Kategorien (Kauf/Verkauf) ein — die 15. Kennzahl (Status) ist der
vorgelagerte Filter.

**Verkauf** verwendet exakt dieselben Kategorien wie **Kauf**, aber mit
umgekehrter Rangfolge je Kategorie (Rang 1 in "Kauf" wird zu Rang N in
"Verkauf" und umgekehrt) — genau wie in der Aufgabenstellung beschrieben
("alle 15 Kategorien, aber die Logik ist umgekehrt").

## Fallback-Logik für "letzte 5 Spiele" (Kennzahl 2-4, 13)

Implementiert in [`kickbase_tool/metrics/fallback.py`](kickbase_tool/metrics/fallback.py),
mit Tests in [`tests/test_fallback.py`](tests/test_fallback.py):

| Gespielte Spiele der letzten 5 Spieltage | Verwendete Spiele |
|---|---|
| 5 von 5 | genau diese 5 |
| 4 von 5 | genau diese 4 |
| 3 von 5 | die letzten **4** tatsächlich bestrittenen Spiele (auch wenn dafür weiter zurückgegangen wird) |
| 0-2 von 5 | die letzten **5** tatsächlich bestrittenen Spiele (unabhängig davon wie weit das zurückliegt) |

## Annahmen (bitte gegen deine echten Daten prüfen)

Die öffentliche, inoffizielle Kickbase-v4-Doku
([kevinskyba/kickbase-api-doc](https://github.com/kevinskyba/kickbase-api-doc),
[simonsagstetter/kickbase-api-v4-docs](https://github.com/simonsagstetter/kickbase-api-v4-docs))
listet alle verwendeten Endpunkt-Pfade zuverlässig, liefert aber **fast keine
Beispiel-Response-Bodies** — insbesondere keine für POST/PUT/DELETE und kaum
welche für GET. Dieses Sandbox-Netzwerk konnte zudem `api.kickbase.com` nicht
erreichen (vom Egress-Proxy geblockt), es gab hier also keine Möglichkeit,
live gegen die echte API zu testen. Nach eurer Vorgabe ("Hauptsache du ziehst
dir die korrekten Daten, ich muss dir manuell nichts liefern") ist das Tool
deshalb so gebaut, dass es **selbst robust gegen unbekannte Feldnamen** ist,
statt dich um Beispieldaten zu bitten:

- **`kickbase_tool/util.py:pick()`** sucht für jeden Wert mehrere plausible
  Feldnamen-Varianten ab (z.B. `marketValue`, `mv`, `market_value`), statt
  einen einzigen hart zu erwarten.
- **Login** (`kickbase_tool/api/client.py`): sendet `{"em": ..., "pass": ...}`
  gemäß dokumentiertem Beispiel-Request; liest ein Token aus mehreren
  Kandidaten-Feldern, **und** verlässt sich zusätzlich auf das automatische
  Cookie-Handling von `requests.Session` (die API setzt laut Doku ein
  `kkstrauth`-Cookie) als Fallback, falls die App primär cookie-basiert
  authentifiziert.
- **Verletzt/Gesperrt-Status** (Kennzahl 14): Das Status-Enum stammt aus einer
  älteren (v3) Community-Reverse-Engineering-Quelle (0=fit, 1=verletzt,
  2=angeschlagen, 4=Reha, 8=Rote Karte, 16=Gelb-Rot, 32=5. Gelbe, 64=nicht im
  Kader, 128=nicht in Liga, 256=abwesend). Für v4 unverifiziert. Aktuell gilt:
  **jeder Status ≠ 0 (fit) führt zum Ausschluss** aus allen drei Rankings
  (`Player.is_unavailable` in `kickbase_tool/data/models.py`) — wie von dir
  vorgegeben ("Lass die verhinderten Spieler raus"). Falls die echten
  Statuscodes abweichen, reicht eine Anpassung von `STATUS_LABELS` /
  `STATUS_NONE` in dieser einen Datei.
- **Team-Punkte pro Spieltag** (Kennzahl 8, 9, 11): Es gibt keinen
  dokumentierten Endpoint dafür. Wie abgestimmt werden sie aus der Summe der
  tatsächlichen Kickbase-Punkte aller Spieler eines Teams an einem Spieltag
  abgeleitet (`build_team_points_by_matchday` in
  `kickbase_tool/metrics/calculations.py`).
- **Tabellenplatz-Differenz** (Kennzahl 10): `Tabellenplatz(Gegner) −
  Tabellenplatz(eigenes Team)`. Positiv = eigenes Team besser platziert
  (Favoritenrolle), negativ = Außenseiterrolle. Höherer (positiverer) Wert
  zählt als "besser" für den Spieler.
- **Restprogramm-Schwierigkeit** (Kennzahl 15): Ø Tabellenplatz der nächsten 5
  Gegner. Ein höherer Durchschnittswert (z.B. 15 statt 3) bedeutet
  durchschnittlich schwächere Gegner = leichteres Restprogramm = zählt als
  "besser".
- **Kennzahl 12** (Tore/Vorlagen/zu-Null) ist laut Aufgabenstellung eine
  einzelne von 15 Kennzahlen, obwohl sie 3 Rohwerte bündelt. Umsetzung: jeder
  der drei Rohwerte wird pro Spieler einzeln über den ganzen Spielerpool
  gerankt, die drei Ränge werden gemittelt — dieser Mittelwert ist der
  Eingabewert für die Kategorie in der finalen Rang-Mittelung
  (`_combined_goals_assists_cleansheets_rank` in `ranking/scoring.py`).
- **Marktwert-Richtung** (Kennzahl 6): Für "Kauf" gilt günstiger = besser
  (mehr Budget-Effizienz, ergänzend zu Kennzahl 7). Das ist eine
  Interpretationsentscheidung, keine Vorgabe aus der Aufgabenstellung — in
  `kickbase_tool/ranking/scoring.py:CATEGORY_DEFINITIONS["market_value"]`
  mit einem Flag leicht umkehrbar.
- **Gewichte pro Kategorie**: du wolltest sie selbst vorgeben; Standard ist
  überall 1.0 (Gleichgewichtung). Anpassung in `weights.yaml`, siehe oben.

### Feldnamen kalibrieren

Falls beim ersten echten Lauf Felder leer/falsch aussehen (z.B. `Score`
überall gleich, oder Spielerliste leer): `python -m kickbase_tool.dump_raw`
ausführen (mit echten `.env`-Zugangsdaten, außerhalb dieser Sandbox). Das
Skript speichert Roh-JSON der wichtigsten Endpunkte unter `raw_samples/` —
darin die exakten Feldnamen nachsehen und in
`kickbase_tool/data/normalize.py` als zusätzlichen Alias in den jeweiligen
`pick(...)`-Aufruf ergänzen (mehrere Kandidaten sind dort bereits die Norm).

## Endpunkte

Basierend auf der v4-Doku (`kickbase_tool/api/endpoints.py`):

| Zweck | Pfad |
|---|---|
| Login | `POST /v4/user/login` |
| Kompletter Spielerpool (Bundesliga) | `GET /v4/competitions/{competitionId}/players` |
| Spieler-Performance-Historie | `GET /v4/competitions/{competitionId}/players/{playerId}/performance` |
| Liga-Tabelle (Bundesliga) | `GET /v4/competitions/{competitionId}/table` |
| Spielplan/Spieltage | `GET /v4/competitions/{competitionId}/matchdays` |
| Eigener Kader | `GET /v4/leagues/{leagueId}/squad` |
| Transfermarkt | `GET /v4/leagues/{leagueId}/market` |
| Liga-Rangliste (Fantasy) | `GET /v4/leagues/{leagueId}/ranking` |

Die Analyse selbst läuft über den kompletten Bundesliga-Spielerpool
(`/competitions/.../players`), nicht nur über den eigenen Kader — passend zu
"jeder verfügbare Bundesliga-Spieler". Kader/Markt-Endpunkte sind
mit angebunden (`dump_raw.py`) und lassen sich in `repository.py` leicht in
die Analyse einbeziehen (z.B. um Spieler auf dem eigenen Transfermarkt zu
markieren).

## Tests

Die reine Rechenlogik (Fallback-Logik, Ranking/Scoring) ist ohne Netzwerk und
ohne echte API-Daten testbar und wird per `pytest` abgedeckt:

```bash
pytest
```

Der API-Client selbst kann in dieser Sandbox nicht gegen die echte Kickbase-API
getestet werden (Netzwerkzugriff auf `api.kickbase.com` ist hier blockiert) —
das muss beim ersten Lauf auf deinem eigenen Rechner passieren.
