# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèles : construction, cohérence des longueurs, dérivés purs."""

from __future__ import annotations

import numpy as np
import pytest

from qaudit.core.errors import InternalError
from qaudit.core.models import (
    Condition,
    Decision,
    Finding,
    PriceSeries,
    RawTable,
    Severity,
    TradeSet,
    Verdict,
    time_to_iso,
)
from tests.helpers import FAKE_FINGERPRINT, make_tradeset


def test_length_mismatch_is_an_internal_error() -> None:
    with pytest.raises(InternalError) as info:
        TradeSet(
            open_time=np.array(["2021-01-01T00:00"], dtype="datetime64[ns]"),
            close_time=np.array(["2021-01-01T01:00"], dtype="datetime64[ns]"),
            profit=np.array([1.0, 2.0]),
            direction=np.array([1, 1], dtype=np.int8),
            volume=np.array([0.1, 0.1]),
            symbol=np.array(["A", "A"]),
            open_price=np.array([1.0, 1.0]),
            close_price=np.array([1.0, 1.0]),
            stop_loss=np.array([np.nan, np.nan]),
            take_profit=np.array([np.nan, np.nan]),
            ticket=np.array([1, 2]),
            currency="USD",
            initial_balance=1000.0,
            fingerprint=FAKE_FINGERPRINT,
            known_fields=frozenset(),
        )
    assert info.value.key == "internal.length_mismatch"
    assert info.value.params["field"] == "open_time"


def test_two_dimensional_input_is_refused() -> None:
    with pytest.raises(InternalError) as info:
        TradeSet(
            open_time=np.array(["2021-01-01T00:00"], dtype="datetime64[ns]"),
            close_time=np.array(["2021-01-01T01:00"], dtype="datetime64[ns]"),
            profit=np.ones((1, 1)),
            direction=np.array([1], dtype=np.int8),
            volume=np.array([0.1]),
            symbol=np.array(["A"]),
            open_price=np.array([1.0]),
            close_price=np.array([1.0]),
            stop_loss=np.array([np.nan]),
            take_profit=np.array([np.nan]),
            ticket=np.array([1]),
            currency="USD",
            initial_balance=1000.0,
            fingerprint=FAKE_FINGERPRINT,
            known_fields=frozenset(),
        )
    assert info.value.key == "internal.array_ndim"


def test_nonpositive_initial_balance_is_refused() -> None:
    with pytest.raises(InternalError):
        make_tradeset([1.0], initial_balance=0.0)


def test_span_days_from_first_open_to_last_close() -> None:
    ts = make_tradeset([1.0, 1.0, 1.0], step_hours=24.0, hold_hours=12.0)
    # ouvertures à t0, t0+24h, t0+48h ; dernière clôture à t0+60h
    assert ts.span_days == pytest.approx(60 / 24)
    assert ts.span_years == pytest.approx(60 / 24 / 365.25)


def test_empty_tradeset_has_zero_span_and_length() -> None:
    ts = make_tradeset([])
    assert ts.n == 0
    assert len(ts) == 0
    assert ts.span_days == 0.0
    assert ts.equity.size == 0


def test_equity_and_cum_profit() -> None:
    ts = make_tradeset([100.0, -50.0, 25.0], initial_balance=1000.0)
    np.testing.assert_allclose(ts.cum_profit, [100.0, 50.0, 75.0])
    np.testing.assert_allclose(ts.equity, [1100.0, 1050.0, 1075.0])


def test_equity_requires_initial_balance() -> None:
    ts = make_tradeset([1.0], initial_balance=None)
    with pytest.raises(InternalError) as info:
        _ = ts.equity
    assert info.value.key == "internal.no_initial_balance"


def test_take_returns_new_object_and_keeps_original() -> None:
    ts = make_tradeset([1.0, -2.0, 3.0, -4.0])
    sub = ts.take(np.array([True, False, True, False]))
    assert sub.n == 2
    np.testing.assert_array_equal(sub.profit, [1.0, 3.0])
    np.testing.assert_array_equal(sub.ticket, [1, 3])
    assert ts.n == 4
    sliced = ts.take(slice(1, 3))
    np.testing.assert_array_equal(sliced.profit, [-2.0, 3.0])


