# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lecteurs : csv générique, csv MT5, rapport HTML MT5 (historique de compte),
rapport du Strategy Tester MT5 (HTML ou Open XML), rapport détaillé MT4,
export Deriv, DataFrame.

``read_table`` choisit le lecteur d'après l'extension puis l'en-tête ; le
lecteur choisi est inscrit dans ``RawTable.source``.
"""

from __future__ import annotations

from pathlib import Path

from qaudit.core.models import RawTable
from qaudit.io.readers.common import decode_bytes, fingerprint_bytes
from qaudit.io.readers.csv_generic import parse_csv_text
from qaudit.io.readers.deriv import deriv_table, looks_like_deriv
from qaudit.io.readers.mt4_html import is_mt4_html, parse_mt4_html
from qaudit.io.readers.mt5_csv import looks_like_mt5, mt5_table
from qaudit.io.readers.mt5_html import parse_mt5_html
from qaudit.io.readers.mt5_tester import is_tester_html, parse_mt5_tester

KINDS: tuple[str, ...] = (
    "auto", "csv", "mt5_csv", "mt5_html", "mt5_tester", "mt4_html", "deriv",
)
TABLE_SUFFIXES: tuple[str, ...] = (".csv", ".txt", ".html", ".htm", ".xlsx")


def read_table(path: Path, kind: str = "auto") -> RawTable:
    """Lit un fichier de trades avec le lecteur demandé ou détecté."""
    data = path.read_bytes()
    fingerprint = fingerprint_bytes(data)
    suffix = path.suffix.lower()
    if kind == "mt5_tester" or (kind == "auto" and suffix == ".xlsx"):
        return parse_mt5_tester(data, fingerprint, suffix)
    text = decode_bytes(data)
    if kind == "mt4_html":
        return parse_mt4_html(text, fingerprint)
    if kind == "mt5_html" or (kind == "auto" and suffix in (".html", ".htm")):
        if kind == "auto" and is_tester_html(text):
            return parse_mt5_tester(data, fingerprint, suffix)
        if kind == "auto" and is_mt4_html(text):
            return parse_mt4_html(text, fingerprint)
        return parse_mt5_html(text, fingerprint)
    table = parse_csv_text(text, fingerprint)
    if kind == "mt5_csv" or (kind == "auto" and looks_like_mt5(table.columns)):
        return mt5_table(table)
    if kind == "deriv" or (kind == "auto" and looks_like_deriv(table.columns)):
        return deriv_table(table)
    return table
