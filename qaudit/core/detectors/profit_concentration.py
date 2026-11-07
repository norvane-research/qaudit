# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concentration du profit : une poignée de trades porte tout le résultat.

Deux mesures : la part du gain brut apportée par les ``top_fraction`` meilleurs
trades (au moins un), et le profit net une fois retirés les ``remove_fraction``
meilleurs trades (au moins un) — s'il devient ≤ 0, le système est fragile.

Paramètres (TOML ``[detectors.profit_concentration]``) : ``top_fraction``,
``share_major``, ``remove_fraction``, ``min_trades``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from qaudit.core.config import DetectorParams, param
from qaudit.core.detectors.base import skipped_too_few, source_of
from qaudit.core.models import Finding, PriceSeries, Severity, TradeSet

NAME = "profit_concentration"
NEEDS_PRICES = False


@dataclass(frozen=True, slots=True)
class ProfitConcentrationDetector:
    name: str
    needs_prices: bool
    top_fraction: float
    share_major: float
    remove_fraction: float
    min_trades: int

    def detect(self, ts: TradeSet, prices: PriceSeries | None = None) -> Finding | None:
        if ts.n < self.min_trades:
            return skipped_too_few(self.name, ts.n, self.min_trades)
        p = np.sort(ts.profit)[::-1]
        gross = float(np.sum(p[p > 0]))
        net = float(np.sum(p))
        if gross <= 0 or net <= 0:
            return None  # système non profitable : les barrières s'en chargent
        k_top = max(1, math.ceil(self.top_fraction * ts.n))
        top_share = float(np.sum(p[:k_top])) / gross
        k_remove = max(1, math.ceil(self.remove_fraction * ts.n))
        net_without_best = net - float(np.sum(p[:k_remove]))
        fragile = net_without_best <= 0
        if top_share < self.share_major and not fragile:
            return None
        return Finding.make(
            self.name,
            Severity.MAJOR,
            "detector.profit_concentration",
            source_of(self.name),
            top_share=top_share,
            top_count=k_top,
            net_without_best=net_without_best,
            removed=k_remove,
        )


def make(params: DetectorParams) -> ProfitConcentrationDetector:
    return ProfitConcentrationDetector(
        name=NAME,
        needs_prices=NEEDS_PRICES,
        top_fraction=param(params, "top_fraction", NAME),
        share_major=param(params, "share_major", NAME),
        remove_fraction=param(params, "remove_fraction", NAME),
        min_trades=int(param(params, "min_trades", NAME)),
    )
