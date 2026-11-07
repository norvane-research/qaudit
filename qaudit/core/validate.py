# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validation d'une table brute : schéma, types, chronologie, doublons, devise,
trous, ruine. Tout message d'erreur nomme la ligne et la colonne fautives.

Hypothèses retenues (voir README.fr.md, « Conventions d'ingestion ») :
- les horodatages sont naïfs, interprétés tels quels (heure du serveur) ; un
  décalage explicite (``+02:00``, ``Z``) est converti en UTC puis oublié ;
- si des colonnes ``commission`` et/ou ``swap`` sont fournies, ``profit`` est
  réputé brut et le résultat net vaut ``profit + commission + swap`` (convention
  MetaTrader, où commission et swap sont signés) ; sinon ``profit`` est réputé net ;
- l'ordre canonique est l'heure de clôture croissante (puis ouverture, puis
  ticket) : c'est l'ordre dans lequel les résultats s'inscrivent sur l'equity ;
- la ruine (D-03) est constatée dès que ``solde initial + cumul des profits`` ≤ 0 ;
  tout calcul relatif à l'equity s'arrête au trade qui la provoque, inclus.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from qaudit.core.errors import DataError, SchemaError
from qaudit.core.models import (
    ALL_FIELDS,
    NS_PER_DAY,
    REQUIRED_FIELDS,
    Cell,
    Finding,
    FloatArray,
    Int8Array,
    IntArray,
    RawTable,
    Severity,
    TimeArray,
    TradeSet,
    time_to_iso,
)

SOURCE = "validate"

_DIRECTION_TOKENS: Mapping[str, int] = {
    "buy": 1,
    "long": 1,
    "b": 1,
    "achat": 1,
    "1": 1,
    "+1": 1,
    "sell": -1,
    "short": -1,
    "s": -1,
    "vente": -1,
    "-1": -1,
}

_DATETIME_FORMATS: tuple[str, ...] = (
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y.%m.%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S.%f",
)

_MISSING_TOKENS = frozenset({"", "nan", "none", "null", "n/a", "na", "-", "--"})


@dataclass(frozen=True)
class ValidationResult:
    """Jeu de trades canonique, constats de validation et index de ruine."""

    tradeset: TradeSet
    findings: tuple[Finding, ...]
    ruin_index: int | None

    @property
    def usable(self) -> TradeSet:
        """Partie de l'historique sur laquelle l'equity reste strictement positive.

        Le trade qui provoque la ruine est inclus : il a eu lieu et son résultat
        appartient au P&L ; aucun rendement n'est calculé au-delà.
        """
        if self.ruin_index is None:
            return self.tradeset
        return self.tradeset.take(slice(0, self.ruin_index + 1))


# ---------------------------------------------------------------------------
# schéma
# ---------------------------------------------------------------------------


def missing_required(mapping: Mapping[str, str]) -> tuple[str, ...]:
    """Champs obligatoires absents de la correspondance champ → colonne."""
    return tuple(f for f in REQUIRED_FIELDS if f not in mapping)


def check_schema(table: RawTable, mapping: Mapping[str, str]) -> None:
    """Lève ``SchemaError`` (porte E1) si un champ obligatoire manque ou si une
    colonne référencée n'existe pas dans la table."""
    missing = list(missing_required(mapping))
    for field_name, column in mapping.items():
        if field_name in ALL_FIELDS and column not in table.columns:
            missing.append(field_name)
    if missing:
        raise SchemaError(table.columns, tuple(dict.fromkeys(missing)))


# ---------------------------------------------------------------------------
# conversion cellule → valeur
# ---------------------------------------------------------------------------


def _is_missing(cell: Cell) -> bool:
    if cell is None:
        return True
    if isinstance(cell, str):
        return cell.strip().lower() in _MISSING_TOKENS
    if isinstance(cell, float):
        return bool(np.isnan(cell))
    if isinstance(cell, np.datetime64):
        return bool(np.isnat(cell))
    return False


def _normalise_number(text: str) -> str:
    """« 1 234,56 » → « 1234.56 » ; « 1,234.56 » → « 1234.56 » ; « 1,5 » → « 1.5 »."""
    cleaned = text.strip()
    for blank in (" ", "\u00a0", "\u202f", "\u2009"):  # espace, insécable, fine, étroite
        cleaned = cleaned.replace(blank, "")
    if "," in cleaned and "." in cleaned:
        # le dernier séparateur rencontré est le séparateur décimal
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    return cleaned


def parse_float(cell: Cell) -> float:
    """Convertit une cellule en flottant ; ``ValueError`` si impossible."""
    if isinstance(cell, bool):
        raise ValueError(repr(cell))
    if isinstance(cell, int | float):
        return float(cell)
    if isinstance(cell, str):
        return float(_normalise_number(cell))
    raise ValueError(repr(cell))


def _epoch_to_datetime64(value: float) -> np.datetime64:
    # secondes si < 1e11 (jusqu'en 5138), sinon millisecondes
    unit_ns = 1_000_000_000 if abs(value) < 1e11 else 1_000_000
    return np.datetime64(round(value * unit_ns), "ns")


def _parse_datetime_text(text: str) -> np.datetime64:
    text = text.strip()
    if text.isdigit() and len(text) >= 9:
        return _epoch_to_datetime64(float(text))
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in _DATETIME_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)  # naïf par convention
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError(repr(text))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return np.datetime64(parsed.isoformat(), "ns")


