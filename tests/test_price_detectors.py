# SPDX-License-Identifier: AGPL-3.0-or-later
"""Détecteurs à données de prix : géométrie du stop, look-ahead, réalisme
d'exécution — sur des barres synthétiques construites à la main."""

from __future__ import annotations

import numpy as np
import pytest

from qaudit.core.config import MethodConfig
from qaudit.core.detectors.base import Detector
from qaudit.core.detectors.prices import align, path_extremes
from qaudit.core.detectors.registry import build_detectors, run_detectors
from qaudit.core.models import PriceSeries, Severity, TradeSet
from qaudit.io.method import load_method
from tests.helpers import FAKE_FINGERPRINT, make_tradeset

HOUR = np.timedelta64(3_600_000_000_000, "ns")
T0 = np.datetime64("2021-01-04T00:00:00", "ns")


@pytest.fixture(scope="module")
def config() -> MethodConfig:
    return load_method()


def _detector(config: MethodConfig, name: str) -> Detector:
    return next(d for d in build_detectors(config) if d.name == name)


def flat_bars(n: int, low: float = 1.0990, high: float = 1.1010) -> PriceSeries:
    """Barres horaires identiques [low, high], ouverture/clôture au milieu."""
    mid = (low + high) / 2
    return PriceSeries(
        T0 + np.arange(n) * HOUR, np.full(n, mid), np.full(n, high), np.full(n, low),
        np.full(n, mid), "EURUSD", FAKE_FINGERPRINT,
    )


def trades_at(n: int, open_price: float, *, direction: int = 1, profit: float = 10.0,
              stop_loss: float | None = None, close_price: float | None = None,
              hold_hours: float = 1.0) -> TradeSet:
    """``n`` trades ouverts un par heure à partir de T0 + 1 h."""
    return make_tradeset(
        np.full(n, profit), start="2021-01-04T01:00:00", step_hours=1.0, hold_hours=hold_hours,
        open_price=np.full(n, open_price),
        close_price=np.full(n, close_price if close_price is not None else open_price),
        direction=np.full(n, direction),
        stop_loss=None if stop_loss is None else np.full(n, stop_loss),
    )


# ---------------------------------------------------------------------------
# alignement
# ---------------------------------------------------------------------------


def test_alignment_and_path_extremes() -> None:
    prices = flat_bars(10)
    ts = make_tradeset([1.0, 1.0], start="2021-01-04T01:30:00", step_hours=3.0, hold_hours=2.0)
    alignment = align(ts, prices)
    assert alignment.open_idx.tolist() == [1, 4]
    assert alignment.close_idx.tolist() == [3, 6]
    assert alignment.share == 1.0
    lows, highs = path_extremes(prices, alignment.open_idx, alignment.close_idx, alignment.aligned)
    assert lows.tolist() == [1.0990, 1.0990]
    assert highs.tolist() == [1.1010, 1.1010]
    far = make_tradeset([1.0], start="2022-01-01T00:00:00")
    assert align(far, prices).share == 0.0


# ---------------------------------------------------------------------------
# réalisme d'exécution
# ---------------------------------------------------------------------------


def test_execution_realism_levels(config: MethodConfig) -> None:
    det = _detector(config, "execution_realism")
    prices = flat_bars(200)
    inside = trades_at(100, 1.1000)
    assert det.detect(inside, prices) is None
    # 30 % des ouvertures hors de la barre (bien au-delà de 3 pb) → bloquant
    bad = np.full(100, 1.1000)
    bad[:30] = 1.1100
    ts = make_tradeset(np.full(100, 10.0), start="2021-01-04T01:00:00", step_hours=1.0,
                       hold_hours=1.0, open_price=bad, close_price=np.full(100, 1.1000))
    finding = det.detect(ts, prices)
    assert finding is not None
    assert finding.severity == Severity.BLOCKING
    assert finding.number("share") == pytest.approx(0.30)
    bad[:3] = 1.1100
    bad[3:] = 1.1000
    ts = make_tradeset(np.full(100, 10.0), start="2021-01-04T01:00:00", step_hours=1.0,
                       hold_hours=1.0, open_price=bad, close_price=np.full(100, 1.1000))
    minor = det.detect(ts, prices)
    assert minor is not None
    assert minor.severity == Severity.MINOR


def test_price_detectors_skip_when_unaligned_or_fields_missing(config: MethodConfig) -> None:
    prices = flat_bars(10)
    far = trades_at(50, 1.1000).with_profit(np.full(50, 5.0))
    far_ts = make_tradeset(np.full(50, 5.0), start="2023-01-01T00:00:00",
                           open_price=np.full(50, 1.1), close_price=np.full(50, 1.1))
    for name in ("execution_realism", "lookahead", "stop_geometry"):
        finding = _detector(config, name).detect(far_ts, prices)
        assert finding is not None
        assert finding.severity == Severity.INFO
    assert far.n == 50
    minimal = make_tradeset(
        np.full(50, 5.0), known=frozenset({"open_time", "close_time", "profit"})
    )
    for name in ("execution_realism", "lookahead", "stop_geometry"):
        finding = _detector(config, name).detect(minimal, prices)
        assert finding is not None
        assert finding.message_key == "detector.skipped_missing_fields"


