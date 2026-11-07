# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lecteur du rapport détaillé MetaTrader 4 : section « Closed Transactions »
seule, dépôt initial, positions ouvertes et ordres en attente écartés, en-têtes
localisés, taxes ajoutées à la commission, verdict identique au témoin CSV."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from qaudit.cli.main import main
from qaudit.core.errors import DataError
from qaudit.core.validate import validate
from qaudit.io.readers import KINDS, read_table
from qaudit.io.readers.common import infer_mapping
from qaudit.io.readers.mt4_html import is_mt4_html, parse_mt4_html
from tests.fixtures import generate
from tests.fixtures import mt4_fixture as mf

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_mt4_statement_reconstructs_the_witness_exactly() -> None:
    table = read_table(FIXTURES / "mt4_statement.html")
    assert table.source == "mt4_html"
    assert table.n == 600
    assert table.currency == "USD"
    assert table.initial_balance == 10_000.0
    ts = validate(table, infer_mapping(table.columns), max_gap_days=30.0).tradeset
    witness = read_table(FIXTURES / "healthy_witness.csv")
    ref = validate(witness, infer_mapping(witness.columns), max_gap_days=30.0).tradeset
    assert np.array_equal(ts.profit, ref.profit)
    assert np.array_equal(ts.open_time, ref.open_time)
    assert np.array_equal(ts.close_time, ref.close_time)
    assert np.array_equal(ts.volume, ref.volume)
    assert np.array_equal(ts.direction, ref.direction)
    assert set(ts.symbol.tolist()) == {"EURUSD"}
    assert ts.has("stop_loss")
    assert "mt4_html" in KINDS


def test_mt4_verdict_matches_the_csv_witness(tmp_path: Path) -> None:
    for name, path in (("mt4", FIXTURES / "mt4_statement.html"),
                       ("csv", FIXTURES / "healthy_witness.csv")):
        code = main(["audit", str(path), "--out", str(tmp_path / name), "--initial-balance",
                     "10000", "--currency", "USD", "--name", "w", "--n-iter", "400",
                     "--cache-dir", str(tmp_path / "c"), "--registry", str(tmp_path / "r.jsonl")])
        assert code == 1
    mt4 = json.loads((tmp_path / "mt4" / "archive" / "w.json").read_text(encoding="utf-8"))
    csv = json.loads((tmp_path / "csv" / "archive" / "w.json").read_text(encoding="utf-8"))
    # le CSV n'a ni commission ni swap : un constat « champs absents » de plus,
    # sans effet sur le verdict ni sur un seul chiffre
    assert mt4["verdict"]["decision"] == csv["verdict"]["decision"]
    assert mt4["verdict"]["barriers"] == csv["verdict"]["barriers"]
    for key in ("metrics", "significance", "resampling"):
        assert mt4[key] == csv[key], key


def test_open_trades_working_orders_and_summary_are_ignored() -> None:
    trades = generate.healthy_witness()[:40]
    table = parse_mt4_html(mf.mt4_statement(trades), "0" * 64)
    assert table.n == 40  # ni la position ouverte 9999, ni l'ordre « sell limit »
    tickets = {row[0] for row in table.rows}
    assert "9999" not in tickets
    assert "9998" not in tickets


def test_french_headers_taxes_and_currency_label() -> None:
    trades = generate.healthy_witness()[:5]
    html = mf.mt4_statement(trades, header=mf.HEADER_FR, currency_label="Devise")
    zeros = "<td>0.00</td><td>0.00</td><td>0.00</td>"
    html = html.replace(zeros, "<td>-0.70</td><td>-0.30</td><td>0.00</td>", 1)
    assert is_mt4_html(html)
    table = parse_mt4_html(html, "0" * 64)
    assert table.n == 5
    assert table.currency == "USD"
    assert table.rows[0][10] == "-1.00"  # commission + taxes


def test_mt5_account_report_is_not_taken_for_mt4() -> None:
    mt5 = (FIXTURES / "mt5_report.html").read_text(encoding="utf-8", errors="replace")
    assert not is_mt4_html(mt5)
    assert read_table(FIXTURES / "mt5_report.html").source == "mt5_html"


def test_mt4_kind_forced_on_a_non_mt4_file_names_the_error(tmp_path: Path) -> None:
    with pytest.raises(DataError) as info:
        read_table(FIXTURES / "healthy_witness.csv", kind="mt4_html")
    assert info.value.key == "reader.mt4_closed_not_found"
