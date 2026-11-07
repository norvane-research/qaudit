# SPDX-License-Identifier: AGPL-3.0-or-later
"""Orchestrateur : de l'historique validé au verdict.

Pur et hors ligne : reçoit un ``ValidationResult``, une ``MethodConfig`` et une
graine ; ne lit ni n'écrit rien. Les flux aléatoires des simulations sont
dérivés de la graine par ``SeedSequence.spawn`` avec des rangs fixes, si bien
qu'ajouter une simulation ne change pas les tirages des précédentes.

Hypothèses retenues :
- toutes les grandeurs sont calculées sur la partie utilisable de l'historique
  (``ValidationResult.usable`` : tronquée au trade de ruine inclus, D-03) ;
- un historique de moins de ``min_trades`` trades reçoit un constat bloquant
  (« échantillon insuffisant ») : le moteur refuse de conclure sur trop peu ;
- le nombre d'essais utilisé pour la barrière DSR est celui déclaré par
  l'appelant, sinon ``default_n_trials`` de la méthode ; la courbe de
  sensibilité est toujours publiée à côté (D-06).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qaudit import ENGINE_VERSION
from qaudit.core.config import MethodConfig
from qaudit.core.detectors.registry import build_detectors, run_detectors
from qaudit.core.metrics import Metrics, compute_metrics
from qaudit.core.models import Finding, PriceSeries, Severity, TradeSet, Verdict
from qaudit.core.propfirm import PropfirmResult, Ruleset, simulate
from qaudit.core.regimes import (
    AtrTerciles,
    PeriodStats,
    RegimeClassifier,
    RegimeReport,
    VolatilityTerciles,
    analyse,
    quarterly_stats,
)
from qaudit.core.resample import (
    METHOD_IID,
    METHOD_STATIONARY,
    BootstrapMethod,
    BootstrapResult,
    NullResult,
    PermutationResult,
    bootstrap,
    null_no_edge,
    permutation_test,
)
from qaudit.core.stats import (
    VARIANCE_LO_APPROX,
    DSRResult,
    Sensitivity,
    dsr,
    dsr_sensitivity,
    psr,
)
from qaudit.core.validate import ValidationResult
from qaudit.core.verdict import (
    BARRIER_DD_PERCENTILE,
    BARRIER_DSR,
    BARRIER_NULL_PVALUE,
    BARRIER_PF_P05,
    BARRIER_WF_EFFICIENCY,
    decide,
    evaluate_barriers,
)
from qaudit.core.walkforward import WalkForwardInput, WalkForwardReport, run

SOURCE = "audit"

# rangs fixes des flux aléatoires dérivés de la graine
STREAM_BOOTSTRAP = 0
STREAM_PERMUTATION = 1
STREAM_NULL = 2
STREAM_PROPFIRM = 3
N_STREAMS = 8


@dataclass(frozen=True, slots=True)
class AuditOptions:
    seed: int = 0
    n_iter: int | None = None
    n_trials: int | None = None
    var_sr: float | None = None
    bootstrap_method: str | None = None
    horizon_trading_days: int | None = None
    pnl_scale: float | None = None


DEFAULT_OPTIONS = AuditOptions()


@dataclass(frozen=True)
class AuditResult:
    tradeset: TradeSet
    full_n: int
    ruin_index: int | None
    metrics: Metrics
    psr_value: float
    dsr_result: DSRResult
    sensitivity: Sensitivity
    bootstrap: BootstrapResult
    permutation: PermutationResult
    null: NullResult
    regimes: RegimeReport
    quarters: tuple[PeriodStats, ...]
    walkforward: WalkForwardReport | None
    propfirm: PropfirmResult | None
    findings: tuple[Finding, ...]
    verdict: Verdict
    seed: int
    n_iter: int
    n_trials: int
    method_version: str
    engine_version: str
    prices_provided: bool

    @property
    def wf_efficiency(self) -> float | None:
        """Efficacité walk-forward, ou ``None`` si elle n'a pas pu être établie."""
        if self.walkforward is None or not self.walkforward.evaluable:
            return None
        value = self.walkforward.efficiency
        return None if value != value else value


def streams(seed: int) -> tuple[np.random.Generator, ...]:
    """Générateurs indépendants dérivés de la graine, aux rangs fixes."""
    return tuple(np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(N_STREAMS))


def _bootstrap_method(name: str) -> BootstrapMethod:
    return METHOD_IID if name == METHOD_IID else METHOD_STATIONARY


