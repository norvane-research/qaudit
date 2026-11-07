# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller : deux exécutables (console « qaudit », fenêtré « qaudit-gui »)
partageant un même dossier ``dist/qaudit``. Construire depuis la racine :

    python -m PyInstaller packaging/qaudit.spec --noconfirm

Les données du paquet (catalogues i18n, méthode, règlements, profils, schéma,
démonstration) sont embarquées par ``collect_data_files``.
"""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("qaudit")
hidden = ["qaudit.gui.app", "qaudit.cli.main"]

cli = Analysis(
    ["../qaudit/__main__.py"],
    pathex=[".."],
    datas=datas,
    hiddenimports=hidden,
    excludes=["matplotlib", "IPython", "PyQt5", "PySide6", "notebook"],
    noarchive=False,
)
gui = Analysis(
    ["gui_entry.py"],
    pathex=[".."],
    datas=datas,
    hiddenimports=hidden,
    excludes=["matplotlib", "IPython", "PyQt5", "PySide6", "notebook"],
    noarchive=False,
)
MERGE((cli, "qaudit", "qaudit"), (gui, "qaudit-gui", "qaudit-gui"))

cli_pyz = PYZ(cli.pure)
gui_pyz = PYZ(gui.pure)
cli_exe = EXE(cli_pyz, cli.scripts, [], exclude_binaries=True, name="qaudit",
              console=True, upx=False)
gui_exe = EXE(gui_pyz, gui.scripts, [], exclude_binaries=True, name="qaudit-gui",
              console=False, upx=False)
COLLECT(cli_exe, cli.binaries, cli.datas, gui_exe, gui.binaries, gui.datas,
        strip=False, upx=False, name="qaudit")
