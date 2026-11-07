# SPDX-License-Identifier: AGPL-3.0-or-later
"""Barrières et décision mécanique."""

from __future__ import annotations

import math

import pytest

from qaudit.core.config import BarrierSpec, MethodConfig
from qaudit.core.errors import InternalError
from qaudit.core.models import Decision, Finding, Severity
from qaudit.core.verdict import BARRIER_NAMES, decide, evaluate_barriers
from qaudit.io.method import load_method


@pytest.fixture(scope="module")
def config() -> MethodConfig:
    return load_method()


def test_method_file_carries_the_specified_thresholds(config: MethodConfig) -> None:
    assert config.version == "1.0"
    assert tuple(b.name for b in config.barriers) == BARRIER_NAMES
    dsr = config.barrier("dsr")
    assert (dsr.threshold, dsr.band_low, dsr.band_high, dsr.sense) == (0.5, 0.45, 0.55, "below")
    pf = config.barrier("pf_p05")
    assert (pf.threshold, pf.band_low, pf.band_high) == (1.0, 0.95, 1.05)
    dd = config.barrier("dd_percentile")
    assert (dd.threshold, dd.band_low, dd.band_high) == (5.0, 3.0, 8.0)
    null = config.barrier("null_pvalue")
    assert (null.threshold, null.band_low, null.band_high, null.sense) == (
        0.05, 0.03, 0.08, "at_or_above",
    )
    wf = config.barrier("wf_efficiency")
    assert (wf.threshold, wf.band_low, wf.band_high) == (0.4, 0.35, 0.5)
    assert config.blocking_no_go == 1
    assert config.major_conditional == 3
    with pytest.raises(InternalError):
        config.barrier("nope")


def test_barrier_below_sense() -> None:
    spec = BarrierSpec("x", 0.5, 0.45, 0.55, "below", "barrier.x")
    low = spec.evaluate(0.30)
    assert (low.evaluated, low.triggered, low.indecision) == (True, True, False)
    edge = spec.evaluate(0.47)
    assert (edge.triggered, edge.indecision) == (True, True)  # déclenchée ET dans la bande
    ok_band = spec.evaluate(0.53)
    assert (ok_band.triggered, ok_band.indecision) == (False, True)
    clear = spec.evaluate(0.90)
    assert (clear.triggered, clear.indecision) == (False, False)
    at_threshold = spec.evaluate(0.50)
    assert not at_threshold.triggered  # « < seuil » : le seuil lui-même passe


def test_barrier_at_or_above_sense() -> None:
    spec = BarrierSpec("p", 0.05, 0.03, 0.08, "at_or_above", "barrier.p")
    assert spec.evaluate(0.05).triggered
    assert spec.evaluate(0.049).triggered is False
    assert spec.evaluate(0.049).indecision
    assert spec.evaluate(0.5).triggered


def test_unevaluated_barrier_for_none_or_nan() -> None:
    spec = BarrierSpec("x", 0.5, 0.45, 0.55, "below", "barrier.x")
    for value in (None, math.nan):
        result = spec.evaluate(value)
        assert (result.evaluated, result.triggered, result.indecision) == (False, False, False)
        assert result.value is None


def _values(**overrides: float | None) -> dict[str, float | None]:
    good: dict[str, float | None] = {
        "dsr": 0.9, "pf_p05": 1.3, "dd_percentile": 50.0, "null_pvalue": 0.001,
        "wf_efficiency": 0.8,
    }
    good.update(overrides)
    return good


def test_go_when_everything_passes(config: MethodConfig) -> None:
    verdict = decide(config, evaluate_barriers(config, _values()), ())
    assert verdict.decision == Decision.GO
    assert verdict.conditions == ()
    assert not verdict.human_review
    assert verdict.method_version == "1.0"


def test_no_go_when_a_barrier_is_triggered(config: MethodConfig) -> None:
    verdict = decide(config, evaluate_barriers(config, _values(dsr=0.2)), ())
    assert verdict.decision == Decision.NO_GO
    verdict = decide(config, evaluate_barriers(config, _values(null_pvalue=0.2)), ())
    assert verdict.decision == Decision.NO_GO


def test_no_go_when_a_blocking_finding_exists(config: MethodConfig) -> None:
    findings = (Finding.make("ruin", Severity.BLOCKING, "validate.ruin", "validate"),)
    verdict = decide(config, evaluate_barriers(config, _values()), findings)
    assert verdict.decision == Decision.NO_GO
    assert verdict.blocking_count == 1


def test_conditional_on_indecision_band_sets_human_review(config: MethodConfig) -> None:
    verdict = decide(config, evaluate_barriers(config, _values(pf_p05=1.02)), ())
    assert verdict.decision == Decision.CONDITIONAL
    assert verdict.human_review
    assert [c.code for c in verdict.conditions] == ["indecision"]
    assert verdict.conditions[0].param("barrier") == "pf_p05"


def test_conditional_when_a_barrier_could_not_be_evaluated(config: MethodConfig) -> None:
    verdict = decide(config, evaluate_barriers(config, _values(wf_efficiency=None)), ())
    assert verdict.decision == Decision.CONDITIONAL
    assert not verdict.human_review
    assert [c.code for c in verdict.conditions] == ["not_evaluated"]


def test_conditional_when_three_major_findings(config: MethodConfig) -> None:
    majors = tuple(Finding.make(f"m{i}", Severity.MAJOR, "k", "s") for i in range(3))
    verdict = decide(config, evaluate_barriers(config, _values()), majors)
    assert verdict.decision == Decision.CONDITIONAL
    assert verdict.conditions[0].code == "majors"
    assert verdict.conditions[0].param("count") == 3
    two = decide(config, evaluate_barriers(config, _values()), majors[:2])
    assert two.decision == Decision.GO


def test_triggered_inside_band_is_no_go_not_conditional(config: MethodConfig) -> None:
    # 0,47 : sous le seuil ET dans la bande → NO-GO, revue humaine signalée
    verdict = decide(config, evaluate_barriers(config, _values(dsr=0.47)), ())
    assert verdict.decision == Decision.NO_GO
    assert verdict.human_review
    assert all(c.code != "indecision" for c in verdict.conditions)
