# -*- coding: utf-8 -*-
"""
Point d'entree dedie a PyInstaller.

PyInstaller execute le script cible comme module top-level "__main__", pas
comme membre du package : un import relatif ("from .main import main")
echoue donc une fois fige. Ce petit script utilise un import absolu et sert
uniquement de cible a l'Analysis() du fichier .spec.
"""
from cse_transcribe_gui.main import main

if __name__ == "__main__":
    main()