def parse_datetime(cell: Cell) -> np.datetime64:
    """Convertit une cellule en ``datetime64[ns]`` naïf ; ``ValueError`` si impossible."""
    if isinstance(cell, np.datetime64):
        if np.isnat(cell):
            raise ValueError(repr(cell))
        return np.datetime64(cell, "ns")
    if isinstance(cell, datetime):
        if cell.tzinfo is not None:
            cell = cell.astimezone(UTC).replace(tzinfo=None)
        return np.datetime64(cell.isoformat(), "ns")
    if isinstance(cell, bool):
        raise ValueError(repr(cell))
    if isinstance(cell, int | float):
        return _epoch_to_datetime64(float(cell))
    if isinstance(cell, str):
        return _parse_datetime_text(cell)
    raise ValueError(repr(cell))


def parse_direction(cell: Cell) -> int:
    """+1 achat, -1 vente ; ``ValueError`` pour tout autre jeton."""
    if isinstance(cell, bool):
        raise ValueError(repr(cell))
    if isinstance(cell, int | float):
        if cell == 1:
            return 1
        if cell == -1:
            return -1
        raise ValueError(repr(cell))
    if isinstance(cell, str):
        token = cell.strip().lower()
        if token in _DIRECTION_TOKENS:
            return _DIRECTION_TOKENS[token]
    raise ValueError(repr(cell))


def parse_int(cell: Cell) -> int:
    value = parse_float(cell)
    if not value.is_integer():
        raise ValueError(repr(cell))
    return int(value)


# ---------------------------------------------------------------------------
# colonnes
# ---------------------------------------------------------------------------


def _column(table: RawTable, name: str) -> list[Cell]:
    pos = table.columns.index(name)
    return [row[pos] for row in table.rows]


def _float_column(
    table: RawTable,
    mapping: Mapping[str, str],
    field_name: str,
    *,
    required: bool,
    strictly_positive: bool = False,
) -> FloatArray:
    if field_name not in mapping:
        return np.full(table.n, np.nan)
    column = mapping[field_name]
    out = np.full(table.n, np.nan)
    for i, (cell, line) in enumerate(zip(_column(table, column), table.line_numbers, strict=True)):
        if _is_missing(cell):
            if required:
                raise DataError("validate.missing_value", row=line, column=column)
            continue
        try:
            value = parse_float(cell)
        except ValueError as exc:
            raise DataError(
                "validate.bad_float", row=line, column=column, value=str(cell)
            ) from exc
        if strictly_positive and not value > 0:
            raise DataError("validate.nonpositive", row=line, column=column, value=value)
        out[i] = value
    return out


