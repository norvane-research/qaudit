# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rapport HTML autonome (CSS en ligne, aucune ressource externe, aucune police
téléchargée), déterministe : mêmes octets pour une même vue.

Charte : identité éditoriale « cabinet d'audit » — titres en serif, corps en
sans-serif système, encre marine et filet or ; le verdict et les statuts
portent des couleurs sémantiques fixes (GO vert, sous conditions ambre, NO-GO
rouge). Le contenu vient exclusivement de la ``ReportView`` : l'écrivain ne
calcule rien et n'invente aucun texte.
"""

from __future__ import annotations

import re
from html import escape

from qaudit.io.writers.render import Chart, Entry, ReportView, Section, Table

_SPACES = "\u202f\u00a0 "  # espaces fines / insécables des nombres formatés
_NUMERIC = re.compile(
    "^[" + "\u2212" + r"\-+]?[\d" + _SPACES + r"]+([.,]\d+)?([" + _SPACES + "]?%)?$"
)

_CSS = """
:root{--ink:#0b1f3a;--ink-2:#17335d;--gold:#b8860b;--gold-2:#e2c26a;--paper:#f6f4ef;
--card:#fff;--text:#1f2933;--muted:#5f6b7a;--rule:#e4dfd4;--rule-2:#eef1f6;
--go:#166534;--go-bg:#e8f5ec;--cond:#a15c07;--cond-bg:#fdf3e1;--nogo:#991b1b;--nogo-bg:#fdecec;
--blocking:#991b1b;--blocking-bg:#fdecec;--major:#c2410c;--major-bg:#fff0e6;
--minor:#8a6d00;--minor-bg:#fff8db;--info:#475569;--info-bg:#eef2f7;
--serif:Georgia,"Palatino Linotype","Book Antiqua",Cambria,serif;
--sans:"Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif;
--mono:Consolas,"Cascadia Mono","Courier New",monospace}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--text);font-family:var(--sans);
font-size:15px;line-height:1.55;font-variant-numeric:tabular-nums}
a{color:var(--ink-2);text-decoration:none}a:hover{text-decoration:underline}
.page{max-width:1080px;margin:0 auto;padding:28px 28px 72px}
.mast{display:grid;grid-template-columns:1.4fr 1fr;gap:24px;align-items:stretch;
border-top:6px solid var(--ink);padding-top:22px}
.brand{font-family:var(--serif);font-size:1.05rem;letter-spacing:.14em;text-transform:uppercase;
color:var(--ink);display:flex;align-items:center;gap:10px}
.brand i{display:inline-block;width:26px;height:26px;border:2px solid var(--gold);
border-radius:50%;position:relative}
.brand i:after{content:"";position:absolute;inset:6px;background:var(--ink);border-radius:50%}
.brand-line{color:var(--muted);font-size:.86rem;margin-top:4px}
h1{font-family:var(--serif);font-weight:normal;font-size:2.35rem;line-height:1.12;color:var(--ink);
margin:26px 0 8px}
.subject{font-size:1.05rem;color:var(--muted)}.subject b{color:var(--text);font-weight:600}
.verdict-panel{border-radius:14px;padding:22px 24px;border:1px solid var(--vc);
background:var(--vbg);display:flex;flex-direction:column;justify-content:center;gap:10px}
.verdict-panel .k{font-size:.78rem;letter-spacing:.14em;text-transform:uppercase;color:var(--vc);
font-weight:600}
.verdict-panel .d{font-family:var(--serif);font-size:2rem;line-height:1.1;color:var(--vc)}
.verdict-panel .counts{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
.GO{--vc:var(--go);--vbg:var(--go-bg)}.GO_CONDITIONAL{--vc:var(--cond);--vbg:var(--cond-bg)}
.NO_GO{--vc:var(--nogo);--vbg:var(--nogo-bg)}
.review{display:inline-flex;align-items:center;gap:8px;background:var(--ink);color:#fff;
border-radius:8px;padding:8px 12px;font-size:.88rem;margin-top:4px}
.review:before{content:"E3";font-family:var(--mono);background:var(--gold);color:var(--ink);
border-radius:4px;padding:1px 6px;font-weight:700}
.facts{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--rule);
border:1px solid var(--rule);border-radius:12px;overflow:hidden;margin:26px 0 10px}
.facts div{background:var(--card);padding:14px 16px}
.facts .l{font-size:.74rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}
.facts .v{font-family:var(--serif);font-size:1.12rem;color:var(--ink);margin-top:3px;
word-break:keep-all}
.toc{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;margin:14px 0 6px;
font-size:.86rem}
.toc .l{color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-size:.72rem;
margin-right:4px}
.toc a{color:var(--ink-2);border-bottom:1px solid transparent}.toc a:hover{border-color:var(--gold);
text-decoration:none}
section.card{background:var(--card);border:1px solid var(--rule);border-radius:14px;
padding:22px 26px 20px;margin:18px 0;break-inside:avoid}
h2{font-family:var(--serif);font-weight:normal;font-size:1.42rem;color:var(--ink);margin:0 0 12px;
padding-bottom:10px;border-bottom:1px solid var(--rule);display:flex;align-items:center;gap:12px}
h2:before{content:"";width:18px;height:3px;background:var(--gold);border-radius:2px;flex:none}
p{margin:.55rem 0}p.lead{color:var(--muted)}
ul{padding-left:1.15rem;margin:.5rem 0}li{margin:.3rem 0}
.alert li{list-style:none;position:relative;padding-left:1.1rem}
.alert li:before{content:"";position:absolute;left:0;top:.55em;width:8px;height:8px;
border-radius:50%;background:var(--nogo)}
table{border-collapse:separate;border-spacing:0;width:100%;margin:.7rem 0;font-size:.92rem;
border:1px solid var(--rule);border-radius:10px;overflow:hidden}
th,td{padding:.5rem .7rem;text-align:left;vertical-align:top;border-top:1px solid var(--rule-2)}
tr:first-child>*{border-top:none}
th{background:var(--rule-2);color:var(--ink);font-weight:600;font-size:.78rem;text-transform:uppercase;
letter-spacing:.06em}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
table.grid tbody tr:nth-child(even) td{background:#fbfaf7}
table.kv td:first-child{color:var(--muted);width:42%;font-size:.88rem}
table.kv td:last-child{font-weight:500;overflow-wrap:anywhere}
tr.neg td{color:var(--nogo)}tr.neg td:first-child{color:var(--nogo)}
.chip{display:inline-block;border-radius:999px;padding:.12rem .62rem;font-size:.76rem;
font-weight:600;letter-spacing:.03em;white-space:nowrap;border:1px solid transparent;
background:var(--cbg);color:var(--cc);border-color:color-mix(in srgb,var(--cc) 25%,transparent)}
.chip.passed{--cc:var(--go);--cbg:var(--go-bg)}
.chip.triggered{--cc:var(--nogo);--cbg:var(--nogo-bg)}
.chip.indecision{--cc:var(--cond);--cbg:var(--cond-bg)}
.chip.not_evaluated{--cc:var(--info);--cbg:var(--info-bg)}
.chip.blocking{--cc:var(--blocking);--cbg:var(--blocking-bg)}
.chip.major{--cc:var(--major);--cbg:var(--major-bg)}
.chip.minor{--cc:var(--minor);--cbg:var(--minor-bg)}.chip.info{--cc:var(--info);--cbg:var(--info-bg)}
.chip.count{--cc:var(--muted);--cbg:#fff;font-weight:500}
.chip.count b{color:var(--text);margin-left:4px}
.chip.zero{opacity:.55}
.kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(196px,1fr));gap:12px;
margin:.6rem 0}
.kpi{border:1px solid var(--rule);border-radius:10px;padding:12px 14px 10px;background:#fff}
.kpi .l{font-size:.74rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
min-height:2.2em;display:flex;align-items:flex-end}
.kpi .v{font-family:var(--serif);font-size:1.55rem;color:var(--ink);margin-top:6px;line-height:1.15}
.finding{display:grid;grid-template-columns:auto 1fr;gap:6px 14px;align-items:start;
padding:11px 14px;border-radius:10px;margin:8px 0;background:var(--fbg);
border-left:4px solid var(--fc)}
.finding .code{font-family:var(--mono);font-size:.8rem;color:var(--muted);grid-column:2;
margin-top:-2px}
.finding .txt{grid-column:2;margin:0}
.finding.blocking{--fc:var(--blocking);--fbg:var(--blocking-bg)}
.finding.major{--fc:var(--major);--fbg:var(--major-bg)}
.finding.minor{--fc:var(--minor);--fbg:var(--minor-bg)}
.finding.info{--fc:var(--info);--fbg:var(--info-bg)}
.finding.passed{--fc:var(--go);--fbg:var(--go-bg)}
.finding.triggered{--fc:var(--nogo);--fbg:var(--nogo-bg)}
.finding.indecision{--fc:var(--cond);--fbg:var(--cond-bg)}
.finding.not_evaluated{--fc:var(--info);--fbg:var(--info-bg)}
.help{background:var(--rule-2);border-left:3px solid var(--gold);border-radius:8px;
padding:10px 14px;margin:2px 0 14px;color:var(--ink-2);font-size:.9rem;line-height:1.5}
.help b{display:block;font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;
color:var(--muted);margin-bottom:3px}
#en_clair{background:#fffdf6;border-color:#e6d7a6}
#en_clair p{font-size:1.02rem}
#en_clair .finding .code{font-family:var(--serif);font-size:1.05rem;color:var(--ink);margin-top:0}
#en_clair .closing{margin-top:14px;padding-top:12px;border-top:1px solid var(--rule)}
figure{margin:.8rem 0 .4rem}figure svg{width:100%;height:auto;display:block}
figcaption{font-size:.8rem;color:var(--muted);margin-top:4px}
#pied p{font-family:var(--mono);font-size:.8rem;color:var(--muted);overflow-wrap:anywhere}
@media (max-width:760px){.mast,.facts{grid-template-columns:1fr}.page{padding:18px 14px 48px}
h1{font-size:1.8rem}table.kv td:first-child{width:auto}}
@media print{@page{margin:16mm}body{background:#fff;font-size:11.5px}
.page{max-width:none;padding:0}.toc{display:none}
section.card{border:none;padding:0 0 6px;margin:14px 0;break-inside:avoid;
border-bottom:1px solid var(--rule)}
.verdict-panel,.facts div,.kpi,.finding,th{-webkit-print-color-adjust:exact;
print-color-adjust:exact}}
"""


def _cell(text: str, tag: str = "td", numeric: bool | None = None) -> str:
    is_num = bool(_NUMERIC.match(text)) if numeric is None else numeric
    attr = ' class="n"' if is_num else ""
    return f"<{tag}{attr}>{escape(text)}</{tag}>"


def _numeric_columns(table: Table) -> list[bool]:
    """Une colonne est numérique si toutes ses cellules non vides le sont
    (l'en-tête suit alors l'alignement à droite des valeurs)."""
    n_cols = max((len(r) for r in (*table.rows, table.headers)), default=0)
    flags = []
    for j in range(n_cols):
        cells = [r[j] for r in table.rows if j < len(r) and r[j]]
        flags.append(bool(cells) and all(_NUMERIC.match(c) for c in cells))
    return flags


def _chip(tag: str, text: str) -> str:
    return f'<span class="chip {escape(tag)}">{escape(text)}</span>'


def _is_kv(table: Table) -> bool:
    return not table.headers and bool(table.rows) and all(len(r) == 2 for r in table.rows)


def _table(table: Table, section_id: str) -> str:
    if _is_kv(table):
        if section_id == "kpi":
            return _kpis(table)
        rows = "".join(
            f"<tr>{_cell(k)}<td>{escape(v)}</td></tr>" for k, v in table.rows
        )
        return f'<table class="kv"><tbody>{rows}</tbody></table>'
    parts = ['<table class="grid">']
    numeric = _numeric_columns(table)
    if table.headers:
        head = "".join(_cell(h, "th", numeric[j]) for j, h in enumerate(table.headers))
        parts.append(f"<thead><tr>{head}</tr></thead>")
    body = []
    status_column = section_id == "barrieres"
    for i, row in enumerate(table.rows):
        tag = table.tags[i] if i < len(table.tags) else ""
        cells = list(row)
        rendered = [_cell(c, "td", numeric[j]) for j, c in enumerate(cells)]
        if status_column and tag and rendered:
            rendered[-1] = f"<td>{_chip(tag, cells[-1])}</td>"
        klass = f' class="{escape(tag)}"' if tag == "neg" else ""
        body.append(f"<tr{klass}>" + "".join(rendered) + "</tr>")
    parts.append("<tbody>" + "".join(body) + "</tbody></table>")
    return "".join(parts)


def _kpis(table: Table) -> str:
    cards = "".join(
        f'<div class="kpi"><div class="l">{escape(k)}</div>'
        f'<div class="v">{escape(v)}</div></div>'
        for k, v in table.rows
    )
    return f'<div class="kpis">{cards}</div>'


def _entry(entry: Entry) -> str:
    return (
        f'<div class="finding {escape(entry.tag)}">{_chip(entry.tag, entry.label)}'
        f'<div class="code">{escape(entry.code)}</div>'
        f'<p class="txt">{escape(entry.text)}</p></div>'
    )


def _chart(chart: Chart) -> str:
    """Barres SVG (déterministe, sans script). Une barre par point ; les points
    sous le seuil prennent la couleur d'alerte ; le seuil est une ligne pointillée."""
    if not chart.points:
        return ""
    w, h, left, top, bottom = 640, 210, 64, 22, 34
    n = len(chart.points)
    inner_w, inner_h = w - left - 12, h - top - bottom
    slot = inner_w / n
    bar_w = min(58.0, slot * 0.58)
    parts = [
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img">',
        (
            f'<line x1="{left}" y1="{top + inner_h}" x2="{w - 12}" y2="{top + inner_h}" '
            'stroke="#cfd6e0" stroke-width="1"/>'
        ),
    ]
    for frac in (0.25, 0.5, 0.75, 1.0):
        y = top + inner_h - frac * inner_h
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{w - 12}" y2="{y:.1f}" stroke="#eef1f6" '
            'stroke-width="1"/>'
        )
        near_threshold = chart.threshold is not None and abs(frac - chart.threshold) < 0.08
        if not near_threshold:  # la graduation cède la place à l'étiquette du seuil
            parts.append(
                f'<text x="{left - 8}" y="{y + 4:.1f}" font-size="10" fill="#5f6b7a" '
                f'text-anchor="end" font-family="Segoe UI,Arial,sans-serif">'
                f"{f'{frac:.2f}'.replace('.', chart.decimal)}</text>"
            )
    for i, point in enumerate(chart.points):
        x = left + i * slot + (slot - bar_w) / 2
        bh = point.value / chart.y_max * inner_h
        y = top + inner_h - bh
        below = chart.threshold is not None and point.value < chart.threshold
        colour = "#991b1b" if below else "#17335d"
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="3" '
            f'fill="{colour}"/>'
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 5:.1f}" font-size="11" text-anchor="middle" '
            f'fill="#1f2933" font-family="Segoe UI,Arial,sans-serif">{escape(point.text)}</text>'
            f'<text x="{x + bar_w / 2:.1f}" y="{top + inner_h + 16}" font-size="11" '
            f'text-anchor="middle" fill="#5f6b7a" font-family="Segoe UI,Arial,sans-serif">'
            f"N = {escape(point.label)}</text>"
        )
    if chart.threshold is not None:
        y = top + inner_h - chart.threshold / chart.y_max * inner_h
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{w - 12}" y2="{y:.1f}" stroke="#991b1b" '
            'stroke-width="1.2" stroke-dasharray="5 4"/>'
            f'<text x="{left - 8}" y="{y + 4:.1f}" font-size="10" text-anchor="end" '
            f'fill="#991b1b" font-weight="600" font-family="Segoe UI,Arial,sans-serif">'
            f"{escape(chart.threshold_text)}</text>"
        )
    parts.append("</svg>")
    return "<figure>" + "".join(parts) + "</figure>"


