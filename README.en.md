# cse-transcribe

🇬🇧 English | 🇫🇷 [Français](README.md)

Local, free, private transcription and diarization (speaker recognition) for long audio/video files (meetings, etc.).

Built on:
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (transcription, Whisper Large-v3 model)
- [pyannote.audio](https://github.com/pyannote/pyannote-audio) >= 4.0 (diarization: who spoke when)

Everything runs locally on your machine — nothing is sent to a third-party service, except the initial download of the models (Hugging Face) and the authentication required for that download.

## Installation (any Windows/Mac/Linux machine)

1. Python 3.10+ installed
2. `pip install -r requirements.txt`
   - For GPU acceleration (recommended, much faster): install `torch`/`torchaudio` with the right CUDA index for your card, for example:
     `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124`
3. A free [Hugging Face](https://huggingface.co/join) account, then accept the terms on these three pages (required by pyannote.audio >= 4.0):
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
   - [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
   - Create a read token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
   - Set the `HF_TOKEN` environment variable (or pass it via `--hf-token`)

No external FFmpeg installation is required: audio decoding goes through PyAV (already bundled with its own libraries), both for transcription and diarization.

## Usage

No vocabulary is provided by default: each user adapts `--initial-prompt` / `--initial-prompt-file` to their own context (proper nouns, domain-specific jargon).

```bash
python -m cse_transcribe.cli --audio "path/to/file.mp4" --out-dir "path/to/output" --initial-prompt-file my_vocabulary.txt
```

Useful options:
- `--model large-v3`: Whisper model (or a local path to a model already downloaded, e.g. by the Buzz app)
- `--language auto|fr|en|...`: audio language. `auto` (default) lets Whisper detect it from the first seconds of audio; forcing a known language is faster and more reliable (useful for a short clip or a strong accent)
- `--initial-prompt-file prompt.txt`: steers recognition toward vocabulary/proper nouns specific to your recording (you provide it yourself)
- `--device auto|cuda|cpu`: hardware to use (auto = tries the GPU, falls back to CPU if unavailable)
- `--skip-diarization`: transcription only, no speaker recognition (no Hugging Face token needed in that case)

## Graphical application (Windows)

A graphical interface (`cse_transcribe_gui/`, PySide6) is available for command-line-free use.

**From source:**
```bash
pip install -r requirements-gui.txt
python -m cse_transcribe_gui
```

On first launch, the application automatically creates a dedicated Python environment (`%LOCALAPPDATA%\cse-transcribe\venv`) and installs the heavy dependencies there (torch, faster-whisper, pyannote.audio), with a progress bar. The interface itself stays lightweight and runs the processing in a separate subprocess: a crash in the transcription engine never affects the window.

After a successful diarization, a "Who said what?" screen lists each detected speaker (`SPEAKER_00`, ...) with a few spoken phrases, and offers three fields to fill in (Last name / First name / Role) — with autocomplete from speakers already identified in previous sessions, handy for recurring meetings with the same people. Once validated, the transcript is rewritten with these identities and exported in the chosen format (Word, PDF, or text) — the lightweight export dependencies (`python-docx`, `fpdf2`) install automatically on first use, with the same progress bar as the main bootstrap.

On first launch, the application detects the presence of an NVIDIA card (via `nvidia-smi`): without a compatible GPU, it installs the CPU torch wheels directly (much lighter) instead of needlessly downloading several GB of CUDA packages.

**Building the Windows installer (.exe):**
```bash
pip install pyinstaller
pyinstaller packaging/cse_transcribe_gui.spec --noconfirm
# Requires Inno Setup 6 (https://jrsoftware.org/isinfo.php):
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```
The installer is generated in `dist_installer\cse-transcribe-setup-<version>.exe` (Start Menu/Desktop shortcuts, uninstaller included). Torch/faster-whisper/pyannote are not bundled in the installer (keeping it lightweight, ~35 MB): they are installed on first launch, same as in source mode.

## Output produced (in `--out-dir`)

- `transcript_diarized.json` — each speech turn: start, end, speaker (`SPEAKER_00`, `SPEAKER_01`...), text
- `transcript_diarized.srt` — subtitles with the speaker prefixed on each line
- `speakers_summary.json` — for each detected speaker: number of turns, total speaking time, a few timestamped examples — used as a basis to identify who's who
- `checkpoints/` — intermediate results (raw transcription, raw diarization): if processing crashes, rerunning the same command automatically resumes where it stopped, without redoing everything
- `logs/` — complete, detailed execution log (debug level), useful in case of a problem

## Robustness

- Automatic resume after a crash (checkpoints per stage: transcription is never redone if it already succeeded, even if diarization fails afterward)
- Automatic GPU → CPU fallback if the GPU is unavailable or fails
- Detailed, timestamped log kept on disk, separate from the progress messages shown on screen
- Word-by-word merging between transcription and diarization (more precise than a segment-level merge, especially when several people share the same room microphone)
- Automatic absorption of short fragments misattributed by diarization (an isolated word wedged between two turns from the same person)
- Detailed diarization progress in the log (segmentation, voice embeddings...) instead of no feedback at all until the step finishes
- Graphical interface: the transcription engine runs in an isolated subprocess, its crash never affects the window

## Known limitations

- Diarization is more fragile on a room microphone shared by several people than on individual mics: the same person can occasionally end up split across several detected speakers, or a very short isolated word can be attributed to an unknown speaker. The generated `speakers_summary.json` serves as a basis to identify and manually merge these cases.
- pyannote.audio >= 4.0 depends on an additional model (`pyannote/speaker-diarization-community-1`) discovered along the way; the code handles this dependency automatically but requires accepting its terms of use (see Installation above).
- pyannote.audio shows a warning about `torchcodec` on load: this is not an issue, the code supplies already-decoded audio (via PyAV) and never uses `torchcodec`.
