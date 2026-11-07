# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outils communs aux détecteurs à données de cours : alignement des trades sur
les barres et extrêmes de cours parcourus pendant une position.

Alignement : un horodatage appartient à la barre ``[time, time + pas)`` ; à
plus d'une barre hors de la série il n'est pas alignable. Si moins de
``min_aligned_share`` des trades s'alignent, les détecteurs à cours se
désactivent avec un constat « info » (série de cours non alignée).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qaudit.core.models import (
    BoolArray,
    Finding,
    FloatArray,
    IntArray,
    PriceSeries,
    Severity,
    TradeSet,
)
from qaudit.core.regimes import UNKNOWN, bar_index


@dataclass(frozen=True, slots=True)
class Alignment:
    open_idx: IntArray
    close_idx: IntArray
    aligned: BoolArray

    @property
    def share(self) -> float:
        return float(np.mean(self.aligned)) if self.aligned.size else 0.0


def align(ts: TradeSet, prices: PriceSeries) -> Alignment:
    open_idx = bar_index(prices, ts.open_time)
    close_idx = bar_index(prices, ts.close_time)
    aligned = (open_idx != UNKNOWN) & (close_idx != UNKNOWN)
    return Alignment(open_idx, close_idx, aligned)


def path_extremes(
    prices: PriceSeries, open_idx: IntArray, close_idx: IntArray, aligned: BoolArray
) -> tuple[FloatArray, FloatArray]:
    """Plus bas et plus haut atteints entre la barre d'ouverture et la barre de
    clôture (incluses) de chaque trade ; NaN si non aligné."""
    n = open_idx.size
    lows = np.full(n, np.nan)
    highs = np.full(n, np.nan)
    for i in np.nonzero(aligned)[0].tolist():
        a, b = int(open_idx[i]), int(close_idx[i])
        if b < a:
            a, b = b, a
        lows[i] = float(np.min(prices.low[a : b + 1]))
        highs[i] = float(np.max(prices.high[a : b + 1]))
    return lows, highs


def unaligned_finding(name: str, share: float, required: float) -> Finding:
    return Finding.make(
        f"{name}_skipped",
        Severity.INFO,
        "detector.prices_unaligned",
        f"detector.{name}",
        detector=name,
        share=share,
        required=required,
    )
