# SPDX-License-Identifier: AGPL-3.0-or-later
"""Profils d'offre (F-410) : quelles sections du rapport sont livrées.

Le noyau calcule tout ; le profil ne fait que filtrer le rendu (règle R4 : la
notion d'offre n'existe pas sous ``core/``). Le verdict ne dépend jamais du
profil (R1), les sections obligatoires sont irretirables (R2), un constat
critique traverse tous les profils (R3), le JSON intégral est toujours archivé
(R5).
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from qaudit.core.errors import DataError

SECTIONS: tuple[str, ...] = (
    "entete",
    "verdict",
    "en_clair",
    "kpi",
    "barrieres",
    "constats_critiques",
    "constats_complets",
    "sharpe_degonfle",
    "sensibilite_essais",
    "monte_carlo",
    "regimes",
    "walkforward",
    "detecteurs_prix",
    "propfirm_challenge",
    "propfirm_finance",
    "propfirm_economie",
    "seuil_arret",
    "conditions",
    "portefeuille",
    "note_comite",
    "portee_et_limites",
    "pied",
)
MANDATORY: tuple[str, ...] = (
    "entete",
    "verdict",
    "constats_critiques",
    "portee_et_limites",
    "pied",
)
INPUTS: tuple[str, ...] = (
    "trades",
    "prix",
    "reglement",
    "taille_compte",
    "frais_challenge",
    "walkforward",
    "portefeuille",
)


@dataclass(frozen=True, slots=True)
class Profile:
    code: str
    label: str
    required_inputs: tuple[str, ...]
    optional_inputs: tuple[str, ...]
    sections: tuple[str, ...]
    html: bool
    pdf: bool
    json: bool
    attestation: bool
    attestation_transferable: bool

    def includes(self, section: str) -> bool:
        return section in self.sections


def missing_inputs(
    profile: Profile, document: Mapping[str, Any], provided: frozenset[str] = frozenset()
) -> tuple[str, ...]:
    """Entrées requises par l'offre mais absentes du dossier audité — l'offre
    livrerait alors des sections qui disent seulement « non effectué ».
    Chaque entrée est lue dans le document archivé (jamais recalculée) ;
    ``provided`` nomme celles connues du contexte d'appel (le lot fournit
    « portefeuille »)."""
    data = document["data"]
    present = {
        "trades": True,
        "prix": bool(data.get("prices_provided")),
        "reglement": document.get("propfirm") is not None,
        "taille_compte": data.get("initial_balance") is not None,
        "frais_challenge": True,  # jamais requis ; sa valeur n'est pas dans le document
        "walkforward": document.get("walkforward") is not None,
        "portefeuille": "portefeuille" in provided,
    }
    return tuple(i for i in profile.required_inputs if not present.get(i, True))


def _require(table: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in table:
        raise DataError("profile.missing_key", column=f"{where}.{key}")
    return table[key]


def parse_profile(raw: Mapping[str, Any]) -> Profile:
    """Construit un profil ; rejette toute section inconnue et tout profil
    omettant une section obligatoire, en la nommant."""
    offer = _require(raw, "offre", "")
    inputs = _require(raw, "entrees", "")
    report = _require(raw, "rapport", "")
    deliverables = _require(raw, "livrables", "")
    sections = tuple(str(s) for s in _require(report, "sections", "rapport"))
    unknown = tuple(s for s in sections if s not in SECTIONS)
    if unknown:
        raise DataError("profile.unknown_section", column=", ".join(unknown))
    missing = tuple(s for s in MANDATORY if s not in sections)
    if missing:
        raise DataError("profile.missing_mandatory_section", column=", ".join(missing))
    ordered = tuple(s for s in SECTIONS if s in sections)  # ordre canonique
    return Profile(
        code=str(_require(offer, "code", "offre")),
        label=str(_require(offer, "libelle", "offre")),
        required_inputs=tuple(str(x) for x in inputs.get("requis", ())),
        optional_inputs=tuple(str(x) for x in inputs.get("optionnel", ())),
        sections=ordered,
        html=bool(deliverables.get("html", True)),
        pdf=bool(deliverables.get("pdf", False)),
        json=bool(deliverables.get("json", False)),
        attestation=bool(deliverables.get("attestation", False)),
        attestation_transferable=bool(deliverables.get("attestation_cessible", False)),
    )


def builtin_profiles() -> tuple[str, ...]:
    root = resources.files("qaudit.io.profils")
    return tuple(sorted(p.name[:-5] for p in root.iterdir() if p.name.endswith(".toml")))


def load_profile(source: str | Path) -> Profile:
    """Charge un profil embarqué (par code) ou un fichier TOML."""
    if isinstance(source, str) and source in builtin_profiles():
        text = (
            resources.files("qaudit.io.profils")
            .joinpath(f"{source}.toml")
            .read_text(encoding="utf-8")
        )
        return parse_profile(tomllib.loads(text))
    path = Path(source)
    if not path.exists():
        raise DataError("profile.not_found", column=str(path))
    return parse_profile(tomllib.loads(path.read_text(encoding="utf-8")))


DEFAULT_PROFILE = "audit_complet"
