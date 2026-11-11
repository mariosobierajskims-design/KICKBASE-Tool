"""Phase 2 – Verkäufer-Update (STUB). Fr: je Objekt Zahlen + Besichtigungsfeedback -> Entwurf je Eigentümer.

Eigentümer lt. Doku über Relation urn:onoffice-de-ns:smart:2.5:relationTypes:estate:address:owner
(resourcetype idsfromrelation, action get).
"""
from __future__ import annotations

from .base import RunContext
from .spaeter import stub

PHASE = 2
RELATION_OWNER = "urn:onoffice-de-ns:smart:2.5:relationTypes:estate:address:owner"


def run(ctx: RunContext) -> int:
    return stub("verkaeufer_update", PHASE, ctx)
