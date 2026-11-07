# SPDX-License-Identifier: AGPL-3.0-or-later
"""Document public « Méthode qaudit » en Markdown, généré depuis la
configuration de méthode réellement chargée (seuils, bandes, paramètres des
détecteurs) et les catalogues de textes.

Généré et non rédigé à la main : la méthode publiée ne peut pas diverger des
seuils appliqués. ``docs/methode-<version>.md`` est produit par
``qaudit methode`` et un test vérifie qu'il est à jour.
"""

from __future__ import annotations

from qaudit.core.config import MethodConfig
from qaudit.i18n import Catalog
from qaudit.io.writers.render import Fmt

BARRIERS = ("dsr", "pf_p05", "dd_percentile", "null_pvalue", "wf_efficiency")
DETECTORS = (
    "martingale", "grid", "no_stop", "profit_concentration", "equity_linearity",
    "payoff_asymmetry", "period_dependence", "holding_time", "stop_geometry", "lookahead",
    "execution_realism",
)
_PCT = {"dsr", "null_pvalue", "wf_efficiency"}


def render_methode(config: MethodConfig, catalog: Catalog) -> str:
    c, f = catalog, Fmt(catalog)
    t = c.text
    lines: list[str] = [f"# {t('methode.title', version=config.version)}", ""]
    lines += [t("methode.intro"), "", t("methode.principles"), ""]

    lines += [f"## {t('methode.h.barriers')}", "", t("methode.barriers_intro"), ""]
    header = (
        f"| {t('report.col.barrier')} | {t('methode.col.question')} | {t('report.col.threshold')} "
        f"| {t('report.col.band')} |"
    )
    lines += [header, "|---|---|---|---|"]
    by_name = {b.name: b for b in config.barriers}
    for name in BARRIERS:
        b = by_name[name]
        sense = "<" if b.sense == "below" else "≥"
        if name in _PCT:
            shown = f"{sense} {f.pct(b.threshold)}"
            band = f"[{f.pct(b.band_low)} ; {f.pct(b.band_high)}]"
        else:
            shown = f"{sense} {f.num(b.threshold, 2)}"
            band = f"[{f.num(b.band_low, 2)} ; {f.num(b.band_high, 2)}]"
        lines.append(
            f"| {t(b.message_key)} | {t(f'explain.barrier_title.{name}')} | {shown} | {band} |"
        )
    lines.append("")
    for name in BARRIERS:
        lines += [f"### {t(f'explain.barrier_title.{name}')}", "", t(f"methode.barrier.{name}"), ""]

    lines += [f"## {t('methode.h.decision')}", ""]
    lines += [
        f"- {t('methode.rule.blocking', n=config.blocking_no_go)}",
        f"- {t('methode.rule.triggered')}",
        f"- {t('methode.rule.majors', n=config.major_conditional)}",
        f"- {t('methode.rule.unevaluated')}",
        f"- {t('methode.rule.band')}",
        f"- {t('methode.rule.sample', n=config.min_trades)}",
        "",
        t("methode.no_score"),
        "",
    ]

    lines += [f"## {t('methode.h.detectors')}", "", t("methode.detectors_intro"), ""]
    lines += [
        f"| {t('methode.col.detector')} | {t('methode.col.what')} | {t('methode.col.params')} |",
        "|---|---|---|",
    ]
    for name in DETECTORS:
        params = config.detectors.get(name, {})
        shown = ", ".join(f"{k} = {_param(v, c.decimal)}" for k, v in params.items())
        lines.append(f"| {t(f'explain.finding_title.{name}')} (`{name}`) | "
                     f"{t(f'methode.detector.{name}')} | {shown} |")
    lines += ["", t("methode.detectors_note"), ""]

    lines += [f"## {t('methode.h.simulation')}", ""]
    grid = ", ".join(str(x) for x in config.trial_grid)
    sims = (
        t("methode.sim.iterations", n=f.integer(config.n_iter)),
        t("methode.sim.bootstrap", method=t(f"report.bootstrap.{config.bootstrap_method}")),
        t("methode.sim.permutation"),
        t("methode.sim.null"),
        t("methode.sim.dsr", n=config.default_n_trials, grid=grid),
        t(
            "methode.sim.walkforward",
            folds=config.walkforward_n_folds,
            protocol=t(f"report.wf.{config.walkforward_protocol}"),
            selection=t(f"report.wf.{config.walkforward_selection}"),
        ),
        t("methode.sim.regimes", window=config.regimes_volatility_window,
          atr=config.regimes_atr_period),
        t("methode.sim.propfirm", days=config.propfirm_horizon_trading_days),
        t("methode.sim.gap", days=f.num(config.max_gap_days, 0)),
        t("methode.sim.seed"),
    )
    lines += [f"- {s}" for s in sims]
    lines.append("")

    lines += [f"## {t('methode.h.inputs')}", "", t("methode.inputs"), ""]
    lines += [f"## {t('methode.h.limits')}", ""]
    limits = ("closed", "prices", "wf", "truncation", "future", "advice")
    lines += [f"- {t(f'methode.limit.{k}')}" for k in limits]
    lines += ["", f"## {t('methode.h.versioning')}", ""]
    lines += [t("methode.versioning", version=config.version), ""]
    lines += [f"## {t('methode.h.reproduce')}", "", t("methode.reproduce"), ""]
    return "\n".join(lines)


def _param(value: float, decimal: str) -> str:
    """Paramètre de détecteur : entier tel quel, sinon au plus trois décimales."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").replace(".", decimal)
