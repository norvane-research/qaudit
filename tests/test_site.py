# SPDX-License-Identifier: AGPL-3.0-or-later
"""Site statique de l'offre : conversion Markdown minimale et assemblage complet
(pages, exemples rendus par le moteur, registre vide → page de vérification)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _module() -> object:
    path = ROOT / "packaging" / "build_site.py"
    spec = importlib.util.spec_from_file_location("build_site", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_site"] = module
    spec.loader.exec_module(module)
    return module


def test_markdown_subset_converts_headings_lists_tables_and_quotes() -> None:
    build_site = _module()
    md = (
        "# Titre\n\nUn **gras** et `code` et [lien](x.html).\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n\n- un\n- deux\n  suite\n\n> note\n"
    )
    html = build_site.md_to_html(md)  # type: ignore[attr-defined]
    assert "<h1>Titre</h1>" in html
    assert "<b>gras</b>" in html
    assert "<code>code</code>" in html
    assert '<a href="x.html">lien</a>' in html
    assert "<th>A</th>" in html
    assert "<td>2</td>" in html
    assert "<li>deux suite</li>" in html
    assert "<blockquote>note</blockquote>" in html


def test_site_builds_with_examples_and_public_pages(tmp_path: Path) -> None:
    build_site = _module()
    out = tmp_path / "site"
    build_site.build(out, tmp_path / "vide.jsonl")  # type: ignore[attr-defined]
    for name in ("index.html", "preparer.html", "methode.html", "donnees.html", "cgv.html",
                 "verification.html", "exemples/index.html", "exemples/temoin-sain.html",
                 "exemples/temoin-sain.pdf", "exemples/martingale.html", "exemples/martingale.pdf"):
        assert (out / name).exists(), name
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "390 €" in index
    assert "sur devis" in index
    assert "Licence commerciale" in index
    assert "Moteur open source" in index
    assert "ne conseille rien" in index
    assert "Transferable attestation" in (out / "en" / "index.html").read_text(encoding="utf-8")
    assert "Aucune attestation" in (out / "verification.html").read_text(encoding="utf-8")
    methode = (out / "methode.html").read_text(encoding="utf-8")
    assert "Les cinq barrières" in methode
    assert "<table>" in methode
    assert "GO" in (out / "exemples" / "temoin-sain.html").read_text(encoding="utf-8")


def test_offers_come_from_site_toml_and_unknown_entries_are_named(tmp_path: Path) -> None:
    build_site = _module()
    config = tmp_path / "site.toml"
    config.write_text(
        '[site]\nrepo_url = "https://example.org/qaudit"\n\n'
        '[[offres]]\ncode = "moteur"\nprix_eur = 0\naction = "depot"\n\n'
        '[[offres]]\ncode = "attestation_cessible"\nprix_eur = 450\n'
        'attestation = "cessible"\naction = "commande"\n',
        encoding="utf-8",
    )
    cfg = build_site.load_config(config)  # type: ignore[attr-defined]
    assert [o.code for o in cfg.offers] == ["moteur", "attestation_cessible"]
    html = build_site.page_index(cfg, "fr")  # type: ignore[attr-defined]
    assert "450 €" in html
    assert 'href="https://example.org/qaudit"' in html
    for bad in ('code = "inconnue"\naction = "devis"', 'code = "moteur"\naction = "vendre"',
                'code = "moteur"\naction = "devis"\nattestation = "toujours"'):
        config.write_text(f"[[offres]]\n{bad}\n", encoding="utf-8")
        with pytest.raises(ValueError, match=r"site\.toml"):
            build_site.load_config(config)  # type: ignore[attr-defined]


def test_default_offers_hide_the_repository_link_until_it_is_public() -> None:
    build_site = _module()
    cfg = build_site.SiteConfig()  # type: ignore[attr-defined]
    html = build_site.page_index(cfg, "en")  # type: ignore[attr-defined]
    assert "Open-source engine" in html
    assert "See the code" not in html
    assert "390 €" in html
