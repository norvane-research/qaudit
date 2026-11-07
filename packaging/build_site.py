# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assemble le site statique de l'offre dans ``site/`` (français à la racine,
anglais sous ``en/``) : page de vente, « Préparer votre audit », méthode
publiée, politique de données, CGV, page de vérification (registre public) et
deux rapports d'exemple rendus par le moteur (témoin sain GO, martingale NO-GO,
données synthétiques de démonstration).

Sans dépendance : Markdown minimal → HTML. L'offre commerciale (prestations,
prix, ordre, actions), les coordonnées et les liens de commande et de paiement
viennent de ``site.toml`` — le moteur, lui, ne connaît aucun prix ; la méthode
vient de ``qaudit methode``.

    python packaging/build_site.py [--out site] [--registry chemin] [--config site.toml]
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

# Actions possibles d'une ligne d'offre : lien vers le dépôt public du moteur,
# envoi d'un fichier pour la pré-vérification, commande (lien de paiement de
# [payment] ou order_url), demande de devis.
ACTIONS = ("depot", "preverification", "commande", "devis")
ATTESTATIONS = ("", "go", "cessible")


@dataclass(frozen=True)
class Offer:
    code: str
    action: str
    price_eur: float | None = None  # 0 = gratuit, None = sur devis
    attestation: str = ""


# Offre par défaut (site.toml absent ou sans [[offres]]) : le moteur est gratuit,
# on vend ce qu'une copie du code ne donne pas — un audit refait par un tiers et
# inscrit au registre public, et la licence commerciale.
DEFAULT_OFFERS = (
    Offer("moteur", "depot", 0),
    Offer("pre_verification", "preverification", 0),
    Offer("attestation_cessible", "commande", 390, "cessible"),
    Offer("portefeuille", "devis", None, "go"),
    Offer("due_diligence", "devis", None, "cessible"),
    Offer("licence_commerciale", "devis"),
)

CSS = """
:root{--ink:#0b1f3a;--ink-2:#17335d;--gold:#b8860b;--paper:#f6f4ef;--card:#fff;--text:#1f2933;
--muted:#5f6b7a;--rule:#e4dfd4;--rule-2:#eef1f6;--go:#166534;--go-bg:#e8f5ec;--cond:#a15c07;
--cond-bg:#fdf3e1;--nogo:#991b1b;--nogo-bg:#fdecec;
--serif:Georgia,"Palatino Linotype","Book Antiqua",Cambria,serif;
--sans:"Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif;
--mono:Consolas,"Cascadia Mono","Courier New",monospace}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--text);
font-family:var(--sans);font-size:16px;line-height:1.6}
a{color:var(--ink-2)}a:hover{color:var(--gold)}
.wrap{max-width:1040px;margin:0 auto;padding:0 24px}
header.top{background:var(--ink);color:#fff}
header.top .wrap{display:flex;align-items:center;justify-content:space-between;gap:16px;
padding:16px 24px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;font-family:var(--serif);font-size:1.3rem;
letter-spacing:.06em;color:#fff;text-decoration:none}
.brand i{width:22px;height:22px;border:2px solid var(--gold);border-radius:50%;position:relative;
display:inline-block}.brand i:after{content:"";position:absolute;inset:5px;background:var(--gold);
border-radius:50%}
nav a{color:#c8d0dc;text-decoration:none;margin-left:18px;font-size:.92rem}nav a:hover{color:#fff}
nav a.lang{border:1px solid #3b4d6b;border-radius:6px;padding:2px 8px}
.hero{padding:64px 0 40px;border-bottom:1px solid var(--rule)}
.hero h1{font-family:var(--serif);font-weight:normal;font-size:2.6rem;line-height:1.15;color:var(--ink);
margin:0 0 14px;max-width:22ch}
.hero p.lead{font-size:1.15rem;color:var(--muted);max-width:60ch;margin:0 0 26px}
.cta{display:inline-block;background:var(--ink);color:#fff;text-decoration:none;padding:12px 22px;
border-radius:10px;font-weight:600}.cta:hover{background:var(--ink-2);color:#fff}
.cta.ghost{background:transparent;color:var(--ink);border:1px solid var(--rule);margin-left:10px}
.cta.small{padding:7px 12px;font-size:.85rem;border-radius:8px}
section{padding:44px 0}section+section{border-top:1px solid var(--rule)}
h2{font-family:var(--serif);font-weight:normal;font-size:1.7rem;color:var(--ink);margin:0 0 18px;
display:flex;align-items:center;gap:12px}
h2:before{content:"";width:18px;height:3px;background:var(--gold);border-radius:2px}
h3{font-family:var(--serif);font-weight:normal;font-size:1.2rem;color:var(--ink);margin:22px 0 8px}
.grid{display:grid;gap:16px}.grid.c3{grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.grid.c2{grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
.card{background:var(--card);border:1px solid var(--rule);border-radius:14px;padding:20px 22px}
.card h3{margin-top:0}.card p{margin:.4rem 0;color:var(--text)}
.card .k{font-size:.74rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.q{font-family:var(--serif);font-size:1.15rem;color:var(--ink);margin:0 0 6px}
.steps{counter-reset:s}.steps .card{position:relative;padding-left:64px}
.steps .card:before{counter-increment:s;content:counter(s,decimal-leading-zero);position:absolute;
left:20px;top:18px;font-family:var(--serif);font-size:1.6rem;color:var(--gold)}
table{border-collapse:separate;border-spacing:0;width:100%;background:var(--card);
border:1px solid var(--rule);border-radius:12px;overflow:hidden;font-size:.95rem;margin:14px 0}
th,td{padding:.65rem .8rem;text-align:left;vertical-align:top;border-top:1px solid var(--rule-2)}
tr:first-child>*{border-top:none}
th{background:var(--rule-2);color:var(--ink);font-size:.76rem;text-transform:uppercase;
letter-spacing:.06em}
td.price{white-space:nowrap;font-family:var(--serif);font-size:1.1rem;color:var(--ink)}
.chip{display:inline-block;border-radius:999px;padding:.12rem .62rem;font-size:.76rem;font-weight:600}
.chip.go{background:var(--go-bg);color:var(--go)}.chip.nogo{background:var(--nogo-bg);color:var(--nogo)}
.chip.cond{background:var(--cond-bg);color:var(--cond)}
.rules .card{border-left:4px solid var(--gold)}
blockquote{margin:0;padding:12px 18px;background:var(--cond-bg);border-left:4px solid var(--cond);
border-radius:8px;color:var(--text)}
code{font-family:var(--mono);font-size:.9em;background:var(--rule-2);padding:.1em .35em;border-radius:4px}
.doc{max-width:820px}.doc h1{font-family:var(--serif);font-weight:normal;color:var(--ink);font-size:2.1rem;
margin:36px 0 16px}.doc h2{margin-top:36px}.doc p{margin:.7rem 0}.doc ul{padding-left:1.2rem}
.doc li{margin:.3rem 0}.doc table{font-size:.9rem}
footer{background:var(--ink);color:#c8d0dc;padding:28px 0;font-size:.9rem;margin-top:40px}
footer a{color:#fff;text-decoration:none;margin-right:16px}footer .wrap{display:flex;flex-wrap:wrap;
gap:12px;justify-content:space-between}
.search{display:flex;gap:10px;margin:14px 0 6px}.search input{flex:1;padding:10px 12px;
border:1px solid var(--rule);border-radius:10px;font:inherit}
.muted{color:var(--muted)}.small{font-size:.9rem}.note{font-size:.9rem;color:var(--muted);margin-top:8px}
@media (max-width:640px){.hero h1{font-size:2rem}.cta.ghost{margin-left:0;margin-top:10px}}
"""


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SiteConfig:
    brand: str = "qaudit"
    issuer: str = ""
    contact: str = "contact@exemple.com"
    order_url: str = ""
    preverification_url: str = ""
    languages: tuple[str, ...] = ("fr", "en")
    payment: dict[str, str] = field(default_factory=dict)
    repo_url: str = ""
    offers: tuple[Offer, ...] = DEFAULT_OFFERS

    def order(self, lang: str) -> str:
        subject = "Commande d'audit" if lang == "fr" else "Audit order"
        return self.order_url or f"mailto:{self.contact}?subject={subject.replace(' ', '%20')}"

    def preverification(self, lang: str) -> str:
        if self.preverification_url:
            return self.preverification_url
        if self.order_url:
            return self.order_url
        subject = "Pré-vérification gratuite" if lang == "fr" else "Free pre-check"
        return f"mailto:{self.contact}?subject={subject.replace(' ', '%20')}"

    def pay(self, code: str, lang: str) -> str:
        return self.payment.get(code) or self.order(lang)