def _section(section: Section, help_label: str = "") -> str:
    parts = [f'<section class="card" id="{escape(section.id)}"><h2>{escape(section.title)}</h2>']
    if section.help:
        parts.append(
            f'<aside class="help"><b>{escape(help_label)}</b>{escape(section.help)}</aside>'
        )
    for i, paragraph in enumerate(section.paragraphs):
        plain = section.id in ("verdict", "pied", "en_clair")
        klass = ' class="lead"' if i == 0 and not plain else ""
        parts.append(f"<p{klass}>{escape(paragraph)}</p>")
    if section.items:
        klass = ' class="alert"' if section.id == "verdict" else ""
        items = "".join(f"<li>{escape(i)}</li>" for i in section.items)
        parts.append(f"<ul{klass}>{items}</ul>")
    parts.extend(_entry(e) for e in section.entries)
    if section.chart is not None:
        parts.append(_chart(section.chart))
    parts.extend(_table(t, section.id) for t in section.tables)
    if section.closing:
        closing = "".join(f"<p>{escape(p)}</p>" for p in section.closing)
        parts.append(f'<div class="closing">{closing}</div>')
    parts.append("</section>")
    return "\n".join(parts)


def _mast(view: ReportView) -> str:
    counts = "".join(
        f'<span class="chip count{" zero" if n == 0 else ""}">{escape(label)}<b>{n}</b></span>'
        for _tag, label, n in view.counts
    )
    review = f'<div class="review">{escape(view.review_label)}</div>' if view.human_review else ""
    return (
        '<header class="mast">\n<div>'
        f'<div class="brand"><i></i>qaudit</div>'
        f'<div class="brand-line">{escape(view.brand_line)}</div>'
        f"<h1>{escape(view.title)}</h1>"
        f'<div class="subject"><b>{escape(view.system_name)}</b> · '
        f"{escape(view.profile_label)}</div>"
        "</div>\n"
        f'<div class="verdict-panel {escape(view.decision_code)}">'
        f'<div class="k">{escape(_verdict_word(view))}</div>'
        f'<div class="d">{escape(view.decision_label)}</div>'
        f'<div class="counts">{counts}</div>{review}</div>\n</header>\n'
    )


