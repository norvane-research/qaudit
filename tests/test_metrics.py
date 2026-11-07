# SPDX-License-Identifier: AGPL-3.0-or-later
"""Métriques : valeurs vérifiées par calcul indépendant."""

from __future__ import annotations

import math

import numpy as np
import pytest

from qaudit.core.metrics import (
    annualize_sharpe,
    compute_metrics,
    drawdown_curve,
    equity_returns,
    kurtosis,
    longest_losing_streak,
    max_drawdown,
    max_drawdown_pct,
    max_drawdown_rows,
    period_keys,
    profit_factor,
    quarter_labels,
    sharpe_ratio,
    skewness,
    trades_per_year,
)
from tests.helpers import make_tradeset

PROFITS = [10.0, -5.0, 20.0, -15.0, 0.0, 30.0]


def test_basic_aggregates() -> None:
    m = compute_metrics(make_tradeset(PROFITS, initial_balance=1000.0))
    assert m.n == 6
    assert m.net_profit == 40.0
    assert m.gross_profit == 60.0
    assert m.gross_loss == -20.0
    assert m.profit_factor == 3.0
    assert (m.n_wins, m.n_losses, m.n_flat) == (3, 2, 1)
    assert m.win_rate == 0.5
    assert m.avg_win == 20.0
    assert m.avg_loss == -10.0
    assert m.payoff_ratio == 2.0
    assert m.expectancy == pytest.approx(40 / 6)
    assert m.largest_win == 30.0
    assert m.largest_loss == -15.0
    assert m.longest_losing_streak == 1
    assert m.avg_holding_hours == 3.0
    assert m.total_return_pct == pytest.approx(4.0)


def test_sharpe_matches_manual_mean_over_std() -> None:
    x = np.array(PROFITS)
    expected = x.mean() / x.std()
    assert sharpe_ratio(x) == pytest.approx(expected)
    assert math.isnan(sharpe_ratio(np.array([1.0])))
    assert math.isnan(sharpe_ratio(np.array([2.0, 2.0, 2.0])))


def test_annualisation_uses_measured_span() -> None:
    # 6 trades ouverts toutes les 6 h : premier ouvert à t0, dernier clos à t0+33 h
    ts = make_tradeset(PROFITS)
    span_days = 33 / 24
    assert ts.span_days == pytest.approx(span_days)
    tpy = trades_per_year(6, span_days)
    assert tpy == pytest.approx(6 / (span_days / 365.25))
    m = compute_metrics(ts)
    assert m.trades_per_year == pytest.approx(tpy)
    assert m.sharpe_annual == pytest.approx(m.sharpe_trade * math.sqrt(tpy))
    assert math.isnan(trades_per_year(0, 10.0))
    assert math.isnan(trades_per_year(5, 0.0))
    assert math.isnan(annualize_sharpe(math.nan, 100.0))
    assert math.isnan(annualize_sharpe(1.0, math.nan))


def test_moments_match_manual_formulas() -> None:
    x = np.array([1.0, 2.0, 2.0, 3.0, 10.0])
    c = x - x.mean()
    m2, m3, m4 = (c**2).mean(), (c**3).mean(), (c**4).mean()
    assert skewness(x) == pytest.approx(m3 / m2**1.5)
    assert kurtosis(x) == pytest.approx(m4 / m2**2)
    assert math.isnan(skewness(np.array([1.0, 1.0, 1.0])))  # série constante
    assert math.isnan(kurtosis(np.array([1.0, 1.0, 1.0, 1.0])))
    assert math.isnan(skewness(np.array([1.0])))  # un seul point
    assert math.isnan(kurtosis(np.array([1.0])))
    assert skewness(np.array([0.0, 1.0])) == 0.0  # deux points : symétrique par construction
    assert kurtosis(np.array([0.0, 1.0])) == 1.0


def test_kurtosis_of_normal_sample_is_near_three(rng: np.random.Generator) -> None:
    x = rng.standard_normal(200_000)
    assert kurtosis(x) == pytest.approx(3.0, abs=0.05)
    assert skewness(x) == pytest.approx(0.0, abs=0.02)


