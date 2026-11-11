"""Gemeinsame Basis für spätere (noch nicht implementierte) Module."""
from __future__ import annotations

from .base import RunContext


def stub(name: str, phase: int, ctx: RunContext) -> int:
    print(f"Modul '{name}' ist für Phase {phase} vorgesehen und noch nicht implementiert.")
    return 2
