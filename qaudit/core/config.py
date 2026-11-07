# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration de la méthode : seuils des barrières, paramètres des détecteurs.

Les valeurs vivent dans un fichier TOML versionné (``qaudit/io/method/``) ;
le noyau ne connaît que cette structure immuable, chargée par la coquille.
Changer un seuil incrémente la version de la méthode et invalide les rapports
antérieurs : la version est imprimée dans chaque rapport.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from qaudit.core.errors import InternalError
from qaudit.core.models import BarrierResult, BarrierSense

DetectorParams = Mapping[str, float]


@dataclass(frozen=True, slots=True)
class BarrierSpec:
    """Une barrière : seuil, bande d'indécision et sens de déclenchement."""

    name: str
    threshold: float
    band_low: float
    band_high: float
    sense: BarrierSense
    message_key: str

    def evaluate(self, value: float | None) -> BarrierResult:
        """NaN ou ``None`` → barrière non évaluée (ni déclenchée ni en indécision)."""
        if value is None or value != value:
            return BarrierResult(
                self.name, None, self.threshold, self.band_low, self.band_high,
                self.sense, False, False, False, self.message_key,
            )
        triggered = value < self.threshold if self.sense == "below" else value >= self.threshold
        indecision = self.band_low <= value <= self.band_high
        return BarrierResult(
            self.name, float(value), self.threshold, self.band_low, self.band_high,
            self.sense, True, triggered, indecision, self.message_key,
        )


@dataclass(frozen=True)
class MethodConfig:
    """Paramètres versionnés de la méthode d'audit."""

    version: str
    barriers: tuple[BarrierSpec, ...]
    blocking_no_go: int
    major_conditional: int
    min_trades: int
    default_n_trials: int
    trial_grid: tuple[int, ...]
    n_iter: int
    bootstrap_method: str
    max_gap_days: float
    propfirm_horizon_trading_days: int
    regimes_volatility_window: int
    regimes_atr_period: int
    walkforward_n_folds: int
    walkforward_protocol: str
    walkforward_selection: str
    detectors: Mapping[str, DetectorParams]

    def __post_init__(self) -> None:
        frozen = MappingProxyType({k: MappingProxyType(dict(v)) for k, v in self.detectors.items()})
        object.__setattr__(self, "detectors", frozen)

    def barrier(self, name: str) -> BarrierSpec:
        for spec in self.barriers:
            if spec.name == name:
                return spec
        raise InternalError("internal.unknown_barrier", name=name)

    def detector_params(self, name: str) -> DetectorParams:
        return self.detectors.get(name, MappingProxyType({}))


def param(params: DetectorParams, name: str, detector: str) -> float:
    """Paramètre obligatoire d'un détecteur ; son absence est un défaut de
    configuration, jamais une valeur devinée."""
    if name not in params:
        raise InternalError("internal.missing_detector_param", detector=detector, name=name)
    return float(params[name])
