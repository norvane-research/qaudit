# SPDX-License-Identifier: AGPL-3.0-or-later
"""Métriques de base d'un historique de trades.

Hypothèses retenues :
- toutes les grandeurs de décision (Sharpe, PSR, DSR, profit factor, drawdown)
  sont calculées sur le **P&L par trade en devise du compte**, pas sur des
  rendements relatifs à l'equity. Le verdict est ainsi exactement invariant par
  changement d'échelle des profits (exigence des tests de propriétés) ; les
  rendements relatifs restent fournis à titre descriptif ;
- l'annualisation utilise la période réellement couverte par les données
  (``TradeSet.span_days``), jamais une constante (D-02) :
  ``trades_par_an = n / (jours_couverts / 365,25)`` ;
- l'écart-type et les moments (asymétrie, kurtosis) sont les moments empiriques
  biaisés (ddof=0) : cohérents entre eux, et exactement invariants quand chaque
  trade est dupliqué ; le kurtosis est celui de Pearson (loi normale → 3), comme
  dans la formule du PSR ;
- le drawdown en devise est mesuré sur le cumul des profits depuis 0 (creux sous
  le sommet précédent) ; le drawdown relatif exige un solde initial connu ;
- les rendements relatifs ne sont jamais calculés sur une base ≤ 0 (D-03) : la
  série s'arrête au premier trade dont la base n'est pas strictement positive.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from qaudit.core.models import DAYS_PER_YEAR, FloatArray, IntArray, TimeArray, TradeSet

NS_PER_HOUR = 3_600_000_000_000


@dataclass(frozen=True, slots=True)
class Metrics:
    """Toutes les grandeurs sont en devise du compte sauf mention ``_pct``."""

    n: int
    span_days: float
    trades_per_year: float
    net_profit: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    n_wins: int
    n_losses: int
    n_flat: int
    win_rate: float
    avg_win: float
    avg_loss: float
    payoff_ratio: float
    expectancy: float
    std_profit: float
    sharpe_trade: float
    sharpe_annual: float
    skew: float
    kurtosis: float
    max_drawdown: float
    max_drawdown_pct: float | None
    longest_losing_streak: int
    largest_win: float
    largest_loss: float
    avg_holding_hours: float
    total_return_pct: float | None
    cagr_pct: float | None


# ---------------------------------------------------------------------------
# briques
# ---------------------------------------------------------------------------


def trades_per_year(n: int, span_days: float) -> float:
    """Fréquence annuelle réelle (D-02). NaN si la période couverte est nulle."""
    if n == 0 or span_days <= 0:
        return math.nan
    return n / (span_days / DAYS_PER_YEAR)


def _degenerate(sd: float, mean: float) -> bool:
    """Série constante à l'arrondi près : l'écart-type est nul en pratique."""
    return sd <= 1e-9 * max(abs(mean), 1e-300)


def sharpe_ratio(x: FloatArray) -> float:
    """Sharpe par observation : moyenne / écart-type (moment biaisé, ddof=0,
    cohérent avec l'asymétrie et le kurtosis ; exactement invariant par
    duplication de l'échantillon). NaN si indéfini."""
    if x.size < 2:
        return math.nan
    mean = float(np.mean(x))
    sd = float(np.std(x))
    if _degenerate(sd, mean):
        return math.nan
    return mean / sd


def annualize_sharpe(sharpe_per_trade: float, trades_per_year_: float) -> float:
    """Sharpe annualisé = Sharpe par trade × √(trades par an), fréquence mesurée."""
    if math.isnan(sharpe_per_trade) or math.isnan(trades_per_year_):
        return math.nan
    return sharpe_per_trade * math.sqrt(trades_per_year_)


def _standardised(x: FloatArray) -> FloatArray | None:
    """(x − moyenne) / écart-type, ou ``None`` si la série est trop courte ou
    constante (moments d'ordre supérieur indéfinis)."""
    if x.size < 2:
        return None
    mean = float(np.mean(x))
    sd = float(np.std(x))
    if _degenerate(sd, mean):
        return None
    return (x - mean) / sd


def skewness(x: FloatArray) -> float:
    """Asymétrie empirique (moment biaisé), calculée sur la série standardisée
    pour éviter tout dépassement de capacité. NaN si indéfinie."""
    z = _standardised(x)
    return math.nan if z is None else float(np.mean(z**3))


def kurtosis(x: FloatArray) -> float:
    """Kurtosis de Pearson (loi normale → 3), moment biaisé. NaN si indéfini."""
    z = _standardised(x)
    return math.nan if z is None else float(np.mean(z**4))


def drawdown_curve(cum: FloatArray) -> FloatArray:
    """Creux sous le sommet précédent (≥ 0), le sommet initial étant 0."""
    if cum.size == 0:
        return np.zeros(0)
    peak = np.maximum.accumulate(np.maximum(cum, 0.0))
    return peak - cum


def max_drawdown(cum: FloatArray) -> float:
    if cum.size == 0:
        return 0.0
    return float(np.max(drawdown_curve(cum)))


def max_drawdown_rows(cum: FloatArray) -> FloatArray:
    """Drawdown maximal de chaque ligne d'une matrice de cumuls (vectorisé)."""
    if cum.size == 0:
        return np.zeros(cum.shape[0])
    peak = np.maximum.accumulate(np.maximum(cum, 0.0), axis=1)
    return np.max(peak - cum, axis=1)


def max_drawdown_pct(equity: FloatArray, initial_balance: float) -> float:
    """Plus forte baisse relative au sommet d'equity, en pourcentage."""
    if equity.size == 0:
        return 0.0
    full = np.concatenate(([initial_balance], equity))
    peak = np.maximum.accumulate(full)
    return float(np.max((peak - full) / peak)) * 100.0


def longest_losing_streak(profit: FloatArray) -> int:
    losing = profit < 0
    best = run = 0
    for flag in losing.tolist():
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def profit_factor(gross_profit: float, gross_loss: float) -> float:
    """Gains bruts / |pertes brutes| ; +inf sans perte, NaN sans activité."""
    if gross_loss < 0:
        return gross_profit / -gross_loss
    if gross_profit > 0:
        return math.inf
    return math.nan


def equity_returns(ts: TradeSet) -> FloatArray:
    """Rendements relatifs par trade, ``profit / equity précédente`` (D-03).

    La série s'arrête au premier trade dont la base est ≤ 0 : aucun ratio n'est
    jamais calculé sur une base négative. Vide si le solde initial est inconnu.
    """
    if ts.initial_balance is None or ts.n == 0:
        return np.zeros(0)
    base = ts.initial_balance + np.concatenate(([0.0], ts.cum_profit[:-1]))
    bad = np.nonzero(base <= 0)[0]
    stop = int(bad[0]) if bad.size else ts.n
    return ts.profit[:stop] / base[:stop]


def holding_hours(open_time: TimeArray, close_time: TimeArray) -> FloatArray:
    delta = close_time.astype(np.int64) - open_time.astype(np.int64)
    return delta.astype(np.float64) / NS_PER_HOUR


def quarter_labels(times: TimeArray) -> tuple[IntArray, IntArray]:
    """(année, trimestre 1-4) de chaque horodatage — sans ``strftime`` (D-01)."""
    years = times.astype("datetime64[Y]").astype(np.int64) + 1970
    months = times.astype("datetime64[M]").astype(np.int64) % 12  # 0-11
    quarters = months // 3 + 1
    return years.astype(np.int64), quarters.astype(np.int64)


def period_keys(times: TimeArray, freq: str) -> IntArray:
    """Clé entière de période : ``"Y"`` → année, ``"Q"`` → année×10+trimestre,
    ``"M"`` → année×100+mois. Sert au découpage par période sans texte."""
    years, quarters = quarter_labels(times)
    if freq == "Y":
        return years
    if freq == "Q":
        return years * 10 + quarters
    months = times.astype("datetime64[M]").astype(np.int64) % 12 + 1
    return years * 100 + months


# ---------------------------------------------------------------------------
# agrégat
# ---------------------------------------------------------------------------


def _relative_block(ts: TradeSet) -> tuple[float | None, float | None, float | None]:
    if ts.initial_balance is None or ts.n == 0:
        return None, None, None
    base = ts.initial_balance
    dd_pct = max_drawdown_pct(ts.equity, base)
    total = float(ts.cum_profit[-1]) / base * 100.0
    final = base + float(ts.cum_profit[-1])
    years = ts.span_years
    cagr: float | None
    if years <= 0 or final <= 0:
        cagr = None
    else:
        try:
            cagr = (math.exp(math.log(final / base) / years) - 1.0) * 100.0
        except OverflowError:
            cagr = None  # période trop courte pour qu'un taux annualisé ait un sens
    return dd_pct, total, cagr


def compute_metrics(ts: TradeSet) -> Metrics:
    """Métriques descriptives ; ne lève jamais sur un jeu vide, unitaire ou
    entièrement gagnant (NaN / inf là où la grandeur est indéfinie)."""
    p = ts.profit
    n = ts.n
    wins = p[p > 0]
    losses = p[p < 0]
    gross_profit = float(np.sum(wins)) if wins.size else 0.0
    gross_loss = float(np.sum(losses)) if losses.size else 0.0
    avg_win = float(np.mean(wins)) if wins.size else math.nan
    avg_loss = float(np.mean(losses)) if losses.size else math.nan
    tpy = trades_per_year(n, ts.span_days)
    sr = sharpe_ratio(p)
    dd_pct, total_pct, cagr = _relative_block(ts)
    hold = holding_hours(ts.open_time, ts.close_time)
    return Metrics(
        n=n,
        span_days=ts.span_days,
        trades_per_year=tpy,
        net_profit=float(np.sum(p)) if n else 0.0,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor(gross_profit, gross_loss),
        n_wins=int(wins.size),
        n_losses=int(losses.size),
        n_flat=int(n - wins.size - losses.size),
        win_rate=float(wins.size) / n if n else math.nan,
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff_ratio=avg_win / -avg_loss if losses.size and wins.size else math.nan,
        expectancy=float(np.mean(p)) if n else math.nan,
        std_profit=float(np.std(p)) if n > 1 else math.nan,
        sharpe_trade=sr,
        sharpe_annual=annualize_sharpe(sr, tpy),
        skew=skewness(p),
        kurtosis=kurtosis(p),
        max_drawdown=max_drawdown(ts.cum_profit),
        max_drawdown_pct=dd_pct,
        longest_losing_streak=longest_losing_streak(p),
        largest_win=float(np.max(p)) if n else math.nan,
        largest_loss=float(np.min(p)) if n else math.nan,
        avg_holding_hours=float(np.mean(hold)) if n else math.nan,
        total_return_pct=total_pct,
        cagr_pct=cagr,
    )
