# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rapport du Strategy Tester MT5 : reconstitution des trades clos depuis les
deals (HTML UTF-16 et Open XML), cas de bord construits à la main."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from qaudit.core.audit import AuditOptions, run_audit
from qaudit.core.errors import DataError
from qaudit.core.models import Severity
from qaudit.core.validate import validate
from qaudit.io.method import load_method
from qaudit.io.readers import KINDS, read_table
from qaudit.io.readers.common import infer_mapping
from qaudit.io.readers.mt5_tester import (
    DEALS_HEADER,
    build_table,
    is_tester_html,
    parse_mt5_tester_html,
    xlsx_rows,
)
from tests.fixtures import tester_fixture as tf

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _witness_profits() -> np.ndarray:
    table = read_table(FIXTURES / "healthy_witness.csv")
    ts = validate(table, infer_mapping(table.columns), max_gap_days=30.0).tradeset
    return np.sort(ts.profit)


@pytest.mark.parametrize("name", ["mt5_tester_report.html", "mt5_tester_report.xlsx"])
def test_tester_report_rebuilds_exactly_the_witness_trades(name: str) -> None:
    table = read_table(FIXTURES / name)
    assert table.source == "mt5_tester"
    assert table.n == 600
    assert table.initial_balance == 10_000.0
    assert table.currency == "USD"
    assert table.notes == ()
    ts = validate(table, infer_mapping(table.columns), max_gap_days=30.0).tradeset
    # profit net = profit du deal de sortie (+0,70) + commission d'entrée + de sortie (−0,35 × 2)
    np.testing.assert_allclose(np.sort(ts.profit), _witness_profits(), atol=1e-9)
    assert ts.has("stop_loss")
    assert int(np.isfinite(ts.stop_loss).sum()) == 600
    assert len(set(ts.ticket.tolist())) == 600
    assert set(ts.direction.tolist()) == {1, -1}
    assert ts.initial_balance == 10_000.0


def test_html_is_utf16_with_bom_like_the_terminal_and_detected_as_tester() -> None:
    raw = (FIXTURES / "mt5_tester_report.html").read_bytes()
    assert raw[:2] == b"\xff\xfe"
    text = raw.decode("utf-16")
    assert is_tester_html(text)
    account = (FIXTURES / "mt5_report.html").read_text(encoding="utf-8")
    assert not is_tester_html(account)  # le rapport de compte a une table Positions


def test_tester_verdict_equals_the_witness_verdict() -> None:
    config = load_method()
    options = AuditOptions(seed=1, n_iter=1500)
    results = {}
    for name, balance in (("healthy_witness.csv", 10_000.0), ("mt5_tester_report.html", None)):
        table = read_table(FIXTURES / name)
        validation = validate(table, infer_mapping(table.columns), max_gap_days=config.max_gap_days,
                              initial_balance=balance)
        results[name] = run_audit(validation, config, options)
    witness, tester = results["healthy_witness.csv"], results["mt5_tester_report.html"]
    assert tester.verdict.decision == witness.verdict.decision
    assert tester.metrics.net_profit == pytest.approx(witness.metrics.net_profit)
    assert tester.metrics.profit_factor == pytest.approx(witness.metrics.profit_factor)
    assert tester.metrics.sharpe_trade == pytest.approx(witness.metrics.sharpe_trade)
    assert tester.dsr_result.dsr == pytest.approx(witness.dsr_result.dsr)


# ---------------------------------------------------------------------------
# cas construits à la main
# ---------------------------------------------------------------------------


def _report(deals: list[list[str]], orders: list[list[str]] | None = None) -> str:
    return tf.tester_html(orders or [], [
        ["2021.01.01 00:00:00", "1", "", "balance", "", "", "", "", "0.00", "0.00", "5 000.00",
         "5 000.00", ""],
        *deals,
    ])


def _deal(time: str, number: int, kind: str, direction: str, volume: str, price: str,
          profit: str = "0.00", commission: str = "0.00", swap: str = "0.00",
          symbol: str = "EURUSD", order: str | None = None) -> list[str]:
    return [time, str(number), symbol, kind, direction, volume, price, order or str(number),
            commission, swap, profit, "0.00", ""]


