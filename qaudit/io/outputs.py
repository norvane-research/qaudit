# SPDX-License-Identifier: AGPL-3.0-or-later
"""Écriture des sorties d'un audit : archive JSON intégrale (toujours, règle
R5), puis livrables selon le profil d'offre (HTML, PDF, JSON livré).

Le rendu HTML/PDF part du document JSON, jamais de l'objet de calcul : un
``render --from archive.json`` produit exactement les mêmes octets qu'un audit
direct (test T-410e).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from qaudit.core.audit import AuditResult
from qaudit.i18n import Catalog
from qaudit.io.document import Json, dumps, to_document
from qaudit.io.profile import Profile
from qaudit.io.registry import Entry, Registry
from qaudit.io.writers.attestation import attestation_view
from qaudit.io.writers.html_writer import render_html
from qaudit.io.writers.pdf_writer import render_pdf
from qaudit.io.writers.render import build_view

ARCHIVE_DIR = "archive"


@dataclass(frozen=True, slots=True)
class Written:
    archive: Path
    deliverables: tuple[Path, ...]


def render_outputs(
    document: Mapping[str, Any], catalog: Catalog, profile: Profile, *, system_name: str
) -> dict[str, bytes]:
    """Livrables en mémoire : ``{"html": ..., "pdf": ..., "json": ...}`` selon le profil."""
    view = build_view(document, catalog, profile, system_name=system_name)
    out: dict[str, bytes] = {}
    if profile.html:
        out["html"] = render_html(view).encode("utf-8")
    if profile.pdf:
        out["pdf"] = render_pdf(view)
    if profile.json:
        out["json"] = dumps(document).encode("utf-8")
    return out


def write_document(document: Mapping[str, Any], out_dir: Path, system_name: str) -> Path:
    """Archive le document intégral (toujours, quel que soit le profil)."""
    archive = out_dir / ARCHIVE_DIR
    archive.mkdir(parents=True, exist_ok=True)
    path = archive / f"{system_name}.json"
    path.write_bytes(dumps(document).encode("utf-8"))
    return path


def write_deliverables(
    document: Mapping[str, Any],
    out_dir: Path,
    catalog: Catalog,
    profile: Profile,
    *,
    system_name: str,
) -> tuple[Path, ...]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for ext, payload in render_outputs(document, catalog, profile, system_name=system_name).items():
        path = out_dir / f"{system_name}.{ext}"
        path.write_bytes(payload)
        written.append(path)
    return tuple(written)


def write_outputs(
    result: AuditResult, out_dir: Path, catalog: Catalog, profile: Profile, *, system_name: str
) -> tuple[Json, Written]:
    """Archive puis livrables ; retourne le document et les chemins écrits."""
    document = to_document(result)
    archive = write_document(document, out_dir, system_name)
    deliverables = write_deliverables(document, out_dir, catalog, profile, system_name=system_name)
    return document, Written(archive, deliverables)


ATTESTATION_SUFFIX = "-attestation"


def issue_attestation(
    document: Mapping[str, Any],
    out_dir: Path,
    catalog: Catalog,
    profile: Profile,
    *,
    system_name: str,
    registry: Registry,
    issued_on: date,
    holder: str | None = None,
    issuer: str | None = None,
) -> tuple[Entry, tuple[Path, ...]]:
    """Inscrit l'attestation au registre (verdict GO exigé, sinon
    ``DataError("attestation.refused")``) et écrit ``<nom>-attestation.html/.pdf``."""
    entry = registry.issue(
        document, system_name=system_name, profile=profile.code,
        transferable=profile.attestation_transferable, issued_on=issued_on,
        holder=holder, issuer=issuer,
    )
    view = attestation_view(document, entry, catalog, profile)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for ext, payload in (("html", render_html(view).encode("utf-8")), ("pdf", render_pdf(view))):
        path = out_dir / f"{system_name}{ATTESTATION_SUFFIX}.{ext}"
        path.write_bytes(payload)
        written.append(path)
    return entry, tuple(written)


def maybe_attest(
    document: Mapping[str, Any],
    out_dir: Path,
    catalog: Catalog,
    profile: Profile,
    *,
    system_name: str,
    registry: Registry | None,
    issued_on: date,
    holder: str | None = None,
    issuer: str | None = None,
) -> tuple[Entry | None, tuple[Path, ...]]:
    """Attestation automatique des offres qui la livrent : seulement si le
    verdict est GO et qu'un registre est fourni ; sinon rien, sans erreur."""
    if registry is None or not profile.attestation:
        return None, ()
    if str(document["verdict"]["decision"]) != "GO":
        return None, ()
    return issue_attestation(
        document, out_dir, catalog, profile, system_name=system_name, registry=registry,
        issued_on=issued_on, holder=holder, issuer=issuer,
    )
