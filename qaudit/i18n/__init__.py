# SPDX-License-Identifier: AGPL-3.0-or-later
"""Catalogues de messages (TOML) et rendu des clés i18n.

Le noyau n'importe jamais ce paquet : il émet des clés et des paramètres, la
coquille les rend ici. Une clé absente ne fait jamais échouer un rendu : on
retombe sur l'anglais, puis sur la clé elle-même entre crochets.
"""

from __future__ import annotations

import math
import string
import tomllib
from collections.abc import Mapping
from importlib import resources
from typing import Any

LANGUAGES: tuple[str, ...] = ("fr", "en")
DEFAULT_LANGUAGE = "fr"
FALLBACK_LANGUAGE = "en"


class _Formatter(string.Formatter):
    """``str.format`` avec séparateur décimal du catalogue pour les flottants."""

    def __init__(self, decimal: str) -> None:
        super().__init__()
        self._decimal = decimal

    def format_field(self, value: Any, format_spec: str) -> str:
        if isinstance(value, float) and not format_spec:
            rendered = _default_float(value)
        else:
            rendered = super().format_field(value, format_spec)
        if isinstance(value, float) and self._decimal != ".":
            rendered = rendered.replace(".", self._decimal)
        return rendered


def _default_float(value: float) -> str:
    """Rendu lisible sans spécification : 4 décimales au plus, sans zéros inutiles."""
    if math.isnan(value) or math.isinf(value):
        return str(value)
    if value == 0:
        return "0"
    if abs(value) >= 1e6 or abs(value) < 1e-3:
        return f"{value:.4g}"
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _flatten(table: Mapping[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in table.items():
        full = f"{prefix}{key}"
        if isinstance(value, Mapping):
            out.update(_flatten(value, f"{full}."))
        else:
            out[full] = str(value)
    return out


class Catalog:
    """Catalogue d'une langue, avec repli sur l'anglais."""

    def __init__(self, lang: str, entries: Mapping[str, str], fallback: Catalog | None) -> None:
        self.lang = lang
        self._entries = dict(entries)
        self._fallback = fallback
        self.decimal = self._entries.get("meta.decimal", ".")
        self._formatter = _Formatter(self.decimal)

    def has(self, key: str) -> bool:
        return key in self._entries

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(self._entries)

    def text(self, key: str, **params: object) -> str:
        template = self._entries.get(key)
        if template is None and self._fallback is not None:
            return self._fallback.text(key, **params)
        if template is None:
            return f"[{key}]"
        return self._formatter.vformat(template, (), dict(params))


EXTRA_CATALOGS: tuple[str, ...] = ("explain",)  # explain_<lang>.toml : textes client


def _load_entries(lang: str) -> dict[str, str]:
    """``<lang>.toml`` puis les catalogues complémentaires ``<nom>_<lang>.toml``
    (une clé dupliquée serait une erreur de rédaction : la dernière gagne)."""
    entries: dict[str, str] = {}
    for name in (lang, *(f"{extra}_{lang}" for extra in EXTRA_CATALOGS)):
        path = resources.files("qaudit.i18n").joinpath(f"{name}.toml")
        with path.open("rb") as handle:
            entries.update(_flatten(tomllib.load(handle)))
    return entries


def load(lang: str = DEFAULT_LANGUAGE) -> Catalog:
    """Charge le catalogue ``lang`` (``fr`` ou ``en``)."""
    if lang not in LANGUAGES:
        raise ValueError(lang)
    fallback = None
    if lang != FALLBACK_LANGUAGE:
        fallback = Catalog(FALLBACK_LANGUAGE, _load_entries(FALLBACK_LANGUAGE), None)
    return Catalog(lang, _load_entries(lang), fallback)
