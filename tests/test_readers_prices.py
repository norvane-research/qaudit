# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lecteur de série OHLC : synonymes, cohérence des barres, erreurs nommées."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from qaudit.core.errors import DataError, SchemaError
from qaudit.io.readers.csv_generic import parse_csv_text
from qaudit.io.readers.prices import infer_price_mapping, read_prices, table_to_prices

FIXTURES = Path(__file__).resolve().parent / "fixtures"
HEADER = "time,open,high,low,close\n"


def test_reads_the_witness_price_series() -> None:
    ps = read_prices(FIXTURES / "healthy_witness_prices.csv", "EURUSD")
    assert ps.symbol == "EURUSD"
    assert ps.n > 20_000
    assert ps.bar_seconds == 3600.0
    assert np.all(np.diff(ps.time.astype(np.int64)) > 0)
    assert np.all(ps.high >= ps.low)
    assert len(ps.fingerprint) == 64
    named = read_prices(FIXTURES / "healthy_witness_prices.csv")
    assert named.symbol == "healthy_witness_prices"


def test_synonyms_and_separate_date_time_columns() -> None:
    text = (
        "DATE;TIME;OPEN;HIGH;LOW;CLOSE;VOL\n"
        "2021.01.04;10:00;1,1;1,2;1,0;1,15;100\n"
        "2021.01.04;11:00;1,15;1,3;1,1;1,2;120\n"
    )
    table = parse_csv_text(text, "0" * 64)
    assert infer_price_mapping(table.columns) == {
        "time": "TIME", "open": "OPEN", "high": "HIGH", "low": "LOW", "close": "CLOSE",
    }
    ps = table_to_prices(table, "X")
    assert ps.n == 2
    assert str(ps.time[0])[:16] == "2021-01-04T10:00"
    assert ps.close.tolist() == [1.15, 1.2]


def test_missing_column_is_a_schema_error() -> None:
    table = parse_csv_text("time,open,high,close\n2021-01-04 10:00,1,2,1.5\n", "0" * 64)
    with pytest.raises(SchemaError) as info:
        table_to_prices(table, "X")
    assert info.value.missing_fields == ("low",)


def test_inconsistent_bar_names_the_row() -> None:
    text = HEADER + "2021-01-04 10:00,1.1,1.2,1.0,1.15\n2021-01-04 11:00,1.1,1.0,1.2,1.15\n"
    with pytest.raises(DataError) as info:
        table_to_prices(parse_csv_text(text, "0" * 64), "X")
    assert (info.value.key, info.value.row, info.value.column) == (
        "prices.inconsistent_bar", 3, "high",
    )


def test_duplicate_bar_and_bad_values_are_named() -> None:
    dup = HEADER + "2021-01-04 10:00,1.1,1.2,1.0,1.15\n2021-01-04 10:00,1.1,1.2,1.0,1.15\n"
    with pytest.raises(DataError) as info:
        table_to_prices(parse_csv_text(dup, "0" * 64), "X")
    assert info.value.key == "prices.duplicate_bar"
    assert info.value.row == 3
    bad = HEADER + "2021-01-04 10:00,1.1,abc,1.0,1.15\n"
    with pytest.raises(DataError) as info2:
        table_to_prices(parse_csv_text(bad, "0" * 64), "X")
    assert (info2.value.key, info2.value.row, info2.value.column) == (
        "validate.bad_float", 2, "high",
    )
    bad_time = HEADER + "hier,1.1,1.2,1.0,1.15\n"
    with pytest.raises(DataError) as info3:
        table_to_prices(parse_csv_text(bad_time, "0" * 64), "X")
    assert info3.value.key == "validate.bad_datetime"
    with pytest.raises(DataError) as info4:
        table_to_prices(parse_csv_text(HEADER, "0" * 64), "X")
    assert info4.value.key == "validate.no_rows"
