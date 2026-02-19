# PyInstaller spec for Gamesphere Import Tool (Windows .exe)
# Build on Windows: pyinstaller GamesphereImportTool.spec
# Or: uv run pyinstaller GamesphereImportTool.spec

import sys

block_cipher = None

# When frozen, the GUI runs the importer in-process and needs the main module.
# Dynamic import in a thread is not traced, so include main explicitly.
hidden_imports = [
    'main',
    'vdf',
    'PIL',
    'PIL.Image',
    'requests',
    'psutil',
    'dotenv',
    'glob2',
]

# Optional: onefile=False produces a folder with .exe + dependencies (faster startup, easier antivirus)
# onefile=True produces a single .exe (simpler to distribute)
a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GamesphereImportTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window for GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,  # Request admin so we can write to Program Files (Sunshine/Apollo config)
)
