# -*- coding: utf-8 -*-
import argparse
import os
import sys

from .logging_utils import setup_logging
from .pipeline import run_pipeline

DEFAULT_PROMPT = ""


def build_parser():
    p = argparse.ArgumentParser(
        prog="cse-transcribe",
        description="Transcription + diarisation (reconnaissance des voix) locale et robuste, "
                    "basee sur faster-whisper et pyannote.audio."
    )
    p.add_argument("--audio", default=None,
                    help="Chemin vers le fichier audio ou video a transcrire. "
                        "Alternative a --youtube-url (l'un des deux est requis).")
    p.add_argument("--youtube-url", default=None,
                    help="URL YouTube (ou tout autre site supporte par yt-dlp) dont la piste audio sera "
                        "telechargee puis transcrite. Attention : contrairement au reste de l'outil, cette "
                        "etape interroge un service tiers ; assurez-vous de disposer des droits necessaires "
                        "sur le contenu et de respecter les conditions d'utilisation de la plateforme source.")
    p.add_argument("--out-dir", required=True, help="Dossier de sortie (resultats, checkpoints, logs).")
    p.add_argument("--model", default="large-v3",
                    help="Nom du modele Whisper (ex: large-v3, medium) ou chemin local vers un modele "
                        "faster-whisper deja telecharge. Defaut: large-v3.")
    p.add_argument("--language", default="auto",
                    help="Code langue (ex: fr, en, es...) ou 'auto' (defaut) pour une detection "
                        "automatique par Whisper sur les premieres secondes de l'audio.")
    p.add_argument("--initial-prompt", default=None,
                    help="Texte pour orienter la reconnaissance (noms propres, jargon specifique a votre "
                        "enregistrement). Aucun vocabulaire n'est fourni par defaut : chaque utilisateur "
                        "doit fournir le sien via cette option ou --initial-prompt-file.")
    p.add_argument("--initial-prompt-file", default=None,
                    help="Fichier texte contenant le prompt initial (prioritaire sur --initial-prompt).")
    p.add_argument("--hf-token", default=None,
                    help="Token Hugging Face (sinon lu depuis la variable d'environnement HF_TOKEN).")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"],
                    help="Materiel a utiliser. 'auto' essaie le GPU puis bascule sur CPU si indisponible.")
    p.add_argument("--skip-diarization", action="store_true",
                    help="Transcription seule, sans reconnaissance des locuteurs.")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    logger, log_path = setup_logging(args.out_dir)

    if not args.audio and not args.youtube_url:
        logger.error("Fournissez soit --audio, soit --youtube-url.")
        sys.exit(1)

    audio_path = args.audio
    if args.youtube_url:
        from .youtube import download_audio
        try:
            audio_path = download_audio(args.youtube_url, os.path.join(args.out_dir, "downloads"))
        except Exception:
            logger.exception("Echec du telechargement depuis l'URL fournie.")
            sys.exit(1)

    if not audio_path or not os.path.exists(audio_path):
        logger.error(f"Fichier audio introuvable : {audio_path}")
        sys.exit(1)

    initial_prompt = args.initial_prompt or DEFAULT_PROMPT
    if args.initial_prompt_file:
        if not os.path.exists(args.initial_prompt_file):
            logger.error(f"Fichier de prompt introuvable : {args.initial_prompt_file}")
            sys.exit(1)
        with open(args.initial_prompt_file, encoding="utf-8") as f:
            initial_prompt = f.read().strip()

    hf_token = args.hf_token or os.environ.get("HF_TOKEN")

    if args.skip_diarization:
        from .pipeline import transcribe_audio, write_outputs
        segments = transcribe_audio(audio_path, args.out_dir, args.model, args.language,
                                    initial_prompt, args.device)
        turns = [{"start": s["start"], "end": s["end"], "speaker": "N/A", "text": s["text"]} for s in segments]
        write_outputs(turns, args.out_dir)
        logger.info("Termine (sans reconnaissance des locuteurs).")
        return

    if not hf_token:
        logger.error(
            "Aucun token Hugging Face disponible. Definissez la variable d'environnement HF_TOKEN, "
            "ou passez --hf-token, ou utilisez --skip-diarization pour transcrire sans reconnaissance des voix."
        )
        sys.exit(1)

    try:
        run_pipeline(audio_path, args.out_dir, args.model, args.language, initial_prompt,
                    hf_token, args.device)
    except Exception:
        logger.error(f"Le traitement a echoue. Consultez le journal complet pour le detail : {log_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