def _datetime_column(table: RawTable, mapping: Mapping[str, str], field_name: str) -> TimeArray:
    column = mapping[field_name]
    out = np.empty(table.n, dtype="datetime64[ns]")
    for i, (cell, line) in enumerate(zip(_column(table, column), table.line_numbers, strict=True)):
        if _is_missing(cell):
            raise DataError("validate.missing_value", row=line, column=column)
        try:
            out[i] = parse_datetime(cell)
        except ValueError as exc:
            raise DataError(
                "validate.bad_datetime", row=line, column=column, value=str(cell)
            ) from exc
    return out


def _direction_column(table: RawTable, mapping: Mapping[str, str]) -> Int8Array:
    if "direction" not in mapping:
        return np.zeros(table.n, dtype=np.int8)
    column = mapping["direction"]
    out = np.zeros(table.n, dtype=np.int8)
    for i, (cell, line) in enumerate(zip(_column(table, column), table.line_numbers, strict=True)):
        try:
            out[i] = parse_direction(cell)
        except ValueError as exc:
            raise DataError(
                "validate.bad_direction", row=line, column=column, value=str(cell)
            ) from exc
    return out


def _int_column(table: RawTable, mapping: Mapping[str, str], field_name: str) -> IntArray:
    if field_name not in mapping:
        return np.arange(table.n, dtype=np.int64)
    column = mapping[field_name]
    out = np.zeros(table.n, dtype=np.int64)
    for i, (cell, line) in enumerate(zip(_column(table, column), table.line_numbers, strict=True)):
        try:
            out[i] = parse_int(cell)
        except ValueError as exc:
            raise DataError("validate.bad_int", row=line, column=column, value=str(cell)) from exc
    return out


def _str_column(
    table: RawTable, mapping: Mapping[str, str], field_name: str, default: str
) -> list[str]:
    if field_name not in mapping:
        return [default] * table.n
    return [
        default if _is_missing(cell) else str(cell).strip()
        for cell in _column(table, mapping[field_name])
    ]


# ---------------------------------------------------------------------------
# contrôles
# ---------------------------------------------------------------------------


def _check_chronology(
    table: RawTable, mapping: Mapping[str, str], open_time: TimeArray, close_time: TimeArray
) -> None:
    bad = np.nonzero(close_time < open_time)[0]
    if bad.size:
        i = int(bad[0])
        raise DataError(
            "validate.close_before_open",
            row=table.line_numbers[i],
            column=mapping["close_time"],
            open_time=time_to_iso(open_time[i]),
            close_time=time_to_iso(close_time[i]),
        )


def _key(value: float) -> float | None:
    """NaN n'est pas égal à lui-même : on le remplace par None dans les signatures."""
    return None if np.isnan(value) else float(value)


def _check_duplicates(
    table: RawTable,
    mapping: Mapping[str, str],
    ticket: IntArray,
    signature: Sequence[tuple[object, ...]],
) -> None:
    if "ticket" in mapping:
        seen: dict[int, int] = {}
        for i, t in enumerate(ticket.tolist()):
            if t in seen:
                raise DataError(
                    "validate.duplicate_ticket",
                    row=table.line_numbers[i],
                    column=mapping["ticket"],
                    ticket=t,
                    first_row=table.line_numbers[seen[t]],
                )
            seen[t] = i
        return
    seen_rows: dict[tuple[object, ...], int] = {}
    for i, sig in enumerate(signature):
        if sig in seen_rows:
            raise DataError(
                "validate.duplicate_row",
                row=table.line_numbers[i],
                column=mapping["open_time"],
                first_row=table.line_numbers[seen_rows[sig]],
            )
        seen_rows[sig] = i


