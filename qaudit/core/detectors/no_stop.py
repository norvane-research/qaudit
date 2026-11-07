# SPDX-License-Identifier: AGPL-3.0-or-later
"""Absence de stop : part des trades sans stop-loss renseigné.

Paramètres (TOML ``[detectors.no_stop]``) : ``minor_share``, ``major_share``.
Si la source ne fournit pas de colonne de stop, le détecteur se désactive avec
un constat « info » (on ne peut pas distinguer « pas de stop » de « colonne
absente »).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qaudit.core.config import DetectorParams, param
from qaudit.core.detectors.base import missing_fields, skipped_missing_fields, source_of
from qaudit.core.models import Finding, PriceSeries, Severity, TradeSet

NAME = "no_stop"
NEEDS_PRICES = False


@dataclass(frozen=True, slots=True)
class NoStopDetector:
    name: str
    needs_prices: bool
    minor_share: float
    major_share: float

    def detect(self, ts: TradeSet, prices: PriceSeries | None = None) -> Finding | None:
        missing = missing_fields(ts, "stop_loss")
        if missing:
            return skipped_missing_fields(self.name, missing)
        if ts.n == 0:
            return None
        share = float(np.mean(np.isnan(ts.stop_loss)))
        if share >= self.major_share:
            severity = Severity.MAJOR
        elif share >= self.minor_share:
            severity = Severity.MINOR
        else:
            return None
        return Finding.make(
            self.name, severity, "detector.no_stop", source_of(self.name), share=share
        )


def make(params: DetectorParams) -> NoStopDetector:
    return NoStopDetector(
        name=NAME,
        needs_prices=NEEDS_PRICES,
        minor_share=param(params, "minor_share", NAME),
        major_share=param(params, "major_share", NAME),
    )
