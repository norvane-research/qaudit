# SPDX-License-Identifier: AGPL-3.0-or-later
"""Les cinq lecteurs, chacun sur une fixture réelle : CSV générique, CSV MT5,
rapport HTML MT5, export Deriv, DataFrame ; détection automatique ;
correspondance E1 et sa mémorisation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qaudit.core.errors import DataError, SchemaError
from qaudit.core.models import RawTable, TradeSet
from qaudit.core.validate import validate
from qaudit.io.mapping import (
    MappingStore,
    header_fingerprint,
    parse_mapping_text,
    resolve_mapping,
    skeleton,
)
from qaudit.io.readers import KINDS, read_table
from qaudit.io.readers.common import fingerprint_bytes, infer_mapping
from qaudit.io.readers.csv_generic import parse_csv_text, sniff_delimiter
from qaudit.io.readers.dataframe import from_dataframe
from qaudit.io.readers.deriv import deriv_table, looks_like_deriv
from qaudit.io.readers.mt5_csv import looks_like_mt5, rename_mt5_columns
from qaudit.io.readers.mt5_html import parse_mt5_html

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _tradeset(table: RawTable, mapping: Mapping[str, str]) -> TradeSet:
    return validate(table, mapping, max_gap_days=30.0).tradeset


# ---------------------------------------------------------------------------
# CSV générique
# ---------------------------------------------------------------------------


def test_generic_csv_reader_and_delimiter_sniffing() -> None:
    table = read_table(FIXTURES / "healthy_witness.csv")
    assert table.source == "csv"
    assert table.n == 600
    assert table.line_numbers[0] == 2
    assert table.fingerprint == fingerprint_bytes((FIXTURES / "healthy_witness.csv").read_bytes())
    assert sniff_delimiter("a;b;c\n1;2;3") == ";"
    assert sniff_delimiter("a\tb\n1\t2") == "\t"
    assert sniff_delimiter("a,b\n1,2") == ","
    assert sniff_delimiter("single\n1") == ","


def test_generic_csv_skips_blank_and_comment_lines_and_names_bad_rows() -> None:
    text = "# export\n\nopen_time,close_time,profit\n2021-01-04 09:00,2021-01-04 10:00,5\n\n"
    table = parse_csv_text(text, "0" * 64)
    assert table.columns == ("open_time", "close_time", "profit")
    assert table.line_numbers == (4,)
    with pytest.raises(DataError) as info:
        parse_csv_text("a,b\n1,2,3\n", "0" * 64)
    assert (info.value.key, info.value.row) == ("reader.row_width", 2)
    with pytest.raises(DataError) as empty:
        parse_csv_text("\n\n", "0" * 64)
    assert empty.value.key == "validate.no_rows"


def test_exotic_columns_need_a_mapping_but_time_columns_are_deduced_from_content() -> None:
    table = read_table(FIXTURES / "exotic_columns.csv")
    mapping, origin = resolve_mapping(table, None, None)
    assert origin == "inferred"
    assert mapping["open_time"] == "Ouverture"
    assert mapping["close_time"] == "Fermeture"
    assert "profit" not in mapping
    with pytest.raises(SchemaError) as info:
        validate(table, mapping, max_gap_days=30.0)
    assert info.value.missing_fields == ("profit",)
    assert info.value.seen_columns == table.columns


# ---------------------------------------------------------------------------
# CSV MetaTrader 5
# ---------------------------------------------------------------------------


def test_mt5_csv_is_detected_renamed_and_balance_rows_dropped() -> None:
    table = read_table(FIXTURES / "mt5_positions.csv")
    assert table.source == "mt5_csv"
    assert looks_like_mt5(("Time", "Position", "Symbol", "Type", "Volume", "Price", "S / L",
                           "T / P", "Time", "Price", "Commission", "Swap", "Profit"))
    assert table.columns == (
        "open_time", "ticket", "symbol", "direction", "volume", "open_price", "stop_loss",
        "take_profit", "close_time", "close_price", "commission", "swap", "profit",
    )
    assert table.n == 600  # 601 lignes moins la ligne de solde
    assert table.line_numbers[0] == 3  # la ligne 2 est le dépôt
    assert table.initial_balance == 10_000.0
    mapping, origin = resolve_mapping(table, None, None)
    assert origin == "inferred"
    ts = _tradeset(table, mapping)
    assert ts.n == 600
    assert ts.has("commission")
    # profit net = profit + commission + swap (−80,50 − 0,70)
    assert ts.profit[0] == pytest.approx(-81.20)
    assert ts.direction[0] == 1
    assert ts.ticket[0] == 100001
    assert ts.stop_loss[0] == pytest.approx(1.09537)


def test_mt5_rename_handles_duplicates_in_order() -> None:
    assert rename_mt5_columns(("Time", "Price", "Time", "Price", "Type")) == (
        "open_time", "open_price", "close_time", "close_price", "direction",
    )
    assert not looks_like_mt5(("open_time", "close_time", "profit"))


# ---------------------------------------------------------------------------
# rapport HTML MetaTrader 5
# ---------------------------------------------------------------------------


def test_mt5_html_report_reader() -> None:
    table = read_table(FIXTURES / "mt5_report.html")
    assert table.source == "mt5_html"
    assert table.currency == "USD"
    assert table.initial_balance == 10_000.0
    assert table.n == 600
    assert all(line > 0 for line in table.line_numbers)
    ts = _tradeset(table, resolve_mapping(table, None, None)[0])
    assert ts.currency == "USD"
    assert ts.n == 600
    # même contenu que l'export CSV MT5 : mêmes profits nets
    csv_table = read_table(FIXTURES / "mt5_positions.csv")
    csv_ts = _tradeset(csv_table, resolve_mapping(csv_table, None, None)[0])
    np.testing.assert_allclose(ts.profit, csv_ts.profit)
    assert table.fingerprint != csv_table.fingerprint  # empreintes des octets, pas du contenu


def test_mt5_html_without_positions_table_is_a_named_error() -> None:
    with pytest.raises(DataError) as info:
        parse_mt5_html("<html><body><table><tr><td>rien</td></tr></table></body></html>", "0" * 64)
    assert info.value.key == "reader.mt5_positions_not_found"
    kind_forced = read_table(FIXTURES / "mt5_report.html", kind="mt5_html")
    assert kind_forced.n == 600


# ---------------------------------------------------------------------------
# export Deriv
# ---------------------------------------------------------------------------


def test_deriv_profit_table_reader() -> None:
    table = read_table(FIXTURES / "deriv_profit_table.csv")
    assert table.source == "deriv"
    assert looks_like_deriv(("Ref. ID", "Buy time", "Sell time"))
    assert not looks_like_deriv(("open_time", "close_time"))
    mapping, _ = resolve_mapping(table, None, None)
    ts = _tradeset(table, mapping)
    assert ts.n == 600
    assert ts.profit[0] == pytest.approx(-8.12)
    assert ts.volume[0] == 10.0  # la mise sert de volume
    assert ts.symbol[0] == "Volatility 75 Index"
    assert ts.ticket[0] == 500001
    assert not ts.has("direction")
    assert not ts.has("stop_loss")


def test_deriv_profit_is_computed_from_stake_and_payout_when_absent() -> None:
    text = ("Ref. ID,Buy time,Buy price,Sell time,Sell price\n"
            "1,2021-01-04 09:00,10.00,2021-01-04 10:00,18.50\n"
            "2,2021-01-05 09:00,10.00,2021-01-05 10:00,0.00\n")
    table = deriv_table(parse_csv_text(text, "0" * 64))
    assert table.columns[-1] == "profit"
    assert [row[-1] for row in table.rows] == ["8.50", "-10.00"]
    with pytest.raises(DataError) as info:
        deriv_table(
            parse_csv_text("Ref. ID,Buy time,Sell time\n1,2021-01-04,2021-01-05\n", "0" * 64)
        )
    assert info.value.key == "reader.deriv_missing_profit"
    bad = "Ref. ID,Buy time,Buy price,Sell time,Sell price\n1,2021-01-04,10,2021-01-05,abc\n"
    with pytest.raises(DataError) as info2:
        deriv_table(parse_csv_text(bad, "0" * 64))
    assert (info2.value.row, info2.value.column) == (2, "Sell price")


# ---------------------------------------------------------------------------
# DataFrame
# ---------------------------------------------------------------------------


def test_dataframe_reader_converts_cells_and_fingerprints_content() -> None:
    df = pd.DataFrame(
        {
            "open_time": pd.to_datetime(["2021-01-04 09:00", "2021-01-05 09:00"]),
            "close_time": pd.to_datetime(["2021-01-04 10:00", "2021-01-05 10:00"]),
            "profit": [12.5, -4.0],
            "volume": [0.1, np.nan],
            "direction": ["buy", "sell"],
            "symbol": ["EURUSD", "EURUSD"],
        }
    )
    table = from_dataframe(df, initial_balance=1_000.0, currency="USD")
    assert table.source == "dataframe"
    assert table.line_numbers == (2, 3)
    assert isinstance(table.rows[0][0], np.datetime64)
    assert table.rows[1][3] is None  # NaN → valeur manquante
    mapping = infer_mapping(table.columns)
    ts = validate(table, mapping, max_gap_days=30.0).tradeset
    assert ts.n == 2
    assert ts.profit.tolist() == [12.5, -4.0]
    assert np.isnan(ts.volume[1])
    assert ts.direction.tolist() == [1, -1]
    assert ts.initial_balance == 1_000.0
    again = from_dataframe(df, initial_balance=1_000.0, currency="USD")
    assert again.fingerprint == table.fingerprint
    changed = pd.DataFrame({"open_time": ["2021-01-04 09:00"], "close_time": ["2021-01-04 10:00"],
                            "profit": [12.6]})
    assert from_dataframe(changed).fingerprint != table.fingerprint


# ---------------------------------------------------------------------------
# dispatch et kinds
# ---------------------------------------------------------------------------


def test_kinds_are_explicit_and_override_detection() -> None:
    assert KINDS == ("auto", "csv", "mt5_csv", "mt5_html", "mt5_tester", "mt4_html", "deriv")
    generic = read_table(FIXTURES / "mt5_positions.csv", kind="csv")
    assert generic.source == "csv"
    assert generic.n == 601  # aucune ligne écartée en lecture générique
    deriv = read_table(FIXTURES / "deriv_profit_table.csv", kind="deriv")
    assert deriv.source == "deriv"


# ---------------------------------------------------------------------------
# correspondance E1 : fichier explicite, mémorisation, squelette
# ---------------------------------------------------------------------------


def test_mapping_store_round_trip_and_invalidation(tmp_path: Path) -> None:
    table = read_table(FIXTURES / "exotic_columns.csv")
    store = MappingStore(tmp_path)
    assert store.load(table.columns) is None
    mapping = {"open_time": "Ouverture", "close_time": "Fermeture", "profit": "Résultat net"}
    path = store.save(table.columns, mapping)
    assert path.stem == header_fingerprint(table.columns)
    assert store.load(table.columns) == mapping
    resolved, origin = resolve_mapping(table, None, store)
    assert (resolved, origin) == (mapping, "memorized")
    # une correspondance mémorisée qui ne colle plus aux colonnes est ignorée
    path.write_text('[fields]\nopen_time = "Disparue"\n', encoding="utf-8")
    assert store.load(table.columns) is None
    assert resolve_mapping(table, None, store)[1] == "inferred"


def test_explicit_mapping_file_wins_and_is_validated(tmp_path: Path) -> None:
    table = read_table(FIXTURES / "exotic_columns.csv")
    explicit = tmp_path / "m.toml"
    explicit.write_text('[fields]\nopen_time = "Ouverture"\nclose_time = "Fermeture"\n'
                        'profit = "Résultat net"\nvolume = ""\n', encoding="utf-8")
    mapping, origin = resolve_mapping(table, explicit, MappingStore(tmp_path))
    assert origin == "explicit"
    assert "volume" not in mapping  # les valeurs vides sont ignorées
    ts = _tradeset(table, mapping)
    assert ts.n == 600
    with pytest.raises(DataError) as info:
        parse_mapping_text('[fields]\nbogus = "x"\n')
    assert info.value.key == "mapping.unknown_field"
    with pytest.raises(DataError) as info2:
        parse_mapping_text("not = toml = at all")
    assert info2.value.key == "mapping.not_toml"


def test_mapping_skeleton_prefills_guesses_and_comments_the_rest() -> None:
    text = skeleton(("Instrument", "Sens", "Lots", "Ouverture", "Fermeture", "Résultat net"))
    assert 'symbol = "Instrument"' in text
    assert 'volume = "Lots"' in text
    assert 'direction = "Sens"' in text
    assert '# profit = ""' in text
    parsed = parse_mapping_text(text)
    assert "profit" not in parsed
    assert parsed["symbol"] == "Instrument"
