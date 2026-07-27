# cse-transcribe

🇬🇧 English | 🇫🇷 [Français](README.md)

Local, free, private transcription and diarization (speaker recognition) for long audio/video files (meetings, etc.).

Built on:
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (transcription, Whisper Large-v3 model)
- [pyannote.audio](https://github.com/pyannote/pyannote-audio) >= 4.0 (diarization: who spoke when)

Everything runs locally on your machine — nothing is sent to a third-party service, except the initial download of the models (Hugging Face) and, if you use it, the `--youtube-url` option which queries YouTube to fetch a video's audio (see below).

## Installation (any Windows/Mac/Linux machine)

1. Python 3.10+ installed
2. `pip install -r requirements.txt`
   - For GPU acceleration (recommended, much faster): install `torch`/`torchaudio` with the right CUDA index for your card, for example:
     `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124`
3. A free Hugging Face token, needed only for speaker recognition (diarization) — see below.

No external FFmpeg installation is required: audio decoding goes through PyAV (already bundled with its own libraries), both for transcription and diarization.

### Getting a Hugging Face token

Only needed if you want speaker recognition (diarization); not needed for transcription-only use (`--skip-diarization` or the "Transcription only" checkbox in the app).

1. Create a free account at [huggingface.co/join](https://huggingface.co/join) (or sign in if you already have one).
2. Accept the terms of use on these three model pages (required by pyannote.audio >= 4.0) — open each link, sign in if needed, and click **"Agree and access repository"**:
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
   - [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
3. Create a token: go to [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens), click **"Create new token"**, choose type **"Read"** (sufficient, no need for a "Write" token), give it a name (e.g. `cse-transcribe`), then **"Create token"**.
4. Copy the displayed token (it starts with `hf_...`) — it's shown only once, copy it right away.
5. Use the token, depending on how you run the tool:
   - **Graphical application**: paste it into the "Token Hugging Face" field (it's remembered for next time).
   - **Command line**: set the `HF_TOKEN` environment variable, or pass it directly via `--hf-token YOUR_TOKEN`.

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
- `--youtube-url URL`: alternative to `--audio` — downloads the audio track of a YouTube video (or any other site supported by [yt-dlp](https://github.com/yt-dlp/yt-dlp)) then transcribes it. ⚠️ Unlike the rest of the tool, this option queries a third-party service: make sure you have the necessary rights to the content (your own recording, freely licensed content...) and comply with the source platform's terms of use.

## Hardware: GPU (NVIDIA) or CPU

The tool works without a graphics card: everything also runs on the processor (CPU), just slower. Only **NVIDIA** cards (via CUDA) speed up processing — faster-whisper and pyannote.audio rely on CUDA, so an AMD or Intel card provides no acceleration and is treated the same as a machine with no GPU.

- `--device auto` (default): tries the GPU, automatically falls back to CPU if no compatible NVIDIA card is available or if initialization fails.
- `--device cuda` / `--device cpu`: force one or the other.
- For reference: on GPU, a 2-hour recording can be transcribed and diarized in about ten minutes; on CPU, expect a much longer time (potentially close to or beyond the recording's actual duration for a long file). GPU is therefore recommended beyond a few minutes of audio.
- In the graphical application, first launch automatically detects an NVIDIA card (via `nvidia-smi`) to decide whether to install CUDA or CPU torch wheels — no manual action required.

## Graphical application (Windows)

A graphical interface (`cse_transcribe_gui/`, PySide6) is available for command-line-free use.

**From source:**
```bash
pip install -r requirements-gui.txt
python -m cse_transcribe_gui
```

On first launch, the application automatically creates a dedicated Python environment (`%LOCALAPPDATA%\cse-transcribe\venv`) and installs the heavy dependencies there (torch, faster-whisper, pyannote.audio), with a progress bar. The interface itself stays lightweight and runs the processing in a separate subprocess: a crash in the transcription engine never affects the window.

An "or YouTube URL" field lets you replace picking a local file with downloading a video's audio track instead (see the rights/terms-of-use warning above).

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