def _resolve_currency(
    table: RawTable, mapping: Mapping[str, str], currencies: list[str], override: str | None
) -> str:
    if "currency" in mapping:
        first = currencies[0]
        for i, cur in enumerate(currencies):
            if cur != first:
                raise DataError(
                    "validate.mixed_currency",
                    row=table.line_numbers[i],
                    column=mapping["currency"],
                    expected=first,
                    actual=cur,
                )
        return first
    if override is not None:
        return override
    return table.currency if table.currency is not None else "?"


def _resolve_initial_balance(table: RawTable, override: float | None) -> float | None:
    value = override if override is not None else table.initial_balance
    if value is not None and not value > 0:
        raise DataError("validate.bad_initial_balance", value=value)
    return value


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


def build_tradeset(
    table: RawTable,
    mapping: Mapping[str, str],
    *,
    initial_balance: float | None = None,
    currency: str | None = None,
) -> TradeSet:
    """Convertit une table brute en ``TradeSet`` canonique ou lève ``DataError``
    / ``SchemaError`` en nommant ligne et colonne."""
    return _build(table, mapping, initial_balance=initial_balance, currency=currency)[0]


def _build(
    table: RawTable,
    mapping: Mapping[str, str],
    *,
    initial_balance: float | None,
    currency: str | None,
) -> tuple[TradeSet, bool]:
    """Construction canonique ; le booléen dit si la source a dû être retriée."""
    check_schema(table, mapping)
    if table.n == 0:
        raise DataError("validate.no_rows")

    open_time = _datetime_column(table, mapping, "open_time")
    close_time = _datetime_column(table, mapping, "close_time")
    _check_chronology(table, mapping, open_time, close_time)

    gross = _float_column(table, mapping, "profit", required=True)
    commission = _float_column(table, mapping, "commission", required=False)
    swap = _float_column(table, mapping, "swap", required=False)
    profit = gross + np.nan_to_num(commission) + np.nan_to_num(swap)

    volume = _float_column(table, mapping, "volume", required=False, strictly_positive=True)
    open_price = _float_column(table, mapping, "open_price", required=False, strictly_positive=True)
    close_price = _float_column(
        table, mapping, "close_price", required=False, strictly_positive=True
    )
    stop_loss = _float_column(table, mapping, "stop_loss", required=False)
    take_profit = _float_column(table, mapping, "take_profit", required=False)
    # un SL/TP à 0 signifie « absent » chez MetaTrader
    stop_loss = np.where(stop_loss == 0, np.nan, stop_loss)
    take_profit = np.where(take_profit == 0, np.nan, take_profit)
    direction = _direction_column(table, mapping)
    ticket = _int_column(table, mapping, "ticket")
    symbol = _str_column(table, mapping, "symbol", default="?")
    currencies = _str_column(table, mapping, "currency", default="?")

    signature = [
        (str(open_time[i]), str(close_time[i]), _key(profit[i]), _key(volume[i]),
         symbol[i], int(direction[i]), _key(open_price[i]))
        for i in range(table.n)
    ]
    _check_duplicates(table, mapping, ticket, signature)
    resolved_currency = _resolve_currency(table, mapping, currencies, currency)
    resolved_balance = _resolve_initial_balance(table, initial_balance)

    order = np.lexsort((ticket, open_time.astype(np.int64), close_time.astype(np.int64)))
    resorted = bool(np.any(order != np.arange(table.n)))
    # la devise est « connue » dès qu'elle est résolue : colonne, en-tête du
    # rapport (table.currency) ou déclaration explicite — pas seulement colonne
    known = frozenset(
        f for f in ALL_FIELDS if f in mapping or (f == "currency" and resolved_currency != "?")
    )
    ts = TradeSet(
        open_time=open_time[order],
        close_time=close_time[order],
        profit=profit[order],
        direction=direction[order],
        volume=volume[order],
        symbol=np.array(symbol, dtype=np.str_)[order],
        open_price=open_price[order],
        close_price=close_price[order],
        stop_loss=stop_loss[order],
        take_profit=take_profit[order],
        ticket=ticket[order],
        currency=resolved_currency,
        initial_balance=resolved_balance,
        fingerprint=table.fingerprint,
        known_fields=known,
    )
    return ts, resorted


