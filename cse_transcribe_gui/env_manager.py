# -*- coding: utf-8 -*-
"""
Gestion de l'environnement Python dedie aux dependances lourdes (torch,
faster-whisper, pyannote.audio). L'application GUI elle-meme reste legere
(PySide6 uniquement) ; ce module cree et utilise un venv separe, invoque en
sous-processus, pour que le moteur de transcription ne puisse jamais faire
planter l'interface graphique.
"""
import json
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
    """
    Repertoire contenant le package cse_transcribe (a mettre sur PYTHONPATH
    pour le sous-processus). En mode source, c'est la racine du depot
    (cse_transcribe_gui/ et cse_transcribe/ sont cote a cote). Une fois
    empaquete avec PyInstaller (mode --onedir), le dossier cse_transcribe/
    est copie soit dans _internal/ (versions recentes), soit a cote de
    l'executable (versions plus anciennes) : on detecte lequel des deux.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        internal_candidate = exe_dir / "_internal"
        if (internal_candidate / "cse_transcribe").is_dir():
            return internal_candidate
        return exe_dir
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


EXPORT_REQUIREMENTS = ["python-docx>=1.1.0", "fpdf2>=2.7.0"]


def export_deps_ready() -> bool:
    """Les dependances d'export (Word/PDF), legeres, sont-elles deja installees ?"""
    py = venv_python()
    if not py.exists():
        return False
    check = subprocess.run(
        [str(py), "-c", "import docx, fpdf"],
        capture_output=True, text=True,
    )
    return check.returncode == 0


def export_bootstrap_step():
    """
    Etape d'installation des dependances d'export : separee du bootstrap
    principal (torch/faster-whisper/pyannote) car legere (pas de CUDA a
    telecharger) et installee a la demande, seulement quand l'utilisateur
    utilise effectivement l'export Word/PDF.
    """
    py = str(venv_python())
    return [py, "-m", "pip", "install", "--progress-bar", "raw",
            "--disable-pip-version-check"] + EXPORT_REQUIREMENTS


YOUTUBE_REQUIREMENTS = ["yt-dlp"]


def youtube_deps_ready() -> bool:
    """yt-dlp est-il deja installe ? Meme logique que pour les dependances d'export :
    is_ready() ne verifie que torch/faster-whisper/pyannote, donc une installation
    existante (creee avant l'ajout de cette fonctionnalite) ne l'aurait pas."""
    py = venv_python()
    if not py.exists():
        return False
    check = subprocess.run(
        [str(py), "-c", "import yt_dlp"],
        capture_output=True, text=True,
    )
    return check.returncode == 0


def youtube_bootstrap_step():
    py = str(venv_python())
    return [py, "-m", "pip", "install", "--progress-bar", "raw",
            "--disable-pip-version-check"] + YOUTUBE_REQUIREMENTS


REQUIREMENTS = [
    "faster-whisper>=1.0.0",
    "pyannote.audio>=4.0.0",
]
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
TORCH_PACKAGES = ["torch", "torchaudio"]


def has_nvidia_gpu() -> bool:
    """
    Detecte une carte NVIDIA fonctionnelle via nvidia-smi (installe par le
    pilote NVIDIA, present des qu'une carte est correctement configuree).
    Permet d'eviter de telecharger les wheels torch CUDA (plusieurs Go) sur
    un poste qui n'a de toute facon pas de GPU compatible.
    """
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False
    try:
        result = subprocess.run(
            [nvidia_smi], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


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
    pip_common = ["--progress-bar", "raw", "--disable-pip-version-check"]
    # torch/torchaudio (CUDA) sont installes seuls, avec --index-url exclusif
    # (pas de --extra-index-url ici) : si on ajoute PyPI comme source
    # supplementaire, pip choisit la version publique la plus recente tous
    # index confondus, qui est souvent une release PyPI plus recente mais
    # CPU-only, plutot que le build +cu128 le plus recent de l'index CUDA.
    # torch (CUDA) doit aussi etre installe AVANT faster-whisper/pyannote.audio
    # (etape suivante) : ces derniers dependent de torch sans epingler de
    # build particulier, donc si torch est deja present, pip considere la
    # dependance satisfaite et ne le remplace pas.
    if has_nvidia_gpu():
        steps.append((
            "Installation de torch (CUDA) — peut prendre plusieurs minutes",
            [py, "-m", "pip", "install"] + pip_common
            + ["--index-url", TORCH_INDEX] + TORCH_PACKAGES,
        ))
    else:
        # Pas de GPU NVIDIA detecte : on installe directement les wheels
        # CPU par defaut de PyPI (bien plus legeres, pas de CUDA a
        # telecharger inutilement).
        steps.append((
            "Installation de torch (CPU, aucun GPU NVIDIA detecte)",
            [py, "-m", "pip", "install"] + pip_common + TORCH_PACKAGES,
        ))
    steps.append((
        "Installation de faster-whisper et pyannote.audio",
        [py, "-m", "pip", "install"] + pip_common + REQUIREMENTS,
    ))
    return steps


def known_speakers_path() -> Path:
    return app_data_dir() / "known_speakers.json"


def load_known_speakers() -> list[dict]:
    """
    Liste des locuteurs deja identifies lors de sessions precedentes
    (Nom / Prenom / Fonction), pour proposer une auto-completion dans
    l'ecran d'identification plutot que de tout retaper a chaque reunion
    recurrente.
    """
    path = known_speakers_path()
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def remember_speakers(entries: list[dict]) -> None:
    """Fusionne de nouvelles identites (nom/prenom/fonction) dans l'historique connu."""
    known = load_known_speakers()
    seen = {(e.get("nom", ""), e.get("prenom", "")) for e in known}
    for entry in entries:
        key = (entry.get("nom", ""), entry.get("prenom", ""))
        if key == ("", "") or key in seen:
            continue
        known.append(entry)
        seen.add(key)
    with open(known_speakers_path(), "w", encoding="utf-8") as f:
        json.dump(known, f, ensure_ascii=False, indent=1)
