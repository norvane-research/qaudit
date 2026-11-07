# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contrôleur de l'application PC : toute la logique, aucun widget.

La fenêtre (``qaudit.gui.app``) ne fait que collecter une ``AuditRequest``,
appeler ``run_request`` dans un fil d'arrière-plan et afficher l'``Outcome``.
Le contrôleur emprunte exactement le chemin de la ligne de commande
(``qaudit.cli.commands``) : mêmes lecteurs, même correspondance E1 mémorisée,
même moteur, mêmes rapports — un audit lancé depuis la fenêtre et un audit
lancé en console produisent le même JSON.

Les trois portes d'escalade remontent comme des résultats typés, jamais comme
des exceptions vers l'interface : ``MappingNeeded`` (E1), ``RulesetNeeded``
(E2) ; la porte E3 est portée par ``AuditDone.human_review``.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from pathlib import Path

from qaudit import ENGINE_VERSION
from qaudit.cli.commands import load_validated, load_walkforward
from qaudit.core.audit import AuditOptions, AuditResult, run_audit
from qaudit.core.errors import DataError, QauditError, RulesetError, SchemaError
from qaudit.core.models import ALL_FIELDS, REQUIRED_FIELDS, PriceSeries
from qaudit.core.propfirm import Ruleset
from qaudit.i18n import Catalog
from qaudit.io.document import Json, loads
from qaudit.io.mapping import MappingStore, header_fingerprint, mapping_toml
from qaudit.io.method import load_method
from qaudit.io.outputs import maybe_attest, write_deliverables, write_outputs
from qaudit.io.profile import (
    DEFAULT_PROFILE,
    Profile,
    builtin_profiles,
    load_profile,
    missing_inputs,
)
from qaudit.io.readers import KINDS, read_table
from qaudit.io.readers.prices import read_prices
from qaudit.io.registry import Registry
from qaudit.io.ruleset import builtin_names, load_ruleset
from qaudit.io.ruleset import skeleton as ruleset_skeleton

NO_RULESET = ""
Log = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class AuditRequest:
    """Ce que la fenêtre collecte. Les chemins vides valent « absent »."""

    trades: Path
    out_dir: Path
    lang: str = "fr"
    kind: str = "auto"
    initial_balance: float | None = None
    currency: str | None = None
    prices: Path | None = None
    symbol: str | None = None
    walkforward: Path | None = None
    ruleset: str = NO_RULESET  # nom embarqué, chemin de fichier, ou vide
    profile: str = DEFAULT_PROFILE
    seed: int = 0
    n_iter: int | None = None
    n_trials: int | None = None
    mapping: Path | None = None
    cache_dir: Path | None = None
    system_name: str | None = None
    registry: Path | None = None  # registre des attestations (défaut : ~/.qaudit)
    holder: str | None = None
    issuer: str | None = None

    @property
    def name(self) -> str:
        return self.system_name or self.trades.stem


@dataclass(frozen=True, slots=True)
class AuditDone:
    result: AuditResult
    document: Json
    archive: Path
    deliverables: tuple[Path, ...]
    warning: str | None = None  # offre exigeant une entrée absente du dossier

    @property
    def decision(self) -> str:
        return self.result.verdict.decision.value

    @property
    def human_review(self) -> bool:
        return self.result.verdict.human_review


@dataclass(frozen=True, slots=True)
class MappingNeeded:
    """Porte E1 : colonnes vues, champs manquants, empreinte de l'en-tête."""

    seen_columns: tuple[str, ...]
    missing_fields: tuple[str, ...]
    header_fingerprint: str


@dataclass(frozen=True, slots=True)
class RulesetNeeded:
    """Porte E2 : règlement absent / en prose / incomplet ; squelette à compléter."""

    message: str
    skeleton: str
    missing_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Failed:
    """Données invalides (20) ou erreur interne (30), message déjà traduit."""

    exit_code: int
    message: str
    detail: str = ""


Outcome = AuditDone | MappingNeeded | RulesetNeeded | Failed


@dataclass(frozen=True, slots=True)
class Choices:
    """Listes proposées par la fenêtre."""

    kinds: tuple[str, ...] = KINDS
    profiles: tuple[str, ...] = field(default_factory=builtin_profiles)
    rulesets: tuple[str, ...] = field(default_factory=builtin_names)
    languages: tuple[str, ...] = ("fr", "en")
    fields: tuple[str, ...] = ALL_FIELDS
    required_fields: tuple[str, ...] = REQUIRED_FIELDS


def profile_label(code: str) -> str:
    profile: Profile = load_profile(code)
    return f"{profile.label} ({profile.code})"


def _location(error: DataError, catalog: Catalog) -> str:
    if error.row is not None and error.column is not None:
        return catalog.text("location.row_column", row=error.row, column=error.column)
    if error.row is not None:
        return catalog.text("location.row", row=error.row)
    if error.column is not None:
        return catalog.text("location.column", column=error.column)
    return catalog.text("location.file")


def _failed(error: QauditError, catalog: Catalog) -> Failed:
    from qaudit.cli.exitcodes import exit_code_for

    message = catalog.text(error.key, **dict(error.params))
    if isinstance(error, DataError):
        message = f"{_location(error, catalog)} : {message}"
    return Failed(int(exit_code_for(error)), message)


def _ruleset(request: AuditRequest) -> Ruleset | None:
    if not request.ruleset:
        return None
    return load_ruleset(request.ruleset)


