# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rééchantillonnage : trois simulations, trois questions distinctes.

1. **Bootstrap** — « avec ce même edge, jusqu'où la malchance peut-elle aller ? »
   Bootstrap par blocs stationnaire de Politis–Romano (1994), longueur moyenne de
   bloc choisie automatiquement par la règle de Politis–White (2004) avec la
   correction de Patton–Politis–White (2009) ; l'IID reste une option explicite
   (D-04 : l'IID détruit la dépendance sérielle et sous-estime le drawdown dès
   que les pertes se groupent).
2. **Permutation d'ordre** — « la performance vient-elle de l'edge ou de
   l'ordre ? » L'ensemble des trades est identique, seul l'ordre change : le
   profit total est invariant, seul le drawdown bouge. Le tableau d'entrée n'est
   jamais muté.
3. **Nulle sans edge** — « combien de systèmes sans aucun edge, mais avec le même
   structure de risque, font aussi bien ? » Taux de réussite d'équilibre
   p₀ = |perte moyenne| / (gain moyen + |perte moyenne|), gains et pertes tirés
   dans leurs distributions empiriques.

   **D-09 — hypothèse documentée** : cette nulle conserve les distributions
   empiriques des gains et des pertes (tailles, asymétrie, queues) et n'en
   neutralise que la fréquence. Ce n'est donc **pas** une nulle de marché
   efficient : elle répond « le taux de réussite observé est-il explicable par
   la chance, à distribution des gains/pertes donnée ? », pas « ce système bat-il un
   marché sans mémoire ? ». Le rapport le dit (``resample.null_empirical``).

Hypothèses retenues :
- l'aléatoire passe exclusivement par le ``numpy.random.Generator`` reçu ;
- les tirages sont produits par blocs de ``CHUNK`` itérations, constante fixe :
  la suite de nombres consommée ne dépend que de la graine et de la version ;
- le centile du drawdown observé parmi les permutations est le rang-centile
  classique : pourcentage de permutations dont le drawdown maximal est ≤ au
  drawdown observé. Un centile bas signifie que l'ordre réel a produit une
  courbe d'equity plus lisse que presque toutes les réorganisations, donc que
  la performance apparente dépend de l'ordre ;
- la p-value Monte Carlo est ``(k + 1) / (n_iter + 1)`` avec k le nombre de
  systèmes nuls faisant au moins aussi bien : jamais exactement 0 ;
- les centiles sont pris sans interpolation (``method="nearest"``) pour rester
  définis quand la distribution contient des +inf (profit factor sans perte).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal

import numpy as np

from qaudit.core.metrics import max_drawdown, max_drawdown_rows
from qaudit.core.models import FloatArray, IndexArray

CHUNK = 1000
METHOD_STATIONARY: Final = "stationary"
METHOD_IID: Final = "iid"
BootstrapMethod = Literal["stationary", "iid"]

_PCT_METHOD: Final = "nearest"


# ---------------------------------------------------------------------------
# longueur de bloc automatique (Politis–White 2004, correction PPW 2009)
# ---------------------------------------------------------------------------


def _autocovariances(x: FloatArray, max_lag: int) -> FloatArray:
    n = x.size
    centred = x - np.mean(x)
    out = np.zeros(max_lag + 1)
    for k in range(max_lag + 1):
        out[k] = float(np.dot(centred[: n - k], centred[k:])) / n
    return out


def _flat_top(t: float) -> float:
    a = abs(t)
    if a <= 0.5:
        return 1.0
    if a <= 1.0:
        return 2.0 * (1.0 - a)
    return 0.0


def _bandwidth(rho: FloatArray, n: int) -> int:
    """Plus petit m dont les K_n autocorrélations suivantes sont toutes
    insignifiantes ; à défaut, le dernier retard significatif."""
    kn = max(5, math.ceil(math.sqrt(math.log10(n))))
    threshold = 2.0 * math.sqrt(math.log10(n) / n)
    significant = np.abs(rho[1:]) > threshold  # index i ↔ retard i+1
    max_lag = significant.size
    for m in range(max_lag - kn + 1):
        if not significant[m : m + kn].any():
            return m
    hits = np.nonzero(significant)[0]
    return int(hits[-1]) + 1 if hits.size else 0


