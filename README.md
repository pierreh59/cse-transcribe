# cse-transcribe

🇫🇷 Français | 🇬🇧 [English](README.en.md)

Transcription et diarisation (reconnaissance des voix) locale, gratuite et privée, pour fichiers audio/vidéo longs (réunions, etc.).

Basé sur :
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (transcription, modèle Whisper Large-v3)
- [pyannote.audio](https://github.com/pyannote/pyannote-audio) >= 4.0 (diarisation : qui parle et quand)

Tout tourne en local sur votre machine — rien n'est envoyé à un service tiers, à l'exception du téléchargement initial des modèles (Hugging Face) et de l'authentification nécessaire à ce téléchargement.

## Installation (sur n'importe quel poste Windows/Mac/Linux)

1. Python 3.10+ installé
2. `pip install -r requirements.txt`
   - Pour l'accélération GPU (recommandé, bien plus rapide) : installez `torch`/`torchaudio` avec le bon index CUDA pour votre carte, par exemple :
     `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124`
3. Un compte [Hugging Face](https://huggingface.co/join) (gratuit), puis accepter les conditions sur ces trois pages (requis par pyannote.audio >= 4.0) :
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
   - [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
   - Créer un token de lecture sur [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
   - Définir la variable d'environnement `HF_TOKEN` (ou la passer via `--hf-token`)

Aucune installation externe de FFmpeg n'est necessaire : le decodage audio passe par PyAV (deja embarque avec ses propres bibliotheques), aussi bien pour la transcription que pour la diarisation.

## Utilisation

Aucun vocabulaire n'est fourni par défaut : chaque utilisateur adapte `--initial-prompt` / `--initial-prompt-file` à son propre contexte (noms propres, jargon métier).

```bash
python -m cse_transcribe.cli --audio "chemin/vers/fichier.mp4" --out-dir "chemin/vers/sortie" --initial-prompt-file mon_vocabulaire.txt
```

Options utiles :
- `--model large-v3` : modèle Whisper (ou chemin local vers un modèle déjà téléchargé, ex. par l'app Buzz)
- `--language auto|fr|en|...` : langue de l'audio. `auto` (défaut) laisse Whisper la détecter sur les premières secondes ; forcer une langue connue est plus rapide et plus fiable (utile pour un clip court ou un accent marqué)
- `--initial-prompt-file prompt.txt` : oriente la reconnaissance sur du vocabulaire/noms propres spécifiques à votre enregistrement (à fournir vous-même)
- `--device auto|cuda|cpu` : matériel à utiliser (auto = essaie le GPU, bascule sur CPU si indisponible)
- `--skip-diarization` : transcription seule, sans reconnaissance des locuteurs (pas besoin de token Hugging Face dans ce cas)

## Application graphique (Windows)

Une interface graphique (`cse_transcribe_gui/`, PySide6) est disponible pour un usage sans ligne de commande.

**Depuis les sources :**
```bash
pip install -r requirements-gui.txt
python -m cse_transcribe_gui
```

Au premier lancement, l'application crée automatiquement un environnement Python dédié (`%LOCALAPPDATA%\cse-transcribe\venv`) et y installe les dépendances lourdes (torch, faster-whisper, pyannote.audio), avec une barre de progression. L'interface elle-même reste légère et lance le traitement dans un sous-processus séparé : un plantage du moteur de transcription n'affecte jamais la fenêtre.

Après une diarisation réussie, un écran « Qui a dit quoi ? » liste chaque locuteur détecté (`SPEAKER_00`, ...) avec quelques phrases prononcées, et propose trois champs à compléter (Nom / Prénom / Fonction). Une fois validé, le transcript est réécrit avec ces identités et exporté au format choisi (Word, PDF ou texte) — les dépendances d'export (`python-docx`, `fpdf2`), légères, s'installent automatiquement à la première utilisation.

**Construire l'installateur Windows (.exe) :**
```bash
pip install pyinstaller
pyinstaller packaging/cse_transcribe_gui.spec --noconfirm
# Nécessite Inno Setup 6 (https://jrsoftware.org/isinfo.php) :
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```
Le programme d'installation est généré dans `dist_installer\cse-transcribe-setup-<version>.exe` (raccourcis Menu Démarrer/Bureau, désinstalleur inclus). Torch/faster-whisper/pyannote ne sont pas embarqués dans l'installateur (il reste ainsi léger, ~35 Mo) : ils sont installés au premier lancement, comme en mode source.

## Résultats produits (dans `--out-dir`)

- `transcript_diarized.json` — chaque tour de parole : début, fin, locuteur (`SPEAKER_00`, `SPEAKER_01`...), texte
- `transcript_diarized.srt` — sous-titres avec le locuteur en préfixe de chaque ligne
- `speakers_summary.json` — pour chaque locuteur détecté : nombre de tours, durée totale de parole, quelques exemples avec horodatage — sert de base pour identifier qui est qui
- `checkpoints/` — résultats intermédiaires (transcription brute, diarisation brute) : si le traitement plante, relancer la même commande reprend automatiquement là où ça s'est arrêté, sans tout refaire
- `logs/` — journal complet et détaillé de l'exécution (niveau debug), utile en cas de problème

## Robustesse

- Reprise automatique après plantage (checkpoints par étape : la transcription n'est jamais refaite si elle a déjà réussi, même si la diarisation échoue ensuite)
- Repli automatique GPU → CPU si le GPU n'est pas disponible ou échoue
- Journal détaillé horodaté conservé sur disque, séparé des messages de progression affichés à l'écran
- Fusion mot par mot entre transcription et diarisation (plus précis qu'une fusion par segment, notamment quand plusieurs personnes partagent un même microphone de salle)
- Absorption automatique des micro-fragments mal attribués par la diarisation (mot isolé coincé entre deux répliques de la même personne)
- Interface graphique : le moteur de transcription tourne dans un sous-processus isolé, son plantage n'affecte jamais la fenêtre

## Limites connues

- La diarisation est plus fragile sur un microphone de salle partagé par plusieurs personnes que sur des micros individuels : une même personne peut occasionnellement se retrouver scindée en plusieurs locuteurs détectés, ou un mot isolé très court peut être attribué à un locuteur inconnu. Le `speakers_summary.json` produit sert de base pour identifier et fusionner manuellement ces cas.
- pyannote.audio >= 4.0 dépend d'un modèle supplémentaire (`pyannote/speaker-diarization-community-1`) découvert au fil de l'utilisation ; le code gère cette dépendance automatiquement mais nécessite l'acceptation de ses conditions d'usage (voir Installation ci-dessus).
- pyannote.audio affiche un avertissement au sujet de `torchcodec` au chargement : sans objet, le code fournit l'audio déjà décodé (via PyAV) et n'utilise jamais `torchcodec`.
