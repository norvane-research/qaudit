# SPDX-License-Identifier: AGPL-3.0-or-later
"""Non-régression des constats de la revue de code du 19/09/2026 (R-01 … R-08).

Chaque test reproduit le scénario de défaillance relevé, puis vérifie le
comportement corrigé.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qaudit import i18n
from qaudit.cli.main import main
from qaudit.core.audit import AuditOptions
from qaudit.core.errors import DataError, SchemaError
from qaudit.core.validate import parse_datetime, validate
from qaudit.io.batch import run_batch
from qaudit.io.mapping import resolve_mapping
from qaudit.io.method import load_method, parse_method
from qaudit.io.profile import load_profile
from qaudit.io.readers import read_table
from qaudit.io.readers.common import decode_bytes, infer_mapping
from qaudit.io.readers.csv_generic import parse_csv_text, unique_headers
from qaudit.io.readers.dataframe import from_dataframe
from qaudit.io.writers.render import Fmt, build_view

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_R01_cp1252_file_of_even_length_is_not_decoded_as_utf16() -> None:  # noqa: N802
    """R-01 : un CSV ANSI de longueur paire sortait en charabia UTF-16."""
    text = "Instrument;Sens;Résultat net\nEURUSD;Achat;-81,20\n"
    raw = text.encode("cp1252")
    for payload in (raw, raw + b"\n"):  # longueur impaire puis paire
        assert decode_bytes(payload) == text + ("" if payload is raw else "\n")
    assert decode_bytes(text.encode("utf-16")) == text  # BOM présent : UTF-16 accepté
    assert decode_bytes(text.encode("utf-8-sig")) == text
    assert decode_bytes(text.encode("utf-8")) == text


def test_R02_nat_timestamp_is_a_missing_value_not_a_date() -> None:  # noqa: N802
    """R-02 : un ``pd.NaT`` traversait la validation et corrompait l'étendue."""
    df = pd.DataFrame(
        {
            "open_time": pd.to_datetime(["2021-01-04 09:00", "2021-01-05 09:00"]),
            "close_time": [pd.Timestamp("2021-01-04 10:00"), pd.NaT],
            "profit": [5.0, -3.0],
        }
    )
    table = from_dataframe(df)
    with pytest.raises(DataError) as info:
        validate(table, infer_mapping(table.columns), max_gap_days=30.0)
    assert (info.value.key, info.value.row, info.value.column) == (
        "validate.missing_value", 3, "close_time",
    )
    with pytest.raises(ValueError, match="NaT"):
        parse_datetime(np.datetime64("NaT", "ns"))


def test_R03_non_finite_numbers_from_the_document_render_as_not_available() -> None:  # noqa: N802
    """R-03 : « NaN » stocké en chaîne dans le JSON s'affichait « nan »."""
    fr = Fmt(i18n.load("fr"))
    en = Fmt(i18n.load("en"))
    assert fr.num("NaN") == fr.num(float("nan")) == fr.num(None) == "n. d."
    assert en.num("NaN") == "n/a"
    assert fr.num("Infinity") == "+∞"
    assert fr.num("-Infinity") == "−∞"
    assert fr.num(1234.5) == "1" + chr(0x202F) + "234,50"
    assert fr.pct("NaN") == "n. d."


def test_R04_numeric_identifier_column_is_never_deduced_as_a_timestamp() -> None:  # noqa: N802
    """R-04 : une colonne « Ref. ID » à dix chiffres devenait l'heure d'ouverture."""
    text = (
        "Ref. ID;Ouverture;Fermeture;Résultat net\n"
        "1609556645;2021-01-04 09:00;2021-01-04 10:00;5\n"
        "1609643045;2021-01-05 09:00;2021-01-05 10:00;-3\n"
    )
    table = parse_csv_text(text, "0" * 64)
    mapping, origin = resolve_mapping(table, None, None)
    assert origin == "inferred"
    assert mapping.get("open_time") == "Ouverture"
    assert mapping.get("close_time") == "Fermeture"
    assert "Ref. ID" not in mapping.values()
    # sans colonne textuelle d'horodatage, rien n'est deviné : porte E1
    numeric_only = parse_csv_text("a;b;profit\n1609556645;1609560245;5\n", "0" * 64)
    mapping2, _ = resolve_mapping(numeric_only, None, None)
    with pytest.raises(SchemaError) as info:
        validate(numeric_only, mapping2, max_gap_days=30.0)
    assert set(info.value.missing_fields) == {"open_time", "close_time"}


