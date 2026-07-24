# -*- mode: python ; coding: utf-8 -*-
"""
Spec PyInstaller pour l'application GUI cse-transcribe.

Construit un dossier autonome (mode --onedir) contenant l'executable et
ses dependances legeres (PySide6). Le package cse_transcribe/ (le moteur,
pur Python, sans dependance lourde a l'import) est copie tel quel a cote
de l'executable : c'est ce dossier qui est mis sur PYTHONPATH au moment
d'invoquer le venv dedie (voir cse_transcribe_gui/env_manager.py).

Utilisation :
    pyinstaller packaging/cse_transcribe_gui.spec --noconfirm
"""
import os

block_cipher = None
ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))

a = Analysis(
    [os.path.join(ROOT, "packaging", "entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "cse_transcribe"), "cse_transcribe"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "faster_whisper", "pyannote"],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cse-transcribe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="cse-transcribe",
)
