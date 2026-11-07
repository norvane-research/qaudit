# SPDX-License-Identifier: AGPL-3.0-or-later
"""Réalisme d'exécution : cours d'ouverture ou de clôture hors de la fourchette
[plus bas ; plus haut] de la barre qui contient l'horodatage, au-delà d'une
tolérance en points de base (écart bid/ask, décalage de flux).

Paramètres (TOML ``[detectors.execution_realism]``) : ``tolerance_bps``,
``minor_share``, ``major_share``, ``blocking_share``, ``min_aligned_share``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qaudit.core.config import DetectorParams, param
from qaudit.core.detectors.base import missing_fields, skipped_missing_fields, source_of
from qaudit.core.detectors.prices import align, unaligned_finding
from qaudit.core.models import Finding, FloatArray, IntArray, PriceSeries, Severity, TradeSet

NAME = "execution_realism"
NEEDS_PRICES = True


def _outside(price: FloatArray, idx: IntArray, prices: PriceSeries, tol: float) -> np.ndarray:
    safe = np.maximum(idx, 0)
    low = prices.low[safe] * (1.0 - tol)
    high = prices.high[safe] * (1.0 + tol)
    return np.isfinite(price) & ((price < low) | (price > high))


@dataclass(frozen=True, slots=True)
class ExecutionRealismDetector:
    name: str
    needs_prices: bool
    tolerance_bps: float
    minor_share: float
    major_share: float
    blocking_share: float
    min_aligned_share: float

    def detect(self, ts: TradeSet, prices: PriceSeries | None = None) -> Finding | None:
        missing = missing_fields(ts, "open_price", "close_price")
        if missing or prices is None:
            return skipped_missing_fields(self.name, missing or ("prices",))
        alignment = align(ts, prices)
        if alignment.share < self.min_aligned_share:
            return unaligned_finding(self.name, alignment.share, self.min_aligned_share)
        tol = self.tolerance_bps / 10_000.0
        bad_open = _outside(ts.open_price, alignment.open_idx, prices, tol)
        bad_close = _outside(ts.close_price, alignment.close_idx, prices, tol)
        implausible = alignment.aligned & (bad_open | bad_close)
        share = float(np.sum(implausible)) / max(1, int(alignment.aligned.sum()))
        if share >= self.blocking_share:
            severity = Severity.BLOCKING
        elif share >= self.major_share:
            severity = Severity.MAJOR
        elif share >= self.minor_share:
            severity = Severity.MINOR
        else:
            return None
        return Finding.make(
            self.name,
            severity,
            "detector.execution_realism",
            source_of(self.name),
            share=share,
            count=int(np.sum(implausible)),
            tolerance_bps=self.tolerance_bps,
        )


def make(params: DetectorParams) -> ExecutionRealismDetector:
    return ExecutionRealismDetector(
        name=NAME,
        needs_prices=NEEDS_PRICES,
        tolerance_bps=param(params, "tolerance_bps", NAME),
        minor_share=param(params, "minor_share", NAME),
        major_share=param(params, "major_share", NAME),
        blocking_share=param(params, "blocking_share", NAME),
        min_aligned_share=param(params, "min_aligned_share", NAME),
    )