def test_R05_duplicate_headers_are_disambiguated_and_reachable(tmp_path: Path) -> None:  # noqa: N802
    """R-05 : deux colonnes « Time » se résolvaient toutes deux sur la première."""
    assert unique_headers(("Time", "Price", "Time", "Price", "X")) == (
        "Time", "Price", "Time#2", "Price#2", "X",
    )
    # export de type MT5 sans colonne Position : lecteur générique
    text = (
        "Time;Symbol;Type;Volume;Price;Time;Price;Profit\n"
        "2021.01.04 09:00:00;EURUSD;buy;0.10;1.1000;2021.01.04 15:00:00;1.1010;10\n"
        "2021.01.05 09:00:00;EURUSD;sell;0.10;1.1000;2021.01.05 15:00:00;1.0990;10\n"
    )
    table = parse_csv_text(text, "0" * 64)
    assert table.columns.count("Time") == 1
    mapping, _ = resolve_mapping(table, None, None)
    assert mapping["close_time"] == "Time"  # synonyme « time » → clôture
    assert mapping["open_time"] == "Time#2"  # déduite par le contenu
    explicit = tmp_path / "m.toml"
    explicit.write_text(
        '[fields]\nopen_time = "Time"\nclose_time = "Time#2"\nprofit = "Profit"\n'
        'open_price = "Price"\nclose_price = "Price#2"\n',
        encoding="utf-8",
    )
    mapping, _ = resolve_mapping(table, explicit, None)
    ts = validate(table, mapping, max_gap_days=30.0).tradeset
    hours = (ts.close_time - ts.open_time).astype("timedelta64[h]").astype(int)
    assert hours.tolist() == [6, 6]  # plus de durée nulle
    assert ts.close_price.tolist() == [1.1010, 1.0990]
    # le lecteur MT5 reconnaît toujours son format malgré les suffixes
    mt5 = read_table(FIXTURES / "mt5_positions.csv")
    assert mt5.source == "mt5_csv"
    assert mt5.n == 600


def test_R06_batch_honours_kind_mapping_cache_and_simulation_options(  # noqa: N802
    tmp_path: Path,
) -> None:
    """R-06 : le mode lot ignorait --kind, --mapping, --cache-dir, --bootstrap…"""
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "exotic.csv").write_bytes((FIXTURES / "exotic_columns.csv").read_bytes())
    (folder / "mt5.csv").write_bytes((FIXTURES / "mt5_positions.csv").read_bytes())
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        '[fields]\nopen_time = "Ouverture"\nclose_time = "Fermeture"\nprofit = "Résultat net"\n'
        'volume = "Lots"\ndirection = "Sens"\nsymbol = "Instrument"\n',
        encoding="utf-8",
    )
    cache = tmp_path / "cache"
    options = AuditOptions(seed=3, n_iter=300, bootstrap_method="iid", n_trials=1)
    # 1. correspondance explicite : le dossier exotique passe et est mémorisé
    result = run_batch(
        [folder / "exotic.csv"], options=options, jobs=1, alpha=0.05,
        initial_balance=10_000.0, mapping_path=mapping, cache_dir=cache,
    )
    assert not result.errors, result.errors
    doc = result.documents["exotic"]
    assert doc["resampling"]["bootstrap"]["method"] == "iid"
    assert doc["n_trials"] == 1
    assert doc["seed"] == 3
    assert list((cache / "mappings").glob("*.toml"))
    # 2. sans --mapping mais avec le cache : la correspondance mémorisée sert ;
    #    le fichier MT5 passe par la détection automatique du lecteur
    result2 = run_batch(
        [folder / "exotic.csv", folder / "mt5.csv"], options=options, jobs=1, alpha=0.05,
        initial_balance=10_000.0, cache_dir=cache,
    )
    assert not result2.errors, result2.errors
    assert result2.documents["mt5"]["data"]["n_trades"] == 600
    # 3. --kind csv force le lecteur générique : les lignes de solde MT5 deviennent
    #    des données invalides, rapportées par leur clé (jamais en silence)
    result3 = run_batch(
        [folder / "mt5.csv"], options=options, jobs=1, alpha=0.05, initial_balance=10_000.0,
        kind="csv", cache_dir=cache,
    )
    assert "mt5" in result3.errors


