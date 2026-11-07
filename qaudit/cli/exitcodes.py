# SPDX-License-Identifier: AGPL-3.0-or-later
"""Codes de sortie du processus (N-11).

0 GO · 1 GO SOUS CONDITIONS · 2 NO-GO · 10 porte E1 (correspondance de colonnes)
· 11 porte E2 (règlement propfirm) · 20 données invalides · 30 erreur interne.
"""

from __future__ import annotations

from enum import IntEnum

from qaudit.core.errors import (
    DataError,
    InternalError,
    QauditError,
    RulesetError,
    SchemaError,
)
from qaudit.core.models import Decision


class ExitCode(IntEnum):
    GO = 0
    CONDITIONAL = 1
    NO_GO = 2
    NEEDS_MAPPING = 10
    NEEDS_RULESET = 11
    INVALID_DATA = 20
    INTERNAL_ERROR = 30

    @property
    def message_key(self) -> str:
        return f"exit.{self.name.lower()}"


DECISION_EXIT: dict[Decision, ExitCode] = {
    Decision.GO: ExitCode.GO,
    Decision.CONDITIONAL: ExitCode.CONDITIONAL,
    Decision.NO_GO: ExitCode.NO_GO,
}


def exit_code_for(error: QauditError) -> ExitCode:
    """Correspondance erreur du noyau → code de sortie."""
    if isinstance(error, SchemaError):
        return ExitCode.NEEDS_MAPPING
    if isinstance(error, RulesetError):
        return ExitCode.NEEDS_RULESET
    if isinstance(error, DataError):
        return ExitCode.INVALID_DATA
    if isinstance(error, InternalError):
        return ExitCode.INTERNAL_ERROR
    return ExitCode.INTERNAL_ERROR
