# -*- coding: utf-8 -*-
"""
Pipeline robuste : transcription (faster-whisper) + diarisation (pyannote.audio)
+ fusion mot-a-mot pour attribuer un locuteur precis a chaque segment de parole.

Concu pour etre reutilisable sur n'importe quel enregistrement (aucune donnee
ni chemin propre a un dossier particulier n'est en dur dans ce module).
"""
import os
import json
import datetime
import logging

logger = logging.getLogger("cse_transcribe")


def fmt_hms(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_srt_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _checkpoint_path(out_dir, name):
    return os.path.join(out_dir, "checkpoints", name)


def _ensure_cuda_dll_path():
    """
    Sur Windows, ctranslate2 (utilise par faster-whisper) ne bundle pas ses
    propres DLLs CUDA (cuBLAS/cuDNN) et ne les trouve pas automatiquement.
    torch les embarque deja dans son propre dossier lib/ (il en a besoin pour
    son propre usage). Le chargeur natif de NVIDIA utilise l'ordre de
    recherche classique de Windows (variable PATH), pas les repertoires
    ajoutes via os.add_dll_directory (celui-ci n'est respecte que par les
    appels qui passent explicitement le flag LOAD_LIBRARY_SEARCH_USER_DIRS,
    ce qui n'est pas le cas ici) : on ajoute donc le dossier au PATH, en plus
    de l'appel a add_dll_directory par precaution. Ca evite un telechargement
    redondant des paquets nvidia-cublas-cu12/nvidia-cudnn-cu12.
    """
    if os.name != "nt":
        return
    try:
        import torch
        torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(torch_lib):
            os.environ["PATH"] = torch_lib + os.pathsep + os.environ.get("PATH", "")
            os.add_dll_directory(torch_lib)
    except Exception:
        logger.warning("Impossible de localiser les bibliotheques CUDA de torch pour le GPU.")


def transcribe_audio(audio_path, out_dir, model_dir_or_name, language, initial_prompt, device_pref="auto"):
    """Etape 1 : transcription. Reprend depuis un checkpoint si deja fait."""
    os.makedirs(os.path.join(out_dir, "checkpoints"), exist_ok=True)
    ckpt = _checkpoint_path(out_dir, "whisper_segments.json")
    if os.path.exists(ckpt):
        logger.info("Une transcription precedente a ete trouvee, je la reutilise (pas besoin de tout refaire).")
        with open(ckpt, encoding="utf-8") as f:
            return json.load(f)

    logger.info("Chargement du modele de reconnaissance vocale (Whisper Large-v3)...")
    _ensure_cuda_dll_path()
    from faster_whisper import WhisperModel

    model = None
    if device_pref in ("auto", "cuda"):
        try:
            model = WhisperModel(model_dir_or_name, device="cuda", compute_type="float16")
            logger.info("Modele charge sur carte graphique (GPU) : la transcription sera rapide.")
        except Exception as e:
            logger.warning(f"Impossible d'utiliser le GPU ({e}). Bascule sur le processeur (CPU, plus lent).")
    if model is None:
        model = WhisperModel(model_dir_or_name, device="cpu", compute_type="int8")
        logger.info("Modele charge sur processeur (CPU).")

    # "auto" (valeur par defaut) n'est pas un code langue Whisper : None active
    # la detection automatique (faster-whisper analyse les premieres secondes
    # de l'audio). Forcer un code connu a l'avance reste plus rapide et plus
    # fiable (utile pour un clip court ou un accent marque qui pourrait
    # tromper la detection).
    whisper_language = None if language in (None, "", "auto") else language
    if whisper_language is None:
        logger.info("Langue non precisee : detection automatique par Whisper.")

    logger.info("Debut de la transcription de l'audio. Cela peut prendre du temps selon la duree du fichier...")
    segments_gen, info = model.transcribe(
        audio_path,
        language=whisper_language,
        initial_prompt=initial_prompt,
        word_timestamps=True,
        vad_filter=True,
    )
    logger.debug(f"Langue detectee: {info.language} (probabilite {info.language_probability:.2f}), "
                 f"duree audio: {info.duration:.1f}s")

    whisper_segments = []
    last_report = 0
    for seg in segments_gen:
        words = [{"start": w.start, "end": w.end, "word": w.word} for w in (seg.words or [])]
        whisper_segments.append({"start": seg.start, "end": seg.end, "text": seg.text.strip(), "words": words})
        logger.debug(f"Segment {len(whisper_segments)}: [{fmt_hms(seg.start)}-{fmt_hms(seg.end)}] {seg.text.strip()!r}")
        if seg.end - last_report > 300:  # toutes les 5 minutes de contenu
            logger.info(f"Transcription en cours... position actuelle dans l'enregistrement : {fmt_hms(seg.end)} "
                        f"sur {fmt_hms(info.duration)} ({len(whisper_segments)} segments traites).")
            last_report = seg.end

    logger.info(f"Transcription terminee : {len(whisper_segments)} segments de parole detectes au total.")
    with open(ckpt, "w", encoding="utf-8") as f:
        json.dump(whisper_segments, f, ensure_ascii=False, indent=1)
    return whisper_segments


def _diarization_progress_hook():
    """
    Fabrique un callback compatible avec le parametre `hook` de pyannote.audio
    (signature : step_name, step_artifact, file=None, total=None, completed=None),
    qui journalise la progression de chaque etape interne (segmentation,
    extraction des empreintes vocales, clustering...) au lieu de ne rien
    afficher avant la toute fin, ce qui peut prendre plusieurs minutes sans
    aucun signe de vie sur un enregistrement long.
    """
    state = {"step": None, "last_pct": -1}

    def hook(step_name, step_artifact, file=None, total=None, completed=None):
        if not total or completed is None:
            return
        if step_name != state["step"]:
            state["step"] = step_name
            state["last_pct"] = -1
        pct = min(100, int(completed / total * 100))
        if pct >= state["last_pct"] + 20 or completed >= total:
            state["last_pct"] = pct
            logger.info(f"Analyse des voix : {step_name} — {pct}% ({completed}/{total})")

    return hook


def diarize_audio(audio_path, out_dir, hf_token, device_pref="auto"):
    """Etape 2 : diarisation (qui parle quand). Reprend depuis un checkpoint si deja fait."""
    os.makedirs(os.path.join(out_dir, "checkpoints"), exist_ok=True)
    ckpt = _checkpoint_path(out_dir, "diarization_segments.json")
    if os.path.exists(ckpt):
        logger.info("Une analyse des locuteurs precedente a ete trouvee, je la reutilise.")
        with open(ckpt, encoding="utf-8") as f:
            return json.load(f)

    if not hf_token:
        raise RuntimeError(
            "Aucun token Hugging Face trouve (variable d'environnement HF_TOKEN). "
            "La reconnaissance des voix (diarisation) necessite un compte Hugging Face gratuit, "
            "l'acceptation des conditions sur pyannote/speaker-diarization-3.1, pyannote/segmentation-3.0 "
            "et pyannote/speaker-diarization-community-1, et un token de lecture cree sur "
            "huggingface.co/settings/tokens."
        )

    logger.info("Chargement du modele de reconnaissance des locuteurs (pyannote)...")
    from pyannote.audio import Pipeline
    import torch
    from faster_whisper.audio import decode_audio

    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=hf_token)
    if device_pref in ("auto", "cuda") and torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))
        logger.info("Analyse des voix lancee sur carte graphique (GPU).")
    else:
        logger.info("Analyse des voix lancee sur processeur (CPU) : cette etape peut prendre plusieurs minutes.")

    logger.info("Analyse des voix en cours (identification de qui parle a chaque instant)...")
    # On decode l'audio nous-memes (via PyAV, deja utilise par faster-whisper)
    # plutot que de laisser pyannote lire le fichier via torchcodec : cette
    # derniere bibliotheque necessite un build FFmpeg "full-shared" specifique
    # rarement present sur les postes Windows, ce qui rend l'installation
    # fragile. Le fournir en waveform pre-decodee evite cette dependance.
    sample_rate = 16000
    waveform = torch.from_numpy(decode_audio(audio_path, sampling_rate=sample_rate)).unsqueeze(0)
    output = pipeline({"waveform": waveform, "sample_rate": sample_rate}, hook=_diarization_progress_hook())
    # pyannote.audio >= 4.0 renvoie un objet DiarizeOutput ; on utilise la version
    # "exclusive" (sans chevauchement), adaptee a la fusion avec la transcription.
    diarization = getattr(output, "exclusive_speaker_diarization", None)
    if diarization is None:
        diarization = getattr(output, "speaker_diarization", output)

    diar_segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        diar_segments.append({"start": turn.start, "end": turn.end, "speaker": speaker})
        logger.debug(f"Tour diarisation: [{fmt_hms(turn.start)}-{fmt_hms(turn.end)}] {speaker}")

    n_speakers = len(set(d["speaker"] for d in diar_segments))
    logger.info(f"Analyse des voix terminee : {n_speakers} locuteurs distincts detectes "
                f"sur {len(diar_segments)} tours de parole.")

    with open(ckpt, "w", encoding="utf-8") as f:
        json.dump(diar_segments, f, ensure_ascii=False, indent=1)
    return diar_segments