def test_drawdown_on_cumulative_profit() -> None:
    cum = np.cumsum([10.0, -5.0, 20.0, -15.0, 0.0, 30.0])  # 10, 5, 25, 10, 10, 40
    np.testing.assert_allclose(drawdown_curve(cum), [0.0, 5.0, 0.0, 15.0, 15.0, 0.0])
    assert max_drawdown(cum) == 15.0
    assert max_drawdown(np.array([-3.0, -7.0, -2.0])) == 7.0  # sommet initial 0
    assert max_drawdown(np.zeros(0)) == 0.0
    rows = np.vstack([cum, np.array([-3.0, -7.0, -2.0, -2.0, -2.0, -2.0])])
    np.testing.assert_allclose(max_drawdown_rows(rows), [15.0, 7.0])
    assert max_drawdown_rows(np.zeros((2, 0))).tolist() == [0.0, 0.0]


def test_relative_drawdown_uses_equity_peak() -> None:
    equity = np.array([1100.0, 1050.0, 1250.0, 1000.0, 1300.0])
    # sommet 1250 → creux 1000 : 20 %
    assert max_drawdown_pct(equity, 1000.0) == pytest.approx(20.0)
    assert max_drawdown_pct(np.zeros(0), 1000.0) == 0.0
    m = compute_metrics(make_tradeset([100.0, -50.0, 200.0, -250.0, 300.0], initial_balance=1000.0))
    assert m.max_drawdown_pct == pytest.approx(20.0)
    assert m.max_drawdown == 250.0


def test_cagr_from_measured_span() -> None:
    # 2 trades, ouverts à 0 et 365,25 j, tenus 0 h ⇒ période exactement 1 an
    ts = make_tradeset(
        [100.0, 110.0], step_hours=365.25 * 24, hold_hours=0.0, initial_balance=1000.0
    )
    m = compute_metrics(ts)
    assert m.span_days == pytest.approx(365.25)
    assert m.cagr_pct == pytest.approx(21.0)


def test_relative_metrics_absent_without_initial_balance() -> None:
    m = compute_metrics(make_tradeset(PROFITS, initial_balance=None))
    assert m.max_drawdown_pct is None
    assert m.total_return_pct is None
    assert m.cagr_pct is None
    assert m.net_profit == 40.0


def test_cagr_undefined_when_final_equity_nonpositive() -> None:
    m = compute_metrics(make_tradeset([-1000.0, -10.0], step_hours=24 * 30, initial_balance=1000.0))
    assert m.cagr_pct is None


def test_streak_and_profit_factor_edges() -> None:
    assert longest_losing_streak(np.array([-1.0, -1.0, 1.0, -1.0, -1.0, -1.0])) == 3
    assert longest_losing_streak(np.zeros(0)) == 0
    assert profit_factor(10.0, 0.0) == math.inf
    assert math.isnan(profit_factor(0.0, 0.0))
    assert profit_factor(0.0, -5.0) == 0.0


def test_equity_returns_stop_at_nonpositive_base() -> None:
    ts = make_tradeset([100.0, -600.0, 200.0, 300.0], initial_balance=500.0)
    r = equity_returns(ts)
    np.testing.assert_allclose(r, [0.2, -1.0])  # base 500 puis 600 ; base 0 ensuite → stop
    assert equity_returns(make_tradeset([1.0], initial_balance=None)).size == 0
    assert equity_returns(make_tradeset([], initial_balance=100.0)).size == 0


def test_degenerate_sets_do_not_raise() -> None:
    for profits in ([], [5.0], [1.0, 2.0, 3.0], [-1.0, -2.0]):
        m = compute_metrics(make_tradeset(profits))
        assert m.n == len(profits)
    empty = compute_metrics(make_tradeset([]))
    assert empty.net_profit == 0.0
    assert math.isnan(empty.win_rate)
    assert math.isnan(empty.profit_factor)
    winners = compute_metrics(make_tradeset([1.0, 2.0, 3.0]))
    assert winners.profit_factor == math.inf
    assert math.isnan(winners.avg_loss)
    assert math.isnan(winners.payoff_ratio)


def test_quarter_labels_without_strftime() -> None:
    times = np.array(
        ["2021-01-15", "2021-03-31T23:59:59", "2021-04-01", "2021-12-31", "2022-07-04"],
        dtype="datetime64[ns]",
    )
    years, quarters = quarter_labels(times)
    assert years.tolist() == [2021, 2021, 2021, 2021, 2022]
    assert quarters.tolist() == [1, 1, 2, 4, 3]
    assert period_keys(times, "Q").tolist() == [20211, 20211, 20212, 20214, 20223]
    assert period_keys(times, "Y").tolist() == [2021, 2021, 2021, 2021, 2022]
    assert period_keys(times, "M").tolist() == [202101, 202103, 202104, 202112, 202207]
