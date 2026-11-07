# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sorties : document JSON versionné et conforme au schéma, déterminisme à
l'octet (N-01, N-02), HTML/PDF, profils d'offre (T-410a … T-410g)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from qaudit import i18n
from qaudit.core.audit import AuditOptions, AuditResult, run_audit
from qaudit.core.config import MethodConfig
from qaudit.core.errors import DataError
from qaudit.core.models import Decision
from qaudit.core.validate import ValidationResult, validate
from qaudit.io.document import SCHEMA_VERSION, dumps, loads, number, to_document
from qaudit.io.method import load_method
from qaudit.io.outputs import render_outputs, write_deliverables, write_document, write_outputs
from qaudit.io.profile import MANDATORY, SECTIONS, builtin_profiles, load_profile, parse_profile
from qaudit.io.readers.common import infer_mapping
from qaudit.io.readers.csv_generic import read_csv_generic
from qaudit.io.readers.prices import read_prices
from qaudit.io.ruleset import load_ruleset
from qaudit.io.writers.html_writer import render_html
from qaudit.io.writers.pdf_writer import render_pdf
from qaudit.io.writers.render import Fmt, build_view
from tests.helpers import make_tradeset

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCHEMA = (
    Path(__file__).resolve().parents[1] / "qaudit" / "io" / "writers" / "schema" / "report-1.0.json"
)
FAST = AuditOptions(seed=3, n_iter=1500)


@pytest.fixture(scope="module")
def config() -> MethodConfig:
    return load_method()


def _load(name: str, config: MethodConfig, balance: float = 10_000.0) -> ValidationResult:
    table = read_csv_generic(FIXTURES / f"{name}.csv")
    return validate(
        table,
        infer_mapping(table.columns),
        max_gap_days=config.max_gap_days,
        initial_balance=balance,
    )


@pytest.fixture(scope="module")
def witness(config: MethodConfig) -> AuditResult:
    prices = read_prices(FIXTURES / "healthy_witness_prices.csv", "EURUSD")
    return run_audit(
        _load("healthy_witness", config),
        config,
        FAST,
        prices=prices,
        ruleset=load_ruleset("two_step_static"),
    )


@pytest.fixture(scope="module")
def martingale(config: MethodConfig) -> AuditResult:
    return run_audit(_load("martingale", config), config, FAST)


# ---------------------------------------------------------------------------
# validateur JSON Schema minimal (sous-ensemble utilisé par report-1.0.json)
# ---------------------------------------------------------------------------


def _resolve(schema: Mapping[str, Any], root: Mapping[str, Any]) -> Mapping[str, Any]:
    if "$ref" not in schema:
        return schema
    target: Any = root
    for part in schema["$ref"].lstrip("#/").split("/"):
        target = target[part]
    return _resolve(target, root)


def _check_scalar(
    instance: object, schema: Mapping[str, Any], root: Mapping[str, Any], path: str
) -> None:
    if "const" in schema:
        assert instance == schema["const"], path
    if "enum" in schema:
        assert instance in schema["enum"], f"{path}: {instance!r} not in {schema['enum']}"
    if "oneOf" in schema:
        matches = 0
        for option in schema["oneOf"]:
            try:
                _check(instance, option, root, path)
                matches += 1
            except AssertionError:
                continue
        assert matches == 1, f"{path}: {instance!r} matched {matches} alternatives"
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        assert any(_is_type(instance, t) for t in types), f"{path}: {instance!r} is not {types}"
    if "pattern" in schema and isinstance(instance, str):
        assert re.match(schema["pattern"], instance), path


def _check(instance: object, schema: Mapping[str, Any], root: Mapping[str, Any], path: str) -> None:
    schema = _resolve(schema, root)
    _check_scalar(instance, schema, root, path)
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            assert key in instance, f"{path}: missing {key}"
        for key, sub in schema.get("properties", {}).items():
            if key in instance:
                _check(instance[key], sub, root, f"{path}.{key}")
    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            _check(item, schema["items"], root, f"{path}[{i}]")


