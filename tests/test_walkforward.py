# SPDX-License-Identifier: AGPL-3.0-or-later
"""Walk-forward ancré et glissant sur des résultats fournis ; WFE vérifiée à la main."""

from __future__ import annotations

import math

import numpy as np
import pytest

from qaudit.core.walkforward import (
    PROTOCOL_ANCHORED,
    PROTOCOL_ROLLING,
    SELECT_SHARPE,
    Candidate,
    WalkForwardInput,
    run,
)
from tests.helpers import make_tradeset

DAY_H = 24.0


def daily_candidate(params: str, per_day: float, n_days: int = 120, noise: float = 0.0,
                    seed: int = 0) -> Candidate:
    """Un trade par jour (ouvert à t0 + k jours, tenu 1 h) de profit ``per_day``."""
    rng = np.random.default_rng(seed)
    profits = np.full(n_days, per_day) + (rng.normal(0, noise, n_days) if noise else 0.0)
    return Candidate(params, make_tradeset(profits, step_hours=DAY_H, hold_hours=1.0))


def test_anchored_protocol_selects_best_in_sample_and_measures_oos() -> None:
    # A gagne 10/jour, B 5/jour : A est retenu dans chaque pli ; WFE = 1 exactement
    inputs = WalkForwardInput((daily_candidate("A", 10.0), daily_candidate("B", 5.0)))
    report = run(inputs, n_folds=4, protocol=PROTOCOL_ANCHORED)
    assert report.evaluable
    assert report.n_folds == 4
    assert all(f.selected == "A" for f in report.folds)
    assert report.efficiency == pytest.approx(1.0, rel=0.03)
    assert report.oos_positive_share == 1.0
    # ancré : la fenêtre IS commence toujours au début
    assert len({f.is_start for f in report.folds}) == 1
    # les plis OOS se suivent sans trou
    for a, b in zip(report.folds, report.folds[1:], strict=False):
        assert a.oos_end == b.oos_start


def test_rolling_protocol_uses_only_the_previous_segment() -> None:
    inputs = WalkForwardInput((daily_candidate("A", 10.0), daily_candidate("B", 5.0)))
    report = run(inputs, n_folds=4, protocol=PROTOCOL_ROLLING)
    assert report.protocol == PROTOCOL_ROLLING
    assert len({f.is_start for f in report.folds}) == 4
    for f in report.folds:
        assert f.is_days == pytest.approx(f.oos_days, rel=0.05)


def test_efficiency_matches_hand_computation() -> None:
    # 121 trades instantanés aux jours 0..120 : étendue = 120 jours exactement,
    # 3 segments de 40 jours. A : +10/jour les 60 premiers jours puis +2 ; B : +4.
    a_profits = np.concatenate((np.full(60, 10.0), np.full(61, 2.0)))
    a = Candidate("A", make_tradeset(a_profits, step_hours=DAY_H, hold_hours=0.0))
    b = Candidate("B", make_tradeset(np.full(121, 4.0), step_hours=DAY_H, hold_hours=0.0))
    report = run(WalkForwardInput((a, b)), n_folds=2, protocol=PROTOCOL_ANCHORED)
    # pli 1 : IS jours 0-39 → A (400) vs B (160) → A ; OOS jours 40-79 : 20×10 + 20×2 = 240
    # pli 2 : IS jours 0-79 → A (640) vs B (320) → A ; OOS jours 80-120 : 41×2 = 82
    assert [f.selected for f in report.folds] == ["A", "A"]
    assert report.folds[0].is_net == pytest.approx(400.0)
    assert report.folds[1].is_net == pytest.approx(640.0)
    assert report.folds[0].oos_net == pytest.approx(240.0)
    assert report.folds[1].oos_net == pytest.approx(82.0)
    # WFE = (322 / 80 j) / (1040 / 120 j) = 4,025 / 8,667 = 0,4644
    assert report.efficiency == pytest.approx((322.0 / 80.0) / (1040.0 / 120.0), rel=1e-6)
    assert report.oos_net_total == pytest.approx(322.0)


def test_sharpe_selection_prefers_the_steadier_candidate() -> None:
    steady = daily_candidate("steady", 3.0, noise=1.0, seed=1)
    wild = daily_candidate("wild", 4.0, noise=40.0, seed=2)
    by_net = run(WalkForwardInput((steady, wild)), n_folds=3)
    by_sharpe = run(WalkForwardInput((steady, wild)), n_folds=3, selection=SELECT_SHARPE)
    assert by_sharpe.selection == SELECT_SHARPE
    assert all(f.selected == "steady" for f in by_sharpe.folds)
    assert by_net.efficiency != by_sharpe.efficiency or by_net.folds != by_sharpe.folds


def test_not_evaluable_cases() -> None:
    empty = run(WalkForwardInput(()), n_folds=3)
    assert not empty.evaluable
    assert math.isnan(empty.efficiency)
    losing = run(WalkForwardInput((daily_candidate("L", -5.0),)), n_folds=3)
    assert losing.evaluable
    assert math.isnan(losing.efficiency)  # rendement IS ≤ 0 : ratio indéfini
    assert losing.oos_positive_share == 0.0
    zero_folds = run(WalkForwardInput((daily_candidate("A", 1.0),)), n_folds=0)
    assert not zero_folds.evaluable


def test_single_candidate_measures_consistency_without_selection() -> None:
    report = run(WalkForwardInput((daily_candidate("only", 5.0),)), n_folds=3)
    assert report.n_candidates == 1
    assert report.efficiency == pytest.approx(1.0, rel=0.03)
