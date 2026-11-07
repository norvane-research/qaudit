# SPDX-License-Identifier: AGPL-3.0-or-later
"""Application PC : le contrôleur (sans écran) emprunte le chemin de la CLI ;
la fenêtre se construit et se remplit (test de fumée, ignoré sans affichage)."""

from __future__ import annotations

import gc
import json
import tkinter as tk
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from qaudit import i18n
from qaudit.cli.main import main as cli_main
from qaudit.gui import controller as ctl

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CATALOG = i18n.load("fr")


@pytest.fixture(autouse=True)
def _reclaim_windows_in_the_main_thread() -> Iterator[None]:
    """Une fenêtre créée par un test est libérée ici, dans le fil principal ; sinon
    le ramasse-miettes la libère plus tard dans le fil d'audit d'un autre test, hors
    du fil de Tcl (voir ``qaudit.gui.app.reclaim_destroyed_windows``)."""
    yield
    from qaudit.gui.app import reclaim_destroyed_windows

    reclaim_destroyed_windows()


def _request(
    tmp_path: Path, name: str = "healthy_witness", **overrides: Any
) -> ctl.AuditRequest:
    base = ctl.AuditRequest(
        trades=FIXTURES / f"{name}.csv",
        out_dir=tmp_path / "out",
        initial_balance=10_000.0,
        n_iter=400,
        cache_dir=tmp_path / "cache",
    )
    return replace(base, **overrides)


def test_controller_audit_matches_the_cli_byte_for_byte(tmp_path: Path) -> None:
    logs: list[str] = []
    outcome = ctl.run_request(_request(tmp_path), CATALOG, log=logs.append)
    assert isinstance(outcome, ctl.AuditDone)
    assert outcome.decision == "GO_CONDITIONAL"
    assert not outcome.human_review
    assert outcome.archive.exists()
    assert {p.suffix for p in outcome.deliverables} == {".html", ".pdf", ".json"}
    assert any("600" in line for line in logs)
    code = cli_main(["audit", str(FIXTURES / "healthy_witness.csv"), "--out",
                     str(tmp_path / "cli"), "--initial-balance", "10000", "--n-iter", "400",
                     "--cache-dir", str(tmp_path / "cache2")])
    assert code == 1
    cli_archive = tmp_path / "cli" / "archive" / "healthy_witness.json"
    assert cli_archive.read_bytes() == outcome.archive.read_bytes()


def test_controller_with_prices_walkforward_and_ruleset(tmp_path: Path) -> None:
    outcome = ctl.run_request(
        _request(tmp_path, prices=FIXTURES / "healthy_witness_prices.csv", symbol="EURUSD",
                 walkforward=FIXTURES / "walkforward" / "healthy_witness",
                 ruleset="two_step_static", profile="due_diligence", lang="en"),
        i18n.load("en"),
    )
    assert isinstance(outcome, ctl.AuditDone)
    assert outcome.decision == "GO"
    assert outcome.document["propfirm"] is not None
    assert outcome.document["walkforward"]["n_candidates"] == 3


def test_controller_gate_e1_then_mapping_resumes(tmp_path: Path) -> None:
    request = _request(tmp_path, name="exotic_columns")
    outcome = ctl.run_request(request, CATALOG)
    assert isinstance(outcome, ctl.MappingNeeded)
    assert outcome.missing_fields == ("profit",)
    assert "Résultat net" in outcome.seen_columns
    assert len(outcome.header_fingerprint) == 64
    columns = ctl.table_columns(request.trades, "auto")
    assert columns == outcome.seen_columns
    mapping_path = ctl.save_mapping(
        tmp_path / "m.toml",
        {"open_time": "Ouverture", "close_time": "Fermeture", "profit": "Résultat net",
         "volume": "", "symbol": "Instrument"},
        columns,
    )
    text = mapping_path.read_text(encoding="utf-8")
    assert 'profit = "Résultat net"' in text
    assert "volume" not in text
    again = ctl.run_request(_request(tmp_path, name="exotic_columns", mapping=mapping_path),
                            CATALOG)
    assert isinstance(again, ctl.AuditDone)
    # mémorisée : un troisième passage sans --mapping passe
    third = ctl.run_request(_request(tmp_path, name="exotic_columns"), CATALOG)
    assert isinstance(third, ctl.AuditDone)


