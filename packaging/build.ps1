# Construit dist\qaudit\ (qaudit.exe + qaudit-gui.exe). À lancer depuis la racine du dépôt.
param([string]$Python = ".venv\Scripts\python.exe")
& $Python -m pip install -q -e ".[build]"
& $Python -m PyInstaller packaging\qaudit.spec --noconfirm --clean --distpath dist --workpath build\pyinstaller
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& "dist\qaudit\qaudit.exe" --version
& "dist\qaudit\qaudit.exe" demo --out dist\demo-out
# Raccourci Bureau -> pythonw.exe -m qaudit gui (Python signé : jamais bloqué par
# Smart App Control, contrairement aux binaires PyInstaller non signés qui peuvent
# l'être après chaque reconstruction). dist\ reste destiné aux autres postes.
$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path $desktop "qaudit.lnk"))
$link.TargetPath = (Resolve-Path ".venv\Scripts\pythonw.exe").Path
$link.Arguments = "-m qaudit gui"
$link.WorkingDirectory = (Resolve-Path ".").Path
$link.WindowStyle = 1
$link.Description = "qaudit - audit de systemes de trading"
$link.Save()
"Raccourci : $(Join-Path $desktop 'qaudit.lnk')"