def load_config(path: Path) -> SiteConfig:
    if not path.exists():
        return SiteConfig()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    site = raw.get("site", {})
    return SiteConfig(
        brand=str(site.get("brand", "qaudit")),
        issuer=str(site.get("issuer", "")),
        contact=str(site.get("contact", "contact@exemple.com")),
        order_url=str(site.get("order_url", "")),
        preverification_url=str(site.get("preverification_url", "")),
        languages=tuple(str(x) for x in site.get("languages", ["fr", "en"])),
        payment={k: str(v) for k, v in raw.get("payment", {}).items() if v},
        repo_url=str(site.get("repo_url", "")),
        offers=parse_offers(raw.get("offres", [])) or DEFAULT_OFFERS,
    )


def parse_offers(rows: list[dict[str, object]]) -> tuple[Offer, ...]:
    """Lignes ``[[offres]]`` de site.toml ; une prestation sans libellé, une action
    ou un type d'attestation inconnus sont refusés en les nommant."""
    labels = T["fr"]["offer_label"]
    assert isinstance(labels, dict)
    offers = []
    for row in rows:
        code = str(row.get("code", ""))
        action = str(row.get("action", ""))
        attestation = str(row.get("attestation", ""))
        price = row.get("prix_eur")
        if code not in labels:
            raise ValueError(f"site.toml : prestation sans libellé : {code!r}")
        if action not in ACTIONS:
            raise ValueError(f"site.toml : action inconnue pour {code} : {action!r}")
        if attestation not in ATTESTATIONS:
            raise ValueError(f"site.toml : attestation inconnue pour {code} : {attestation!r}")
        if price is not None and not isinstance(price, (int, float)):
            raise ValueError(f"site.toml : prix_eur non numérique pour {code}")
        offers.append(Offer(code, action, None if price is None else float(price), attestation))
    return tuple(offers)


# ---------------------------------------------------------------------------
# textes
# ---------------------------------------------------------------------------

