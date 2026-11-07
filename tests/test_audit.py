# SPDX-License-Identifier: AGPL-3.0-or-later
"""Orchestrateur : déterminisme, autonomie hors ligne, cas dégénérés."""

from __future__ import annotations

import socket
from dataclasses import dataclass, fields

import numpy as np
import pytest

from qaudit.core.audit import AuditOptions, AuditResult, run_audit, streams
from qaudit.core.config import MethodConfig
from qaudit.core.models import Decision, IntArray, PriceSeries, Severity, TradeSet
from qaudit.core.validate import ValidationResult
from qaudit.core.walkforward import Candidate, WalkForwardInput
from qaudit.io.method import load_method
from qaudit.io.ruleset import load_ruleset
from tests.helpers import make_tradeset

FAST = AuditOptions(seed=7, n_iter=500)


@pytest.fixture(scope="module")
def config() -> MethodConfig:
    return load_method()


def _validation(profits: np.ndarray, initial_balance: float | None = 10_000.0) -> ValidationResult:
    return ValidationResult(make_tradeset(profits, initial_balance=initial_balance), (), None)


def _healthy(n: int = 300, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.where(rng.random(n) < 0.5, rng.gamma(4.0, 40.0, n), -rng.gamma(8.0, 12.5, n))


def _flatten(result: AuditResult) -> list[object]:
    """Toutes les grandeurs scalaires du résultat, dans un ordre fixe."""
    out: list[object] = []
    for block in (result.metrics, result.dsr_result, result.bootstrap, result.permutation,
                  result.null):
        out.extend(getattr(block, f.name) for f in fields(block))
    out.append(result.psr_value)
    out.extend((pt.n_trials, pt.dsr) for pt in result.sensitivity.points)
    out.append(result.verdict)
    return out


def test_same_seed_gives_identical_results(config: MethodConfig) -> None:
    v = _validation(_healthy())
    a = run_audit(v, config, FAST)
    b = run_audit(v, config, FAST)
    assert _flatten(a) == _flatten(b)


def test_different_seed_changes_simulations_only(config: MethodConfig) -> None:
    v = _validation(_healthy())
    a = run_audit(v, config, AuditOptions(seed=1, n_iter=500))
    b = run_audit(v, config, AuditOptions(seed=2, n_iter=500))
    assert a.metrics == b.metrics
    assert a.dsr_result == b.dsr_result
    assert a.bootstrap != b.bootstrap


def test_streams_are_independent_and_reproducible() -> None:
    a = streams(5)
    b = streams(5)
    assert len(a) == 8
    assert a[0].random() == b[0].random()
    assert a[0].random() != a[1].random()


def test_result_carries_versions_seed_and_fingerprint(config: MethodConfig) -> None:
    result = run_audit(_validation(_healthy()), config, FAST)
    assert result.engine_version == "1.0.0"
    assert result.method_version == "1.0"
    assert result.seed == 7
    assert result.n_iter == 500
    assert result.n_trials == config.default_n_trials == 10
    assert len(result.tradeset.fingerprint) == 64


def test_options_override_configuration(config: MethodConfig) -> None:
    result = run_audit(
        _validation(_healthy()), config,
        AuditOptions(seed=1, n_iter=300, n_trials=1, bootstrap_method="iid", var_sr=0.001),
    )
    assert result.n_trials == 1
    assert result.bootstrap.method == "iid"
    assert result.dsr_result.variance_source == "given"
    assert all(f.code != "dsr_lo_variance" for f in result.findings)


def test_lo_variance_is_flagged_when_variance_unknown(config: MethodConfig) -> None:
    result = run_audit(_validation(_healthy()), config, FAST)
    flagged = [f for f in result.findings if f.code == "dsr_lo_variance"]
    assert len(flagged) == 1
    assert flagged[0].severity == Severity.INFO
    assert any(f.code == "null_empirical" for f in result.findings)


# ---------------------------------------------------------------------------
# cas dégénérés : jamais d'exception non gérée
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "profits",
    [np.zeros(0), np.array([5.0]), np.array([1.0, 2.0, 3.0]), -np.ones(40), np.ones(40)],
    ids=["empty", "single", "three_winners", "all_losers", "all_winners"],
)
def test_degenerate_sets_produce_a_verdict_without_raising(
    profits: np.ndarray, config: MethodConfig
) -> None:
    result = run_audit(_validation(profits), config, FAST)
    assert result.verdict.decision in set(Decision)
    if profits.size < config.min_trades:
        assert result.verdict.decision == Decision.NO_GO
        assert any(f.code == "too_few_trades" for f in result.findings)