def _is_type(value: object, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    return value is None


def validate_schema(document: Mapping[str, Any]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    _check(document, schema, schema, "$")


# ---------------------------------------------------------------------------
# document
# ---------------------------------------------------------------------------


def test_document_conforms_to_published_schema(
    witness: AuditResult, martingale: AuditResult
) -> None:
    for result in (witness, martingale):
        document = to_document(result)
        validate_schema(document)
        assert document["schema_version"] == SCHEMA_VERSION
        # aller-retour texte : identique
        assert loads(dumps(document)) == document


def test_document_carries_the_four_traceability_fields(witness: AuditResult) -> None:
    document = to_document(witness)
    assert document["engine_version"] == "1.0.0"
    assert document["method_version"] == "1.0"
    assert document["seed"] == 3
    assert re.fullmatch(r"[0-9a-f]{64}", document["data"]["fingerprint"])


def test_document_has_no_natural_language(witness: AuditResult) -> None:
    text = dumps(to_document(witness))
    # les constats ne portent que des clés : aucune phrase française ni anglaise
    assert "message_key" in text
    for forbidden in (
        "Martingale :",
        "Martingale:",
        "Grille :",
        "RUINE",
        "probabilité",
        "Verdict :",
    ):
        assert forbidden not in text


def test_non_finite_numbers_are_encoded_explicitly(config: MethodConfig) -> None:
    result = run_audit(ValidationResult(make_tradeset([5.0] * 40), (), None), config, FAST)
    document = to_document(result)
    validate_schema(document)
    assert document["metrics"]["profit_factor"] == "Infinity"
    assert document["metrics"]["avg_loss"] == "NaN"
    assert number("Infinity") == float("inf")
    assert number(document["metrics"]["n"]) == 40.0
    text = dumps(document)
    assert "NaN" in text
    assert "Infinity" in text
    json.loads(text, parse_constant=lambda _: pytest.fail("constante JSON non standard"))


def test_document_is_byte_identical_across_runs_and_processes(config: MethodConfig) -> None:
    """N-01 : mêmes entrées, même version, même graine → JSON identique à l'octet."""
    prices = read_prices(FIXTURES / "healthy_witness_prices.csv", "EURUSD")
    runs = []
    for _ in range(2):
        result = run_audit(
            _load("healthy_witness", config),
            config,
            AuditOptions(seed=11, n_iter=2000),
            prices=prices,
            ruleset=load_ruleset("one_step_trailing"),
        )
        runs.append(dumps(to_document(result)).encode("utf-8"))
    assert runs[0] == runs[1]
    assert len(runs[0]) > 5_000


def test_golden_witness_document_matches_committed_bytes(config: MethodConfig) -> None:
    """Test doré : le document du témoin (graine 1, 2 000 itérations) est figé.

    S'il change, soit la méthode a changé (et sa version doit être incrémentée),
    soit le déterminisme est rompu.
    """
    golden = FIXTURES / "golden" / "healthy_witness.json"
    result = run_audit(_load("healthy_witness", config), config, AuditOptions(seed=1, n_iter=2000))
    produced = dumps(to_document(result)).encode("utf-8")
    if not golden.exists():  # première génération : on fige
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_bytes(produced)
    assert produced == golden.read_bytes()


# ---------------------------------------------------------------------------
# HTML et PDF
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", i18n.LANGUAGES)
def test_html_report_renders_every_section_of_the_profile(witness: AuditResult, lang: str) -> None:
    profile = load_profile("due_diligence")
    view = build_view(to_document(witness), i18n.load(lang), profile, system_name="w")
    html = render_html(view)
    assert html.startswith("<!DOCTYPE html>")
    for section in profile.sections:
        assert f'id="{section}"' in html
    assert "[report." not in html  # aucune clé non traduite
    assert "[detector." not in html


def test_pdf_is_well_formed_and_deterministic(witness: AuditResult) -> None:
    profile = load_profile("audit_complet")
    view = build_view(to_document(witness), i18n.load("fr"), profile, system_name="w")
    pdf = render_pdf(view)
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert pdf == render_pdf(view)
    match = re.search(rb"startxref\n(\d+)\n%%EOF", pdf)
    assert match is not None
    xref = int(match.group(1))
    assert pdf[xref : xref + 4] == b"xref"
    offsets = re.findall(rb"(\d{10}) 00000 n", pdf[xref:])
    for i, off in enumerate(offsets):
        assert pdf[int(off) :].startswith(b"%d 0 obj" % (i + 1))
    assert pdf.count(b"/Type /Page ") >= 2
    assert b"/CreationDate" not in pdf


def test_pdf_transliterates_characters_outside_winansi(witness: AuditResult) -> None:
    view = build_view(
        to_document(witness),
        i18n.load("fr"),
        load_profile("audit_complet"),
        system_name="système ≥ γ → ok",
    )
    pdf = render_pdf(view)
    assert b">=" in pdf
    assert b"gamma" in pdf
    assert b"->" in pdf


# ---------------------------------------------------------------------------
# profils d'offre (F-410)
# ---------------------------------------------------------------------------


def test_T410a_seven_profiles_load_and_unknown_section_is_rejected() -> None:  # noqa: N802
    names = builtin_profiles()
    assert len(names) == 7
    assert set(names) == {
        "pre_verification",
        "verdict_propfirm",
        "audit_complet",
        "audit_prix",
        "portefeuille",
        "attestation_cessible",
        "due_diligence",
    }
    for name in names:
        profile = load_profile(name)
        assert profile.code == name
        assert set(profile.sections) <= set(SECTIONS)
    raw = {
        "offre": {"code": "x", "libelle": "x"},
        "entrees": {},
        "livrables": {},
        "rapport": {"sections": [*MANDATORY, "section_inconnue"]},
    }
    with pytest.raises(DataError) as info:
        parse_profile(raw)
    assert info.value.key == "profile.unknown_section"
    assert info.value.column == "section_inconnue"


def test_T410b_profile_missing_a_mandatory_section_is_rejected() -> None:  # noqa: N802
    for missing in MANDATORY:
        sections = [s for s in MANDATORY if s != missing]
        raw = {
            "offre": {"code": "x", "libelle": "x"},
            "entrees": {},
            "livrables": {},
            "rapport": {"sections": sections},
        }
        with pytest.raises(DataError) as info:
            parse_profile(raw)
        assert info.value.key == "profile.missing_mandatory_section"
        assert info.value.column == missing


def test_T410c_verdict_is_identical_across_profiles(martingale: AuditResult) -> None:  # noqa: N802
    document = to_document(martingale)
    decisions = set()
    for name in builtin_profiles():
        view = build_view(document, i18n.load("fr"), load_profile(name), system_name="m")
        decisions.add((view.decision_code, view.human_review))
        assert view.decision_code == document["verdict"]["decision"] == Decision.NO_GO.value
    assert len(decisions) == 1


def test_T410d_critical_findings_traverse_every_profile(martingale: AuditResult) -> None:  # noqa: N802
    document = to_document(martingale)
    catalog = i18n.load("fr")
    critical = [f for f in document["findings"] if f["severity"] in ("blocking", "major")]
    assert critical, "la fixture martingale doit porter des constats critiques"
    for name in builtin_profiles():
        html = render_html(build_view(document, catalog, load_profile(name), system_name="m"))
        for finding in critical:
            full_text = catalog.text(finding["message_key"], **finding["params"])
            assert finding["code"] in html
            assert full_text.replace("'", "&#x27;") in html or full_text in html


def test_T410e_render_from_archive_is_byte_identical(witness: AuditResult, tmp_path: Path) -> None:  # noqa: N802
    catalog = i18n.load("fr")
    profile = load_profile("audit_complet")
    _, written = write_outputs(witness, tmp_path / "direct", catalog, profile, system_name="w")
    reloaded = loads(written.archive.read_text(encoding="utf-8"))
    again = write_deliverables(
        reloaded, tmp_path / "from_archive", catalog, profile, system_name="w"
    )
    assert [p.name for p in again] == [p.name for p in written.deliverables]
    for a, b in zip(sorted(written.deliverables), sorted(again), strict=True):
        assert a.read_bytes() == b.read_bytes(), a.name


def test_T410f_core_knows_nothing_about_offers_or_prices() -> None:  # noqa: N802
    core = Path(__file__).resolve().parents[1] / "qaudit" / "core"
    pattern = re.compile(r"\b(offre|profil|prix|tarif)\b", re.IGNORECASE)
    for path in core.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), (path, pattern.search(text))


def test_T410g_full_json_is_archived_even_when_not_delivered(  # noqa: N802
    witness: AuditResult, tmp_path: Path
) -> None:
    profile = load_profile("verdict_propfirm")
    assert not profile.json
    document, written = write_outputs(witness, tmp_path, i18n.load("fr"), profile, system_name="w")
    assert written.archive == tmp_path / "archive" / "w.json"
    assert written.archive.exists()
    assert loads(written.archive.read_text(encoding="utf-8")) == document
    assert {p.suffix for p in written.deliverables} == {".html", ".pdf"}
    outputs = render_outputs(document, i18n.load("fr"), profile, system_name="w")
    assert set(outputs) == {"html", "pdf"}


def test_profile_sections_follow_canonical_order_and_filter_content(witness: AuditResult) -> None:
    document = to_document(witness)
    view = build_view(document, i18n.load("en"), load_profile("verdict_propfirm"), system_name="w")
    ids = [s.id for s in view.sections]
    assert ids == [s for s in SECTIONS if s in ids]
    assert "propfirm_challenge" in ids
    assert "monte_carlo" not in ids
    html = render_html(view)
    assert 'id="monte_carlo"' not in html
    assert 'id="verdict"' in html


def test_write_document_is_the_canonical_archive(witness: AuditResult, tmp_path: Path) -> None:
    document = to_document(witness)
    path = write_document(document, tmp_path, "sys")
    assert path.read_bytes() == dumps(document).encode("utf-8")


# ---------------------------------------------------------------------------
# « En clair » : explication client, textes du catalogue, chiffres du document
# ---------------------------------------------------------------------------


def test_explain_catalogues_are_complete_in_both_languages() -> None:
    fr, en = i18n.load("fr"), i18n.load("en")
    fr_keys = {k for k in fr.keys if k.startswith("explain.")}
    assert fr_keys == {k for k in en.keys if k.startswith("explain.")}
    for section in SECTIONS:
        if section != "en_clair":
            assert f"explain.section.{section}" in fr_keys, section
    for barrier in ("dsr", "pf_p05", "dd_percentile", "null_pvalue", "wf_efficiency"):
        assert f"explain.barrier.{barrier}" in fr_keys
        assert f"explain.barrier_title.{barrier}" in fr_keys


def test_en_clair_is_in_every_profile_and_names_the_documents_numbers(
    martingale: AuditResult,
) -> None:
    document = to_document(martingale)
    catalog = i18n.load("fr")
    fmt = Fmt(catalog)
    for name in builtin_profiles():
        view = build_view(document, catalog, load_profile(name), system_name="m")
        section = next(s for s in view.sections if s.id == "en_clair")
        assert section.paragraphs[0].startswith("Feu rouge")
        assert all(s.help for s in view.sections if s.id not in ("en_clair",))
        # cinq barrières expliquées, dans l'ordre de la méthode, avec leur valeur
        barrier_entries = section.entries[:5]
        for entry, barrier in zip(barrier_entries, document["verdict"]["barriers"], strict=True):
            assert entry.tag in ("passed", "triggered", "indecision", "not_evaluated")
            if barrier["evaluated"] and barrier["name"] == "pf_p05":
                assert fmt.num(barrier["value"], 3) in entry.text
        # les constats critiques y sont, titrés en langage courant
        critical = [f for f in document["findings"] if f["severity"] in ("blocking", "major")]
        titles = [e.code for e in section.entries[5:]]
        assert len(titles) == len(critical)
        assert "Mise augmentée après les pertes" in titles  # martingale
        assert section.closing[-2].startswith("Un feu rouge ne se corrige pas dans le rapport")
        html = render_html(view)
        assert 'id="en_clair"' in html
        assert "Comment lire cette section" in html
        assert "[explain." not in html


def test_en_clair_reasons_never_name_a_zero_count(witness: AuditResult) -> None:
    view = build_view(to_document(witness), i18n.load("en"), load_profile("audit_complet"),
                      system_name="w")
    section = next(s for s in view.sections if s.id == "en_clair")
    first = section.paragraphs[0]
    assert first.startswith("Amber light")
    assert "1 test(s) could not be run" in first
    assert " 0 " not in first
    assert section.closing[0].startswith("No serious flaw")
    pdf = render_pdf(view)
    assert b"How to read this section".upper() in pdf.upper()
