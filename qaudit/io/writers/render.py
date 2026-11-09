# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vue rendue d'un document : sections, titres, tableaux — dans la langue
demandée, filtrée par le profil d'offre. Consommée par les écrivains HTML et
PDF, construite à partir du **document JSON** (jamais de l'objet de calcul), ce
qui garantit qu'un rendu depuis l'archive est identique au rendu direct.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from qaudit.i18n import Catalog
from qaudit.io.document import number
from qaudit.io.profile import Profile

CRITICAL = ("blocking", "major")
SEVERITY_ORDER = {"blocking": 0, "major": 1, "minor": 2, "info": 3}


@dataclass(frozen=True, slots=True)
class Table:
    """``tags[i]`` : étiquette sémantique de la ligne ``i`` (statut de barrière,
    gravité, ``neg`` pour un résultat négatif…) ; vide = aucune. Les écrivains
    s'en servent pour la couleur, jamais pour le contenu."""

    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Entry:
    """Un constat : gravité (code et libellé), code du constat, texte intégral."""

    tag: str
    label: str
    code: str
    text: str


@dataclass(frozen=True, slots=True)
class Point:
    label: str
    value: float
    text: str


@dataclass(frozen=True, slots=True)
class Chart:
    """Série à barres (valeurs dans [0 ; y_max]) avec un seuil horizontal."""

    points: tuple[Point, ...]
    threshold: float | None
    threshold_text: str
    y_max: float = 1.0
    decimal: str = "."


@dataclass(frozen=True, slots=True)
class Section:
    """``help`` : encadré « comment lire » en langage courant (texte fixe du
    catalogue) ; ``closing`` : paragraphes rendus après les tableaux."""

    id: str
    title: str
    paragraphs: tuple[str, ...] = ()
    tables: tuple[Table, ...] = ()
    items: tuple[str, ...] = ()
    entries: tuple[Entry, ...] = ()
    chart: Chart | None = None
    help: str = ""
    closing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReportView:
    lang: str
    title: str
    system_name: str
    decision_code: str
    decision_label: str
    human_review: bool
    profile_code: str
    profile_label: str
    sections: tuple[Section, ...]
    review_label: str = ""
    facts: tuple[tuple[str, str], ...] = ()
    counts: tuple[tuple[str, str, int], ...] = ()
    footer: str = ""
    toc_label: str = ""
    brand_line: str = ""
    help_label: str = ""
    verdict_caption: str = ""


class Fmt:
    """Formatage numérique localisé (séparateur décimal du catalogue)."""

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def num(self, value: object, digits: int = 2) -> str:
        if value is None:
            return self.catalog.text("report.na")
        v = number(value)  # float, int ou chaîne « NaN » / « Infinity » du document
        if math.isnan(v):
            return self.catalog.text("report.na")
        if math.isinf(v):
            return "+∞" if v > 0 else "−∞"
        text = f"{v:,.{digits}f}".replace(",", "\u202f")
        return text.replace(".", self.catalog.decimal)

    def pct(self, value: object, digits: int = 1) -> str:
        v = number(value)
        if math.isnan(v):
            return self.catalog.text("report.na")
        return self.num(100.0 * v, digits) + "\u202f%"

    def integer(self, value: object) -> str:
        if value is None:
            return self.catalog.text("report.na")
        return f"{int(number(value)):,}".replace(",", "\u202f")


def _t(catalog: Catalog, key: str, **params: object) -> str:
    return catalog.text(key, **params)


def _finding_text(catalog: Catalog, finding: Mapping[str, Any]) -> str:
    params = {k: _param(v) for k, v in finding.get("params", {}).items()}
    return catalog.text(str(finding["message_key"]), **params)


def _param(value: object) -> object:
    if isinstance(value, str) and value in ("NaN", "Infinity", "-Infinity"):
        return number(value)
    return value


def _sorted_findings(findings: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        findings, key=lambda f: (SEVERITY_ORDER.get(str(f["severity"]), 9), str(f["code"]))
    )


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------


def _entete(
    doc: Mapping[str, Any], c: Catalog, f: Fmt, system_name: str, profile: Profile
) -> Section:
    data = doc["data"]
    rows = (
        (_t(c, "report.system"), system_name),
        (_t(c, "report.engine_version"), str(doc["engine_version"])),
        (_t(c, "report.method_version"), str(doc["method_version"])),
        (_t(c, "report.seed"), str(doc["seed"])),
        (_t(c, "report.fingerprint"), str(data["fingerprint"])),
        (_t(c, "report.n_iter"), f.integer(doc["n_iter"])),
        (_t(c, "report.n_trials"), f.integer(doc["n_trials"])),
        (_t(c, "report.period"), f"{data['first_open'] or '—'} → {data['last_close'] or '—'}"),
        (
            _t(c, "report.n_trades"),
            f"{f.integer(data['n_usable'])} / {f.integer(data['n_trades'])}",
        ),
        (_t(c, "report.currency"), str(data["currency"])),
        (_t(c, "report.initial_balance"), f.num(data["initial_balance"], 2)),
        (_t(c, "report.profile"), f"{profile.label} ({profile.code})"),
    )
    return Section("entete", _t(c, "report.section.entete"), tables=(Table((), rows),))


def _verdict(doc: Mapping[str, Any], c: Catalog, f: Fmt) -> Section:
    verdict = doc["verdict"]
    label = _t(c, f"decision.{verdict['decision']}")
    counts = verdict["counts"]
    paragraphs = [
        _t(c, "report.verdict_line", decision=label),
        _t(
            c,
            "report.counts",
            blocking=counts["blocking"],
            major=counts["major"],
            minor=counts["minor"],
            info=counts["info"],
        ),
    ]
    if verdict["revue_humaine"]:
        paragraphs.append(_t(c, "report.human_review"))
    triggered = [b for b in verdict["barriers"] if b["triggered"]]
    items = [
        _t(
            c,
            "report.barrier_triggered",
            name=_t(c, str(b["message_key"])),
            value=f.num(b["value"], 3),
            threshold=f.num(b["threshold"], 3),
        )
        for b in triggered
    ]
    items += [
        _finding_text(c, fd)
        for fd in _sorted_findings(doc["findings"])
        if fd["severity"] == "blocking"
    ]
    return Section(
        "verdict", _t(c, "report.section.verdict"), tuple(paragraphs), items=tuple(items)
    )


def _en_clair(doc: Mapping[str, Any], c: Catalog, f: Fmt) -> Section:
    """Explication en langage courant : sens du verdict, les cinq tests avec
    leurs chiffres, les défauts graves, ce qui reste à faire. Tout vient du
    document ; les phrases sont des gabarits du catalogue « explain »."""
    verdict = doc["verdict"]
    decision = str(verdict["decision"])
    counts = verdict["counts"]
    barriers = verdict["barriers"]
    reasons = _reasons(
        c,
        (
            ("tests", sum(1 for b in barriers if b["triggered"])),
            ("blocking", int(counts["blocking"])),
            ("unevaluated", sum(1 for b in barriers if not b["evaluated"])),
            ("indecision", sum(1 for b in barriers if b["indecision"])),
            ("majors", int(counts["major"])),
        ),
    )
    paragraphs = (
        _t(c, f"explain.verdict.{decision}", reasons=reasons),
        _t(c, "explain.verdict.scope"),
        _t(c, "explain.barriers_intro"),
    )
    entries = [_barrier_entry(b, doc, c, f) for b in barriers]
    critical = [fd for fd in _sorted_findings(doc["findings"]) if fd["severity"] in CRITICAL]
    entries += [_explained_finding(c, fd) for fd in critical]
    closing = (
        *(() if critical else (_t(c, "explain.critical_none"),)),
        _t(c, f"explain.next.{decision}"),
        _t(c, "explain.not_advice"),
    )
    return Section(
        "en_clair", _t(c, "explain.section_title"), paragraphs, entries=tuple(entries),
        closing=closing,
    )


def _reasons(c: Catalog, counted: tuple[tuple[str, int], ...]) -> str:
    """« 3 tests ont échoué et 1 défaut majeur a été relevé » — seules les
    quantités non nulles sont nommées, reliées par le mot du catalogue."""
    parts = [_t(c, f"explain.reason.{key}", n=n) for key, n in counted if n > 0]
    if not parts:
        return _t(c, "explain.reason.none")
    if len(parts) == 1:
        return parts[0]
    return _t(c, "explain.reason.join_last", head=", ".join(parts[:-1]), last=parts[-1])


def _barrier_entry(b: Mapping[str, Any], doc: Mapping[str, Any], c: Catalog, f: Fmt) -> Entry:
    name, tag = str(b["name"]), _barrier_tag(b)
    if not b["evaluated"] and c.has(f"explain.barrier.{name}_na"):
        text = _t(c, f"explain.barrier.{name}_na")
    else:
        text = _t(c, f"explain.barrier.{name}", **_barrier_params(b, doc, f))
    return Entry(
        tag,
        _t(c, f"report.status.{tag}"),
        _t(c, f"explain.barrier_title.{name}"),
        f"{text} {_t(c, f'explain.status.{tag}')}",
    )


def _barrier_params(b: Mapping[str, Any], doc: Mapping[str, Any], f: Fmt) -> dict[str, str]:
    name = str(b["name"])
    value, threshold = b["value"], b["threshold"]
    if name in ("dsr", "null_pvalue", "wf_efficiency"):
        shown, limit = f.pct(value if value is not None else "NaN"), f.pct(threshold)
    elif name == "dd_percentile":
        shown, limit = f.num(value, 1), f.num(threshold, 0)
    else:
        shown, limit = f.num(value, 3), f.num(threshold, 2)
    return {
        "value": shown,
        "threshold": limit,
        "n_trials": f.integer(doc["n_trials"]),
        "n_iter": f.integer(doc["n_iter"]),
        "observed": f.num(doc["resampling"]["permutation"]["observed_drawdown"]),
    }


def _explained_finding(c: Catalog, fd: Mapping[str, Any]) -> Entry:
    code = str(fd["code"])
    title_key = f"explain.finding_title.{code}"
    title = _t(c, title_key) if c.has(title_key) else code
    text = _finding_text(c, fd)
    if c.has(f"explain.finding.{code}"):
        text = f"{text} {_t(c, f'explain.finding.{code}')}"
    return Entry(str(fd["severity"]), _t(c, "severity." + str(fd["severity"])), title, text)


def _with_help(section: Section, c: Catalog) -> Section:
    key = f"explain.section.{section.id}"
    return replace(section, help=_t(c, key)) if c.has(key) else section


def _kpi(doc: Mapping[str, Any], c: Catalog, f: Fmt) -> Section:
    m = doc["metrics"]
    rows = (
        (_t(c, "report.kpi.net_profit"), f.num(m["net_profit"])),
        (_t(c, "report.kpi.profit_factor"), f.num(m["profit_factor"], 3)),
        (_t(c, "report.kpi.win_rate"), f.pct(m["win_rate"])),
        (_t(c, "report.kpi.payoff"), f.num(m["payoff_ratio"], 3)),
        (_t(c, "report.kpi.expectancy"), f.num(m["expectancy"])),
        (_t(c, "report.kpi.sharpe_trade"), f.num(m["sharpe_trade"], 3)),
        (_t(c, "report.kpi.sharpe_annual"), f.num(m["sharpe_annual"], 2)),
        (_t(c, "report.kpi.trades_per_year"), f.num(m["trades_per_year"], 1)),
        (_t(c, "report.kpi.max_drawdown"), f.num(m["max_drawdown"])),
        (_t(c, "report.kpi.max_drawdown_pct"), f.pct(_ratio(m["max_drawdown_pct"]))),
        (_t(c, "report.kpi.cagr"), f.pct(_ratio(m["cagr_pct"]))),
        (_t(c, "report.kpi.longest_losing_streak"), f.integer(m["longest_losing_streak"])),
    )
    return Section("kpi", _t(c, "report.section.kpi"), tables=(Table((), rows),))


def _ratio(pct_value: object) -> object:
    if pct_value is None:
        return "NaN"
    return number(pct_value) / 100.0


def _barrier_tag(b: Mapping[str, Any]) -> str:
    if not b["evaluated"]:
        return "not_evaluated"
    if b["triggered"]:
        return "triggered"
    if b["indecision"]:
        return "indecision"
    return "passed"


def barrier_tag(b: Mapping[str, Any]) -> str:
    """Étiquette de statut d'une barrière du document (public pour l'attestation)."""
    return _barrier_tag(b)


def _barrier_status(b: Mapping[str, Any], c: Catalog) -> str:
    return _t(c, f"report.status.{_barrier_tag(b)}")


def _barrieres(doc: Mapping[str, Any], c: Catalog, f: Fmt) -> Section:
    headers = (
        _t(c, "report.col.barrier"),
        _t(c, "report.col.value"),
        _t(c, "report.col.threshold"),
        _t(c, "report.col.band"),
        _t(c, "report.col.status"),
    )
    rows = tuple(
        (
            _t(c, str(b["message_key"])),
            f.num(b["value"], 3) if b["value"] is not None else _t(c, "report.na"),
            f"{'<' if b['sense'] == 'below' else '≥'} {f.num(b['threshold'], 3)}",
            f"[{f.num(b['band_low'], 3)} ; {f.num(b['band_high'], 3)}]",
            _barrier_status(b, c),
        )
        for b in doc["verdict"]["barriers"]
    )
    tags = tuple(_barrier_tag(b) for b in doc["verdict"]["barriers"])
    return Section(
        "barrieres",
        _t(c, "report.section.barrieres"),
        (_t(c, "report.barrier_intro"),),
        (Table(headers, rows, tags),),
    )


def _constats(doc: Mapping[str, Any], c: Catalog, critical_only: bool) -> Section:
    findings = _sorted_findings(doc["findings"])
    if critical_only:
        findings = [fd for fd in findings if fd["severity"] in CRITICAL]
    entries = tuple(_entry(c, fd) for fd in findings)
    sid = "constats_critiques" if critical_only else "constats_complets"
    paragraphs = () if entries else (_t(c, "report.no_findings"),)
    return Section(sid, _t(c, f"report.section.{sid}"), paragraphs, entries=entries)


def _entry(c: Catalog, fd: Mapping[str, Any]) -> Entry:
    return Entry(
        str(fd["severity"]),
        _t(c, "severity." + str(fd["severity"])),
        str(fd["code"]),
        _finding_text(c, fd),
    )


def _sharpe(doc: Mapping[str, Any], c: Catalog, f: Fmt) -> Section:
    s = doc["significance"]
    d = s["dsr"]
    rows = (
        (_t(c, "report.psr"), f.num(s["psr"], 4)),
        (_t(c, "report.dsr"), f.num(d["dsr"], 4)),
        (_t(c, "report.sr0"), f.num(d["sr0"], 4)),
        (_t(c, "report.n_trials"), f.integer(d["n_trials"])),
        (_t(c, "report.var_sr"), f.num(d["var_sr"], 6)),
        (_t(c, "report.variance_source"), _t(c, f"report.variance.{d['variance_source']}")),
    )
    return Section(
        "sharpe_degonfle",
        _t(c, "report.section.sharpe_degonfle"),
        (_t(c, "report.sharpe_intro"),),
        (Table((), rows),),
    )


def _sensibilite(doc: Mapping[str, Any], c: Catalog, f: Fmt) -> Section:
    s = doc["significance"]["sensitivity"]
    headers = (_t(c, "report.col.n_trials"), _t(c, "report.col.dsr"))
    rows = tuple((f.integer(p["n_trials"]), f.num(p["dsr"], 4)) for p in s["points"])
    tip = s["tipping_n_trials"]
    if s["beyond_grid"]:
        sentence = _t(c, "report.tipping_beyond", n=f.integer(s["points"][-1]["n_trials"]))
    elif tip == 0:
        sentence = _t(c, "report.tipping_never")
    else:
        sentence = _t(c, "report.tipping", n=f.integer(tip), threshold=f.num(s["threshold"], 2))
    threshold = number(s["threshold"])
    chart = Chart(
        tuple(
            Point(f.integer(p["n_trials"]), max(0.0, min(1.0, number(p["dsr"]))),
                  f.num(p["dsr"], 3))
            for p in s["points"]
        ),
        threshold,
        f"DSR {f.num(threshold, 2)}",
        decimal=c.decimal,
    )
    tags = tuple("neg" if number(p["dsr"]) < threshold else "" for p in s["points"])
    return Section(
        "sensibilite_essais",
        _t(c, "report.section.sensibilite_essais"),
        (sentence,),
        (Table(headers, rows, tags),),
        chart=chart,
    )


def _triplet(f: Fmt, a: object, b: object, c: object, digits: int) -> str:
    return f"{f.num(a, digits)} / {f.num(b, digits)} / {f.num(c, digits)}"


def _monte_carlo(doc: Mapping[str, Any], c: Catalog, f: Fmt) -> Section:
    r = doc["resampling"]
    b, p, n = r["bootstrap"], r["permutation"], r["null"]
    rows_b = (
        (_t(c, "report.mc.method"), _t(c, f"report.bootstrap.{b['method']}")),
        (_t(c, "report.mc.block_length"), f.num(b["block_length"], 2)),
        (
            _t(c, "report.mc.pf_interval"),
            _triplet(f, b["profit_factor_p05"], b["profit_factor_p50"], b["profit_factor_p95"], 3),
        ),
        (
            _t(c, "report.mc.net_interval"),
            _triplet(f, b["net_profit_p05"], b["net_profit_p50"], b["net_profit_p95"], 2),
        ),
        (
            _t(c, "report.mc.dd_quantiles"),
            _triplet(f, b["max_drawdown_p50"], b["max_drawdown_p95"], b["max_drawdown_p99"], 2),
        ),
    )
    rows_p = (
        (_t(c, "report.mc.observed_dd"), f.num(p["observed_drawdown"])),
        (_t(c, "report.mc.dd_percentile"), f.num(p["drawdown_percentile"], 1)),
        (
            _t(c, "report.mc.dd_perm_quantiles"),
            f"{f.num(p['drawdown_p50'])} / {f.num(p['drawdown_p95'])}",
        ),
    )
    rows_n = (
        (_t(c, "report.mc.p0"), f.pct(n["p0"])),
        (_t(c, "report.mc.p_value"), f.num(n["p_value"], 4)),
        (
            _t(c, "report.mc.null_quantiles"),
            f"{f.num(n['null_net_p50'])} / {f.num(n['null_net_p95'])}",
        ),
    )
    paragraphs = (_t(c, "report.mc.intro"), _t(c, "resample.null_empirical", p0=number(n["p0"])))
    return Section(
        "monte_carlo",
        _t(c, "report.section.monte_carlo"),
        paragraphs,
        (Table((), rows_b), Table((), rows_p), Table((), rows_n)),
    )


def _regimes(doc: Mapping[str, Any], c: Catalog, f: Fmt) -> Section:
    r = doc["regimes"]
    headers = (
        _t(c, "report.col.regime"),
        _t(c, "report.col.n"),
        _t(c, "report.col.net"),
        _t(c, "report.col.pf"),
        _t(c, "report.col.win_rate"),
        _t(c, "report.col.share"),
    )
    rows = tuple(
        (
            _t(c, f"regimes.{s['label']}"),
            f.integer(s["n"]),
            f.num(s["net_profit"]),
            f.num(s["profit_factor"], 3),
            f.pct(s["win_rate"]),
            f.pct(s["share_of_net"]),
        )
        for s in r["stats"]
    )
    q_headers = (
        _t(c, "report.col.quarter"),
        _t(c, "report.col.n"),
        _t(c, "report.col.net"),
        _t(c, "report.col.pf"),
    )
    q_rows = tuple(
        (
            _t(c, "period.quarter", year=q["year"], quarter=q["quarter"]),
            f.integer(q["n"]),
            f.num(q["net_profit"]),
            f.num(q["profit_factor"], 3),
        )
        for q in doc["quarters"]
    )
    intro = _t(
        c,
        "report.regimes_method",
        method=_t(c, f"regimes.{r['method']}"),
        unclassified=f.integer(r["n_unclassified"]),
    )
    tags = tuple(_neg(s["net_profit"]) for s in r["stats"])
    q_tags = tuple(_neg(q["net_profit"]) for q in doc["quarters"])
    return Section(
        "regimes",
        _t(c, "report.section.regimes"),
        (intro,),
        (Table(headers, rows, tags), Table(q_headers, q_rows, q_tags)),
    )


def _neg(value: object) -> str:
    v = number(value)
    return "neg" if not math.isnan(v) and v < 0 else ""


def _walkforward(doc: Mapping[str, Any], c: Catalog, f: Fmt) -> Section:
    wf = doc.get("walkforward")
    if wf is None:
        return Section(
            "walkforward", _t(c, "report.section.walkforward"), (_t(c, "report.wf_missing"),)
        )
    intro = _t(
        c,
        "report.wf_intro",
        protocol=_t(c, f"report.wf.{wf['protocol']}"),
        selection=_t(c, f"report.wf.{wf['selection']}"),
        folds=f.integer(wf["n_folds"]),
        candidates=f.integer(wf["n_candidates"]),
    )
    headers = (
        _t(c, "report.col.fold"),
        _t(c, "report.col.is_window"),
        _t(c, "report.col.oos_window"),
        _t(c, "report.col.selected"),
        _t(c, "report.col.is_net"),
        _t(c, "report.col.oos_net"),
        _t(c, "report.col.oos_trades"),
    )
    rows = tuple(
        (
            str(fd["index"]),
            f"{fd['is_start'][:10]} → {fd['is_end'][:10]}",
            f"{fd['oos_start'][:10]} → {fd['oos_end'][:10]}",
            str(fd["selected"]),
            f.num(fd["is_net"]),
            f.num(fd["oos_net"]),
            f.integer(fd["oos_trades"]),
        )
        for fd in wf["folds"]
    )
    tags = tuple(_neg(fd["oos_net"]) for fd in wf["folds"])
    summary = _t(
        c,
        "report.wf_summary",
        efficiency=f.num(wf["efficiency"], 3),
        positive=f.pct(wf["oos_positive_share"]),
        oos_net=f.num(wf["oos_net_total"]),
    )
    return Section(
        "walkforward",
        _t(c, "report.section.walkforward"),
        (intro, summary),
        (Table(headers, rows, tags),),
    )


def _detecteurs_prix(doc: Mapping[str, Any], c: Catalog) -> Section:
    if not doc["data"]["prices_provided"]:
        return Section(
            "detecteurs_prix",
            _t(c, "report.section.detecteurs_prix"),
            (_t(c, "report.prices_missing"),),
        )
    wanted = ("stop_geometry", "lookahead", "execution_realism")
    entries = tuple(
        _entry(c, fd)
        for fd in _sorted_findings(doc["findings"])
        if fd["source"] in {f"detector.{w}" for w in wanted}
    )
    mentioned = {str(fd["code"]) for fd in doc["findings"]}
    clean = tuple(w for w in wanted if w not in mentioned and f"{w}_skipped" not in mentioned)
    paragraphs = tuple(_t(c, "report.price_detector_clean", detector=w) for w in clean)
    return Section(
        "detecteurs_prix", _t(c, "report.section.detecteurs_prix"), paragraphs, entries=entries
    )


def _propfirm_sections(doc: Mapping[str, Any], c: Catalog, f: Fmt) -> dict[str, Section]:
    pf = doc.get("propfirm")
    titles = {
        k: _t(c, f"report.section.{k}")
        for k in ("propfirm_challenge", "propfirm_finance", "propfirm_economie")
    }
    if pf is None or not pf["evaluable"]:
        text = (
            _t(c, "report.propfirm_missing")
            if pf is None
            else _t(c, "report.propfirm_not_evaluable")
        )
        return {k: Section(k, title, (text,)) for k, title in titles.items()}
    intro = _t(
        c,
        "report.propfirm_intro",
        name=pf["ruleset_name"],
        as_of=pf["as_of"],
        n_paths=f.integer(pf["n_paths"]),
        scale=f.num(pf["pnl_scale"], 3),
        horizon=f.integer(pf["horizon_trading_days"]),
        carry=_t(c, f"report.carry.{pf['balance_carry']}"),
        block=f.num(pf["day_block_length"], 2),
        days=f.integer(pf["n_history_days"]),
    )
    headers = (
        _t(c, "report.col.phase"),
        _t(c, "report.col.horizon"),
        _t(c, "report.col.p_pass"),
        _t(c, "report.col.p_cumulative"),
        _t(c, "report.col.median_days"),
        _t(c, "report.col.causes"),
    )
    eval_rows: list[tuple[str, ...]] = []
    funded_rows: list[tuple[str, ...]] = []
    for ph in pf["phases"]:
        causes = ", ".join(
            f"{_t(c, 'report.cause.' + name)} {f.pct(share)}"
            for name, share in ph["fail_causes"]
            if number(share) > 0
        )
        horizon = f.integer(ph["horizon_trading_days"]) + (
            "" if ph["horizon_from_ruleset"] else " " + _t(c, "report.horizon_param")
        )
        row = (
            str(ph["name"]),
            horizon,
            f.pct(ph["pass_probability"]),
            f.pct(ph["cumulative_pass_probability"]),
            f.num(ph["median_days_to_pass"], 0),
            causes or "—",
        )
        (funded_rows if ph["funded"] else eval_rows).append(row)
    challenge = Section(
        "propfirm_challenge",
        titles["propfirm_challenge"],
        (intro,),
        (Table(headers, tuple(eval_rows)),),
    )
    finance = Section(
        "propfirm_finance",
        titles["propfirm_finance"],
        (
            _t(
                c,
                "report.propfirm_funded",
                ruin=f.pct(pf["funded_ruin_probability"]),
                payouts=f.num(pf["expected_payouts"]),
            ),
        ),
        (Table(headers, tuple(funded_rows)),),
    )
    econ_rows = (
        (_t(c, "report.pf.p_funded"), f.pct(pf["funded_probability"])),
        (_t(c, "report.pf.ruin"), f.pct(pf["funded_ruin_probability"])),
        (_t(c, "report.pf.expected_payouts"), f.num(pf["expected_payouts"])),
        (_t(c, "report.pf.median_gain"), f.num(pf["median_trader_gain"])),
        (_t(c, "report.pf.expected_net"), f.num(pf["expected_net_value"])),
    )
    economie = Section(
        "propfirm_economie",
        titles["propfirm_economie"],
        (_t(c, "report.propfirm_assumptions"),),
        (Table((), econ_rows),),
    )
    return {
        "propfirm_challenge": challenge,
        "propfirm_finance": finance,
        "propfirm_economie": economie,
    }


def _seuil_arret(doc: Mapping[str, Any], c: Catalog, f: Fmt) -> Section:
    b = doc["resampling"]["bootstrap"]
    m = doc["metrics"]
    rows = (
        (_t(c, "report.stop.observed"), f.num(m["max_drawdown"])),
        (_t(c, "report.stop.p95"), f.num(b["max_drawdown_p95"])),
        (_t(c, "report.stop.p99"), f.num(b["max_drawdown_p99"])),
    )
    return Section(
        "seuil_arret",
        _t(c, "report.section.seuil_arret"),
        (_t(c, "report.stop_intro"),),
        (Table((), rows),),
    )


def _conditions(doc: Mapping[str, Any], c: Catalog) -> Section:
    conds = doc["verdict"]["conditions"]
    items = tuple(
        c.text(str(cd["message_key"]), **{k: _param(v) for k, v in cd["params"].items()})
        for cd in conds
    )
    paragraphs = () if items else (_t(c, "report.no_conditions"),)
    return Section("conditions", _t(c, "report.section.conditions"), paragraphs, items=items)


def _portefeuille(doc: Mapping[str, Any], c: Catalog) -> Section:
    return Section(
        "portefeuille", _t(c, "report.section.portefeuille"), (_t(c, "report.portfolio_single"),)
    )


def _note_comite(doc: Mapping[str, Any], c: Catalog, f: Fmt) -> Section:
    v, m, s = doc["verdict"], doc["metrics"], doc["significance"]
    items = (
        _t(c, "report.note.decision", decision=_t(c, f"decision.{v['decision']}")),
        _t(
            c,
            "report.note.evidence",
            dsr=f.num(s["dsr"]["dsr"], 3),
            pf=f.num(m["profit_factor"], 2),
            n=f.integer(m["n"]),
        ),
        _t(
            c,
            "report.note.risk",
            dd=f.num(m["max_drawdown"]),
            dd95=f.num(doc["resampling"]["bootstrap"]["max_drawdown_p95"]),
        ),
        _t(c, "report.note.findings", blocking=v["counts"]["blocking"], major=v["counts"]["major"]),
    )
    return Section("note_comite", _t(c, "report.section.note_comite"), items=items)


def _portee(doc: Mapping[str, Any], c: Catalog) -> Section:
    data = doc["data"]
    items = [
        _t(c, "report.scope.closed_only"),
        _t(c, "report.scope.prices_yes" if data["prices_provided"] else "report.scope.prices_no"),
        _t(c, "report.scope.wf_yes" if doc.get("walkforward") else "report.scope.wf_no"),
        _t(c, "report.scope.propfirm_yes" if doc.get("propfirm") else "report.scope.propfirm_no"),
        _t(c, "report.scope.null"),
        _t(c, "report.scope.no_advice"),
    ]
    if doc["significance"]["dsr"]["variance_source"] == "lo_approx":
        items.append(_t(c, "report.scope.lo"))
    if data["ruin_index"] is not None:
        items.append(_t(c, "report.scope.ruin", index=int(data["ruin_index"]) + 1))
    return Section(
        "portee_et_limites", _t(c, "report.section.portee_et_limites"), items=tuple(items)
    )


def _pied(doc: Mapping[str, Any], c: Catalog, profile: Profile) -> Section:
    text = _t(
        c,
        "report.footer",
        engine=doc["engine_version"],
        method=doc["method_version"],
        seed=doc["seed"],
        fingerprint=doc["data"]["fingerprint"],
        schema=doc["schema_version"],
        profile=profile.code,
    )
    return Section(
        "pied",
        _t(c, "report.section.pied"),
        (text, _t(c, "report.reproducible"), _t(c, "report.not_advice")),
    )


def _day(stamp: object) -> str:
    """Date seule d'un horodatage ISO (l'en-tête garde l'heure)."""
    return str(stamp)[:10] if stamp else "—"


def build_view(
    document: Mapping[str, Any], catalog: Catalog, profile: Profile, *, system_name: str
) -> ReportView:
    """Construit la vue rendue, sections filtrées par le profil (ordre canonique)."""
    c, f = catalog, Fmt(catalog)
    propfirm = _propfirm_sections(document, c, f)
    builders = {
        "entete": lambda: _entete(document, c, f, system_name, profile),
        "verdict": lambda: _verdict(document, c, f),
        "en_clair": lambda: _en_clair(document, c, f),
        "kpi": lambda: _kpi(document, c, f),
        "barrieres": lambda: _barrieres(document, c, f),
        "constats_critiques": lambda: _constats(document, c, True),
        "constats_complets": lambda: _constats(document, c, False),
        "sharpe_degonfle": lambda: _sharpe(document, c, f),
        "sensibilite_essais": lambda: _sensibilite(document, c, f),
        "monte_carlo": lambda: _monte_carlo(document, c, f),
        "regimes": lambda: _regimes(document, c, f),
        "walkforward": lambda: _walkforward(document, c, f),
        "detecteurs_prix": lambda: _detecteurs_prix(document, c),
        "propfirm_challenge": lambda: propfirm["propfirm_challenge"],
        "propfirm_finance": lambda: propfirm["propfirm_finance"],
        "propfirm_economie": lambda: propfirm["propfirm_economie"],
        "seuil_arret": lambda: _seuil_arret(document, c, f),
        "conditions": lambda: _conditions(document, c),
        "portefeuille": lambda: _portefeuille(document, c),
        "note_comite": lambda: _note_comite(document, c, f),
        "portee_et_limites": lambda: _portee(document, c),
        "pied": lambda: _pied(document, c, profile),
    }
    sections = tuple(_with_help(builders[s](), c) for s in profile.sections)
    decision = str(document["verdict"]["decision"])
    data, counts = document["data"], document["verdict"]["counts"]
    facts = (
        (_t(c, "report.period"), f"{_day(data['first_open'])} → {_day(data['last_close'])}"),
        (
            _t(c, "report.n_trades"),
            f"{f.integer(data['n_usable'])} / {f.integer(data['n_trades'])}",
        ),
        (
            _t(c, "report.initial_balance"),
            f"{f.num(data['initial_balance'], 2)} {data['currency']}",
        ),
        (_t(c, "report.n_trials"), f.integer(document["n_trials"])),
    )
    return ReportView(
        lang=catalog.lang,
        title=_t(c, "report.title"),
        system_name=system_name,
        decision_code=decision,
        decision_label=_t(c, f"decision.{decision}"),
        human_review=bool(document["verdict"]["revue_humaine"]),
        profile_code=profile.code,
        profile_label=profile.label,
        sections=sections,
        review_label=_t(c, "report.human_review"),
        facts=facts,
        counts=tuple(
            (sev, _t(c, f"severity.{sev}"), int(counts[sev]))
            for sev in ("blocking", "major", "minor", "info")
        ),
        footer=_pied(document, c, profile).paragraphs[0],
        toc_label=_t(c, "report.toc"),
        brand_line=_t(c, "report.brand_line", version=str(document["engine_version"])),
        help_label=_t(c, "explain.how_to_read"),
        verdict_caption=_t(c, "report.section.verdict"),
    )