def test_controller_gate_e2_returns_skeleton(tmp_path: Path) -> None:
    prose = tmp_path / "rules.txt"
    prose.write_text("Perte max 10 %.", encoding="utf-8")
    outcome = ctl.run_request(_request(tmp_path, ruleset=str(prose)), CATALOG)
    assert isinstance(outcome, ctl.RulesetNeeded)
    assert "[[phases]]" in outcome.skeleton
    assert "TOML" in outcome.message


def test_controller_reports_invalid_data_and_internal_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("open_time,close_time,profit\n2021-01-04 09:00,2021-01-04 10:00,abc\n",
                   encoding="utf-8")
    outcome = ctl.run_request(_request(tmp_path, trades=bad), CATALOG)
    assert isinstance(outcome, ctl.Failed)
    assert outcome.exit_code == 20
    assert "ligne 2" in outcome.message
    assert "profit" in outcome.message

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("panne")

    monkeypatch.setattr(ctl, "run_audit", boom)
    internal = ctl.run_request(_request(tmp_path), CATALOG)
    assert isinstance(internal, ctl.Failed)
    assert internal.exit_code == 30
    assert "RuntimeError" in internal.message


def test_archive_helpers_and_render(tmp_path: Path) -> None:
    done = ctl.run_request(_request(tmp_path, name="martingale"), CATALOG)
    assert isinstance(done, ctl.AuditDone)
    archives = ctl.list_archives(tmp_path / "out")
    assert [a.stem for a in archives] == ["martingale"]
    summary = ctl.archive_summary(archives[0])
    assert summary["decision"] == "NO_GO"
    assert summary["n_trades"] == "600"
    document, written = ctl.render_archive(archives[0], tmp_path / "again", CATALOG,
                                           "verdict_propfirm")
    assert document["verdict"]["decision"] == "NO_GO"
    assert {p.suffix for p in written} == {".html", ".pdf"}
    assert ctl.list_archives(tmp_path / "nowhere") == ()


def test_choices_and_labels() -> None:
    choices = ctl.Choices()
    assert len(choices.profiles) == 7
    assert len(choices.rulesets) == 4
    assert choices.kinds[0] == "auto"
    assert ctl.profile_label("audit_complet") == "Audit complet (audit_complet)"
    assert ctl.profile_label("attestation_cessible").startswith("Attestation cessible (")
    about = ctl.about_text(CATALOG)
    assert "1.0.0" in about
    assert "30" in about


def _display_available() -> bool:
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


@pytest.mark.skipif(not _display_available(), reason="aucun affichage disponible")
def test_window_builds_and_shows_an_outcome(tmp_path: Path) -> None:
    from qaudit.gui.app import App

    app = App("fr")
    warnings: list[str] = []
    app.warn = warnings.append
    try:
        app.withdraw()
        assert app.title() == "qaudit 1.0.0"
        assert app.request() is None  # pas de fichier : message et refus
        assert warnings == ["Choisir d'abord un fichier de trades."]
        app.v_trades.set(str(FIXTURES / "healthy_witness.csv"))
        app.v_balance.set("10 000")
        app.v_n_iter.set("300")
        app.v_out.set(str(tmp_path / "out"))
        request = app.request()
        assert request is not None
        assert request.initial_balance == 10_000.0
        assert request.n_iter == 300
        outcome = ctl.run_request(request, app.catalog)
        assert isinstance(outcome, ctl.AuditDone)
        app._show_outcome(request, outcome)
        app.update()
        assert app.decision_label.cget("text") == "GO SOUS CONDITIONS"
        assert len(app.barriers.get_children()) == 5
        assert len(app.findings.get_children()) == len(outcome.result.findings)
        assert len(app.history.get_children()) == 1
        app.v_seed.set("x")
        assert app.request() is None  # nombre invalide refusé
        assert warnings[-1].startswith("Solde initial, graine")
    finally:
        app.destroy()


