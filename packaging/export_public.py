# SPDX-License-Identifier: AGPL-3.0-or-later
"""Export public du dépôt : sans historique, sans documents internes, sans
donnée personnelle.

Copie les fichiers du dossier de travail que git suit ou suivrait (``git
ls-files --cached --others --exclude-standard``), sauf ceux des préfixes privés
(``interne/``), vers un dossier cible. Avant toute copie, cherche des données
personnelles : chemins de poste, adresses e-mail réelles, et les motifs privés
de ``interne/motifs-prives.txt`` (une expression régulière par ligne, jamais
exportée). Un seul constat suffit à refuser l'export. Seule exception : l'adresse
de contact publiée par le site (``contact`` de ``site.toml``), qui est publique.
Les adresses sont cherchées en ASCII : les octets d'une image lus en latin-1 ne
forment pas de fausses adresses avec des lettres accentuées.

Avec ``--commit --author "Nom <email>"``, initialise un dépôt git neuf (branche
``main``) et crée un unique commit sous cette identité : l'historique privé,
dont les métadonnées portent l'adresse personnelle de l'auteur, ne part jamais.
``--commit`` est refusé tant que ``NOTICE`` contient le marqueur « à compléter ».

Avec ``--update``, met à jour un dépôt créé par un export précédent (marqueur
exclu dans ``.git/info/exclude``) : ``.git`` est gardé, les fichiers sortis de
l'export sont retirés, rien n'est commité. On relit ``git status`` et ``git diff``
dans le dépôt avant de commiter soi-même.

Rien n'est publié : aucun remote n'est ajouté, rien n'est poussé.

    python packaging/export_public.py [--out ../qaudit-public] [--commit --author "Nom <email>"]
    python packaging/export_public.py --update [--out ../qaudit-public]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_PREFIXES = ("interne/",)
PRIVATE_PATTERNS_FILE = "interne/motifs-prives.txt"
MARKER = ".qaudit-export"
PLACEHOLDER = "à compléter"
EXAMPLE_DOMAINS = ("exemple.com", "example.com", "example.org", "example.net")

GENERIC_PATTERNS = (
    (re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"'<>]+"), "chemin de poste Windows"),
    (re.compile(r"/(?:home|Users)/[a-z][\w.-]*/"), "chemin de poste Unix"),
)
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", re.ASCII)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    reason: str
    excerpt: str


def list_files(root: Path) -> list[str]:
    """Fichiers suivis ou suivables (ni ignorés ni supprimés), hors préfixes privés."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    names = sorted({n for n in out.split("\0") if n})
    return [n for n in names
            if not n.startswith(PRIVATE_PREFIXES) and (root / n).is_file()]


def load_private_patterns(root: Path) -> list[re.Pattern[str]]:
    path = root / PRIVATE_PATTERNS_FILE
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [re.compile(line.strip(), re.IGNORECASE) for line in lines
            if line.strip() and not line.lstrip().startswith("#")]


def public_addresses(root: Path) -> frozenset[str]:
    """L'adresse de contact que le site publie (``[site] contact`` de site.toml)."""
    path = root / "site.toml"
    if not path.exists():
        return frozenset()
    site = tomllib.loads(path.read_text(encoding="utf-8")).get("site", {})
    contact = str(site.get("contact", "")).strip().lower()
    return frozenset({contact} if contact else set())


def _is_personal(m: re.Match[str], public: frozenset[str]) -> bool:
    return m.group(1).lower() not in EXAMPLE_DOMAINS and m.group(0).lower() not in public


def _line_findings(name: str, number: int, line: str, private: list[re.Pattern[str]],
                   public: frozenset[str] = frozenset()) -> list[Finding]:
    found = [Finding(name, number, reason, hit.group(0))
             for pattern, reason in GENERIC_PATTERNS if (hit := pattern.search(line))]
    found.extend(Finding(name, number, "adresse e-mail", m.group(0))
                 for m in EMAIL.finditer(line) if _is_personal(m, public))
    found.extend(Finding(name, number, "motif privé", hit.group(0))
                 for pattern in private if (hit := pattern.search(line)))
    return found


def scan(root: Path, names: list[str], private: list[re.Pattern[str]],
         public: frozenset[str] = frozenset()) -> list[Finding]:
    """Cherche les données personnelles ligne par ligne ; les fichiers binaires
    sont lus en latin-1 pour que rien n'échappe au motif."""
    findings: list[Finding] = []
    for name in names:
        text = (root / name).read_bytes().decode("latin-1")
        for number, line in enumerate(text.splitlines(), start=1):
            findings.extend(_line_findings(name, number, line, private, public))
    return findings


