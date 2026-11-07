# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration pytest commune."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def rng() -> np.random.Generator:
    """Générateur à graine fixe : tout test aléatoire est reproductible."""
    return np.random.default_rng(20260913)


@pytest.fixture(autouse=True)
def _isolated_qaudit_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aucun test ne touche ``~/.qaudit`` (mémoire des correspondances, registre
    des attestations) : la racine est redirigée vers un dossier temporaire."""
    monkeypatch.setenv("QAUDIT_HOME", str(tmp_path / "qaudit-home"))
