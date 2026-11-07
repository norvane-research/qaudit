# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sensibilité de la géométrie du stop : que devient le profit si le stop-loss
avait été placé 10 / 20 / 30 % plus près (ou plus loin) de l'entrée ?

Pour chaque trade gagnant doté d'un stop et aligné sur les barres, on vérifie
si le stop resserré aurait été touché par le chemin de cours parcouru entre la
barre d'ouverture et la barre de clôture (plus bas pour un achat, plus haut
pour une vente). L'« effondrement » à −x % est la part du gain brut apportée
par les gagnants qui auraient été stoppés. Un système dont la moitié du gain
brut tient à 10 % de largeur de stop a une géométrie fragile. Le desserrement
(+x %) est rapporté à titre d'information : il ne peut que réduire le nombre de
gagnants stoppés, on publie la part des perdants qui auraient survécu à un
stop plus large (perte évitée au moins jusqu'à la clôture réelle).

Paramètres (TOML ``[detectors.stop_geometry]``) : ``collapse_major`` (part du
gain brut perdue à −10 % déclenchant un constat majeur), ``min_trades``,
``min_aligned_share``. Les chiffres de sensibilité sont toujours publiés : sous
le seuil, le constat est de niveau « info ».
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
from qaudit.core.detectors.prices import align, path_extremes, unaligned_finding
from qaudit.core.models import BoolArray, Finding, FloatArray, PriceSeries, Severity, TradeSet

NAME = "stop_geometry"
NEEDS_PRICES = True
SHIFTS: tuple[float, ...] = (0.10, 0.20, 0.30)


def stopped_by(
    ts: TradeSet, lows: FloatArray, highs: FloatArray, factor: float, rows: BoolArray
) -> BoolArray:
    """Trades (parmi ``rows``) dont le chemin de cours touche un stop dont la
    distance à l'entrée est multipliée par ``factor``."""
    distance = np.abs(ts.open_price - ts.stop_loss) * factor
    shifted = ts.open_price - ts.direction * distance
    hit_buy = (ts.direction > 0) & (lows <= shifted)
    hit_sell = (ts.direction < 0) & (highs >= shifted)
    return rows & (hit_buy | hit_sell)


@dataclass(frozen=True, slots=True)
class StopGeometryDetector:
    name: str
    needs_prices: bool
    collapse_major: float
    min_trades: int
    min_aligned_share: float

    def detect(self, ts: TradeSet, prices: PriceSeries | None = None) -> Finding | None:
        missing = missing_fields(ts, "stop_loss", "open_price", "direction")
        if missing or prices is None:
            return skipped_missing_fields(self.name, missing or ("prices",))
        alignment = align(ts, prices)
        if alignment.share < self.min_aligned_share:
            return unaligned_finding(self.name, alignment.share, self.min_aligned_share)
        usable = alignment.aligned & np.isfinite(ts.stop_loss) & (ts.direction != 0)
        if int(usable.sum()) < self.min_trades:
            return skipped_too_few(self.name, int(usable.sum()), self.min_trades)
        lows, highs = path_extremes(prices, alignment.open_idx, alignment.close_idx, usable)
        winners = usable & (ts.profit > 0)
        losers = usable & (ts.profit < 0)
        gross = float(np.sum(ts.profit[winners]))
        collapse = {}
        survived = {}
        for shift in SHIFTS:
            stopped = stopped_by(ts, lows, highs, 1.0 - shift, winners)
            collapse[shift] = float(np.sum(ts.profit[stopped])) / gross if gross > 0 else 0.0
            still_hit = stopped_by(ts, lows, highs, 1.0 + shift, losers)
            n_losers = int(losers.sum())
            survived[shift] = 1.0 - int(still_hit.sum()) / n_losers if n_losers else 0.0
        fragile = collapse[0.10] >= self.collapse_major
        return Finding.make(
            self.name,
            Severity.MAJOR if fragile else Severity.INFO,
            "detector.stop_geometry" if fragile else "detector.stop_geometry_info",
            source_of(self.name),
            collapse_10=collapse[0.10],
            collapse_20=collapse[0.20],
            collapse_30=collapse[0.30],
            survived_10=survived[0.10],
            survived_20=survived[0.20],
            survived_30=survived[0.30],
            winners=int(winners.sum()),
        )


def make(params: DetectorParams) -> StopGeometryDetector:
    return StopGeometryDetector(
        name=NAME,
        needs_prices=NEEDS_PRICES,
        collapse_major=param(params, "collapse_major", NAME),
        min_trades=int(param(params, "min_trades", NAME)),
        min_aligned_share=param(params, "min_aligned_share", NAME),
    )
