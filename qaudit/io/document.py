# SPDX-License-Identifier: AGPL-3.0-or-later
"""Document JSON du rapport : versionné, schéma publié, indépendant de la langue.

Le document est la représentation canonique d'un audit : c'est lui qui est
archivé (règle R5), rendu en HTML/PDF (avec ou sans nouveau calcul) et agrégé
en mode lot. Il ne contient que des clés, des nombres, des chaînes techniques
et les paramètres des constats — jamais de texte de langue naturelle : les
libellés sont produits au rendu par les catalogues i18n.

Déterminisme : clés triées, indentation fixe, flottants arrondis à 12 chiffres
significatifs, non-finis encodés en chaînes explicites (``"NaN"``,
``"Infinity"``, ``"-Infinity"``), aucune horodatation de génération.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import asdict, fields, is_dataclass
from typing import Any

import numpy as np

from qaudit import ENGINE_VERSION
from qaudit.core.audit import AuditResult
from qaudit.core.models import Finding, Severity, time_to_iso

SCHEMA_NAME = "qaudit.report"
SCHEMA_VERSION = "1.0"
Json = dict[str, Any]


def _number(value: float) -> float | str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0:
        return 0.0
    return float(f"{value:.12g}")


def _scalar(value: object) -> tuple[bool, Any]:
    """(reconnu, valeur JSON) pour les scalaires."""
    if isinstance(value, bool | str) or value is None:
        return True, value
    if isinstance(value, Severity):
        return True, value.name.lower()
    if isinstance(value, int | np.integer):
        return True, int(value)
    if isinstance(value, float | np.floating):
        return True, _number(float(value))
    return False, None


def _clean(value: object) -> Any:
    """Convertit récursivement en types JSON purs, de façon déterministe."""
    known, scalar = _scalar(value)
    if known:
        return scalar
    if isinstance(value, np.ndarray):
        return [_clean(v) for v in value.tolist()]
    if isinstance(value, Mapping):
        return {str(k): _clean(v) for k, v in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _clean(getattr(value, f.name)) for f in fields(value)}
    if hasattr(value, "value"):  # Enum (Decision)
        return _clean(value.value)
    return str(value)


def _finding(finding: Finding) -> Json:
    return {
        "code": finding.code,
        "severity": finding.severity.name.lower(),
        "source": finding.source,
        "message_key": finding.message_key,
        "params": {k: _clean(v) for k, v in finding.params},
    }


def _verdict(result: AuditResult) -> Json:
    verdict = result.verdict
    return {
        "decision": verdict.decision.value,
        "revue_humaine": verdict.human_review,
        "method_version": verdict.method_version,
        "counts": {
            "blocking": verdict.blocking_count,
            "major": verdict.major_count,
            "minor": verdict.count(Severity.MINOR),
            "info": verdict.count(Severity.INFO),
        },
        "barriers": [_clean(asdict(b)) for b in verdict.barriers],
        "conditions": [
            {
                "code": c.code,
                "message_key": c.message_key,
                "params": {k: _clean(v) for k, v in c.params},
            }
            for c in verdict.conditions
        ],
    }


def _data(result: AuditResult) -> Json:
    ts = result.tradeset
    return {
        "fingerprint": ts.fingerprint,
        "currency": ts.currency,
        "initial_balance": _clean(ts.initial_balance),
        "n_trades": result.full_n,
        "n_usable": ts.n,
        "ruin_index": result.ruin_index,
        "span_days": _number(ts.span_days),
        "first_open": time_to_iso(ts.open_time.min()) if ts.n else None,
        "last_close": time_to_iso(ts.close_time.max()) if ts.n else None,
        "known_fields": sorted(ts.known_fields),
        "prices_provided": result.prices_provided,
    }


def to_document(result: AuditResult) -> Json:
    """Document canonique d'un audit (dictionnaire JSON pur)."""
    return {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "engine_version": result.engine_version,
        "method_version": result.method_version,
        "seed": result.seed,
        "n_iter": result.n_iter,
        "n_trials": result.n_trials,
        "data": _data(result),
        "verdict": _verdict(result),
        "findings": [_finding(f) for f in result.findings],
        "metrics": _clean(result.metrics),
        "significance": {
            "psr": _number(result.psr_value),
            "dsr": _clean(result.dsr_result),
            "sensitivity": _clean(result.sensitivity),
        },
        "resampling": {
            "bootstrap": _clean(result.bootstrap),
            "permutation": _clean(result.permutation),
            "null": _clean(result.null),
        },
        "regimes": _clean(result.regimes),
        "quarters": [_clean(q) for q in result.quarters],
        "walkforward": _clean(result.walkforward) if result.walkforward is not None else None,
        "propfirm": _clean(result.propfirm) if result.propfirm is not None else None,
    }


def dumps(document: Mapping[str, Any]) -> str:
    """Sérialisation canonique : identique à l'octet pour un document identique."""
    return (
        json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )


def loads(text: str) -> Json:
    document = json.loads(text)
    if not isinstance(document, dict):
        raise ValueError("document")
    return document


def number(value: object) -> float:
    """Relit un nombre encodé par ``_number`` (chaînes non finies comprises)."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if value == "NaN":
        return math.nan
    if value == "Infinity":
        return math.inf
    if value == "-Infinity":
        return -math.inf
    if value is None:
        return math.nan
    return float(str(value))


ENGINE = ENGINE_VERSION
