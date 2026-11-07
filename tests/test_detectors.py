# SPDX-License-Identifier: AGPL-3.0-or-later
"""Détecteurs structurels : cas positifs, négatifs et désactivation propre."""

from __future__ import annotations

import numpy as np
import pytest

from qaudit.core.config import MethodConfig
from qaudit.core.detectors import (
    equity_linearity,
    grid,
    holding_time,
    martingale,
    no_stop,
    payoff_asymmetry,
    period_dependence,
    profit_concentration,
)
from qaudit.core.detectors.base import Detector
from qaudit.core.detectors.registry import build_detectors, detector_names, run_detectors
from qaudit.core.errors import InternalError
from qaudit.core.models import Severity, TradeSet
from qaudit.io.method import load_method
from tests.helpers import make_tradeset


@pytest.fixture(scope="module")
def config() -> MethodConfig:
    return load_method()


def _detector(config: MethodConfig, name: str) -> Detector:
    return next(d for d in build_detectors(config) if d.name == name)


# ---------------------------------------------------------------------------
# registre
# ---------------------------------------------------------------------------


def test_registry_lists_eight_price_free_and_three_price_detectors(config: MethodConfig) -> None:
    names = detector_names()
    assert len(names) == len(set(names)) == 11
    detectors = build_detectors(config)
    assert sum(1 for d in detectors if not d.needs_prices) == 8
    assert {d.name for d in detectors if d.needs_prices} == {
        "stop_geometry", "lookahead", "execution_realism",
    }


def test_missing_detector_parameter_is_a_configuration_error(config: MethodConfig) -> None:
    with pytest.raises(InternalError) as info:
        martingale.make({"ratio_min": 1.5})
    assert info.value.key == "internal.missing_detector_param"


def test_run_detectors_returns_only_findings(config: MethodConfig) -> None:
    ts = make_tradeset(np.random.default_rng(1).normal(20, 50, 200), stop_loss=np.full(200, 1.09))
    findings = run_detectors(build_detectors(config), ts)
    assert all(f.source.startswith("detector.") for f in findings)
    assert all(f.severity == Severity.INFO for f in findings), findings
    # sans série de prix, chaque détecteur à prix dit ce qu'il n'a pas pu tester
    skipped = {
        f.param("detector") for f in findings if f.message_key == "detector.skipped_no_prices"
    }
    assert skipped == {"stop_geometry", "lookahead", "execution_realism"}


# ---------------------------------------------------------------------------
# martingale
# ---------------------------------------------------------------------------


def _martingale_set(n: int, seed: int) -> TradeSet:
    rng = np.random.default_rng(seed)
    volume = 0.01
    vols, profits = [], []
    for _ in range(n):
        win = rng.random() < 0.7
        units = volume / 0.01
        vols.append(volume)
        profits.append(10.0 * units if win else -30.0 * units)
        volume = 0.01 if win else volume * 2
    return make_tradeset(profits, volume=vols)


def test_martingale_detected_as_blocking(config: MethodConfig) -> None:
    finding = _detector(config, "martingale").detect(_martingale_set(300, 3))
    assert finding is not None
    assert finding.severity == Severity.BLOCKING
    assert finding.param("share_after_loss") == 1.0
    assert finding.param("share_after_win") == 0.0


def test_constant_volume_is_not_a_martingale(config: MethodConfig) -> None:
    ts = make_tradeset(np.random.default_rng(2).normal(0, 50, 300))
    assert _detector(config, "martingale").detect(ts) is None


def test_symmetric_sizing_is_not_a_martingale(config: MethodConfig) -> None:
    # volume qui croît avec l'equity, indépendamment du résultat précédent
    rng = np.random.default_rng(4)
    profits = rng.normal(5, 50, 300)
    volumes = 0.1 * 1.01 ** np.arange(300) * rng.choice([1.0, 2.0], 300)
    ts = make_tradeset(profits, volume=volumes.astype(np.float64))
    assert _detector(config, "martingale").detect(ts) is None


def test_martingale_skips_without_volume_or_events(config: MethodConfig) -> None:
    det = _detector(config, "martingale")
    no_volume = make_tradeset(
        [1.0, -1.0, 2.0], known=frozenset({"open_time", "close_time", "profit"})
    )
    skipped = det.detect(no_volume)
    assert skipped is not None
    assert skipped.severity == Severity.INFO
    assert skipped.param("fields") == "volume"
    few = det.detect(make_tradeset([1.0, -1.0, 2.0]))
    assert few is not None
    assert few.message_key == "detector.skipped_too_few"
    assert det.detect(make_tradeset([])) is not None


# ---------------------------------------------------------------------------
# grille
# ---------------------------------------------------------------------------


