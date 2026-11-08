# SPDX-License-Identifier: AGPL-3.0-or-later
"""Badge d'attestation : SVG léger qui porte la référence, extraits HTML et
Markdown vers la vérification pré-remplie, et refus de tout badge pour une
référence absente du registre."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pytest

from qaudit import i18n
from qaudit.cli.main import main
from qaudit.io.registry import Registry
from qaudit.io.writers.badge import badge_kit, badge_links, badge_svg

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
SVG = "{http://www.w3.org/2000/svg}"


def _registry(tmp_path: Path, issuer: str | None = "Norvane Research") -> Path:
    document = json.loads((GOLDEN / "healthy_witness.json").read_text(encoding="utf-8"))
    document["verdict"]["decision"] = "GO"
    path = tmp_path / "registre.jsonl"
    Registry(path).issue(document, system_name="witness", profile="audit_complet",
                         transferable=True, issued_on=date(2026, 11, 8), issuer=issuer)
    return path


def test_svg_is_light_well_formed_and_carries_the_reference() -> None:
    svg = badge_svg("AUD-2026-001", i18n.load("en"), "Norvane Research")
    assert len(svg.encode("utf-8")) < 1500  # léger : pas de police ni d'image embarquée
    root = ET.fromstring(svg)
    texts = [t.text for t in root.iter(f"{SVG}text")]
    assert texts == ["Audited by Norvane Research", "AUD-2026-001"]
    assert root.find(f"{SVG}title") is not None
    assert "AUD-2026-001" in root.attrib["aria-label"]
    assert "href" not in svg
    assert "http" not in svg.replace("http://www.w3.org/2000/svg", "")
    french = ET.fromstring(badge_svg("AUD-2026-001", i18n.load("fr"), "Norvane Research"))
    assert next(t.text for t in french.iter(f"{SVG}text")) == "Audité par Norvane Research"
    engine = ET.fromstring(badge_svg("AUD-2026-001", i18n.load("en"), None))
    assert next(t.text for t in engine.iter(f"{SVG}text")) == "Audited with qaudit"
    assert int(engine.attrib["width"]) < int(root.attrib["width"])  # largeur suit le libellé


def test_links_point_to_the_prefilled_verification_and_the_hosted_image() -> None:
    links = badge_links("AUD-2026-001", "https://exemple.org/en/", i18n.load("en"), "X")
    assert links.verify_url == "https://exemple.org/en/verification?ref=AUD-2026-001"
    assert links.image_url == "https://exemple.org/en/badge/AUD-2026-001.svg"
    assert links.html() == (
        '<a href="https://exemple.org/en/verification?ref=AUD-2026-001">'
        '<img src="https://exemple.org/en/badge/AUD-2026-001.svg" '
        'alt="Audited by X — attestation AUD-2026-001" height="28"></a>')
    assert links.markdown() == (
        "[![Audited by X — attestation AUD-2026-001](https://exemple.org/en/badge/AUD-2026-001.svg)]"
        "(https://exemple.org/en/verification?ref=AUD-2026-001)")
    kit = badge_kit("AUD-2026-001", "<svg/>", links, i18n.load("en"))
    assert "&lt;a href=&quot;https://exemple.org/en/verification?ref=AUD-2026-001&quot;&gt;" in kit
    assert "What it does not prove" in kit


def test_cli_writes_the_kit_for_a_registered_reference(tmp_path: Path,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    registry = _registry(tmp_path)
    out = tmp_path / "kit"
    code = main(["badge", "aud-2026-001", "--registry", str(registry), "--site",
                 "https://exemple.org", "--lang", "fr", "--out", str(out)])
    assert code == 0
    svg = (out / "AUD-2026-001-badge.svg").read_text(encoding="utf-8")
    assert "Audité par Norvane Research" in svg
    kit = (out / "AUD-2026-001-badge.html").read_text(encoding="utf-8")
    assert "Votre badge — attestation AUD-2026-001" in kit
    assert "https://exemple.org/verification?ref=AUD-2026-001" in kit
    printed = capsys.readouterr().out
    assert "[![" in printed
    assert "https://exemple.org/badge/AUD-2026-001.svg" in printed


def test_cli_refuses_unknown_or_malformed_references(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    for reference in ("AUD-2026-002", "n'importe quoi"):
        out = tmp_path / reference.replace("'", "").replace(" ", "_")
        code = main(["badge", reference, "--registry", str(registry), "--site", "https://exemple.org",
                     "--out", str(out)])
        assert code == 20
        assert not out.exists() or not any(out.iterdir())


def test_cli_example_needs_no_registry_and_uses_a_generic_reference(tmp_path: Path) -> None:
    code = main(["badge", "--example", "--lang", "en", "--issuer", "Norvane Research",
                 "--out", str(tmp_path)])
    assert code == 0
    svg = (tmp_path / "AUD-YYYY-NNN-badge.svg").read_text(encoding="utf-8")
    assert "AUD-YYYY-NNN" in svg
    assert not list(tmp_path.glob("*.html"))


def test_registry_issuer_wins_over_the_command_line(tmp_path: Path) -> None:
    registry = _registry(tmp_path, issuer=None)
    code = main(["badge", "AUD-2026-001", "--registry", str(registry), "--issuer", "Repli",
                 "--lang", "en", "--out", str(tmp_path / "a")])
    assert code == 0
    svg = (tmp_path / "a" / "AUD-2026-001-badge.svg").read_text(encoding="utf-8")
    assert "Audited by Repli" in svg
    registry = _registry(tmp_path / "b", issuer="Norvane Research")
    main(["badge", "AUD-2026-001", "--registry", str(registry), "--issuer", "Autre",
          "--lang", "en", "--out", str(tmp_path / "c")])
    assert "Audited by Norvane Research" in (tmp_path / "c" / "AUD-2026-001-badge.svg").read_text(
        encoding="utf-8")
