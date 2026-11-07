# SPDX-License-Identifier: AGPL-3.0-or-later
"""Règles de dépendance et d'hygiène du noyau (analyse statique par AST).

Toute violation est un échec de revue : ``core/`` n'importe ni ``io``, ni
``cli``, ni ``i18n`` ; n'accède ni au réseau ni au disque ; n'utilise jamais
l'aléatoire global de numpy.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

import numpy as np
import pytest

from qaudit.core.models import Finding, PriceSeries, Severity
from tests.helpers import make_tradeset

PACKAGE = Path(__file__).resolve().parents[1] / "qaudit"
CORE = PACKAGE / "core"

FORBIDDEN_IN_CORE = ("qaudit.io", "qaudit.cli", "qaudit.i18n")
FORBIDDEN_MODULES = {
    "socket", "urllib", "http", "requests", "ssl", "ftplib", "smtplib", "asyncio",
    "pathlib", "os", "shutil", "subprocess", "tempfile", "glob", "fileinput",
    "importlib.resources",
}
FORBIDDEN_CALLS = {"open", "exec", "eval"}


def _core_files() -> list[Path]:
    files = sorted(CORE.rglob("*.py"))
    assert files, "aucun module dans core/"
    return files


def _package_files() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def _imports(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


@pytest.mark.parametrize("path", _core_files(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_core_never_imports_shell_layers(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for name in _imports(tree):
        for forbidden in FORBIDDEN_IN_CORE:
            assert not name.startswith(forbidden), f"{path.name} importe {name}"


@pytest.mark.parametrize("path", _core_files(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_core_has_no_network_or_disk_access(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for name in _imports(tree):
        root = name.split(".")[0]
        assert root not in FORBIDDEN_MODULES, f"{path.name} importe {name}"
        assert name not in FORBIDDEN_MODULES, f"{path.name} importe {name}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in FORBIDDEN_CALLS, f"{path.name} appelle {node.func.id}()"


@pytest.mark.parametrize("path", _core_files(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_core_third_party_imports_are_numpy_scipy_pandas_only(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed_third_party = {"numpy", "scipy", "pandas"}
    stdlib_allowed = {
        "__future__", "collections", "dataclasses", "datetime", "enum", "functools",
        "itertools", "math", "typing", "types", "hashlib", "heapq", "bisect", "operator",
        "statistics", "string", "json",
    }
    for name in _imports(tree):
        root = name.split(".")[0]
        assert root in allowed_third_party | stdlib_allowed | {"qaudit"}, (
            f"{path.name} importe {name}"
        )


_LEGACY_RANDOM = re.compile(
    r"np\.random\.(?!Generator|default_rng|SeedSequence|BitGenerator|PCG64)"
)


@pytest.mark.parametrize("path", _package_files(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_no_global_numpy_random_state(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert not _LEGACY_RANDOM.search(text), f"{path.name} utilise l'aléatoire global numpy"
    assert "random.seed(" not in text


def test_core_has_no_llm_or_http_client_reference() -> None:
    pattern = re.compile(r"(anthropic|openai|llm|chatgpt|requests\.|httpx|urlopen)", re.IGNORECASE)
    for path in _core_files():
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), f"{path.name} mentionne un client HTTP/LLM"


# --- immuabilité -------------------------------------------------------------


def _assign(obj: object, name: str, value: object) -> None:
    """Affectation dynamique : contourne le typage statique, pas le gel."""
    setattr(obj, name, value)


def test_tradeset_is_frozen_and_arrays_are_read_only() -> None:
    ts = make_tradeset([1.0, -2.0, 3.0])
    with pytest.raises(dataclasses.FrozenInstanceError):
        _assign(ts, "currency", "EUR")
    with pytest.raises(ValueError, match="read-only"):
        ts.profit[0] = 99.0


def test_tradeset_copies_its_input() -> None:
    source = np.array([1.0, -2.0, 3.0])
    ts = make_tradeset(source)
    source[0] = 42.0
    assert ts.profit[0] == 1.0
    assert source.flags.writeable  # l'entrée n'a pas été gelée


def test_priceseries_is_frozen() -> None:
    ps = PriceSeries(
        time=np.array(["2021-01-01T00:00", "2021-01-01T01:00"], dtype="datetime64[ns]"),
        open=np.array([1.0, 1.1]),
        high=np.array([1.2, 1.3]),
        low=np.array([0.9, 1.0]),
        close=np.array([1.1, 1.2]),
        symbol="X",
        fingerprint="0" * 64,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        _assign(ps, "symbol", "Y")
    with pytest.raises(ValueError, match="read-only"):
        ps.high[0] = 5.0


def test_finding_is_frozen() -> None:
    f = Finding.make("x", Severity.INFO, "k", "src", b=1, a=2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        _assign(f, "code", "y")