T: dict[str, dict[str, object]] = {
    "fr": {
        "lang_switch": ("en/index.html", "English"),
        "nav": (("index.html", "Offre"), ("preparer.html", "Préparer votre audit"),
                ("methode.html", "Méthode"), ("verification.html", "Vérifier une attestation"),
                ("exemples/index.html", "Exemples")),
        "footer_links": (("methode.html", "Méthode"), ("donnees.html", "Données"),
                         ("cgv.html", "CGV"), ("verification.html", "Vérification")),
        "tagline": "audit statistique de systèmes de trading",
        "title_index": "Audit de systèmes de trading",
        "hero_h1": "Un verdict sur votre système de trading que vous pouvez montrer.",
        "hero_lead": "Audit statistique indépendant d'un historique de trades : moteur open source, méthode publiée, seuils fixés à l'avance, rapport reproductible à l'octet près, attestation vérifiable par n'importe qui. Le moteur constate ; il ne conseille rien et ne prédit rien.",
        "cta_pre": "Commencer par la pré-vérification gratuite",
        "cta_example": "Voir un rapport",
        "proofs_h2": "Pourquoi ce verdict vaut quelque chose",
        "proofs": (
            ("Méthode publique", "Les seuils sont écrits avant votre dossier", "Cinq barrières éliminatoires, onze détecteurs, leurs paramètres : tout est <a href=\"methode.html\">publié</a>. Un NO-GO se discute sur des faits, pas sur une opinion."),
            ("Reproductible", "Même fichier, même rapport, à l'octet près", "Chaque rapport imprime l'empreinte SHA-256 de vos données, la version de la méthode et la graine. Le moteur est open source : quiconque détient le fichier peut refaire le calcul."),
            ("Vérifiable", "Une attestation numérotée, un registre public", "Émise uniquement sur GO, inscrite au <a href=\"verification.html\">registre</a> avec l'empreinte du fichier. Vos clients la vérifient sans vous croire sur parole."),
        ),
        "questions_h2": "Les cinq questions posées à vos résultats",
        "questions": (
            ("Le hasard est-il écarté ?", "Sharpe dégonflé : la performance survit-elle au nombre de variantes que vous avez essayées avant de garder celle-ci ?"),
            ("Et avec de la malchance ?", "10 000 rejeux des mêmes trades par blocs : dans les 5 % de scénarios les plus défavorables, gagnez-vous encore ?"),
            ("Les pertes arrivent-elles groupées ?", "Votre drawdown comparé à celui de milliers de réordonnancements des mêmes trades."),
            ("Un système sans avantage ferait-il aussi bien ?", "Des systèmes sans aucun edge, aux gains et pertes de même taille : combien font mieux que vous ?"),
            ("Tient-il hors des périodes où il a été réglé ?", "Walk-forward sur vos jeux de paramètres : ce qui reste de la performance hors échantillon."),
        ),
        "detectors_note": "S'y ajoutent onze détecteurs de la façon de trader : martingale, grille, absence de stop, concentration du profit, courbe trop lisse, asymétrie, dépendance à une période, durées irréalistes et, avec les cotations, look-ahead, prix impossibles, stop trop sensible.",
        "steps_h2": "Comment ça se passe",
        "steps": (
            ("Vous envoyez l'export brut", "Rapport MetaTrader 4 ou 5 (compte ou Strategy Tester), export Deriv, ou CSV une ligne par trade. Jamais votre code : l'audit porte sur vos trades. <a href=\"preparer.html\">Comment l'exporter</a>."),
            ("Pré-vérification gratuite", "En quinze minutes : fichier lisible, champs présents, échantillon suffisant. Si les données ne tiennent pas, vous le savez avant que l'argent change de main."),
            ("Audit refait sous 72 heures", "Nous relançons le moteur sur votre fichier : verdict en première page, section « En clair » qui se lit sans nous, barrières, constats, simulations, repères. Attestation inscrite au registre si GO. Appel de restitution de 45 minutes."),
        ),
        "offers_h2": "Offres",
        "offers_cols": ("Prestation", "Prix", "Attestation", ""),
        "offer_label": {
            "moteur": "Moteur open source",
            "pre_verification": "Pré-vérification",
            "attestation_cessible": "Attestation cessible",
            "portefeuille": "Portefeuille de systèmes",
            "due_diligence": "Due diligence",
            "licence_commerciale": "Licence commerciale",
        },
        "offer_blurb": {
            "moteur": "Le moteur complet — ligne de commande, fenêtre, bibliothèque — et tous les rapports, à lancer vous-même. Licence AGPL-3.0.",
            "pre_verification": "Votre fichier est-il exploitable ? Réponse en quinze minutes, avant tout paiement.",
            "attestation_cessible": "Nous refaisons l'audit sur votre fichier ; si GO, une attestation numérotée au registre public, que vos acquéreurs vérifient eux-mêmes. Due quel que soit le verdict.",
            "portefeuille": "Plusieurs systèmes audités ensemble, avec la correction statistique de sélection multiple.",
            "due_diligence": "Tout, plus une note de comité d'investissement ; périmètre et prix définis sur devis.",
            "licence_commerciale": "Intégrer le moteur dans un produit ou un service fermé, sans les obligations de l'AGPL.",
        },
        "price_free": "gratuit", "price_quote": "sur devis",
        "att_transferable": "attestation cessible", "att_go": "attestation si GO", "att_none": "—",
        "order": "Commander", "send_file": "Envoyer un fichier", "ask_quote": "Demander un devis",
        "repo": "Voir le code",
        "offers_note": "Le moteur est le même pour tous et son code est public : le verdict ne dépend ni de l'offre ni de celui qui le lance. Ce que vous payez, c'est un audit refait par un tiers et inscrit à un registre public.",
        "rules_h2": "Les règles",
        "rules": (
            ("Un NO-GO reste un NO-GO", "Le rapport est dû et payé quel que soit le verdict. Aucune conclusion n'est modifiée parce qu'elle déplaît — c'est ce qui rend l'attestation crédible quand elle est favorable."),
            ("Données inexploitables : remboursé", "La pré-vérification gratuite rend le cas rare. S'il survient malgré tout après paiement, remboursement intégral."),
            ("Ce que l'audit ne fait pas", "Il ne prédit aucune performance, ne constitue pas un conseil en investissement, ne répare pas votre système et ne recommande aucun réglage. Il n'analyse que les données fournies."),
        ),
        "faq_h2": "Questions fréquentes",
        "faq": (
            ("Pourquoi payer si le moteur est gratuit ?", "Lancer le moteur vous-même vous donne le verdict. Une attestation vaut autre chose : un tiers a refait le calcul sur votre fichier et l'a inscrite à un registre public, que vos acheteurs consultent sans vous croire sur parole."),
            ("Mon code source reste-t-il confidentiel ?", "Nous n'en avons pas besoin. L'audit porte sur vos trades, pas sur votre code : vous ne transmettez jamais votre stratégie."),
            ("Pourquoi tant insister sur le nombre de variantes testées ?", "Parce que c'est la question que personne ne pose et qui élimine la majorité des systèmes. Un résultat obtenu après trois cents essais n'a pas la valeur du même résultat obtenu du premier coup. Le rapport montre à partir de combien d'essais votre résultat cesse d'être significatif."),
            ("Et si mon système est bon ?", "Vous recevez l'attestation numérotée, inscrite au registre, et les repères de drawdown : le niveau de perte au-delà duquel votre système ne se comporte plus comme dans son historique. Souvent l'élément le plus utile du rapport, même pour un système sain."),
            ("Que deviennent mes données ?", "Le fichier source est supprimé 30 jours après livraison ; l'archive conservée ne contient ni nom, ni numéro de compte, ni trade individuel. <a href=\"donnees.html\">Politique de données</a>."),
        ),
        # préparer
        "title_prepare": "Préparer votre audit",
        "prep_lead": "Ce qu'il faut envoyer, comment l'exporter, ce que vous recevez. Comptez dix minutes. Envoyez d'abord votre fichier, sans rien payer : la pré-vérification en quinze minutes dit franchement s'il est exploitable — et sinon, quoi réexporter.",
        "prep_step1": "Étape 1 — Exporter votre historique de trades",
        "prep_step1_intro": "Un seul fichier suffit. Les libellés de menus varient légèrement selon les versions ; si vous ne trouvez pas le chemin exact, envoyez une capture de votre onglet d'historique et nous vous guidons.",
        "prep_cols": ("Plateforme", "Chemin d'export", "Format"),
        "prep_rows": (
            ("MetaTrader 5 — backtest", "Strategy Tester → clic droit sur les résultats → <i>Rapport</i>", ".html ou Open XML (.xlsx)"),
            ("MetaTrader 5 — compte réel ou démo", "Boîte à outils → onglet <i>Historique</i> → période <i>Tout l'historique</i> → clic droit → <i>Rapport</i>", ".html ou .xlsx"),
            ("MetaTrader 4 — compte réel ou démo", "Terminal → onglet <i>Historique du compte</i> → période <i>Tout l'historique</i> → clic droit → <i>Enregistrer comme rapport détaillé</i>", ".html"),
            ("Deriv", "Rapports → <i>Table des profits</i> → exporter", ".csv"),
            ("Autre plateforme / fichier maison", "Un CSV, une ligne par trade clos", ".csv"),
            ("cTrader, autres", "Envoyez le fichier à la pré-vérification : nous vous dirons s'il est lu, et sinon quel export demander", "—"),
        ),
        "prep_req_h3": "Deux exigences non négociables",
        "prep_req1": "<b>L'historique complet.</b> Pas une sélection, pas une période choisie. Le moteur signale les trous, les doublons, une ruine en cours de route et un dépôt initial incohérent ; un historique tronqué fausse les conclusions et le rapport le dira.",
        "prep_req2": "<b>Le fichier d'origine, pas une capture d'écran.</b> Une image ne s'analyse pas.",
        "prep_csv_h3": "Si votre CSV est fait maison",
        "prep_csv": "Minimum : date d'ouverture, date de clôture, profit net. Utiles : sens, volume, symbole, prix d'entrée et de sortie, stop, take-profit, commission, swap, ticket. Les noms de colonnes usuels sont reconnus, en français comme en anglais ; sinon, une correspondance de colonnes vous est proposée.",
        "prep_n_h3": "Combien de trades faut-il ?",
        "prep_n": "En dessous de 30, l'audit n'a pas de sens et s'arrête (constat bloquant). En dessous de 100, les conclusions sont fragiles et le rapport le dit. L'idéal : plus de 200 trades sur au moins deux années.",
        "prep_step2": "Étape 2 — Quatre informations à donner",
        "prep_infos": (
            ("Le contexte du compte", "Capital initial et devise (lus automatiquement dans un rapport MT4/MT5), courtier, type de compte. Sans capital de départ, aucun pourcentage n'a de sens."),
            ("Combien de variantes avez-vous testées ?", "Le nombre de jeux de paramètres essayés avant cette version. Une tranche suffit : 1 à 5, 5 à 50, 50 à 300, plus de 300. C'est l'information la plus importante de l'audit : la correction du hasard en dépend. Si vous avez utilisé l'optimiseur du Strategy Tester, joignez le rapport d'optimisation, le nombre de passes y figure."),
            ("Votre objectif", "Capital personnel ou compte financé. Si propfirm : laquelle, quel type de compte, quelle taille, quel coût de challenge. Le règlement est repris depuis le site de la firme le jour de l'audit — ne le résumez pas, ces règles changent."),
            ("Ce qui vous inquiète", "Une phrase suffit : « il perd en réel alors que le backtest est bon », « je veux savoir si je peux passer un challenge », « un client me demande une validation indépendante ». Cela oriente la restitution, jamais les calculs."),
        ),
        "prep_step3": "Étape 3 — Ce que vous recevez",
        "prep_deliverables": (
            ("Le rapport", "HTML et PDF. Verdict en première page, puis « En clair : ce que dit ce rapport » — l'explication en langage courant, faite pour être lue sans nous —, barrières, constats, statistiques, simulations, régimes, repères de drawdown, conditions."),
            ("Les résultats bruts", "Un fichier JSON avec tous les chiffres, l'empreinte de vos données et la graine de calcul (selon l'offre). Tout est recalculable, y compris par quelqu'un d'autre que nous."),
            ("L'attestation", "Datée, numérotée, inscrite au registre public avec l'empreinte des données. Délivrée uniquement si le système franchit les barrières. Cessible avec la licence développeur."),
            ("L'appel de restitution", "45 minutes pour parcourir le rapport ensemble et répondre à vos questions."),
            ("Le délai", "72 heures à compter de la réception d'un dossier complet et recevable."),
            ("La langue", "Rapport en français ou en anglais, au choix."),
        ),
        "prep_rules_h2": "À lire avant de commander",
        "prep_rules": (
            ("Un NO-GO reste un NO-GO", "Le rapport est dû et payé quel que soit le verdict. Si vous cherchez une validation de complaisance, ne commandez pas."),
            ("Garantie", "Données inexploitables après paiement malgré la pré-vérification : remboursement intégral."),
            ("Ce que l'audit ne fait pas", "Aucune prédiction, aucun conseil en investissement, aucun réglage recommandé — conseiller un paramétrage reviendrait à devenir co-auteur du système évalué. Une correction de votre système donne lieu à un nouvel audit."),
        ),
        "prep_cta": "Envoyer mon fichier pour la pré-vérification gratuite",
        "prep_cta2": "Voir les offres",
        # vérification
        "title_verify": "Vérifier une attestation",
        "verify_lead": "Chaque attestation émise est inscrite ici avec l'empreinte SHA-256 du fichier de trades audité. Saisissez la référence (AUD-AAAA-NNN) ; si vous détenez le fichier d'origine, son empreinte doit correspondre exactement. Aucune donnée personnelle n'est publiée.",
        "verify_placeholder": "AUD-2026-001 ou empreinte",
        "verify_hash": "Calculer l'empreinte d'un fichier : <code>certutil -hashfile fichier.html SHA256</code> (Windows) · <code>shasum -a 256 fichier.html</code> (macOS/Linux).",
        "verify_empty": "Aucune attestation émise pour l'instant.",
        # exemples
        "title_examples": "Deux rapports d'exemple",
        "examples_lead": "Données synthétiques de démonstration, rendues par le moteur exactement comme un dossier client. Le premier est un système sain audité avec ses jeux de paramètres walk-forward et son règlement propfirm ; le second est une martingale.",
        "example_go": ("Témoin sain", "600 trades sur trois ans, cinq barrières franchies, aucun constat critique, walk-forward fourni, rejeu propfirm two-step."),
        "example_nogo": ("Martingale", "Courbe flatteuse, puis le détecteur : volume multiplié après les pertes dans 96 % des cas. Constat bloquant, barrières déclenchées, revue humaine signalée."),
        "report_html": "Rapport HTML", "pdf": "PDF",
        # documents
        "title_method": "Méthode", "title_data": "Politique de données", "title_terms": "Conditions générales",
        "doc_fr_only": "",
    },
    "en": {
        "lang_switch": ("../index.html", "Français"),
        "nav": (("index.html", "Service"), ("preparer.html", "Prepare your audit"),
                ("methode.html", "Method"), ("verification.html", "Verify an attestation"),
                ("exemples/index.html", "Samples")),
        "footer_links": (("methode.html", "Method"), ("donnees.html", "Data"),
                         ("cgv.html", "Terms"), ("verification.html", "Verification")),
        "tagline": "statistical audit of trading systems",
        "title_index": "Trading system audit",
        "hero_h1": "A verdict on your trading system that you can show.",
        "hero_lead": "Independent statistical audit of a trade history: open-source engine, published method, thresholds fixed in advance, report reproducible byte for byte, attestation anyone can verify. The engine states facts; it advises nothing and predicts nothing.",
        "cta_pre": "Start with the free pre-check",
        "cta_example": "See a report",
        "proofs_h2": "Why this verdict is worth something",
        "proofs": (
            ("Public method", "The thresholds are written before your file", "Five eliminatory barriers, eleven detectors, their parameters: everything is <a href=\"methode.html\">published</a>. A NO-GO is argued on facts, not on an opinion."),
            ("Reproducible", "Same file, same report, byte for byte", "Every report prints the SHA-256 fingerprint of your data, the method version and the seed. The engine is open source: anyone holding the file can redo the computation."),
            ("Verifiable", "A numbered attestation, a public registry", "Issued only on GO, recorded in the <a href=\"verification.html\">registry</a> with the file's fingerprint. Your clients verify it without taking your word."),
        ),
        "questions_h2": "The five questions put to your results",
        "questions": (
            ("Is chance ruled out?", "Deflated Sharpe: does the performance survive the number of variants you tried before keeping this one?"),
            ("And with bad luck?", "10,000 block replays of the same trades: in the 5 % least favourable scenarios, do you still win?"),
            ("Do the losses come clustered?", "Your drawdown compared with thousands of reorderings of the same trades."),
            ("Would a system with no edge do as well?", "Systems with no edge at all, same sizes of gains and losses: how many beat you?"),
            ("Does it hold outside the periods it was tuned on?", "Walk-forward on your parameter sets: what is left of the performance out of sample."),
        ),
        "detectors_note": "Plus eleven detectors of the way the trading is done: martingale, grid, missing stops, profit concentration, too-smooth curve, asymmetry, single-period dependence, unrealistic holding times and, with quotes, look-ahead, impossible prices, over-sensitive stop.",
        "steps_h2": "How it works",
        "steps": (
            ("You send the raw export", "MetaTrader 4 or 5 report (account or Strategy Tester), Deriv export, or a CSV with one row per trade. Never your code: the audit covers your trades. <a href=\"preparer.html\">How to export it</a>."),
            ("Free pre-check", "Within fifteen minutes: readable file, fields present, sufficient sample. If the data does not hold, you know before any money changes hands."),
            ("Audit re-run within 72 hours", "We run the engine again on your file: verdict on page one, an “In plain words” section that reads without us, barriers, findings, simulations, benchmarks. Attestation recorded in the registry on GO. A 45-minute debrief call."),
        ),
        "offers_h2": "Services",
        "offers_cols": ("Service", "Price", "Attestation", ""),
        "offer_label": {
            "moteur": "Open-source engine",
            "pre_verification": "Pre-check",
            "attestation_cessible": "Transferable attestation",
            "portefeuille": "Portfolio of systems",
            "due_diligence": "Due diligence",
            "licence_commerciale": "Commercial licence",
        },
        "offer_blurb": {
            "moteur": "The whole engine — command line, desktop window, library — and every report, to run yourself. AGPL-3.0 licence.",
            "pre_verification": "Is your file usable? Answer within fifteen minutes, before any payment.",
            "attestation_cessible": "We re-run the audit on your file; on GO, a numbered attestation in the public registry that your buyers verify themselves. Due whatever the verdict.",
            "portefeuille": "Several systems audited together, with the statistical correction for multiple selection.",
            "due_diligence": "Everything, plus an investment-committee note; scope and price on quote.",
            "licence_commerciale": "Embed the engine in a closed-source product or service, without the AGPL obligations.",
        },
        "price_free": "free", "price_quote": "on quote",
        "att_transferable": "transferable attestation", "att_go": "attestation on GO", "att_none": "—",
        "order": "Order", "send_file": "Send a file", "ask_quote": "Request a quote",
        "repo": "See the code",
        "offers_note": "The engine is the same for everyone and its code is public: the verdict depends neither on the service nor on who runs it. What you pay for is an audit re-run by a third party and recorded in a public registry.",
        "rules_h2": "The rules",
        "rules": (
            ("A NO-GO stays a NO-GO", "The report is due and paid whatever the verdict. No conclusion is changed because it displeases — that is what makes the attestation credible when it is favourable."),
            ("Unusable data: refunded", "The free pre-check makes the case rare. Should it happen after payment anyway, full refund."),
            ("What the audit does not do", "It predicts no performance, is not investment advice, does not fix your system and recommends no settings. It analyses only the data provided."),
        ),
        "faq_h2": "Frequently asked questions",
        "faq": (
            ("Why pay if the engine is free?", "Running the engine yourself gives you the verdict. An attestation is worth something else: a third party re-ran the computation on your file and recorded it in a public registry that your buyers check without taking your word."),
            ("Does my source code stay confidential?", "We do not need it. The audit covers your trades, not your code: you never hand over your strategy."),
            ("Why insist so much on the number of variants tested?", "Because it is the question nobody asks and it eliminates most systems. A result obtained after three hundred attempts is not worth the same result obtained first time. The report shows from how many attempts your result stops being significant."),
            ("And if my system is good?", "You receive the numbered attestation, recorded in the registry, and the drawdown benchmarks: the loss level beyond which your system no longer behaves as in its history. Often the most useful part of the report, even for a sound system."),
            ("What happens to my data?", "The source file is deleted 30 days after delivery; the archive kept contains no name, no account number, no individual trade. <a href=\"donnees.html\">Data policy</a>."),
        ),
        "title_prepare": "Prepare your audit",
        "prep_lead": "What to send, how to export it, what you receive. Allow ten minutes. Send your file first, without paying: the fifteen-minute pre-check says frankly whether it is usable — and if not, what to re-export.",
        "prep_step1": "Step 1 — Export your trade history",
        "prep_step1_intro": "A single file is enough. Menu labels vary slightly between versions; if you cannot find the exact path, send a screenshot of your history tab and we will guide you.",
        "prep_cols": ("Platform", "Export path", "Format"),
        "prep_rows": (
            ("MetaTrader 5 — backtest", "Strategy Tester → right-click on the results → <i>Report</i>", ".html or Open XML (.xlsx)"),
            ("MetaTrader 5 — live or demo account", "Toolbox → <i>History</i> tab → period <i>All history</i> → right-click → <i>Report</i>", ".html or .xlsx"),
            ("MetaTrader 4 — live or demo account", "Terminal → <i>Account History</i> tab → period <i>All history</i> → right-click → <i>Save as Detailed Report</i>", ".html"),
            ("Deriv", "Reports → <i>Profit table</i> → export", ".csv"),
            ("Other platform / home-made file", "A CSV, one row per closed trade", ".csv"),
            ("cTrader, others", "Send the file to the pre-check: we will tell you whether it is read and, if not, which export to request", "—"),
        ),
        "prep_req_h3": "Two non-negotiable requirements",
        "prep_req1": "<b>The complete history.</b> Not a selection, not a chosen period. The engine flags gaps, duplicates, a ruin along the way and an inconsistent initial deposit; a truncated history distorts the conclusions and the report will say so.",
        "prep_req2": "<b>The original file, not a screenshot.</b> An image cannot be analysed.",
        "prep_csv_h3": "If your CSV is home-made",
        "prep_csv": "Minimum: open time, close time, net profit. Useful: direction, volume, symbol, entry and exit prices, stop, take-profit, commission, swap, ticket. Usual column names are recognised in French and English; otherwise a column mapping is offered.",
        "prep_n_h3": "How many trades are needed?",
        "prep_n": "Below 30 the audit is meaningless and stops (blocking finding). Below 100 the conclusions are fragile and the report says so. Ideal: more than 200 trades over at least two years.",
        "prep_step2": "Step 2 — Four pieces of information",
        "prep_infos": (
            ("The account context", "Initial capital and currency (read automatically from an MT4/MT5 report), broker, account type. Without the starting capital no percentage makes sense."),
            ("How many variants did you test?", "The number of parameter sets tried before this version. A range is enough: 1 to 5, 5 to 50, 50 to 300, over 300. It is the most important piece of information of the audit: the correction for chance depends on it. If you used the Strategy Tester optimiser, attach the optimisation report, the number of passes is in it."),
            ("Your goal", "Own capital or funded account. If a propfirm: which one, which account type, which size, which challenge fee. The rulebook is taken from the firm's site on the day of the audit — do not summarise it, these rules change."),
            ("What worries you", "One sentence is enough: “it loses live while the backtest is good”, “I want to know whether I can pass a challenge”, “a client asks me for an independent validation”. It guides the debrief, never the computations."),
        ),
        "prep_step3": "Step 3 — What you receive",
        "prep_deliverables": (
            ("The report", "HTML and PDF. Verdict on page one, then “In plain words: what this report says” — the everyday-language explanation, made to be read without us —, barriers, findings, statistics, simulations, regimes, drawdown benchmarks, conditions."),
            ("The raw results", "A JSON file with every figure, the fingerprint of your data and the computation seed (depending on the service). Everything is recomputable, including by someone other than us."),
            ("The attestation", "Dated, numbered, recorded in the public registry with the data fingerprint. Issued only if the system passes the barriers. Transferable with the developer licence."),
            ("The debrief call", "45 minutes to go through the report together and answer your questions."),
            ("The deadline", "72 hours from receipt of a complete, admissible file."),
            ("The language", "Report in French or English, your choice."),
        ),
        "prep_rules_h2": "Read before ordering",
        "prep_rules": (
            ("A NO-GO stays a NO-GO", "The report is due and paid whatever the verdict. If you are looking for a rubber stamp, do not order."),
            ("Guarantee", "Data unusable after payment despite the pre-check: full refund."),
            ("What the audit does not do", "No forecast, no investment advice, no recommended settings — advising on parameters would make us co-author of the system under review. A correction of your system leads to a new audit."),
        ),
        "prep_cta": "Send my file for the free pre-check",
        "prep_cta2": "See the services",
        "title_verify": "Verify an attestation",
        "verify_lead": "Every attestation issued is recorded here with the SHA-256 fingerprint of the audited trade file. Enter the reference (AUD-YYYY-NNN); if you hold the original file, its fingerprint must match exactly. No personal data is published.",
        "verify_placeholder": "AUD-2026-001 or fingerprint",
        "verify_hash": "Compute a file's fingerprint: <code>certutil -hashfile file.html SHA256</code> (Windows) · <code>shasum -a 256 file.html</code> (macOS/Linux).",
        "verify_empty": "No attestation issued yet.",
        "title_examples": "Two sample reports",
        "examples_lead": "Synthetic demonstration data, rendered by the engine exactly like a client file. The first is a sound system audited with its walk-forward parameter sets and a propfirm rulebook; the second is a martingale.",
        "example_go": ("Healthy witness", "600 trades over three years, five barriers passed, no critical finding, walk-forward supplied, two-step propfirm replay."),
        "example_nogo": ("Martingale", "A flattering curve, then the detector: volume multiplied after losses in 96 % of cases. Blocking finding, barriers triggered, human review flagged."),
        "report_html": "HTML report", "pdf": "PDF",
        "title_method": "Method", "title_data": "Data policy", "title_terms": "Terms",
        "doc_fr_only": "This document is published in French; the French text is authoritative.",
    },
}