def run_request(request: AuditRequest, catalog: Catalog, log: Log | None = None) -> Outcome:
    """Exécute la demande du début à la fin ; ne lève jamais vers l'interface."""
    say = log or (lambda _text: None)
    try:
        config = load_method(None)
        store = MappingStore(request.cache_dir)
        say(catalog.text("gui.log.reading", path=str(request.trades)))
        validation = load_validated(
            request.trades,
            config,
            kind=request.kind,
            mapping_file=request.mapping,
            store=store,
            initial_balance=request.initial_balance,
            currency=request.currency,
        )
        say(catalog.text("gui.log.validated", n=validation.tradeset.n))
        prices: PriceSeries | None = None
        if request.prices is not None:
            prices = read_prices(request.prices, request.symbol or None)
            say(catalog.text("gui.log.prices", n=prices.n))
        walkforward = None
        if request.walkforward is not None:
            walkforward = load_walkforward(
                request.walkforward, config, request.initial_balance, request.kind,
                request.mapping, store,
            )
            say(catalog.text("gui.log.walkforward", n=len(walkforward.candidates)))
        ruleset = _ruleset(request)
        say(catalog.text("gui.log.running", n_iter=request.n_iter or config.n_iter))
        result = run_audit(
            validation,
            config,
            AuditOptions(seed=request.seed, n_iter=request.n_iter, n_trials=request.n_trials),
            prices=prices,
            walkforward=walkforward,
            ruleset=ruleset,
        )
        profile = load_profile(request.profile)
        document, written = write_outputs(
            result, request.out_dir, catalog, profile, system_name=request.name,
        )
    except SchemaError as error:
        return MappingNeeded(
            error.seen_columns, error.missing_fields, header_fingerprint(error.seen_columns)
        )
    except RulesetError as error:
        return RulesetNeeded(
            catalog.text(error.key, **dict(error.params)), ruleset_skeleton(), error.missing_keys
        )
    except QauditError as error:
        return _failed(error, catalog)
    except Exception as error:  # noqa: BLE001 — dernier recours, nommé et affiché (code 30)
        return Failed(30, f"{type(error).__name__}: {error}")
    say(catalog.text("gui.log.written", path=str(written.archive)))
    warning = offer_warning(profile, document, catalog)
    if warning:
        say(warning)
    entry, attested = maybe_attest(
        document, request.out_dir, catalog, profile, system_name=request.name,
        registry=Registry(request.registry), issued_on=date.today(),
        holder=request.holder, issuer=request.issuer,
    )
    if entry is not None:
        say(catalog.text("attestation.issued", reference=entry.reference))
    return AuditDone(result, document, written.archive, (*written.deliverables, *attested), warning)


def offer_warning(profile: Profile, document: Json, catalog: Catalog) -> str | None:
    """Texte d'avertissement si l'offre exige des entrées absentes du dossier
    (même message que la ligne de commande), sinon ``None``."""
    missing = missing_inputs(profile, document)
    if not missing:
        return None
    return catalog.text(
        "cli.offer_missing_inputs", offer=profile.code,
        inputs=", ".join(catalog.text(f"input.{i}") for i in missing),
    )


def demo_folder() -> Path:
    """Dossier des données de démonstration embarquées (témoin sain, martingale)."""
    return Path(str(resources.files("qaudit.demo")))


def exit_code_of(done: AuditDone) -> int:
    from qaudit.cli.exitcodes import DECISION_EXIT

    return int(DECISION_EXIT[done.result.verdict.decision])


def table_columns(path: Path, kind: str) -> tuple[str, ...]:
    """Colonnes vues dans un fichier (pour l'éditeur de correspondance E1)."""
    return read_table(path, kind).columns


def save_mapping(
    path: Path, mapping: Mapping[str, str], columns: tuple[str, ...]
) -> Path:
    """Écrit une correspondance choisie dans l'éditeur E1 (TOML ``[fields]``)."""
    clean = {k: v for k, v in mapping.items() if v}
    path.write_text(mapping_toml(clean, columns), encoding="utf-8")
    return path


def render_archive(
    archive: Path, out_dir: Path, catalog: Catalog, profile: str
) -> tuple[Json, tuple[Path, ...]]:
    """Rend un document archivé sans recalcul (équivalent de ``render --from``)."""
    document = loads(archive.read_text(encoding="utf-8"))
    loaded = load_profile(profile)
    written = write_deliverables(document, out_dir, catalog, loaded, system_name=archive.stem)
    return document, written


def list_archives(out_dir: Path) -> tuple[Path, ...]:
    folder = out_dir / "archive"
    if not folder.is_dir():
        return ()
    return tuple(sorted(folder.glob("*.json")))


def archive_summary(archive: Path) -> dict[str, str]:
    """Quelques champs d'un document archivé pour la liste d'historique."""
    document = loads(archive.read_text(encoding="utf-8"))
    verdict = document["verdict"]
    data = document["data"]
    return {
        "name": archive.stem,
        "decision": str(verdict["decision"]),
        "human_review": "E3" if verdict["revue_humaine"] else "",
        "n_trades": str(data["n_trades"]),
        "period": f"{data['first_open'] or '—'} → {data['last_close'] or '—'}",
        "seed": str(document["seed"]),
        "method": str(document["method_version"]),
    }


def open_path(path: Path) -> None:
    """Ouvre un fichier ou un dossier avec l'application associée du système."""
    if sys.platform.startswith("win"):
        import os

        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def about_text(catalog: Catalog) -> str:
    from qaudit.cli.exitcodes import ExitCode

    lines = [
        catalog.text("gui.about", version=ENGINE_VERSION),
        "",
        catalog.text("cli.exit_codes_title"),
    ]
    lines.extend(f"  {catalog.text(code.message_key)}" for code in ExitCode)
    return "\n".join(lines)
