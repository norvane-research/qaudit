# SPDX-License-Identifier: AGPL-3.0-or-later
"""Détection de look-ahead : entrées (ou sorties) au plus bas ou au plus haut
**exact** de leur barre, trop souvent pour être dues au hasard.

Un achat ouvert au plus bas de la barre ou une vente ouverte au plus haut est
« parfait ». Sous une exécution honnête, un cours uniformément réparti dans la
fourchette de la barre tombe sur un extrême avec une probabilité voisine de
``tick / fourchette``. On compare le nombre observé d'entrées parfaites à
cette attente par un test binomial unilatéral (``scipy.stats.binomtest``).

Paramètres (TOML ``[detectors.lookahead]``) : ``tick_bps`` (taille d'un tick
en points de base du cours, tolérance de l'« exactitude »), ``min_share``,
``p_major``, ``p_blocking``, ``min_aligned_share``, ``min_trades``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import binomtest

from qaudit.core.config import DetectorParams, param
from qaudit.core.detectors.base import (
    missing_fields,
    skipped_missing_fields,
    skipped_too_few,
    source_of,
)
from qaudit.core.detectors.prices import align, unaligned_finding
from qaudit.core.models import Finding, PriceSeries, Severity, TradeSet

NAME = "lookahead"
NEEDS_PRICES = True


@dataclass(frozen=True, slots=True)
class LookaheadDetector:
    name: str
    needs_prices: bool
    tick_bps: float
    min_share: float
    p_major: float
    p_blocking: float
    min_aligned_share: float
    min_trades: int

    def detect(self, ts: TradeSet, prices: PriceSeries | None = None) -> Finding | None:
        missing = missing_fields(ts, "open_price", "direction")
        if missing or prices is None:
            return skipped_missing_fields(self.name, missing or ("prices",))
        alignment = align(ts, prices)
        if alignment.share < self.min_aligned_share:
            return unaligned_finding(self.name, alignment.share, self.min_aligned_share)
        rows = np.nonzero(alignment.aligned & (ts.direction != 0))[0]
        if rows.size < self.min_trades:
            return skipped_too_few(self.name, int(rows.size), self.min_trades)
        idx = alignment.open_idx[rows]
        low, high = prices.low[idx], prices.high[idx]
        tick = ts.open_price[rows] * self.tick_bps / 10_000.0
        entry = ts.open_price[rows]
        perfect = np.where(ts.direction[rows] > 0, entry <= low + tick, entry >= high - tick)
        ranges = np.maximum(high - low, tick)
        expected = float(np.mean(np.minimum(1.0, tick / ranges)))
        k, n = int(np.sum(perfect)), int(rows.size)
        share = k / n
        p_value = float(binomtest(k, n, expected, alternative="greater").pvalue)
        if share < self.min_share:
            return None
        if p_value < self.p_blocking:
            severity = Severity.BLOCKING
        elif p_value < self.p_major:
            severity = Severity.MAJOR
        else:
            return None
        return Finding.make(
            self.name,
            severity,
            "detector.lookahead",
            source_of(self.name),
            share=share,
            expected=expected,
            p_value=p_value,
            count=k,
        )


def make(params: DetectorParams) -> LookaheadDetector:
    return LookaheadDetector(
        name=NAME,
        needs_prices=NEEDS_PRICES,
        tick_bps=param(params, "tick_bps", NAME),
        min_share=param(params, "min_share", NAME),
        p_major=param(params, "p_major", NAME),
        p_blocking=param(params, "p_blocking", NAME),
        min_aligned_share=param(params, "min_aligned_share", NAME),
        min_trades=int(param(params, "min_trades", NAME)),
    )