def t(lang: str, key: str) -> str:
    value = T[lang][key]
    assert isinstance(value, str), key
    return value


# ---------------------------------------------------------------------------
# gabarit
# ---------------------------------------------------------------------------


def shell(cfg: SiteConfig, lang: str, title: str, body: str, *, depth: int = 0,
          doc: bool = False) -> str:
    prefix = "../" * depth
    nav_items = T[lang]["nav"]
    assert isinstance(nav_items, tuple)
    nav = "".join(f'<a href="{prefix}{href}">{escape(str(label))}</a>' for href, label in nav_items)
    switch = T[lang]["lang_switch"]
    assert isinstance(switch, tuple)
    if len(cfg.languages) > 1:
        nav += f'<a class="lang" href="{prefix}{switch[0]}">{escape(str(switch[1]))}</a>'
    foot_items = T[lang]["footer_links"]
    assert isinstance(foot_items, tuple)
    foot = "".join(f'<a href="{prefix}{href}">{escape(str(label))}</a>' for href, label in foot_items)
    who = cfg.issuer or cfg.brand
    klass = ' class="wrap doc"' if doc else ' class="wrap"'
    return (
        f'<!DOCTYPE html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(title)} — {escape(cfg.brand)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f'<header class="top"><div class="wrap"><a class="brand" href="{prefix}index.html">'
        f"<i></i>{escape(cfg.brand)}</a><nav>{nav}</nav></div></header>\n"
        f"<main{klass}>\n{body}\n</main>\n"
        f'<footer><div class="wrap"><div>{foot}</div>'
        f"<div>{escape(who)} — {escape(t(lang, 'tagline'))} · "
        f'<a href="mailto:{escape(cfg.contact)}">{escape(cfg.contact)}</a></div>'
        "</div></footer>\n</body>\n</html>\n"
    )