def _audit_findings(ts: TradeSet, config: MethodConfig, dsr_result: DSRResult) -> list[Finding]:
    out: list[Finding] = []
    if ts.n < config.min_trades:
        out.append(
            Finding.make(
                "too_few_trades",
                Severity.BLOCKING,
                "audit.too_few_trades",
                SOURCE,
                n=ts.n,
                required=config.min_trades,
            )
        )
    if dsr_result.variance_source == VARIANCE_LO_APPROX:
        out.append(
            Finding.make(
                "dsr_lo_variance",
                Severity.INFO,
                "audit.dsr_lo_variance",
                SOURCE,
                var_sr=dsr_result.var_sr,
                n_trials=dsr_result.n_trials,
            )
        )
    return out


def run_audit(
    validation: ValidationResult,
    config: MethodConfig,
    options: AuditOptions = DEFAULT_OPTIONS,
    prices: PriceSeries | None = None,
    walkforward: WalkForwardInput | None = None,
    ruleset: Ruleset | None = None,
    classifier: RegimeClassifier | None = None,
) -> AuditResult:
    """Audit complet, déterministe pour (entrées, version, graine).

    Le classificateur de régimes est injectable ; par défaut : ATR si une série
    de cours est fournie, sinon terciles de volatilité des P&L.
    """
    ts = validation.usable
    n_iter = config.n_iter if options.n_iter is None else options.n_iter
    n_trials = config.default_n_trials if options.n_trials is None else options.n_trials
    method = _bootstrap_method(options.bootstrap_method or config.bootstrap_method)
    rng = streams(options.seed)

    metrics = compute_metrics(ts)
    psr_value = psr(metrics.sharpe_trade, metrics.skew, metrics.kurtosis, ts.n)
    dsr_result = dsr(metrics.sharpe_trade, metrics.skew, metrics.kurtosis, ts.n, n_trials,
                     options.var_sr)
    sensitivity = dsr_sensitivity(
        metrics.sharpe_trade, metrics.skew, metrics.kurtosis, ts.n,
        config.barrier(BARRIER_DSR).threshold, grid=config.trial_grid, var_sr=options.var_sr,
    )
    boot = bootstrap(ts.profit, n_iter, rng[STREAM_BOOTSTRAP], method=method)
    perm = permutation_test(ts.profit, n_iter, rng[STREAM_PERMUTATION])
    null = null_no_edge(ts.profit, n_iter, rng[STREAM_NULL])
    if classifier is None:
        classifier = (
            AtrTerciles(config.regimes_atr_period)
            if prices is not None
            else VolatilityTerciles(config.regimes_volatility_window)
        )
    regimes = analyse(ts, classifier, prices)
    quarters = quarterly_stats(ts)
    wf_report: WalkForwardReport | None = None
    wf_efficiency: float | None = None
    if walkforward is not None:
        wf_report = run(
            walkforward, n_folds=config.walkforward_n_folds,
            protocol=config.walkforward_protocol, selection=config.walkforward_selection,
        )
        wf_efficiency = wf_report.efficiency if wf_report.evaluable else None
    propfirm: PropfirmResult | None = None
    if ruleset is not None:
        horizon = (
            config.propfirm_horizon_trading_days
            if options.horizon_trading_days is None
            else options.horizon_trading_days
        )
        propfirm = simulate(
            ts, ruleset, n_iter, rng[STREAM_PROPFIRM],
            horizon_trading_days=horizon, pnl_scale=options.pnl_scale,
        )

    findings = list(validation.findings)
    findings.extend(_audit_findings(ts, config, dsr_result))
    if null.evaluable:
        findings.append(
            Finding.make("null_empirical", Severity.INFO, null.note_key, SOURCE, p0=null.p0)
        )
    findings.extend(run_detectors(build_detectors(config), ts, prices))

    barriers = evaluate_barriers(
        config,
        {
            BARRIER_DSR: dsr_result.dsr,
            BARRIER_PF_P05: boot.profit_factor_p05,
            BARRIER_DD_PERCENTILE: perm.drawdown_percentile,
            BARRIER_NULL_PVALUE: null.p_value,
            BARRIER_WF_EFFICIENCY: wf_efficiency,
        },
    )
    verdict = decide(config, barriers, tuple(findings))
    return AuditResult(
        tradeset=ts,
        full_n=validation.tradeset.n,
        ruin_index=validation.ruin_index,
        metrics=metrics,
        psr_value=psr_value,
        dsr_result=dsr_result,
        sensitivity=sensitivity,
        bootstrap=boot,
        permutation=perm,
        null=null,
        regimes=regimes,
        quarters=quarters,
        walkforward=wf_report,
        propfirm=propfirm,
        findings=tuple(findings),
        verdict=verdict,
        seed=options.seed,
        n_iter=n_iter,
        n_trials=n_trials,
        method_version=config.version,
        engine_version=ENGINE_VERSION,
        prices_provided=prices is not None,
    )
