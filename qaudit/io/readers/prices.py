# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lecteur de série OHLC (CSV) → ``PriceSeries``.

Colonnes reconnues par synonymes : horodatage (time/date/datetime/…), open,
high, low, close. Toute erreur nomme la ligne et la colonne. La cohérence
``low ≤ open, close ≤ high`` est vérifiée ligne par ligne.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np

from qaudit.core.errors import DataError, SchemaError
from qaudit.core.models import PriceSeries, RawTable
from qaudit.core.validate import parse_datetime, parse_float
from qaudit.io.readers.common import normalise_header
from qaudit.io.readers.csv_generic import read_csv_generic

PRICE_FIELDS: tuple[str, ...] = ("time", "open", "high", "low", "close")
PRICE_SYNONYMS: Mapping[str, tuple[str, ...]] = {
    "time": ("time", "date", "datetime", "timestamp", "bartime", "heure", "gmttime", "localtime"),
    "open": ("open", "o", "ouverture", "openprice"),
    "high": ("high", "h", "haut", "max", "highprice"),
    "low": ("low", "l", "bas", "min", "lowprice"),
    "close": ("close", "c", "cloture", "last", "closeprice"),
}


def infer_price_mapping(columns: tuple[str, ...]) -> dict[str, str]:
    normalised = {normalise_header(c): c for c in columns}
    mapping: dict[str, str] = {}
    taken: set[str] = set()
    for field_name in PRICE_FIELDS:
        for candidate in PRICE_SYNONYMS[field_name]:
            column = normalised.get(candidate)
            if column is not None and column not in taken:
                mapping[field_name] = column
                taken.add(column)
                break
    return mapping


def _floats(table: RawTable, column: str) -> np.ndarray:
    pos = table.columns.index(column)
    out = np.empty(table.n)
    for i, (row, line) in enumerate(zip(table.rows, table.line_numbers, strict=True)):
        try:
            out[i] = parse_float(row[pos])
        except ValueError as exc:
            raise DataError(
                "validate.bad_float", row=line, column=column, value=str(row[pos])
            ) from exc
    return out


def _times(table: RawTable, column: str, date_column: str | None) -> np.ndarray:
    pos = table.columns.index(column)
    date_pos = table.columns.index(date_column) if date_column else None
    out = np.empty(table.n, dtype="datetime64[ns]")
    for i, (row, line) in enumerate(zip(table.rows, table.line_numbers, strict=True)):
        cell = row[pos]
        if date_pos is not None:
            cell = f"{row[date_pos]} {cell}".strip()
        try:
            out[i] = parse_datetime(cell)
        except ValueError as exc:
            raise DataError(
                "validate.bad_datetime", row=line, column=column, value=str(cell)
            ) from exc
    return out


def table_to_prices(table: RawTable, symbol: str) -> PriceSeries:
    mapping = infer_price_mapping(table.columns)
    missing = tuple(f for f in PRICE_FIELDS if f not in mapping)
    if missing:
        raise SchemaError(table.columns, missing)
    if table.n == 0:
        raise DataError("validate.no_rows")
    # colonnes DATE + TIME séparées (export MetaTrader) : TIME seule est une heure
    date_column = None
    lowered = {normalise_header(c): c for c in table.columns}
    if normalise_header(mapping["time"]) == "time" and "date" in lowered:
        date_column = lowered["date"]
    times = _times(table, mapping["time"], date_column)
    open_ = _floats(table, mapping["open"])
    high = _floats(table, mapping["high"])
    low = _floats(table, mapping["low"])
    close = _floats(table, mapping["close"])
    outside = (open_ > high) | (open_ < low) | (close > high) | (close < low)
    bad = np.nonzero((high < low) | outside)[0]
    if bad.size:
        i = int(bad[0])
        raise DataError(
            "prices.inconsistent_bar", row=table.line_numbers[i], column=mapping["high"]
        )
    order = np.argsort(times.astype(np.int64), kind="stable")
    if np.any(np.diff(times[order].astype(np.int64)) == 0):
        dup = int(np.nonzero(np.diff(times[order].astype(np.int64)) == 0)[0][0]) + 1
        raise DataError(
            "prices.duplicate_bar", row=table.line_numbers[int(order[dup])], column=mapping["time"]
        )
    return PriceSeries(
        time=times[order], open=open_[order], high=high[order], low=low[order],
        close=close[order], symbol=symbol, fingerprint=table.fingerprint,
    )


def read_prices(path: Path, symbol: str | None = None) -> PriceSeries:
    table = read_csv_generic(path)
    return table_to_prices(table, symbol or path.stem)
