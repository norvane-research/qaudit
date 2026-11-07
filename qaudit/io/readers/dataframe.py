# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lecteur DataFrame (pandas) : usage en bibliothèque.

Les cellules sont converties en types que la validation du noyau comprend
(chaînes, nombres, ``datetime64``) ; les horodatages pandas sont ramenés en
``numpy.datetime64``. L'empreinte SHA-256 est calculée sur une sérialisation
canonique des cellules (en-tête compris), puisqu'il n'y a pas de fichier.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np
import pandas as pd

from qaudit.core.models import Cell, RawTable

SOURCE = "dataframe"


def _cell(value: object) -> Cell:
    if value is None:
        return None
    if hasattr(value, "to_datetime64"):
        return np.datetime64(value.to_datetime64(), "ns")
    if isinstance(value, np.datetime64):
        return np.datetime64(value, "ns")
    if isinstance(value, np.bool_ | bool):
        return bool(value)
    if isinstance(value, np.integer | int):
        return int(value)
    if isinstance(value, np.floating | float):
        f = float(value)
        return None if math.isnan(f) else f
    return str(value)


def _canonical(columns: tuple[str, ...], rows: tuple[tuple[Cell, ...], ...]) -> bytes:
    lines = [",".join(columns)]
    lines.extend(",".join("" if c is None else str(c) for c in row) for row in rows)
    return "\n".join(lines).encode("utf-8")


def from_dataframe(
    df: pd.DataFrame, *, initial_balance: float | None = None, currency: str | None = None
) -> RawTable:
    """DataFrame → table brute ; les lignes sont numérotées à partir de 2 (1 = en-tête)."""
    columns = tuple(str(c) for c in df.columns)
    rows = tuple(
        tuple(_cell(v) for v in record) for record in df.itertuples(index=False, name=None)
    )
    fingerprint = hashlib.sha256(_canonical(columns, rows)).hexdigest()
    return RawTable(
        columns,
        rows,
        tuple(range(2, 2 + len(rows))),
        fingerprint,
        SOURCE,
        initial_balance=initial_balance,
        currency=currency,
    )
