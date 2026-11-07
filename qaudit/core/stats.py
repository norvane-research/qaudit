# SPDX-License-Identifier: AGPL-3.0-or-later
"""Statistiques de significativité : PSR, DSR, courbe de sensibilité au nombre
d'essais, correction de Benjamini-Hochberg.

Formules (Bailey & López de Prado) :

    PSR(SR*) = Φ[ (SR − SR*)·√(T−1) / √(1 − γ₃·SR + ((γ₄−1)/4)·SR²) ]
    SR₀      = √V·[ (1−γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) ]
    DSR      = PSR(SR₀)

où SR est le Sharpe par trade (non annualisé), γ₃ l'asymétrie, γ₄ le kurtosis de
Pearson, T le nombre d'observations, N le nombre d'essais, γ la constante
d'Euler-Mascheroni et V la variance des Sharpe entre variantes testées.

Hypothèses retenues :
- N ≤ 1 : aucun biais de sélection, SR₀ = 0 et DSR = PSR(0) ;
- V inconnue : approximation de Lo, V = (1 + SR²/2)/T, signalée comme prudente
  (``variance_source = "lo_approx"``) — le vrai DSR est alors probablement
  inférieur ;
- le point de bascule est le plus grand N entier tel que DSR(N) ≥ seuil, obtenu
  par bissection sur les entiers entre deux points de la grille (le DSR est
  monotone décroissant en N) ; 0 si même N = 1 échoue ; ``None`` si la grille
  entière passe (au-delà de sa borne).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.special import ndtri

from qaudit.core.models import BoolArray, FloatArray

EULER_GAMMA = 0.5772156649015329
DEFAULT_TRIAL_GRID: tuple[int, ...] = (1, 10, 50, 100, 300, 1000)
VARIANCE_GIVEN = "given"
VARIANCE_LO_APPROX = "lo_approx"


def normal_cdf(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def psr(sr: float, skew: float, kurt: float, n: int, sr_star: float = 0.0) -> float:
    """Sharpe probabiliste : P(SR vrai > SR*) sous asymétrie et queues épaisses.

    NaN si la statistique est indéfinie (moins de deux observations, moments
    non finis, dénominateur non réel).
    """
    if n < 2 or not all(math.isfinite(v) for v in (sr, skew, kurt, sr_star)):
        return math.nan
    inner = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if inner <= 0.0:
        return math.nan
    z = (sr - sr_star) * math.sqrt(n - 1.0) / math.sqrt(inner)
    return normal_cdf(z)


def lo_variance(sr: float, n: int) -> float:
    """Variance asymptotique du Sharpe estimé (Lo, 2002) : (1 + SR²/2)/T."""
    if n < 2 or not math.isfinite(sr):
        return math.nan
    return (1.0 + sr * sr / 2.0) / n


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """Sharpe maximal attendu sous l'hypothèse nulle après ``n_trials`` essais."""
    if n_trials <= 1:
        return 0.0
    if not math.isfinite(var_sr) or var_sr < 0:
        return math.nan
    z1 = float(ndtri(1.0 - 1.0 / n_trials))
    z2 = float(ndtri(1.0 - 1.0 / (n_trials * math.e)))
    return math.sqrt(var_sr) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


@dataclass(frozen=True, slots=True)
class DSRResult:
    dsr: float
    sr0: float
    n_trials: int
    var_sr: float
    variance_source: str  # "given" | "lo_approx"


def dsr(
    sr: float,
    skew: float,
    kurt: float,
    n: int,
    n_trials: int,
    var_sr: float | None = None,
) -> DSRResult:
    """Sharpe dégonflé : PSR évalué contre SR₀(N)."""
    if var_sr is None:
        variance = lo_variance(sr, n)
        source = VARIANCE_LO_APPROX
    else:
        variance = var_sr
        source = VARIANCE_GIVEN
    sr0 = expected_max_sharpe(n_trials, variance)
    return DSRResult(psr(sr, skew, kurt, n, sr0), sr0, n_trials, variance, source)


@dataclass(frozen=True, slots=True)
class SensitivityPoint:
    n_trials: int
    dsr: float


@dataclass(frozen=True, slots=True)
class Sensitivity:
    """Courbe DSR = f(N) et point de bascule (D-06)."""

    points: tuple[SensitivityPoint, ...]
    threshold: float
    tipping_n_trials: int | None
    beyond_grid: bool

    def dsr_at(self, n_trials: int) -> float:
        for point in self.points:
            if point.n_trials == n_trials:
                return point.dsr
        return math.nan


def _dsr_value(
    sr: float, skew: float, kurt: float, n: int, n_trials: int, var: float | None
) -> float:
    return dsr(sr, skew, kurt, n, n_trials, var).dsr


def _bisect_tipping(
    sr: float,
    skew: float,
    kurt: float,
    n: int,
    var: float | None,
    lo: int,
    hi: int,
    threshold: float,
) -> int:
    """Plus grand N dans [lo, hi] tel que DSR(N) ≥ seuil ; DSR(lo) ≥ seuil > DSR(hi)."""
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _dsr_value(sr, skew, kurt, n, mid, var) >= threshold:
            lo = mid
        else:
            hi = mid
    return lo


def dsr_sensitivity(
    sr: float,
    skew: float,
    kurt: float,
    n: int,
    threshold: float,
    *,
    grid: tuple[int, ...] = DEFAULT_TRIAL_GRID,
    var_sr: float | None = None,
) -> Sensitivity:
    """DSR pour chaque N de la grille et N de bascule : « ce système cesse d'être
    significatif au-delà de N variantes testées »."""
    points = tuple(
        SensitivityPoint(k, _dsr_value(sr, skew, kurt, n, k, var_sr)) for k in grid
    )
    passing = [pt.n_trials for pt in points if pt.dsr >= threshold]
    failing = [pt.n_trials for pt in points if not pt.dsr >= threshold]
    if not passing:
        return Sensitivity(points, threshold, 0, False)
    if not failing:
        return Sensitivity(points, threshold, None, True)
    lo = max(passing)
    hi = min(k for k in failing if k > lo)
    tipping = _bisect_tipping(sr, skew, kurt, n, var_sr, lo, hi, threshold)
    return Sensitivity(points, threshold, tipping, False)


# ---------------------------------------------------------------------------
# Benjamini-Hochberg
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BHResult:
    adjusted: FloatArray
    reject: BoolArray
    alpha: float
    n_tests: int


def benjamini_hochberg(pvalues: FloatArray, alpha: float) -> BHResult:
    """p-values ajustées (step-up) ; les NaN sont exclus du dénominateur et
    jamais rejetés."""
    p = np.asarray(pvalues, dtype=np.float64)
    adjusted = np.full(p.shape, np.nan)
    reject = np.zeros(p.shape, dtype=bool)
    valid = np.nonzero(np.isfinite(p))[0]
    m = int(valid.size)
    if m == 0:
        return BHResult(adjusted, reject, alpha, 0)
    order = valid[np.argsort(p[valid], kind="stable")]
    ranks = np.arange(1, m + 1, dtype=np.float64)
    raw = p[order] * m / ranks
    adj = np.minimum(1.0, np.minimum.accumulate(raw[::-1])[::-1])
    adjusted[order] = adj
    reject[order] = adj <= alpha
    return BHResult(adjusted, reject, alpha, m)
