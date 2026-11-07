# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rapport détaillé MetaTrader 4 (« Save as Detailed Report ») synthétique,
construit depuis le témoin sain : en-tête de compte, section « Closed
Transactions » (ligne de dépôt incluse), « Open Trades » (une position ouverte,
à écarter), « Working Orders », « Summary ». Encodage windows-1252 comme MT4.
Appelé par ``generate.py``.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.generate import PIP, Trade, _exit_price, _iso

HEADER = ["Ticket", "Open Time", "Type", "Size", "Item", "Price", "S / L", "T / P", "Close Time",
          "Price", "Commission", "Taxes", "Swap", "Profit"]
HEADER_FR = ["Ticket", "Heure d'ouverture", "Type", "Taille", "Item", "Prix", "S / L", "T / P",
             "Heure de fermeture", "Prix", "Commission", "Taxes", "Swap", "Profit"]


def _money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def _row(cells: list[str], align: str = "right") -> str:
    return f'<tr align="{align}">' + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def mt4_statement(trades: list[Trade], header: list[str] | None = None,
                  currency_label: str = "Currency") -> str:
    """HTML du rapport détaillé ; ``header`` permet la variante localisée."""
    header = header or HEADER
    ordered = sorted(trades, key=lambda t: (t.close_ns, t.open_ns))
    stamp = _iso(ordered[0].open_ns - 3_600_000_000_000).replace("-", ".")
    lines = [
        (
            "<html><head><title>Statement: 1234567 - Demo</title>"
            '<meta http-equiv="Content-Type" content="text/html; charset=windows-1252"></head>'
        ),
        "<body><div align=center><table cellspacing=1 cellpadding=3 border=0>",
        (
            "<tr align=left><td colspan=2><b>Account: 1234567</b></td>"
            "<td colspan=6><b>Name: Témoin Sain</b></td>"
            f"<td colspan=3><b>{currency_label}: USD</b></td>"
            "<td colspan=3><b>Leverage: 1:100</b></td></tr>"
        ),
        '<tr align=center bgcolor="#C0C0C0"><td colspan=14><b>Closed Transactions:</b></td></tr>',
        _row(header, "center"),
        (
            f'<tr align="right"><td>1000</td><td class=msdate>{stamp}</td><td>balance</td>'
            f"<td colspan=9>Deposit</td><td colspan=2>{_money(10_000.0)}</td></tr>"
        ),
    ]
    for i, t in enumerate(ordered, start=1001):
        tp = t.open_price + t.direction * 60 * PIP
        lines.append(_row([
            str(i), _iso(t.open_ns).replace("-", "."), "buy" if t.direction > 0 else "sell",
            f"{t.volume:.2f}", t.symbol.lower(), f"{t.open_price:.5f}",
            "" if t.sl is None else f"{t.sl:.5f}", f"{tp:.5f}",
            _iso(t.close_ns).replace("-", "."), f"{_exit_price(t):.5f}", "0.00", "0.00", "0.00",
            _money(t.profit),
        ]))
    total = sum(t.profit for t in ordered)
    lines += [
        (
            f'<tr align="right"><td colspan=10><b>Closed P/L:</b></td>'
            f"<td colspan=4><b>{_money(total)}</b></td></tr>"
        ),
        '<tr align=center bgcolor="#C0C0C0"><td colspan=14><b>Open Trades:</b></td></tr>',
        _row([*header[:8], "", *header[9:]], "center"),
        _row(["9999", "2024.03.01 10:00:00", "buy", "0.10", "eurusd", "1.08000", "", "", "",
              "1.08100", "0.00", "0.00", "0.00", "10.00"]),
        '<tr align="right"><td colspan=13><b>Floating P/L:</b></td><td><b>10.00</b></td></tr>',
        '<tr align=center bgcolor="#C0C0C0"><td colspan=14><b>Working Orders:</b></td></tr>',
        _row(["9998", "2024.03.01 11:00:00", "sell limit", "0.10", "eurusd", "1.09000", "", "",
              "", "1.08500", "", "", "", ""]),
        '<tr align=center bgcolor="#C0C0C0"><td colspan=14><b>Summary:</b></td></tr>',
        (
            '<tr align="right"><td colspan=3><b>Deposit/Withdrawal:</b></td>'
            f"<td><b>{_money(10_000.0)}</b></td></tr>"
        ),
        "</table></div></body></html>",
    ]
    return "\n".join(lines) + "\n"


def write_mt4(folder: Path, trades: list[Trade]) -> None:
    (folder / "mt4_statement.html").write_bytes(mt4_statement(trades).encode("cp1252"))
