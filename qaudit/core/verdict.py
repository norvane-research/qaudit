# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verdict : barrières, décision, conditions.

Le verdict découle **mécaniquement** des barrières déclenchées et des constats.
Aucun score composite, aucune pondération : chaque point est contestable
séparément.

Règles (seuils dans la configuration de méthode, jamais ici) :
- NO-GO si le nombre de constats bloquants ≥ ``blocking_no_go`` ou si une
  barrière est déclenchée ;
- sinon GO SOUS CONDITIONS si une barrière tombe dans sa bande d'indécision
  (porte E3 → ``revue_humaine``), si les constats majeurs cumulés atteignent
  ``major_conditional``, ou si une barrière n'a pas pu être évaluée (donnée
  manquante : walk-forward non fourni, nulle non calculable…) ;
- sinon GO.

Hypothèse retenue : une barrière non évaluable n'est jamais réputée franchie
avec succès ; elle devient une condition de mise en production nommée.
"""

from __future__ import annotations

from collections.abc import Iterable

from qaudit.core.config import MethodConfig
from qaudit.core.models import (
    BarrierResult,
    Condition,
    Decision,
    Finding,
    Severity,
    Verdict,
)

BARRIER_DSR = "dsr"
BARRIER_PF_P05 = "pf_p05"
BARRIER_DD_PERCENTILE = "dd_percentile"
BARRIER_NULL_PVALUE = "null_pvalue"
BARRIER_WF_EFFICIENCY = "wf_efficiency"
BARRIER_NAMES: tuple[str, ...] = (
    BARRIER_DSR,
    BARRIER_PF_P05,
    BARRIER_DD_PERCENTILE,
    BARRIER_NULL_PVALUE,
    BARRIER_WF_EFFICIENCY,
)


def evaluate_barriers(
    config: MethodConfig, values: dict[str, float | None]
) -> tuple[BarrierResult, ...]:
    """Évalue chaque barrière de la configuration sur la valeur fournie
    (``None`` / NaN → non évaluée)."""
    return tuple(spec.evaluate(values.get(spec.name)) for spec in config.barriers)


def _conditions(
    barriers: Iterable[BarrierResult], major_count: int, config: MethodConfig
) -> tuple[Condition, ...]:
    out: list[Condition] = []
    for b in barriers:
        if not b.evaluated:
            out.append(Condition.make("not_evaluated", "condition.not_evaluated", barrier=b.name))
        elif b.indecision and not b.triggered:
            out.append(
                Condition.make(
                    "indecision",
                    "condition.indecision",
                    barrier=b.name,
                    value=b.value if b.value is not None else 0.0,
                    band_low=b.band_low if b.band_low is not None else 0.0,
                    band_high=b.band_high if b.band_high is not None else 0.0,
                )
            )
    if major_count >= config.major_conditional:
        out.append(
            Condition.make(
                "majors", "condition.majors", count=major_count, threshold=config.major_conditional
            )
        )
    return tuple(out)


def decide(
    config: MethodConfig,
    barriers: tuple[BarrierResult, ...],
    findings: tuple[Finding, ...],
) -> Verdict:
    """Décision mécanique à partir des barrières évaluées et des constats."""
    blocking = sum(1 for f in findings if f.severity == Severity.BLOCKING)
    majors = sum(1 for f in findings if f.severity == Severity.MAJOR)
    triggered = any(b.triggered for b in barriers)
    indecision = any(b.indecision and b.evaluated for b in barriers)
    conditions = _conditions(barriers, majors, config)
    if blocking >= config.blocking_no_go or triggered:
        decision = Decision.NO_GO
    elif conditions:
        decision = Decision.CONDITIONAL
    else:
        decision = Decision.GO
    return Verdict(
        decision=decision,
        barriers=barriers,
        findings=findings,
        conditions=conditions,
        human_review=indecision,
        method_version=config.version,
    )
