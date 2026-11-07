# SPDX-License-Identifier: AGPL-3.0-or-later
"""Régimes : segmentation de l'historique et performance par régime.

Trois classificateurs, tous injectables via le protocole ``RegimeClassifier`` :
- ``VolatilityTerciles`` (sans cours) : proxy de volatilité = écart-type glissant
  des P&L des ``window`` trades précédents, coupé en terciles ;
- ``AtrTerciles`` (avec cours) : ATR(``period``) de la barre précédant
  l'ouverture de chaque trade, coupé en terciles ;
- tout objet externe respectant le protocole.

Le rapport dit toujours quel classificateur a servi (``RegimeReport.method``).

La performance par période civile (trimestres) est calculée ici aussi, à
partir de clés entières (``metrics.period_keys``) — jamais de ``strftime``
(D-01) : le libellé « 2021-T1 » / « 2021-Q1 » est produit par la coquille via
une clé i18n.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from qaudit.core.metrics import period_keys, profit_factor, quarter_labels
from qaudit.core.models import FloatArray, IntArray, PriceSeries, TimeArray, TradeSet

LABELS_TERCILES: tuple[str, ...] = ("low", "mid", "high")
UNKNOWN = -1


class RegimeClassifier(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def labels(self) -> tuple[str, ...]: ...

    def classify(self, ts: TradeSet, prices: PriceSeries | None) -> IntArray: ...


def terciles(values: FloatArray) -> IntArray:
    """0 / 1 / 2 selon le tercile de chaque valeur ; −1 pour NaN."""
    out = np.full(values.size, UNKNOWN, dtype=np.int64)
    valid = np.isfinite(values)
    if valid.sum() < 3:
        return out
    q1, q2 = np.percentile(values[valid], [100 / 3, 200 / 3])
    v = values[valid]
    out[valid] = np.where(v <= q1, 0, np.where(v <= q2, 1, 2))
    return out


def rolling_std(x: FloatArray, window: int) -> FloatArray:
    """Écart-type des ``window`` valeurs précédant chaque position (exclue) ;
    NaN tant que moins de deux valeurs précèdent. Boucle explicite : n ≤ 10⁴."""
    n = x.size
    out = np.full(n, np.nan)
    for i in range(2, n):
        start = max(0, i - window)
        out[i] = float(np.std(x[start:i]))
    return out


@dataclass(frozen=True, slots=True)
class VolatilityTerciles:
    window: int
    name: str = "volatility_terciles"
    labels: tuple[str, ...] = LABELS_TERCILES

    def classify(self, ts: TradeSet, prices: PriceSeries | None = None) -> IntArray:
        return terciles(rolling_std(np.abs(ts.profit), self.window))


def atr(prices: PriceSeries, period: int) -> FloatArray:
    """ATR simple (moyenne glissante du true range) par barre ; NaN au début."""
    n = prices.n
    out = np.full(n, np.nan)
    if n < 2:
        return out
    prev_close = np.concatenate(([prices.close[0]], prices.close[:-1]))
    tr = np.maximum(
        prices.high - prices.low,
        np.maximum(np.abs(prices.high - prev_close), np.abs(prices.low - prev_close)),
    )
    if n <= period:
        return out
    cumsum = np.concatenate(([0.0], np.cumsum(tr)))
    out[period:] = (cumsum[period + 1 :] - cumsum[1:-period]) / period
    return out


def bar_index(prices: PriceSeries, times: TimeArray) -> IntArray:
    """Index de la barre contenant chaque horodatage (barre = [time, time + pas)).

    Tolérance d'une barre aux deux bouts : un horodatage jusqu'à une barre avant
    la première barre est rattaché à celle-ci, jusqu'à une barre après la fin de
    la dernière à celle-là ; au-delà, −1 (non alignable).
    """
    if prices.n == 0:
        return np.full(times.size, UNKNOWN, dtype=np.int64)
    t = times.astype("datetime64[ns]").astype(np.int64)
    bars = prices.time.astype(np.int64)
    step = round(prices.bar_seconds * 1e9) if prices.n > 1 else 0
    idx = np.searchsorted(bars, t, side="right") - 1
    idx = np.where((idx < 0) & (t >= bars[0] - step), 0, idx)
    too_late = t >= bars[-1] + 2 * step
    idx = np.where((idx < 0) | too_late, UNKNOWN, idx)
    return idx.astype(np.int64)


@dataclass(frozen=True, slots=True)
class AtrTerciles:
    period: int
    name: str = "atr_terciles"
    labels: tuple[str, ...] = LABELS_TERCILES

    def classify(self, ts: TradeSet, prices: PriceSeries | None = None) -> IntArray:
        if prices is None or prices.n < self.period + 2:
            return np.full(ts.n, UNKNOWN, dtype=np.int64)
        values = atr(prices, self.period)
        idx = bar_index(prices, ts.open_time)
        prev = np.where(idx > 0, idx - 1, UNKNOWN)  # barre précédant l'ouverture
        per_trade = np.where(prev >= 0, values[np.maximum(prev, 0)], np.nan)
        return terciles(per_trade)


@dataclass(frozen=True, slots=True)
class RegimeStats:
    label: str
    n: int
    net_profit: float
    profit_factor: float
    win_rate: float
    expectancy: float
    share_of_net: float


@dataclass(frozen=True, slots=True)
class RegimeReport:
    method: str
    stats: tuple[RegimeStats, ...]
    n_unclassified: int


def _stats_for(label: str, profit: FloatArray, total_net: float) -> RegimeStats:
    n = int(profit.size)
    if n == 0:
        return RegimeStats(label, 0, 0.0, math.nan, math.nan, math.nan, 0.0)
    gains = float(np.sum(profit[profit > 0]))
    losses = float(np.sum(profit[profit < 0]))
    net = float(np.sum(profit))
    share = net / total_net if total_net != 0 else math.nan
    return RegimeStats(
        label, n, net, profit_factor(gains, losses), float(np.mean(profit > 0)),
        float(np.mean(profit)), share,
    )


def analyse(
    ts: TradeSet, classifier: RegimeClassifier, prices: PriceSeries | None = None
) -> RegimeReport:
    """Performance par régime selon le classificateur fourni."""
    labels = classifier.classify(ts, prices)
    total_net = float(np.sum(ts.profit)) if ts.n else 0.0
    stats = tuple(
        _stats_for(name, ts.profit[labels == k], total_net)
        for k, name in enumerate(classifier.labels)
    )
    return RegimeReport(classifier.name, stats, int(np.sum(labels == UNKNOWN)))


@dataclass(frozen=True, slots=True)
class PeriodStats:
    year: int
    quarter: int
    n: int
    net_profit: float
    profit_factor: float


def quarterly_stats(ts: TradeSet) -> tuple[PeriodStats, ...]:
    """Performance par trimestre civil (clés entières, sans ``strftime`` — D-01)."""
    if ts.n == 0:
        return ()
    keys = period_keys(ts.close_time, "Q")
    years, quarters = quarter_labels(ts.close_time)
    out = []
    for key in np.unique(keys):
        mask = keys == key
        profit = ts.profit[mask]
        gains = float(np.sum(profit[profit > 0]))
        losses = float(np.sum(profit[profit < 0]))
        out.append(
            PeriodStats(
                int(years[mask][0]), int(quarters[mask][0]), int(mask.sum()),
                float(np.sum(profit)), profit_factor(gains, losses),
            )
        )
    return tuple(out)
