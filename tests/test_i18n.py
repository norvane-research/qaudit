# SPDX-License-Identifier: AGPL-3.0-or-later
"""Catalogues : mêmes clés en français et en anglais, et toute clé émise par le
noyau existe dans les deux."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from qaudit import i18n

PACKAGE = Path(__file__).resolve().parents[1] / "qaudit"
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
# préfixes réservés aux clés i18n dans le code du noyau
KEY_PREFIXES = ("validate.", "schema.", "internal.", "detector.", "metrics.", "stats.", "gui.",
                "resample.", "regimes.", "walkforward.", "propfirm.", "verdict.", "barrier.",
                "condition.", "audit.", "report.", "batch.", "profile.", "prices.", "period.",
                "method.", "reader.", "exit.", "location.")


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _keys_used_in(directory: Path) -> set[str]:
    used: set[str] = set()
    for path in sorted(directory.rglob("*.py")):
        for const in _string_constants(path):
            if KEY_PATTERN.match(const) and const.startswith(KEY_PREFIXES):
                used.add(const)
    return used


def test_both_catalogues_have_identical_key_sets() -> None:
    fr = i18n.load("fr")
    en = i18n.load("en")
    assert fr.keys == en.keys, sorted(fr.keys ^ en.keys)


@pytest.mark.parametrize("lang", i18n.LANGUAGES)
def test_every_key_used_in_core_and_cli_exists(lang: str) -> None:
    catalog = i18n.load(lang)
    used = (_keys_used_in(PACKAGE / "core") | _keys_used_in(PACKAGE / "cli")
            | _keys_used_in(PACKAGE / "io"))
    assert used, "aucune clé détectée : le motif de détection est cassé"
    missing = sorted(k for k in used if not catalog.has(k))
    assert not missing, missing


def test_unknown_language_is_refused() -> None:
    with pytest.raises(ValueError, match="xx"):
        i18n.load("xx")


def test_french_uses_decimal_comma_and_english_a_point() -> None:
    fr = i18n.load("fr")
    en = i18n.load("en")
    assert fr.text("validate.nonpositive", value=-1.5) == (
        "Valeur qui devrait être strictement positive : -1,5."
    )
    assert en.text("validate.nonpositive", value=-1.5) == (
        "Value that should be strictly positive: -1.5."
    )


def test_missing_key_falls_back_to_english_then_to_bracketed_key() -> None:
    fr = i18n.load("fr")
    assert fr.text("no.such.key") == "[no.such.key]"


def test_default_float_rendering_is_compact() -> None:
    en = i18n.load("en")
    assert en.text("validate.nonpositive", value=0.0) == (
        "Value that should be strictly positive: 0."
    )
    assert en.text("validate.nonpositive", value=12345.678912) == (
        "Value that should be strictly positive: 12345.6789."
    )
    assert en.text("validate.nonpositive", value=2.5e-7) == (
        "Value that should be strictly positive: 2.5e-07."
    )
