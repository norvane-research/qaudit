# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chargeur de la configuration de méthode (TOML → ``MethodConfig``)."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any, cast

from qaudit.core.config import BarrierSpec, MethodConfig
from qaudit.core.errors import DataError
from qaudit.core.models import BarrierSense
from qaudit.core.resample import METHOD_IID, METHOD_STATIONARY
from qaudit.core.walkforward import (
    PROTOCOL_ANCHORED,
    PROTOCOL_ROLLING,
    SELECT_NET_PROFIT,
    SELECT_SHARPE,
)

DEFAULT_METHOD_FILE = "method-1.0.toml"


def _require(table: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in table:
        raise DataError("method.missing_key", column=f"{where}.{key}")
    return table[key]


def _barrier(name: str, table: Mapping[str, Any]) -> BarrierSpec:
    band = _require(table, "band", f"barriers.{name}")
    sense = str(table.get("sense", "below"))
    if sense not in ("below", "at_or_above"):
        raise DataError("method.bad_sense", column=f"barriers.{name}.sense", value=sense)
    return BarrierSpec(
        name=name,
        threshold=float(_require(table, "threshold", f"barriers.{name}")),
        band_low=float(band[0]),
        band_high=float(band[1]),
        sense=cast(BarrierSense, sense),
        message_key=str(table.get("message_key", f"barrier.{name}")),
    )


def _choice(table: Mapping[str, Any], key: str, where: str, allowed: tuple[str, ...]) -> str:
    value = str(_require(table, key, where))
    if value not in allowed:
        raise DataError(
            "method.bad_choice", column=f"{where}.{key}", value=value, allowed=", ".join(allowed)
        )
    return value


def parse_method(raw: Mapping[str, Any]) -> MethodConfig:
    """Construit la configuration à partir d'un TOML décodé ; toute clé
    obligatoire absente est une erreur nommée."""
    method = _require(raw, "method", "")
    barriers_raw = _require(raw, "barriers", "")
    findings = _require(raw, "findings", "")
    sample = _require(raw, "sample", "")
    dsr = _require(raw, "dsr", "")
    resample = _require(raw, "resample", "")
    validate = _require(raw, "validate", "")
    propfirm = _require(raw, "propfirm", "")
    regimes = _require(raw, "regimes", "")
    walkforward = _require(raw, "walkforward", "")
    detectors_raw = raw.get("detectors", {})
    detectors = {
        str(name): {str(k): float(v) for k, v in params.items()}
        for name, params in detectors_raw.items()
    }
    return MethodConfig(
        version=str(_require(method, "version", "method")),
        barriers=tuple(_barrier(str(name), table) for name, table in barriers_raw.items()),
        blocking_no_go=int(_require(findings, "blocking_no_go", "findings")),
        major_conditional=int(_require(findings, "major_conditional", "findings")),
        min_trades=int(_require(sample, "min_trades", "sample")),
        default_n_trials=int(_require(dsr, "default_n_trials", "dsr")),
        trial_grid=tuple(int(k) for k in _require(dsr, "trial_grid", "dsr")),
        n_iter=int(_require(resample, "n_iter", "resample")),
        bootstrap_method=_choice(
            resample, "bootstrap_method", "resample", (METHOD_STATIONARY, METHOD_IID)
        ),
        max_gap_days=float(_require(validate, "max_gap_days", "validate")),
        propfirm_horizon_trading_days=int(
            _require(propfirm, "default_horizon_trading_days", "propfirm")
        ),
        regimes_volatility_window=int(_require(regimes, "volatility_window", "regimes")),
        regimes_atr_period=int(_require(regimes, "atr_period", "regimes")),
        walkforward_n_folds=int(_require(walkforward, "n_folds", "walkforward")),
        walkforward_protocol=_choice(
            walkforward, "protocol", "walkforward", (PROTOCOL_ANCHORED, PROTOCOL_ROLLING)
        ),
        walkforward_selection=_choice(
            walkforward, "selection", "walkforward", (SELECT_NET_PROFIT, SELECT_SHARPE)
        ),
        detectors=detectors,
    )


def load_method(path: Path | None = None) -> MethodConfig:
    """Charge le fichier de méthode fourni, ou celui embarqué par défaut."""
    if path is None:
        source = resources.files("qaudit.io.methods").joinpath(DEFAULT_METHOD_FILE)
        with source.open("rb") as handle:
            return parse_method(tomllib.load(handle))
    with path.open("rb") as handle:
        return parse_method(tomllib.load(handle))
