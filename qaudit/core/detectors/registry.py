# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registre des détecteurs : ajouter un détecteur = un fichier + une ligne ici."""

from __future__ import annotations

from collections.abc import Callable

from qaudit.core.config import DetectorParams, MethodConfig
from qaudit.core.detectors import (
    equity_linearity,
    execution_realism,
    grid,
    holding_time,
    lookahead,
    martingale,
    no_stop,
    payoff_asymmetry,
    period_dependence,
    profit_concentration,
    stop_geometry,
)
from qaudit.core.detectors.base import Detector, skipped_no_prices
from qaudit.core.models import Finding, PriceSeries, TradeSet

Factory = Callable[[DetectorParams], Detector]

REGISTRY: tuple[tuple[str, bool, Factory], ...] = (
    (martingale.NAME, martingale.NEEDS_PRICES, martingale.make),
    (grid.NAME, grid.NEEDS_PRICES, grid.make),
    (no_stop.NAME, no_stop.NEEDS_PRICES, no_stop.make),
    (profit_concentration.NAME, profit_concentration.NEEDS_PRICES, profit_concentration.make),
    (equity_linearity.NAME, equity_linearity.NEEDS_PRICES, equity_linearity.make),
    (payoff_asymmetry.NAME, payoff_asymmetry.NEEDS_PRICES, payoff_asymmetry.make),
    (period_dependence.NAME, period_dependence.NEEDS_PRICES, period_dependence.make),
    (holding_time.NAME, holding_time.NEEDS_PRICES, holding_time.make),
    # détecteurs à données de cours
    (stop_geometry.NAME, stop_geometry.NEEDS_PRICES, stop_geometry.make),
    (lookahead.NAME, lookahead.NEEDS_PRICES, lookahead.make),
    (execution_realism.NAME, execution_realism.NEEDS_PRICES, execution_realism.make),
)


def detector_names() -> tuple[str, ...]:
    return tuple(name for name, _, _ in REGISTRY)


def build_detectors(config: MethodConfig) -> tuple[Detector, ...]:
    """Instancie chaque détecteur avec ses paramètres de configuration."""
    return tuple(factory(config.detector_params(name)) for name, _, factory in REGISTRY)


def run_detectors(
    detectors: tuple[Detector, ...], ts: TradeSet, prices: PriceSeries | None = None
) -> tuple[Finding, ...]:
    """Exécute les détecteurs dans l'ordre du registre ; ceux qui exigent des
    cours absents rendent un constat « info »."""
    findings: list[Finding] = []
    for detector in detectors:
        if detector.needs_prices and prices is None:
            findings.append(skipped_no_prices(detector.name))
            continue
        finding = detector.detect(ts, prices)
        if finding is not None:
            findings.append(finding)
    return tuple(findings)
