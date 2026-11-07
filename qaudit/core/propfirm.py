# SPDX-License-Identifier: AGPL-3.0-or-later
"""Simulateur propfirm : règlement (objet chargé depuis un TOML par la coquille)
et moteur de rejeu par journées entières.

Le rejeu rééchantillonne des **journées entières** (bootstrap par blocs
stationnaire sur la série des journées, longueur de bloc automatique) en
conservant l'ordre intra-journalier : les règles de perte journalière portent
ainsi sur une dynamique qui a existé.

Hypothèses retenues (toutes imprimées ou documentées dans le rapport) :
- seuls les résultats **clos** sont connus : l'equity intra-journalière est le
  cumul des trades clos dans la journée ; le flottant n'étant pas observable,
  les probabilités de violation sont des planchers ;
- le temps est compté en **journées de trading** (journées où au moins un trade
  a été clos) ; une limite calendaire (``max_days``) est convertie avec le
  rapport historique jours calendaires / journées de trading ;
- une phase sans limite de durée (``max_days = 0``) court sur
  ``horizon_trading_days``, paramètre explicite imprimé dans le rapport, jamais
  une constante cachée (D-05) ;
- report du solde entre phases : option explicite ``balance_carry``
  (``"reset"`` : chaque phase repart du solde initial du règlement, qui sert de
  référence aux cibles et limites ; ``"carry"`` : la phase suivante démarre du
  solde final de la précédente, qui devient la référence de ses cibles et
  limites) (D-07) ;
- la cible de profit est constatée en fin de journée ; la règle de consistance
  (part maximale d'une journée dans le profit) doit être satisfaite au moment
  où la cible est constatée, sinon la phase continue ;
- le drawdown suiveur est mesuré sur le plus haut des soldes de **fin de
  journée** (``trailing``) ; il peut se figer au solde initial
  (``trailing_lock_at_initial``) ;
- les P&L historiques sont mis à l'échelle du compte du règlement par
  ``pnl_scale = solde_règlement / solde_historique`` quand les deux sont
  connus (sinon 1) ;
- la phase financée verse ``profit_split × profit`` tous les
  ``payout_cycle_days`` jours de trading, puis le solde revient au solde
  initial ; l'espérance économique nette vaut
  −frais + P(financé)·remboursement + E[versements].
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np

from qaudit.core.errors import InternalError
from qaudit.core.models import BoolArray, FloatArray, IndexArray, IntArray, TradeSet
from qaudit.core.resample import stationary_block_length, stationary_bootstrap_indices

CARRY_RESET: Final = "reset"
CARRY_CARRY: Final = "carry"
DD_STATIC: Final = "static"
DD_TRAILING: Final = "trailing"
BASE_INITIAL: Final = "initial"
BASE_BALANCE: Final = "balance"

CAUSE_DAILY_LOSS: Final = "daily_loss"
CAUSE_MAX_LOSS: Final = "max_loss"
CAUSE_TIMEOUT: Final = "timeout"
CAUSE_CONSISTENCY: Final = "consistency"
CAUSE_MIN_DAYS: Final = "min_days"
CAUSES: tuple[str, ...] = (
    CAUSE_DAILY_LOSS, CAUSE_MAX_LOSS, CAUSE_TIMEOUT, CAUSE_CONSISTENCY, CAUSE_MIN_DAYS,
)

PATH_CHUNK = 2000
# tolérance relative des comparaisons à un seuil (toucher le seuil compte :
# cible atteinte à l'égalité près, plancher violé à l'égalité près)
REL_TOL = 1e-9


# ---------------------------------------------------------------------------
# règlement
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PhaseRule:
    """Une phase. Les fractions sont relatives au solde initial du règlement.
    Une règle absente est écrite explicitement à 0 (jamais devinée)."""

    name: str
    funded: bool
    profit_target: float
    max_daily_loss: float
    daily_loss_base: str
    max_total_loss: float
    drawdown_type: str
    trailing_lock_at_initial: bool
    min_trading_days: int
    max_days: int
    consistency_max_day_share: float


@dataclass(frozen=True, slots=True)
class Ruleset:
    name: str
    as_of: str
    initial_balance: float
    currency: str
    fee: float
    refund_fee_on_funded: bool
    profit_split: float
    payout_cycle_days: int
    balance_carry: str
    phases: tuple[PhaseRule, ...]

    def __post_init__(self) -> None:
        if not self.phases:
            raise InternalError("internal.ruleset_no_phase")
        if self.balance_carry not in (CARRY_RESET, CARRY_CARRY):
            raise InternalError("internal.ruleset_bad_carry", value=self.balance_carry)
        for phase in self.phases:
            if phase.drawdown_type not in (DD_STATIC, DD_TRAILING):
                raise InternalError("internal.ruleset_bad_drawdown", value=phase.drawdown_type)
            if phase.daily_loss_base not in (BASE_INITIAL, BASE_BALANCE):
                raise InternalError("internal.ruleset_bad_base", value=phase.daily_loss_base)


# ---------------------------------------------------------------------------
# agrégat journalier
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DayProfile:
    """Journées de trading : P&L total, pire et meilleur cumul intra-journalier."""

    pnl: FloatArray
    min_run: FloatArray
    max_run: FloatArray
    n_trades: IntArray
    calendar_days_per_trading_day: float
    block_length: float

    @property
    def n_days(self) -> int:
        return int(self.pnl.size)


def daily_profile(ts: TradeSet, pnl_scale: float = 1.0) -> DayProfile:
    """Agrège l'historique par journée civile de clôture, ordre intra-journalier
    conservé (l'ordre canonique du TradeSet)."""
    if ts.n == 0:
        empty = np.zeros(0)
        return DayProfile(empty, empty, empty, np.zeros(0, dtype=np.int64), 1.0, 1.0)
    days = ts.close_time.astype("datetime64[D]").astype(np.int64)
    unique, inverse, counts = np.unique(days, return_inverse=True, return_counts=True)
    profit = ts.profit * pnl_scale
    pnl = np.bincount(inverse, weights=profit, minlength=unique.size)
    cum = np.cumsum(profit)
    starts = np.concatenate(([0], np.cumsum(counts)[:-1]))
    offset = np.concatenate(([0.0], cum[:-1]))[starts]
    within = cum - offset[inverse]
    bounds = list(zip(starts.tolist(), counts.tolist(), strict=True))
    min_run = np.minimum(0.0, np.array([within[s : s + c].min() for s, c in bounds]))
    max_run = np.maximum(0.0, np.array([within[s : s + c].max() for s, c in bounds]))
    span = ts.span_days
    ratio = span / unique.size if unique.size > 1 and span > 0 else 1.0
    block = stationary_block_length(pnl)
    return DayProfile(pnl, min_run, max_run, counts.astype(np.int64), max(1.0, ratio), block)


# ---------------------------------------------------------------------------
# résultats
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PhaseOutcome:
    name: str
    funded: bool
    horizon_trading_days: int
    horizon_from_ruleset: bool
    pass_probability: float
    cumulative_pass_probability: float
    fail_causes: tuple[tuple[str, float], ...]
    median_days_to_pass: float
    ruin_probability: float


@dataclass(frozen=True, slots=True)
class PropfirmResult:
    ruleset_name: str
    as_of: str
    n_paths: int
    pnl_scale: float
    horizon_trading_days: int
    calendar_days_per_trading_day: float
    day_block_length: float
    n_history_days: int
    balance_carry: str
    phases: tuple[PhaseOutcome, ...]
    funded_probability: float
    funded_ruin_probability: float
    median_trader_gain: float
    expected_payouts: float
    expected_net_value: float
    evaluable: bool


# ---------------------------------------------------------------------------
# moteur
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PhaseRun:
    """Résultat vectorisé d'une phase pour un lot de trajectoires."""

    passed: BoolArray
    cause: IntArray  # index dans CAUSES ; -1 si réussie
    days: IntArray  # journée de sortie (1-based) ; horizon si dépassement
    final_balance: FloatArray
    payouts: FloatArray


def _horizon(phase: PhaseRule, profile: DayProfile, horizon_trading_days: int) -> tuple[int, bool]:
    """Horizon en journées de trading : limite du règlement convertie, sinon le
    paramètre explicite (D-05)."""
    if phase.max_days > 0:
        return max(1, math.ceil(phase.max_days / profile.calendar_days_per_trading_day)), True
    return max(1, horizon_trading_days), False


def _first_true(mask: BoolArray) -> IntArray:
    """Index de la première colonne vraie par ligne ; n_cols si aucune."""
    any_true = mask.any(axis=1)
    first = np.argmax(mask, axis=1)
    return np.where(any_true, first, mask.shape[1]).astype(np.int64)


def _sample_days(
    profile: DayProfile, n_paths: int, horizon: int, rng: np.random.Generator
) -> IndexArray:
    """Indices de journées rééchantillonnées par blocs stationnaires, prolongés
    jusqu'à l'horizon."""
    blocks = [stationary_bootstrap_indices(profile.n_days, n_paths, profile.block_length, rng)]
    while sum(b.shape[1] for b in blocks) < horizon:
        blocks.append(
            stationary_bootstrap_indices(profile.n_days, n_paths, profile.block_length, rng)
        )
    return np.concatenate(blocks, axis=1)[:, :horizon]


def _breaches(
    phase: PhaseRule,
    reference: FloatArray,
    start: FloatArray,
    sod: FloatArray,
    eod: FloatArray,
    min_run: FloatArray,
) -> tuple[BoolArray, BoolArray]:
    """(violation quelconque, violation journalière) par journée ; ``reference``
    est le solde de référence de la phase pour chaque trajectoire."""
    ref = reference[:, None]
    daily = np.zeros(sod.shape, dtype=bool)
    if phase.max_daily_loss > 0:
        base = np.broadcast_to(ref, sod.shape) if phase.daily_loss_base == BASE_INITIAL else sod
        daily = min_run <= -phase.max_daily_loss * base * (1.0 - REL_TOL)
    if phase.drawdown_type == DD_STATIC:
        floor = np.broadcast_to(ref * (1.0 - phase.max_total_loss), sod.shape)
    else:
        prev_eod = np.concatenate((start[:, None], eod[:, :-1]), axis=1)
        floor = np.maximum.accumulate(prev_eod, axis=1) - phase.max_total_loss * ref
        if phase.trailing_lock_at_initial:
            floor = np.minimum(floor, ref)
    total = (sod + min_run) <= floor * (1.0 + REL_TOL)
    return daily | total, daily


def _success(
    phase: PhaseRule, reference: FloatArray, pnl: FloatArray, eod: FloatArray
) -> tuple[BoolArray, BoolArray, BoolArray]:
    """(succès constaté, cible atteinte, consistance satisfaite) par journée."""
    ref = reference[:, None]
    target = eod >= ref * (1.0 + phase.profit_target) * (1.0 - REL_TOL)
    consistent = np.ones(eod.shape, dtype=bool)
    if phase.consistency_max_day_share > 0:
        best_day = np.maximum.accumulate(np.maximum(pnl, 0.0), axis=1)
        profit = eod - ref
        positive = profit > 0
        limit = phase.consistency_max_day_share * np.where(positive, profit, 1.0)
        consistent = ~positive | (best_day <= limit * (1.0 + REL_TOL))
    enough_days = np.arange(1, eod.shape[1] + 1)[None, :] >= phase.min_trading_days
    return target & consistent & enough_days, target, consistent


def _evaluation_phase(
    phase: PhaseRule,
    reference: FloatArray,
    start: FloatArray,
    pnl: FloatArray,
    min_run: FloatArray,
) -> _PhaseRun:
    n_paths, horizon = pnl.shape
    eod = start[:, None] + np.cumsum(pnl, axis=1)
    sod = np.concatenate((start[:, None], eod[:, :-1]), axis=1)
    breach, daily = _breaches(phase, reference, start, sod, eod, min_run)
    success, target, consistent = _success(phase, reference, pnl, eod)
    first_breach = _first_true(breach)
    first_success = _first_true(success)
    passed = first_success < first_breach
    rows = np.arange(n_paths)
    exit_col = np.minimum(np.minimum(first_success, first_breach), horizon - 1)
    breached = ~passed & (first_breach < horizon)
    timed_out = ~passed & ~breached
    cause = np.full(n_paths, -1, dtype=np.int64)
    cause[breached] = CAUSES.index(CAUSE_MAX_LOSS)
    cause[breached & daily[rows, exit_col]] = CAUSES.index(CAUSE_DAILY_LOSS)
    cause[timed_out] = CAUSES.index(CAUSE_TIMEOUT)
    cause[timed_out & target[:, -1] & ~consistent[:, -1]] = CAUSES.index(CAUSE_CONSISTENCY)
    cause[timed_out & target[:, -1] & consistent[:, -1]] = CAUSES.index(CAUSE_MIN_DAYS)
    days = np.where(passed, first_success + 1, np.minimum(first_breach + 1, horizon))
    return _PhaseRun(passed, cause, days.astype(np.int64), eod[rows, exit_col], np.zeros(n_paths))


def _funded_phase(
    phase: PhaseRule,
    reference: FloatArray,
    start: FloatArray,
    pnl: FloatArray,
    min_run: FloatArray,
    split: float,
    cycle_days: int,
) -> _PhaseRun:
    """Phase financée : versements périodiques jusqu'à la violation ou l'horizon.
    Après chaque versement, le solde revient au solde de référence."""
    n_paths, horizon = pnl.shape
    eod = start[:, None] + np.cumsum(pnl, axis=1)
    sod = np.concatenate((start[:, None], eod[:, :-1]), axis=1)
    breach, daily = _breaches(phase, reference, start, sod, eod, min_run)
    first_breach = _first_true(breach)
    alive = np.arange(horizon)[None, :] < first_breach[:, None]
    cycle = max(1, cycle_days)
    payouts = np.zeros(n_paths)
    balance = start.copy()
    for begin in range(0, horizon, cycle):
        stop = min(begin + cycle, horizon)
        balance = balance + np.where(alive[:, begin:stop], pnl[:, begin:stop], 0.0).sum(axis=1)
        gain = np.where(alive[:, stop - 1] & (balance > reference), balance - reference, 0.0)
        payouts += split * gain
        balance = np.where(gain > 0, reference, balance)
    survived = first_breach >= horizon
    rows = np.arange(n_paths)
    exit_col = np.minimum(first_breach, horizon - 1)
    cause = np.full(n_paths, -1, dtype=np.int64)
    cause[~survived] = CAUSES.index(CAUSE_MAX_LOSS)
    cause[~survived & daily[rows, exit_col]] = CAUSES.index(CAUSE_DAILY_LOSS)
    days = np.minimum(first_breach + 1, horizon).astype(np.int64)
    return _PhaseRun(survived, cause, days, eod[rows, exit_col], payouts)


def _run_phase(
    phase: PhaseRule,
    profile: DayProfile,
    ruleset: Ruleset,
    start: FloatArray,
    horizon: int,
    rng: np.random.Generator,
) -> _PhaseRun:
    idx = _sample_days(profile, start.size, horizon, rng)
    pnl = profile.pnl[idx]
    min_run = profile.min_run[idx]
    if ruleset.balance_carry == CARRY_CARRY:
        reference = start
    else:
        reference = np.full(start.size, ruleset.initial_balance)
    if phase.funded:
        return _funded_phase(
            phase, reference, start, pnl, min_run, ruleset.profit_split,
            ruleset.payout_cycle_days,
        )
    return _evaluation_phase(phase, reference, start, pnl, min_run)


def _empty_result(ruleset: Ruleset, n_paths: int, horizon: int, scale: float) -> PropfirmResult:
    nan = math.nan
    return PropfirmResult(
        ruleset.name, ruleset.as_of, n_paths, scale, horizon, 1.0, 1.0, 0, ruleset.balance_carry,
        (), nan, nan, nan, nan, nan, False,
    )


def _phase_outcome(
    phase: PhaseRule,
    horizon: int,
    from_ruleset: bool,
    alive_before: BoolArray,
    passed: BoolArray,
    cause: IntArray,
    days: IntArray,
) -> PhaseOutcome:
    n_paths = alive_before.size
    n_alive = int(alive_before.sum())
    p_pass = float(np.sum(passed & alive_before)) / n_alive if n_alive else 0.0
    causes = tuple(
        (name, float(np.sum(alive_before & (cause == i))) / n_alive if n_alive else math.nan)
        for i, name in enumerate(CAUSES)
    )
    pass_days = days[alive_before & passed]
    return PhaseOutcome(
        name=phase.name,
        funded=phase.funded,
        horizon_trading_days=horizon,
        horizon_from_ruleset=from_ruleset,
        pass_probability=p_pass,
        cumulative_pass_probability=float(np.sum(passed & alive_before)) / n_paths,
        fail_causes=causes,
        median_days_to_pass=float(np.median(pass_days)) if pass_days.size else math.nan,
        ruin_probability=1.0 - p_pass if phase.funded else math.nan,
    )


def simulate(
    ts: TradeSet,
    ruleset: Ruleset,
    n_paths: int,
    rng: np.random.Generator,
    *,
    horizon_trading_days: int,
    pnl_scale: float | None = None,
) -> PropfirmResult:
    """Rejoue le règlement sur ``n_paths`` trajectoires de journées rééchantillonnées."""
    if pnl_scale is None:
        pnl_scale = ruleset.initial_balance / ts.initial_balance if ts.initial_balance else 1.0
    profile = daily_profile(ts, pnl_scale)
    if profile.n_days < 2 or n_paths < 1:
        return _empty_result(ruleset, n_paths, horizon_trading_days, pnl_scale)
    initial = ruleset.initial_balance
    n_eval = sum(1 for p in ruleset.phases if not p.funded)
    alive = np.ones(n_paths, dtype=bool)
    funded_mask = np.ones(n_paths, dtype=bool) if n_eval == 0 else np.zeros(n_paths, dtype=bool)
    balance = np.full(n_paths, initial)
    payouts_total = np.zeros(n_paths)
    outcomes: list[PhaseOutcome] = []
    funded_ruin = math.nan
    seen_eval = 0
    for phase in ruleset.phases:
        horizon, from_ruleset = _horizon(phase, profile, horizon_trading_days)
        passed = np.zeros(n_paths, dtype=bool)
        cause = np.full(n_paths, -1, dtype=np.int64)
        days = np.zeros(n_paths, dtype=np.int64)
        idx_alive = np.nonzero(alive)[0]
        for begin in range(0, idx_alive.size, PATH_CHUNK):
            sel = idx_alive[begin : begin + PATH_CHUNK]
            run = _run_phase(phase, profile, ruleset, balance[sel], horizon, rng)
            passed[sel] = run.passed
            cause[sel] = run.cause
            days[sel] = run.days
            payouts_total[sel] += run.payouts
            balance[sel] = run.final_balance if ruleset.balance_carry == CARRY_CARRY else initial
        outcome = _phase_outcome(phase, horizon, from_ruleset, alive, passed, cause, days)
        outcomes.append(outcome)
        alive = alive & passed
        if phase.funded:
            funded_ruin = outcome.ruin_probability
        else:
            seen_eval += 1
            if seen_eval == n_eval:
                funded_mask = alive.copy()
    refund = ruleset.fee if ruleset.refund_fee_on_funded else 0.0
    gains = payouts_total - ruleset.fee + refund * funded_mask
    return PropfirmResult(
        ruleset_name=ruleset.name,
        as_of=ruleset.as_of,
        n_paths=n_paths,
        pnl_scale=pnl_scale,
        horizon_trading_days=horizon_trading_days,
        calendar_days_per_trading_day=profile.calendar_days_per_trading_day,
        day_block_length=profile.block_length,
        n_history_days=profile.n_days,
        balance_carry=ruleset.balance_carry,
        phases=tuple(outcomes),
        funded_probability=float(funded_mask.mean()),
        funded_ruin_probability=funded_ruin,
        median_trader_gain=float(np.median(gains)),
        expected_payouts=float(payouts_total.mean()),
        expected_net_value=float(gains.mean()),
        evaluable=True,
    )
