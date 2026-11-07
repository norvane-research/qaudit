# SPDX-License-Identifier: AGPL-3.0-or-later
"""CLI et portes d'escalade : codes de sortie (N-11), E1, E2, E3, démo hors ligne."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from qaudit.cli.main import main
from qaudit.io.document import loads

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FAST = ["--n-iter", "400"]


def run(*argv: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


# ---------------------------------------------------------------------------
# audit : codes 0 / 1 / 2
# ---------------------------------------------------------------------------


def test_audit_witness_without_walkforward_is_conditional(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run("audit", str(FIXTURES / "healthy_witness.csv"), "--out", str(tmp_path),
                       "--initial-balance", "10000", "--cache-dir", str(tmp_path / "c"), *FAST,
                       capsys=capsys)
    assert code == 1
    assert "GO SOUS CONDITIONS" in out
    assert "revue_humaine: false" in out
    assert (tmp_path / "archive" / "healthy_witness.json").exists()
    assert (tmp_path / "healthy_witness.html").exists()
    assert (tmp_path / "healthy_witness.pdf").exists()


def test_audit_witness_with_prices_and_walkforward_is_go(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(
        "audit", str(FIXTURES / "healthy_witness.csv"), "--out", str(tmp_path),
        "--initial-balance", "10000", "--prices", str(FIXTURES / "healthy_witness_prices.csv"),
        "--symbol", "EURUSD", "--walkforward", str(FIXTURES / "walkforward" / "healthy_witness"),
        "--ruleset", "two_step_static", "--offre", "due_diligence", "--lang", "en",
        "--cache-dir", str(tmp_path / "c"), *FAST, capsys=capsys,
    )
    assert code == 0
    assert "Verdict: GO" in out
    document = loads((tmp_path / "archive" / "healthy_witness.json").read_text(encoding="utf-8"))
    assert document["verdict"]["decision"] == "GO"
    assert document["propfirm"] is not None
    assert document["walkforward"]["n_candidates"] == 3


def test_audit_martingale_is_no_go(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run("audit", str(FIXTURES / "martingale.csv"), "--out", str(tmp_path),
                       "--initial-balance", "10000", "--cache-dir", str(tmp_path / "c"), *FAST,
                       capsys=capsys)
    assert code == 2
    assert "NO-GO" in out


# ---------------------------------------------------------------------------
# porte E1 : colonnes exotiques → 10 + JSON ; reprise par --mapping ; mémorisation
# ---------------------------------------------------------------------------


def test_E1_exotic_columns_exit_10_with_json_then_mapping_resumes_and_is_memorised(  # noqa: N802
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = tmp_path / "cache"
    code, out, err = run("audit", str(FIXTURES / "exotic_columns.csv"), "--out", str(tmp_path),
                         "--cache-dir", str(cache), *FAST, capsys=capsys)
    assert code == 10
    payload = json.loads(out)
    assert payload["gate"] == "E1"
    assert payload["missing_fields"] == ["profit"]  # les horodatages ont été déduits du contenu
    assert "Résultat net" in payload["seen_columns"]
    assert len(payload["header_fingerprint"]) == 64
    assert "[10]" in err

    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        '[fields]\nopen_time = "Ouverture"\nclose_time = "Fermeture"\nprofit = "Résultat net"\n'
        'volume = "Lots"\ndirection = "Sens"\nsymbol = "Instrument"\n',
        encoding="utf-8",
    )
    code, out, _ = run("audit", str(FIXTURES / "exotic_columns.csv"), "--out", str(tmp_path),
                       "--mapping", str(mapping), "--initial-balance", "10000",
                       "--cache-dir", str(cache), *FAST, capsys=capsys)
    assert code == 1
    stored = list((cache / "mappings").glob("*.toml"))
    assert len(stored) == 1
    assert stored[0].stem == payload["header_fingerprint"]

    # troisième passage : sans --mapping, la correspondance mémorisée sert
    code, out, _ = run("audit", str(FIXTURES / "exotic_columns.csv"), "--out", str(tmp_path),
                       "--initial-balance", "10000", "--cache-dir", str(cache), *FAST,
                       capsys=capsys)
    assert code == 1
    assert "GO SOUS CONDITIONS" in out


def test_mapping_skeleton_lists_every_field(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run("mapping-skeleton", str(FIXTURES / "exotic_columns.csv"), capsys=capsys)
    assert code == 0
    assert '[fields]' in out
    assert 'open_time = "Ouverture"' in out
    assert '# profit = ""' in out


# ---------------------------------------------------------------------------
# porte E2 : règlement en prose ou incomplet → 11 + squelette
# ---------------------------------------------------------------------------


def test_E2_prose_ruleset_exit_11_with_skeleton(  # noqa: N802
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prose = tmp_path / "rules.txt"
    prose.write_text("Perte max 10 %, perte journalière 5 %, cible 8 % puis 5 %.\n",
                     encoding="utf-8")
    code, out, err = run("audit", str(FIXTURES / "healthy_witness.csv"), "--out", str(tmp_path),
                         "--ruleset", str(prose), "--cache-dir", str(tmp_path / "c"), *FAST,
                         capsys=capsys)
    assert code == 11
    assert "[[phases]]" in out
    assert "as_of" in out
    assert "[11]" in err


def test_E2_incomplete_ruleset_names_missing_keys(  # noqa: N802
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from qaudit.io.ruleset import skeleton

    incomplete = tmp_path / "rules.toml"
    incomplete.write_text(skeleton().replace("profit_split = 0.80", ""), encoding="utf-8")
    code, out, err = run("audit", str(FIXTURES / "healthy_witness.csv"), "--out", str(tmp_path),
                         "--ruleset", str(incomplete), "--cache-dir", str(tmp_path / "c"), *FAST,
                         capsys=capsys)
    assert code == 11
    assert "profit_split" in err
    assert "[[phases]]" in out


def test_ruleset_helpers(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run("rulesets", capsys=capsys)
    assert code == 0
    assert "two_step_static" in out
    code, out, _ = run("ruleset-skeleton", capsys=capsys)
    assert code == 0
    assert "balance_carry" in out


# ---------------------------------------------------------------------------
# porte E3 : bande d'indécision → verdict rendu, revue_humaine = true
# ---------------------------------------------------------------------------


def test_E3_borderline_file_is_flagged_for_human_review_not_stopped(  # noqa: N802
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run("audit", str(FIXTURES / "borderline.csv"), "--out", str(tmp_path),
                       "--initial-balance", "10000", "--cache-dir", str(tmp_path / "c"),
                       "--n-iter", "2000", "--seed", "1", capsys=capsys)
    assert code == 1
    assert "revue_humaine: true" in out
    assert "Grandeur limite" in out
    document = loads((tmp_path / "archive" / "borderline.json").read_text(encoding="utf-8"))
    assert document["verdict"]["revue_humaine"] is True
    assert document["verdict"]["decision"] == "GO_CONDITIONAL"
    boundary = [b for b in document["verdict"]["barriers"] if b["indecision"]]
    assert [b["name"] for b in boundary] == ["dd_percentile"]
    assert 3.0 <= float(boundary[0]["value"]) <= 8.0
    assert not boundary[0]["triggered"]


# ---------------------------------------------------------------------------
# 20 données invalides, 30 erreur interne
# ---------------------------------------------------------------------------


def test_invalid_data_exit_20_names_row_and_column(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("open_time,close_time,profit\n2021-01-04 09:00,2021-01-04 10:00,5\n"
                   "2021-01-05 09:00,2021-01-05 10:00,abc\n", encoding="utf-8")
    code, _, err = run("audit", str(bad), "--out", str(tmp_path), "--cache-dir",
                       str(tmp_path / "c"), *FAST, capsys=capsys)
    assert code == 20
    assert "ligne 3" in err
    assert "profit" in err


def test_internal_error_exit_30(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from qaudit.cli import commands

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("panne simulée")

    monkeypatch.setattr(commands, "run_audit", boom)
    code, _, err = run("audit", str(FIXTURES / "healthy_witness.csv"), "--out", str(tmp_path),
                       "--cache-dir", str(tmp_path / "c"), *FAST, capsys=capsys)
    assert code == 30
    assert "RuntimeError" in err
    assert "panne simulée" in err


# ---------------------------------------------------------------------------
# render --from, validate, demo, profils, batch
# ---------------------------------------------------------------------------


def test_render_from_archive_matches_direct_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    direct = tmp_path / "direct"
    run("audit", str(FIXTURES / "martingale.csv"), "--out", str(direct), "--initial-balance",
        "10000", "--cache-dir", str(tmp_path / "c"), "--offre", "audit_complet", *FAST,
        capsys=capsys)
    again = tmp_path / "again"
    code, _, _ = run("render", "--from", str(direct / "archive" / "martingale.json"), "--out",
                     str(again), "--offre", "audit_complet", capsys=capsys)
    assert code == 2  # le code de sortie suit le verdict du document
    for name in ("martingale.html", "martingale.pdf", "martingale.json"):
        assert (again / name).read_bytes() == (direct / name).read_bytes()
    other = tmp_path / "other"
    code, _, _ = run("render", "--from", str(direct / "archive" / "martingale.json"), "--out",
                     str(other), "--offre", "verdict_propfirm", capsys=capsys)
    assert code == 2
    assert not (other / "martingale.json").exists()  # ce profil ne livre pas le JSON


def test_validate_subcommand(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run("validate", str(FIXTURES / "healthy_witness.csv"), "--initial-balance",
                       "10000", "--cache-dir", str(tmp_path / "c"), capsys=capsys)
    assert code == 0
    assert "600 trades" in out
    assert "missing_optional" in out
    code, out, _ = run("validate", str(FIXTURES / "exotic_columns.csv"), "--cache-dir",
                       str(tmp_path / "c"), capsys=capsys)
    assert code == 10
    assert json.loads(out)["gate"] == "E1"


def test_demo_runs_offline_and_yields_expected_verdicts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("réseau")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    code, out, _ = run("demo", "--out", str(tmp_path), capsys=capsys)
    assert code == 0
    assert "healthy_witness : GO (attendu : GO)" in out
    assert "martingale : NO-GO (attendu : NO-GO)" in out
    assert (tmp_path / "healthy_witness.html").exists()
    assert (tmp_path / "martingale.html").exists()
    assert (tmp_path / "archive" / "martingale.json").exists()


def test_profils_lists_the_seven_profiles(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run("profils", capsys=capsys)
    assert code == 0
    for name in ("pre_verification", "verdict_propfirm", "audit_complet", "audit_prix",
                 "portefeuille", "attestation_cessible", "due_diligence"):
        assert name in out
    assert "€" not in out  # le moteur ne connaît aucun prix (offre commerciale : site.toml)


def test_batch_subcommand(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    for name in ("healthy_witness", "martingale"):
        (folder / f"{name}.csv").write_bytes((FIXTURES / f"{name}.csv").read_bytes())
    code, out, _ = run("batch", str(folder), "--out", str(tmp_path / "out"), "--jobs", "1",
                       "--initial-balance", "10000", "--n-iter", "300", "--offre", "portefeuille",
                       capsys=capsys)
    assert code == 2  # le pire verdict du lot
    assert "2 système(s)" in out
    assert (tmp_path / "out" / "portfolio.html").exists()
    assert (tmp_path / "out" / "archive" / "healthy_witness.json").exists()


def test_console_entry_point_and_version() -> None:
    result = subprocess.run([sys.executable, "-m", "qaudit", "--version"], capture_output=True,
                            text=True, check=False)
    assert result.returncode == 0
    assert "qaudit 1.0.0" in result.stdout
    helped = subprocess.run([sys.executable, "-m", "qaudit", "audit", "--help"],
                            capture_output=True, text=True, check=False)
    assert helped.returncode == 0
    assert "--mapping" in helped.stdout


def test_gui_subcommand_forwards_language_and_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """``qaudit --lang en gui f.csv --run`` ouvre l'application graphique via le
    binaire console (contournement Smart App Control) en lui passant la langue
    et les arguments tels quels ; le code de sortie est celui de la fenêtre."""
    from qaudit.gui import app as gui_app

    seen: list[list[str]] = []

    def fake_main(argv: list[str] | None = None) -> int:
        seen.append(list(argv or []))
        return 5

    monkeypatch.setattr(gui_app, "main", fake_main)
    monkeypatch.setattr(gui_app, "hide_own_console", lambda: False)
    assert main(["--lang", "en", "gui", "f.csv", "--run", "--exit-after"]) == 5
    assert seen == [["--lang", "en", "f.csv", "--run", "--exit-after"]]


def test_offer_requiring_absent_inputs_is_warned_on_stderr_not_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verdict Propfirm sans règlement : le rapport est rendu (il dit lui-même
    « rejeu non effectué »), le code de sortie reste le verdict, et stderr nomme
    l'offre et les entrées requises absentes. Avec le règlement : silence."""
    out = tmp_path / "pf"
    code, _, err = run("audit", str(FIXTURES / "healthy_witness.csv"), "--out", str(out),
                       "--initial-balance", "10000", "--cache-dir", str(tmp_path / "c"),
                       "--offre", "verdict_propfirm", *FAST, capsys=capsys)
    assert code == 1
    assert "verdict_propfirm" in err
    assert "règlement propfirm" in err
    assert "taille du compte" not in err  # le solde initial était fourni
    assert (out / "healthy_witness.html").exists()
    code, _, err = run("render", "--from", str(out / "archive" / "healthy_witness.json"),
                       "--out", str(tmp_path / "again"), "--offre", "verdict_propfirm",
                       capsys=capsys)
    assert code == 1
    assert "règlement propfirm" in err
    code, _, err = run("render", "--from", str(out / "archive" / "healthy_witness.json"),
                       "--out", str(tmp_path / "ac"), "--offre", "audit_complet", capsys=capsys)
    assert code == 1
    assert err == ""
    code, _, err = run("audit", str(FIXTURES / "healthy_witness.csv"), "--out",
                       str(tmp_path / "ok"), "--initial-balance", "10000", "--cache-dir",
                       str(tmp_path / "c"), "--offre", "verdict_propfirm", "--ruleset",
                       "two_step_static", *FAST, capsys=capsys)
    assert code == 1
    assert err == ""
