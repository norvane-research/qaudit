# SPDX-License-Identifier: AGPL-3.0-or-later
"""Constructeurs de fixtures partagés par les tests. Rien ici n'est aléatoire
sans générateur explicite."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from qaudit.core.models import Cell, RawTable, TradeSet

FAKE_FINGERPRINT = "0" * 64

STANDARD_COLUMNS: tuple[str, ...] = (
    "ticket",
    "open_time",
    "close_time",
    "symbol",
    "direction",
    "volume",
    "open_price",
    "close_price",
    "sl",
    "tp",
    "profit",
)

STANDARD_MAPPING: dict[str, str] = {
    "ticket": "ticket",
    "open_time": "open_time",
    "close_time": "close_time",
    "symbol": "symbol",
    "direction": "direction",
    "volume": "volume",
    "open_price": "open_price",
    "close_price": "close_price",
    "stop_loss": "sl",
    "take_profit": "tp",
    "profit": "profit",
}

MINIMAL_MAPPING: dict[str, str] = {
    "open_time": "open_time",
    "close_time": "close_time",
    "profit": "profit",
}


def make_table(
    columns: Sequence[str],
    rows: Sequence[Sequence[Cell]],
    *,
    first_line: int = 2,
    initial_balance: float | None = None,
    currency: str | None = None,
    source: str = "test",
) -> RawTable:
    """Table brute dont les lignes sont numérotées à partir de ``first_line``
    (2 = juste après l'en-tête d'un CSV)."""
    return RawTable(
        columns=tuple(columns),
        rows=tuple(tuple(r) for r in rows),
        line_numbers=tuple(range(first_line, first_line + len(rows))),
        fingerprint=FAKE_FINGERPRINT,
        source=source,
        initial_balance=initial_balance,
        currency=currency,
    )


def standard_row(
    i: int,
    profit: float,
    *,
    volume: float = 0.1,
    direction: str = "buy",
    open_time: str | None = None,
    close_time: str | None = None,
    sl: float | str = 1.0950,
) -> list[Cell]:
    """Ligne conforme aux STANDARD_COLUMNS, ``i`` décalant les horodatages de 6 h."""
    base = np.datetime64("2021-01-04T09:00:00")
    ot = open_time if open_time is not None else str(base + np.timedelta64(6 * i, "h"))
    ct = close_time if close_time is not None else str(base + np.timedelta64(6 * i + 3, "h"))
    return [i + 1, ot, ct, "EURUSD", direction, volume, 1.1000, 1.1010, sl, 1.1100, profit]


def make_tradeset(
    profit: Sequence[float] | NDArray[np.float64],
    *,
    start: str = "2021-01-04T09:00:00",
    step_hours: float = 6.0,
    hold_hours: float | None = None,
    initial_balance: float | None = 10_000.0,
    volume: Sequence[float] | NDArray[np.float64] | None = None,
    direction: Sequence[int] | NDArray[np.int64] | None = None,
    symbol: str | Sequence[str] = "EURUSD",
    open_price: Sequence[float] | NDArray[np.float64] | None = None,
    close_price: Sequence[float] | NDArray[np.float64] | None = None,
    stop_loss: Sequence[float] | NDArray[np.float64] | None = None,
    take_profit: Sequence[float] | NDArray[np.float64] | None = None,
    known: frozenset[str] | None = None,
    currency: str = "USD",
) -> TradeSet:
    """TradeSet synthétique : trades régulièrement espacés, ouverts ``step_hours``
    l'un après l'autre et tenus ``hold_hours`` (moitié du pas par défaut)."""
    p = np.asarray(profit, dtype=np.float64)
    n = p.size
    hold = step_hours / 2 if hold_hours is None else hold_hours
    t0 = np.datetime64(start, "ns")
    step_ns = np.int64(round(step_hours * 3_600_000_000_000))
    hold_ns = np.int64(round(hold * 3_600_000_000_000))
    open_time = t0 + np.arange(n, dtype=np.int64) * step_ns
    close_time = open_time + hold_ns
    vol = np.full(n, 0.1) if volume is None else np.asarray(volume, dtype=np.float64)
    dirn = np.ones(n, dtype=np.int8) if direction is None else np.asarray(direction, dtype=np.int8)
    sym = np.full(n, symbol) if isinstance(symbol, str) else np.asarray(symbol, dtype=np.str_)
    op = np.full(n, 1.1) if open_price is None else np.asarray(open_price, dtype=np.float64)
    cp = np.full(n, 1.1) + np.sign(p) * 0.001 if close_price is None else np.asarray(close_price)
    sl = np.full(n, np.nan) if stop_loss is None else np.asarray(stop_loss, dtype=np.float64)
    tp = np.full(n, np.nan) if take_profit is None else np.asarray(take_profit, dtype=np.float64)
    if known is None:
        known_fields = {"open_time", "close_time", "profit", "volume", "direction", "symbol",
                        "open_price", "close_price"}
        if stop_loss is not None:
            known_fields.add("stop_loss")
        if take_profit is not None:
            known_fields.add("take_profit")
        known = frozenset(known_fields)
    return TradeSet(
        open_time=open_time,
        close_time=close_time,
        profit=p,
        direction=dirn,
        volume=vol,
        symbol=sym,
        open_price=op,
        close_price=np.asarray(cp, dtype=np.float64),
        stop_loss=sl,
        take_profit=tp,
        ticket=np.arange(1, n + 1, dtype=np.int64),
        currency=currency,
        initial_balance=initial_balance,
        fingerprint=FAKE_FINGERPRINT,
        known_fields=known,
    )
