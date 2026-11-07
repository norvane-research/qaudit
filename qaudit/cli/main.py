# SPDX-License-Identifier: AGPL-3.0-or-later
"""Point d'entrée ``qaudit`` : analyse des arguments, dispatch, codes de sortie.

Codes (N-11) : 0 GO · 1 GO sous conditions · 2 NO-GO · 10 porte E1 (colonnes
non reconnues, JSON sur la sortie standard, reprise par ``--mapping``) · 11
porte E2 (règlement absent ou non structuré, squelette TOML sur la sortie
standard) · 20 données invalides (ligne et colonne nommées) · 30 erreur interne.
"""

from __future__ import annotations

import argparse
import codecs
import io
import os
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from qaudit import ENGINE_VERSION, i18n
from qaudit.cli import commands
from qaudit.cli.exitcodes import ExitCode, exit_code_for
from qaudit.core.errors import DataError, QauditError, RulesetError, SchemaError
from qaudit.i18n import Catalog
from qaudit.io.mapping import header_fingerprint
from qaudit.io.profile import DEFAULT_PROFILE
from qaudit.io.readers import KINDS
from qaudit.io.ruleset import skeleton as ruleset_skeleton


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lang", choices=i18n.LANGUAGES, default=i18n.DEFAULT_LANGUAGE)
    parser.add_argument("--out", type=Path, default=Path("qaudit-out"))
    parser.add_argument("--offre", default=DEFAULT_PROFILE)
    parser.add_argument("--method", type=Path, default=None)