def stationary_block_length(x: FloatArray) -> float:
    """Longueur moyenne de bloc optimale pour le bootstrap stationnaire.

    Retourne 1,0 (équivalent IID) pour une série courte, constante ou sans
    dépendance détectable ; plafonnée à min(3√n, n/3).
    """
    n = x.size
    if n < 10 or float(np.std(x)) == 0.0:
        return 1.0
    max_lag = min(n - 1, math.ceil(math.sqrt(n)) + max(5, math.ceil(math.sqrt(math.log10(n)))))
    acov = _autocovariances(x, max_lag)
    if acov[0] <= 0:
        return 1.0
    rho = acov / acov[0]
    m_hat = _bandwidth(rho, n)
    m = min(2 * m_hat, max_lag)
    if m == 0:
        return 1.0
    weights = np.array([_flat_top(k / m) for k in range(m + 1)])
    lags = np.arange(m + 1)
    g_hat = 2.0 * float(np.sum(weights[1:] * lags[1:] * acov[1 : m + 1]))
    g0 = acov[0] + 2.0 * float(np.sum(weights[1:] * acov[1 : m + 1]))
    d_sb = 2.0 * g0 * g0
    if d_sb <= 0 or g_hat == 0.0:
        return 1.0
    b_sb = (2.0 * g_hat * g_hat / d_sb) ** (1.0 / 3.0) * n ** (1.0 / 3.0)
    b_max = min(3.0 * math.sqrt(n), n / 3.0)
    return float(max(1.0, min(b_sb, b_max)))


# ---------------------------------------------------------------------------
# indices de rééchantillonnage
# ---------------------------------------------------------------------------


def iid_bootstrap_indices(n: int, n_iter: int, rng: np.random.Generator) -> IndexArray:
    return rng.integers(0, n, size=(n_iter, n)).astype(np.intp)


def stationary_bootstrap_indices(
    n: int, n_iter: int, mean_block: float, rng: np.random.Generator
) -> IndexArray:
    """Indices du bootstrap stationnaire (blocs géométriques, circulaire),
    entièrement vectorisés : ``mean_block ≤ 1`` dégénère en IID."""
    starts = rng.integers(0, n, size=(n_iter, n))
    if mean_block <= 1.0 or n < 2:
        return starts.astype(np.intp)
    p = 1.0 / mean_block
    restart = rng.random((n_iter, n)) < p
    restart[:, 0] = True
    pos = np.arange(n)
    last = np.maximum.accumulate(np.where(restart, pos, 0), axis=1)
    idx = (np.take_along_axis(starts, last, axis=1) + (pos - last)) % n
    return idx.astype(np.intp)


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    method: str
    n_iter: int
    block_length: float
    profit_factor_p05: float
    profit_factor_p50: float
    profit_factor_p95: float
    net_profit_p05: float
    net_profit_p50: float
    net_profit_p95: float
    max_drawdown_p50: float
    max_drawdown_p95: float
    max_drawdown_p99: float


def _row_profit_factors(samples: FloatArray) -> FloatArray:
    """Profit factor de chaque ligne, vectorisé, sans division par zéro :
    +inf sans perte mais avec gain, NaN sans activité."""
    gains = np.sum(np.where(samples > 0, samples, 0.0), axis=1)
    losses = -np.sum(np.where(samples < 0, samples, 0.0), axis=1)
    pf = np.full(samples.shape[0], np.nan)
    has_loss = losses > 0
    pf[has_loss] = gains[has_loss] / losses[has_loss]
    pf[~has_loss & (gains > 0)] = np.inf
    return pf


def _pct(values: FloatArray, q: float) -> float:
    if values.size == 0:
        return math.nan
    return float(np.percentile(values, q, method=_PCT_METHOD))


def _empty_bootstrap(method: str, n_iter: int, block: float) -> BootstrapResult:
    nan = math.nan
    return BootstrapResult(method, n_iter, block, nan, nan, nan, nan, nan, nan, nan, nan, nan)


def bootstrap(
    profit: FloatArray,
    n_iter: int,
    rng: np.random.Generator,
    *,
    method: BootstrapMethod = METHOD_STATIONARY,
    block_length: float | None = None,
) -> BootstrapResult:
    """Distribution bootstrap du profit factor, du profit net et du drawdown."""
    x = np.asarray(profit, dtype=np.float64)
    n = x.size
    if method == METHOD_IID:
        block = 1.0
    else:
        block = stationary_block_length(x) if block_length is None else float(block_length)
    if n < 2 or n_iter < 1:
        return _empty_bootstrap(method, n_iter, block)
    pfs: list[FloatArray] = []
    nets: list[FloatArray] = []
    dds: list[FloatArray] = []
    done = 0
    while done < n_iter:
        size = min(CHUNK, n_iter - done)
        if method == METHOD_IID:
            idx = iid_bootstrap_indices(n, size, rng)
        else:
            idx = stationary_bootstrap_indices(n, size, block, rng)
        samples = x[idx]
        pfs.append(_row_profit_factors(samples))
        nets.append(np.sum(samples, axis=1))
        dds.append(max_drawdown_rows(np.cumsum(samples, axis=1)))
        done += size
    pf = np.concatenate(pfs)
    net = np.concatenate(nets)
    dd = np.concatenate(dds)
    return BootstrapResult(
        method=method,
        n_iter=n_iter,
        block_length=block,
        profit_factor_p05=_pct(pf, 5),
        profit_factor_p50=_pct(pf, 50),
        profit_factor_p95=_pct(pf, 95),
        net_profit_p05=_pct(net, 5),
        net_profit_p50=_pct(net, 50),
        net_profit_p95=_pct(net, 95),
        max_drawdown_p50=_pct(dd, 50),
        max_drawdown_p95=_pct(dd, 95),
        max_drawdown_p99=_pct(dd, 99),
    )


