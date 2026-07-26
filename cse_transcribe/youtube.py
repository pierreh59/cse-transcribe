# -*- coding: utf-8 -*-
"""
Telechargement de la piste audio d'une video (YouTube ou tout autre site
supporte par yt-dlp) afin de la transcrire ensuite comme un fichier local.

Attention : contrairement au reste de l'outil (qui tourne entierement en
local), cette etape interroge un service tiers pour recuperer le contenu.
Il est de la responsabilite de l'utilisateur de ne telecharger que du
contenu sur lequel il dispose des droits necessaires (son propre
enregistrement, contenu sous licence libre...) et de respecter les
conditions d'utilisation de la plateforme source.
"""
import logging
import os

logger = logging.getLogger("cse_transcribe")


def download_audio(url: str, out_dir: str) -> str:
    """
    Telecharge la meilleure piste audio disponible pour `url` dans out_dir
    (sans transcodage : le fichier est conserve dans son format d'origine,
    m4a/webm selon la source, que le decodeur audio du pipeline lit
    directement). Retourne le chemin du fichier telecharge.
    """
    import yt_dlp

    os.makedirs(out_dir, exist_ok=True)
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    logger.info(f"Telechargement de la piste audio depuis : {url}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)

    if not os.path.exists(path):
        raise RuntimeError(f"Le fichier attendu n'a pas ete trouve apres telechargement : {path}")

    logger.info(f"Audio telecharge : {path}")
    return path
