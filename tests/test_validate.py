# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validation : chaque défaut de données nomme sa ligne et sa colonne."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import numpy as np
import pytest

from qaudit.core.errors import DataError, SchemaError
from qaudit.core.models import Cell, Severity
from qaudit.core.validate import (
    build_tradeset,
    find_gaps,
    parse_datetime,
    parse_direction,
    parse_float,
    validate,
)
from tests.helpers import (
    MINIMAL_MAPPING,
    STANDARD_COLUMNS,
    STANDARD_MAPPING,
    make_table,
    make_tradeset,
    standard_row,
)

# ---------------------------------------------------------------------------
# schéma (porte E1)
# ---------------------------------------------------------------------------


def test_missing_required_field_raises_schema_error_listing_columns() -> None:
    table = make_table(("when", "pnl"), [["2021-01-01", 1.0]])
    with pytest.raises(SchemaError) as info:
        build_tradeset(table, {"open_time": "when", "profit": "pnl"})
    assert info.value.missing_fields == ("close_time",)
    assert info.value.seen_columns == ("when", "pnl")


def test_mapping_to_nonexistent_column_is_a_schema_error() -> None:
    table = make_table(("open_time", "close_time", "profit"), [["2021-01-01", "2021-01-02", 1.0]])
    mapping = dict(MINIMAL_MAPPING, volume="lots")
    with pytest.raises(SchemaError) as info:
        build_tradeset(table, mapping)
    assert info.value.missing_fields == ("volume",)


def test_empty_table_is_invalid_data() -> None:
    table = make_table(STANDARD_COLUMNS, [])
    with pytest.raises(DataError) as info:
        build_tradeset(table, STANDARD_MAPPING)
    assert info.value.key == "validate.no_rows"
    assert info.value.row is None


# ---------------------------------------------------------------------------
# types : la ligne et la colonne sont nommées
# ---------------------------------------------------------------------------


def test_bad_number_names_row_and_column() -> None:
    rows = [standard_row(0, 10.0), standard_row(1, 0.0)]
    rows[1][-1] = "abc"
    table = make_table(STANDARD_COLUMNS, rows)
    with pytest.raises(DataError) as info:
        build_tradeset(table, STANDARD_MAPPING)
    assert (info.value.key, info.value.row, info.value.column) == (
        "validate.bad_float", 3, "profit",
    )
    assert info.value.params["value"] == "abc"


def test_bad_datetime_names_row_and_column() -> None:
    rows = [standard_row(0, 1.0), standard_row(1, 1.0, open_time="hier")]
    table = make_table(STANDARD_COLUMNS, rows)
    with pytest.raises(DataError) as info:
        build_tradeset(table, STANDARD_MAPPING)
    assert (info.value.key, info.value.row, info.value.column) == (
        "validate.bad_datetime", 3, "open_time",
    )


def test_missing_required_value_names_row_and_column() -> None:
    rows = [standard_row(0, 1.0), standard_row(1, 1.0, close_time="")]
    table = make_table(STANDARD_COLUMNS, rows)
    with pytest.raises(DataError) as info:
        build_tradeset(table, STANDARD_MAPPING)
    assert (info.value.key, info.value.row, info.value.column) == (
        "validate.missing_value", 3, "close_time",
    )


def test_bad_direction_names_row_and_column() -> None:
    rows = [standard_row(0, 1.0, direction="hold")]
    table = make_table(STANDARD_COLUMNS, rows)
    with pytest.raises(DataError) as info:
        build_tradeset(table, STANDARD_MAPPING)
    assert (info.value.key, info.value.row, info.value.column) == (
        "validate.bad_direction", 2, "direction",
    )


def test_nonpositive_volume_names_row_and_column() -> None:
    rows = [standard_row(0, 1.0, volume=0.0)]
    table = make_table(STANDARD_COLUMNS, rows)
    with pytest.raises(DataError) as info:
        build_tradeset(table, STANDARD_MAPPING)
    assert (info.value.key, info.value.row, info.value.column) == (
        "validate.nonpositive", 2, "volume",
    )