def test_R07_skipped_price_detector_is_not_reported_as_clean() -> None:  # noqa: N802
    """R-07 : la section prix disait « aucun constat » pour un détecteur non exécuté."""
    doc = json.loads((FIXTURES / "golden" / "healthy_witness.json").read_text(encoding="utf-8"))
    doc["data"]["prices_provided"] = True  # les constats *_skipped restent ceux du document
    catalog = i18n.load("fr")
    view = build_view(doc, catalog, load_profile("audit_prix"), system_name="x")
    section = next(s for s in view.sections if s.id == "detecteurs_prix")
    assert any(e.code == "lookahead_skipped" for e in section.entries)
    assert not any("lookahead" in p and "aucun constat" in p for p in section.paragraphs)
    assert section.paragraphs == ()


def test_R08_method_file_rejects_unknown_protocol_selection_and_bootstrap() -> None:  # noqa: N802
    """R-08 : une faute de frappe dans walkforward.protocol basculait en glissant."""
    import tomllib
    from importlib import resources

    raw = tomllib.loads(
        resources.files("qaudit.io.methods").joinpath("method-1.0.toml").read_text("utf-8")
    )
    assert parse_method(raw).walkforward_protocol == "anchored"
    for section, key, bad in (
        ("walkforward", "protocol", "anchor"),
        ("walkforward", "selection", "net"),
        ("resample", "bootstrap_method", "block"),
    ):
        broken = json.loads(json.dumps(raw))
        broken[section][key] = bad
        with pytest.raises(DataError) as info:
            parse_method(broken)
        assert info.value.key == "method.bad_choice"
        assert info.value.column == f"{section}.{key}"
        assert info.value.params["value"] == bad
    assert load_method().walkforward_selection == "net_profit"


def test_R06_cli_batch_forwards_bootstrap_choice(  # noqa: N802
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "w.csv").write_bytes((FIXTURES / "healthy_witness.csv").read_bytes())
    code = main(["batch", str(folder), "--out", str(tmp_path / "out"), "--jobs", "1",
                 "--initial-balance", "10000", "--n-iter", "200", "--bootstrap", "iid",
                 "--cache-dir", str(tmp_path / "c")])
    capsys.readouterr()
    assert code in (0, 1)
    doc = json.loads((tmp_path / "out" / "archive" / "w.json").read_text(encoding="utf-8"))
    assert doc["resampling"]["bootstrap"]["method"] == "iid"


# ---------------------------------------------------------------------------
# R-09 : rapport d'historique MT5 dans la langue du terminal, structure réelle
# ---------------------------------------------------------------------------

