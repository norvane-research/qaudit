# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registre des attestations émises : un fichier JSON Lines, une ligne par
attestation, numérotation ``AUD-<année>-<NNN>``.

Le registre est l'état d'émission (référence, date, titulaire) — il ne fait pas
partie du calcul : le rapport et l'archive restent identiques avec ou sans
attestation. Idempotence : la même empreinte de données, auditée avec la même
version de méthode et de moteur, reçoit toujours la même référence (pas de
doublon d'attestation pour un même dossier).

Emplacement par défaut : ``~/.qaudit/registre.jsonl`` (même racine que la
mémoire des correspondances) ; surchargeable par ``--registry``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from qaudit.core.errors import DataError
from qaudit.io.mapping import default_home

REGISTRY_FILE = "registre.jsonl"
REFERENCE_PREFIX = "AUD"


@dataclass(frozen=True, slots=True)
class Entry:
    reference: str
    issued_on: str  # ISO 8601, date seule
    system_name: str
    fingerprint: str
    decision: str
    engine_version: str
    method_version: str
    profile: str
    transferable: bool
    n_trades: int
    first_open: str
    last_close: str
    holder: str | None = None
    issuer: str | None = None

    def public(self) -> dict[str, Any]:
        """Champs publiables sur une page de vérification : jamais le titulaire."""
        return {
            "reference": self.reference,
            "issued_on": self.issued_on,
            "system_name": self.system_name,
            "fingerprint": self.fingerprint,
            "decision": self.decision,
            "engine_version": self.engine_version,
            "method_version": self.method_version,
            "transferable": self.transferable,
        }


def default_registry_path(override: Path | None = None) -> Path:
    return override if override is not None else default_home() / REGISTRY_FILE


class Registry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = default_registry_path(path)

    def entries(self) -> tuple[Entry, ...]:
        if not self.path.exists():
            return ()
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return tuple(Entry(**json.loads(line)) for line in lines if line.strip())

    def find(self, fingerprint: str, method_version: str, engine_version: str) -> Entry | None:
        for entry in self.entries():
            if (entry.fingerprint, entry.method_version, entry.engine_version) == (
                fingerprint, method_version, engine_version,
            ):
                return entry
        return None

    def lookup(self, reference: str) -> Entry:
        wanted = reference.strip().upper()
        for entry in self.entries():
            if entry.reference == wanted:
                return entry
        raise DataError("attestation.not_found", reference=reference)

    def next_reference(self, year: int) -> str:
        prefix = f"{REFERENCE_PREFIX}-{year}-"
        count = sum(1 for e in self.entries() if e.reference.startswith(prefix))
        return f"{REFERENCE_PREFIX}-{year}-{count + 1:03d}"

    def issue(
        self,
        document: Mapping[str, Any],
        *,
        system_name: str,
        profile: str,
        transferable: bool,
        issued_on: date,
        holder: str | None = None,
        issuer: str | None = None,
    ) -> Entry:
        """Inscrit l'attestation d'un document GO ; renvoie l'entrée existante si
        ce dossier (empreinte + versions) a déjà été attesté."""
        decision = str(document["verdict"]["decision"])
        if decision != "GO":
            raise DataError("attestation.refused", decision=decision)
        data = document["data"]
        existing = self.find(
            str(data["fingerprint"]), str(document["method_version"]),
            str(document["engine_version"]),
        )
        if existing is not None:
            return existing
        entry = Entry(
            reference=self.next_reference(issued_on.year),
            issued_on=issued_on.isoformat(),
            system_name=system_name,
            fingerprint=str(data["fingerprint"]),
            decision=decision,
            engine_version=str(document["engine_version"]),
            method_version=str(document["method_version"]),
            profile=profile,
            transferable=transferable,
            n_trades=int(data["n_usable"]),
            first_open=str(data["first_open"] or ""),
            last_close=str(data["last_close"] or ""),
            holder=holder,
            issuer=issuer,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry), ensure_ascii=False, sort_keys=True) + "\n")
        return entry