def _verdict_word(view: ReportView) -> str:
    """Légende du bloc de verdict : celle de la vue, sinon le titre de la section
    « verdict » (même langue)."""
    if view.verdict_caption:
        return view.verdict_caption
    for section in view.sections:
        if section.id == "verdict":
            return section.title
    return ""


def _facts(view: ReportView) -> str:
    if not view.facts:
        return ""
    cells = "".join(
        f'<div><div class="l">{escape(k)}</div><div class="v">{escape(v)}</div></div>'
        for k, v in view.facts
    )
    return f'<div class="facts">{cells}</div>\n'


def _toc(view: ReportView) -> str:
    links = "".join(
        f'<a href="#{escape(s.id)}">{escape(s.title)}</a>'
        for s in view.sections
        if s.id not in ("entete", "pied")
    )
    return f'<nav class="toc"><span class="l">{escape(view.toc_label)}</span>{links}</nav>\n'


def render_html(view: ReportView) -> str:
    """Document HTML complet, encodé UTF-8, sans horodatage."""
    head = (
        f'<!DOCTYPE html>\n<html lang="{escape(view.lang)}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(view.title)} — {escape(view.system_name)}</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n<div class=\"page\">\n"
    )
    body = "\n".join(_section(s, view.help_label) for s in view.sections)
    tail = "</div>\n</body>\n</html>\n"
    return head + _mast(view) + _facts(view) + _toc(view) + body + "\n" + tail