# ---------------------------------------------------------------------------
# look-ahead
# ---------------------------------------------------------------------------


def test_lookahead_flags_entries_at_the_exact_extreme(config: MethodConfig) -> None:
    det = _detector(config, "lookahead")
    prices = flat_bars(200)
    cheating = trades_at(100, 1.0990)  # achats au plus bas exact de la barre
    finding = det.detect(cheating, prices)
    assert finding is not None
    assert finding.severity == Severity.BLOCKING
    assert finding.number("share") == 1.0
    assert finding.number("p_value") < 1e-6
    honest = trades_at(100, 1.1000)  # au milieu de la barre
    assert det.detect(honest, prices) is None
    sells = trades_at(100, 1.1010, direction=-1)  # ventes au plus haut exact
    sell_finding = det.detect(sells, prices)
    assert sell_finding is not None
    assert sell_finding.severity == Severity.BLOCKING


def test_lookahead_tolerates_a_plausible_rate(config: MethodConfig) -> None:
    det = _detector(config, "lookahead")
    prices = flat_bars(200)
    # fourchette 20 pips, tick 1 pb ≈ 0,11 pip → attendu ≈ 0,55 % ; 4 % observé
    # dépasse min_share (5 %) ? non → aucun constat même si p est petit
    open_price = np.full(100, 1.1000)
    open_price[:4] = 1.0990
    ts = make_tradeset(np.full(100, 10.0), start="2021-01-04T01:00:00", step_hours=1.0,
                       hold_hours=1.0, open_price=open_price, close_price=np.full(100, 1.1),
                       direction=np.ones(100, dtype=np.int64))
    assert det.detect(ts, prices) is None


# ---------------------------------------------------------------------------
# géométrie du stop
# ---------------------------------------------------------------------------


def stop_prices(n: int, dips: np.ndarray) -> PriceSeries:
    """Barres horaires ; chaque trade k (ouvert à T0 + 1 h + k h, tenu 1 h) voit sa
    barre de clôture creuser jusqu'à ``1.1000 − dips[k]``."""
    total = n + 4
    low = np.full(total, 1.0995)
    high = np.full(total, 1.1005)
    for k in range(n):
        low[k + 2] = min(low[k + 2], 1.1000 - dips[k])
    return PriceSeries(
        T0 + np.arange(total) * HOUR, np.full(total, 1.1), high, low, np.full(total, 1.1),
        "EURUSD", FAKE_FINGERPRINT,
    )


def test_stop_geometry_measures_collapse(config: MethodConfig) -> None:
    det = _detector(config, "stop_geometry")
    n = 60
    # stop à 50 pips ; les gagnants creusent jusqu'à 44 pips : un stop 10 % plus
    # serré (45 pips) n'est pas touché, un stop 20 % plus serré (40 pips) l'est
    prices = stop_prices(n, np.full(n, 0.0044))
    ts = trades_at(n, 1.1000, profit=10.0, stop_loss=1.0950)
    finding = det.detect(ts, prices)
    assert finding is not None
    assert finding.severity == Severity.INFO
    assert finding.number("collapse_10") == 0.0
    assert finding.number("collapse_20") == 1.0
    assert finding.number("collapse_30") == 1.0
    # creux à 46 pips : le stop à 45 pips est touché par tous les gagnants → fragile
    finding2 = det.detect(ts, stop_prices(n, np.full(n, 0.0046)))
    assert finding2 is not None
    assert finding2.number("collapse_10") == 1.0
    assert finding2.severity == Severity.MAJOR


def test_stop_geometry_survival_of_losers(config: MethodConfig) -> None:
    det = _detector(config, "stop_geometry")
    n = 60
    # perdants stoppés à 50 pips exactement ; un stop 10 % plus large (55) aurait survécu
    prices = stop_prices(n, np.full(n, 0.0050))
    ts = trades_at(n, 1.1000, profit=-50.0, stop_loss=1.0950, close_price=1.0950)
    finding = det.detect(ts, prices)
    assert finding is not None
    assert finding.number("survived_10") == 1.0
    assert finding.number("collapse_10") == 0.0  # aucun gagnant
    assert finding.number("winners") == 0


def test_price_detectors_run_through_the_registry(config: MethodConfig) -> None:
    prices = flat_bars(200)
    ts = trades_at(100, 1.1000, stop_loss=1.0950)
    findings = run_detectors(build_detectors(config), ts, prices)
    codes = {f.code for f in findings}
    assert "stop_geometry" in codes  # toujours publié (info)
    assert not any(f.message_key == "detector.skipped_no_prices" for f in findings)
