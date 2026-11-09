# SPDX-License-Identifier: AGPL-3.0-or-later
"""Export public : préfixes privés exclus, données personnelles refusées,
dépôt neuf à un seul commit sous l'identité choisie, aucun dépôt écrasé."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _module() -> ModuleType:
    path = ROOT / "packaging" / "export_public.py"
    spec = importlib.util.spec_from_file_location("export_public", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["export_public"] = module
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


def _source(tmp_path: Path, notice: str = "Copyright (C) 2026 <à compléter>\n") -> Path:
    """Petit dépôt : un fichier suivi, un non suivi, un ignoré, deux privés."""
    root = tmp_path / "src"
    (root / "docs").mkdir(parents=True)
    (root / "interne").mkdir()
    (root / "README.md").write_text("qaudit\ncontact@exemple.com\n", encoding="utf-8")
    (root / "NOTICE").write_text(notice, encoding="utf-8")
    (root / "docs" / "a.md").write_text("doc\n", encoding="utf-8")
    (root / "interne" / "kit.md").write_text("interne\n", encoding="utf-8")
    (root / "interne" / "motifs-prives.txt").write_text("# privé\nmotprive\n", encoding="utf-8")
    (root / ".gitignore").write_text("ignore.txt\n", encoding="utf-8")
    (root / "ignore.txt").write_text("x\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "README.md", "NOTICE", ".gitignore", "interne")
    return root  # docs/a.md reste non suivi mais suivable


def test_export_copies_public_files_only_and_can_be_repeated(tmp_path: Path) -> None:
    ep = _module()
    root, out = _source(tmp_path), tmp_path / "out"
    assert ep.export(root, out) == []
    copied = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert copied == [".gitignore", ".qaudit-export", "NOTICE", "README.md", "docs/a.md"]
    assert ep.export(root, out) == []  # un export précédent se remplace


def test_export_refuses_a_folder_that_is_not_a_previous_export(tmp_path: Path) -> None:
    ep = _module()
    root, out = _source(tmp_path), tmp_path / "out"
    out.mkdir()
    (out / "travail.txt").write_text("ne pas effacer\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="n'est pas vide"):
        ep.export(root, out)
    assert (out / "travail.txt").exists()


def test_personal_data_blocks_the_export(tmp_path: Path) -> None:
    ep = _module()
    root, out = _source(tmp_path), tmp_path / "out"
    drive_path = "C:" + "\\Users\\" + "bob\\AUDIT"  # assemblé : rien de tel dans ce fichier
    address = "jean" + "@" + "mail.fr"
    (root / "docs" / "a.md").write_text(f"{drive_path}\n{address}\nmotprive\n", encoding="utf-8")
    findings = ep.export(root, out)
    reasons = {f.reason for f in findings}
    assert reasons == {"chemin de poste Windows", "adresse e-mail", "motif privé"}
    assert all(f.path == "docs/a.md" for f in findings)
    assert not out.exists()  # rien n'est copié


def test_published_contact_and_image_bytes_do_not_block(tmp_path: Path) -> None:
    ep = _module()
    root, out = _source(tmp_path), tmp_path / "out"
    contact = "equipe" + "@" + "studio-x.fr"
    (root / "site.toml").write_text(f'[site]\ncontact = "{contact}"\n', encoding="utf-8")
    (root / "docs" / "a.md").write_text(f"Écrire à {contact.upper()}\n", encoding="utf-8")
    (root / "docs" / "img.png").write_bytes(b"\x89PNG\r\n\xe9\xcc@\xe0.\xe7\xe8\n")
    assert ep.export(root, out) == []
    other = "jean" + "@" + "studio-x.fr"  # une autre adresse du même domaine reste refusée
    (root / "docs" / "a.md").write_text(f"{other}\n", encoding="utf-8")
    assert [f.excerpt for f in ep.export(root, tmp_path / "out2")] == [other]


def test_update_refreshes_an_exported_repository_without_committing(tmp_path: Path) -> None:
    ep = _module()
    root, out = _source(tmp_path, notice="Copyright (C) 2026 Studio X\n"), tmp_path / "out"
    assert ep.export(root, out, author="Studio X <contact@example.org>") == []
    (root / "docs" / "a.md").unlink()
    (root / "docs" / "b.md").write_text("nouveau\n", encoding="utf-8")
    (out / "local.tmp").write_text("construction locale\n", encoding="utf-8")
    with (out / ".git" / "info" / "exclude").open("a", encoding="utf-8") as exclude:
        exclude.write("local.tmp\n")  # ignoré : la vérification de statut reste exacte
    assert ep.export(root, out, update=True) == []
    assert (out / "docs" / "b.md").exists()
    assert not (out / "docs" / "a.md").exists()
    assert (out / "local.tmp").exists()  # un fichier non suivi n'est jamais touché
    assert len(_git(out, "log", "--format=%H").split()) == 1  # rien de commité
    status = _git(out, "status", "--porcelain").splitlines()
    assert sorted(line[3:] for line in status) == ["docs/a.md", "docs/b.md"]
    plain = tmp_path / "autre"
    plain.mkdir()
    _git(plain, "init", "-q")
    with pytest.raises(SystemExit, match="créé par un export"):
        ep.export(root, plain, update=True)


def test_commit_needs_the_rights_holder_then_makes_a_single_commit(tmp_path: Path) -> None:
    ep = _module()
    root, out = _source(tmp_path), tmp_path / "out"
    with pytest.raises(SystemExit, match="à compléter"):
        ep.export(root, out, author="Studio X <contact@example.org>")
    (root / "NOTICE").write_text("Copyright (C) 2026 Studio X\n", encoding="utf-8")
    assert ep.export(root, out, author="Studio X <contact@example.org>") == []
    identity = "Studio X <contact@example.org>"
    log = _git(out, "log", "--format=%an <%ae>|%cn <%ce>")
    assert log.strip().splitlines() == [f"{identity}|{identity}"]  # un seul commit
    tracked = _git(out, "ls-files").split()
    assert ".qaudit-export" not in tracked
    assert "README.md" in tracked
    with pytest.raises(SystemExit, match="dépôt git"):
        ep.export(root, out)  # un dépôt n'est jamais écrasé


def test_author_must_be_name_and_address() -> None:
    ep = _module()
    assert ep.parse_author("Studio X <contact@example.org>") == ("Studio X", "contact@example.org")
    with pytest.raises(SystemExit, match="Nom <email>"):
        ep.parse_author("Studio X")
