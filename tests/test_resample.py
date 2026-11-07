# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rééchantillonnage : bootstrap (IID et blocs), permutation, nulle sans edge."""

from __future__ import annotations

import math

import numpy as np
import pytest

from qaudit.core.resample import (
    CHUNK,
    METHOD_IID,
    METHOD_STATIONARY,
    bootstrap,
    equilibrium_win_rate,
    iid_bootstrap_indices,
    null_no_edge,
    permutation_test,
    permute_rows,
    stationary_block_length,
    stationary_bootstrap_indices,
)


def clustered_series(n: int, seed: int, stay: float = 0.9) -> np.ndarray:
    """Chaîne de Markov à deux régimes : les pertes se groupent (autocorrélation
    positive du P&L), ce que l'IID détruit."""
    r = np.random.default_rng(seed)
    state = 0
    out = np.empty(n)
    for i in range(n):
        if r.random() > stay:
            state = 1 - state
        out[i] = r.normal(20.0, 60.0) if state == 0 else r.normal(-25.0, 60.0)
    return out


# ---------------------------------------------------------------------------
# longueur de bloc
# ---------------------------------------------------------------------------


def test_block_length_is_one_for_iid_series() -> None:
    x = np.random.default_rng(1).normal(5.0, 100.0, 1000)
    assert stationary_block_length(x) == 1.0


def test_block_length_grows_with_serial_dependence() -> None:
    y = clustered_series(1000, 7)
    rho1 = float(np.corrcoef(y[:-1], y[1:])[0, 1])
    assert rho1 > 0.05  # dépendance bien présente
    block = stationary_block_length(y)
    assert block > 3.0
    assert block <= min(3 * math.sqrt(1000), 1000 / 3)


def test_block_length_edge_cases() -> None:
    assert stationary_block_length(np.ones(50)) == 1.0  # constante
    assert stationary_block_length(np.arange(5, dtype=float)) == 1.0  # trop courte
    assert stationary_block_length(np.zeros(0)) == 1.0


# ---------------------------------------------------------------------------
# indices
# ---------------------------------------------------------------------------


def test_iid_indices_shape_and_range(rng: np.random.Generator) -> None:
    idx = iid_bootstrap_indices(37, 12, rng)
    assert idx.shape == (12, 37)
    assert idx.min() >= 0
    assert idx.max() < 37


def test_stationary_indices_form_circular_blocks(rng: np.random.Generator) -> None:
    n = 50
    idx = stationary_bootstrap_indices(n, 200, 8.0, rng)
    assert idx.shape == (200, n)
    assert idx.min() >= 0
    assert idx.max() < n
    steps = (idx[:, 1:] - idx[:, :-1]) % n
    continuations = steps == 1  # à l'intérieur d'un bloc, l'indice avance de 1 (circulaire)
    share = float(np.mean(continuations))
    # P(continuer) = 1 − 1/8 = 0,875 ; tolérance large pour 200 × 49 pas
    assert 0.83 < share < 0.92


def test_stationary_indices_degenerate_to_iid_when_block_is_one() -> None:
    a = stationary_bootstrap_indices(20, 5, 1.0, np.random.default_rng(3))
    b = iid_bootstrap_indices(20, 5, np.random.default_rng(3))
    np.testing.assert_array_equal(a, b)


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_fields_are_ordered_and_finite(rng: np.random.Generator) -> None:
    x = np.random.default_rng(5).normal(3.0, 50.0, 300)
    res = bootstrap(x, 2000, rng)
    assert res.method == METHOD_STATIONARY
    assert res.n_iter == 2000
    assert res.profit_factor_p05 <= res.profit_factor_p50 <= res.profit_factor_p95
    assert res.net_profit_p05 <= res.net_profit_p50 <= res.net_profit_p95
    assert res.max_drawdown_p50 <= res.max_drawdown_p95 <= res.max_drawdown_p99
    assert all(math.isfinite(v) for v in (res.profit_factor_p05, res.net_profit_p95))


def test_bootstrap_iid_option_is_explicit(rng: np.random.Generator) -> None:
    x = clustered_series(400, 3)
    res = bootstrap(x, 500, rng, method=METHOD_IID)
    assert res.method == METHOD_IID
    assert res.block_length == 1.0
    forced = bootstrap(x, 500, rng, block_length=4.0)
    assert forced.block_length == 4.0


def test_bootstrap_degenerate_inputs() -> None:
    rng = np.random.default_rng(0)
    assert math.isnan(bootstrap(np.zeros(0), 100, rng).profit_factor_p05)
    assert math.isnan(bootstrap(np.array([5.0]), 100, rng).net_profit_p50)
    assert math.isnan(bootstrap(np.array([1.0, 2.0]), 0, rng).net_profit_p50)
    winners = bootstrap(np.array([1.0, 2.0, 3.0]), 50, rng)
    assert winners.profit_factor_p05 == math.inf
    assert winners.max_drawdown_p99 == 0.0