# ---------------------------------------------------------------------------
# Markdown minimal → HTML
# ---------------------------------------------------------------------------


def _inline(text: str) -> str:
    text = escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)


def _table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    body = cells[2:] if len(cells) > 1 and set(cells[1][0]) <= set("-: ") else cells[1:]
    head = "".join(f"<th>{_inline(c)}</th>" for c in cells[0])
    trs = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{trs}</tbody></table>"


def md_to_html(markdown: str) -> str:
    out: list[str] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            out.append(f"<h{level}>{_inline(line[level:].strip())}</h{level}>")
            i += 1
        elif line.startswith("|"):
            start = i
            while i < len(lines) and lines[i].startswith("|"):
                i += 1
            out.append(_table(lines[start:i]))
        elif line.startswith("- "):
            items: list[str] = []
            while i < len(lines) and (lines[i].startswith("- ") or lines[i].startswith("  ")):
                if lines[i].startswith("- "):
                    items.append(lines[i][2:].strip())
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + "</ul>")
        elif line.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i][1:].strip())
                i += 1
            out.append(f"<blockquote>{_inline(' '.join(quote))}</blockquote>")
        elif line.startswith("---"):
            out.append("<hr>")
            i += 1
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||- |>|---)", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------


def price(p: float | None, lang: str) -> str:
    if p is None:
        return t(lang, "price_quote")
    if p == 0:
        return t(lang, "price_free")
    return f"{int(p)} €"