# ---------------------------------------------------------------------------
# permutation d'ordre
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PermutationResult:
    n_iter: int
    total_profit: float
    observed_drawdown: float
    drawdown_percentile: float
    drawdown_p50: float
    drawdown_p95: float


def permute_rows(x: FloatArray, n_rows: int, rng: np.random.Generator) -> FloatArray:
    """``n_rows`` réorganisations indépendantes de ``x`` (copie ; ``x`` intact)."""
    return rng.permuted(np.tile(x, (n_rows, 1)), axis=1)


def permutation_test(
    profit: FloatArray, n_iter: int, rng: np.random.Generator
) -> PermutationResult:
    """Drawdown de l'ordre réel comparé à celui de réorganisations aléatoires."""
    x = np.asarray(profit, dtype=np.float64)
    n = x.size
    total = float(np.sum(x)) if n else 0.0
    observed = max_drawdown(np.cumsum(x))
    if n < 2 or n_iter < 1:
        return PermutationResult(n_iter, total, observed, math.nan, math.nan, math.nan)
    dds: list[FloatArray] = []
    done = 0
    while done < n_iter:
        size = min(CHUNK, n_iter - done)
        dds.append(max_drawdown_rows(np.cumsum(permute_rows(x, size, rng), axis=1)))
        done += size
    dd = np.concatenate(dds)
    # égalité à l'arrondi près : une permutation au même drawdown que l'ordre réel
    # compte comme « ≤ » (l'ordre réel n'est alors pas anormalement lisse)
    tolerance = 1e-9 * max(abs(observed), 1e-300)
    percentile = 100.0 * float(np.mean(dd <= observed + tolerance))
    return PermutationResult(n_iter, total, observed, percentile, _pct(dd, 50), _pct(dd, 95))


# ---------------------------------------------------------------------------
# nulle sans edge
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NullResult:
    n_iter: int
    evaluable: bool
    p0: float
    observed_net: float
    p_value: float
    null_net_p50: float
    null_net_p95: float
    note_key: str = "resample.null_empirical"


def equilibrium_win_rate(gains: FloatArray, losses: FloatArray) -> float:
    """p₀ = |perte moyenne| / (gain moyen + |perte moyenne|) — espérance nulle."""
    if gains.size == 0 or losses.size == 0:
        return math.nan
    mean_gain = float(np.mean(gains))
    mean_loss = abs(float(np.mean(losses)))
    return mean_loss / (mean_gain + mean_loss)


def null_no_edge(profit: FloatArray, n_iter: int, rng: np.random.Generator) -> NullResult:
    """p-value du profit net observé contre des systèmes sans edge de même structure."""
    x = np.asarray(profit, dtype=np.float64)
    n = x.size
    gains = x[x > 0]
    losses = x[x < 0]
    observed = float(np.sum(x)) if n else 0.0
    p0 = equilibrium_win_rate(gains, losses)
    if math.isnan(p0) or n_iter < 1:
        return NullResult(n_iter, False, p0, observed, math.nan, math.nan, math.nan)
    nets: list[FloatArray] = []
    done = 0
    while done < n_iter:
        size = min(CHUNK, n_iter - done)
        is_win = rng.random((size, n)) < p0
        drawn_gains = rng.choice(gains, size=(size, n))
        drawn_losses = rng.choice(losses, size=(size, n))
        nets.append(np.sum(np.where(is_win, drawn_gains, drawn_losses), axis=1))
        done += size
    net = np.concatenate(nets)
    k = int(np.sum(net >= observed))
    p_value = (k + 1) / (n_iter + 1)
    return NullResult(n_iter, True, p0, observed, p_value, _pct(net, 50), _pct(net, 95))
