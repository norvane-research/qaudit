# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mode lot : N systèmes audités en parallèle, correction de Benjamini-Hochberg
sur les p-values de la nulle sans edge, tableau de synthèse.

Chaque système est audité indépendamment avec la même graine : le résultat
d'un système ne dépend ni de l'ordre ni du nombre de processus. La correction
BH ne modifie aucun verdict individuel (mécanique, par système) : elle ajoute
une colonne « survit à BH » au niveau du portefeuille et compte les systèmes
dont la significativité ne tient pas une fois le nombre d'essais du
portefeuille pris en compte.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from html import escape
from pathlib import Path

import numpy as np

from qaudit.core.audit import AuditOptions, run_audit
from qaudit.core.errors import QauditError
from qaudit.core.stats import benjamini_hochberg
from qaudit.core.validate import validate
from qaudit.i18n import Catalog
from qaudit.io.document import Json, dumps, number, to_document
from qaudit.io.mapping import MappingStore, resolve_mapping
from qaudit.io.method import load_method
from qaudit.io.outputs import write_deliverables, write_document
from qaudit.io.profile import Profile
from qaudit.io.readers import read_table


@dataclass(frozen=True, slots=True)
class BatchTask:
    """Une tâche du lot : mêmes entrées et mêmes options qu'un audit unitaire
    (lecteur, correspondance E1 explicite ou mémorisée, options de simulation)."""

    name: str
    path: str
    initial_balance: float | None
    currency: str | None
    kind: str
    mapping_path: str | None
    cache_dir: str | None
    options: AuditOptions
    method_path: str | None


@dataclass(frozen=True, slots=True)
class BatchResult:
    documents: dict[str, Json]
    errors: dict[str, str]
    summary: Json


def audit_task(task: BatchTask) -> tuple[str, Json | None, str | None]:
    """Audite un fichier avec le même chemin d'ingestion qu'un audit unitaire ;
    toute erreur du moteur est rapportée par sa clé."""
    try:
        config = load_method(Path(task.method_path) if task.method_path else None)
        table = read_table(Path(task.path), task.kind)
        store = MappingStore(Path(task.cache_dir)) if task.cache_dir else MappingStore()
        mapping, origin = resolve_mapping(
            table, Path(task.mapping_path) if task.mapping_path else None, store
        )
        validation = validate(
            table,
            mapping,
            max_gap_days=config.max_gap_days,
            initial_balance=task.initial_balance,
            currency=task.currency,
        )
        if origin == "explicit":
            store.save(table.columns, mapping)
        result = run_audit(validation, config, task.options)
    except QauditError as exc:
        return task.name, None, exc.key
    return task.name, to_document(result), None


def summarize(documents: dict[str, Json], alpha: float) -> Json:
    """Tableau de synthèse et correction BH sur les p-values de la nulle."""
    names = sorted(documents)
    pvalues = np.array([number(documents[n]["resampling"]["null"]["p_value"]) for n in names])
    bh = benjamini_hochberg(pvalues, alpha) if names else None
    rows = []
    for i, name in enumerate(names):
        doc = documents[name]
        rows.append(
            {
                "system": name,
                "decision": doc["verdict"]["decision"],
                "revue_humaine": doc["verdict"]["revue_humaine"],
                "n_trades": doc["metrics"]["n"],
                "net_profit": doc["metrics"]["net_profit"],
                "profit_factor": doc["metrics"]["profit_factor"],
                "dsr": doc["significance"]["dsr"]["dsr"],
                "pf_p05": doc["resampling"]["bootstrap"]["profit_factor_p05"],
                "dd_percentile": doc["resampling"]["permutation"]["drawdown_percentile"],
                "null_p_value": doc["resampling"]["null"]["p_value"],
                "null_p_adjusted": _num(bh.adjusted[i]) if bh is not None else "NaN",
                "survives_bh": bool(bh.reject[i]) if bh is not None else False,
                "blocking": doc["verdict"]["counts"]["blocking"],
                "major": doc["verdict"]["counts"]["major"],
            }
        )
    decisions = [r["decision"] for r in rows]
    return {
        "schema": "qaudit.portfolio",
        "schema_version": "1.0",
        "n_systems": len(rows),
        "alpha": alpha,
        "n_tests": bh.n_tests if bh is not None else 0,
        "counts": {d: decisions.count(d) for d in ("GO", "GO_CONDITIONAL", "NO_GO")},
        "n_survive_bh": sum(1 for r in rows if r["survives_bh"]),
        "systems": rows,
    }