def _offer_action(cfg: SiteConfig, lang: str, offer: Offer) -> str:
    if offer.action == "depot":
        if not cfg.repo_url:
            return ""  # dépôt pas encore public : pas de lien
        return f'<a class="cta small ghost" href="{escape(cfg.repo_url)}">{escape(t(lang, "repo"))}</a>'
    if offer.action == "preverification":
        return f'<a class="cta small" href="{escape(cfg.preverification(lang))}">{escape(t(lang, "send_file"))}</a>'
    if offer.action == "devis":
        return f'<a class="cta small ghost" href="{escape(cfg.order(lang))}">{escape(t(lang, "ask_quote"))}</a>'
    return f'<a class="cta small" href="{escape(cfg.pay(offer.code, lang))}">{escape(t(lang, "order"))}</a>'


def _cards(items: object, *, kicker: bool = False) -> str:
    assert isinstance(items, tuple)
    out = []
    for item in items:
        if kicker:
            k, h, p = item
            out.append(f'<div class="card"><div class="k">{escape(k)}</div><h3>{escape(h)}</h3><p>{p}</p></div>')
        else:
            h, p = item
            out.append(f'<div class="card"><h3>{escape(h)}</h3><p>{p}</p></div>')
    return "".join(out)


def page_index(cfg: SiteConfig, lang: str) -> str:
    labels = T[lang]["offer_label"]
    blurbs = T[lang]["offer_blurb"]
    assert isinstance(labels, dict)
    assert isinstance(blurbs, dict)
    attestations = {"cessible": t(lang, "att_transferable"), "go": t(lang, "att_go"), "": t(lang, "att_none")}
    rows = [
        f"<tr><td><b>{escape(str(labels[offer.code]))}</b><br><span class='muted small'>"
        f"{escape(str(blurbs.get(offer.code, '')))}</span></td>"
        f"<td class='price'>{price(offer.price_eur, lang)}</td>"
        f"<td>{escape(attestations[offer.attestation])}</td><td>{_offer_action(cfg, lang, offer)}</td></tr>"
        for offer in cfg.offers
    ]
    cols = T[lang]["offers_cols"]
    assert isinstance(cols, tuple)
    head = "".join(f"<th>{escape(str(c))}</th>" for c in cols)
    questions = T[lang]["questions"]
    assert isinstance(questions, tuple)
    q_cards = "".join(f'<div class="card"><p class="q">{escape(q)}</p><p>{escape(d)}</p></div>'
                      for q, d in questions)
    faq = T[lang]["faq"]
    assert isinstance(faq, tuple)
    faq_html = "".join(f"<h3>{escape(q)}</h3><p>{a}</p>" for q, a in faq)
    return f"""
<section class="hero">
  <h1>{escape(t(lang, "hero_h1"))}</h1>
  <p class="lead">{escape(t(lang, "hero_lead"))}</p>
  <a class="cta" href="{escape(cfg.preverification(lang))}">{escape(t(lang, "cta_pre"))}</a>
  <a class="cta ghost" href="exemples/index.html">{escape(t(lang, "cta_example"))}</a>
</section>
<section><h2>{escape(t(lang, "proofs_h2"))}</h2><div class="grid c3">{_cards(T[lang]["proofs"], kicker=True)}</div></section>
<section><h2>{escape(t(lang, "questions_h2"))}</h2><div class="grid c2">{q_cards}</div>
  <p class="muted small">{escape(t(lang, "detectors_note"))}</p></section>
<section><h2>{escape(t(lang, "steps_h2"))}</h2><div class="grid c3 steps">{_cards(T[lang]["steps"])}</div></section>
<section id="offres"><h2>{escape(t(lang, "offers_h2"))}</h2>
  <table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>
  <p class="muted small">{escape(t(lang, "offers_note"))}</p></section>
<section class="rules"><h2>{escape(t(lang, "rules_h2"))}</h2><div class="grid c3">{_cards(T[lang]["rules"])}</div></section>
<section><h2>{escape(t(lang, "faq_h2"))}</h2>{faq_html}</section>
"""