_FR_REPORT = """<!DOCTYPE html><html><head><meta charset="utf-16"></head><body><table>
<tr><th colspan="14"><b>Rapport d'historique de trading</b></th></tr>
<tr><td colspan="2"><b>Compte:</b></td>
<td colspan="12">1234567&nbsp;(USD,&nbsp;Deriv-Demo,&nbsp;demo,&nbsp;Hedge)</td></tr>
<tr><th colspan="14"><b>Positions</b></th></tr>
<tr><td><b>Heure</b></td><td><b>Position</b></td><td><b>Symbole</b></td><td><b>Type</b></td>
<td><b>Volume</b></td><td><b>Prix</b></td><td><b>S / L</b></td><td><b>T / P</b></td>
<td><b>Heure</b></td>
<td><b>Prix</b></td><td><b>Commission</b></td><td><b>Echange</b></td>
<td colspan="2"><b>Profit</b></td></tr>
<tr><td>2026.07.02 07:58:48</td><td>5703395863</td><td>XAGUSD</td><td>buy</td>
<td class="hidden" colspan="8"></td><td>0.01</td><td>59.417</td><td></td><td></td>
<td>2026.07.02 08:04:53</td><td>59.418</td><td>0.00</td><td>0.00</td><td colspan="2">0.05</td></tr>
<tr><td>2026.07.12 15:39:12</td><td>5713147279</td><td>Volatility 75 Index</td><td>sell</td>
<td class="hidden" colspan="8">FORCÉE 5min (mom</td><td>0.03</td><td>54630.38</td>
<td>49595.33</td><td></td>
<td>2026.08.26 09:37:48</td><td>49597.14</td><td>0.00</td><td>-10.09</td>
<td colspan="2">151.00</td></tr>
<tr><td colspan="14"></td></tr>
<tr><th colspan="14"><b>Transactions</b></th></tr>
<tr><td>Heure</td><td>Opération</td><td>Symbole</td><td>Type</td><td>Direction</td>
<td>Volume</td><td>Prix</td>
<td>Ordre</td><td>Coût</td><td>Commission</td><td>Frais</td><td>Echange</td><td>Profit</td>
<td>Solde</td><td>Commentaire</td></tr>
<tr><td>2026.07.02 07:53:51</td><td>5583273889</td><td></td><td>balance</td><td></td><td></td>
<td></td><td></td><td></td>
<td>0.00</td><td>0.00</td><td>0.00</td><td>10 000.00</td><td>10 000.00</td>
<td>MT5+Virtual+Money+deposit</td></tr>
</table></body></html>"""


def test_R09_french_mt5_history_report_with_hidden_cells_is_read(tmp_path: Path) -> None:  # noqa: N802
    """R-09 : le rapport d'historique réel (langue du terminal, cellule de
    commentaire « hidden » après Type, devise dans la ligne Compte, dépôt dans
    la section Transactions) sortait « section Positions introuvable »."""
    from qaudit.io.readers import read_table
    from qaudit.io.readers.common import normalise_header
    from qaudit.io.readers.mt5_headers import mt5_key

    path = tmp_path / "ReportHistory-1234567.html"
    path.write_bytes(_FR_REPORT.encode("utf-16"))
    table = read_table(path)
    assert table.source == "mt5_html"
    assert table.n == 2
    assert table.currency == "USD"
    assert table.initial_balance == 10_000.0
    assert table.columns == (
        "open_time", "ticket", "symbol", "direction", "volume", "open_price", "stop_loss",
        "take_profit", "close_time", "close_price", "commission", "swap", "profit",
    )
    assert table.rows[1][2] == "Volatility 75 Index"
    assert table.rows[1][6] == "49595.33"  # le commentaire masqué n'a pas décalé les colonnes
    assert table.rows[1][12] == "151.00"
    ts = validate(table, infer_mapping(table.columns), max_gap_days=30.0).tradeset
    assert ts.profit.tolist() == [0.05, 151.0 - 10.09]
    assert normalise_header("Clôture") == "cloture"
    assert [mt5_key(h) for h in ("Heure", "Echange", "Heure d'ouverture", "Symbole", "Preis",
                                  "Beneficio", "Lucro")] == [
        "time", "swap", "opentime", "symbol", "price", "profit", "profit",
    ]
