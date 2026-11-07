# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests de non-régression nommés par défaut (N-09) : D-01 … D-09.

Chaque test porte l'identifiant du défaut relevé sur la v0.1 et reproduit le
scénario qui l'avait révélé.
"""

from __future__ import annotations

import ast
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from qaudit import i18n
from qaudit.core.audit import AuditOptions, run_audit
from qaudit.core.detectors.registry import build_detectors
from qaudit.core.metrics import compute_metrics, quarter_labels
from qaudit.core.models import Cell, Severity
from qaudit.core.propfirm import CAUSE_TIMEOUT, simulate
from qaudit.core.regimes import quarterly_stats
from qaudit.core.resample import METHOD_IID, bootstrap, null_no_edge
from qaudit.core.stats import dsr, dsr_sensitivity
from qaudit.core.validate import ValidationResult, find_ruin, validate
from qaudit.io.method import load_method
from tests.helpers import MINIMAL_MAPPING, make_table, make_tradeset
from tests.test_detectors import _grid_set
from tests.test_propfirm import constant_days, phase, ruleset
from tests.test_resample import clustered_series


def test_D03_ruin_stops_return_computation_and_is_blocking() -> None:  # noqa: N802
    """D-03 : la v0.1 calculait des rendements sur une base négative (-4,80 observé).

    Solde initial 500 ; profits +100, -600, +200, +300 : l'equity vaut 600, 0,
    200, 500. La ruine survient au 2e trade (equity ≤ 0). Au-delà, aucun
    rendement ne doit être calculé, et aucune base ne doit être ≤ 0.
    """
    ts = make_tradeset([100.0, -600.0, 200.0, 300.0], initial_balance=500.0)
    finding, idx = find_ruin(ts)
    assert finding is not None
    assert finding.severity == Severity.BLOCKING
    assert finding.code == "ruin"
    assert idx == 1
    assert finding.param("trade_index") == 2
    assert finding.param("equity") == 0.0

    columns = ("open_time", "close_time", "profit")
    rows: list[list[Cell]] = [
        ["2021-01-04 09:00", "2021-01-04 10:00", 100.0],
        ["2021-01-05 09:00", "2021-01-05 10:00", -600.0],
        ["2021-01-06 09:00", "2021-01-06 10:00", 200.0],
        ["2021-01-07 09:00", "2021-01-07 10:00", 300.0],
    ]
    result = validate(make_table(columns, rows), MINIMAL_MAPPING, max_gap_days=30,
                      initial_balance=500.0)
    assert result.ruin_index == 1
    assert any(f.code == "ruin" and f.severity == Severity.BLOCKING for f in result.findings)

    usable = result.usable
    assert usable.n == 2  # le trade fautif est inclus, rien au-delà
    equity_before = 500.0 + np.concatenate(([0.0], usable.cum_profit[:-1]))
    assert np.all(equity_before > 0)
    returns = usable.profit / equity_before
    np.testing.assert_allclose(returns, [100 / 500, -600 / 600])
    # la v0.1 aurait produit, après ruine, 200 / 0 puis 300 / 200 : ici impossible
    assert result.tradeset.n == 4  # l'historique complet reste disponible pour le rapport


def test_D03_no_ruin_when_equity_stays_positive() -> None:  # noqa: N802
    ts = make_tradeset([100.0, -400.0, 200.0], initial_balance=500.0)
    finding, idx = find_ruin(ts)
    assert finding is None
    assert idx is None


def test_D03_ruin_not_evaluable_without_initial_balance() -> None:  # noqa: N802
    ts = make_tradeset([-1e9], initial_balance=None)
    assert find_ruin(ts) == (None, None)


def test_D02_sharpe_annualisation_uses_measured_frequency() -> None:  # noqa: N802
    """D-02 : la v0.1 annualisait à 250 trades/an ; un système à 131 trades/an
    affichait 1,99 au lieu de 1,44 (1,44 × √(250/131) = 1,99).

    On construit 131 trades couvrant exactement un an : la fréquence mesurée est
    131/an et le Sharpe annualisé vaut SR_trade × √131, pas SR_trade × √250.
    """
    n = 131
    rng_local = np.random.default_rng(2)
    profits = rng_local.normal(10.0, 100.0, n)
    # premier ouvert à t0, dernier clos à t0 + 365,25 j : pas = 365,25/130 j, tenue 0 h
    step_hours = 365.25 * 24 / (n - 1)
    ts = make_tradeset(profits, step_hours=step_hours, hold_hours=0.0)
    m = compute_metrics(ts)
    assert m.span_days == pytest.approx(365.25)
    assert m.trades_per_year == pytest.approx(131.0)
    assert m.sharpe_annual == pytest.approx(m.sharpe_trade * np.sqrt(131.0))
    wrong_v01 = m.sharpe_trade * np.sqrt(250.0)
    assert m.sharpe_annual != pytest.approx(wrong_v01)
    assert wrong_v01 / m.sharpe_annual == pytest.approx(np.sqrt(250 / 131))


def test_D06_number_of_trials_is_a_sensitivity_curve_not_a_point() -> None:  # noqa: N802
    """D-06 : la v0.1 traitait le nombre d'essais déclaré comme un point unique.

    Le DSR doit être publié sur la grille {1, 10, 50, 100, 300, 1000} avec le N
    de bascule, pour que le verdict ne repose pas sur une déclaration
    invérifiable.
    """
    curve = dsr_sensitivity(0.10, -0.5, 4.0, 500, threshold=0.5)
    assert [pt.n_trials for pt in curve.points] == [1, 10, 50, 100, 300, 1000]
    values = [pt.dsr for pt in curve.points]
    assert all(a > b for a, b in pairwise(values))
    tip = curve.tipping_n_trials
    assert tip is not None
    assert 10 < tip < 50  # DSR(10) = 0,7385 ≥ 0,5 et DSR(50) < 0,5 pour ce cas
    assert dsr(0.10, -0.5, 4.0, 500, tip).dsr >= 0.5
    assert dsr(0.10, -0.5, 4.0, 500, tip + 1).dsr < 0.5


def test_D04_block_bootstrap_keeps_serial_dependence_iid_destroys_it() -> None:  # noqa: N802
    """D-04 : la v0.1 n'avait qu'un bootstrap IID, qui détruit la dépendance
    sérielle et sous-estime le drawdown du 95ᵉ centile dès que les pertes se
    groupent.

    Sur une série volontairement autocorrélée (chaîne de Markov à deux régimes,
    ρ₁ ≈ 0,12), la longueur de bloc automatique est ≈ 7,9 et le DD95 par blocs
    dépasse le DD95 IID d'environ 14 % (mesuré : ≈ 12 000 contre ≈ 10 500).
    Sur une série IID, la longueur de bloc retombe à 1 et les deux méthodes
    coïncident.
    """
    y = clustered_series(1000, 7)
    iid = bootstrap(y, 10_000, np.random.default_rng(0), method=METHOD_IID)
    blocks = bootstrap(y, 10_000, np.random.default_rng(0))
    assert blocks.block_length > 3.0
    assert blocks.max_drawdown_p95 > iid.max_drawdown_p95 * 1.08
    assert blocks.profit_factor_p05 < iid.profit_factor_p05  # borne basse plus prudente

    x = np.random.default_rng(1).normal(5.0, 100.0, 1000)
    iid_x = bootstrap(x, 10_000, np.random.default_rng(0), method=METHOD_IID)
    blocks_x = bootstrap(x, 10_000, np.random.default_rng(0))
    assert blocks_x.block_length == 1.0
    assert blocks_x.max_drawdown_p95 == pytest.approx(iid_x.max_drawdown_p95, rel=0.05)


def test_D08_grid_detector_does_not_flag_concurrent_independent_positions() -> None:  # noqa: N802
    """D-08 : la v0.1 n'avait aucun test automatisé ; un faux positif du
    détecteur de grille (positions concurrentes prises pour une grille) est passé
    en production.

    Système sain à positions qui se chevauchent : ouvertures toutes les 6 h,
    tenue 30 h, prix aléatoires, volume constant, clôtures indépendantes. Le
    détecteur ne doit rien signaler ; la même configuration sur une vraie grille
    (ajouts à prix pire, volume ×1,5, clôture en panier) doit être bloquante.
    """
    config = load_method()
    grid_detector = next(d for d in build_detectors(config) if d.name == "grid")
    rng = np.random.default_rng(8)
    n = 300
    prices = 1.1 + np.cumsum(rng.normal(0, 0.0008, n))
    concurrent = make_tradeset(
        rng.normal(5, 50, n), step_hours=6.0, hold_hours=30.0, open_price=prices,
        direction=rng.choice(np.array([1, -1]), n),
    )
    assert grid_detector.detect(concurrent) is None
    finding = grid_detector.detect(_grid_set(30))
    assert finding is not None
    assert finding.severity == Severity.BLOCKING


def test_D05_unlimited_phase_uses_explicit_horizon_not_a_hidden_cap() -> None:  # noqa: N802
    """D-05 : la v0.1 plafonnait à 400 jours toute phase sans limite, et comptait
    les systèmes lents « délai dépassé » à tort.

    Système lent : +50 par jour sur 100 000 (0,05 %/jour) ; la cible de 10 %
    demande 200 journées. Sans limite dans le règlement, l'horizon est le
    paramètre explicite : 150 journées → dépassement, 250 → réussite. Il est
    imprimé dans le résultat et marqué « hors règlement ».
    """
    ts = constant_days([50.0], n_days=400)
    rs = ruleset(phase(profit_target=0.10, max_days=0))
    short = simulate(ts, rs, 20, np.random.default_rng(0), horizon_trading_days=150)
    assert short.horizon_trading_days == 150
    assert short.phases[0].horizon_trading_days == 150
    assert not short.phases[0].horizon_from_ruleset
    assert short.phases[0].pass_probability == 0.0
    assert dict(short.phases[0].fail_causes)[CAUSE_TIMEOUT] == 1.0
    long = simulate(ts, rs, 20, np.random.default_rng(0), horizon_trading_days=250)
    assert long.phases[0].pass_probability == 1.0
    assert long.phases[0].median_days_to_pass == 200.0
    # une limite calendaire du règlement est convertie en journées de trading
    limited = ruleset(phase(profit_target=0.10, max_days=30))
    res = simulate(ts, limited, 20, np.random.default_rng(0), horizon_trading_days=250)
    assert res.phases[0].horizon_from_ruleset
    assert res.phases[0].horizon_trading_days == 30  # 1 journée de trading par jour civil


def test_D07_balance_carry_between_phases_is_an_explicit_option() -> None:  # noqa: N802
    """D-07 : la remise à l'échelle du solde entre phases était codée en dur.

    +1 000 par journée. Phase 1 : cible 10 % → réussie au jour 10 à 110 000.
    Phase 2 : cible 5 %. « reset » : repart de 100 000, cible 105 000 → 5 jours.
    « carry » : repart de 110 000 qui devient la référence, cible 115 500 →
    6 jours (5,5 arrondi à la journée entière suivante).
    """
    ts = constant_days([1_000.0])
    phases = (phase(name="P1", profit_target=0.10), phase(name="P2", profit_target=0.05))
    reset = simulate(ts, ruleset(*phases, carry="reset"), 20, np.random.default_rng(0),
                     horizon_trading_days=50)
    carry = simulate(ts, ruleset(*phases, carry="carry"), 20, np.random.default_rng(0),
                     horizon_trading_days=50)
    assert reset.balance_carry == "reset"
    assert carry.balance_carry == "carry"
    assert reset.phases[1].median_days_to_pass == 5.0
    assert carry.phases[1].median_days_to_pass == 6.0
    assert reset.funded_probability == carry.funded_probability == 1.0


def test_D01_quarter_labels_never_go_through_strftime_q() -> None:  # noqa: N802
    """D-01 : la v0.1 formatait les trimestres avec ``strftime("%Y-T%q")`` ; ``%q``
    n'existe pas en Python et le libellé sortait littéralement « 2021-T%q ».

    Ici l'année et le trimestre sont des entiers (``quarter_labels``), et le
    libellé est rendu par une clé i18n : « 2021-T1 » en français, « 2021-Q1 » en
    anglais. Aucun ``strftime`` ni ``%q`` ne subsiste dans le noyau.
    """
    times = np.array(["2021-01-15", "2021-05-02", "2021-08-31", "2021-12-31T23:59:59"],
                     dtype="datetime64[ns]")
    years, quarters = quarter_labels(times)
    assert years.tolist() == [2021, 2021, 2021, 2021]
    assert quarters.tolist() == [1, 2, 3, 4]
    fr, en = i18n.load("fr"), i18n.load("en")
    pairs = list(zip(years.tolist(), quarters.tolist(), strict=True))
    labels_fr = [fr.text("period.quarter", year=y, quarter=q) for y, q in pairs]
    labels_en = [en.text("period.quarter", year=y, quarter=q) for y, q in pairs]
    assert labels_fr == ["2021-T1", "2021-T2", "2021-T3", "2021-T4"]
    assert labels_en == ["2021-Q1", "2021-Q2", "2021-Q3", "2021-Q4"]
    assert not any("%" in label for label in labels_fr + labels_en)

    ts = make_tradeset([10.0, -5.0, 20.0, 30.0], step_hours=24 * 45)
    rendered = [fr.text("period.quarter", year=s.year, quarter=s.quarter)
                for s in quarterly_stats(ts)]
    assert rendered == ["2021-T1", "2021-T2"]

    core = Path(__file__).resolve().parents[1] / "qaudit" / "core"
    for path in core.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "strftime", path
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "%q" not in node.value, path


def test_D09_null_without_edge_states_its_empirical_distribution_assumption() -> None:  # noqa: N802
    """D-09 : la nulle sans edge de la v0.1 conservait les distributions
    empiriques des gains et des pertes — correct, mais écrit nulle part.

    Ici l'hypothèse est (1) vraie par construction : chaque tirage nul est un
    gain ou une perte réellement observé, seul le taux de réussite est ramené à
    p₀ ; (2) écrite dans le rapport : un constat « info » à clé
    ``resample.null_empirical`` accompagne chaque audit où la nulle est
    calculable, et son texte dit que ce n'est pas une nulle de marché efficient.
    """
    # gains ∈ {10, 30}, pertes ∈ {−5} : tout profit net simulé est une somme de
    # ces valeurs ; p₀ = 5 / (20 + 5) = 0,2
    profits = np.array([10.0, 30.0, -5.0, -5.0, -5.0, -5.0, 10.0, 30.0])
    result = null_no_edge(profits, 500, np.random.default_rng(0))
    assert result.evaluable
    assert result.p0 == pytest.approx(0.2)
    assert result.note_key == "resample.null_empirical"
    # médiane et p95 sont des sommes de termes pris dans {10, 30, −5} : multiples de 5
    assert result.null_net_p50 % 5 == 0
    assert result.null_net_p95 % 5 == 0

    config = load_method()
    audit = run_audit(ValidationResult(make_tradeset(profits), (), None), config,
                      AuditOptions(seed=0, n_iter=200))
    note = next(f for f in audit.findings if f.code == "null_empirical")
    assert note.message_key == "resample.null_empirical"
    assert note.number("p0") == pytest.approx(0.2)
    for lang, needle, disclaimer in (
        ("fr", "distributions empiriques", "pas une nulle de marché efficient"),
        ("en", "empirical distributions", "not an efficient-market null"),
    ):
        text = i18n.load(lang).text(note.message_key, **dict(note.params))
        assert needle in text
        assert disclaimer in text