def test_with_profit_keeps_everything_else() -> None:
    ts = make_tradeset([1.0, 2.0])
    other = ts.with_profit(np.array([5.0, 6.0]))
    np.testing.assert_array_equal(other.profit, [5.0, 6.0])
    np.testing.assert_array_equal(other.open_time, ts.open_time)
    np.testing.assert_array_equal(ts.profit, [1.0, 2.0])


def test_has_reports_known_fields() -> None:
    ts = make_tradeset([1.0], known=frozenset({"open_time", "close_time", "profit"}))
    assert ts.has("profit")
    assert not ts.has("volume")


def test_finding_params_are_sorted_and_accessible() -> None:
    f = Finding.make("code", Severity.MAJOR, "detector.x", "detector.x", zeta=1, alpha=2.5)
    assert f.params == (("alpha", 2.5), ("zeta", 1))
    assert f.param("alpha") == 2.5
    assert f.has_param("zeta")
    assert not f.has_param("nope")
    with pytest.raises(InternalError):
        f.param("nope")


def test_condition_factory() -> None:
    c = Condition.make("c", "condition.k", n=3)
    assert c.params == (("n", 3),)


def test_verdict_counts_by_severity() -> None:
    findings = (
        Finding.make("a", Severity.MAJOR, "k", "s"),
        Finding.make("b", Severity.MAJOR, "k", "s"),
        Finding.make("c", Severity.BLOCKING, "k", "s"),
        Finding.make("d", Severity.INFO, "k", "s"),
    )
    v = Verdict(Decision.NO_GO, (), findings, (), False, "1.0")
    assert v.major_count == 2
    assert v.blocking_count == 1
    assert v.count(Severity.MINOR) == 0


def test_severity_is_ordered() -> None:
    assert Severity.INFO < Severity.MINOR < Severity.MAJOR < Severity.BLOCKING


def test_priceseries_rejects_unsorted_time() -> None:
    with pytest.raises(InternalError) as info:
        PriceSeries(
            time=np.array(["2021-01-01T01:00", "2021-01-01T00:00"], dtype="datetime64[ns]"),
            open=np.array([1.0, 1.0]),
            high=np.array([1.0, 1.0]),
            low=np.array([1.0, 1.0]),
            close=np.array([1.0, 1.0]),
            symbol="X",
            fingerprint=FAKE_FINGERPRINT,
        )
    assert info.value.key == "internal.prices_unsorted"


def test_priceseries_bar_seconds_is_the_median_step() -> None:
    times = np.array(
        ["2021-01-01T00:00", "2021-01-01T00:05", "2021-01-01T00:10", "2021-01-01T01:00"],
        dtype="datetime64[ns]",
    )
    ps = PriceSeries(times, np.ones(4), np.ones(4), np.ones(4), np.ones(4), "X", FAKE_FINGERPRINT)
    assert ps.bar_seconds == 300.0
    assert ps.n == 4
    single = PriceSeries(times[:1], np.ones(1), np.ones(1), np.ones(1), np.ones(1), "X", "0")
    assert single.bar_seconds == 0.0


def test_rawtable_checks_row_width_and_line_numbers() -> None:
    with pytest.raises(InternalError) as info:
        RawTable(("a", "b"), ((1, 2), (3,)), (2, 3), FAKE_FINGERPRINT, "test")
    assert info.value.key == "internal.row_width"
    with pytest.raises(InternalError):
        RawTable(("a",), ((1,),), (2, 3), FAKE_FINGERPRINT, "test")
    table = RawTable(("a",), ((1,), (2,)), (2, 3), FAKE_FINGERPRINT, "test")
    assert table.n == 2


def test_time_to_iso_is_second_precision_without_zone() -> None:
    t = np.datetime64("2021-03-04T05:06:07.123456789", "ns")
    assert time_to_iso(t) == "2021-03-04T05:06:07"
