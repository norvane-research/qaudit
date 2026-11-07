# SPDX-License-Identifier: AGPL-3.0-or-later
"""Asymétrie extrême réussite / ratio : beaucoup de petits gains, de rares
pertes énormes — signature des ventes d'options implicites, des martingales et
des systèmes sans stop.

Paramètres (TOML ``[detectors.payoff_asymmetry]``) : ``win_rate_major``,
``payoff_major``, ``win_rate_blocking``, ``payoff_blocking``, ``min_trades``.
Le ratio de gain est ``gain moyen / |perte moyenne|`` (0,2 = pertes 5× plus
grosses que les gains).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qaudit.core.config import DetectorParams, param
from qaudit.core.detectors.base import skipped_too_few, source_of
from qaudit.core.models import Finding, PriceSeries, Severity, TradeSet

NAME = "payoff_asymmetry"
NEEDS_PRICES = False


@dataclass(frozen=True, slots=True)
class PayoffAsymmetryDetector:
    name: str
    needs_prices: bool
    win_rate_major: float
    payoff_major: float
    win_rate_blocking: float
    payoff_blocking: float
    min_trades: int

    def detect(self, ts: TradeSet, prices: PriceSeries | None = None) -> Finding | None:
        if ts.n < self.min_trades:
            return skipped_too_few(self.name, ts.n, self.min_trades)
        wins = ts.profit[ts.profit > 0]
        losses = ts.profit[ts.profit < 0]
        if wins.size == 0 or losses.size == 0:
            return None
        win_rate = wins.size / ts.n
        payoff = float(np.mean(wins)) / abs(float(np.mean(losses)))
        if win_rate >= self.win_rate_blocking and payoff <= self.payoff_blocking:
            severity = Severity.BLOCKING
        elif win_rate >= self.win_rate_major and payoff <= self.payoff_major:
            severity = Severity.MAJOR
        else:
            return None
        return Finding.make(
            self.name,
            severity,
            "detector.payoff_asymmetry",
            source_of(self.name),
            win_rate=win_rate,
            payoff=payoff,
        )


def make(params: DetectorParams) -> PayoffAsymmetryDetector:
    return PayoffAsymmetryDetector(
        name=NAME,
        needs_prices=NEEDS_PRICES,
        win_rate_major=param(params, "win_rate_major", NAME),
        payoff_major=param(params, "payoff_major", NAME),
        win_rate_blocking=param(params, "win_rate_blocking", NAME),
        payoff_blocking=param(params, "payoff_blocking", NAME),
        min_trades=int(param(params, "min_trades", NAME)),
    )
