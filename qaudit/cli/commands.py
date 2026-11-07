# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sous-commandes de la CLI : audit, batch, render, validate, demo, profils,
rulesets, ruleset-skeleton, mapping-skeleton. Chaque commande retourne le code
de sortie ; les erreurs du noyau remontent à ``main`` qui les traduit."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from importlib import resources
from pathlib import Path

from qaudit.cli.exitcodes import DECISION_EXIT, ExitCode
from qaudit.core.audit import AuditOptions, AuditResult, run_audit
from qaudit.core.config import MethodConfig
from qaudit.core.models import Decision, PriceSeries
from qaudit.core.propfirm import Ruleset
from qaudit.core.validate import ValidationResult, validate
from qaudit.core.walkforward import Candidate, WalkForwardInput
from qaudit.i18n import Catalog
from qaudit.io import batch as batch_mod
from qaudit.io.document import Json, loads
from qaudit.io.mapping import MappingStore, resolve_mapping
from qaudit.io.mapping import skeleton as mapping_skeleton
from qaudit.io.method import load_method
from qaudit.io.outputs import issue_attestation, maybe_attest, write_deliverables, write_outputs
from qaudit.io.profile import (
    DEFAULT_PROFILE,
    Profile,
    builtin_profiles,
    load_profile,
    missing_inputs,
)
from qaudit.io.readers import read_table
from qaudit.io.readers.prices import read_prices
from qaudit.io.registry import Registry
from qaudit.io.ruleset import builtin_names, load_ruleset
from qaudit.io.ruleset import skeleton as ruleset_skeleton
from qaudit.io.writers.attestation import registry_page
from qaudit.io.writers.methode import render_methode
from qaudit.io.writers.render import Fmt


def _say(text: str) -> None:
    print(text)


def _warn_missing_inputs(
    profile: Profile, document: Json, catalog: Catalog,
    provided: frozenset[str] = frozenset(),
) -> None:
    """Sur stderr : l'offre exige des entrées que le dossier n'a pas. Le rapport
    est tout de même rendu (il dit lui-même ce qui manque) ; le code de sortie
    reste celui du verdict."""
    missing = missing_inputs(profile, document, provided)
    if missing:
        print(
            catalog.text("cli.offer_missing_inputs", offer=profile.code,
                         inputs=", ".join(catalog.text(f"input.{i}") for i in missing)),
            file=sys.stderr,
        )


def _options(args: argparse.Namespace) -> AuditOptions:
    return AuditOptions(
        seed=args.seed,
        n_iter=args.n_iter,
        n_trials=args.n_trials,
        var_sr=args.var_sr,
        bootstrap_method=args.bootstrap,
        horizon_trading_days=args.horizon_days,
        pnl_scale=args.pnl_scale,
    )


def load_validated(
    path: Path,
    config: MethodConfig,
    *,
    kind: str,
    mapping_file: Path | None,
    store: MappingStore | None,
    initial_balance: float | None,
    currency: str | None,
) -> ValidationResult:
    """Lecture, correspondance (E1) et validation ; mémorise une correspondance
    explicite une fois qu'elle a permis de construire le jeu de trades."""
    table = read_table(path, kind)
    mapping, origin = resolve_mapping(table, mapping_file, store)
    validation = validate(
        table,
        mapping,
        max_gap_days=config.max_gap_days,
        initial_balance=initial_balance,
        currency=currency,
    )
    if origin == "explicit" and store is not None:
        store.save(table.columns, mapping)
    return validation


def load_walkforward(
    folder: Path,
    config: MethodConfig,
    initial_balance: float | None,
    kind: str,
    mapping_file: Path | None = None,
    store: MappingStore | None = None,
) -> WalkForwardInput:
    candidates = []
    for path in sorted(p for p in folder.iterdir() if p.suffix.lower() in BATCH_SUFFIXES):
        table = read_table(path, kind)
        mapping, _ = resolve_mapping(table, mapping_file, store)
        ts = validate(
            table, mapping, max_gap_days=config.max_gap_days, initial_balance=initial_balance
        ).tradeset
        candidates.append(Candidate(path.stem, ts))
    return WalkForwardInput(tuple(candidates))