# ---------------------------------------------------------------------------
# constats (non bloquants sauf la ruine)
# ---------------------------------------------------------------------------


def find_gaps(ts: TradeSet, max_gap_days: float) -> Finding | None:
    """Trou entre deux clôtures consécutives au-delà de ``max_gap_days``."""
    if ts.n < 2:
        return None
    gaps_days = np.diff(ts.close_time.astype(np.int64)).astype(np.float64) / NS_PER_DAY
    over = np.nonzero(gaps_days > max_gap_days)[0]
    if over.size == 0:
        return None
    worst = int(over[np.argmax(gaps_days[over])])
    return Finding.make(
        "gap",
        Severity.MINOR,
        "validate.gap",
        SOURCE,
        count=int(over.size),
        days=float(gaps_days[worst]),
        start=time_to_iso(ts.close_time[worst]),
        end=time_to_iso(ts.close_time[worst + 1]),
        max_gap_days=float(max_gap_days),
    )


def find_ruin(ts: TradeSet) -> tuple[Finding | None, int | None]:
    """D-03 : premier trade après lequel l'equity est ≤ 0.

    Retourne le constat bloquant et l'index (ordre canonique) du trade fautif.
    Sans solde initial connu, la ruine n'est pas évaluable et rien n'est levé.
    """
    if ts.initial_balance is None or ts.n == 0:
        return None, None
    equity = ts.equity
    hit = np.nonzero(equity <= 0)[0]
    if hit.size == 0:
        return None, None
    idx = int(hit[0])
    finding = Finding.make(
        "ruin",
        Severity.BLOCKING,
        "validate.ruin",
        SOURCE,
        trade_index=idx + 1,
        time=time_to_iso(ts.close_time[idx]),
        equity=float(equity[idx]),
        initial_balance=float(ts.initial_balance),
    )
    return finding, idx


def missing_optional_finding(ts: TradeSet) -> Finding | None:
    missing = [f for f in ALL_FIELDS if f not in REQUIRED_FIELDS and not ts.has(f)]
    if not missing:
        return None
    return Finding.make(
        "missing_optional",
        Severity.INFO,
        "validate.missing_optional",
        SOURCE,
        fields=", ".join(missing),
    )


def validate(
    table: RawTable,
    mapping: Mapping[str, str],
    *,
    max_gap_days: float,
    initial_balance: float | None = None,
    currency: str | None = None,
) -> ValidationResult:
    """Chaîne complète : construction canonique puis constats."""
    ts, resorted = _build(table, mapping, initial_balance=initial_balance, currency=currency)
    findings: list[Finding] = [
        Finding(key.rsplit(".", 1)[-1], Severity.INFO, key, "reader", params)
        for key, params in table.notes
    ]
    if resorted:
        findings.append(Finding.make("resorted", Severity.INFO, "validate.resorted", SOURCE))
    optional = missing_optional_finding(ts)
    if optional is not None:
        findings.append(optional)
    if ts.initial_balance is None:
        findings.append(
            Finding.make(
                "no_initial_balance", Severity.MINOR, "validate.no_initial_balance", SOURCE
            )
        )
    gap = find_gaps(ts, max_gap_days)
    if gap is not None:
        findings.append(gap)
    ruin, ruin_index = find_ruin(ts)
    if ruin is not None:
        findings.append(ruin)
    return ValidationResult(ts, tuple(findings), ruin_index)