def page_preparer(cfg: SiteConfig, lang: str) -> str:
    cols = T[lang]["prep_cols"]
    rows = T[lang]["prep_rows"]
    assert isinstance(cols, tuple)
    assert isinstance(rows, tuple)
    head = "".join(f"<th>{escape(str(c))}</th>" for c in cols)
    body = "".join(f"<tr><td><b>{escape(a)}</b></td><td>{b}</td><td>{escape(c)}</td></tr>" for a, b, c in rows)
    return f"""
<section class="hero"><h1>{escape(t(lang, "title_prepare"))}</h1><p class="lead">{escape(t(lang, "prep_lead"))}</p>
  <a class="cta" href="{escape(cfg.preverification(lang))}">{escape(t(lang, "prep_cta"))}</a></section>
<section><h2>{escape(t(lang, "prep_step1"))}</h2><p>{escape(t(lang, "prep_step1_intro"))}</p>
  <table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
  <h3>{escape(t(lang, "prep_req_h3"))}</h3><p>{t(lang, "prep_req1")}</p><p>{t(lang, "prep_req2")}</p>
  <h3>{escape(t(lang, "prep_csv_h3"))}</h3><p>{escape(t(lang, "prep_csv"))}</p>
  <h3>{escape(t(lang, "prep_n_h3"))}</h3><p>{escape(t(lang, "prep_n"))}</p></section>
<section><h2>{escape(t(lang, "prep_step2"))}</h2><div class="grid c2 steps">{_cards(T[lang]["prep_infos"])}</div></section>
<section><h2>{escape(t(lang, "prep_step3"))}</h2><div class="grid c3">{_cards(T[lang]["prep_deliverables"])}</div></section>
<section class="rules"><h2>{escape(t(lang, "prep_rules_h2"))}</h2><div class="grid c3">{_cards(T[lang]["prep_rules"])}</div>
  <p style="margin-top:22px"><a class="cta" href="{escape(cfg.preverification(lang))}">{escape(t(lang, "prep_cta"))}</a>
  <a class="cta ghost" href="index.html#offres">{escape(t(lang, "prep_cta2"))}</a></p></section>
"""


