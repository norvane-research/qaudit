# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures dorées à verdict connu (N-10) : un témoin sain et cinq dossiers
truqués, générés par ``tests/fixtures/generate.py``.

Le témoin sain est le garde-fou principal : s'il ressort NO-GO, c'est le moteur
qui est cassé, pas la fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from qaudit.core.audit import AuditOptions, AuditResult, run_audit
from qaudit.core.config import MethodConfig
from qaudit.core.models import Decision, Severity
from qaudit.core.validate import ValidationResult, validate
from qaudit.core.walkforward import Candidate, WalkForwardInput
from qaudit.io.method import load_method
from qaudit.io.readers.common import infer_mapping
from qaudit.io.readers.csv_generic import read_csv_generic
from qaudit.io.readers.prices import read_prices

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FAST = AuditOptions(seed=1, n_iter=2000)


@dataclass(frozen=True)
class Expected:
    name: str
    initial_balance: float
    decision: Decision
    blocking_codes: frozenset[str]  # constats bloquants attendus (exactement)
    triggered_barriers: frozenset[str]  # barrières déclenchées attendues (exactement)
    prices: str | None = None  # série OHLC à joindre


EXPECTED: tuple[Expected, ...] = (
    # Système sain : edge modeste et réel, iid, stops, volume constant, un tiers
    # de positions concurrentes. Sans walk-forward fourni, le verdict est
    # « GO sous conditions » (barrière wf non évaluée) — jamais NO-GO.
    Expected("healthy_witness", 10_000.0, Decision.CONDITIONAL, frozenset(), frozenset()),
    # Volume doublé après chaque perte.
    Expected("martingale", 10_000.0, Decision.NO_GO, frozenset({"martingale"}), frozenset()),
    # Ajouts de même sens à prix pire, volume ×1,5, clôture en panier ; perdant.
    Expected("grid", 10_000.0, Decision.NO_GO, frozenset({"grid"}),
             frozenset({"dsr", "pf_p05", "null_pvalue"})),
    # 96 % de réussite, pertes 12× plus grosses, aucun stop.
    Expected("no_stop_asymmetry", 10_000.0, Decision.NO_GO, frozenset({"payoff_asymmetry"}),
             frozenset()),
    # Bruit pur N(0, 100) : aucun détecteur, les barrières statistiques tranchent.
    Expected("no_edge_noise", 10_000.0, Decision.NO_GO, frozenset(),
             frozenset({"dsr", "pf_p05", "null_pvalue"})),
    # Compte de 5 000 mis à zéro par une série de pertes (D-03).
    Expected("ruined", 5_000.0, Decision.NO_GO, frozenset({"ruin"}),
             frozenset({"dsr", "pf_p05", "null_pvalue"})),
    # Look-ahead : chaque entrée au plus bas / plus haut exact de sa barre horaire ;
    # rentable, aucune barrière déclenchée — seul le détecteur à prix le voit.
    Expected("lookahead", 10_000.0, Decision.NO_GO, frozenset({"lookahead"}), frozenset(),
             prices="lookahead_prices"),
)


@pytest.fixture(scope="module")
def config() -> MethodConfig:
    return load_method()


def load_fixture(name: str, initial_balance: float, config: MethodConfig) -> ValidationResult:
    table = read_csv_generic(FIXTURES / f"{name}.csv")
    mapping = infer_mapping(table.columns)
    return validate(table, mapping, max_gap_days=config.max_gap_days,
                    initial_balance=initial_balance)


def audit_fixture(
    name: str, initial_balance: float, config: MethodConfig, prices: str | None = None,
    walkforward: WalkForwardInput | None = None,
) -> AuditResult:
    series = read_prices(FIXTURES / f"{prices}.csv", "EURUSD") if prices else None
    return run_audit(load_fixture(name, initial_balance, config), config, FAST, prices=series,
                     walkforward=walkforward)


def witness_walkforward(config: MethodConfig) -> WalkForwardInput:
    folder = FIXTURES / "walkforward" / "healthy_witness"
    candidates = []
    for path in sorted(folder.glob("*.csv")):
        table = read_csv_generic(path)
        ts = validate(table, infer_mapping(table.columns), max_gap_days=config.max_gap_days,
                      initial_balance=10_000.0).tradeset
        candidates.append(Candidate(path.stem, ts))
    return WalkForwardInput(tuple(candidates))


@pytest.mark.parametrize("expected", EXPECTED, ids=lambda e: e.name)
def test_golden_verdicts(expected: Expected, config: MethodConfig) -> None:
    result = audit_fixture(expected.name, expected.initial_balance, config, expected.prices)
    verdict = result.verdict
    blocking = frozenset(f.code for f in verdict.findings if f.severity == Severity.BLOCKING)
    triggered = frozenset(b.name for b in verdict.barriers if b.triggered)
    assert verdict.decision == expected.decision, (blocking, triggered, verdict.conditions)
    assert blocking == expected.blocking_codes
    assert triggered == expected.triggered_barriers


