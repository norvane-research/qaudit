# SPDX-License-Identifier: AGPL-3.0-or-later
"""Linéarité anormale de la courbe d'equity.

Un R² de la courbe cumulée contre l'indice du trade proche de 1 sur un
historique long est plus typique d'une martingale qui lisse ses pertes, d'un
résultat fabriqué ou d'une courbe sur-ajustée que d'un système réel.

Paramètres (TOML ``[detectors.equity_linearity]``) : ``r2_major``,
``min_trades``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qaudit.core.config import DetectorParams, param
from qaudit.core.detectors.base import skipped_too_few, source_of
from qaudit.core.models import Finding, FloatArray, PriceSeries, Severity, TradeSet

NAME = "equity_linearity"
NEEDS_PRICES = False


def r_squared(cum: FloatArray) -> float:
    """R² de la régression linéaire de ``cum`` sur l'indice 0..n−1 ; NaN si plat."""
    n = cum.size
    if n < 3:
        return float("nan")
    x = np.arange(n, dtype=np.float64)
    xc = x - x.mean()
    yc = cum - cum.mean()
    ss_y = float(np.dot(yc, yc))
    if ss_y == 0.0:
        return float("nan")
    slope = float(np.dot(xc, yc)) / float(np.dot(xc, xc))
    ss_res = float(np.sum((yc - slope * xc) ** 2))
    return 1.0 - ss_res / ss_y


@dataclass(frozen=True, slots=True)
class EquityLinearityDetector:
    name: str
    needs_prices: bool
    r2_major: float
    min_trades: int

    def detect(self, ts: TradeSet, prices: PriceSeries | None = None) -> Finding | None:
        if ts.n < self.min_trades:
            return skipped_too_few(self.name, ts.n, self.min_trades)
        r2 = r_squared(ts.cum_profit)
        if not r2 >= self.r2_major or float(ts.cum_profit[-1]) <= 0:
            return None
        return Finding.make(
            self.name, Severity.MAJOR, "detector.equity_linearity", source_of(self.name), r2=r2
        )


def make(params: DetectorParams) -> EquityLinearityDetector:
    return EquityLinearityDetector(
        name=NAME,
        needs_prices=NEEDS_PRICES,
        r2_major=param(params, "r2_major", NAME),
        min_trades=int(param(params, "min_trades", NAME)),
    )
