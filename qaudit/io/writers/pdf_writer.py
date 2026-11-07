# SPDX-License-Identifier: AGPL-3.0-or-later
"""Export PDF sans dépendance : générateur PDF 1.4 minimal (polices standard
Helvetica / Helvetica-Bold / Courier, encodage WinAnsi), déterministe (aucune
date de création, aucun identifiant aléatoire).

Mise en page : même charte que le rapport HTML — encre marine, filet or,
couleurs sémantiques du verdict et des statuts ; en-tête de marque, bandeau de
verdict, bandeau de faits, sections titrées, tableaux à en-tête et zébrures,
fiches de constats, graphique à barres, pied de page numéroté.

Limites assumées : polices standard non incorporées, largeur des caractères
estimée d'après les métriques Helvetica (ASCII) ; les caractères hors WinAnsi
sont translittérés.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from qaudit.core.errors import InternalError
from qaudit.io.writers.render import Chart, Entry, ReportView, Section, Table

PAGE_W, PAGE_H = 595.0, 842.0
MARGIN = 46.0
WIDTH = PAGE_W - 2 * MARGIN
FOOT = 40.0  # hauteur réservée au pied de page
BODY, SMALL, TINY, H1, H2, MONO = 9.4, 8.2, 7.2, 21.0, 12.6, 7.6
LEADING = 1.36

Colour = tuple[float, float, float]

# couleurs (r, g, b) dans [0 ; 1]
INK: Colour = (0.043, 0.122, 0.227)
INK2: Colour = (0.09, 0.2, 0.365)
GOLD: Colour = (0.722, 0.525, 0.043)
TEXT: Colour = (0.122, 0.161, 0.2)
MUTED: Colour = (0.373, 0.42, 0.478)
RULE: Colour = (0.894, 0.875, 0.831)
RULE2: Colour = (0.933, 0.945, 0.965)
ZEBRA: Colour = (0.984, 0.98, 0.969)
WHITE: Colour = (1.0, 1.0, 1.0)
RED: Colour = (0.6, 0.106, 0.106)
_SEMANTIC: dict[str, tuple[Colour, Colour]] = {
    "GO": ((0.086, 0.4, 0.204), (0.91, 0.96, 0.925)),
    "GO_CONDITIONAL": ((0.631, 0.361, 0.027), (0.992, 0.953, 0.882)),
    "NO_GO": (RED, (0.992, 0.925, 0.925)),
    "passed": ((0.086, 0.4, 0.204), (0.91, 0.96, 0.925)),
    "triggered": (RED, (0.992, 0.925, 0.925)),
    "indecision": ((0.631, 0.361, 0.027), (0.992, 0.953, 0.882)),
    "not_evaluated": ((0.278, 0.333, 0.412), (0.933, 0.949, 0.969)),
    "blocking": (RED, (0.992, 0.925, 0.925)),
    "major": ((0.761, 0.255, 0.047), (1.0, 0.941, 0.902)),
    "minor": ((0.541, 0.427, 0.0), (1.0, 0.973, 0.859)),
    "info": ((0.278, 0.333, 0.412), (0.933, 0.949, 0.969)),
}

# largeurs Helvetica (AFM, /1000) pour l'ASCII imprimable ; Helvetica-Bold est
# approchée par +6 %, Courier est à chasse fixe (600).
_HELV = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556,
    556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722,
    722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722,
    667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556,
    556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500,
    500, 334, 260, 334, 584,
]

_TRANSLIT = {
    "≥": ">=", "≤": "<=", "→": "->", "−": "-", "–": "-", "—": "-", "…": "...", "’": "'",
    "‘": "'", "“": '"', "”": '"', "₀": "0", "₃": "3", "₄": "4", "ᵉ": "e", "∞": "inf",
    "Φ": "Phi", "γ": "gamma", "σ": "sigma", "√": "sqrt", "·": ".", "×": "x", "\u00a0": " ",
    "\u202f": " ", "\u2009": " ", "œ": "oe", "Œ": "OE", "Δ": "D",
}
_NUMERIC = re.compile(r"^[-+]?[\d ]+([.,]\d+)?( ?%)?$")


def _clean(text: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in text)


def _ansi(text: str) -> bytes:
    raw = _clean(text).encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _width(text: str, font: str, size: float) -> float:
    """Largeur estimée du texte (points)."""
    if font == "F3":
        return 0.6 * size * len(text)
    total = 0
    for ch in _clean(text):
        code = ord(ch)
        total += _HELV[code - 32] if 32 <= code < 127 else 556
    factor = 1.06 if font == "F2" else 1.0
    return total / 1000.0 * size * factor


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    words = _clean(text).split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if _width(candidate, font, size) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        while _width(word, font, size) > width and len(word) > 1:
            cut = max(1, int(len(word) * width / _width(word, font, size)))
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    lines.append(current)
    return lines


def _rgb(colour: Colour, stroke: bool = False) -> bytes:
    op = b"RG" if stroke else b"rg"
    return b"%.3f %.3f %.3f %s" % (*colour, op)


def _is_kv(table: Table) -> bool:
    return not table.headers and bool(table.rows) and all(len(r) == 2 for r in table.rows)


@dataclass
class _Page:
    ops: list[bytes] = field(default_factory=list)
    y: float = PAGE_H - MARGIN


class _Layout:
    def __init__(self) -> None:
        self.pages: list[_Page] = [_Page()]

    @property
    def page(self) -> _Page:
        return self.pages[-1]

    def need(self, height: float) -> bool:
        """Saute de page si ``height`` ne tient plus ; vrai si une page a été ouverte."""
        if self.page.y - height < MARGIN + FOOT:
            self.pages.append(_Page())
            return True
        return False

    # -- primitives ------------------------------------------------------------

    def text(self, x: float, y: float, text: str, font: str, size: float,
             colour: Colour = TEXT, align: str = "left") -> None:
        if align == "right":
            x -= _width(text, font, size)
        elif align == "center":
            x -= _width(text, font, size) / 2
        self.page.ops.append(
            _rgb(colour) + b" BT /%s %.1f Tf %.2f %.2f Td (%s) Tj ET"
            % (font.encode(), size, x, y, _ansi(text))
        )

    def rect(self, x: float, y: float, w: float, h: float, fill: Colour | None = None,
             stroke: Colour | None = None, line: float = 0.6) -> None:
        if fill is not None:
            self.page.ops.append(_rgb(fill) + b" %.2f %.2f %.2f %.2f re f" % (x, y, w, h))
        if stroke is not None:
            self.page.ops.append(
                _rgb(stroke, True) + b" %.2f w %.2f %.2f %.2f %.2f re S" % (line, x, y, w, h)
            )

    def line(self, x1: float, y1: float, x2: float, y2: float, colour: Colour = RULE,
             width: float = 0.6, dash: bytes = b"[] 0") -> None:
        self.page.ops.append(
            _rgb(colour, True) + b" %.2f w %s d %.2f %.2f m %.2f %.2f l S [] 0 d"
            % (width, dash, x1, y1, x2, y2)
        )

    # -- blocs -----------------------------------------------------------------

    def paragraph(self, text: str, font: str = "F1", size: float = BODY, colour: Colour = TEXT,
                  indent: float = 0.0) -> None:
        for chunk in _wrap(text, font, size, WIDTH - indent):
            self.need(size * LEADING)
            self.page.y -= size * LEADING
            self.text(MARGIN + indent, self.page.y, chunk, font, size, colour)

    def gap(self, points: float) -> None:
        self.need(points)
        self.page.y -= points

    def bullet(self, text: str, dot: Colour = INK) -> None:
        self.need(BODY * LEADING)
        top = self.page.y
        self.paragraph(text, "F1", BODY, TEXT, indent=12)
        if self.page.y < top:  # même page : point devant la première ligne
            self.rect(MARGIN + 2.5, top - BODY * LEADING + 2.6, 3.2, 3.2, fill=dot)

    def entry(self, entry: Entry) -> None:
        colour, tint = _SEMANTIC.get(entry.tag, _SEMANTIC["info"])
        lines = _wrap(entry.text, "F1", BODY, WIDTH - 22)
        height = SMALL * LEADING + len(lines) * BODY * LEADING + 10
        self.need(height)
        top = self.page.y
        self.rect(MARGIN, top - height, WIDTH, height, fill=tint)
        self.rect(MARGIN, top - height, 2.6, height, fill=colour)
        y = top - 4 - SMALL
        label = entry.label.upper()
        self.text(MARGIN + 12, y, label, "F2", TINY, colour)
        self.text(MARGIN + 12 + _width(label, "F2", TINY) + 8, y, entry.code, "F3", MONO, MUTED)
        for line in lines:
            y -= BODY * LEADING
            self.text(MARGIN + 12, y, line, "F1", BODY, TEXT)
        self.page.y = top - height

    # -- tableaux --------------------------------------------------------------

    def kv_table(self, table: Table) -> None:
        label_w = WIDTH * 0.42
        value_size = SMALL + 0.4
        for i, (label, value) in enumerate(table.rows):
            l_lines = _wrap(label, "F1", SMALL, label_w - 16)
            v_lines = _wrap(value, "F2", value_size, WIDTH - label_w - 8)
            height = max(len(l_lines) * SMALL, len(v_lines) * value_size) * LEADING + 8
            self.need(height)
            top = self.page.y
            if i > 0:
                self.line(MARGIN, top, MARGIN + WIDTH, top, RULE2)
            y = top - 4 - SMALL
            for text in l_lines:
                self.text(MARGIN + 8, y, text, "F1", SMALL, MUTED)
                y -= SMALL * LEADING
            y = top - 4 - SMALL
            for text in v_lines:
                self.text(MARGIN + label_w, y, text, "F2", value_size, TEXT)
                y -= value_size * LEADING
            self.page.y = top - height
        self.gap(6)

    def grid_table(self, table: Table, section_id: str) -> None:
        rows = list(table.rows)
        if not rows:
            return
        n_cols = max(len(r) for r in (*rows, table.headers))
        widths = self._column_widths(table, n_cols)
        numeric = [_numeric_column(rows, j) for j in range(n_cols)]
        if table.headers:
            self._grid_header(table.headers, widths, numeric)
        for i, row in enumerate(rows):
            tag = table.tags[i] if i < len(table.tags) else ""
            cells = [(row[j] if j < len(row) else "") for j in range(n_cols)]
            wrapped = [_wrap(c, "F1", SMALL, widths[j] - 8) for j, c in enumerate(cells)]
            height = max(len(w) for w in wrapped) * SMALL * LEADING + 7
            if self.need(height) and table.headers:
                self._grid_header(table.headers, widths, numeric)
            top = self.page.y
            if i % 2 == 1:
                self.rect(MARGIN, top - height, WIDTH, height, fill=ZEBRA)
            self.line(MARGIN, top, MARGIN + WIDTH, top, RULE2)
            self._grid_row(wrapped, widths, numeric, top, tag, section_id)
            self.page.y = top - height
        self.line(MARGIN, self.page.y, MARGIN + WIDTH, self.page.y, RULE)
        self.gap(8)

    def _grid_row(self, wrapped: list[list[str]], widths: list[float], numeric: list[bool],
                  top: float, tag: str, section_id: str) -> None:
        row_colour = RED if tag == "neg" else TEXT
        x = MARGIN
        last = len(wrapped) - 1
        for j, lines in enumerate(wrapped):
            colour, font = row_colour, "F1"
            if section_id == "barrieres" and j == last and tag in _SEMANTIC:
                colour, font = _SEMANTIC[tag][0], "F2"
            y = top - 4 - SMALL
            for text in lines:
                if numeric[j]:
                    self.text(x + widths[j] - 4, y, text, font, SMALL, colour, "right")
                else:
                    self.text(x + 4, y, text, font, SMALL, colour)
                y -= SMALL * LEADING
            x += widths[j]

    def _grid_header(self, headers: tuple[str, ...], widths: list[float],
                     numeric: list[bool]) -> None:
        wrapped = [_wrap(h.upper(), "F2", TINY, widths[j] - 8) for j, h in enumerate(headers)]
        height = max(len(w) for w in wrapped) * TINY * LEADING + 7
        self.need(height)
        top = self.page.y
        self.rect(MARGIN, top - height, WIDTH, height, fill=RULE2)
        x = MARGIN
        for j, lines in enumerate(wrapped):
            y = top - 4 - TINY
            for text in lines:
                if j < len(numeric) and numeric[j]:
                    self.text(x + widths[j] - 4, y, text, "F2", TINY, INK, "right")
                else:
                    self.text(x + 4, y, text, "F2", TINY, INK)
                y -= TINY * LEADING
            x += widths[j]
        self.page.y = top - height

    @staticmethod
    def _column_widths(table: Table, n_cols: int) -> list[float]:
        """Largeurs proportionnelles au contenu, bornées, somme = WIDTH."""
        rows = [*table.rows, table.headers] if table.headers else list(table.rows)
        need = []
        for j in range(n_cols):
            longest = max((_width(r[j], "F1", SMALL) for r in rows if j < len(r)), default=20.0)
            need.append(min(max(longest + 10, 34.0), WIDTH * 0.5))
        total = sum(need)
        return [w * WIDTH / total for w in need]

    # -- graphique -------------------------------------------------------------

    def chart(self, chart: Chart) -> None:
        if not chart.points:
            return
        height, left_pad, top_pad, bottom_pad = 150.0, 34.0, 16.0, 22.0
        self.need(height + 10)
        top = self.page.y - 4
        base = top - height + bottom_pad
        inner_h = height - top_pad - bottom_pad
        x0 = MARGIN + left_pad
        inner_w = WIDTH - left_pad - 8
        slot = inner_w / len(chart.points)
        bar_w = min(42.0, slot * 0.58)
        for frac in (0.25, 0.5, 0.75, 1.0):
            y = base + frac * inner_h
            self.line(x0, y, x0 + inner_w, y, RULE2, 0.5)
            near = chart.threshold is not None and abs(frac - chart.threshold) < 0.08
            if not near:
                label = f"{frac:.2f}".replace(".", chart.decimal)
                self.text(x0 - 6, y - 2.5, label, "F1", TINY, MUTED, "right")
        self.line(x0, base, x0 + inner_w, base, RULE, 0.8)
        for i, point in enumerate(chart.points):
            x = x0 + i * slot + (slot - bar_w) / 2
            bh = point.value / chart.y_max * inner_h
            below = chart.threshold is not None and point.value < chart.threshold
            self.rect(x, base, bar_w, bh, fill=RED if below else INK2)
            self.text(x + bar_w / 2, base + bh + 3, point.text, "F1", TINY, TEXT, "center")
            self.text(x + bar_w / 2, base - 10, f"N = {point.label}", "F1", TINY, MUTED, "center")
        if chart.threshold is not None:
            y = base + chart.threshold / chart.y_max * inner_h
            self.line(x0, y, x0 + inner_w, y, RED, 0.9, b"[4 3] 0")
            self.text(x0 - 6, y - 2.5, chart.threshold_text, "F2", TINY, RED, "right")
        self.page.y = top - height - 6


def _numeric_column(rows: list[tuple[str, ...]], j: int) -> bool:
    cells = [r[j] for r in rows if j < len(r) and r[j]]
    return bool(cells) and all(_NUMERIC.match(_clean(c)) for c in cells)


# ---------------------------------------------------------------------------
# composition
# ---------------------------------------------------------------------------


def _verdict_word(view: ReportView) -> str:
    if view.verdict_caption:
        return view.verdict_caption
    for section in view.sections:
        if section.id == "verdict":
            return section.title
    return ""


def _masthead(layout: _Layout, view: ReportView) -> None:
    top = PAGE_H - MARGIN
    layout.rect(MARGIN, top - 4, WIDTH, 4, fill=INK)
    y = top - 26
    layout.rect(MARGIN, y - 3, 11, 11, stroke=GOLD, line=1.2)
    layout.rect(MARGIN + 3.2, y + 0.2, 4.6, 4.6, fill=INK)
    layout.text(MARGIN + 17, y, "Q A U D I T", "F2", 9.5, INK)
    layout.text(MARGIN, y - 13, view.brand_line, "F1", TINY, MUTED)
    # bloc verdict à droite
    colour, tint = _SEMANTIC.get(view.decision_code, _SEMANTIC["not_evaluated"])
    box_w = WIDTH * 0.40
    box_x = MARGIN + WIDTH - box_w
    counts_text = "   ".join(f"{label} {n}" for _tag, label, n in view.counts)
    review_lines = _wrap(view.review_label, "F2", TINY, box_w - 24) if view.human_review else []
    box_h = 62 + len(review_lines) * TINY * LEADING + (6 if review_lines else 0)
    box_top = top - 14
    layout.rect(box_x, box_top - box_h, box_w, box_h, fill=tint, stroke=colour, line=0.8)
    layout.text(box_x + 12, box_top - 16, _verdict_word(view).upper(), "F2", TINY, colour)
    layout.text(box_x + 12, box_top - 34, view.decision_label, "F2", 15.5, colour)
    layout.text(box_x + 12, box_top - 50, counts_text, "F1", TINY, MUTED)
    yy = box_top - 50
    for text in review_lines:
        yy -= TINY * LEADING
        layout.text(box_x + 12, yy, text, "F2", TINY, INK)
    # titre et sujet
    title_w = WIDTH - box_w - 14
    y = top - 74
    for text in _wrap(view.title, "F2", H1, title_w):
        layout.text(MARGIN, y, text, "F2", H1, INK)
        y -= H1 * 1.15
    y -= 2
    for text in _wrap(f"{view.system_name}  |  {view.profile_label}", "F1", BODY + 0.6, title_w):
        layout.text(MARGIN, y, text, "F1", BODY + 0.6, MUTED)
        y -= (BODY + 0.6) * LEADING
    layout.page.y = min(y, box_top - box_h) - 10


def _facts(layout: _Layout, view: ReportView) -> None:
    if not view.facts:
        return
    cell_w = WIDTH / len(view.facts)
    label_size = TINY - 0.6
    wrapped = [
        (_wrap(k.upper(), "F1", label_size, cell_w - 16), _wrap(v, "F2", BODY, cell_w - 16))
        for k, v in view.facts
    ]
    height = max(len(k) * label_size + len(v) * BODY for k, v in wrapped) * LEADING + 18
    layout.need(height + 6)
    top = layout.page.y
    layout.rect(MARGIN, top - height, WIDTH, height, fill=WHITE, stroke=RULE)
    for i, (k_lines, v_lines) in enumerate(wrapped):
        x = MARGIN + i * cell_w
        if i:
            layout.line(x, top, x, top - height, RULE)
        y = top - 8 - TINY
        for text in k_lines:
            layout.text(x + 8, y, text, "F1", label_size, MUTED)
            y -= label_size * LEADING
        y -= 3
        for text in v_lines:
            layout.text(x + 8, y, text, "F2", BODY, INK)
            y -= BODY * LEADING
    layout.page.y = top - height - 12


def _heading(layout: _Layout, title: str) -> None:
    layout.need(H2 * 3.2)
    layout.page.y -= H2 * 1.6
    y = layout.page.y
    layout.rect(MARGIN, y + 3, 10, 2.2, fill=GOLD)
    layout.text(MARGIN + 17, y, title, "F2", H2, INK)
    layout.page.y -= 7
    layout.line(MARGIN, layout.page.y, MARGIN + WIDTH, layout.page.y, RULE)
    layout.page.y -= 4


def _help(layout: _Layout, label: str, text: str) -> None:
    """Encadré « comment lire » : fond clair, filet or à gauche, texte marine."""
    lines = _wrap(text, "F1", SMALL, WIDTH - 22)
    height = TINY * LEADING + len(lines) * SMALL * LEADING + 10
    layout.need(height)
    top = layout.page.y
    layout.rect(MARGIN, top - height, WIDTH, height, fill=RULE2)
    layout.rect(MARGIN, top - height, 2.4, height, fill=GOLD)
    y = top - 4 - TINY
    layout.text(MARGIN + 12, y, label.upper(), "F2", TINY - 0.6, MUTED)
    for line in lines:
        y -= SMALL * LEADING
        layout.text(MARGIN + 12, y, line, "F1", SMALL, INK2)
    layout.page.y = top - height - 6


def _section(layout: _Layout, section: Section, help_label: str = "") -> None:
    _heading(layout, section.title)
    if section.help:
        _help(layout, help_label, section.help)
    for i, paragraph in enumerate(section.paragraphs):
        plain = section.id in ("verdict", "pied", "en_clair")
        colour = MUTED if i == 0 and not plain else TEXT
        layout.paragraph(paragraph, "F1", BODY, colour)
        layout.gap(2)
    for item in section.items:
        layout.bullet(item, dot=RED if section.id == "verdict" else INK)
    if section.items:
        layout.gap(3)
    for entry in section.entries:
        layout.entry(entry)
        layout.gap(4)
    if section.chart is not None:
        layout.chart(section.chart)
    for table in section.tables:
        layout.gap(2)
        if _is_kv(table):
            layout.kv_table(table)
        else:
            layout.grid_table(table, section.id)
    for paragraph in section.closing:
        layout.gap(2)
        layout.paragraph(paragraph, "F1", BODY, TEXT)


def render_pdf(view: ReportView) -> bytes:
    """Octets du PDF."""
    layout = _Layout()
    _masthead(layout, view)
    _facts(layout, view)
    for section in view.sections:
        _section(layout, section, view.help_label)
    footer_left = f"qaudit  |  {view.system_name}  |  {view.profile_label}"
    return _assemble(layout.pages, footer_left)


def _footer(page: _Page, index: int, total: int, left: str) -> None:
    y = MARGIN + 14
    page.ops.append(
        _rgb(RULE, True) + b" 0.6 w %.2f %.2f m %.2f %.2f l S"
        % (MARGIN, y + 10, MARGIN + WIDTH, y + 10)
    )
    page.ops.append(
        _rgb(MUTED) + b" BT /F1 %.1f Tf %.2f %.2f Td (%s) Tj ET" % (TINY, MARGIN, y, _ansi(left))
    )
    right = f"{index} / {total}"
    x = MARGIN + WIDTH - _width(right, "F1", TINY)
    page.ops.append(
        _rgb(MUTED) + b" BT /F1 %.1f Tf %.2f %.2f Td (%s) Tj ET" % (TINY, x, y, _ansi(right))
    )


def _assemble(pages: list[_Page], footer_left: str) -> bytes:
    for i, page in enumerate(pages, start=1):
        _footer(page, i, len(pages), footer_left)
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    fonts = {
        "F1": add(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
        ),
        "F2": add(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold"
            b" /Encoding /WinAnsiEncoding >>"
        ),
        "F3": add(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"
        ),
    }
    font_dict = (
        b"<< " + b" ".join(b"/%s %d 0 R" % (k.encode(), v) for k, v in fonts.items()) + b" >>"
    )
    pages_id = len(objects) + 1 + 2 * len(pages)  # objet Pages placé après les pages
    page_ids = []
    for page in pages:
        stream = b"\n".join(page.ops)
        content_id = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Resources << /Font %s >> "
                b"/Contents %d 0 R >>" % (pages_id, int(PAGE_W), int(PAGE_H), font_dict, content_id)
            )
        )
    kids = b" ".join(b"%d 0 R" % i for i in page_ids)
    real_pages_id = add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids)))
    if real_pages_id != pages_id:
        raise InternalError("internal.pdf_layout", expected=pages_id, actual=real_pages_id)
    catalog_id = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (
        b"trailer\n<< /Size %d /Root %d 0 R /ID [<0000000000000000> <0000000000000000>] >>\n"
        b"startxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog_id, xref)
    )
    return bytes(out)
