# -*- coding: utf-8 -*-
"""
Deux canaux de journalisation :
  - fichier .log : tout, niveau DEBUG, horodate, avec tracebacks complets -> pour le debug
    - console : uniquement des phrases utilisateur claires en francais, niveau INFO
    """
import logging
import os
import sys
import datetime


class FriendlyConsoleFormatter(logging.Formatter):
      ICONS = {
                logging.INFO: "->",
                logging.WARNING: "!!",
                logging.ERROR: "XX",
      }

    def format(self, record):
              icon = self.ICONS.get(record.levelno, "..")
              ts = datetime.datetime.now().strftime("%H:%M:%S")
              return f"[{ts}] {icon} {record.getMessage()}"


def setup_logging(out_dir: str, run_name: str = "run"):
      os.makedirs(os.path.join(out_dir, "logs"), exist_ok=True)
      ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
      log_path = os.path.join(out_dir, "logs", f"{run_name}_{ts}.log")

    logger = logging.getLogger("cse_transcribe")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
              "%(asctime)s | %(levelname)-7s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
    ))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(FriendlyConsoleFormatter())
    logger.addHandler(console_handler)

    logger.info(f"Journal detaille de cette execution : {log_path}")
    return logger, log_path
