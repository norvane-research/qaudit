# SPDX-License-Identifier: AGPL-3.0-or-later
"""Attestation de validation : registre, émission, refus, vérification, page
publique. L'attestation est un acte d'émission (état externe) : le rapport et
l'archive restent identiques avec ou sans elle."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from qaudit import i18n
from qaudit.cli.main import main
from qaudit.core.errors import DataError
from qaudit.gui import controller as ctl
from qaudit.io.outputs import issue_attestation, maybe_attest
from qaudit.io.profile import load_profile
from qaudit.io.registry import Registry
from qaudit.io.writers.attestation import registry_page

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = FIXTURES / "golden"
FAST = ["--n-iter", "400"]


def _go_document(tmp_path: Path) -> Path:
    """Archive GO : le témoin sain avec prix et walk-forward (verdict GO, exit 0)."""
    out = tmp_path / "go"
    code = main([
        "audit", str(FIXTURES / "healthy_witness.csv"), "--out", str(out), "--initial-balance",
        "10000", "--prices", str(FIXTURES / "healthy_witness_prices.csv"), "--symbol", "EURUSD",
        "--walkforward", str(FIXTURES / "walkforward" / "healthy_witness"),
        "--cache-dir", str(tmp_path / "c"), "--registry", str(tmp_path / "none.jsonl"),
        "--offre", "pre_verification", *FAST,
    ])
    assert code == 0
    return out / "archive" / "healthy_witness.json"


def test_registry_numbers_per_year_and_is_idempotent(tmp_path: Path) -> None:
    document = json.loads((GOLDEN / "healthy_witness.json").read_text(encoding="utf-8"))
    document["verdict"]["decision"] = "GO"  # seul le registre est testé ici
    registry = Registry(tmp_path / "r" / "registre.jsonl")
    first = registry.issue(document, system_name="a", profile="audit_complet",
                           transferable=False, issued_on=date(2026, 9, 21), holder="X")
    again = registry.issue(document, system_name="a", profile="audit_complet",
                           transferable=False, issued_on=date(2026, 9, 22))
    assert first.reference == "AUD-2026-001"
    assert again == first  # même empreinte + versions : même attestation, pas de doublon
    other = dict(document)
    other["data"] = dict(document["data"], fingerprint="f" * 64)
    second = registry.issue(other, system_name="b", profile="audit_complet",
                            transferable=True, issued_on=date(2026, 9, 21))
    assert second.reference == "AUD-2026-002"
    third = registry.issue(dict(other, data=dict(other["data"], fingerprint="e" * 64)),
                           system_name="c", profile="audit_complet", transferable=False,
                           issued_on=date(2027, 1, 5))
    assert third.reference == "AUD-2027-001"
    assert registry.lookup("aud-2026-002").system_name == "b"
    with pytest.raises(DataError) as info:
        registry.lookup("AUD-2026-999")
    assert info.value.key == "attestation.not_found"
    lines = (tmp_path / "r" / "registre.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert all(json.loads(line)["reference"].startswith("AUD-") for line in lines)
    assert "holder" not in first.public()


def test_non_go_archive_is_refused(tmp_path: Path) -> None:
    document = json.loads((GOLDEN / "healthy_witness.json").read_text(encoding="utf-8"))
    assert document["verdict"]["decision"] == "GO_CONDITIONAL"
    registry = Registry(tmp_path / "registre.jsonl")
    with pytest.raises(DataError) as info:
        issue_attestation(document, tmp_path, i18n.load("fr"), load_profile("audit_complet"),
                          system_name="w", registry=registry, issued_on=date(2026, 9, 21))
    assert info.value.key == "attestation.refused"
    skipped = maybe_attest(document, tmp_path, i18n.load("fr"), load_profile("audit_complet"),
                           system_name="w", registry=registry, issued_on=date(2026, 9, 21))
    assert skipped == (None, ())
    assert not (tmp_path / "registre.jsonl").exists()
    assert not list(tmp_path.glob("*-attestation.*"))


def test_cli_attest_verify_and_public_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = _go_document(tmp_path)
    registry = tmp_path / "registre.jsonl"
    code = main(["attest", "--from", str(archive), "--out", str(tmp_path / "a"), "--offre",
                 "attestation_cessible", "--registry", str(registry), "--holder", "Studio X",
                 "--issuer", "Auditeur Y", "--issued-on", "2026-09-21"])
    out = capsys.readouterr().out
    assert code == 0
    assert "AUD-2026-001" in out
    html = (tmp_path / "a" / "healthy_witness-attestation.html").read_text(encoding="utf-8")
    pdf = (tmp_path / "a" / "healthy_witness-attestation.pdf").read_bytes()
    document = json.loads(archive.read_text(encoding="utf-8"))
    fingerprint = document["data"]["fingerprint"]
    assert fingerprint in html
    assert "Studio X" in html
    assert "Auditeur Y" in html
    assert "Cessible" in html
    assert "ne garantit aucune performance future" in html
    assert pdf.startswith(b"%PDF-1.4")
    assert b"AUD-2026-001" in pdf
    # ré-émission : même référence, mêmes octets (déterminisme de l'acte)
    code = main(["attest", "--from", str(archive), "--out", str(tmp_path / "b"), "--offre",
                 "attestation_cessible", "--registry", str(registry), "--issued-on", "2026-10-01"])
    assert code == 0
    assert (tmp_path / "b" / "healthy_witness-attestation.pdf").read_bytes() == pdf
    # refus d'une archive NO-GO : code du verdict, rien d'écrit
    main(["audit", str(FIXTURES / "martingale.csv"), "--out", str(tmp_path / "m"),
          "--initial-balance", "10000", "--cache-dir", str(tmp_path / "c"),
          "--registry", str(registry), "--offre", "audit_complet", *FAST])
    capsys.readouterr()
    code = main(["attest", "--from", str(tmp_path / "m" / "archive" / "martingale.json"),
                 "--out", str(tmp_path / "m"), "--registry", str(registry)])
    err = capsys.readouterr().err
    assert code == 2
    assert "refusée" in err
    assert not list((tmp_path / "m").glob("*-attestation.*"))
    # vérification
    code = main(["verify", "AUD-2026-001", "--registry", str(registry)])
    out = capsys.readouterr().out
    assert code == 0
    assert fingerprint in out
    assert main(["verify", "AUD-2026-042", "--registry", str(registry)]) == 20
    capsys.readouterr()
    # page publique : empreinte oui, titulaire et émetteur non
    page = tmp_path / "public" / "registre.html"
    code = main(["registre", "--registry", str(registry), "--html", str(page)])
    assert code == 0
    text = page.read_text(encoding="utf-8")
    assert fingerprint in text
    assert "AUD-2026-001" in text
    assert "Studio X" not in text
    assert "Auditeur Y" not in text
    assert registry_page((), i18n.load("en")).count("<tr>") == 1


def test_audit_with_attesting_profile_issues_automatically_on_go(tmp_path: Path) -> None:
    registry = tmp_path / "registre.jsonl"
    out = tmp_path / "go"
    code = main([
        "audit", str(FIXTURES / "healthy_witness.csv"), "--out", str(out), "--initial-balance",
        "10000", "--prices", str(FIXTURES / "healthy_witness_prices.csv"), "--symbol", "EURUSD",
        "--walkforward", str(FIXTURES / "walkforward" / "healthy_witness"),
        "--cache-dir", str(tmp_path / "c"), "--registry", str(registry),
        "--offre", "audit_complet", "--issued-on", "2026-09-21", *FAST,
    ])
    assert code == 0
    assert (out / "healthy_witness-attestation.html").exists()
    assert (out / "healthy_witness-attestation.pdf").exists()
    assert "Nominative" in (out / "healthy_witness-attestation.html").read_text(encoding="utf-8")
    assert Registry(registry).lookup("AUD-2026-001").profile == "audit_complet"
    # une offre sans attestation n'en émet pas, même sur GO
    code = main([
        "render", "--from", str(out / "archive" / "healthy_witness.json"), "--out",
        str(tmp_path / "pv"), "--offre", "pre_verification", "--registry", str(registry),
    ])
    assert code == 0
    assert not list((tmp_path / "pv").glob("*-attestation.*"))


def test_controller_issues_attestation_on_go(tmp_path: Path) -> None:
    logs: list[str] = []
    request = ctl.AuditRequest(
        trades=FIXTURES / "healthy_witness.csv", out_dir=tmp_path / "out",
        initial_balance=10_000.0, n_iter=400, cache_dir=tmp_path / "cache",
        prices=FIXTURES / "healthy_witness_prices.csv", symbol="EURUSD",
        walkforward=FIXTURES / "walkforward" / "healthy_witness", profile="audit_complet",
        registry=tmp_path / "registre.jsonl", holder="Client Z",
    )
    outcome = ctl.run_request(request, i18n.load("fr"), log=logs.append)
    assert isinstance(outcome, ctl.AuditDone)
    assert outcome.decision == "GO"
    assert any(p.name == "healthy_witness-attestation.pdf" for p in outcome.deliverables)
    assert any("AUD-2026-001" in line or "AUD-" in line for line in logs)