def test_healthy_witness_is_never_no_go_and_has_no_major_finding(config: MethodConfig) -> None:
    result = audit_fixture("healthy_witness", 10_000.0, config)
    assert result.verdict.decision != Decision.NO_GO
    assert result.verdict.major_count == 0
    assert result.verdict.blocking_count == 0
    assert not result.verdict.human_review
    assert [c.code for c in result.verdict.conditions] == ["not_evaluated"]
    assert result.verdict.conditions[0].param("barrier") == "wf_efficiency"
    # chiffres mesurés lors de la construction (graine 1, 2 000 itérations)
    assert result.metrics.n == 600
    assert 0.10 < result.metrics.sharpe_trade < 0.20
    assert result.dsr_result.dsr > 0.9
    assert result.bootstrap.profit_factor_p05 > 1.1
    assert result.null.p_value < 0.01
    assert result.bootstrap.block_length == 1.0  # iid : le bloc retombe à 1


def test_healthy_witness_with_prices_and_walkforward_is_a_clean_go(config: MethodConfig) -> None:
    """Avec la série de prix et les trois jeux de paramètres, plus aucune barrière
    n'est non évaluée : le témoin sain sort GO, sans condition ni revue humaine."""
    result = audit_fixture("healthy_witness", 10_000.0, config, "healthy_witness_prices",
                           witness_walkforward(config))
    assert result.verdict.decision == Decision.GO
    assert result.verdict.conditions == ()
    assert not result.verdict.human_review
    assert result.prices_provided
    assert result.regimes.method == "atr_terciles"
    assert result.walkforward is not None
    assert result.walkforward.n_candidates == 3
    assert result.wf_efficiency is not None
    assert result.wf_efficiency > 0.5  # mesuré : 0,654 (ancré, sélection au profit net)
    assert all(b.evaluated for b in result.verdict.barriers)
    # les détecteurs à prix ont tourné : géométrie du stop publiée, look-ahead absent
    codes = {f.code for f in result.findings}
    assert "stop_geometry" in codes
    assert "lookahead" not in codes
    assert "execution_realism" not in codes
    assert result.verdict.major_count == 0


def test_healthy_witness_has_concurrent_positions_but_no_grid(config: MethodConfig) -> None:
    """Le témoin tient des positions concurrentes (un tiers des ouvertures) : la
    v0.1 y voyait une grille."""
    ts = load_fixture("healthy_witness", 10_000.0, config).tradeset
    open_ns = ts.open_time.astype(np.int64)
    close_ns = ts.close_time.astype(np.int64)
    order = np.argsort(open_ns)
    open_ns, close_ns = open_ns[order], close_ns[order]
    running_max_close = np.maximum.accumulate(close_ns)
    concurrent = int(np.sum(running_max_close[:-1] > open_ns[1:]))
    assert concurrent / ts.n > 0.25
    result = audit_fixture("healthy_witness", 10_000.0, config)
    assert all(f.code != "grid" for f in result.findings)


def test_martingale_fixture_details(config: MethodConfig) -> None:
    result = audit_fixture("martingale", 10_000.0, config)
    finding = next(f for f in result.findings if f.code == "martingale")
    assert finding.number("share_after_loss") > 0.9
    assert finding.number("share_after_win") < 0.05
    assert result.bootstrap.block_length > 5.0  # la martingale crée de la dépendance sérielle


def test_grid_fixture_details(config: MethodConfig) -> None:
    result = audit_fixture("grid", 10_000.0, config)
    finding = next(f for f in result.findings if f.code == "grid")
    assert finding.number("share") > 0.5
    assert finding.param("max_depth") == 4


def test_ruined_fixture_details(config: MethodConfig) -> None:
    validation = load_fixture("ruined", 5_000.0, config)
    assert validation.ruin_index is not None
    assert validation.tradeset.n == 200
    assert validation.usable.n == validation.ruin_index + 1 < 200
    result = audit_fixture("ruined", 5_000.0, config)
    assert result.full_n == 200
    assert result.metrics.n == validation.usable.n


def test_fixture_generator_is_deterministic(tmp_path: Path) -> None:
    """Les CSV versionnés sont exactement ceux que produit le générateur."""
    import tests.fixtures.generate as gen

    original = gen.HERE
    try:
        gen.HERE = tmp_path
        gen.main()
    finally:
        gen.HERE = original
    produced = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*.csv"))
    committed = sorted(p.relative_to(FIXTURES) for p in FIXTURES.rglob("*.csv"))
    assert produced == committed
    for rel in produced:
        assert (tmp_path / rel).read_bytes() == (FIXTURES / rel).read_bytes(), rel