def test_bad_ticket_names_row_and_column() -> None:
    row = standard_row(0, 1.0)
    row[0] = "12.5"
    table = make_table(STANDARD_COLUMNS, [row])
    with pytest.raises(DataError) as info:
        build_tradeset(table, STANDARD_MAPPING)
    assert (info.value.key, info.value.row, info.value.column) == ("validate.bad_int", 2, "ticket")


# ---------------------------------------------------------------------------
# chronologie, doublons, devise
# ---------------------------------------------------------------------------


def test_close_before_open_is_refused() -> None:
    rows = [
        standard_row(0, 1.0),
        standard_row(1, 1.0, open_time="2021-01-05T12:00:00", close_time="2021-01-05T11:59:59"),
    ]
    table = make_table(STANDARD_COLUMNS, rows)
    with pytest.raises(DataError) as info:
        build_tradeset(table, STANDARD_MAPPING)
    assert (info.value.key, info.value.row, info.value.column) == (
        "validate.close_before_open", 3, "close_time",
    )


def test_duplicate_ticket_names_both_rows() -> None:
    rows = [standard_row(0, 1.0), standard_row(1, 1.0), standard_row(2, 1.0)]
    rows[2][0] = 2  # même ticket que la 2e ligne
    table = make_table(STANDARD_COLUMNS, rows)
    with pytest.raises(DataError) as info:
        build_tradeset(table, STANDARD_MAPPING)
    assert (info.value.key, info.value.row, info.value.column) == (
        "validate.duplicate_ticket", 4, "ticket",
    )
    assert info.value.params["first_row"] == 3


def test_duplicate_row_without_ticket_is_refused() -> None:
    columns = ("open_time", "close_time", "profit")
    rows: list[list[Cell]] = [
        ["2021-01-04 09:00", "2021-01-04 10:00", 5.0],
        ["2021-01-04 11:00", "2021-01-04 12:00", -3.0],
        ["2021-01-04 09:00", "2021-01-04 10:00", 5.0],
    ]
    table = make_table(columns, rows)
    with pytest.raises(DataError) as info:
        build_tradeset(table, MINIMAL_MAPPING)
    assert (info.value.key, info.value.row) == ("validate.duplicate_row", 4)
    assert info.value.params["first_row"] == 2


def test_mixed_currency_is_refused_at_first_deviating_row() -> None:
    columns = (*STANDARD_COLUMNS, "currency")
    rows = [
        [*standard_row(0, 1.0), "USD"],
        [*standard_row(1, 1.0), "USD"],
        [*standard_row(2, 1.0), "EUR"],
    ]
    table = make_table(columns, rows)
    mapping = dict(STANDARD_MAPPING, currency="currency")
    with pytest.raises(DataError) as info:
        build_tradeset(table, mapping)
    assert (info.value.key, info.value.row, info.value.column) == (
        "validate.mixed_currency", 4, "currency",
    )
    assert info.value.params["expected"] == "USD"
    assert info.value.params["actual"] == "EUR"


def test_currency_resolution_order() -> None:
    table = make_table(STANDARD_COLUMNS, [standard_row(0, 1.0)], currency="GBP")
    assert build_tradeset(table, STANDARD_MAPPING).currency == "GBP"
    assert build_tradeset(table, STANDARD_MAPPING, currency="CHF").currency == "CHF"
    plain = make_table(STANDARD_COLUMNS, [standard_row(0, 1.0)])
    assert build_tradeset(plain, STANDARD_MAPPING).currency == "?"


def test_currency_from_header_or_override_is_a_known_field() -> None:
    """Une devise lue dans l'en-tête du rapport (MT5, testeur) ou déclarée n'est
    pas « absente de la source » : le constat missing_optional ne la cite pas."""
    header = make_table(STANDARD_COLUMNS, [standard_row(0, 1.0)], currency="GBP")
    assert build_tradeset(header, STANDARD_MAPPING).has("currency")
    plain = make_table(STANDARD_COLUMNS, [standard_row(0, 1.0)])
    assert build_tradeset(plain, STANDARD_MAPPING, currency="CHF").has("currency")
    assert not build_tradeset(plain, STANDARD_MAPPING).has("currency")