def prepare_target(out: Path) -> None:
    """Le dossier cible doit être absent, vide, ou un export précédent (marqueur)
    qui n'est pas devenu un dépôt git — un dépôt n'est jamais écrasé."""
    if out.exists() and any(out.iterdir()):
        if (out / ".git").exists():
            raise SystemExit(f"refus : {out} contient un dépôt git ; il n'est jamais écrasé")
        if not (out / MARKER).exists():
            raise SystemExit(f"refus : {out} n'est pas vide et n'est pas un export précédent")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)


def sync_repository(out: Path, names: list[str]) -> list[str]:
    """Prépare la mise à jour d'un dépôt créé par un export : ``.git`` est gardé ;
    seuls les fichiers suivis par ce dépôt qui ne font plus partie de l'export sont
    retirés (rendus triés). Les fichiers non suivis (constructions locales, etc.)
    ne sont jamais touchés."""
    exclude = out / ".git" / "info" / "exclude"
    if not exclude.is_file() or MARKER not in exclude.read_text(encoding="utf-8").split():
        raise SystemExit(f"refus : {out} n'est pas un dépôt créé par un export")
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=out, capture_output=True,
                             check=True).stdout.decode("utf-8").split("\0")
    removed = sorted(rel for rel in tracked if rel and rel not in set(names))
    for rel in removed:
        (out / rel).unlink(missing_ok=True)
        parent = (out / rel).parent
        while parent != out and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return removed


def copy_files(root: Path, names: list[str], out: Path) -> None:
    for name in names:
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    (out / MARKER).write_text("Dossier produit par packaging/export_public.py.\n", encoding="utf-8")


def parse_author(author: str) -> tuple[str, str]:
    m = re.fullmatch(r"\s*([^<>]+?)\s*<([^<>\s]+@[^<>\s]+)>\s*", author)
    if m is None:
        raise SystemExit('refus : --author attend la forme "Nom <email>"')
    return m.group(1), m.group(2)


def commit(out: Path, author: str, message: str) -> None:
    name, email = parse_author(author)
    env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=out, env=env, check=True)
    with (out / ".git" / "info" / "exclude").open("a", encoding="utf-8") as exclude:
        exclude.write(f"{MARKER}\n")  # le marqueur d'export reste hors du dépôt
    for args in (["add", "-A"], ["commit", "-q", "--no-gpg-sign", "-m", message]):
        subprocess.run(["git", *args], cwd=out, env=env, check=True)


def export(root: Path, out: Path, *, author: str | None = None, update: bool = False,
           message: str = "qaudit — première publication") -> list[Finding]:
    """Exporte ; rend les constats (export refusé s'il y en a)."""
    if update and author is not None:
        raise SystemExit("refus : --update ne commite pas ; relire puis commiter dans le dépôt")
    names = list_files(root)
    findings = scan(root, names, load_private_patterns(root), public_addresses(root))
    if findings:
        return findings
    if author is not None and PLACEHOLDER in (root / "NOTICE").read_text(encoding="utf-8"):
        raise SystemExit("refus : NOTICE contient encore le marqueur « à compléter » "
                         "(titulaire des droits)")
    if update:
        for rel in sync_repository(out, names):
            print(f"retiré : {rel}")
    else:
        prepare_target(out)
    copy_files(root, names, out)
    if author is not None:
        commit(out, author, message)
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, default=ROOT.parent / "qaudit-public")
    parser.add_argument("--commit", action="store_true", help="dépôt git neuf, un seul commit")
    parser.add_argument("--author", help='identité du commit : "Nom <email>"')
    parser.add_argument("--update", action="store_true",
                        help="met à jour un dépôt créé par un export, sans commiter")
    args = parser.parse_args(argv)
    if args.commit and not args.author:
        parser.error("--commit exige --author")
    if args.commit and args.update:
        parser.error("--update et --commit s'excluent")
    findings = export(ROOT, args.out.resolve(), author=args.author if args.commit else None,
                      update=args.update)
    for f in findings:
        print(f"{f.path}:{f.line}: {f.reason} : {f.excerpt}", file=sys.stderr)
    if findings:
        print(f"export refusé : {len(findings)} constat(s)", file=sys.stderr)
        return 1
    print(f"export : {args.out.resolve()} ({len(list_files(ROOT))} fichiers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
