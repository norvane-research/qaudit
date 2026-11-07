# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lecteur CSV MetaTrader 5 : export de l'onglet Historique (positions).

Format reconnu (séparateur ``;``, ``,`` ou tabulation ; nombres avec espaces ou
virgule décimale) :

    Time;Position;Symbol;Type;Volume;Price;S / L;T / P;Time;Price;Commission;Swap;Profit

Les colonnes ``Time`` et ``Price`` apparaissent deux fois (ouverture puis
clôture) : elles sont renommées ``open_time`` / ``close_time`` et
``open_price`` / ``close_price``. Les lignes de solde (``balance``, dépôt,
retrait) sont écartées ; un dépôt initial détecté renseigne le solde initial.
"""

from __future__ import annotations

from pathlib import Path

from qaudit.core.models import Cell, RawTable
from qaudit.core.validate import parse_float
from qaudit.io.readers.common import decode_bytes, fingerprint_bytes
from qaudit.io.readers.csv_generic import parse_csv_text
from qaudit.io.readers.mt5_headers import mt5_key

SOURCE = "mt5_csv"
BALANCE_TYPES = frozenset({"balance", "credit", "deposit", "withdrawal", "correction", "bonus"})


def _base_header(column: str) -> str:
    """Clé canonique (anglaise) de l'en-tête, quelle que soit la langue du terminal."""
    return mt5_key(column)


def looks_like_mt5(columns: tuple[str, ...]) -> bool:
    normalised = [_base_header(c) for c in columns]
    return (
        normalised.count("time") >= 2
        and normalised.count("price") >= 2
        and "position" in normalised
        and "symbol" in normalised
    )


def rename_mt5_columns(columns: tuple[str, ...]) -> tuple[str, ...]:
    """Désambiguïse les doublons ``Time`` / ``Price`` en ouverture puis clôture."""
    seen_time = seen_price = 0
    out = []
    for column in columns:
        key = _base_header(column)
        if key == "time":
            out.append("open_time" if seen_time == 0 else "close_time")
            seen_time += 1
        elif key == "price":
            out.append("open_price" if seen_price == 0 else "close_price")
            seen_price += 1
        elif key == "sl":
            out.append("stop_loss")
        elif key == "tp":
            out.append("take_profit")
        elif key == "position":
            out.append("ticket")
        elif key == "type":
            out.append("direction")
        else:
            out.append(key)
    return tuple(out)


def _initial_balance(rows: list[tuple[Cell, ...]], type_pos: int, profit_pos: int) -> float | None:
    for row in rows:
        kind = str(row[type_pos]).strip().lower()
        if kind in ("balance", "deposit"):
            try:
                value = parse_float(row[profit_pos])
            except ValueError:
                continue
            if value > 0:
                return value
    return None


def mt5_table(table: RawTable) -> RawTable:
    """Table MT5 générique → table aux colonnes canoniques, sans lignes de solde."""
    columns = rename_mt5_columns(table.columns)
    type_pos = columns.index("direction")
    profit_pos = columns.index("profit") if "profit" in columns else -1
    kept_rows: list[tuple[Cell, ...]] = []
    kept_lines: list[int] = []
    for row, line in zip(table.rows, table.line_numbers, strict=True):
        kind = str(row[type_pos]).strip().lower()
        if kind in BALANCE_TYPES or not kind:
            continue
        kept_rows.append(row)
        kept_lines.append(line)
    balance = _initial_balance(list(table.rows), type_pos, profit_pos) if profit_pos >= 0 else None
    return RawTable(
        columns,
        tuple(kept_rows),
        tuple(kept_lines),
        table.fingerprint,
        SOURCE,
        initial_balance=balance,
        currency=table.currency,
    )


def read_mt5_csv(path: Path) -> RawTable:
    data = path.read_bytes()
    table = parse_csv_text(decode_bytes(data), fingerprint_bytes(data), source=SOURCE)
    return mt5_table(table)
