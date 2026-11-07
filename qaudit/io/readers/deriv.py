# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lecteur d'export Deriv (table des profits, « Profit table » → CSV).

Format reconnu : en-tête contenant ``Buy time`` et ``Sell time`` (casse et
ponctuation libres), par exemple :

    Ref. ID,Contract,Market,Buy time,Buy price,Sell time,Sell price,Profit/Loss

Correspondance : ``Buy time`` → ouverture, ``Sell time`` → clôture, ``Profit/Loss``
(ou ``Sell price − Buy price`` à défaut) → profit, ``Buy price`` (mise) → volume,
``Market``/``Contract``/``Symbol`` → symbole, ``Ref. ID`` → ticket. Les contrats
n'ont pas de sens long/short ni de stop : ces champs restent inconnus et les
analyses qui en dépendent sont signalées comme non testées.
"""

from __future__ import annotations

from pathlib import Path

from qaudit.core.errors import DataError
from qaudit.core.models import Cell, RawTable
from qaudit.core.validate import parse_float
from qaudit.io.readers.common import decode_bytes, fingerprint_bytes, normalise_header
from qaudit.io.readers.csv_generic import parse_csv_text

SOURCE = "deriv"
_SYNONYMS = {
    "buytime": "open_time",
    "purchasetime": "open_time",
    "selltime": "close_time",
    "expirytime": "close_time",
    "buyprice": "volume",
    "stake": "volume",
    "sellprice": "payout",
    "payout": "payout",
    "profitloss": "profit",
    "profit": "profit",
    "refid": "ticket",
    "reference": "ticket",
    "contractid": "ticket",
    "market": "symbol",
    "symbol": "symbol",
    "underlying": "symbol",
    "contract": "contract",
    "contracttype": "contract",
    "currency": "currency",
}


def looks_like_deriv(columns: tuple[str, ...]) -> bool:
    keys = {normalise_header(c) for c in columns}
    return bool({"buytime", "purchasetime"} & keys) and bool({"selltime", "expirytime"} & keys)


def deriv_table(table: RawTable) -> RawTable:
    """Renomme les colonnes et calcule le profit si seul le couple mise / gain existe."""
    columns = tuple(_SYNONYMS.get(normalise_header(c), normalise_header(c)) for c in table.columns)
    if "profit" in columns:
        return RawTable(
            columns,
            table.rows,
            table.line_numbers,
            table.fingerprint,
            SOURCE,
            initial_balance=table.initial_balance,
            currency=table.currency,
        )
    if "volume" not in columns or "payout" not in columns:
        raise DataError("reader.deriv_missing_profit")
    stake_pos, payout_pos = columns.index("volume"), columns.index("payout")
    rows: list[tuple[Cell, ...]] = []
    for row, line in zip(table.rows, table.line_numbers, strict=True):
        try:
            profit = parse_float(row[payout_pos]) - parse_float(row[stake_pos])
        except ValueError as exc:
            raise DataError(
                "validate.bad_float",
                row=line,
                column=table.columns[payout_pos],
                value=str(row[payout_pos]),
            ) from exc
        rows.append((*row, f"{profit:.2f}"))
    return RawTable(
        (*columns, "profit"),
        tuple(rows),
        table.line_numbers,
        table.fingerprint,
        SOURCE,
        initial_balance=table.initial_balance,
        currency=table.currency,
    )


def read_deriv(path: Path) -> RawTable:
    data = path.read_bytes()
    return deriv_table(parse_csv_text(decode_bytes(data), fingerprint_bytes(data), source=SOURCE))