def _grid_set(cycles: int) -> TradeSet:
    """Cycles de 3 achats à prix décroissant, volume ×1,5, clôturés ensemble."""
    t0 = np.datetime64("2021-01-04T09:00:00", "ns")
    hour = np.timedelta64(3_600_000_000_000, "ns")
    opens, closes, prices, volumes, profits = [], [], [], [], []
    t = t0
    for c in range(cycles):
        close_t = t + 10 * hour
        for level in range(3):
            opens.append(t + level * 2 * hour)
            closes.append(close_t)
            prices.append(1.1000 - level * 0.0020 + c * 0.0001)
            volumes.append(0.1 * 1.5**level)
            profits.append(20.0 - level * 5.0)
        t = close_t + hour
    n = len(opens)
    return TradeSet(
        open_time=np.array(opens, dtype="datetime64[ns]"),
        close_time=np.array(closes, dtype="datetime64[ns]"),
        profit=np.array(profits),
        direction=np.ones(n, dtype=np.int8),
        volume=np.array(volumes),
        symbol=np.full(n, "EURUSD"),
        open_price=np.array(prices),
        close_price=np.array(prices) + 0.001,
        stop_loss=np.full(n, np.nan),
        take_profit=np.full(n, np.nan),
        ticket=np.arange(1, n + 1),
        currency="USD",
        initial_balance=10_000.0,
        fingerprint="0" * 64,
        known_fields=frozenset({"open_time", "close_time", "profit", "direction", "volume",
                                "symbol", "open_price", "close_price"}),
    )


def test_grid_detected_as_blocking(config: MethodConfig) -> None:
    finding = _detector(config, "grid").detect(_grid_set(20))
    assert finding is not None
    assert finding.severity == Severity.BLOCKING
    assert finding.param("share") == pytest.approx(2 / 3)
    assert finding.param("max_depth") == 2


def test_concurrent_independent_positions_are_not_a_grid(config: MethodConfig) -> None:
    """Le piège de la v0.1 : positions concurrentes ≠ grille.

    Trades longs qui se chevauchent (ouverts toutes les 6 h, tenus 30 h), à prix
    aléatoires, volume constant, clôturés séparément : aucun constat.
    """
    rng = np.random.default_rng(5)
    n = 200
    prices = 1.1 + np.cumsum(rng.normal(0, 0.0008, n))
    ts = make_tradeset(
        rng.normal(5, 50, n), step_hours=6.0, hold_hours=30.0, open_price=prices,
        direction=np.ones(n, dtype=np.int64),
    )
    assert _detector(config, "grid").detect(ts) is None


def test_pyramiding_into_winners_is_not_a_grid(config: MethodConfig) -> None:
    # ajouts à prix *meilleur* pour un achat (prix croissant), clôture commune
    base = _grid_set(20)
    reversed_prices = np.array(base.open_price)
    # inverse l'ordre des prix dans chaque cycle : niveau 0 le plus bas
    for c in range(20):
        block = reversed_prices[c * 3 : c * 3 + 3]
        reversed_prices[c * 3 : c * 3 + 3] = block[::-1]
    ts = TradeSet(
        open_time=base.open_time, close_time=base.close_time, profit=base.profit,
        direction=base.direction, volume=base.volume, symbol=base.symbol,
        open_price=reversed_prices, close_price=base.close_price, stop_loss=base.stop_loss,
        take_profit=base.take_profit, ticket=base.ticket, currency="USD",
        initial_balance=10_000.0, fingerprint="0" * 64, known_fields=base.known_fields,
    )
    assert _detector(config, "grid").detect(ts) is None


def test_grid_skips_when_fields_missing_or_history_short(config: MethodConfig) -> None:
    det = _detector(config, "grid")
    minimal = make_tradeset([1.0] * 50, known=frozenset({"open_time", "close_time", "profit"}))
    skipped = det.detect(minimal)
    assert skipped is not None
    assert skipped.message_key == "detector.skipped_missing_fields"
    short = det.detect(_grid_set(2))
    assert short is not None
    assert short.message_key == "detector.skipped_too_few"


# ---------------------------------------------------------------------------
# absence de stop, asymétrie, concentration, linéarité, période, durée
# ---------------------------------------------------------------------------


def test_no_stop_levels(config: MethodConfig) -> None:
    det = _detector(config, "no_stop")
    n = 100
    all_missing = make_tradeset(np.ones(n), stop_loss=np.full(n, np.nan))
    major = det.detect(all_missing)
    assert major is not None
    assert major.severity == Severity.MAJOR
    some = np.full(n, 1.09)
    some[:20] = np.nan
    minor = det.detect(make_tradeset(np.ones(n), stop_loss=some))
    assert minor is not None
    assert minor.severity == Severity.MINOR
    assert det.detect(make_tradeset(np.ones(n), stop_loss=np.full(n, 1.09))) is None
    unknown = det.detect(make_tradeset(np.ones(n)))
    assert unknown is not None
    assert unknown.severity == Severity.INFO