def test_partial_close_splits_the_lot_and_prorates_profit() -> None:
    deals = [
        _deal("2021.01.04 09:00:00", 2, "buy", "in", "0.30", "1.1000", commission="-0.90"),
        _deal("2021.01.04 12:00:00", 3, "sell", "out", "0.10", "1.1020", profit="20.00",
              commission="-0.30"),
        _deal("2021.01.04 15:00:00", 4, "sell", "out", "0.20", "1.1030", profit="60.00",
              commission="-0.60", swap="-1.00"),
    ]
    table = parse_mt5_tester_html(_report(deals), "0" * 64)
    assert table.n == 2
    assert table.initial_balance == 5_000.0
    rows = {row[5]: row for row in table.rows}  # par volume
    first, second = rows[0.1], rows[0.2]
    assert first[1] == "2021.01.04 09:00:00"
    assert first[2] == "2021.01.04 12:00:00"
    assert first[12] == pytest.approx(20.0)
    assert first[10] == pytest.approx(-0.90 / 3 - 0.30)  # commission d'entrée au prorata + sortie
    assert second[12] == pytest.approx(60.0)
    assert second[11] == pytest.approx(-1.0)
    assert first[0] != second[0]  # tickets séquentiels : un trade clos = un ticket


def test_reversal_in_out_closes_then_opens() -> None:
    deals = [
        _deal("2021.01.04 09:00:00", 2, "buy", "in", "0.10", "1.1000"),
        _deal("2021.01.04 12:00:00", 3, "sell", "in/out", "0.30", "1.1010", profit="10.00"),
        _deal("2021.01.04 15:00:00", 4, "buy", "out", "0.20", "1.0990", profit="40.00"),
    ]
    table = parse_mt5_tester_html(_report(deals), "0" * 64)
    assert table.n == 2
    long_trade, short_trade = sorted(table.rows, key=lambda r: str(r[2]))
    assert (long_trade[4], long_trade[5]) == ("buy", 0.1)
    assert long_trade[12] == pytest.approx(10.0)  # tout le profit du deal in/out va au clos
    assert (short_trade[4], short_trade[5]) == ("sell", 0.2)
    assert short_trade[12] == pytest.approx(40.0)
    assert short_trade[1] == "2021.01.04 12:00:00"
    assert table.notes == ()


def test_overlapping_positions_prefer_equal_volume_then_fifo_and_are_flagged() -> None:
    # deux achats ouverts (0,10 puis 0,20) ; la sortie de 0,20 doit aller au second
    deals = [
        _deal("2021.01.04 09:00:00", 2, "buy", "in", "0.10", "1.1000"),
        _deal("2021.01.04 10:00:00", 3, "buy", "in", "0.20", "1.1005"),
        _deal("2021.01.04 12:00:00", 4, "sell", "out", "0.20", "1.1030", profit="50.00"),
        _deal("2021.01.04 13:00:00", 5, "sell", "out", "0.10", "1.1040", profit="40.00"),
    ]
    table = parse_mt5_tester_html(_report(deals), "0" * 64)
    by_volume = {row[5]: row for row in table.rows}
    assert by_volume[0.2][12] == 50.0
    assert by_volume[0.2][6] == 1.1005  # entrée du second achat (volume égal)
    assert by_volume[0.1][12] == 40.0
    assert by_volume[0.1][6] == 1.1000
    assert table.notes == ()  # égalité de volume : aucune ambiguïté
    # même volumes : FIFO, et l'ambiguïté est signalée si la sortie fractionne
    deals2 = [
        _deal("2021.01.04 09:00:00", 2, "buy", "in", "0.10", "1.1000"),
        _deal("2021.01.04 10:00:00", 3, "buy", "in", "0.10", "1.1005"),
        _deal("2021.01.04 12:00:00", 4, "sell", "out", "0.15", "1.1030", profit="30.00"),
        _deal("2021.01.04 13:00:00", 5, "sell", "out", "0.05", "1.1040", profit="5.00"),
    ]
    table2 = parse_mt5_tester_html(_report(deals2), "0" * 64)
    assert table2.n == 3
    assert dict(table2.notes)["reader.tester_ambiguous"] == (("count", 1),)
    validation = validate(table2, infer_mapping(table2.columns), max_gap_days=30.0)
    flagged = [f for f in validation.findings if f.code == "tester_ambiguous"]
    assert flagged
    assert flagged[0].severity == Severity.INFO
    assert flagged[0].source == "reader"


