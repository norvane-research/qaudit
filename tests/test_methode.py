# SPDX-License-Identifier: AGPL-3.0-or-later
"""Méthode publiée : générée depuis la configuration, jamais rédigée à la main.
Le document committé doit être identique à la génération courante."""

from __future__ import annotations

from pathlib import Path

import pytest

from qaudit import i18n
from qaudit.cli.main import main
from qaudit.io.method import load_method
from qaudit.io.writers.methode import BARRIERS, DETECTORS, render_methode

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(("lang", "name"), [("fr", "methode-1.0.md"), ("en", "method-1.0.en.md")])
def test_published_method_document_is_up_to_date(lang: str, name: str) -> None:
    generated = render_methode(load_method(None), i18n.load(lang))
    committed = (ROOT / "docs" / name).read_text(encoding="utf-8")
    assert committed == generated, f"docs/{name} : régénérer avec « qaudit methode --lang {lang} »"


def test_method_document_names_every_threshold_and_detector() -> None:
    config = load_method(None)
    text = render_methode(config, i18n.load("fr"))
    for barrier in config.barriers:
        assert i18n.load("fr").text(barrier.message_key) in text
    nnbsp = chr(0x202F)
    assert f"< 50,0{nnbsp}%" in text  # DSR
    assert f"≥ 5,0{nnbsp}%" in text  # p-value
    for name in DETECTORS:
        assert f"`{name}`" in text
    assert "ratio_min = 1,5" in text
    assert "min_events = 10" in text
    assert f"10{nnbsp}000 itérations" in text
    assert "[methode." not in text
    assert "[explain." not in text
    assert set(BARRIERS) == {b.name for b in config.barriers}


def test_methode_keys_exist_in_both_languages() -> None:
    fr, en = i18n.load("fr"), i18n.load("en")
    fr_keys = {k for k in fr.keys if k.startswith("methode.")}
    assert fr_keys == {k for k in en.keys if k.startswith("methode.")}
    assert len(fr_keys) > 40


def test_cli_methode_writes_the_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "m.md"
    assert main(["methode", "--lang", "en", "--write", str(target)]) == 0
    assert target.read_text(encoding="utf-8").startswith("# qaudit method — version 1.0")
    capsys.readouterr()
    assert main(["methode"]) == 0
    assert capsys.readouterr().out.startswith("# Méthode qaudit — version 1.0")
