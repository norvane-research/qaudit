# SPDX-License-Identifier: AGPL-3.0-or-later
"""Simulateur propfirm : règlement TOML, profil journalier, moteur de rejeu."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from qaudit.core.errors import InternalError, RulesetError
from qaudit.core.models import TradeSet
from qaudit.core.propfirm import (
    CAUSE_CONSISTENCY,
    CAUSE_DAILY_LOSS,
    CAUSE_MAX_LOSS,
    PhaseRule,
    Ruleset,
    _breaches,
    _success,
    daily_profile,
    simulate,
)
from qaudit.core.validate import validate
from qaudit.io.readers.common import infer_mapping
from qaudit.io.readers.csv_generic import read_csv_generic
from qaudit.io.ruleset import (
    REQUIRED_PHASE,
    REQUIRED_TOP,
    builtin_names,
    load_ruleset,
    parse_ruleset,
    parse_ruleset_text,
    skeleton,
)
from tests.helpers import make_tradeset

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def phase(
    *,
    name: str = "P",
    funded: bool = False,
    profit_target: float = 0.10,
    max_daily_loss: float = 0.0,
    daily_loss_base: str = "initial",
    max_total_loss: float = 0.10,
    drawdown_type: str = "static",
    trailing_lock_at_initial: bool = False,
    min_trading_days: int = 0,
    max_days: int = 0,
    consistency_max_day_share: float = 0.0,
) -> PhaseRule:
    return PhaseRule(
        name, funded, profit_target, max_daily_loss, daily_loss_base, max_total_loss,
        drawdown_type, trailing_lock_at_initial, min_trading_days, max_days,
        consistency_max_day_share,
    )


def ruleset(*phases: PhaseRule, carry: str = "reset", fee: float = 500.0,
            refund: bool = True, split: float = 0.8, cycle: int = 10) -> Ruleset:
    return Ruleset("test", "2026-09-13", 100_000.0, "USD", fee, refund, split, cycle, carry, phases)


def daily_trades(day_profits: list[list[float]], initial_balance: float = 100_000.0) -> TradeSet:
    """Un historique dont chaque journée contient exactement les trades donnés,
    dans cet ordre (une journée par entrée, jours consécutifs)."""
    opens, closes, profits = [], [], []
    day0 = np.datetime64("2021-01-04T00:00:00", "ns")
    hour = np.timedelta64(3_600_000_000_000, "ns")
    for d, trades in enumerate(day_profits):
        for k, p in enumerate(trades):
            opens.append(day0 + np.timedelta64(d, "D") + (8 + k) * hour)
            closes.append(day0 + np.timedelta64(d, "D") + (9 + k) * hour)
            profits.append(p)
    n = len(profits)
    return TradeSet(
        open_time=np.array(opens, dtype="datetime64[ns]"),
        close_time=np.array(closes, dtype="datetime64[ns]"),
        profit=np.array(profits),
        direction=np.ones(n, dtype=np.int8),
        volume=np.full(n, 1.0),
        symbol=np.full(n, "X"),
        open_price=np.full(n, 1.0),
        close_price=np.full(n, 1.0),
        stop_loss=np.full(n, np.nan),
        take_profit=np.full(n, np.nan),
        ticket=np.arange(1, n + 1),
        currency="USD",
        initial_balance=initial_balance,
        fingerprint="0" * 64,
        known_fields=frozenset({"open_time", "close_time", "profit"}),
    )


def constant_days(day: list[float], n_days: int = 300) -> TradeSet:
    return daily_trades([list(day) for _ in range(n_days)])


# ---------------------------------------------------------------------------
# profil journalier
# ---------------------------------------------------------------------------


def test_daily_profile_keeps_intraday_order() -> None:
    ts = daily_trades([[200.0, -900.0, 400.0], [100.0], [-50.0, -50.0]])
    prof = daily_profile(ts)
    assert prof.n_days == 3
    np.testing.assert_allclose(prof.pnl, [-300.0, 100.0, -100.0])
    np.testing.assert_allclose(prof.min_run, [-700.0, 0.0, -100.0])
    np.testing.assert_allclose(prof.max_run, [200.0, 100.0, 0.0])
    assert prof.n_trades.tolist() == [3, 1, 2]
    assert prof.calendar_days_per_trading_day == pytest.approx(1.0, abs=0.05)


def test_daily_profile_scales_pnl_and_handles_empty() -> None:
    ts = daily_trades([[100.0], [-50.0]])
    assert daily_profile(ts, 10.0).pnl.tolist() == [1000.0, -500.0]
    assert daily_profile(make_tradeset([])).n_days == 0


# ---------------------------------------------------------------------------
# règles de violation (matrices construites à la main)
# ---------------------------------------------------------------------------


def test_static_and_trailing_floors() -> None:
    start = np.array([100_000.0])
    eod = np.array([[102_000.0, 104_000.0, 102_500.0, 101_000.0]])
    sod = np.array([[100_000.0, 102_000.0, 104_000.0, 102_500.0]])
    min_run = np.array([[0.0, 0.0, -1_500.0, -1_500.0]])
    ref = np.array([100_000.0])
    static = phase(max_total_loss=0.05)
    breach, _ = _breaches(static, ref, start, sod, eod, min_run)
    assert not breach.any()  # plancher 95 000 jamais touché
    trailing = phase(max_total_loss=0.03, drawdown_type="trailing")
    breach, _ = _breaches(trailing, ref, start, sod, eod, min_run)
    # jour 4 : plus haut des fins de journée précédentes 104 000 → plancher 101 000 ;
    # pire equity du jour 102 500 − 1 500 = 101 000 ≤ plancher → violation
    assert breach.tolist() == [[False, False, False, True]]
    locked = phase(max_total_loss=0.03, drawdown_type="trailing", trailing_lock_at_initial=True)
    breach, _ = _breaches(locked, ref, start, sod, eod, min_run)
    assert not breach.any()  # plancher figé à 100 000 : 101 000 reste au-dessus


def test_daily_loss_base_initial_versus_balance() -> None:
    start = np.array([100_000.0])
    eod = np.array([[90_000.0, 89_000.0]])
    sod = np.array([[100_000.0, 90_000.0]])
    min_run = np.array([[-4_800.0, -4_800.0]])
    ref = np.array([100_000.0])
    on_initial = phase(max_daily_loss=0.05, daily_loss_base="initial", max_total_loss=0.5)
    _, daily = _breaches(on_initial, ref, start, sod, eod, min_run)
    assert daily.tolist() == [[False, False]]  # 4 800 < 5 000 sur solde initial
    on_balance = phase(max_daily_loss=0.05, daily_loss_base="balance", max_total_loss=0.5)
    _, daily = _breaches(on_balance, ref, start, sod, eod, min_run)
    assert daily.tolist() == [[False, True]]  # jour 2 : 5 % de 90 000 = 4 500 < 4 800


# ---------------------------------------------------------------------------
# moteur sur profils déterministes (journées identiques → rejeu exact)
# ---------------------------------------------------------------------------


def test_deterministic_two_step_passes_at_expected_days() -> None:
    ts = constant_days([1_000.0])  # +1 % par journée
    rs = ruleset(phase(name="P1", profit_target=0.10, min_trading_days=4),
                 phase(name="P2", profit_target=0.05, min_trading_days=4))
    res = simulate(ts, rs, 200, np.random.default_rng(0), horizon_trading_days=100)
    assert res.evaluable
    p1, p2 = res.phases
    assert p1.pass_probability == 1.0
    assert p1.median_days_to_pass == 10.0
    assert p2.pass_probability == 1.0
    assert p2.median_days_to_pass == 5.0
    assert res.funded_probability == 1.0
    assert res.expected_payouts == 0.0  # aucune phase financée


def test_min_trading_days_delays_success() -> None:
    ts = constant_days([5_000.0])
    rs = ruleset(phase(profit_target=0.10, min_trading_days=4))
    res = simulate(ts, rs, 50, np.random.default_rng(0), horizon_trading_days=50)
    assert res.phases[0].median_days_to_pass == 4.0


def test_intraday_order_matters_for_daily_loss() -> None:
    # journée : +200, −900, +400 → P&L −300 mais pire cumul −700
    ts = constant_days([200.0, -900.0, 400.0])
    rs = ruleset(phase(max_daily_loss=0.005, max_total_loss=0.50, profit_target=0.01))
    res = simulate(ts, rs, 50, np.random.default_rng(0), horizon_trading_days=20)
    causes = dict(res.phases[0].fail_causes)
    assert res.phases[0].pass_probability == 0.0
    assert causes[CAUSE_DAILY_LOSS] == 1.0
    # même P&L journalier, ordre favorable : le pire cumul n'atteint jamais −500
    ts2 = constant_days([400.0, 200.0, -900.0])
    res2 = simulate(ts2, rs, 50, np.random.default_rng(0), horizon_trading_days=20)
    assert dict(res2.phases[0].fail_causes)[CAUSE_DAILY_LOSS] == 0.0


def test_consistency_rule_on_hand_built_path() -> None:
    # +6 000 le premier jour puis +2 000/jour : cible 10 000 atteinte au jour 3
    # (6 000 + 2×2 000) ; 6 000/10 000 = 60 % > 40 % → pas encore ; au jour 5 le
    # cumul vaut 14 000 (43 %) ; au jour 6, 16 000 (37,5 %) → succès
    pnl = np.array([[6_000.0, 2_000.0, 2_000.0, 2_000.0, 2_000.0, 2_000.0]])
    eod = 100_000.0 + np.cumsum(pnl, axis=1)
    ref = np.array([100_000.0])
    loose = phase(profit_target=0.10)
    success, target, consistent = _success(loose, ref, pnl, eod)
    assert target.tolist() == [[False, False, True, True, True, True]]
    assert consistent.all()
    assert success.tolist() == [[False, False, True, True, True, True]]
    strict = phase(profit_target=0.10, consistency_max_day_share=0.40)
    success, _, consistent = _success(strict, ref, pnl, eod)
    assert consistent.tolist() == [[False, False, False, False, False, True]]
    assert success.tolist() == [[False, False, False, False, False, True]]


def test_consistency_failures_are_reported_as_such() -> None:
    # journées identiques +6 000 : cible 10 % au jour 2 ; la meilleure journée pèse
    # 1/n du profit → 50 %, 33 %, 25 % : consistante à 30 % seulement au jour 4
    ts = constant_days([6_000.0])
    rs = ruleset(phase(profit_target=0.10, consistency_max_day_share=0.30))
    short = simulate(ts, rs, 20, np.random.default_rng(0), horizon_trading_days=3)
    assert short.phases[0].pass_probability == 0.0
    assert dict(short.phases[0].fail_causes)[CAUSE_CONSISTENCY] == 1.0
    longer = simulate(ts, rs, 20, np.random.default_rng(0), horizon_trading_days=5)
    assert longer.phases[0].pass_probability == 1.0
    assert longer.phases[0].median_days_to_pass == 4.0


def test_static_drawdown_breach_is_reported_as_max_loss() -> None:
    ts = constant_days([-3_000.0])  # −3 % par jour : plancher 90 000 touché le 4e jour
    rs = ruleset(phase(max_total_loss=0.10))
    res = simulate(ts, rs, 50, np.random.default_rng(0), horizon_trading_days=30)
    out = res.phases[0]
    assert out.pass_probability == 0.0
    assert dict(out.fail_causes)[CAUSE_MAX_LOSS] == 1.0


def test_funded_phase_payouts_and_economics() -> None:
    ts = constant_days([1_000.0])
    rs = ruleset(phase(name="F", funded=True, profit_target=0.0), fee=500.0, refund=True,
                 split=0.8, cycle=10)
    res = simulate(ts, rs, 100, np.random.default_rng(0), horizon_trading_days=50)
    out = res.phases[0]
    assert out.funded
    assert out.ruin_probability == 0.0
    assert res.funded_probability == 1.0
    # 5 cycles de 10 jours : 0,8 × 10 000 par cycle → 40 000 ; frais remboursés
    assert res.expected_payouts == pytest.approx(40_000.0)
    assert res.median_trader_gain == pytest.approx(40_000.0)
    assert res.expected_net_value == pytest.approx(40_000.0)


def test_pnl_scale_defaults_to_account_ratio_and_can_be_forced() -> None:
    ts = daily_trades([[10.0], [-5.0], [10.0]], initial_balance=1_000.0)
    rs = ruleset(phase())
    auto = simulate(ts, rs, 10, np.random.default_rng(0), horizon_trading_days=5)
    assert auto.pnl_scale == 100.0
    forced = simulate(ts, rs, 10, np.random.default_rng(0), horizon_trading_days=5, pnl_scale=1.0)
    assert forced.pnl_scale == 1.0


def test_degenerate_history_is_not_evaluable() -> None:
    rs = ruleset(phase())
    single = simulate(daily_trades([[100.0]]), rs, 10, np.random.default_rng(0),
                      horizon_trading_days=5)
    assert not single.evaluable
    assert math.isnan(single.funded_probability)
    empty = simulate(make_tradeset([]), rs, 10, np.random.default_rng(0), horizon_trading_days=5)
    assert not empty.evaluable


def test_simulation_is_deterministic_for_a_seed() -> None:
    table = read_csv_generic(FIXTURES / "healthy_witness.csv")
    ts = validate(table, infer_mapping(table.columns), max_gap_days=30,
                  initial_balance=10_000.0).usable
    rs = load_ruleset("two_step_static")
    a = simulate(ts, rs, 3000, np.random.default_rng(4), horizon_trading_days=250)
    b = simulate(ts, rs, 3000, np.random.default_rng(4), horizon_trading_days=250)
    assert a == b
    c = simulate(ts, rs, 3000, np.random.default_rng(5), horizon_trading_days=250)
    assert c != a


def test_causes_and_pass_probability_sum_to_one() -> None:
    table = read_csv_generic(FIXTURES / "healthy_witness.csv")
    ts = validate(table, infer_mapping(table.columns), max_gap_days=30,
                  initial_balance=10_000.0).usable
    for name in builtin_names():
        res = simulate(ts, load_ruleset(name), 2000, np.random.default_rng(0),
                       horizon_trading_days=120)
        assert res.evaluable
        for out in res.phases:
            total = out.pass_probability + sum(p for _, p in out.fail_causes)
            assert total == pytest.approx(1.0)


def test_ruleset_validation_rejects_unknown_tokens() -> None:
    with pytest.raises(InternalError):
        ruleset(phase(), carry="keep")
    with pytest.raises(InternalError):
        ruleset(phase(drawdown_type="hybrid"))
    with pytest.raises(InternalError):
        ruleset(phase(daily_loss_base="equity"))
    with pytest.raises(InternalError):
        Ruleset("x", "2026-01-01", 1.0, "USD", 0.0, False, 0.8, 10, "reset", ())


# ---------------------------------------------------------------------------
# chargeur TOML (porte E2)
# ---------------------------------------------------------------------------


def test_four_builtin_models_load_and_carry_a_date() -> None:
    names = builtin_names()
    assert len(names) == 4
    for name in names:
        rs = load_ruleset(name)
        assert rs.as_of == "2026-09-13"
        assert rs.phases
    kinds = {(rs.balance_carry, rs.phases[0].drawdown_type) for rs in map(load_ruleset, names)}
    assert ("carry", "trailing") in kinds
    assert ("reset", "static") in kinds


def test_skeleton_is_valid_toml_with_every_required_key() -> None:
    rs = parse_ruleset_text(skeleton())
    assert rs.as_of == "2026-01-01"
    for key in REQUIRED_TOP:
        assert key in skeleton()
    for key in REQUIRED_PHASE:
        assert key in skeleton()


def test_missing_keys_are_listed_never_guessed() -> None:
    text = skeleton().replace("as_of = 2026-01-01", "").replace("profit_split = 0.80", "")
    with pytest.raises(RulesetError) as info:
        parse_ruleset_text(text)
    assert info.value.missing_keys == ("as_of", "profit_split")
    phase_text = skeleton().replace(
        "max_daily_loss = 0.05           # fraction ; 0 = pas de règle journalière", ""
    )
    with pytest.raises(RulesetError) as info2:
        parse_ruleset_text(phase_text)
    assert info2.value.missing_keys == ("phases[0].max_daily_loss",)


def test_prose_ruleset_is_an_escalation() -> None:
    with pytest.raises(RulesetError) as info:
        parse_ruleset_text("Max loss 10 %, daily 5 %, target 8 % in phase one.")
    assert info.value.key == "propfirm.not_toml"


def test_bad_as_of_is_refused() -> None:
    raw = {k: v for k, v in _minimal_raw().items()}
    raw["as_of"] = "hier"
    with pytest.raises(RulesetError) as info:
        parse_ruleset(raw)
    assert info.value.key == "propfirm.bad_as_of"
    raw["as_of"] = "2026-02-01"
    assert parse_ruleset(raw).as_of == "2026-02-01"


def test_unknown_ruleset_path_is_reported(tmp_path: Path) -> None:
    with pytest.raises(RulesetError) as info:
        load_ruleset(tmp_path / "absent.toml")
    assert info.value.key == "propfirm.not_found"
    custom = tmp_path / "custom.toml"
    custom.write_text(skeleton(), encoding="utf-8")
    assert load_ruleset(custom).name.startswith("Nom")


def _minimal_raw() -> dict[str, object]:
    import tomllib

    return dict(tomllib.loads(skeleton()))
