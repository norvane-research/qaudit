# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests de propriétés (hypothesis) sur les invariants statistiques (N-08).

Chaque test énonce un invariant qui doit tenir quelles que soient les données.
"""

from __future__ import annotations

import math
from itertools import pairwise

import numpy as np
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from qaudit.core.audit import AuditOptions, run_audit
from qaudit.core.metrics import compute_metrics, equity_returns, max_drawdown
from qaudit.core.resample import bootstrap, null_no_edge, permutation_test, permute_rows
from qaudit.core.stats import benjamini_hochberg, dsr, dsr_sensitivity, psr
from qaudit.core.validate import ValidationResult
from qaudit.io.method import load_method
from tests.helpers import make_tradeset

# montants réalistes : zéro exact ou |p| ∈ [1e-6, 1e6] (les dénormalisés ne sont
# pas des profits, et ils s'annulent sous une simple multiplication)
FINITE = st.one_of(
    st.just(0.0),
    st.floats(min_value=1e-6, max_value=1e6, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-1e6, max_value=-1e-6, allow_nan=False, allow_infinity=False),
)
PROFITS = hnp.arrays(np.float64, st.integers(min_value=0, max_value=60), elements=FINITE)
PROFITS_NONEMPTY = hnp.arrays(np.float64, st.integers(min_value=2, max_value=60), elements=FINITE)
SHARPE = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False)
SKEW = st.floats(min_value=-2.0, max_value=2.0, allow_nan=False)
KURT = st.floats(min_value=1.0, max_value=15.0, allow_nan=False)
SCALE = st.floats(min_value=1e-3, max_value=1e3, allow_nan=False, allow_infinity=False)

RATIO_FIELDS = (
    "win_rate",
    "profit_factor",
    "payoff_ratio",
    "sharpe_trade",
    "skew",
    "kurtosis",
)


def _same(a: float, b: float) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    if math.isinf(a) or math.isinf(b):
        return a == b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


# --- invariant 1 : le DSR décroît de façon monotone quand n_essais croît -----


@settings(max_examples=200, deadline=None)
@given(sr=SHARPE, skew=SKEW, kurt=KURT, n=st.integers(min_value=5, max_value=5000))
def test_dsr_is_monotone_decreasing_in_number_of_trials(
    sr: float, skew: float, kurt: float, n: int
) -> None:
    values = [dsr(sr, skew, kurt, n, k).dsr for k in (1, 2, 3, 5, 10, 50, 100, 300, 1000, 5000)]
    assume(all(not math.isnan(v) for v in values))
    for a, b in pairwise(values):
        assert a >= b - 1e-12


# --- invariant 2 : dupliquer chaque trade ne change aucun ratio -------------


@settings(max_examples=150, deadline=None)
@given(profits=PROFITS_NONEMPTY)
def test_duplicating_every_trade_leaves_ratios_unchanged(profits: np.ndarray) -> None:
    base = compute_metrics(make_tradeset(profits))
    doubled = compute_metrics(make_tradeset(np.repeat(profits, 2)))
    for name in RATIO_FIELDS:
        assert _same(getattr(base, name), getattr(doubled, name)), name
    assert _same(base.expectancy, doubled.expectancy)


# --- invariant 3 : multiplier les profits par c > 0 laisse les ratios inchangés


@settings(max_examples=150, deadline=None)
@given(profits=PROFITS_NONEMPTY, scale=SCALE)
def test_scaling_profits_leaves_ratios_and_significance_unchanged(
    profits: np.ndarray, scale: float
) -> None:
    base = compute_metrics(make_tradeset(profits))
    scaled = compute_metrics(make_tradeset(profits * scale))
    for name in RATIO_FIELDS:
        assert _same(getattr(base, name), getattr(scaled, name)), name
    assert _same(
        psr(base.sharpe_trade, base.skew, base.kurtosis, base.n),
        psr(scaled.sharpe_trade, scaled.skew, scaled.kurtosis, scaled.n),
    )
    assert _same(
        dsr(base.sharpe_trade, base.skew, base.kurtosis, base.n, 10).dsr,
        dsr(scaled.sharpe_trade, scaled.skew, scaled.kurtosis, scaled.n, 10).dsr,
    )


# --- invariant 4 : vide, unitaire, entièrement gagnant : jamais d'exception --


@settings(max_examples=100, deadline=None)
@given(profits=PROFITS)
def test_metrics_and_stats_never_raise(profits: np.ndarray) -> None:
    m = compute_metrics(make_tradeset(profits))
    assert m.n == profits.size
    _ = psr(m.sharpe_trade, m.skew, m.kurtosis, m.n)
    _ = dsr_sensitivity(m.sharpe_trade, m.skew, m.kurtosis, m.n, threshold=0.5)


@settings(max_examples=50, deadline=None)
@given(profits=hnp.arrays(np.float64, st.integers(min_value=1, max_value=40),
                          elements=st.floats(min_value=1e-3, max_value=1e6, allow_nan=False)))
def test_all_winning_set_is_handled(profits: np.ndarray) -> None:
    m = compute_metrics(make_tradeset(profits))
    assert m.profit_factor == math.inf
    assert m.win_rate == 1.0
    assert m.max_drawdown == 0.0
    assert m.longest_losing_streak == 0


# --- invariant 5 : PSR est une probabilité, croissante en SR ----------------


@settings(max_examples=200, deadline=None)
@given(sr=SHARPE, skew=SKEW, kurt=KURT, n=st.integers(min_value=2, max_value=5000))
def test_psr_is_a_probability_and_increases_with_sharpe(
    sr: float, skew: float, kurt: float, n: int
) -> None:
    p = psr(sr, skew, kurt, n)
    assume(not math.isnan(p))
    assert 0.0 <= p <= 1.0
    higher = psr(sr + 0.05, skew, kurt, n)
    assume(not math.isnan(higher))
    assert higher >= p - 1e-12


# --- invariant 6 : le drawdown est borné par la somme des pertes ------------


@settings(max_examples=150, deadline=None)
@given(profits=PROFITS)
def test_drawdown_is_nonnegative_and_bounded_by_total_losses(profits: np.ndarray) -> None:
    dd = max_drawdown(np.cumsum(profits))
    total_losses = float(-np.sum(profits[profits < 0])) if profits.size else 0.0
    assert dd >= 0.0
    assert dd <= total_losses + 1e-6 * max(1.0, total_losses)


# --- invariant 7 : les rendements relatifs n'ont jamais de base ≤ 0 ---------


@settings(max_examples=150, deadline=None)
@given(profits=PROFITS, balance=st.floats(min_value=1.0, max_value=1e6, allow_nan=False))
def test_equity_returns_never_use_a_nonpositive_base(profits: np.ndarray, balance: float) -> None:
    ts = make_tradeset(profits, initial_balance=balance)
    r = equity_returns(ts)
    if profits.size:
        base = balance + np.concatenate(([0.0], np.cumsum(profits)[:-1]))
    else:
        base = np.zeros(0)
    assert r.size <= profits.size
    assert np.all(base[: r.size] > 0)
    if r.size < profits.size:
        assert base[r.size] <= 0


# --- invariant 8 : Benjamini-Hochberg ---------------------------------------


@settings(max_examples=150, deadline=None)
@given(p=hnp.arrays(np.float64, st.integers(min_value=1, max_value=50),
                    elements=st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
       alpha=st.floats(min_value=0.001, max_value=0.5, allow_nan=False))
def test_benjamini_hochberg_adjusted_values_dominate_raw_and_are_monotone(
    p: np.ndarray, alpha: float
) -> None:
    res = benjamini_hochberg(p, alpha)
    assert np.all(res.adjusted >= p - 1e-12)
    assert np.all(res.adjusted <= 1.0 + 1e-12)
    order = np.argsort(p, kind="stable")
    sorted_adj = res.adjusted[order]
    assert np.all(np.diff(sorted_adj) >= -1e-12)
    assert np.all(res.reject == (res.adjusted <= alpha))
    # rejeter avec BH n'est jamais plus strict que Bonferroni
    assert np.all(res.reject >= (p * p.size <= alpha))


# --- invariant 9 : la permutation d'ordre conserve exactement le profit total


@settings(max_examples=100, deadline=None)
@given(profits=PROFITS_NONEMPTY, seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_permutation_preserves_exactly_the_multiset_and_the_total(
    profits: np.ndarray, seed: int
) -> None:
    rows = permute_rows(profits, 8, np.random.default_rng(seed))
    sorted_profits = np.sort(profits)
    for row in rows:
        np.testing.assert_array_equal(np.sort(row), sorted_profits)
    result = permutation_test(profits, 16, np.random.default_rng(seed))
    assert result.total_profit == float(np.sum(profits))


# --- invariant 10 : rééchantillonner ne lève jamais (vide, unitaire, gagnant) --


@settings(max_examples=60, deadline=None)
@given(profits=PROFITS, seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_resampling_never_raises(profits: np.ndarray, seed: int) -> None:
    rng = np.random.default_rng(seed)
    b = bootstrap(profits, 32, rng)
    p = permutation_test(profits, 32, rng)
    z = null_no_edge(profits, 32, rng)
    assert b.n_iter == p.n_iter == z.n_iter == 32


# --- invariant 11 : le PF de l'échantillon tombe dans l'intervalle bootstrap
#     [p05, p95] dans ≥ 90 % des cas (fréquence mesurée sur 200 jeux) ----------


def test_sample_profit_factor_falls_in_bootstrap_interval_at_least_90_percent() -> None:
    gen = np.random.default_rng(20260913)
    inside = 0
    trials = 200
    for _ in range(trials):
        n = int(gen.integers(30, 300))
        profits = gen.normal(gen.uniform(-5, 15), gen.uniform(20, 120), n)
        m = compute_metrics(make_tradeset(profits))
        res = bootstrap(profits, 400, np.random.default_rng(int(gen.integers(0, 2**31))))
        if res.profit_factor_p05 <= m.profit_factor <= res.profit_factor_p95:
            inside += 1
    assert inside / trials >= 0.90, inside


# --- invariant 12 : multiplier tous les profits (et le solde) par c > 0 laisse
#     le verdict inchangé — audit complet, même graine ------------------------


@settings(max_examples=25, deadline=None)
@given(
    profits=hnp.arrays(np.float64, st.integers(min_value=40, max_value=120), elements=FINITE),
    scale=st.floats(min_value=1e-2, max_value=1e2, allow_nan=False, allow_infinity=False),
    seed=st.integers(min_value=0, max_value=10_000),
)
def test_scaling_profits_leaves_the_verdict_unchanged(
    profits: np.ndarray, scale: float, seed: int
) -> None:
    config = load_method()
    options = AuditOptions(seed=seed, n_iter=200)
    base = run_audit(ValidationResult(make_tradeset(profits), (), None), config, options)
    scaled = run_audit(
        ValidationResult(
            make_tradeset(profits * scale, initial_balance=10_000.0 * scale), (), None
        ),
        config,
        options,
    )
    assert scaled.verdict.decision == base.verdict.decision
    assert [b.triggered for b in scaled.verdict.barriers] == [
        b.triggered for b in base.verdict.barriers
    ]
    assert [(f.code, f.severity) for f in scaled.findings] == [
        (f.code, f.severity) for f in base.findings
    ]