def _print_verdict(result: AuditResult, catalog: Catalog, paths: Sequence[Path]) -> None:
    verdict = result.verdict
    fmt = Fmt(catalog)
    _say(
        catalog.text(
            "cli.verdict",
            decision=catalog.text(f"decision.{verdict.decision.value}"),
            blocking=verdict.blocking_count,
            major=verdict.major_count,
        )
    )
    _say(f"revue_humaine: {'true' if verdict.human_review else 'false'}")
    for barrier in verdict.barriers:
        if barrier.evaluated and barrier.indecision:
            _say(
                catalog.text(
                    "cli.boundary",
                    name=catalog.text(barrier.message_key),
                    value=fmt.num(barrier.value, 4),
                    low=fmt.num(barrier.band_low, 3),
                    high=fmt.num(barrier.band_high, 3),
                )
            )
    for path in paths:
        _say(catalog.text("cli.written", path=str(path)))


def cmd_audit(args: argparse.Namespace, catalog: Catalog) -> int:
    config = load_method(args.method)
    store = MappingStore(args.cache_dir)
    validation = load_validated(
        args.file,
        config,
        kind=args.kind,
        mapping_file=args.mapping,
        store=store,
        initial_balance=args.initial_balance,
        currency=args.currency,
    )
    prices: PriceSeries | None = None
    if args.prices is not None:
        prices = read_prices(args.prices, args.symbol)
    ruleset: Ruleset | None = load_ruleset(args.ruleset) if args.ruleset else None
    walkforward = None
    if args.walkforward is not None:
        walkforward = load_walkforward(
            args.walkforward, config, args.initial_balance, args.kind, args.mapping, store
        )
    result = run_audit(
        validation, config, _options(args), prices=prices, walkforward=walkforward, ruleset=ruleset
    )
    profile = load_profile(args.offre)
    name = args.name or args.file.stem
    document, written = write_outputs(result, args.out, catalog, profile, system_name=name)
    _warn_missing_inputs(profile, document, catalog)
    entry, attested = maybe_attest(
        document, args.out, catalog, profile, system_name=name,
        registry=Registry(args.registry), issued_on=_issued_on(args),
        holder=args.holder, issuer=args.issuer,
    )
    _print_verdict(result, catalog, (written.archive, *written.deliverables, *attested))
    if entry is not None:
        _say(catalog.text("attestation.issued", reference=entry.reference))
    return int(DECISION_EXIT[result.verdict.decision])


def _issued_on(args: argparse.Namespace) -> date:
    raw = getattr(args, "issued_on", None)
    return date.fromisoformat(raw) if raw else date.today()


BATCH_SUFFIXES = (".csv", ".txt", ".html", ".htm", ".xlsx")


