# -*- coding: utf-8 -*-
"""
Gestion de l'environnement Python dedie aux dependances lourdes (torch,
faster-whisper, pyannote.audio). L'application GUI elle-meme reste legere
(PySide6 uniquement) ; ce module cree et utilise un venv separe, invoque en
sous-processus, pour que le moteur de transcription ne puisse jamais faire
planter l'interface graphique.
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

APP_DIR_NAME = "cse-transcribe"


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    d = Path(base) / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def venv_dir() -> Path:
    return app_data_dir() / "venv"


def venv_python() -> Path:
    if sys.platform == "win32":
        return venv_dir() / "Scripts" / "python.exe"
    return venv_dir() / "bin" / "python"


def repo_root() -> Path:
    # cse_transcribe_gui/ et cse_transcribe/ sont cote a cote a la racine du depot.
    return Path(__file__).resolve().parent.parent


def find_system_python() -> str | None:
    """Cherche un Python systeme utilisable pour creer le venv (3.10+)."""
    candidates = []
    py_launcher = shutil.which("py")
    if py_launcher:
        candidates.append([py_launcher, "-3"])
    python_exe = shutil.which("python")
    if python_exe:
        candidates.append([python_exe])
    python3_exe = shutil.which("python3")
    if python3_exe:
        candidates.append([python3_exe])

    for cmd in candidates:
        try:
            out = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=10)
            version_str = (out.stdout or out.stderr).strip()
            # "Python 3.12.10" -> (3, 12)
            parts = version_str.replace("Python ", "").split(".")
            major, minor = int(parts[0]), int(parts[1])
            if (major, minor) >= (3, 10):
                return cmd[0] if len(cmd) == 1 else " ".join(cmd)
        except Exception:
            continue
    return None


def is_ready() -> bool:
    """Le venv existe-t-il deja et contient-il les dependances necessaires ?"""
    py = venv_python()
    if not py.exists():
        return False
    check = subprocess.run(
        [str(py), "-c", "import torch, faster_whisper, pyannote.audio"],
        capture_output=True, text=True,
    )
    return check.returncode == 0


REQUIREMENTS = [
    "faster-whisper>=1.0.0",
    "pyannote.audio>=4.0.0",
]
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
TORCH_PACKAGES = ["torch", "torchaudio", "torchcodec"]


def bootstrap_steps(system_python_cmd: str):
    """
    Genere la liste des commandes a executer pour mettre en place le venv.
    Chaque etape est un tuple (description, commande_liste).
    L'appelant (GUI) execute ces commandes une par une via QProcess pour
    pouvoir afficher une progression et rester reactif.
    """
    py = str(venv_python())
    steps = []
    steps.append((
        "Creation de l'environnement Python dedie...",
        system_python_cmd.split() + ["-m", "venv", str(venv_dir())],
    ))
    steps.append((
        "Installation de faster-whisper et pyannote.audio...",
        [py, "-m", "pip", "install", "--quiet"] + REQUIREMENTS,
    ))
    steps.append((
        "Installation de torch (CUDA) — peut prendre plusieurs minutes...",
        [py, "-m", "pip", "install", "--quiet", "--index-url", TORCH_INDEX] + TORCH_PACKAGES,
    ))
    return steps
