# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lecteur du rapport du **Strategy Tester** MetaTrader 5 (« Rapport » → HTML
ou Open XML). Le rapport ne contient pas de table « Positions » mais les tables
**Orders** et **Deals** : les trades clos sont reconstitués à partir des deals.

Reconstitution (documentée, déterministe) :

- un deal ``in`` ouvre un lot (heure, sens = type du deal, volume, prix,
  commission d'entrée, ordre) ; un deal ``out`` ferme du volume sur les lots
  ouverts du même symbole et du **sens opposé** (une vente ``out`` clôt des
  achats) ; ``in/out`` ferme d'abord tout ce qui peut l'être puis ouvre le reste ;
- choix du lot fermé : le plus ancien lot dont le volume restant **égale** celui
  du deal, sinon le plus ancien (FIFO) avec fractionnement. Sans identifiant de
  position dans le rapport, c'est exact en mode *netting* et dès que les
  positions d'un même symbole et sens ne se chevauchent pas ; en cas de
  chevauchement sans égalité de volume, l'appariement est une hypothèse et le
  lecteur le dit (constat « info » ``reader.tester_ambiguous``) ;
- profit, swap et commission de sortie du deal sont répartis au prorata du
  volume fermé ; la commission d'entrée du lot au prorata du volume du lot ;
- le stop et la cible viennent de la table Orders (ordre d'entrée du lot) ;
- le premier deal ``balance`` donne le dépôt initial ; la devise est lue dans
  l'en-tête (« Currency: USD ») ;
- les lots encore ouverts à la fin du rapport ne sont pas des trades clos : ils
  sont écartés et comptés (``reader.tester_open_positions``).

Le ``ticket`` d'un trade reconstitué est un numéro d'ordre séquentiel (un deal
d'entrée peut être fermé en plusieurs fois et un deal de sortie fermer plusieurs
lots : ni l'un ni l'autre n'identifie un trade) ; sa ligne source est celle du
deal de sortie.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from io import BytesIO

from qaudit.core.errors import DataError
from qaudit.core.models import Cell, Params, RawTable
from qaudit.core.validate import parse_float
from qaudit.io.readers.common import decode_bytes
from qaudit.io.readers.mt5_headers import mt5_key
from qaudit.io.readers.mt5_html import _is_positions_header, _match_currency, _Rows

SOURCE = "mt5_tester"
COLUMNS: tuple[str, ...] = (
    "ticket", "open_time", "close_time", "symbol", "direction", "volume", "open_price",
    "close_price", "stop_loss", "take_profit", "commission", "swap", "profit",
)
DEALS_HEADER = ("time", "deal", "symbol", "type", "direction", "volume", "price", "order",
                "commission", "swap", "profit", "balance")
ORDERS_HEADER = ("opentime", "order", "symbol", "type", "volume", "price", "sl", "tp")
BALANCE_TYPES = frozenset({"balance", "credit", "deposit", "withdrawal", "correction", "bonus"})
EXCEL_EPOCH = datetime(1899, 12, 30)
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

Row = tuple[int, list[str]]


@dataclass
class _Lot:
    deal: int
    time: str
    direction: int
    volume: float
    remaining: float
    price: float
    commission: float
    order: str


@dataclass(frozen=True, slots=True)
class _Deal:
    line: int
    time: str
    deal: int
    symbol: str
    type: str
    direction: str
    volume: float
    price: float
    order: str
    commission: float
    swap: float
    profit: float


@dataclass
class _Book:
    """État de la reconstitution : lots ouverts par symbole, trades produits."""

    orders: Mapping[str, tuple[float, float]]
    lots: dict[str, list[_Lot]] = field(default_factory=dict)
    rows: list[tuple[Cell, ...]] = field(default_factory=list)
    lines: list[int] = field(default_factory=list)
    ambiguous: int = 0


# ---------------------------------------------------------------------------
# cellules
# ---------------------------------------------------------------------------


def _number(text: str) -> float:
    text = text.strip()
    if not text:
        return 0.0
    return parse_float(text.split("/")[0])  # « 0.10 / 0.10 » (rempli / demandé)


def _time_cell(text: str) -> str:
    """Horodatage texte, ou numéro de série Excel (export Open XML) converti."""
    text = text.strip()
    if re.fullmatch(r"\d+(\.\d+)?", text) and float(text) < 1_000_000:
        return (EXCEL_EPOCH + timedelta(days=float(text))).strftime("%Y.%m.%d %H:%M:%S")
    return text


def _header_index(rows: Sequence[Row], header: tuple[str, ...]) -> int | None:
    for i, (_, cells) in enumerate(rows):
        keys = [mt5_key(c) for c in cells]
        if len(keys) >= len(header) and tuple(keys[: len(header)]) == header:
            return i
    return None


def is_tester_rows(rows: Sequence[Row]) -> bool:
    """Rapport du testeur : une table Deals et **aucune** table Positions (le
    rapport d'historique de compte a les deux ; ses positions font foi)."""
    has_positions = any(_is_positions_header(cells) for _, cells in rows)
    return not has_positions and _header_index(rows, DEALS_HEADER) is not None


# ---------------------------------------------------------------------------
# tables Orders et Deals
# ---------------------------------------------------------------------------


def _orders(rows: Sequence[Row]) -> dict[str, tuple[float, float]]:
    start = _header_index(rows, ORDERS_HEADER)
    if start is None:
        return {}
    out: dict[str, tuple[float, float]] = {}
    for _, cells in rows[start + 1 :]:
        # l'export Open XML omet les cellules vides de fin : on exige les 8 premières
        if len(cells) < len(ORDERS_HEADER) or not cells[1].strip():
            break
        try:
            out[cells[1].strip()] = (_number(cells[6]), _number(cells[7]))
        except ValueError:
            continue
    return out


def _deals(rows: Sequence[Row]) -> list[_Deal]:
    start = _header_index(rows, DEALS_HEADER)
    if start is None:
        raise DataError("reader.mt5_tester_no_deals")
    deals: list[_Deal] = []
    for line, cells in rows[start + 1 :]:
        if len(cells) < len(DEALS_HEADER) - 1 or not cells[1].strip():
            break  # ligne de totaux (cellules fusionnées) ou fin de table
        try:
            deals.append(
                _Deal(
                    line=line,
                    time=_time_cell(cells[0]),
                    deal=int(_number(cells[1])),
                    symbol=cells[2].strip(),
                    type=cells[3].strip().lower(),
                    direction=cells[4].strip().lower(),
                    volume=_number(cells[5]),
                    price=_number(cells[6]),
                    order=cells[7].strip(),
                    commission=_number(cells[8]),
                    swap=_number(cells[9]),
                    profit=_number(cells[10]),
                )
            )
        except ValueError as exc:
            raise DataError("reader.mt5_tester_bad_deal", row=line, column="Deals") from exc
    return deals


# ---------------------------------------------------------------------------
# reconstitution
# ---------------------------------------------------------------------------


def _open(book: _Book, deal: _Deal, volume: float, commission: float) -> None:
    direction = 1 if deal.type == "buy" else -1
    book.lots.setdefault(deal.symbol, []).append(
        _Lot(deal.deal, deal.time, direction, volume, volume, deal.price, commission, deal.order)
    )


def _pick(candidates: list[_Lot], volume: float) -> _Lot:
    for lot in candidates:
        if abs(lot.remaining - volume) < 1e-9:
            return lot
    return candidates[0]


def _emit(book: _Book, deal: _Deal, lot: _Lot, matched: float, closable: float) -> None:
    """Un trade clos : profit et swap du deal au prorata du volume fermé par ce
    deal (``closable``), commission de sortie au prorata du volume du deal,
    commission d'entrée au prorata du volume du lot."""
    matched = round(matched, 8)
    profit_share = matched / closable if closable > 0 else 1.0
    exit_share = matched / deal.volume if deal.volume > 0 else 1.0
    entry_share = matched / lot.volume if lot.volume > 0 else 1.0
    sl, tp = book.orders.get(lot.order, (0.0, 0.0))
    book.rows.append((
        len(book.rows) + 1,
        lot.time,
        deal.time,
        deal.symbol,
        "buy" if lot.direction > 0 else "sell",
        matched,
        lot.price,
        deal.price,
        sl,
        tp,
        lot.commission * entry_share + deal.commission * exit_share,
        deal.swap * profit_share,
        deal.profit * profit_share,
    ))
    book.lines.append(deal.line)


def _close(book: _Book, deal: _Deal, volume: float) -> float:
    """Ferme jusqu'à ``volume`` sur les lots opposés du symbole ; volume fermé."""
    closing = -1 if deal.type == "buy" else 1  # une vente « out » clôt des achats
    opposite = [lot for lot in book.lots.get(deal.symbol, []) if lot.direction == closing]
    closable = min(volume, sum(lot.remaining for lot in opposite))
    closed = 0.0
    while volume - closed > 1e-9:
        candidates = [lot for lot in book.lots.get(deal.symbol, []) if lot.direction == closing]
        if not candidates:
            break
        remaining = volume - closed
        lot = _pick(candidates, remaining)
        if len(candidates) > 1 and abs(lot.remaining - remaining) >= 1e-9:
            book.ambiguous += 1
        matched = min(lot.remaining, remaining)
        _emit(book, deal, lot, matched, closable)
        lot.remaining -= matched
        if lot.remaining <= 1e-9:
            book.lots[deal.symbol].remove(lot)
        closed += matched
    return closed


def _replay(
    deals: list[_Deal], orders: Mapping[str, tuple[float, float]]
) -> tuple[_Book, float | None]:
    book = _Book(orders)
    initial: float | None = None
    for deal in sorted(deals, key=lambda d: (d.time, d.deal)):
        if deal.type in BALANCE_TYPES or deal.type not in ("buy", "sell"):
            if initial is None and deal.profit > 0:
                initial = deal.profit
            continue
        if deal.direction == "in":
            _open(book, deal, deal.volume, deal.commission)
        elif deal.direction == "out":
            _close(book, deal, deal.volume)
        elif deal.direction in ("in/out", "inout"):
            closed = _close(book, deal, deal.volume)
            rest = deal.volume - closed
            if rest > 1e-9:
                _open(book, deal, rest, deal.commission * rest / deal.volume)
    return book, initial


def build_table(rows: Sequence[Row], fingerprint: str, whole_text: str) -> RawTable:
    """Rapport (lignes de cellules) → table brute de trades clos reconstitués."""
    deals = _deals(rows)
    book, initial = _replay(deals, _orders(rows))
    notes: list[tuple[str, Params]] = []
    if book.ambiguous:
        notes.append(("reader.tester_ambiguous", (("count", book.ambiguous),)))
    still_open = sum(len(lots) for lots in book.lots.values())
    if still_open:
        notes.append(("reader.tester_open_positions", (("count", still_open),)))
    if not book.rows:
        raise DataError("reader.mt5_tester_no_trades")
    return RawTable(
        COLUMNS,
        tuple(book.rows),
        tuple(book.lines),
        fingerprint,
        SOURCE,
        initial_balance=initial,
        currency=_match_currency(whole_text),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def html_rows(text: str) -> tuple[list[Row], str]:
    parser = _Rows()
    parser.feed(text)
    whole = " ".join(parser.texts) + " " + " ".join(" ".join(c) for _, c in parser.rows)
    return parser.rows, whole


def is_tester_html(text: str) -> bool:
    return is_tester_rows(html_rows(text)[0])


def parse_mt5_tester_html(text: str, fingerprint: str) -> RawTable:
    rows, whole = html_rows(text)
    return build_table(rows, fingerprint, whole)


# ---------------------------------------------------------------------------
# Open XML (xlsx) — lecture minimale, bibliothèque standard seulement
# ---------------------------------------------------------------------------


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")) for si in root]


def _column_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref)
    index = 0
    for ch in letters.group(0) if letters else "A":
        index = index * 26 + (ord(ch) - 64)
    return index - 1


def xlsx_rows(data: bytes) -> list[Row]:
    """Lignes de la première feuille, cellules en texte, numérotées par ``r``."""
    with zipfile.ZipFile(BytesIO(data)) as archive:
        strings = _shared_strings(archive)
        sheets = sorted(n for n in archive.namelist() if n.startswith("xl/worksheets/sheet"))
        if not sheets:
            raise DataError("reader.mt5_tester_no_deals")
        root = ET.fromstring(archive.read(sheets[0]))
    rows: list[Row] = []
    for row in root.iter(f"{{{_NS['m']}}}row"):
        cells: dict[int, str] = {}
        for cell in row.findall("m:c", _NS):
            value = cell.find("m:v", _NS)
            inline = cell.find("m:is", _NS)
            kind = cell.get("t", "n")
            if kind == "s" and value is not None and value.text is not None:
                text = strings[int(value.text)]
            elif kind == "inlineStr" and inline is not None:
                text = "".join(t.text or "" for t in inline.iter(f"{{{_NS['m']}}}t"))
            else:
                text = value.text or "" if value is not None else ""
            cells[_column_index(cell.get("r", "A"))] = text
        width = max(cells) + 1 if cells else 0
        rows.append((int(row.get("r", len(rows) + 1)), [cells.get(i, "") for i in range(width)]))
    return rows


def parse_mt5_tester_xlsx(data: bytes, fingerprint: str) -> RawTable:
    rows = xlsx_rows(data)
    whole = " ".join(" ".join(c) for _, c in rows)
    return build_table(rows, fingerprint, whole)


def parse_mt5_tester(data: bytes, fingerprint: str, suffix: str) -> RawTable:
    if suffix.lower() == ".xlsx" or data[:2] == b"PK":
        return parse_mt5_tester_xlsx(data, fingerprint)
    return parse_mt5_tester_html(decode_bytes(data), fingerprint)