def _speaker_for_interval(start, end, diar_segments):
    best_speaker, best_overlap = None, 0.0
    for d in diar_segments:
        overlap = min(end, d["end"]) - max(start, d["start"])
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = d["speaker"]
    return best_speaker or "INCONNU"


def merge_transcript_and_speakers(whisper_segments, diar_segments, max_gap_sec=1.5,
                                   bridge_fragments=True, fragment_max_duration=1.5,
                                   bridge_max_gap=3.0):
    """
    Fusion au niveau du mot (plus precis que par segment whisper complet,
    important quand un segment chevauche un changement de locuteur, ce qui
    arrive souvent avec plusieurs personnes sur un meme micro de salle).
    Regroupe ensuite les mots consecutifs du meme locuteur en "tours".

    Si bridge_fragments est actif, un tour tres court dont le locuteur est
    entoure des deux cotes par le MEME autre locuteur est considere comme une
    erreur probable de diarisation (mot isole mal attribue, frequent sur un
    micro de salle partage) et absorbe dans la phrase environnante plutot que
    de casser artificiellement le texte en plusieurs tours.
    """
    logger.info("Fusion de la transcription et des voix detectees (attribution mot par mot)...")
    words_with_speaker = []
    for seg in whisper_segments:
        if seg["words"]:
            for w in seg["words"]:
                spk = _speaker_for_interval(w["start"], w["end"], diar_segments)
                words_with_speaker.append({"start": w["start"], "end": w["end"], "word": w["word"], "speaker": spk})
        else:
            # pas de mots (rare) : on utilise le segment entier
            spk = _speaker_for_interval(seg["start"], seg["end"], diar_segments)
            words_with_speaker.append({"start": seg["start"], "end": seg["end"], "word": seg["text"], "speaker": spk})

    raw_turns = []
    current = None
    for w in words_with_speaker:
        if current and current["speaker"] == w["speaker"] and (w["start"] - current["end"]) <= max_gap_sec:
            current["end"] = w["end"]
            current["text"] += w["word"]
        else:
            if current:
                raw_turns.append(current)
            current = {"start": w["start"], "end": w["end"], "speaker": w["speaker"], "text": w["word"]}
    if current:
        raw_turns.append(current)
    for t in raw_turns:
        t["text"] = t["text"].strip()

    if not bridge_fragments:
        logger.info(f"Fusion terminee : {len(raw_turns)} tours de parole attribues a un locuteur.")
        return raw_turns

    turns = []
    current = None
    bridged_count = 0
    i = 0
    n = len(raw_turns)
    while i < n:
        seg = raw_turns[i]
        duration = seg["end"] - seg["start"]
        if (
            duration <= fragment_max_duration
            and current is not None
            and i + 1 < n
        ):
            nxt = raw_turns[i + 1]
            if nxt["speaker"] == current["speaker"] and (nxt["start"] - current["end"]) <= bridge_max_gap:
                current["end"] = seg["end"]
                current["text"] += (" " if not current["text"].endswith(" ") else "") + seg["text"]
                bridged_count += 1
                i += 1
                continue
        if current and current["speaker"] == seg["speaker"]:
            current["end"] = seg["end"]
            current["text"] += (" " if not current["text"].endswith(" ") else "") + seg["text"]
        else:
            if current:
                turns.append(current)
            current = dict(seg)
        i += 1
    if current:
        turns.append(current)

    logger.info(f"Fusion terminee : {len(turns)} tours de parole attribues a un locuteur "
                f"({bridged_count} fragments courts recolles automatiquement).")
    return turns