def _batch_paths(inputs: Sequence[Path]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        if item.is_dir():
            paths.extend(sorted(p for p in item.iterdir() if p.suffix.lower() in BATCH_SUFFIXES))
        else:
            paths.append(item)
    return paths


def cmd_batch(args: argparse.Namespace, catalog: Catalog) -> int:
    config = load_method(args.method)
    paths = _batch_paths(args.inputs)
    alpha = config.barrier("null_pvalue").threshold
    result = batch_mod.run_batch(
        paths,
        options=_options(args),
        jobs=args.jobs,
        alpha=alpha,
        initial_balance=args.initial_balance,
        currency=args.currency,
        kind=args.kind,
        mapping_path=args.mapping,
        cache_dir=args.cache_dir,
        method_path=args.method,
    )
    profile = load_profile(args.offre)
    summary_path = batch_mod.write_batch(result, args.out, catalog, profile)
    for document in result.documents.values():
        _warn_missing_inputs(profile, document, catalog, frozenset({"portefeuille"}))
    counts = result.summary["counts"]
    _say(
        catalog.text(
            "cli.batch_done",
            n=len(result.documents),
            errors=len(result.errors),
            go=counts["GO"],
            cond=counts["GO_CONDITIONAL"],
            nogo=counts["NO_GO"],
            survive=result.summary["n_survive_bh"],
        )
    )
    for name, key in sorted(result.errors.items()):
        _say(catalog.text("cli.batch_error", system=name, message=catalog.text(key)))
    _say(catalog.text("cli.written", path=str(summary_path)))
    if result.errors:
        return int(ExitCode.INVALID_DATA)
    worst = max(
        (DECISION_EXIT[Decision(d["decision"])] for d in result.summary["systems"]),
        default=ExitCode.GO,
    )
    return int(worst)


def cmd_render(args: argparse.Namespace, catalog: Catalog) -> int:
    document = loads(Path(args.source).read_text(encoding="utf-8"))
    profile = load_profile(args.offre)
    name = args.name or Path(args.source).stem
    written = write_deliverables(document, args.out, catalog, profile, system_name=name)
    _warn_missing_inputs(profile, document, catalog)
    entry, attested = maybe_attest(
        document, args.out, catalog, profile, system_name=name,
        registry=Registry(args.registry), issued_on=_issued_on(args),
        holder=args.holder, issuer=args.issuer,
    )
    for path in (*written, *attested):
        _say(catalog.text("cli.written", path=str(path)))
    if entry is not None:
        _say(catalog.text("attestation.issued", reference=entry.reference))
    return int(DECISION_EXIT[Decision(document["verdict"]["decision"])])


def cmd_attest(args: argparse.Namespace, catalog: Catalog) -> int:
    """Émet (ou ré-émet à l'identique) l'attestation d'une archive GO."""
    document = loads(Path(args.source).read_text(encoding="utf-8"))
    profile = load_profile(args.offre)
    name = args.name or Path(args.source).stem
    decision = Decision(document["verdict"]["decision"])
    if decision is not Decision.GO:
        label = catalog.text(f"decision.{decision.value}")
        print(catalog.text("attestation.refused", decision=label), file=sys.stderr)
        return int(DECISION_EXIT[decision])
    entry, written = issue_attestation(
        document, args.out, catalog, profile, system_name=name,
        registry=Registry(args.registry), issued_on=_issued_on(args),
        holder=args.holder, issuer=args.issuer,
    )
    for path in written:
        _say(catalog.text("cli.written", path=str(path)))
    _say(catalog.text("attestation.issued", reference=entry.reference))
    return int(ExitCode.GO)


def cmd_verify(args: argparse.Namespace, catalog: Catalog) -> int:
    """Vérification d'une référence : l'entrée du registre, ou code 20 si inconnue."""
    entry = Registry(args.registry).lookup(args.reference)
    _say(
        catalog.text(
            "attestation.verify_line", reference=entry.reference, issued_on=entry.issued_on,
            system=entry.system_name, decision=catalog.text(f"decision.{entry.decision}"),
            method=entry.method_version, engine=entry.engine_version,
            fingerprint=entry.fingerprint,
        )
    )
    return int(ExitCode.GO)


def cmd_registre(args: argparse.Namespace, catalog: Catalog) -> int:
    """Liste des attestations émises ; ``--html`` écrit la page publique de vérification."""
    entries = Registry(args.registry).entries()
    for entry in entries:
        short = entry.fingerprint[:16]
        _say(f"{entry.reference}  {entry.issued_on}  {entry.system_name}  {short}…")
    if args.html is not None:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(registry_page(entries, catalog), encoding="utf-8")
        _say(catalog.text("cli.written", path=str(args.html)))
    _say(catalog.text("attestation.registry.footer", n=len(entries)))
    return int(ExitCode.GO)


def cmd_validate(args: argparse.Namespace, catalog: Catalog) -> int:
    config = load_method(args.method)
    validation = load_validated(
        args.file,
        config,
        kind=args.kind,
        mapping_file=args.mapping,
        store=MappingStore(args.cache_dir),
        initial_balance=args.initial_balance,
        currency=args.currency,
    )
    ts = validation.tradeset
    _say(
        catalog.text(
            "cli.validated",
            n=ts.n,
            fingerprint=ts.fingerprint,
            currency=ts.currency,
            fields=", ".join(sorted(ts.known_fields)),
        )
    )
    for finding in validation.findings:
        params = dict(finding.params)
        _say(
            f"[{catalog.text('severity.' + finding.severity.name.lower())}] "
            f"{finding.code} — {catalog.text(finding.message_key, **params)}"
        )
    return int(ExitCode.GO)


def _demo_file(name: str) -> Path:
    return Path(str(resources.files("qaudit.demo").joinpath(name)))


def cmd_demo(args: argparse.Namespace, catalog: Catalog) -> int:
    """Deux audits hors ligne sur les données embarquées : témoin sain (avec
    walk-forward) attendu GO, martingale attendue NO-GO."""
    config = load_method(None)
    out = args.out
    expected = {"healthy_witness": Decision.GO, "martingale": Decision.NO_GO}
    obtained: dict[str, Decision] = {}
    for name, wanted in expected.items():
        validation = load_validated(
            _demo_file(f"{name}.csv"),
            config,
            kind="auto",
            mapping_file=None,
            store=None,
            initial_balance=10_000.0,
            currency="USD",
        )
        walkforward = None
        if name == "healthy_witness":
            walkforward = load_walkforward(_demo_file("walkforward"), config, 10_000.0, "auto")
        result = run_audit(
            validation, config, AuditOptions(seed=args.seed), walkforward=walkforward
        )
        _, written = write_outputs(
            result, out, catalog, load_profile(DEFAULT_PROFILE), system_name=name
        )
        obtained[name] = result.verdict.decision
        _say(
            catalog.text(
                "cli.demo_line",
                system=name,
                decision=catalog.text(f"decision.{result.verdict.decision.value}"),
                expected=catalog.text(f"decision.{wanted.value}"),
                path=str(written.deliverables[0]),
            )
        )
    if obtained != expected:
        _say(catalog.text("cli.demo_mismatch"))
        return int(ExitCode.INTERNAL_ERROR)
    return int(ExitCode.GO)


def cmd_methode(args: argparse.Namespace, catalog: Catalog) -> int:
    """Document public de la méthode (Markdown) généré depuis la configuration chargée."""
    text = render_methode(load_method(args.method), catalog)
    if args.write is not None:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(text, encoding="utf-8", newline="\n")
        _say(catalog.text("cli.written", path=str(args.write)))
    else:
        sys.stdout.write(text)
    return int(ExitCode.GO)


def cmd_gui(args: argparse.Namespace, catalog: Catalog) -> int:
    """``qaudit gui [fichier] [options]`` : ouvre l'application graphique depuis
    l'exécutable console. Raison d'être : Smart App Control refuse volontiers un
    binaire fenêtré non signé alors qu'il laisse passer le binaire console ; la
    console est masquée quand ce processus en est le seul occupant (double-clic)."""
    from qaudit.gui import app as gui_app  # import tardif : tkinter n'est chargé qu'ici

    gui_app.hide_own_console()
    return gui_app.main(["--lang", catalog.lang, *args.gui_args])


def cmd_profils(args: argparse.Namespace, catalog: Catalog) -> int:
    for code in builtin_profiles():
        profile = load_profile(code)
        _say(f"{profile.code:22} {profile.label}  [{len(profile.sections)} sections]")
    return int(ExitCode.GO)


def cmd_rulesets(args: argparse.Namespace, catalog: Catalog) -> int:
    for name in builtin_names():
        ruleset = load_ruleset(name)
        _say(f"{name:26} {ruleset.as_of}  {ruleset.name}  ({len(ruleset.phases)} phases)")
    return int(ExitCode.GO)


def cmd_ruleset_skeleton(args: argparse.Namespace, catalog: Catalog) -> int:
    sys.stdout.write(ruleset_skeleton())
    return int(ExitCode.GO)


def cmd_mapping_skeleton(args: argparse.Namespace, catalog: Catalog) -> int:
    table = read_table(args.file, args.kind)
    sys.stdout.write(mapping_skeleton(table.columns))
    return int(ExitCode.GO)


def e1_payload(seen: tuple[str, ...], missing: tuple[str, ...], fingerprint: str) -> str:
    """JSON de la porte E1 : colonnes vues, champs manquants, empreinte d'en-tête."""
    return json.dumps(
        {
            "gate": "E1",
            "exit_code": int(ExitCode.NEEDS_MAPPING),
            "seen_columns": list(seen),
            "missing_fields": list(missing),
            "header_fingerprint": fingerprint,
            "resume_with": "--mapping fichier.toml",
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
