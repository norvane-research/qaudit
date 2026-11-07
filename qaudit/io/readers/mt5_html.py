# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lecteur du rapport HTML MetaTrader 5 (« Enregistrer sous rapport »).

Analyse par ``html.parser`` (bibliothèque standard) : on cherche la table dont
une ligne d'en-tête contient ``Position``, ``Symbol``, ``Type`` et ``Volume``
— la section « Positions » — puis on lit les lignes de données jusqu'à la
première ligne vide ou de synthèse. La devise et le dépôt initial sont lus dans
l'en-tête du rapport quand ils s'y trouvent (``Currency: USD``, ligne
``Deposit`` de la section Deals ou ``Initial Deposit``).

Les colonnes ``Time`` / ``Price`` dédoublées sont traitées comme pour le CSV MT5.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from qaudit.core.errors import DataError
from qaudit.core.models import Cell, RawTable
from qaudit.core.validate import parse_float
from qaudit.io.readers.common import decode_bytes, fingerprint_bytes
from qaudit.io.readers.mt5_csv import BALANCE_TYPES, rename_mt5_columns
from qaudit.io.readers.mt5_headers import mt5_key

SOURCE = "mt5_html"
_CURRENCY = re.compile(r"(?:currency|devise|moneda|wahrung|moeda|valuta)\s*:?\s*([A-Z]{3})\b",
                       re.IGNORECASE)
# ligne « Compte: 1234567 (USD, Deriv-Demo, demo, Hedge) » du rapport d'historique
_ACCOUNT_CURRENCY = re.compile(r"\b\d{4,}\s*\(\s*([A-Z]{3})\s*,")
_DEPOSIT = re.compile(
    r"(?:initial deposit|dépôt initial|deposit)\s*:?\s*([-\d\s.,]+)", re.IGNORECASE
)


class _Rows(HTMLParser):
    """Collecte chaque ligne de tableau comme liste de cellules texte, avec le
    numéro de ligne source de son ``<tr>``."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[int, list[str]]] = []
        self._cells: list[str] | None = None
        self._buffer: list[str] = []
        self._in_cell = False
        self._skip = False
        self._line = 0
        self.texts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._cells = []
            self._line = self.getpos()[0]
        elif tag in ("td", "th") and self._cells is not None:
            # MT5 insère des cellules « hidden » (commentaire replié) : hors grille
            classes = dict(attrs).get("class") or ""
            self._skip = "hidden" in classes.split()
            self._in_cell = True
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_cell and self._cells is not None:
            if not self._skip:
                self._cells.append(" ".join("".join(self._buffer).split()))
            self._in_cell = False
        elif tag == "tr" and self._cells is not None:
            self.rows.append((self._line, self._cells))
            self._cells = None

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._buffer.append(data)
        else:
            self.texts.append(data)


def _is_positions_header(cells: list[str]) -> bool:
    keys = [mt5_key(c) for c in cells]
    return {"position", "symbol", "type", "volume"} <= set(keys) and keys.count("time") >= 2


def parse_mt5_html(text: str, fingerprint: str) -> RawTable:
    parser = _Rows()
    parser.feed(text)
    header_index = next(
        (i for i, (_, cells) in enumerate(parser.rows) if _is_positions_header(cells)), None
    )
    if header_index is None:
        raise DataError("reader.mt5_positions_not_found")
    header = parser.rows[header_index][1]
    columns = rename_mt5_columns(tuple(header))
    type_pos = columns.index("direction")
    rows: list[tuple[Cell, ...]] = []
    lines: list[int] = []
    for line, cells in parser.rows[header_index + 1 :]:
        if len(cells) != len(columns) or not any(cells):
            break
        kind = cells[type_pos].strip().lower()
        if kind in BALANCE_TYPES or kind not in ("buy", "sell"):
            continue
        rows.append(tuple(cells))
        lines.append(line)
    whole = " ".join(parser.texts) + " " + " ".join(" ".join(c) for _, c in parser.rows)
    currency = _match_currency(whole)
    return RawTable(
        columns,
        tuple(rows),
        tuple(lines),
        fingerprint,
        SOURCE,
        initial_balance=_match_deposit(parser.rows, whole),
        currency=currency,
    )


def _match_currency(text: str) -> str | None:
    match = _CURRENCY.search(text) or _ACCOUNT_CURRENCY.search(text)
    return match.group(1).upper() if match else None


def _match_deposit(rows: list[tuple[int, list[str]]], text: str) -> float | None:
    for _, cells in rows:
        lowered = [c.lower() for c in cells]
        if any(c in ("balance", "deposit") for c in lowered):
            for cell in reversed(cells):
                try:
                    value = parse_float(cell)
                except ValueError:
                    continue
                if value > 0:
                    return value
    match = _DEPOSIT.search(text)
    if match:
        try:
            return parse_float(match.group(1))
        except ValueError:
            return None
    return None


def read_mt5_html(path: Path) -> RawTable:
    data = path.read_bytes()
    return parse_mt5_html(decode_bytes(data), fingerprint_bytes(data))
