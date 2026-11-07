# SPDX-License-Identifier: AGPL-3.0-or-later
"""Martingale : progression du volume après une perte (vectorisé).

Signature recherchée : sur une même série d'instruments, le volume du trade
suivant une perte est multiplié par un facteur ≥ ``ratio_min`` bien plus
souvent qu'après un gain.

Paramètres (TOML ``[detectors.martingale]``) :
- ``ratio_min`` : facteur de volume à partir duquel on parle de progression ;
- ``min_events`` : nombre minimal de trades suivant une perte pour conclure ;
- ``major_share`` / ``blocking_share`` : part des trades post-perte en
  progression déclenchant un constat majeur / bloquant ;
- ``contrast_min`` : écart minimal entre la part post-perte et la part post-gain
  (une progression symétrique n'est pas une martingale, c'est un sizing).

Hypothèse : les séquences sont formées par symbole, dans l'ordre canonique de
clôture ; un volume inconnu (NaN) est ignoré.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qaudit.core.config import DetectorParams, param
from qaudit.core.detectors.base import (
    missing_fields,
    skipped_missing_fields,
    skipped_too_few,
    source_of,
)
from qaudit.core.models import Finding, PriceSeries, Severity, TradeSet

NAME = "martingale"
NEEDS_PRICES = False


@dataclass(frozen=True, slots=True)
class MartingaleDetector:
    name: str
    needs_prices: bool
    ratio_min: float
    min_events: int
    major_share: float
    blocking_share: float
    contrast_min: float

    def detect(self, ts: TradeSet, prices: PriceSeries | None = None) -> Finding | None:
        missing = missing_fields(ts, "volume")
        if missing:
            return skipped_missing_fields(self.name, missing)
        if ts.n < 2:
            return skipped_too_few(self.name, 0, self.min_events)
        order = np.lexsort((np.arange(ts.n), ts.symbol))
        symbol = ts.symbol[order]
        volume = ts.volume[order]
        profit = ts.profit[order]
        same_symbol = symbol[1:] == symbol[:-1]
        finite = np.isfinite(volume[1:]) & np.isfinite(volume[:-1])
        usable = same_symbol & finite & (volume[:-1] > 0)
        ratio = np.divide(volume[1:], volume[:-1], out=np.ones(ts.n - 1), where=volume[:-1] > 0)
        scaled_up = ratio >= self.ratio_min
        after_loss = usable & (profit[:-1] < 0)
        after_win = usable & (profit[:-1] > 0)
        n_loss = int(after_loss.sum())
        if n_loss < self.min_events:
            return skipped_too_few(self.name, n_loss, self.min_events)
        share_loss = float(np.mean(scaled_up[after_loss]))
        share_win = float(np.mean(scaled_up[after_win])) if after_win.any() else 0.0
        contrast = share_loss - share_win
        if share_loss >= self.blocking_share and contrast >= self.contrast_min:
            severity = Severity.BLOCKING
        elif share_loss >= self.major_share and contrast >= self.contrast_min:
            severity = Severity.MAJOR
        else:
            return None
        return Finding.make(
            self.name,
            severity,
            "detector.martingale",
            source_of(self.name),
            share_after_loss=share_loss,
            share_after_win=share_win,
            ratio_min=self.ratio_min,
            events=n_loss,
        )


def make(params: DetectorParams) -> MartingaleDetector:
    return MartingaleDetector(
        name=NAME,
        needs_prices=NEEDS_PRICES,
        ratio_min=param(params, "ratio_min", NAME),
        min_events=int(param(params, "min_events", NAME)),
        major_share=param(params, "major_share", NAME),
        blocking_share=param(params, "blocking_share", NAME),
        contrast_min=param(params, "contrast_min", NAME),
    )
