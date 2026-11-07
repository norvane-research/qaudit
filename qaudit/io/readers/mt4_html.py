# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lecteur du rapport détaillé MetaTrader 4 (« Enregistrer comme rapport
détaillé » / *Save as Detailed Report*).

Structure : en-tête de compte (``Account``, ``Name``, ``Currency``), section
« Closed Transactions » — en-tête ``Ticket, Open Time, Type, Size, Item,
Price, S / L, T / P, Close Time, Price, Commission, Taxes, Swap, Profit`` —
puis « Open Trades », « Working Orders », « Summary ». Seules les lignes
``buy`` / ``sell`` de la première section sont des trades clos ; les lignes
``balance`` donnent le dépôt initial ; les positions ouvertes et les ordres en
attente sont ignorés. En-têtes reconnus dans la langue du terminal via
``mt5_key``. Les ``Taxes`` sont ajoutées à la commission (même signe, même
nature : un coût), pour que le profit net reste ``profit + commission + swap``.

Encodage : MT4 écrit en windows-1252 (``decode_bytes`` le gère).
"""

from __future__ import annotations

from qaudit.core.errors import DataError
from qaudit.core.models import Cell, RawTable
from qaudit.core.validate import parse_float
from qaudit.io.readers.mt5_csv import BALANCE_TYPES
from qaudit.io.readers.mt5_headers import mt5_key
from qaudit.io.readers.mt5_html import _match_currency, _Rows

SOURCE = "mt4_html"
COLUMNS = ("ticket", "open_time", "direction", "volume", "symbol", "open_price", "stop_loss",
           "take_profit", "close_time", "close_price", "commission", "swap", "profit")
_KEYS = ("ticket", "opentime", "type", "volume", "symbol", "price", "sl", "tp", "closetime",
         "price", "commission", "taxes", "swap", "profit")


def _is_closed_header(cells: list[str]) -> bool:
    keys = tuple(mt5_key(c) for c in cells)
    return keys[: len(_KEYS)] == _KEYS


def is_mt4_html(text: str) -> bool:
    parser = _Rows()
    parser.feed(text)
    return any(_is_closed_header(cells) for _, cells in parser.rows)


def parse_mt4_html(text: str, fingerprint: str) -> RawTable:
    parser = _Rows()
    parser.feed(text)
    start = next((i for i, (_, c) in enumerate(parser.rows) if _is_closed_header(c)), None)
    if start is None:
        raise DataError("reader.mt4_closed_not_found")
    rows: list[tuple[Cell, ...]] = []
    lines: list[int] = []
    initial_balance: float | None = None
    for line, cells in parser.rows[start + 1 :]:
        kind = cells[2].strip().lower() if len(cells) > 2 else ""
        if kind in BALANCE_TYPES:
            initial_balance = _first_deposit(initial_balance, cells)
            continue
        if len(cells) != len(_KEYS) or kind not in ("buy", "sell"):
            break  # fin de la section « Closed Transactions » (total, positions ouvertes…)
        rows.append(_trade(cells))
        lines.append(line)
    whole = " ".join(parser.texts) + " " + " ".join(" ".join(c) for _, c in parser.rows)
    return RawTable(
        COLUMNS, tuple(rows), tuple(lines), fingerprint, SOURCE,
        initial_balance=initial_balance, currency=_match_currency(whole),
    )


def _trade(cells: list[str]) -> tuple[Cell, ...]:
    (ticket, open_time, kind, size, item, price, sl, tp, close_time, close_price, commission,
     taxes, swap, profit) = cells
    return (
        ticket, open_time, kind.lower(), size, item.upper(), price, sl, tp, close_time,
        close_price, _sum(commission, taxes), swap, profit,
    )


def _sum(commission: str, taxes: str) -> str:
    """Commission + taxes (les deux sont des coûts ; vides = 0)."""
    total = 0.0
    for text in (commission, taxes):
        if text.strip():
            total += parse_float(text)
    return f"{total:.2f}"


def _first_deposit(current: float | None, cells: list[str]) -> float | None:
    """Premier mouvement de solde strictement positif : le dépôt initial."""
    if current is not None:
        return current
    for cell in reversed(cells):
        try:
            value = parse_float(cell)
        except ValueError:
            continue
        if value > 0:
            return value
    return None