def test_bootstrap_is_deterministic_for_a_seed() -> None:
    x = clustered_series(300, 11)
    a = bootstrap(x, CHUNK + 250, np.random.default_rng(42))
    b = bootstrap(x, CHUNK + 250, np.random.default_rng(42))
    assert a == b
    c = bootstrap(x, CHUNK + 250, np.random.default_rng(43))
    assert c != a


def test_bootstrap_does_not_mutate_input() -> None:
    x = clustered_series(100, 2)
    before = x.copy()
    bootstrap(x, 200, np.random.default_rng(0))
    np.testing.assert_array_equal(x, before)


# ---------------------------------------------------------------------------
# permutation
# ---------------------------------------------------------------------------


def test_permutation_preserves_total_profit_and_input() -> None:
    x = np.random.default_rng(9).normal(2.0, 30.0, 250)
    x.setflags(write=False)
    before = x.copy()
    res = permutation_test(x, 3000, np.random.default_rng(1))
    assert res.total_profit == float(np.sum(x))
    np.testing.assert_array_equal(x, before)
    assert 0.0 <= res.drawdown_percentile <= 100.0
    assert res.drawdown_p50 <= res.drawdown_p95
    assert res.n_iter == 3000


def test_permute_rows_keeps_the_multiset_of_each_row() -> None:
    x = np.array([3.0, -1.0, 2.5, -7.0, 0.0, 4.0])
    rows = permute_rows(x, 20, np.random.default_rng(4))
    assert rows.shape == (20, 6)
    for row in rows:
        np.testing.assert_array_equal(np.sort(row), np.sort(x))


def test_permutation_percentile_reflects_order_luck() -> None:
    # tous les gains d'abord, toutes les pertes ensuite : drawdown observé maximal
    worst = np.concatenate((np.full(50, 10.0), np.full(50, -8.0)))
    res_worst = permutation_test(worst, 2000, np.random.default_rng(1))
    assert res_worst.drawdown_percentile >= 99.0
    # alternance stricte : drawdown observé minimal
    best = np.tile([10.0, -8.0], 50)
    res_best = permutation_test(best, 2000, np.random.default_rng(1))
    assert res_best.drawdown_percentile <= 1.0


def test_permutation_degenerate_inputs() -> None:
    rng = np.random.default_rng(0)
    res = permutation_test(np.zeros(0), 10, rng)
    assert res.total_profit == 0.0
    assert math.isnan(res.drawdown_percentile)
    single = permutation_test(np.array([-4.0]), 10, rng)
    assert single.observed_drawdown == 4.0
    assert math.isnan(single.drawdown_p50)


# ---------------------------------------------------------------------------
# nulle sans edge
# ---------------------------------------------------------------------------


def test_equilibrium_win_rate_formula() -> None:
    gains = np.array([30.0, 10.0])  # moyenne 20
    losses = np.array([-10.0, -10.0])  # |moyenne| 10
    assert equilibrium_win_rate(gains, losses) == pytest.approx(10 / 30)
    assert math.isnan(equilibrium_win_rate(np.zeros(0), losses))


def test_null_has_zero_expectation_by_construction() -> None:
    x = np.random.default_rng(3).normal(8.0, 40.0, 400)
    res = null_no_edge(x, 10_000, np.random.default_rng(0))
    assert res.evaluable
    # espérance nulle par trade : la médiane du profit net nul est proche de 0
    # relativement à l'écart-type d'un système nul (√n·σ ≈ 20·40 = 800)
    assert abs(res.null_net_p50) < 80.0
    assert res.null_net_p95 > 0.0
    assert 0.0 < res.p0 < 1.0
    assert res.note_key == "resample.null_empirical"


def test_null_p_value_is_small_for_a_real_edge_and_large_without() -> None:
    edge = np.random.default_rng(3).normal(15.0, 40.0, 400)  # SR ≈ 0,375/trade
    res_edge = null_no_edge(edge, 5000, np.random.default_rng(0))
    assert res_edge.p_value < 0.001
    noise = np.random.default_rng(4).normal(0.0, 40.0, 400)
    res_noise = null_no_edge(noise, 5000, np.random.default_rng(0))
    assert res_noise.p_value > 0.05


def test_null_p_value_is_never_zero() -> None:
    edge = np.full(50, 1.0)
    edge[::10] = -0.1
    res = null_no_edge(edge, 999, np.random.default_rng(0))
    assert res.p_value >= 1 / 1000


def test_null_not_evaluable_without_both_gains_and_losses() -> None:
    rng = np.random.default_rng(0)
    winners = null_no_edge(np.array([1.0, 2.0, 3.0]), 100, rng)
    assert not winners.evaluable
    assert math.isnan(winners.p_value)
    assert math.isnan(winners.p0)
    empty = null_no_edge(np.zeros(0), 100, rng)
    assert not empty.evaluable
    assert empty.observed_net == 0.0


def test_null_is_deterministic_for_a_seed() -> None:
    x = np.random.default_rng(3).normal(8.0, 40.0, 120)
    a = null_no_edge(x, 1500, np.random.default_rng(7))
    b = null_no_edge(x, 1500, np.random.default_rng(7))
    assert a == b