def test_payoff_asymmetry_levels(config: MethodConfig) -> None:
    det = _detector(config, "payoff_asymmetry")
    n = 200
    profits = np.full(n, 10.0)
    profits[:8] = -150.0  # 96 % de réussite, ratio 0,067
    blocking = det.detect(make_tradeset(profits))
    assert blocking is not None
    assert blocking.severity == Severity.BLOCKING
    profits = np.full(n, 10.0)
    profits[:24] = -60.0  # 88 % de réussite, ratio 0,167
    major = det.detect(make_tradeset(profits))
    assert major is not None
    assert major.severity == Severity.MAJOR
    balanced = np.where(np.arange(n) % 2 == 0, 30.0, -20.0)
    assert det.detect(make_tradeset(balanced)) is None
    assert det.detect(make_tradeset(np.ones(n))) is None  # sans perte : rien à comparer


def test_profit_concentration(config: MethodConfig) -> None:
    det = _detector(config, "profit_concentration")
    n = 100
    profits = np.full(n, 1.0)
    profits[0] = 500.0  # un seul trade porte 83 % du gain brut
    finding = det.detect(make_tradeset(profits))
    assert finding is not None
    assert finding.severity == Severity.MAJOR
    assert finding.param("top_share") == pytest.approx(504 / 599)  # 5 meilleurs sur 100
    spread = np.random.default_rng(3).gamma(4.0, 10.0, n)
    assert det.detect(make_tradeset(spread)) is None
    losing = -np.ones(n)
    assert det.detect(make_tradeset(losing)) is None
    fragile = np.full(n, -1.0)
    fragile[0] = 150.0  # net 51 ; sans le meilleur : −99
    weak = det.detect(make_tradeset(fragile))
    assert weak is not None
    assert weak.param("net_without_best") == pytest.approx(-99.0)


def test_equity_linearity(config: MethodConfig) -> None:
    det = _detector(config, "equity_linearity")
    straight = np.full(200, 10.0) + np.random.default_rng(1).normal(0, 0.5, 200)
    finding = det.detect(make_tradeset(straight))
    assert finding is not None
    assert finding.severity == Severity.MAJOR
    assert finding.number("r2") > 0.995
    noisy = np.random.default_rng(2).normal(5, 100, 200)
    assert det.detect(make_tradeset(noisy)) is None
    assert equity_linearity.r_squared(np.zeros(10)) != equity_linearity.r_squared(np.arange(10.0))
    assert np.isnan(equity_linearity.r_squared(np.ones(10)))
    assert np.isnan(equity_linearity.r_squared(np.array([1.0, 2.0])))
    short = det.detect(make_tradeset(np.ones(10)))
    assert short is not None
    assert short.message_key == "detector.skipped_too_few"
    # une droite décroissante (système perdant) n'est pas signalée ici
    assert det.detect(make_tradeset(-straight)) is None


def test_period_dependence(config: MethodConfig) -> None:
    det = _detector(config, "period_dependence")
    # 400 trades sur ~2 ans (pas 44 h) : profit uniquement au 1er trimestre 2021
    n = 400
    profits = np.full(n, -1.0)
    profits[:40] = 60.0
    ts = make_tradeset(profits, step_hours=44.0)
    finding = det.detect(ts)
    assert finding is not None
    assert finding.severity == Severity.MAJOR
    assert (finding.param("year"), finding.param("quarter")) == (2021, 1)
    assert finding.number("rest") < 0
    steady = make_tradeset(np.full(n, 5.0) + np.random.default_rng(1).normal(0, 20, n),
                           step_hours=44.0)
    assert det.detect(steady) is None
    short_span = det.detect(make_tradeset(np.ones(50), step_hours=1.0))
    assert short_span is not None
    assert short_span.message_key == "detector.skipped_too_few"
    assert det.detect(make_tradeset(np.full(n, -1.0), step_hours=44.0)) is None
    assert det.detect(make_tradeset([])) is None


def test_holding_time(config: MethodConfig) -> None:
    det = _detector(config, "holding_time")
    instant = make_tradeset(np.ones(100), hold_hours=0.0)
    blocking = det.detect(instant)
    assert blocking is not None
    assert blocking.severity == Severity.BLOCKING
    normal = det.detect(make_tradeset(np.ones(100), hold_hours=5.0))
    assert normal is None
    long = det.detect(make_tradeset(np.ones(100), step_hours=24.0, hold_hours=400 * 24.0))
    assert long is not None
    assert long.severity == Severity.MINOR
    assert det.detect(make_tradeset([])) is None


def test_every_detector_module_exposes_the_contract() -> None:
    for module in (martingale, grid, no_stop, profit_concentration, equity_linearity,
                   payoff_asymmetry, period_dependence, holding_time):
        assert isinstance(module.NAME, str)
        assert isinstance(module.NEEDS_PRICES, bool)
        assert callable(module.make)
