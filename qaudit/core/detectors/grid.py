# SPDX-License-Identifier: AGPL-3.0-or-later
"""Grille : empilement de positions de même sens, sur le même symbole, ouvertes
à un cours *pire* que des positions encore ouvertes (moyenne à la baisse pour un
achat, à la hausse pour une vente), à volume au moins égal, **et clôturées en
panier** avec la position sur laquelle elles s'empilent.

Balayage par symbole et sens dans l'ordre d'ouverture, avec un tas des
positions actives trié par heure de clôture : O(n log n), jamais O(n²).

**Piège connu** (v0.1) : des positions *concurrentes* ne font pas une grille.
Sur un système sain à positions indépendantes, un tiers des trades peuvent
s'ouvrir alors qu'un autre est encore ouvert, et la moitié de ceux-là à un cours
pire : sans le critère de clôture en panier, 10 % des trades du témoin sain
passaient pour des ajouts de grille. Pyramider dans le sens du gain (cours
meilleur), tenir des positions indépendantes ou clôturer séparément ne
déclenche rien ici.

Paramètres (TOML ``[detectors.grid]``) :
- ``min_depth`` : nombre de positions actives à cours meilleur (et volume ≤) à
  partir duquel un trade est compté comme ajout de grille (1 = dès la première
  moyenne à la baisse) ;
- ``major_share`` / ``blocking_share`` : part des trades appartenant à une
  pile de grille déclenchant un constat majeur / bloquant ;
- ``min_trades`` : taille minimale de l'historique pour conclure ;
- ``basket_close_seconds`` : écart maximal entre la clôture d'un ajout et celle
  de la position sur laquelle il s'empile pour parler de clôture en panier.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

from qaudit.core.config import DetectorParams, param
from qaudit.core.detectors.base import (
    missing_fields,
    skipped_missing_fields,
    skipped_too_few,
    source_of,
)
from qaudit.core.models import Finding, IntArray, PriceSeries, Severity, TradeSet

NAME = "grid"
NEEDS_PRICES = False


def _count_worse(
    active: list[tuple[int, float, float]],
    direction: int,
    price: float,
    volume: float,
    close_ns: int,
    tolerance_ns: int,
) -> int:
    """Positions actives ouvertes à meilleur cours (donc ajout à une perte), de
    volume ≤ à celui du nouveau trade, et clôturées en panier avec lui."""
    count = 0
    for active_close, active_price, active_volume in active:
        if not np.isfinite(active_price):
            continue
        if np.isfinite(active_volume) and active_volume > volume:
            continue
        if abs(active_close - close_ns) > tolerance_ns:
            continue
        better = active_price > price if direction > 0 else active_price < price
        if better:
            count += 1
    return count


def _stack_depths(ts: TradeSet, tolerance_ns: int) -> tuple[IntArray, int]:
    """Pour chaque trade, nombre de positions actives de même symbole et sens
    ouvertes à un cours meilleur, de volume ≤, clôturées en panier avec lui ;
    et profondeur maximale."""
    depths = np.zeros(ts.n, dtype=np.int64)
    order = np.lexsort((ts.open_time.astype(np.int64), ts.direction, ts.symbol))
    open_ns = ts.open_time.astype(np.int64)
    close_ns = ts.close_time.astype(np.int64)
    volumes = ts.volume if ts.has("volume") else np.ones(ts.n)
    active: list[tuple[int, float, float]] = []  # (clôture, cours, volume)
    key: tuple[str, int] | None = None
    max_depth = 0
    for i in order.tolist():
        this_key = (str(ts.symbol[i]), int(ts.direction[i]))
        if this_key != key:
            key = this_key
            active = []
        while active and active[0][0] <= open_ns[i]:
            heapq.heappop(active)
        price = float(ts.open_price[i])
        volume = float(volumes[i])
        if np.isfinite(price):
            depths[i] = _count_worse(
                active, int(ts.direction[i]), price, volume, int(close_ns[i]), tolerance_ns
            )
            max_depth = max(max_depth, int(depths[i]))
        heapq.heappush(active, (int(close_ns[i]), price, volume))
    return depths, max_depth


@dataclass(frozen=True, slots=True)
class GridDetector:
    name: str
    needs_prices: bool
    min_depth: int
    major_share: float
    blocking_share: float
    min_trades: int
    basket_close_seconds: float

    def detect(self, ts: TradeSet, prices: PriceSeries | None = None) -> Finding | None:
        missing = missing_fields(ts, "direction", "open_price", "symbol")
        if missing:
            return skipped_missing_fields(self.name, missing)
        if ts.n < self.min_trades:
            return skipped_too_few(self.name, ts.n, self.min_trades)
        depths, max_depth = _stack_depths(ts, int(self.basket_close_seconds * 1e9))
        in_grid = depths >= self.min_depth
        share = float(np.mean(in_grid))
        if share >= self.blocking_share:
            severity = Severity.BLOCKING
        elif share >= self.major_share:
            severity = Severity.MAJOR
        else:
            return None
        return Finding.make(
            self.name,
            severity,
            "detector.grid",
            source_of(self.name),
            share=share,
            max_depth=max_depth,
            min_depth=self.min_depth,
        )


def make(params: DetectorParams) -> GridDetector:
    return GridDetector(
        name=NAME,
        needs_prices=NEEDS_PRICES,
        min_depth=int(param(params, "min_depth", NAME)),
        major_share=param(params, "major_share", NAME),
        blocking_share=param(params, "blocking_share", NAME),
        min_trades=int(param(params, "min_trades", NAME)),
        basket_close_seconds=param(params, "basket_close_seconds", NAME),
    )
