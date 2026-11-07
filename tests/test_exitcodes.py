# SPDX-License-Identifier: AGPL-3.0-or-later
"""Codes de sortie (N-11) : valeurs documentées et correspondance des erreurs."""

from __future__ import annotations

import pytest

from qaudit import i18n
from qaudit.cli.exitcodes import DECISION_EXIT, ExitCode, exit_code_for
from qaudit.core.errors import (
    DataError,
    InternalError,
    QauditError,
    RulesetError,
    SchemaError,
)
from qaudit.core.models import Decision


def test_exit_code_values_are_the_documented_ones() -> None:
    assert int(ExitCode.GO) == 0
    assert int(ExitCode.CONDITIONAL) == 1
    assert int(ExitCode.NO_GO) == 2
    assert int(ExitCode.NEEDS_MAPPING) == 10
    assert int(ExitCode.NEEDS_RULESET) == 11
    assert int(ExitCode.INVALID_DATA) == 20
    assert int(ExitCode.INTERNAL_ERROR) == 30
    assert len(ExitCode) == 7


def test_decisions_map_to_exit_codes() -> None:
    assert DECISION_EXIT[Decision.GO] is ExitCode.GO
    assert DECISION_EXIT[Decision.CONDITIONAL] is ExitCode.CONDITIONAL
    assert DECISION_EXIT[Decision.NO_GO] is ExitCode.NO_GO
    assert set(DECISION_EXIT) == set(Decision)


def test_errors_map_to_exit_codes() -> None:
    assert exit_code_for(SchemaError(("a",), ("profit",))) == ExitCode.NEEDS_MAPPING
    assert exit_code_for(RulesetError("propfirm.no_ruleset")) == ExitCode.NEEDS_RULESET
    assert exit_code_for(DataError("validate.no_rows")) == ExitCode.INVALID_DATA
    assert exit_code_for(InternalError("internal.prices_unsorted")) == ExitCode.INTERNAL_ERROR
    assert exit_code_for(QauditError("x.y")) == ExitCode.INTERNAL_ERROR


@pytest.mark.parametrize("lang", i18n.LANGUAGES)
def test_every_exit_code_is_documented_in_both_languages(lang: str) -> None:
    catalog = i18n.load(lang)
    for code in ExitCode:
        assert catalog.has(code.message_key), code
        assert catalog.text(code.message_key).startswith(f"{int(code)} ")
