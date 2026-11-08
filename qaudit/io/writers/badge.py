# SPDX-License-Identifier: AGPL-3.0-or-later
"""Badge d'attestation : un petit SVG autonome (≈ 1 Ko, aucune ressource
externe) qui porte la référence ``AUD-AAAA-NNN``, et l'extrait HTML / Markdown
qui le relie à la page publique de vérification, la référence pré-remplie
(``verification?ref=AUD-AAAA-NNN``) et contrôlée au chargement.

Le badge n'est fabriqué que pour une référence présente au registre (voir
``cmd_badge``) : ce qu'il prouve, c'est le registre qui le dit, pas l'image.
Une image copiée avec une référence inventée mène à une page qui répond
« inconnue ».

Convention d'adresses du site (``site`` = racine d'une langue, sans « / »
final) : ``<site>/verification?ref=<réf>`` et ``<site>/badge/<réf>.svg``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from urllib.parse import quote

from qaudit.i18n import Catalog

REFERENCE = re.compile(r"^AUD-\d{4}-\d{3,}$")

_INK, _GOLD, _PAPER = "#0b1f3a", "#b8860b", "#f6f4ef"
_HEIGHT = 28
# Largeurs moyennes d'un caractère à 11 px ; ``textLength`` impose ensuite la
# largeur exacte, quelle que soit la police disponible chez le lecteur.
_CHAR_LABEL, _CHAR_REF = 6.1, 7.0
_ICON = 26  # anneau + marge à gauche du libellé


def badge_label(catalog: Catalog, issuer: str | None) -> str:
    if issuer:
        return catalog.text("badge.label", issuer=issuer)
    return catalog.text("badge.label_engine")


def badge_svg(reference: str, catalog: Catalog, issuer: str | None = None) -> str:
    """SVG du badge : libellé sur fond encre, référence sur fond papier."""
    label = badge_label(catalog, issuer)
    label_w = round(len(label) * _CHAR_LABEL)
    ref_w = round(len(reference) * _CHAR_REF)
    left = _ICON + label_w + 10
    width = left + ref_w + 18
    title = escape(catalog.text("badge.title", label=label, reference=reference))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{_HEIGHT}" '
        f'viewBox="0 0 {width} {_HEIGHT}" role="img" aria-label="{title}">'
        f"<title>{title}</title>"
        f'<rect width="{width}" height="{_HEIGHT}" rx="5" fill="{_PAPER}"/>'
        f'<path d="M5 0H{left}V{_HEIGHT}H5A5 5 0 0 1 0 {_HEIGHT - 5}V5A5 5 0 0 1 5 0Z" '
        f'fill="{_INK}"/>'
        f'<rect x=".5" y=".5" width="{width - 1}" height="{_HEIGHT - 1}" rx="4.5" fill="none" '
        f'stroke="{_INK}"/>'
        f'<circle cx="14" cy="14" r="6" fill="none" stroke="{_GOLD}" stroke-width="1.6"/>'
        f'<circle cx="14" cy="14" r="2.6" fill="{_GOLD}"/>'
        '<g font-family="Segoe UI,Verdana,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{_ICON}" y="18" fill="#fff" textLength="{label_w}" '
        f'lengthAdjust="spacingAndGlyphs">{escape(label)}</text>'
        f'<text x="{left + 9}" y="18" fill="{_INK}" font-weight="600" textLength="{ref_w}" '
        f'lengthAdjust="spacingAndGlyphs">{escape(reference)}</text>'
        "</g></svg>\n"
    )


@dataclass(frozen=True, slots=True)
class BadgeLinks:
    verify_url: str
    image_url: str
    alt: str

    def html(self) -> str:
        return (f'<a href="{escape(self.verify_url)}"><img src="{escape(self.image_url)}" '
                f'alt="{escape(self.alt)}" height="28"></a>')

    def markdown(self) -> str:
        alt = self.alt.replace("[", "(").replace("]", ")")
        return f"[![{alt}]({self.image_url})]({self.verify_url})"


def badge_links(
    reference: str, site: str, catalog: Catalog, issuer: str | None = None
) -> BadgeLinks:
    """Adresses publiques du badge et de sa vérification (``site`` = racine de
    la langue, par exemple ``https://exemple.org/en``)."""
    base = site.rstrip("/")
    ref = quote(reference, safe="")
    return BadgeLinks(
        verify_url=f"{base}/verification?ref={ref}",
        image_url=f"{base}/badge/{ref}.svg",
        alt=catalog.text("badge.alt", label=badge_label(catalog, issuer), reference=reference),
    )


_KIT_CSS = """
body{margin:0;background:#f6f4ef;color:#1f2933;font-family:"Segoe UI",system-ui,Arial,sans-serif;
font-size:15px;line-height:1.55}
.page{max-width:820px;margin:0 auto;padding:28px 18px}
h1{font-family:Georgia,serif;font-weight:normal;color:#0b1f3a;font-size:1.9rem;margin:8px 0 6px;
border-top:6px solid #0b1f3a;padding-top:18px}
h2{color:#0b1f3a;font-size:1.05rem;margin:26px 0 8px}
.preview{background:#fff;border:1px solid #e4dfd4;border-radius:10px;padding:22px;text-align:center}
textarea{width:100%;box-sizing:border-box;min-height:84px;font-size:.82rem;
font-family:Consolas,"Courier New",monospace;border:1px solid #e4dfd4;border-radius:8px;
padding:10px;background:#fff;color:#1f2933}
ul{padding-left:1.2rem}li{margin:.3rem 0}.muted{color:#5f6b7a;font-size:.9rem}
"""


def badge_kit(reference: str, svg: str, links: BadgeLinks, catalog: Catalog) -> str:
    """Page remise avec l'attestation : aperçu du badge, extraits HTML et
    Markdown prêts à coller, ce que le badge prouve et ne prouve pas."""
    c = catalog
    proves = "".join(f"<li>{escape(c.text(f'badge.kit.proves_{i}'))}</li>" for i in (1, 2, 3))
    limits = "".join(f"<li>{escape(c.text(f'badge.kit.limits_{i}'))}</li>" for i in (1, 2))
    where = c.text("badge.kit.links", verify=links.verify_url, image=links.image_url)
    return (
        f'<!DOCTYPE html>\n<html lang="{escape(c.lang)}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(c.text('badge.kit.title', reference=reference))}</title>\n"
        f"<style>{_KIT_CSS}</style>\n</head>\n<body>\n<div class=\"page\">\n"
        f"<h1>{escape(c.text('badge.kit.title', reference=reference))}</h1>\n"
        f"<p>{escape(c.text('badge.kit.intro', reference=reference))}</p>\n"
        f'<div class="preview"><a href="{escape(links.verify_url)}">{svg.strip()}</a></div>\n'
        f"<h2>{escape(c.text('badge.kit.html_h'))}</h2>\n"
        f"<textarea readonly>{escape(links.html())}</textarea>\n"
        f"<h2>{escape(c.text('badge.kit.md_h'))}</h2>\n"
        f"<textarea readonly>{escape(links.markdown())}</textarea>\n"
        f"<p class=\"muted\">{escape(where)}</p>\n"
        f"<h2>{escape(c.text('badge.kit.proves_h'))}</h2>\n<ul>{proves}</ul>\n"
        f"<h2>{escape(c.text('badge.kit.limits_h'))}</h2>\n<ul>{limits}</ul>\n"
        f"<p class=\"muted\">{escape(c.text('badge.kit.hosting'))}</p>\n"
        "</div>\n</body>\n</html>\n"
    )
