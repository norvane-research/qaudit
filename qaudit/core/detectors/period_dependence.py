# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dépendance à une période : le profit net vient d'un seul trimestre, le reste
de l'historique perd de l'argent (ou presque).

Découpage par trimestre civil via ``metrics.period_keys`` (clés entières, sans
``strftime`` — voir D-01). Paramètres (TOML ``[detectors.period_dependence]``) :
``min_periods`` (nombre minimal de trimestres couverts), ``share_major`` (part
du net apportée par le meilleur trimestre à partir de laquelle on signale ; on
signale aussi, quelle que soit la part, si le reste de l'historique est ≤ 0).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qaudit.core.config import DetectorParams, param
from qaudit.core.detectors.base import skipped_too_few, source_of
from qaudit.core.metrics import period_keys
from qaudit.core.models import Finding, PriceSeries, Severity, TradeSet

NAME = "period_dependence"
NEEDS_PRICES = False


@dataclass(frozen=True, slots=True)
class PeriodDependenceDetector:
    name: str
    needs_prices: bool
    min_periods: int
    share_major: float

    def detect(self, ts: TradeSet, prices: PriceSeries | None = None) -> Finding | None:
        if ts.n == 0:
            return None
        keys = period_keys(ts.close_time, "Q")
        unique, inverse = np.unique(keys, return_inverse=True)
        if unique.size < self.min_periods:
            return skipped_too_few(self.name, int(unique.size), self.min_periods)
        per_period = np.bincount(inverse, weights=ts.profit, minlength=unique.size)
        net = float(np.sum(ts.profit))
        if net <= 0:
            return None
        best = int(np.argmax(per_period))
        best_net = float(per_period[best])
        share = best_net / net
        rest = net - best_net
        if share < self.share_major and rest > 0:
            return None
        key = int(unique[best])
        return Finding.make(
            self.name,
            Severity.MAJOR,
            "detector.period_dependence",
            source_of(self.name),
            share=share,
            year=key // 10,
            quarter=key % 10,
            rest=rest,
            periods=int(unique.size),
        )


def make(params: DetectorParams) -> PeriodDependenceDetector:
    return PeriodDependenceDetector(
        name=NAME,
        needs_prices=NEEDS_PRICES,
        min_periods=int(param(params, "min_periods", NAME)),
        share_major=param(params, "share_major", NAME),
    )