def test_gui_strings_are_all_in_both_catalogues() -> None:
    fr, en = i18n.load("fr"), i18n.load("en")
    gui_keys = {k for k in fr.keys if k.startswith("gui.")}
    assert len(gui_keys) > 60
    assert gui_keys == {k for k in en.keys if k.startswith("gui.")}
    doc = json.loads((FIXTURES / "golden" / "healthy_witness.json").read_text(encoding="utf-8"))
    assert doc["verdict"]["decision"] == "GO_CONDITIONAL"


def test_launch_options_are_parsed() -> None:
    from qaudit.gui.app import parse_args

    assert parse_args([]) == {}
    parsed = parse_args(["trades.csv", "--lang", "en", "--out", "o", "--initial-balance",
                         "10000", "--run", "--exit-after"])
    assert parsed == {"trades": "trades.csv", "lang": "en", "out": "o",
                      "initial_balance": "10000", "run": True, "exit_after": True}


@pytest.mark.skipif(not _display_available(), reason="aucun affichage disponible")
def test_launch_with_file_run_and_exit_returns_the_verdict_code(tmp_path: Path) -> None:
    from qaudit.gui.app import App, main

    code = main([str(FIXTURES / "healthy_witness.csv"), "--initial-balance", "10000",
                 "--out", str(tmp_path / "out"), "--run", "--exit-after"])
    assert code == 1
    assert (tmp_path / "out" / "archive" / "healthy_witness.json").exists()
    code = main([str(FIXTURES / "exotic_columns.csv"), "--out", str(tmp_path / "out"),
                 "--run", "--exit-after"])
    assert code == 10
    # la fenêtre est libérée par main(), dans le fil de Tcl, pas par un passage
    # ultérieur du ramasse-miettes dans le fil d'audit d'une autre fenêtre
    assert not [o for o in gc.get_objects() if isinstance(o, App)]


@pytest.mark.skipif(not _display_available(), reason="aucun affichage disponible")
def test_load_example_prefills_the_embedded_witness(tmp_path: Path) -> None:
    from qaudit.gui.app import App

    app = App("fr")
    try:
        app.withdraw()
        app.v_out.set(str(tmp_path / "out"))
        app.load_example()
        request = app.request()
        assert request is not None
        assert request.trades.name == "healthy_witness.csv"
        assert request.trades.exists()
        assert request.initial_balance == 10_000.0
        assert request.walkforward is not None
        assert request.walkforward.is_dir()
        assert request.ruleset == "two_step_static"
        outcome = ctl.run_request(replace(request, n_iter=300), app.catalog)
        assert isinstance(outcome, ctl.AuditDone)
        assert outcome.decision == "GO"
    finally:
        app.destroy()


def test_controller_reports_offer_inputs_missing_from_the_file(tmp_path: Path) -> None:
    logs: list[str] = []
    outcome = ctl.run_request(
        _request(tmp_path, profile="audit_prix"), CATALOG, log=logs.append
    )
    assert isinstance(outcome, ctl.AuditDone)
    assert outcome.warning is not None
    assert "série de prix" in outcome.warning
    assert outcome.warning in logs
    assert outcome.decision == "GO_CONDITIONAL"  # R1 : le verdict ne dépend pas de l'offre
    fine = ctl.run_request(_request(tmp_path, profile="audit_complet"), CATALOG)
    assert isinstance(fine, ctl.AuditDone)
    assert fine.warning is None
