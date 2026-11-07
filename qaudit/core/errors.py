# SPDX-License-Identifier: AGPL-3.0-or-later
"""Erreurs du noyau.

Aucune erreur ne porte de texte destiné à l'utilisateur : chacune transporte une
clé i18n et des paramètres, rendus par la coquille. Le noyau ne connaît pas les
codes de sortie ; ``qaudit.cli.exitcodes`` fait la correspondance.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

Param = float | int | str | bool | None


class QauditError(Exception):
    """Base de toutes les erreurs signalées au client par clé i18n."""

    def __init__(self, key: str, **params: Param) -> None:
        super().__init__(key)
        self.key = key
        self.params: Mapping[str, Param] = MappingProxyType(dict(params))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.key!r}, {dict(self.params)!r})"


class DataError(QauditError):
    """Donnée d'entrée invalide : nomme toujours la ligne et la colonne fautives.

    ``row`` est le numéro de ligne dans la source (1 = première ligne du
    fichier, en-tête comprise) ; ``column`` est le nom de colonne tel que vu
    dans la source. L'un ou l'autre peut manquer quand le défaut porte sur le
    fichier entier (ex. aucune ligne de données).
    """

    def __init__(
        self,
        key: str,
        *,
        row: int | None = None,
        column: str | None = None,
        **params: Param,
    ) -> None:
        super().__init__(key, row=row, column=column, **params)
        self.row = row
        self.column = column


class SchemaError(QauditError):
    """Champs obligatoires absents après application de la correspondance (porte E1)."""

    def __init__(self, seen_columns: tuple[str, ...], missing_fields: tuple[str, ...]) -> None:
        super().__init__(
            "schema.missing_fields",
            seen_columns=", ".join(seen_columns),
            missing_fields=", ".join(missing_fields),
        )
        self.seen_columns = seen_columns
        self.missing_fields = missing_fields


class RulesetError(QauditError):
    """Règlement propfirm absent, incomplet ou non structuré (porte E2)."""

    def __init__(self, key: str, missing_keys: tuple[str, ...] = (), **params: Param) -> None:
        super().__init__(key, missing_keys=", ".join(missing_keys), **params)
        self.missing_keys = missing_keys


class InternalError(QauditError):
    """Invariant interne violé : c'est un défaut du moteur, pas des données."""
