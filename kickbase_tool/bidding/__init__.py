"""Dynamisches Gebotsmodell: berechnet pro Spieler eine Kaufempfehlung
("wie viel sollte ich maximal bieten"), gelernt aus den echten abgeschlossenen
Transfers der eigenen Kickbase-Liga statt aus einem festen Prozentsatz auf den
Marktwert.

Module (bewusst getrennt, siehe jeweiliges Docstring):
  config.py         zentrale Gewichte/Schwellenwerte (bidding_config.yaml)
  snapshot_store.py taeglicher Spieler-Snapshot (Basis fuer MW-Trend + Bias-freie
                     Transfer-Anreicherung)
  transfers.py      liest /leagues/{id}/activitiesFeed, reichert neue Transfers
                     mit dem Snapshot von JETZT an, persistiert dauerhaft
  calibration.py    robuste Liga-Marktstatistik aus dem Transfer-Log
  similarity.py     findet je Spieler die aehnlichsten historischen Transfers
  scoring.py        regelbasierter Attraktivitaets-Score + Gebotskategorie
  pricing.py        kombiniert alles zur finalen Empfehlung + Confidence
  pipeline.py       Orchestrierung, einziger Einstiegspunkt fuer export_artifact.py

Jede Stufe ist bewusst robust gegen fehlende/duenne Daten (Cold Start): ohne
genuegend echte Liga-Transfers greift ein regelbasiertes Grundmodell, das sich
mit wachsendem Transfer-Log automatisch zunehmend an die echte Liga anpasst.
"""