def page_verification(lang: str, registry_html: str) -> str:
    table = re.search(r"<table>.*?</table>", registry_html, re.S)
    found = table.group(0) if table else ""
    body = found if found and "<tbody></tbody>" not in found else (
        f"<p class='muted'>{escape(t(lang, 'verify_empty'))}</p>"
    )
    return f"""
<section class="hero"><h1>{escape(t(lang, "title_verify"))}</h1><p class="lead">{escape(t(lang, "verify_lead"))}</p>
  <div class="search"><input id="q" placeholder="{escape(t(lang, "verify_placeholder"))}" autocomplete="off"></div>
  <p class="muted small">{t(lang, "verify_hash")}</p></section>
<section id="registre">{body}</section>
<script>
(function(){{var q=document.getElementById('q');var rows=[].slice.call(document.querySelectorAll('#registre tbody tr'));
q.addEventListener('input',function(){{var v=q.value.trim().toLowerCase();rows.forEach(function(r){{r.style.display=!v||r.textContent.toLowerCase().indexOf(v)>=0?'':'none';}});}});}})();
</script>
"""


def page_examples(lang: str) -> str:
    go = T[lang]["example_go"]
    nogo = T[lang]["example_nogo"]
    assert isinstance(go, tuple)
    assert isinstance(nogo, tuple)
    return f"""
<section class="hero"><h1>{escape(t(lang, "title_examples"))}</h1><p class="lead">{escape(t(lang, "examples_lead"))}</p></section>
<section><div class="grid c2">
  <div class="card"><span class="chip go">GO</span><h3>{escape(go[0])}</h3><p>{escape(go[1])}</p>
    <p><a href="temoin-sain.html">{escape(t(lang, "report_html"))}</a> · <a href="temoin-sain.pdf">{escape(t(lang, "pdf"))}</a></p></div>
  <div class="card"><span class="chip nogo">NO-GO</span><h3>{escape(nogo[0])}</h3><p>{escape(nogo[1])}</p>
    <p><a href="martingale.html">{escape(t(lang, "report_html"))}</a> · <a href="martingale.pdf">{escape(t(lang, "pdf"))}</a></p></div>
</div></section>
"""


# ---------------------------------------------------------------------------
# assemblage
# ---------------------------------------------------------------------------


def _write(path: Path, text: str) -> None:
    """UTF-8, fins de ligne LF quelle que soit la plateforme."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _run(*args: str, check: bool = True) -> str:
    result = subprocess.run([PYTHON, "-m", "qaudit", *args], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", check=False)
    if check and result.returncode not in (0, 1, 2):
        raise RuntimeError(result.stderr)
    return result.stdout


def _examples(root: Path, lang: str) -> None:
    demo = ROOT / "build" / f"site-demo-{lang}"
    if demo.exists():
        shutil.rmtree(demo)
    _run("demo", "--out", str(demo), "--lang", lang)
    for stem, target in (("healthy_witness", "temoin-sain"), ("martingale", "martingale")):
        _run("render", "--from", str(demo / "archive" / f"{stem}.json"), "--out",
             str(demo / "render"), "--offre", "audit_complet", "--name", target, "--lang", lang,
             "--registry", str(demo / "registre-demo.jsonl"))
        for ext in ("html", "pdf"):
            (root / "exemples").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(demo / "render" / f"{target}.{ext}", root / "exemples" / f"{target}.{ext}")


def build_lang(cfg: SiteConfig, lang: str, root: Path, depth: int, registry: Path | None) -> None:
    _examples(root, lang)
    methode = _run("methode", "--lang", lang)
    _write(root / "methode.html", shell(cfg, lang, t(lang, "title_method"), md_to_html(methode), depth=depth, doc=True))
    note = f"<p class='note'>{escape(t(lang, 'doc_fr_only'))}</p>" if t(lang, "doc_fr_only") else ""
    for name, target, title in (("politique-donnees", "donnees.html", t(lang, "title_data")),
                                ("cgv-modele", "cgv.html", t(lang, "title_terms"))):
        md = (ROOT / "docs" / f"{name}.md").read_text(encoding="utf-8")
        _write(root / target, shell(cfg, lang, title, note + md_to_html(md), depth=depth, doc=True))
    reg_html = root / "_registre.html"
    reg_args = ["--registry", str(registry)] if registry else []
    _run("registre", "--lang", lang, "--html", str(reg_html), *reg_args)
    registry_html = reg_html.read_text(encoding="utf-8")
    reg_html.unlink()
    _write(root / "verification.html", shell(cfg, lang, t(lang, "title_verify"),
                                              page_verification(lang, registry_html), depth=depth))
    _write(root / "index.html", shell(cfg, lang, t(lang, "title_index"), page_index(cfg, lang), depth=depth))
    _write(root / "preparer.html", shell(cfg, lang, t(lang, "title_prepare"), page_preparer(cfg, lang), depth=depth))
    _write(root / "exemples" / "index.html", shell(cfg, lang, t(lang, "title_examples"), page_examples(lang), depth=depth + 1))


def build(out: Path, registry: Path | None, config: Path | None = None) -> None:
    cfg = load_config(config or ROOT / "site.toml")
    out.mkdir(parents=True, exist_ok=True)
    for lang in cfg.languages:
        root = out if lang == cfg.languages[0] else out / lang
        build_lang(cfg, lang, root, 0 if lang == cfg.languages[0] else 1, registry)
    print(f"site : {out} ({len(list(out.rglob('*.html')))} pages, {', '.join(cfg.languages)})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "site")
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    build(args.out, args.registry, args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
