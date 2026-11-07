# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contrat commun des détecteurs.

Un détecteur = un fichier exposant ``NAME``, ``NEEDS_PRICES`` et ``make(params)``
qui retourne un objet dont la méthode ``detect(ts, prices=None)`` rend un
``Finding`` ou ``None``. Ajouter un détecteur ne modifie que ``registry.py``.

Quand une donnée nécessaire manque (champ absent de la source, série de cours
non fournie), le détecteur se désactive proprement et rend un constat de niveau
« info » disant ce qui n'a pas pu être testé.
"""

from __future__ import annotations

from typing import Protocol

from qaudit.core.models import Finding, PriceSeries, Severity, TradeSet


class Detector(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def needs_prices(self) -> bool: ...

    def detect(self, ts: TradeSet, prices: PriceSeries | None = None) -> Finding | None: ...


def source_of(name: str) -> str:
    return f"detector.{name}"


def skipped_missing_fields(name: str, fields: tuple[str, ...]) -> Finding:
    """Constat « info » : le détecteur n'a pas pu tourner faute de ces champs."""
    return Finding.make(
        f"{name}_skipped",
        Severity.INFO,
        "detector.skipped_missing_fields",
        source_of(name),
        detector=name,
        fields=", ".join(fields),
    )


def skipped_no_prices(name: str) -> Finding:
    return Finding.make(
        f"{name}_skipped",
        Severity.INFO,
        "detector.skipped_no_prices",
        source_of(name),
        detector=name,
    )


def skipped_too_few(name: str, n: int, required: int) -> Finding:
    return Finding.make(
        f"{name}_skipped",
        Severity.INFO,
        "detector.skipped_too_few",
        source_of(name),
        detector=name,
        n=n,
        required=required,
    )


def missing_fields(ts: TradeSet, *fields: str) -> tuple[str, ...]:
    return tuple(f for f in fields if not ts.has(f))
