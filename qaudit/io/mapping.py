# SPDX-License-Identifier: AGPL-3.0-or-later
"""Correspondance champ canonique → colonne (porte E1) et sa mémorisation.

Résolution, dans l'ordre : fichier ``--mapping`` explicite (TOML, table
``[fields]``), correspondance mémorisée pour l'empreinte de l'en-tête, déduction
par synonymes puis par le contenu (colonnes d'horodatage). Si un champ
obligatoire manque toujours, ``SchemaError`` remonte : la coquille sort en
code 10 avec les colonnes vues et les champs manquants.

Une correspondance explicite qui a permis de construire un ``TradeSet`` est
mémorisée sous l'empreinte SHA-256 de l'en-tête (``QAUDIT_HOME/mappings/``),
pour que le dossier suivant au même format passe sans intervention.
"""

from __future__ import annotations

import hashlib
import os
import tomllib
from collections.abc import Mapping
from pathlib import Path

from qaudit.core.errors import DataError
from qaudit.core.models import ALL_FIELDS, RawTable
from qaudit.io.readers.common import deduce_time_columns, infer_mapping

ENV_HOME = "QAUDIT_HOME"


def header_fingerprint(columns: tuple[str, ...]) -> str:
    return hashlib.sha256("\x1f".join(columns).encode("utf-8")).hexdigest()


def default_home() -> Path:
    override = os.environ.get(ENV_HOME)
    return Path(override) if override else Path.home() / ".qaudit"


class MappingStore:
    """Mémoire des correspondances validées, un fichier TOML par empreinte."""

    def __init__(self, home: Path | None = None) -> None:
        self.directory = (home or default_home()) / "mappings"

    def path_for(self, fingerprint: str) -> Path:
        return self.directory / f"{fingerprint}.toml"

    def load(self, columns: tuple[str, ...]) -> dict[str, str] | None:
        path = self.path_for(header_fingerprint(columns))
        if not path.exists():
            return None
        mapping = parse_mapping_text(path.read_text(encoding="utf-8"))
        if any(column not in columns for column in mapping.values()):
            return None
        return mapping

    def save(self, columns: tuple[str, ...], mapping: Mapping[str, str]) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(header_fingerprint(columns))
        path.write_text(mapping_toml(mapping, columns), encoding="utf-8")
        return path


def mapping_toml(mapping: Mapping[str, str], columns: tuple[str, ...] = ()) -> str:
    lines = ["# qaudit — correspondance champ canonique → colonne source"]
    if columns:
        lines.append("# colonnes vues : " + ", ".join(columns))
    lines.append("[fields]")
    lines.extend(f'{field} = "{column}"' for field, column in mapping.items())
    return "\n".join(lines) + "\n"


def skeleton(columns: tuple[str, ...]) -> str:
    """Squelette à compléter : tous les champs canoniques, déduits quand c'est possible."""
    guessed = infer_mapping(columns)
    lines = [
        "# qaudit — correspondance à compléter (porte E1)",
        "# colonnes vues : " + ", ".join(columns),
        "# champs obligatoires : open_time, close_time, profit ; les autres sont optionnels",
        "[fields]",
    ]
    for field in ALL_FIELDS:
        value = guessed.get(field, "")
        prefix = "" if value else "# "
        lines.append(f'{prefix}{field} = "{value}"')
    return "\n".join(lines) + "\n"


def parse_mapping_text(text: str) -> dict[str, str]:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DataError("mapping.not_toml", value=str(exc)) from exc
    fields = raw.get("fields", raw)
    mapping = {str(k): str(v) for k, v in fields.items() if str(v).strip()}
    unknown = tuple(k for k in mapping if k not in ALL_FIELDS)
    if unknown:
        raise DataError("mapping.unknown_field", column=", ".join(unknown))
    return mapping


def resolve_mapping(
    table: RawTable, explicit: Path | None, store: MappingStore | None
) -> tuple[dict[str, str], str]:
    """Correspondance retenue et son origine : ``explicit`` / ``memorized`` / ``inferred``."""
    if explicit is not None:
        return parse_mapping_text(explicit.read_text(encoding="utf-8")), "explicit"
    if store is not None:
        memorized = store.load(table.columns)
        if memorized is not None:
            return memorized, "memorized"
    inferred = deduce_time_columns(table.columns, table.rows, infer_mapping(table.columns))
    return inferred, "inferred"
