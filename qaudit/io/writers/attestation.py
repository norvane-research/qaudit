# SPDX-License-Identifier: AGPL-3.0-or-later
"""Attestation de validation : document émis uniquement sur un verdict GO, à
partir de l'archive JSON et d'une entrée du registre (référence, date).

Elle atteste un fait borné — ce fichier (empreinte), cette méthode (version),
ce jour — et rien d'autre ; ses limites sont imprimées. Rendue par les mêmes
écrivains HTML et PDF que le rapport (même charte), sans recalcul : tout vient
du document archivé et du registre.

La page publique de vérification (``registry_page``) liste les attestations
émises avec leur empreinte, sans jamais le nom du titulaire.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

from qaudit.i18n import Catalog
from qaudit.io.profile import Profile
from qaudit.io.registry import Entry
from qaudit.io.writers.render import Fmt, ReportView, Section, Table, barrier_tag

_LIMITS = ("future", "advice", "data", "truncation", "revision")


def attestation_view(
    document: Mapping[str, Any], entry: Entry, catalog: Catalog, profile: Profile
) -> ReportView:
    """Vue rendue de l'attestation (titre, faits, sections) pour ``render_html``
    et ``render_pdf``."""
    c, f = catalog, Fmt(catalog)
    data = document["data"]
    verdict = document["verdict"]
    period = f"{_day(data['first_open'])} → {_day(data['last_close'])}"
    transfer_key = "attestation.transferable_" + ("yes" if entry.transferable else "no")
    who = entry.issuer or c.text("attestation.the_auditor")
    declaration = Section(
        "declaration",
        c.text("attestation.section.declaration"),
        (
            c.text("attestation.declaration", issuer=who, system=entry.system_name,
                   method=entry.method_version, issued_on=entry.issued_on),
            c.text("attestation.scope"),
        ),
    )
    rows = [
        (c.text("attestation.field.reference"), entry.reference),
        (c.text("attestation.field.issued_on"), entry.issued_on),
    ]
    if entry.holder:
        rows.append((c.text("attestation.field.holder"), entry.holder))
    rows += [
        (c.text("report.system"), entry.system_name),
        (c.text("report.period"), period),
        (
            c.text("report.n_trades"),
            f"{f.integer(data['n_usable'])} / {f.integer(data['n_trades'])}",
        ),
        (c.text("report.n_trials"), f.integer(document["n_trials"])),
        (c.text("attestation.field.capital"),
         f"{f.num(data['initial_balance'], 2)} {data['currency']}"),
        (c.text("report.method_version"), entry.method_version),
        (c.text("report.engine_version"), entry.engine_version),
        (c.text("report.fingerprint"), entry.fingerprint),
        (c.text("attestation.field.transferable"), c.text(transfer_key)),
    ]
    objet = Section("objet", c.text("attestation.section.objet"), tables=(Table((), tuple(rows)),))
    headers = (c.text("report.col.barrier"), c.text("report.col.value"),
               c.text("report.col.threshold"), c.text("report.col.status"))
    b_rows = [
        (
            c.text(str(b["message_key"])),
            f.num(b["value"], 3),
            f"{'<' if b['sense'] == 'below' else '≥'} {f.num(b['threshold'], 3)}",
            c.text(f"report.status.{barrier_tag(b)}"),
        )
        for b in verdict["barriers"]
    ]
    tags = [barrier_tag(b) for b in verdict["barriers"]]
    counts = verdict["counts"]
    critical = int(counts["blocking"]) + int(counts["major"])
    b_rows.append((
        c.text("attestation.integrity"), c.text("attestation.integrity_value", n=critical),
        "0", c.text("report.status.passed"),
    ))
    tags.append("passed")
    barrieres = Section(
        "barrieres", c.text("attestation.section.barrieres"),
        (c.text("attestation.barriers_intro"),), (Table(headers, tuple(b_rows), tuple(tags)),),
    )
    limites = Section(
        "limites", c.text("attestation.section.limites"),
        items=tuple(c.text(f"attestation.limits.{k}") for k in _LIMITS),
    )
    verification = Section(
        "verification", c.text("attestation.section.verification"),
        (
            c.text("attestation.verify", reference=entry.reference, fingerprint=entry.fingerprint),
            c.text("attestation.verify_command", reference=entry.reference),
        ),
    )
    pied = Section(
        "pied", c.text("report.section.pied"),
        (c.text("attestation.footer", reference=entry.reference, issued_on=entry.issued_on,
                engine=entry.engine_version, method=entry.method_version,
                fingerprint=entry.fingerprint),),
    )
    return ReportView(
        lang=c.lang,
        title=c.text("attestation.title"),
        system_name=entry.system_name,
        decision_code="GO",
        decision_label=c.text("decision.GO"),
        human_review=False,
        profile_code=profile.code,
        profile_label=profile.label,
        sections=(declaration, objet, barrieres, limites, verification, pied),
        review_label="",
        facts=(
            (c.text("attestation.field.reference"), entry.reference),
            (c.text("attestation.field.issued_on"), entry.issued_on),
            (c.text("report.method_version"), entry.method_version),
            (c.text("report.n_trades"), f.integer(data["n_usable"])),
        ),
        counts=(),
        footer="",
        toc_label="",
        brand_line=c.text("report.brand_line", version=entry.engine_version),
        help_label="",
        verdict_caption=c.text("attestation.caption"),
    )


def _day(stamp: object) -> str:
    return str(stamp)[:10] if stamp else "—"


_PAGE_CSS = """
body{margin:0;background:#f6f4ef;color:#1f2933;font-family:"Segoe UI",system-ui,Arial,sans-serif;
font-size:15px;line-height:1.5}
.page{max-width:1080px;margin:0 auto;padding:28px}
h1{font-family:Georgia,serif;font-weight:normal;color:#0b1f3a;font-size:2rem;margin:16px 0 6px;
border-top:6px solid #0b1f3a;padding-top:18px}
p.lead{color:#5f6b7a;max-width:70ch}
table{border-collapse:separate;border-spacing:0;width:100%;background:#fff;border:1px solid #e4dfd4;
border-radius:10px;overflow:hidden;font-size:.92rem;margin-top:16px}
th,td{padding:.55rem .7rem;text-align:left;border-top:1px solid #eef1f6;vertical-align:top}
tr:first-child>*{border-top:none}
th{background:#eef1f6;color:#0b1f3a;font-size:.76rem;text-transform:uppercase;letter-spacing:.06em}
td.fp{font-family:Consolas,"Courier New",monospace;font-size:.78rem;overflow-wrap:anywhere}
.go{display:inline-block;background:#e8f5ec;color:#166534;border-radius:999px;padding:.1rem .6rem;
font-weight:600;font-size:.78rem}
footer{color:#5f6b7a;font-size:.82rem;margin-top:24px}
"""


def registry_page(entries: Sequence[Entry], catalog: Catalog) -> str:
    """Page HTML publique : référence, date, système, méthode, verdict, empreinte."""
    c = catalog
    head = "".join(
        f"<th>{escape(c.text(f'attestation.registry.col.{k}'))}</th>"
        for k in ("reference", "issued_on", "system", "method", "decision", "fingerprint")
    )
    rows = "".join(
        f"<tr><td><b>{escape(e.reference)}</b></td><td>{escape(e.issued_on)}</td>"
        f"<td>{escape(e.system_name)}</td><td>{escape(e.method_version)}</td>"
        f'<td><span class="go">{escape(c.text(f"decision.{e.decision}"))}</span></td>'
        f'<td class="fp">{escape(e.fingerprint)}</td></tr>'
        for e in sorted(entries, key=lambda e: e.reference)
    )
    return (
        f'<!DOCTYPE html>\n<html lang="{escape(c.lang)}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(c.text('attestation.registry.title'))}</title>\n"
        f"<style>{_PAGE_CSS}</style>\n</head>\n<body>\n<div class=\"page\">\n"
        f"<h1>{escape(c.text('attestation.registry.title'))}</h1>\n"
        f'<p class="lead">{escape(c.text("attestation.registry.intro"))}</p>\n'
        f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>\n"
        f"<footer>{escape(c.text('attestation.registry.footer', n=len(entries)))}</footer>\n"
        "</div>\n</body>\n</html>\n"
    )
