# SPDX-License-Identifier: AGPL-3.0-or-later
"""Walk-forward à partir de jeux de paramètres et de résultats **fournis** :
l'auditeur ne rejoue jamais la stratégie, il constate.

Entrée : pour chaque jeu de paramètres (« candidat »), l'historique complet des
trades qu'il a produits sur la même période. Protocole :

- la période commune [T0, T1] est découpée en ``n_folds + 1`` segments égaux ;
  le segment 0 ne sert qu'à l'apprentissage ; pour k = 1..n_folds, le segment k
  est la fenêtre hors échantillon (OOS) du pli k ;
- fenêtre d'apprentissage (IS) du pli k : ``anchored`` → [T0, début du segment
  k) ; ``rolling`` → le seul segment k − 1 ;
- dans chaque pli, le candidat retenu est celui qui maximise le critère de
  sélection sur la fenêtre IS (``net_profit`` ou ``sharpe``) ; son résultat OOS
  est celui constaté sur le segment k ;
- efficacité walk-forward (Pardo) : rendement OOS par jour des candidats
  retenus ÷ rendement IS par jour de ces mêmes candidats, sommés sur les plis :
  ``WFE = (Σ OOS net / Σ jours OOS) / (Σ IS net / Σ jours IS)`` ;
  indéfinie (NaN) si le numérateur IS est ≤ 0 ou si un pli est vide.

Hypothèses : les candidats couvrent la même période (l'union des étendues
sert de référence) ; un candidat sans trade dans une fenêtre y vaut 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np

from qaudit.core.metrics import sharpe_ratio
from qaudit.core.models import NS_PER_DAY, TradeSet

PROTOCOL_ANCHORED: Final = "anchored"
PROTOCOL_ROLLING: Final = "rolling"
SELECT_NET_PROFIT: Final = "net_profit"
SELECT_SHARPE: Final = "sharpe"


@dataclass(frozen=True, slots=True)
class Candidate:
    params: str
    trades: TradeSet


@dataclass(frozen=True, slots=True)
class WalkForwardInput:
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True, slots=True)
class Fold:
    index: int
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    selected: str
    is_net: float
    is_days: float
    oos_net: float
    oos_days: float
    oos_trades: int


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    protocol: str
    selection: str
    n_folds: int
    n_candidates: int
    folds: tuple[Fold, ...]
    efficiency: float
    oos_positive_share: float
    oos_net_total: float
    evaluable: bool


def _window_net(ts: TradeSet, start_ns: int, end_ns: int) -> tuple[float, float, int]:
    """(profit net, Sharpe par trade, nombre de trades) des trades clos dans [start, end)."""
    close = ts.close_time.astype(np.int64)
    mask = (close >= start_ns) & (close < end_ns)
    profit = ts.profit[mask]
    if profit.size == 0:
        return 0.0, math.nan, 0
    return float(np.sum(profit)), sharpe_ratio(profit), int(profit.size)


def _score(net: float, sharpe: float, selection: str) -> float:
    if selection == SELECT_SHARPE:
        return sharpe if not math.isnan(sharpe) else -math.inf
    return net


def _iso(ns: int) -> str:
    return str(np.datetime_as_string(np.datetime64(int(ns), "ns"), unit="s"))


def _span(inputs: WalkForwardInput) -> tuple[int, int]:
    starts = [int(c.trades.open_time.min().astype(np.int64)) for c in inputs.candidates
              if c.trades.n]
    ends = [int(c.trades.close_time.max().astype(np.int64)) for c in inputs.candidates
            if c.trades.n]
    if not starts:
        return 0, 0
    return min(starts), max(ends) + 1  # borne haute exclusive, dernier trade inclus


def run(
    inputs: WalkForwardInput,
    *,
    n_folds: int,
    protocol: str = PROTOCOL_ANCHORED,
    selection: str = SELECT_NET_PROFIT,
) -> WalkForwardReport:
    """Walk-forward ancré ou glissant sur des résultats fournis."""
    t0, t1 = _span(inputs)
    if not inputs.candidates or n_folds < 1 or t1 <= t0:
        return WalkForwardReport(protocol, selection, n_folds, len(inputs.candidates), (),
                                 math.nan, math.nan, 0.0, False)
    # bornes en arithmétique entière : les nanosecondes dépassent la précision du float64
    edges = [t0 + (k * (t1 - t0)) // (n_folds + 1) for k in range(n_folds + 2)]
    folds: list[Fold] = []
    is_net_sum = is_days_sum = oos_net_sum = oos_days_sum = 0.0
    for k in range(1, n_folds + 1):
        is_start = edges[0] if protocol == PROTOCOL_ANCHORED else edges[k - 1]
        is_end, oos_end = edges[k], edges[k + 1]
        scored = []
        for cand in inputs.candidates:
            net, sharpe, _ = _window_net(cand.trades, is_start, is_end)
            scored.append((_score(net, sharpe, selection), net, cand))
        _, best_net, best = max(scored, key=lambda item: item[0])
        oos_net, _, oos_n = _window_net(best.trades, is_end, oos_end)
        is_days = (is_end - is_start) / NS_PER_DAY
        oos_days = (oos_end - is_end) / NS_PER_DAY
        folds.append(Fold(k, _iso(is_start), _iso(is_end), _iso(is_end), _iso(oos_end),
                          best.params, best_net, is_days, oos_net, oos_days, oos_n))
        is_net_sum += best_net
        is_days_sum += is_days
        oos_net_sum += oos_net
        oos_days_sum += oos_days
    is_rate = is_net_sum / is_days_sum if is_days_sum > 0 else math.nan
    oos_rate = oos_net_sum / oos_days_sum if oos_days_sum > 0 else math.nan
    efficiency = oos_rate / is_rate if is_rate > 0 else math.nan
    positive = float(np.mean([f.oos_net > 0 for f in folds]))
    return WalkForwardReport(protocol, selection, n_folds, len(inputs.candidates),
                             tuple(folds), efficiency, positive, oos_net_sum, True)
