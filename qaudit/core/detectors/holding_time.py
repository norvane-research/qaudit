# SPDX-License-Identifier: AGPL-3.0-or-later
"""Durée de position irréaliste : trades quasi instantanés (arbitrage de
latence, tick-scalping non reproductible) ou anormalement longs.

Paramètres (TOML ``[detectors.holding_time]``) : ``min_seconds``,
``short_share_major``, ``short_share_blocking``, ``max_days``,
``long_share_minor``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qaudit.core.config import DetectorParams, param
from qaudit.core.detectors.base import source_of
from qaudit.core.metrics import holding_hours
from qaudit.core.models import Finding, PriceSeries, Severity, TradeSet

NAME = "holding_time"
NEEDS_PRICES = False


@dataclass(frozen=True, slots=True)
class HoldingTimeDetector:
    name: str
    needs_prices: bool
    min_seconds: float
    short_share_major: float
    short_share_blocking: float
    max_days: float
    long_share_minor: float

    def detect(self, ts: TradeSet, prices: PriceSeries | None = None) -> Finding | None:
        if ts.n == 0:
            return None
        hours = holding_hours(ts.open_time, ts.close_time)
        short_share = float(np.mean(hours * 3600.0 <= self.min_seconds))
        long_share = float(np.mean(hours / 24.0 > self.max_days))
        if short_share >= self.short_share_blocking:
            severity = Severity.BLOCKING
        elif short_share >= self.short_share_major:
            severity = Severity.MAJOR
        elif long_share >= self.long_share_minor:
            severity = Severity.MINOR
        else:
            return None
        return Finding.make(
            self.name,
            severity,
            "detector.holding_time",
            source_of(self.name),
            short_share=short_share,
            long_share=long_share,
            min_seconds=self.min_seconds,
            max_days=self.max_days,
        )


def make(params: DetectorParams) -> HoldingTimeDetector:
    return HoldingTimeDetector(
        name=NAME,
        needs_prices=NEEDS_PRICES,
        min_seconds=param(params, "min_seconds", NAME),
        short_share_major=param(params, "short_share_major", NAME),
        short_share_blocking=param(params, "short_share_blocking", NAME),
        max_days=param(params, "max_days", NAME),
        long_share_minor=param(params, "long_share_minor", NAME),
    )