def test_all_winning_history_is_conditional_not_go(config: MethodConfig) -> None:
    # 40 gains sans aucune perte : nulle non calculable, PF infini, DSR indéfini
    # (écart-type nul) → barrières non évaluées → conditions, pas GO
    result = run_audit(_validation(np.ones(40)), config, FAST)
    assert result.verdict.decision == Decision.CONDITIONAL
    assert {c.param("barrier") for c in result.verdict.conditions if c.code == "not_evaluated"} >= {
        "null_pvalue", "wf_efficiency",
    }


# ---------------------------------------------------------------------------
# autonomie : aucun socket, aucun accès réseau pendant un audit complet
# ---------------------------------------------------------------------------


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("accès réseau tenté pendant un audit")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.mark.usefixtures("no_network")
def test_full_audit_runs_with_sockets_cut(config: MethodConfig) -> None:
    result = run_audit(_validation(_healthy(400)), config, AuditOptions(seed=3, n_iter=1000))
    assert result.verdict.decision in set(Decision)
    assert result.metrics.n == 400
    with pytest.raises(AssertionError, match="réseau"):
        socket.socket()


def test_audit_with_ruleset_reports_propfirm_block(config: MethodConfig) -> None:
    result = run_audit(
        _validation(_healthy(400)), config,
        AuditOptions(seed=1, n_iter=500, horizon_trading_days=60),
        ruleset=load_ruleset("two_step_static"),
    )
    assert result.propfirm is not None
    assert result.propfirm.evaluable
    assert result.propfirm.horizon_trading_days == 60
    assert result.propfirm.as_of == "2026-09-13"
    without = run_audit(_validation(_healthy(400)), config, AuditOptions(seed=1, n_iter=500))
    assert without.propfirm is None
    # le bloc propfirm n'entre pas dans le verdict : mêmes barrières, même décision
    assert [b.value for b in result.verdict.barriers] == [b.value for b in without.verdict.barriers]
    assert result.verdict.decision == without.verdict.decision


def test_default_horizon_comes_from_the_method_file(config: MethodConfig) -> None:
    result = run_audit(
        _validation(_healthy(400)), config, FAST, ruleset=load_ruleset("one_step_trailing")
    )
    assert result.propfirm is not None
    assert result.propfirm.horizon_trading_days == config.propfirm_horizon_trading_days == 250


# ---------------------------------------------------------------------------
# régimes et walk-forward dans l'orchestrateur
# ---------------------------------------------------------------------------


def test_default_classifier_depends_on_prices(config: MethodConfig) -> None:
    result = run_audit(_validation(_healthy()), config, FAST)
    assert result.regimes.method == "volatility_terciles"
    assert not result.prices_provided
    assert len(result.quarters) >= 1


@dataclass(frozen=True)
class OddEven:
    name: str = "odd_even"
    labels: tuple[str, ...] = ("even", "odd")

    def classify(self, ts: TradeSet, prices: PriceSeries | None) -> IntArray:
        return (np.arange(ts.n) % 2).astype(np.int64)


def test_classifier_is_injectable(config: MethodConfig) -> None:
    result = run_audit(_validation(_healthy()), config, FAST, classifier=OddEven())
    assert result.regimes.method == "odd_even"
    assert [s.n for s in result.regimes.stats] == [150, 150]


def test_walkforward_feeds_the_barrier(config: MethodConfig) -> None:
    good = _healthy(400, seed=5)
    inputs = WalkForwardInput((
        Candidate("A", make_tradeset(good, step_hours=24.0)),
        Candidate("B", make_tradeset(good * 0.5, step_hours=24.0)),
    ))
    result = run_audit(_validation(good), config, FAST, walkforward=inputs)
    barrier = next(b for b in result.verdict.barriers if b.name == "wf_efficiency")
    assert barrier.evaluated
    assert result.wf_efficiency == barrier.value
    losing = WalkForwardInput((Candidate("L", make_tradeset(-np.abs(good), step_hours=24.0)),))
    result2 = run_audit(_validation(good), config, FAST, walkforward=losing)
    assert result2.wf_efficiency is None
    assert any(c.code == "not_evaluated" and c.param("barrier") == "wf_efficiency"
               for c in result2.verdict.conditions)
