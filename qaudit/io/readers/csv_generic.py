# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lecteur CSV générique : séparateur détecté, en-tête libre, cellules brutes.

Le lecteur ne convertit rien : il livre une ``RawTable`` de chaînes numérotées
par ligne source ; la validation (noyau) convertit et nomme ligne et colonne en
cas d'erreur. Les lignes vides sont ignorées, les lignes de commentaire
(``#`` en tête) aussi.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from io import StringIO
from pathlib import Path

from qaudit.core.errors import DataError
from qaudit.core.models import RawTable
from qaudit.io.readers.common import decode_bytes, fingerprint_bytes

SOURCE = "csv"
DELIMITERS = ",;\t|"


def sniff_delimiter(sample: str) -> str:
    """Séparateur le plus fréquent dans la première ligne non vide."""
    first = next((line for line in sample.splitlines() if line.strip()), "")
    counts = {d: first.count(d) for d in DELIMITERS}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > 0 else ","


def parse_csv_text(text: str, fingerprint: str, *, source: str = SOURCE) -> RawTable:
    """Découpe le texte CSV en table brute ; ``fingerprint`` est celle des octets."""
    delimiter = sniff_delimiter(text[:4096])
    reader = csv.reader(StringIO(text), delimiter=delimiter)
    columns: tuple[str, ...] | None = None
    rows: list[tuple[str, ...]] = []
    lines: list[int] = []
    for number, record in enumerate(reader, start=1):
        if not record or all(not cell.strip() for cell in record):
            continue
        if record[0].lstrip().startswith("#"):
            continue
        if columns is None:
            columns = unique_headers(tuple(cell.strip() for cell in record))
            continue
        cells = _fit(record, len(columns), number)
        rows.append(cells)
        lines.append(number)
    if columns is None:
        raise DataError("validate.no_rows")
    return RawTable(columns, tuple(rows), tuple(lines), fingerprint, source)


def unique_headers(columns: Sequence[str]) -> tuple[str, ...]:
    """Rend chaque en-tête unique : le deuxième « Time » devient « Time#2 », le
    troisième « Time#3 »… Sans cela, toute résolution par nom (déduction,
    ``--mapping``) atteindrait toujours la première colonne du nom."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for name in columns:
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f"{name}#{seen[name]}")
    return tuple(out)


def _fit(record: Sequence[str], width: int, line: int) -> tuple[str, ...]:
    if len(record) == width:
        return tuple(cell.strip() for cell in record)
    if len(record) > width and all(not c.strip() for c in record[width:]):
        return tuple(cell.strip() for cell in record[:width])
    raise DataError("reader.row_width", row=line, expected=width, actual=len(record))


def read_csv_generic(path: Path) -> RawTable:
    data = path.read_bytes()
    return parse_csv_text(decode_bytes(data), fingerprint_bytes(data))
