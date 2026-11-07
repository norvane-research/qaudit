# SPDX-License-Identifier: AGPL-3.0-or-later
"""Régimes : terciles de volatilité, ATR, classificateur injectable, trimestres."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pytest

from qaudit.core.models import IntArray, PriceSeries, TradeSet
from qaudit.core.regimes import (
    UNKNOWN,
    AtrTerciles,
    VolatilityTerciles,
    analyse,
    atr,
    bar_index,
    quarterly_stats,
    rolling_std,
    terciles,
)
from tests.helpers import FAKE_FINGERPRINT, make_tradeset


def hourly_prices(n: int, start: str = "2021-01-04T00:00:00", seed: int = 1) -> PriceSeries:
    rng = np.random.default_rng(seed)
    close = 1.1 + np.cumsum(rng.normal(0, 0.0004, n))
    open_ = np.concatenate(([1.1], close[:-1]))
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.0002, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.0002, n))
    times = np.datetime64(start, "ns") + np.arange(n) * np.timedelta64(3_600_000_000_000, "ns")
    return PriceSeries(times, open_, high, low, close, "EURUSD", FAKE_FINGERPRINT)


def test_terciles_split_values_in_three_groups() -> None:
    values = np.arange(30, dtype=float)
    labels = terciles(values)
    assert np.bincount(labels).tolist() == [10, 10, 10]
    assert labels[0] == 0
    assert labels[-1] == 2
    with_nan = np.array([1.0, np.nan, 3.0, 2.0, 5.0, 4.0])
    labels = terciles(with_nan)
    assert labels[1] == UNKNOWN
    assert terciles(np.array([1.0, np.nan])).tolist() == [UNKNOWN, UNKNOWN]


def test_rolling_std_uses_only_previous_values() -> None:
    x = np.array([1.0, 3.0, 5.0, 100.0, 7.0])
    out = rolling_std(x, window=3)
    assert math.isnan(out[0])
    assert math.isnan(out[1])
    assert out[2] == pytest.approx(np.std([1.0, 3.0]))
    assert out[3] == pytest.approx(np.std([1.0, 3.0, 5.0]))
    assert out[4] == pytest.approx(np.std([3.0, 5.0, 100.0]))  # la valeur courante est exclue


def test_volatility_terciles_report_names_the_method() -> None:
    rng = np.random.default_rng(3)
    profits = np.concatenate((rng.normal(0, 10, 100), rng.normal(0, 100, 100)))
    ts = make_tradeset(profits)
    report = analyse(ts, VolatilityTerciles(window=20))
    assert report.method == "volatility_terciles"
    assert [s.label for s in report.stats] == ["low", "mid", "high"]
    assert sum(s.n for s in report.stats) + report.n_unclassified == 200
    assert report.n_unclassified == 2  # les deux premiers trades n'ont pas d'historique
    # les trades de forte volatilité sont concentrés en seconde moitié
    labels = VolatilityTerciles(window=20).classify(ts, None)
    # après la fenêtre de transition, plus aucun trade de la seconde moitié n'est
    # « volatilité basse », et la première moitié l'est presque entièrement
    assert np.mean(labels[130:] >= 1) > 0.95
    assert np.mean(labels[20:100] == 0) >= 0.75


def test_atr_matches_manual_computation() -> None:
    ps = hourly_prices(10)
    values = atr(ps, period=3)
    assert all(math.isnan(v) for v in values[:3])
    prev_close = np.concatenate(([ps.close[0]], ps.close[:-1]))
    tr = np.maximum(ps.high - ps.low,
                    np.maximum(abs(ps.high - prev_close), abs(ps.low - prev_close)))
    assert values[3] == pytest.approx(np.mean(tr[1:4]))
    assert values[9] == pytest.approx(np.mean(tr[7:10]))
    assert all(math.isnan(v) for v in atr(hourly_prices(1), 3))


def test_bar_index_alignment_rules() -> None:
    ps = hourly_prices(5)  # barres 00:00 … 04:00 (la dernière couvre 04:00-05:00)
    times = np.array(
        ["2021-01-03T22:30", "2021-01-03T23:30", "2021-01-04T00:00", "2021-01-04T01:30",
         "2021-01-04T04:59", "2021-01-04T05:30", "2021-01-04T06:00"],
        dtype="datetime64[ns]",
    )
    # tolérance d'une barre : 23:30 → barre 0 ; 05:30 → barre 4 ; 22:30 et 06:00 hors série
    assert bar_index(ps, times).tolist() == [UNKNOWN, 0, 0, 1, 4, 4, UNKNOWN]


def test_atr_terciles_classify_trades_by_preceding_bar() -> None:
    ps = hourly_prices(500)
    ts = make_tradeset(np.random.default_rng(1).normal(5, 50, 200), start="2021-01-05T00:00:00",
                       step_hours=2.0, hold_hours=1.0)
    report = analyse(ts, AtrTerciles(period=14), ps)
    assert report.method == "atr_terciles"
    assert sum(s.n for s in report.stats) + report.n_unclassified == 200
    assert report.n_unclassified == 0
    without_prices = analyse(ts, AtrTerciles(period=14), None)
    assert without_prices.n_unclassified == 200


def test_external_classifier_is_injectable() -> None:
    @dataclass(frozen=True)
    class ByDirection:
        name: str = "by_direction"
        labels: tuple[str, ...] = ("short", "long")

        def classify(self, ts: TradeSet, prices: PriceSeries | None) -> IntArray:
            return np.where(ts.direction > 0, 1, 0).astype(np.int64)

    ts = make_tradeset([10.0, -5.0, 20.0, -1.0], direction=np.array([1, -1, 1, -1]))
    report = analyse(ts, ByDirection())
    assert report.method == "by_direction"
    long = next(s for s in report.stats if s.label == "long")
    assert (long.n, long.net_profit, long.win_rate) == (2, 30.0, 1.0)
    short = next(s for s in report.stats if s.label == "short")
    assert short.net_profit == -6.0
    assert short.share_of_net == pytest.approx(-6 / 24)


def test_empty_regime_stats_are_defined() -> None:
    report = analyse(make_tradeset([]), VolatilityTerciles(window=5))
    assert all(s.n == 0 for s in report.stats)
    assert all(math.isnan(s.profit_factor) for s in report.stats)


def test_quarterly_stats_without_strftime() -> None:
    # clôtures : 2021-01-04, 02-18, 04-04, 05-19 → T1, T1, T2, T2
    ts = make_tradeset([10.0, -5.0, 20.0, 30.0], step_hours=24 * 45)
    stats = quarterly_stats(ts)
    assert [(s.year, s.quarter) for s in stats] == [(2021, 1), (2021, 2)]
    assert [s.n for s in stats] == [2, 2]
    assert stats[0].net_profit == 5.0
    assert stats[0].profit_factor == 2.0
    assert quarterly_stats(make_tradeset([])) == ()