def _attestation(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--holder", default=None)
    parser.add_argument("--issuer", default=None)
    parser.add_argument("--issued-on", default=None)  # AAAA-MM-JJ ; défaut : aujourd'hui


def _inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--kind", choices=KINDS, default="auto")
    parser.add_argument("--mapping", type=Path, default=None)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--initial-balance", type=float, default=None)
    parser.add_argument("--currency", default=None)


def _simulation(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-iter", type=int, default=None)
    parser.add_argument("--n-trials", type=int, default=None)
    parser.add_argument("--var-sr", type=float, default=None)
    parser.add_argument("--bootstrap", choices=("stationary", "iid"), default=None)
    parser.add_argument("--horizon-days", type=int, default=None)
    parser.add_argument("--pnl-scale", type=float, default=None)


def exit_codes_help(catalog: Catalog) -> str:
    """Texte d'aide listant les codes de sortie (N-11), dans la langue demandée."""
    lines = [catalog.text("cli.exit_codes_title")]
    lines.extend(f"  {catalog.text(code.message_key)}" for code in ExitCode)
    return chr(10).join(lines)


def _lang_from_argv(argv: Sequence[str] | None) -> str:
    """Langue demandée (``--lang`` avant ou après la sous-commande), lue avant
    l'analyse complète pour traduire l'aide ; source unique de la langue."""
    args = list(sys.argv[1:] if argv is None else argv)
    for i, item in enumerate(args):
        if item == "--lang" and i + 1 < len(args) and args[i + 1] in i18n.LANGUAGES:
            return args[i + 1]
        if item.startswith("--lang=") and item[7:] in i18n.LANGUAGES:
            return item[7:]
    return i18n.DEFAULT_LANGUAGE


def build_parser(catalog: Catalog | None = None) -> argparse.ArgumentParser:
    catalog = catalog or i18n.load(i18n.DEFAULT_LANGUAGE)
    parser = argparse.ArgumentParser(
        prog="qaudit",
        description=catalog.text("cli.description", version=ENGINE_VERSION),
        epilog=exit_codes_help(catalog),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"qaudit {ENGINE_VERSION}")
    parser.add_argument("--lang", choices=i18n.LANGUAGES, default=i18n.DEFAULT_LANGUAGE)
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit")
    audit.add_argument("file", type=Path)
    audit.add_argument("--prices", type=Path, default=None)
    audit.add_argument("--symbol", default=None)
    audit.add_argument("--ruleset", default=None)
    audit.add_argument("--walkforward", type=Path, default=None)
    audit.add_argument("--name", default=None)
    _common(audit)
    _inputs(audit)
    _simulation(audit)
    _attestation(audit)
    audit.set_defaults(func=commands.cmd_audit)

    batch = sub.add_parser("batch")
    batch.add_argument("inputs", type=Path, nargs="+")
    batch.add_argument("--jobs", type=int, default=4)
    _common(batch)
    _inputs(batch)
    _simulation(batch)
    batch.set_defaults(func=commands.cmd_batch)

    render = sub.add_parser("render")
    render.add_argument("--from", dest="source", type=Path, required=True)
    render.add_argument("--name", default=None)
    _common(render)
    _attestation(render)
    render.set_defaults(func=commands.cmd_render)

    attest = sub.add_parser("attest")
    attest.add_argument("--from", dest="source", type=Path, required=True)
    attest.add_argument("--name", default=None)
    _common(attest)
    _attestation(attest)
    attest.set_defaults(func=commands.cmd_attest)

    verify = sub.add_parser("verify")
    verify.add_argument("reference")
    verify.add_argument("--registry", type=Path, default=None)
    _common(verify)
    verify.set_defaults(func=commands.cmd_verify)

    registre = sub.add_parser("registre")
    registre.add_argument("--registry", type=Path, default=None)
    registre.add_argument("--html", type=Path, default=None)
    _common(registre)
    registre.set_defaults(func=commands.cmd_registre)

    validate = sub.add_parser("validate")
    validate.add_argument("file", type=Path)
    _common(validate)
    _inputs(validate)
    validate.set_defaults(func=commands.cmd_validate)

    demo = sub.add_parser("demo")
    demo.add_argument("--seed", type=int, default=0)
    _common(demo)
    demo.set_defaults(func=commands.cmd_demo)

    for name, func in (
        ("profils", commands.cmd_profils),
        ("rulesets", commands.cmd_rulesets),
        ("ruleset-skeleton", commands.cmd_ruleset_skeleton),
    ):
        simple = sub.add_parser(name)
        _common(simple)
        simple.set_defaults(func=func)

    methode = sub.add_parser("methode")
    methode.add_argument("--write", type=Path, default=None)
    _common(methode)
    methode.set_defaults(func=commands.cmd_methode)

    gui = sub.add_parser("gui")
    gui.add_argument("gui_args", nargs=argparse.REMAINDER)
    gui.set_defaults(func=commands.cmd_gui)

    mapping = sub.add_parser("mapping-skeleton")
    mapping.add_argument("file", type=Path)
    mapping.add_argument("--kind", choices=KINDS, default="auto")
    _common(mapping)
    mapping.set_defaults(func=commands.cmd_mapping_skeleton)
    return parser


def _location(error: DataError, catalog: Catalog) -> str:
    if error.row is not None and error.column is not None:
        return catalog.text("location.row_column", row=error.row, column=error.column)
    if error.row is not None:
        return catalog.text("location.row", row=error.row)
    if error.column is not None:
        return catalog.text("location.column", column=error.column)
    return catalog.text("location.file")


def _report_error(error: QauditError, catalog: Catalog) -> int:
    """Traduit une erreur du noyau en message et code de sortie ; les portes E1
    et E2 déposent en plus leur charge utile sur la sortie standard."""
    code = exit_code_for(error)
    message = catalog.text(error.key, **dict(error.params))
    if isinstance(error, SchemaError):
        print(
            commands.e1_payload(
                error.seen_columns, error.missing_fields, header_fingerprint(error.seen_columns)
            )
        )
    elif isinstance(error, RulesetError):
        sys.stdout.write(ruleset_skeleton())
    elif isinstance(error, DataError):
        message = f"{_location(error, catalog)} : {message}"
    print(f"qaudit [{int(code)}] {message}", file=sys.stderr)
    return int(code)


def utf8_output() -> None:
    """Sorties standard en UTF-8 sur toutes les plateformes. Sous Windows, une
    sortie redirigée prend sinon le code page ANSI (cp1252 en général) et un
    caractère comme « → » fait échouer la commande. Un choix explicite de
    l'utilisateur (PYTHONIOENCODING) est respecté."""
    if os.environ.get("PYTHONIOENCODING"):
        return
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and codecs.lookup(stream.encoding).name != "utf-8":
            stream.reconfigure(encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    utf8_output()
    catalog = i18n.load(_lang_from_argv(argv))
    parser = build_parser(catalog)
    args = parser.parse_args(argv)
    try:
        return int(args.func(args, catalog))
    except QauditError as error:
        return _report_error(error, catalog)
    except Exception as error:  # noqa: BLE001 — dernier recours : nommé, tracé, code 30
        traceback.print_exc()
        print(
            f"qaudit [{int(ExitCode.INTERNAL_ERROR)}] {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return int(ExitCode.INTERNAL_ERROR)


if __name__ == "__main__":
    sys.exit(main())