def test_bad_initial_balance_is_refused() -> None:
    table = make_table(STANDARD_COLUMNS, [standard_row(0, 1.0)])
    with pytest.raises(DataError) as info:
        build_tradeset(table, STANDARD_MAPPING, initial_balance=-5.0)
    assert info.value.key == "validate.bad_initial_balance"


# ---------------------------------------------------------------------------
# canonisation
# ---------------------------------------------------------------------------


def test_unsorted_input_is_resorted_by_close_time_with_an_info_finding() -> None:
    rows = [standard_row(2, 3.0), standard_row(0, 1.0), standard_row(1, 2.0)]
    table = make_table(STANDARD_COLUMNS, rows)
    result = validate(table, STANDARD_MAPPING, max_gap_days=30)
    np.testing.assert_array_equal(result.tradeset.profit, [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(result.tradeset.ticket, [1, 2, 3])
    codes = {f.code for f in result.findings}
    assert "resorted" in codes


def test_sorted_input_has_no_resorted_finding() -> None:
    rows = [standard_row(0, 1.0), standard_row(1, 2.0)]
    table = make_table(STANDARD_COLUMNS, rows)
    result = validate(table, STANDARD_MAPPING, max_gap_days=30)
    assert "resorted" not in {f.code for f in result.findings}


def test_commission_and_swap_are_netted_into_profit() -> None:
    columns = (*STANDARD_COLUMNS, "commission", "swap")
    rows = [[*standard_row(0, 10.0), -0.7, -0.3], [*standard_row(1, -5.0), -0.7, ""]]
    table = make_table(columns, rows)
    mapping = dict(STANDARD_MAPPING, commission="commission", swap="swap")
    ts = build_tradeset(table, mapping)
    np.testing.assert_allclose(ts.profit, [9.0, -5.7])
    assert ts.has("commission")


def test_zero_stop_loss_means_absent() -> None:
    rows = [standard_row(0, 1.0, sl=0), standard_row(1, 1.0, sl=1.09)]
    table = make_table(STANDARD_COLUMNS, rows)
    ts = build_tradeset(table, STANDARD_MAPPING)
    assert np.isnan(ts.stop_loss[0])
    assert ts.stop_loss[1] == pytest.approx(1.09)


def test_known_fields_reflect_the_mapping() -> None:
    table = make_table(("open_time", "close_time", "profit"), [["2021-01-01", "2021-01-02", 1.0]])
    ts = build_tradeset(table, MINIMAL_MAPPING)
    assert ts.known_fields == frozenset({"open_time", "close_time", "profit"})
    assert np.isnan(ts.volume[0])
    assert ts.direction[0] == 0
    assert ts.symbol[0] == "?"
    assert ts.ticket[0] == 0


def test_missing_optional_fields_are_reported_as_info() -> None:
    table = make_table(("open_time", "close_time", "profit"), [["2021-01-01", "2021-01-02", 1.0]])
    result = validate(table, MINIMAL_MAPPING, max_gap_days=30)
    by_code = {f.code: f for f in result.findings}
    assert by_code["missing_optional"].severity == Severity.INFO
    assert "volume" in str(by_code["missing_optional"].param("fields"))
    assert by_code["no_initial_balance"].severity == Severity.MINOR


# ---------------------------------------------------------------------------
# trous
# ---------------------------------------------------------------------------


def test_gap_finding_reports_count_and_longest_gap() -> None:
    regular = make_tradeset([1.0, 1.0, 1.0, 1.0], step_hours=24.0)
    assert find_gaps(regular, max_gap_days=2.0) is None
    columns = ("open_time", "close_time", "profit")
    rows: list[list[Cell]] = [
        ["2021-01-04 09:00", "2021-01-04 10:00", 1.0],
        ["2021-01-14 09:00", "2021-01-14 10:00", 1.0],  # trou de 10 j
        ["2021-01-15 09:00", "2021-01-15 10:00", 1.0],
        ["2021-02-04 09:00", "2021-02-04 10:00", 1.0],  # trou de 20 j
    ]
    ts = build_tradeset(make_table(columns, rows), MINIMAL_MAPPING)
    finding = find_gaps(ts, max_gap_days=5.0)
    assert finding is not None
    assert finding.param("count") == 2
    assert finding.param("days") == pytest.approx(20.0)
    assert finding.param("start") == "2021-01-15T10:00:00"
    assert finding.param("max_gap_days") == 5.0


def test_gap_detected_on_real_gap() -> None:
    columns = ("open_time", "close_time", "profit")
    rows: list[list[Cell]] = [
        ["2021-01-04 09:00", "2021-01-04 10:00", 1.0],
        ["2021-01-05 09:00", "2021-01-05 10:00", 1.0],
        ["2021-03-05 09:00", "2021-03-05 10:00", 1.0],
        ["2021-03-06 09:00", "2021-03-06 10:00", 1.0],
    ]
    table = make_table(columns, rows)
    result = validate(table, MINIMAL_MAPPING, max_gap_days=30)
    gap = next(f for f in result.findings if f.code == "gap")
    assert gap.severity == Severity.MINOR
    assert gap.param("count") == 1
    assert gap.param("days") == pytest.approx(59.0)
    assert gap.param("start") == "2021-01-05T10:00:00"
    assert gap.param("end") == "2021-03-05T10:00:00"


def test_single_trade_has_no_gap() -> None:
    assert find_gaps(make_tradeset([1.0]), max_gap_days=1.0) is None


# ---------------------------------------------------------------------------
# analyseurs de cellules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 234,56", 1234.56),
        ("1,234.56", 1234.56),
        ("1.234,56", 1234.56),
        ("-1,5", -1.5),
        ("  42  ", 42.0),
        (7, 7.0),
        (2.5, 2.5),
    ],
)
def test_parse_float_accepts_european_and_anglo_formats(text: Cell, expected: float) -> None:
    assert parse_float(text) == pytest.approx(expected)


