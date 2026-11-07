# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rapport du Strategy Tester MT5 synthétique : tables Orders + Deals (pas de
Positions), HTML en UTF-16 LE avec BOM comme le testeur, et export Open XML.

Les 600 trades du témoin sain y apparaissent comme deals ``in`` / ``out`` ;
commission −0,35 par côté, profit du deal de sortie = profit net du témoin
+ 0,70 : la table reconstituée doit donner exactement les profits nets du
témoin. Appelé par ``generate.py``.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from tests.fixtures.generate import PIP, Trade, _exit_price, _iso

ORDERS_HEADER = ["Open Time", "Order", "Symbol", "Type", "Volume", "Price", "S / L", "T / P",
                 "Time", "State", "Comment"]
DEALS_HEADER = ["Time", "Deal", "Symbol", "Type", "Direction", "Volume", "Price", "Order",
                "Commission", "Swap", "Profit", "Balance", "Comment"]
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def tester_tables(trades: list[Trade]) -> tuple[list[list[str]], list[list[str]]]:
    """(lignes Orders, lignes Deals) triées par heure ; un ordre par deal."""
    events: list[tuple[int, int, Trade, str]] = []
    for i, t in enumerate(sorted(trades, key=lambda x: (x.open_ns, x.close_ns)), start=1):
        events.append((t.open_ns, i, t, "in"))
        events.append((t.close_ns, i, t, "out"))
    events.sort(key=lambda e: (e[0], e[3] == "in", e[1]))
    orders: list[list[str]] = []
    deals: list[list[str]] = [[
        "2021.01.01 00:00:00", "1", "", "balance", "", "", "", "", "0.00", "0.00", "10 000.00",
        "10 000.00", "",
    ]]
    balance = 10_000.0
    number = 1
    for when, _i, t, kind in events:
        number += 1
        side = t.direction if kind == "in" else -t.direction
        side_text = "buy" if side > 0 else "sell"
        price = t.open_price if kind == "in" else _exit_price(t)
        sl = "" if t.sl is None else f"{t.sl:.5f}"
        tp = f"{t.open_price + t.direction * 60 * PIP:.5f}"
        stamp = _iso(when).replace("-", ".")
        orders.append([
            stamp, str(number), t.symbol, side_text, f"{t.volume:.2f} / {t.volume:.2f}",
            f"{price:.5f}", sl if kind == "in" else "", tp if kind == "in" else "", stamp,
            "filled", "",
        ])
        profit = 0.0 if kind == "in" else t.profit + 0.70
        balance += profit - 0.35
        comment = "" if kind == "in" or t.sl is None or t.profit >= 0 else f"sl {t.sl:.5f}"
        deals.append([
            stamp, str(number), t.symbol, side_text, kind, f"{t.volume:.2f}", f"{price:.5f}",
            str(number), "-0.35", "0.00", _money(profit), _money(balance), comment,
        ])
    return orders, deals


def _row(cells: list[str], tag: str = "td") -> str:
    return "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>"


def tester_html(orders: list[list[str]], deals: list[list[str]]) -> str:
    def setting(label: str, value: str) -> str:
        return f"<tr><td colspan='2'>{label}</td><td colspan='11'><b>{value}</b></td></tr>"

    head = [
        ("<html><head><title>Strategy Tester Report</title>"
         "<meta http-equiv='Content-Type' content='text/html; charset=utf-16'></head><body>"),
        "<table>",
        "<tr><th colspan='13'>Strategy Tester Report</th></tr>",
        "<tr><th colspan='13'>MetaQuotes-Demo (Build 4000)</th></tr>",
        "<tr><td colspan='13'><b>Settings</b></td></tr>",
        setting("Expert:", "Witness EA"),
        setting("Symbol:", "EURUSD"),
        setting("Period:", "H1 (2021.01.01 - 2024.03.01)"),
        setting("Inputs:", "Risk=0.5"),
        setting("Currency:", "USD"),
        setting("Initial Deposit:", "10 000.00"),
        setting("Leverage:", "1:100"),
        "<tr><td colspan='13'><b>Results</b></td></tr>",
        setting("History Quality:", "100%"),
        "<tr><td colspan='13'><b>Orders</b></td></tr>",
        _row(ORDERS_HEADER),
    ]
    body = [_row(o) for o in orders]
    body.append("<tr><td colspan='13'><b>Deals</b></td></tr>")
    body.append(_row(DEALS_HEADER))
    body.extend(_row(d) for d in deals)
    body.append("<tr><td colspan='8'></td><td>-420.00</td><td>0.00</td><td>x</td><td>y</td>"
                "<td></td></tr>")
    body.append("</table></body></html>")
    return "\n".join(head + body) + "\n"


def _column(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def tester_xlsx(orders: list[list[str]], deals: list[list[str]]) -> bytes:
    """Classeur Open XML minimal (feuille unique, chaînes en ligne), déterministe."""
    lines: list[list[str]] = [
        ["Strategy Tester Report"], ["Settings"], ["Expert:", "Witness EA"],
        ["Symbol:", "EURUSD"], ["Currency:", "USD"], ["Initial Deposit:", "10000"],
        ["Orders"], ORDERS_HEADER, *orders, ["Deals"], DEALS_HEADER, *deals,
    ]
    rows_xml = []
    for r, values in enumerate(lines, start=1):
        cells = "".join(
            f'<c r="{_column(c)}{r}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
            for c, v in enumerate(values) if v != ""
        )
        rows_xml.append(f'<row r="{r}">{cells}</row>')
    sheet = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{NS}">'
             f"<sheetData>{''.join(rows_xml)}</sheetData></worksheet>")
    workbook = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{NS}" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    doc_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    xml_head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    rels = (f'{xml_head}<Relationships xmlns="{rel_ns}"><Relationship Id="rId1" '
            f'Type="{doc_rel}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
    root_rels = (f'{xml_head}<Relationships xmlns="{rel_ns}"><Relationship Id="rId1" '
                 f'Type="{doc_rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    ct = "http://schemas.openxmlformats.org/package/2006/content-types"
    types = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="{ct}">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
             'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
             'officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/'
             'sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.'
             'worksheet+xml"/></Types>')
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in (("[Content_Types].xml", types), ("_rels/.rels", root_rels),
                              ("xl/workbook.xml", workbook), ("xl/_rels/workbook.xml.rels", rels),
                              ("xl/worksheets/sheet1.xml", sheet)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return buffer.getvalue()


def write_tester(folder: Path, trades: list[Trade]) -> None:
    orders, deals = tester_tables(trades)
    (folder / "mt5_tester_report.html").write_bytes(tester_html(orders, deals).encode("utf-16"))
    (folder / "mt5_tester_report.xlsx").write_bytes(tester_xlsx(orders, deals))
