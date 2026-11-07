# SPDX-License-Identifier: AGPL-3.0-or-later
"""Site statique de l'offre : conversion Markdown minimale et assemblage complet
(pages, exemples rendus par le moteur, registre vide → page de vérification)."""

from __future__ import annotations

import importlib.util
import re
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
    _assert_links_stay_in_their_language(out)
    _assert_search_engines_get_one_address_per_page(out)


def _assert_search_engines_get_one_address_per_page(out: Path) -> None:
    """site.toml donne l'adresse publique : chaque page annonce son adresse canonique
    (celle que sert l'hébergeur, sans .html) et sa version dans l'autre langue ;
    sitemap.xml et robots.txt les reprennent."""
    base = "https://norvane-research.pages.dev"
    prep_en = (out / "en" / "preparer.html").read_text(encoding="utf-8")
    assert f'<link rel="canonical" href="{base}/en/preparer">' in prep_en
    assert f'hreflang="fr" href="{base}/preparer"' in prep_en
    assert '<meta name="description" content="What to send' in prep_en
    index_fr = (out / "index.html").read_text(encoding="utf-8")
    assert f'<link rel="canonical" href="{base}/">' in index_fr
    assert "Sharpe déflaté" in index_fr
    examples_fr = (out / "exemples" / "index.html").read_text(encoding="utf-8")
    assert f'hreflang="en" href="{base}/en/exemples/"' in examples_fr
    sitemap = (out / "sitemap.xml").read_text(encoding="utf-8")
    assert sitemap.count("<loc>") == 14
    assert f"<loc>{base}/en/methode</loc>" in sitemap
    assert f"Sitemap: {base}/sitemap.xml" in (out / "robots.txt").read_text(encoding="utf-8")


def test_no_public_address_means_no_canonical_and_no_sitemap(tmp_path: Path) -> None:
    build_site = _module()
    cfg = build_site.SiteConfig()  # type: ignore[attr-defined]
    html = build_site.shell(cfg, "en", "T", "<p>x</p>", path="index.html")  # type: ignore[attr-defined]
    assert '<meta name="description"' in html
    assert "canonical" not in html
    assert "og:url" not in html
    build_site.write_crawler_files(cfg, tmp_path)  # type: ignore[attr-defined]
    assert list(tmp_path.iterdir()) == []


def _assert_links_stay_in_their_language(out: Path) -> None:
    """Chaque lien interne mène à un fichier existant de la même langue ; seul le
    sélecteur de langue (class="lang") change de langue. Régression : les pages
    anglaises renvoyaient vers les pages françaises (liens comptés depuis la
    racine du site au lieu de la racine de la langue)."""
    english = (out / "en").resolve()
    for page in out.rglob("*.html"):
        if page.name.startswith(("temoin-sain", "martingale")):
            continue  # rapports rendus par le moteur, sans navigation du site
        html = page.read_text("utf-8")
        for klass, href in re.findall(r'<a(?: class="([^"]*)")? href="([^"#]+)"', html):
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            target = (page.parent / href).resolve()
            assert target.exists(), f"{page.relative_to(out)} → {href}"
            if klass != "lang":
                same = target.is_relative_to(english) == page.resolve().is_relative_to(english)
                assert same, f"{page.relative_to(out)} → {href} change de langue"


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