@pytest.mark.parametrize("bad", ["abc", None, True, "1.2.3,4,5"])
def test_parse_float_rejects_garbage(bad: Cell) -> None:
    with pytest.raises(ValueError, match=r"."):
        parse_float(bad)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2021.01.02 03:04:05", "2021-01-02T03:04:05"),
        ("2021.01.02 03:04", "2021-01-02T03:04:00"),
        ("2021-01-02T03:04:05", "2021-01-02T03:04:05"),
        ("2021-01-02 03:04:05.250", "2021-01-02T03:04:05.250"),
        ("2021-01-02T03:04:05Z", "2021-01-02T03:04:05"),
        ("2021-01-02T05:04:05+02:00", "2021-01-02T03:04:05"),
        ("02/01/2021 03:04:05", "2021-01-02T03:04:05"),
        ("1609556645", "2021-01-02T03:04:05"),
        (1609556645, "2021-01-02T03:04:05"),
        (1609556645000.0, "2021-01-02T03:04:05"),
        (np.datetime64("2021-01-02T03:04:05"), "2021-01-02T03:04:05"),
        (datetime(2021, 1, 2, 3, 4, 5), "2021-01-02T03:04:05"),
        (datetime(2021, 1, 2, 4, 4, 5, tzinfo=timezone(timedelta(hours=1))), "2021-01-02T03:04:05"),
        (datetime(2021, 1, 2, 3, 4, 5, tzinfo=UTC), "2021-01-02T03:04:05"),
    ],
)
def test_parse_datetime_formats(text: Cell, expected: str) -> None:
    assert parse_datetime(text) == np.datetime64(expected, "ns")


@pytest.mark.parametrize("bad", ["demain", "", None, True, "2021-13-45"])
def test_parse_datetime_rejects_garbage(bad: Cell) -> None:
    with pytest.raises(ValueError, match=r"."):
        parse_datetime(bad)


@pytest.mark.parametrize(
    ("token", "expected"),
    [("buy", 1), ("BUY", 1), ("Long", 1), ("achat", 1), ("+1", 1), (1, 1), (1.0, 1),
     ("sell", -1), ("short", -1), ("vente", -1), ("-1", -1), (-1, -1), ("S", -1)],
)
def test_parse_direction_tokens(token: Cell, expected: int) -> None:
    assert parse_direction(token) == expected


@pytest.mark.parametrize("bad", ["hold", 0, 2, True, None, ""])
def test_parse_direction_rejects_ambiguous_tokens(bad: Cell) -> None:
    with pytest.raises(ValueError, match=r"."):
        parse_direction(bad)