def _num(value: float) -> float | str:
    if math.isnan(value):
        return "NaN"
    return float(f"{value:.12g}")


def run_batch(
    paths: Sequence[Path],
    *,
    options: AuditOptions,
    jobs: int,
    alpha: float,
    initial_balance: float | None = None,
    currency: str | None = None,
    kind: str = "auto",
    mapping_path: Path | None = None,
    cache_dir: Path | None = None,
    method_path: Path | None = None,
) -> BatchResult:
    """Audite chaque fichier (en parallèle si ``jobs > 1``) et synthétise."""
    tasks = [
        BatchTask(
            p.stem,
            str(p),
            initial_balance,
            currency,
            kind,
            str(mapping_path) if mapping_path else None,
            str(cache_dir) if cache_dir else None,
            options,
            str(method_path) if method_path else None,
        )
        for p in paths
    ]
    documents: dict[str, Json] = {}
    errors: dict[str, str] = {}
    if jobs > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            outcomes = list(pool.map(audit_task, tasks))
    else:
        outcomes = [audit_task(t) for t in tasks]
    for name, doc, error in outcomes:
        if doc is not None:
            documents[name] = doc
        else:
            errors[name] = error or "internal"
    return BatchResult(documents, errors, summarize(documents, alpha))


def portfolio_html(summary: Json, catalog: Catalog) -> str:
    """Tableau de synthèse HTML (autonome, déterministe)."""

    def t(key: str, **params: object) -> str:
        return catalog.text(key, **params)

    headers = [
        t("batch.col.system"),
        t("batch.col.decision"),
        t("batch.col.n"),
        t("batch.col.net"),
        t("batch.col.pf"),
        t("batch.col.dsr"),
        t("batch.col.pf_p05"),
        t("batch.col.dd_pct"),
        t("batch.col.p"),
        t("batch.col.p_adj"),
        t("batch.col.bh"),
        t("batch.col.blocking"),
        t("batch.col.major"),
    ]
    cells = [
        [
            r["system"],
            t(f"decision.{r['decision']}") + (" E3" if r["revue_humaine"] else ""),
            str(r["n_trades"]),
            _fmt(r["net_profit"], 0),
            _fmt(r["profit_factor"], 2),
            _fmt(r["dsr"], 3),
            _fmt(r["pf_p05"], 3),
            _fmt(r["dd_percentile"], 1),
            _fmt(r["null_p_value"], 4),
            _fmt(r["null_p_adjusted"], 4),
            t("batch.yes") if r["survives_bh"] else t("batch.no"),
            str(r["blocking"]),
            str(r["major"]),
        ]
        for r in summary["systems"]
    ]
    intro = t(
        "batch.intro",
        n=summary["n_systems"],
        alpha=summary["alpha"],
        survive=summary["n_survive_bh"],
        go=summary["counts"]["GO"],
        cond=summary["counts"]["GO_CONDITIONAL"],
        nogo=summary["counts"]["NO_GO"],
    )
    rows_html = "\n".join(
        "<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>" for row in cells
    )
    return (
        f'<!DOCTYPE html>\n<html lang="{catalog.lang}"><head><meta charset="utf-8">'
        f"<title>{escape(t('batch.title'))}</title><style>body{{font-family:Georgia,serif;"
        "max-width:1100px;margin:2rem auto}table{border-collapse:collapse;font-size:.9rem}"
        "td,th{border:1px solid #ccc;padding:.3rem .5rem}th{background:#f2f2f2}</style></head>"
        f"<body><h1>{escape(t('batch.title'))}</h1><p>{escape(intro)}</p><table><tr>"
        + "".join(f"<th>{escape(h)}</th>" for h in headers)
        + f"</tr>\n{rows_html}\n</table></body></html>\n"
    )


def _fmt(value: object, digits: int) -> str:
    v = number(value)
    if math.isnan(v):
        return "n/a"
    if math.isinf(v):
        return "inf"
    return f"{v:.{digits}f}"


def write_batch(result: BatchResult, out_dir: Path, catalog: Catalog, profile: Profile) -> Path:
    """Archive chaque document, écrit les livrables par système et la synthèse."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, doc in sorted(result.documents.items()):
        write_document(doc, out_dir, name)
        write_deliverables(doc, out_dir, catalog, profile, system_name=name)
    (out_dir / "portfolio.json").write_bytes(dumps(result.summary).encode("utf-8"))
    summary_html = out_dir / "portfolio.html"
    summary_html.write_bytes(portfolio_html(result.summary, catalog).encode("utf-8"))
    return summary_html