def write_outputs(turns, out_dir, base_name="transcript_diarized"):
    logger.info("Ecriture des fichiers de resultat...")

    json_path = os.path.join(out_dir, f"{base_name}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(turns, f, ensure_ascii=False, indent=1)

    srt_path = os.path.join(out_dir, f"{base_name}.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, t in enumerate(turns, start=1):
            f.write(f"{i}\n{fmt_srt_time(t['start'])} --> {fmt_srt_time(t['end'])}\n")
            f.write(f"[{t['speaker']}] {t['text']}\n\n")

    by_speaker = {}
    for t in turns:
        d = by_speaker.setdefault(t["speaker"], {"count": 0, "duration": 0.0, "examples": []})
        d["count"] += 1
        d["duration"] += t["end"] - t["start"]
        if len(d["examples"]) < 5:
            d["examples"].append({"timestamp": fmt_hms(t["start"]), "text": t["text"][:200]})

    summary = [
        {"speaker": spk, "nombre_tours": d["count"], "duree_totale_sec": round(d["duration"], 1),
         "duree_totale": fmt_hms(d["duration"]), "exemples": d["examples"]}
        for spk, d in sorted(by_speaker.items(), key=lambda x: -x[1]["duration"])
    ]
    summary_path = os.path.join(out_dir, "speakers_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    logger.info(f"Resultats ecrits : {json_path}")
    logger.info(f"Resultats ecrits : {srt_path}")
    logger.info(f"Resume par locuteur ecrit : {summary_path}")
    logger.info(f"{len(summary)} locuteurs distincts au total, tries par duree de parole decroissante.")
    return {"json": json_path, "srt": srt_path, "summary": summary_path}


def run_pipeline(audio_path, out_dir, model_dir_or_name, language, initial_prompt,
                  hf_token, device_pref="auto"):
    os.makedirs(out_dir, exist_ok=True)
    start_time = datetime.datetime.now()
    logger.info(f"Demarrage du traitement du fichier : {audio_path}")

    try:
        whisper_segments = transcribe_audio(audio_path, out_dir, model_dir_or_name, language,
                                             initial_prompt, device_pref)
    except Exception:
        logger.exception("Echec pendant l'etape de transcription.")
        raise

    try:
        diar_segments = diarize_audio(audio_path, out_dir, hf_token, device_pref)
    except Exception:
        logger.exception("Echec pendant l'etape de diarisation (reconnaissance des voix).")
        raise

    turns = merge_transcript_and_speakers(whisper_segments, diar_segments)
    paths = write_outputs(turns, out_dir)

    elapsed = datetime.datetime.now() - start_time
    logger.info(f"Traitement termine en {elapsed}.")
    return paths