def test_open_positions_at_the_end_are_discarded_and_counted() -> None:
    deals = [
        _deal("2021.01.04 09:00:00", 2, "buy", "in", "0.10", "1.1000"),
        _deal("2021.01.04 12:00:00", 3, "sell", "out", "0.10", "1.1020", profit="20.00"),
        _deal("2021.01.05 09:00:00", 4, "sell", "in", "0.10", "1.1000"),
    ]
    table = parse_mt5_tester_html(_report(deals), "0" * 64)
    assert table.n == 1
    assert dict(table.notes)["reader.tester_open_positions"] == (("count", 1),)


def test_stop_and_target_come_from_the_orders_table() -> None:
    orders = [["2021.01.04 09:00:00", "2", "EURUSD", "buy", "0.10 / 0.10", "1.10000",
               "1.09500", "1.11000", "2021.01.04 09:00:00", "filled", ""]]
    deals = [
        _deal("2021.01.04 09:00:00", 2, "buy", "in", "0.10", "1.1000"),
        _deal("2021.01.04 12:00:00", 3, "sell", "out", "0.10", "1.1020", profit="20.00"),
    ]
    table = parse_mt5_tester_html(_report(deals, orders), "0" * 64)
    row = table.rows[0]
    assert (row[8], row[9]) == (1.095, 1.11)
    ts = validate(table, infer_mapping(table.columns), max_gap_days=30.0).tradeset
    assert ts.stop_loss[0] == pytest.approx(1.095)


def test_errors_are_named() -> None:
    with pytest.raises(DataError) as info:
        parse_mt5_tester_html("<html><table><tr><td>rien</td></tr></table></html>", "0" * 64)
    assert info.value.key == "reader.mt5_tester_no_deals"
    bad = _report([_deal("2021.01.04 09:00:00", 2, "buy", "in", "abc", "1.1000")])
    with pytest.raises(DataError) as info2:
        parse_mt5_tester_html(bad, "0" * 64)
    assert info2.value.key == "reader.mt5_tester_bad_deal"
    assert info2.value.row is not None
    only_open = _report([_deal("2021.01.04 09:00:00", 2, "buy", "in", "0.10", "1.1000")])
    with pytest.raises(DataError) as info3:
        parse_mt5_tester_html(only_open, "0" * 64)
    assert info3.value.key == "reader.mt5_tester_no_trades"


def test_xlsx_rows_and_excel_serial_dates() -> None:
    orders: list[list[str]] = []
    deals = [
        ["2021.01.01 00:00:00", "1", "", "balance", "", "", "", "", "0.00", "0.00", "5000",
         "5000", ""],
        # 44200.375 = 2021-01-04 09:00 en numéro de série Excel
        ["44200.375", "2", "EURUSD", "buy", "in", "0.1", "1.1", "2", "0", "0", "0", "5000", ""],
        ["44200.5", "3", "EURUSD", "sell", "out", "0.1", "1.102", "3", "0", "0", "20", "5020", ""],
    ]
    data = tf.tester_xlsx(orders, deals)
    rows = xlsx_rows(data)
    assert rows[0][1] == ["Strategy Tester Report"]
    header = next(cells for _, cells in rows if cells[:2] == ["Time", "Deal"])
    assert header == tf.DEALS_HEADER[: len(header)]
    assert len(DEALS_HEADER) == 12
    table = build_table(rows, "0" * 64, " ".join(" ".join(c) for _, c in rows))
    assert table.n == 1
    assert table.rows[0][1] == "2021.01.04 09:00:00"
    assert table.rows[0][2] == "2021.01.04 12:00:00"
    assert table.currency == "USD"
    assert len(tf.ORDERS_HEADER) == 11


def test_kind_can_be_forced_and_xlsx_is_a_known_suffix() -> None:
    assert "mt5_tester" in KINDS
    forced = read_table(FIXTURES / "mt5_tester_report.html", kind="mt5_tester")
    assert forced.n == 600
    from qaudit.io.readers import TABLE_SUFFIXES

    assert ".xlsx" in TABLE_SUFFIXES
