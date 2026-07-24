# -*- coding: utf-8 -*-
"""
Interface graphique cse-transcribe.

Architecture : cette fenetre ne fait jamais d'import lourd (torch, whisper,
pyannote) dans son propre process. Elle pilote un environnement Python
dedie (voir env_manager.py) et lance le traitement comme un sous-processus
(cse_transcribe.cli), dont elle lit la sortie en direct. Si le moteur de
transcription plante, seul le sous-processus meurt : l'interface reste
utilisable.
"""
import json
import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QProcess, QTimer, QElapsedTimer
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLineEdit, QPushButton, QComboBox, QCheckBox, QPlainTextEdit,
    QProgressBar, QFileDialog, QLabel, QMessageBox, QDialog, QScrollArea,
    QInputDialog,
)

from . import env_manager

ORG = "cse-transcribe"
APP = "cse-transcribe-gui"

MODELS = ["large-v3", "large-v3-turbo", "medium", "small"]
DEVICES = ["auto", "cuda", "cpu"]

PROGRESS_RE = re.compile(r"position actuelle dans l'enregistrement : (\d+):(\d+):(\d+) sur (\d+):(\d+):(\d+)")


def _to_seconds(h, m, s):
    return int(h) * 3600 + int(m) * 60 + int(s)


class BootstrapDialog(QDialog):
    """
    Configuration initiale : cree le venv et installe les dependances.

    Donne trois reperes distincts a l'utilisateur, plutot qu'une seule
    barre indeterminee : (1) l'etape en cours sur le nombre total d'etapes,
    (2) une phrase qui interprete le journal en direct (telechargement /
    installation / verification...), (3) un chronometre. La barre de
    progression devient chiffree des qu'un pourcentage est detecte dans
    la sortie de pip (telechargement), sinon elle reste animee.
    """

    STATUS_PATTERNS = [
        (re.compile(r"creating virtual environment|python -m venv", re.I), "Création de l'environnement Python..."),
        (re.compile(r"^collecting ", re.I | re.M), "Recherche des paquets nécessaires..."),
        (re.compile(r"^downloading ", re.I | re.M), "Téléchargement en cours..."),
        (re.compile(r"installing collected packages", re.I), "Installation des fichiers..."),
        (re.compile(r"successfully installed", re.I), "Étape terminée."),
    ]
    PERCENT_RE = re.compile(r"(\d{1,3})%")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration initiale — cse-transcribe")
        self.setMinimumWidth(600)
        self.setModal(True)

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Premier lancement : installation des composants nécessaires "
            "(transcription et reconnaissance des voix)."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.step_label = QLabel("Préparation...")
        step_font = QFont()
        step_font.setBold(True)
        step_font.setPointSize(11)
        self.step_label.setFont(step_font)
        layout.addWidget(self.step_label)

        status_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888;")
        self.elapsed_label = QLabel("")
        self.elapsed_label.setStyleSheet("color: #aaa;")
        status_row.addWidget(self.status_label, stretch=1)
        status_row.addWidget(self.elapsed_label)
        layout.addLayout(status_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indetermine par defaut
        layout.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log)

        self.close_btn = QPushButton("Fermer")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        layout.addWidget(self.close_btn)

        self._steps = []
        self._step_index = 0
        self._process = None
        self._failed = False

        self._elapsed_timer = QElapsedTimer()
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(1000)
        self._ui_timer.timeout.connect(self._update_elapsed)

    def start(self, system_python_cmd: str):
        self._steps = env_manager.bootstrap_steps(system_python_cmd)
        self._run_next_step()

    def _run_next_step(self):
        if self._step_index >= len(self._steps):
            self._ui_timer.stop()
            self.step_label.setText("Configuration terminée.")
            self.status_label.setText("")
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.close_btn.setEnabled(True)
            return

        desc, cmd = self._steps[self._step_index]
        self.step_label.setText(f"Étape {self._step_index + 1} sur {len(self._steps)} : {desc}")
        self.status_label.setText("Démarrage...")
        self.progress.setRange(0, 0)
        self.log.appendPlainText(f"\n$ {' '.join(cmd)}\n")

        self._elapsed_timer.start()
        self._ui_timer.start()

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_output)
        self._process.finished.connect(self._on_step_finished)
        self._process.start(cmd[0], cmd[1:])

    def _update_elapsed(self):
        secs = self._elapsed_timer.elapsed() // 1000
        m, s = divmod(int(secs), 60)
        self.elapsed_label.setText(f"Écoulé : {m} min {s:02d} s" if m else f"Écoulé : {s} s")

    def _on_output(self):
        data = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.log.appendPlainText(data.rstrip())
        self._interpret_output(data)

    def _interpret_output(self, data: str):
        percents = self.PERCENT_RE.findall(data)
        if percents:
            pct = int(percents[-1])
            if self.progress.maximum() == 0:
                self.progress.setRange(0, 100)
            self.progress.setValue(pct)
            self.status_label.setText(f"Téléchargement en cours... {pct}%")
            return
        for pattern, message in self.STATUS_PATTERNS:
            if pattern.search(data):
                self.status_label.setText(message)
                return

    def _on_step_finished(self, exit_code, _status):
        self._ui_timer.stop()
        if exit_code != 0:
            self._failed = True
            self.step_label.setText("Échec de la configuration.")
            self.status_label.setText("Consultez le journal ci-dessous.")
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.close_btn.setEnabled(True)
            return
        self._step_index += 1
        self._run_next_step()

    def failed(self) -> bool:
        return self._failed


EXPORT_FORMATS = {
    "Word (.docx)": ("docx", "Documents Word (*.docx)"),
    "PDF (.pdf)": ("pdf", "Documents PDF (*.pdf)"),
    "Texte (.txt)": ("txt", "Fichiers texte (*.txt)"),
}


class SpeakerNamingDialog(QDialog):
    """
    Affichee juste apres une diarisation reussie : un locuteur detecte
    (SPEAKER_00, ...) n'est qu'un identifiant technique, pas un nom. Cet
    ecran montre, pour chacun, quelques phrases prononcees (pour aider a le
    reconnaitre) et trois champs a completer (Nom / Prenom / Fonction).
    A la validation, le transcript est reecrit avec ces identites et exporte
    au format choisi (Word, PDF ou texte).
    """

    def __init__(self, out_dir: str, parent=None):
        super().__init__(parent)
        self.out_dir = out_dir
        self.exported_path = None
        self.setWindowTitle("Qui a dit quoi ? — Identification des locuteurs")
        self.resize(760, 620)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "La reconnaissance des voix a détecté plusieurs locuteurs distincts. "
            "Indiquez, pour chacun, le nom, prénom et la fonction de la personne "
            "(laissez vide si vous ne savez pas)."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        form_layout = QVBoxLayout(container)

        self.row_fields = {}
        with open(os.path.join(out_dir, "speakers_summary.json"), encoding="utf-8") as f:
            summary = json.load(f)

        for s in summary:
            if s["speaker"] == "INCONNU":
                continue
            box = QGroupBox(f"{s['speaker']}  —  {s['nombre_tours']} tours de parole, {s['duree_totale']}")
            box_layout = QVBoxLayout(box)
            for ex in s.get("exemples", [])[:3]:
                ex_label = QLabel(f"[{ex['timestamp']}] « {ex['text']} »")
                ex_label.setWordWrap(True)
                ex_label.setStyleSheet("color: #888; font-style: italic;")
                box_layout.addWidget(ex_label)

            fields_row = QHBoxLayout()
            nom_edit = QLineEdit()
            nom_edit.setPlaceholderText("Nom")
            prenom_edit = QLineEdit()
            prenom_edit.setPlaceholderText("Prénom")
            fonction_edit = QLineEdit()
            fonction_edit.setPlaceholderText("Fonction")
            fields_row.addWidget(nom_edit)
            fields_row.addWidget(prenom_edit)
            fields_row.addWidget(fonction_edit)
            box_layout.addLayout(fields_row)

            form_layout.addWidget(box)
            self.row_fields[s["speaker"]] = (nom_edit, prenom_edit, fonction_edit)

        form_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        btn_row = QHBoxLayout()
        skip_btn = QPushButton("Ignorer")
        skip_btn.clicked.connect(self.reject)
        self.validate_btn = QPushButton("Valider et exporter...")
        self.validate_btn.clicked.connect(self._on_validate)
        btn_row.addWidget(skip_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.validate_btn)
        layout.addLayout(btn_row)

    def _on_validate(self):
        mapping = {}
        for speaker_id, (nom_e, prenom_e, fonction_e) in self.row_fields.items():
            nom = nom_e.text().strip()
            prenom = prenom_e.text().strip()
            fonction = fonction_e.text().strip()
            if nom or prenom or fonction:
                mapping[speaker_id] = {"nom": nom, "prenom": prenom, "fonction": fonction}

        fmt_choice, ok = QInputDialog.getItem(
            self, "Format d'export", "Format du document de sortie :",
            list(EXPORT_FORMATS.keys()), 0, False
        )
        if not ok:
            return
        fmt_key, filter_str = EXPORT_FORMATS[fmt_choice]

        default_name = os.path.join(self.out_dir, f"transcription_identifiee.{fmt_key}")
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer sous...", default_name, filter_str
        )
        if not out_path:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            success, message = self._export(mapping, fmt_key, out_path)
        finally:
            QApplication.restoreOverrideCursor()

        if success:
            self.exported_path = out_path
            QMessageBox.information(self, "Export réussi", f"Fichier généré :\n{out_path}")
            self.accept()
        else:
            QMessageBox.critical(self, "Échec de l'export", message)

    def _export(self, mapping: dict, fmt_key: str, out_path: str):
        if not env_manager.export_deps_ready():
            install = subprocess.run(
                env_manager.export_bootstrap_step(), capture_output=True, text=True
            )
            if install.returncode != 0:
                return False, "Installation des dépendances d'export impossible :\n" + install.stderr

        mapping_path = os.path.join(self.out_dir, "_mapping_temp.json")
        try:
            with open(mapping_path, "w", encoding="utf-8") as f:
                json.dump(mapping, f, ensure_ascii=False)

            args = [
                str(env_manager.venv_python()), "-m", "cse_transcribe.export_cli",
                "--transcript", os.path.join(self.out_dir, "transcript_diarized.json"),
                "--mapping", mapping_path,
                "--format", fmt_key,
                "--output", out_path,
            ]
            env = os.environ.copy()
            env["PYTHONPATH"] = str(env_manager.repo_root())
            result = subprocess.run(args, env=env, capture_output=True, text=True)
        finally:
            if os.path.exists(mapping_path):
                os.remove(mapping_path)

        if result.returncode != 0:
            return False, result.stderr or "Erreur inconnue."
        return True, ""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("cse-transcribe — Transcription et reconnaissance des voix")
        self.setMinimumSize(760, 640)

        self.settings = QSettings(ORG, APP)
        self.process: QProcess | None = None
        self.last_out_dir: str | None = None
        self.total_duration_sec: int | None = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ---------------- Fichiers ----------------
        file_group = QGroupBox("Fichier")
        file_form = QFormLayout(file_group)

        self.audio_edit = QLineEdit(self.settings.value("last_audio", ""))
        audio_browse = QPushButton("Parcourir...")
        audio_browse.clicked.connect(self._browse_audio)
        audio_row = QHBoxLayout()
        audio_row.addWidget(self.audio_edit)
        audio_row.addWidget(audio_browse)
        file_form.addRow("Audio / video :", audio_row)

        self.out_edit = QLineEdit(self.settings.value("last_out_dir", ""))
        out_browse = QPushButton("Parcourir...")
        out_browse.clicked.connect(self._browse_out_dir)
        out_row = QHBoxLayout()
        out_row.addWidget(self.out_edit)
        out_row.addWidget(out_browse)
        file_form.addRow("Dossier de sortie :", out_row)

        root.addWidget(file_group)

        # ---------------- Options ----------------
        opt_group = QGroupBox("Options")
        opt_form = QFormLayout(opt_group)

        self.model_combo = QComboBox()
        self.model_combo.addItems(MODELS)
        self.model_combo.setCurrentText(self.settings.value("model", "large-v3"))
        opt_form.addRow("Modele Whisper :", self.model_combo)

        self.language_edit = QLineEdit(self.settings.value("language", "fr"))
        opt_form.addRow("Langue :", self.language_edit)

        self.device_combo = QComboBox()
        self.device_combo.addItems(DEVICES)
        self.device_combo.setCurrentText(self.settings.value("device", "auto"))
        opt_form.addRow("Materiel :", self.device_combo)

        self.prompt_file_edit = QLineEdit(self.settings.value("prompt_file", ""))
        prompt_browse = QPushButton("Parcourir...")
        prompt_browse.clicked.connect(self._browse_prompt_file)
        prompt_row = QHBoxLayout()
        prompt_row.addWidget(self.prompt_file_edit)
        prompt_row.addWidget(prompt_browse)
        opt_form.addRow("Vocabulaire initial (optionnel) :", prompt_row)

        self.hf_token_edit = QLineEdit(self.settings.value("hf_token", ""))
        self.hf_token_edit.setEchoMode(QLineEdit.Password)
        opt_form.addRow("Token Hugging Face :", self.hf_token_edit)

        self.skip_diarization_check = QCheckBox("Transcription seule (sans reconnaissance des locuteurs)")
        opt_form.addRow("", self.skip_diarization_check)

        root.addWidget(opt_group)

        # ---------------- Actions ----------------
        actions_row = QHBoxLayout()
        self.run_btn = QPushButton("Lancer le traitement")
        self.run_btn.clicked.connect(self._start_run)
        self.cancel_btn = QPushButton("Annuler")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_run)
        self.open_folder_btn = QPushButton("Ouvrir le dossier de resultats")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._open_results_folder)
        actions_row.addWidget(self.run_btn)
        actions_row.addWidget(self.cancel_btn)
        actions_row.addWidget(self.open_folder_btn)
        root.addLayout(actions_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        root.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        root.addWidget(self.log, stretch=1)

    # ---------------- Selecteurs de fichiers ----------------
    def _browse_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir un fichier audio ou video", "",
            "Audio/Video (*.mp3 *.mp4 *.wav *.m4a *.mkv *.mov *.avi);;Tous les fichiers (*)"
        )
        if path:
            self.audio_edit.setText(path)
            if not self.out_edit.text():
                self.out_edit.setText(str(Path(path).parent / (Path(path).stem + "_transcription")))

    def _browse_out_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Choisir le dossier de sortie", "")
        if path:
            self.out_edit.setText(path)

    def _browse_prompt_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier de vocabulaire", "", "Texte (*.txt)")
        if path:
            self.prompt_file_edit.setText(path)

    def _open_results_folder(self):
        if self.last_out_dir and os.path.isdir(self.last_out_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_out_dir))

    # ---------------- Lancement du traitement ----------------
    def _save_settings(self):
        self.settings.setValue("last_audio", self.audio_edit.text())
        self.settings.setValue("last_out_dir", self.out_edit.text())
        self.settings.setValue("model", self.model_combo.currentText())
        self.settings.setValue("language", self.language_edit.text())
        self.settings.setValue("device", self.device_combo.currentText())
        self.settings.setValue("prompt_file", self.prompt_file_edit.text())
        self.settings.setValue("hf_token", self.hf_token_edit.text())

    def _start_run(self):
        audio = self.audio_edit.text().strip()
        out_dir = self.out_edit.text().strip()
        if not audio or not os.path.isfile(audio):
            QMessageBox.warning(self, "Fichier manquant", "Choisissez un fichier audio/video valide.")
            return
        if not out_dir:
            QMessageBox.warning(self, "Dossier manquant", "Choisissez un dossier de sortie.")
            return
        if not self.skip_diarization_check.isChecked() and not self.hf_token_edit.text().strip():
            QMessageBox.warning(
                self, "Token manquant",
                "Un token Hugging Face est necessaire pour la reconnaissance des locuteurs "
                "(ou cochez \"Transcription seule\")."
            )
            return

        self._save_settings()
        self.last_out_dir = out_dir
        self.total_duration_sec = None
        self.log.clear()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        args = [
            "-m", "cse_transcribe.cli",
            "--audio", audio,
            "--out-dir", out_dir,
            "--model", self.model_combo.currentText(),
            "--language", self.language_edit.text().strip() or "fr",
            "--device", self.device_combo.currentText(),
        ]
        if self.prompt_file_edit.text().strip():
            args += ["--initial-prompt-file", self.prompt_file_edit.text().strip()]
        if self.skip_diarization_check.isChecked():
            args += ["--skip-diarization"]

        env = os.environ.copy()
        env["PYTHONPATH"] = str(env_manager.repo_root())
        if self.hf_token_edit.text().strip():
            env["HF_TOKEN"] = self.hf_token_edit.text().strip()

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        qenv = self.process.processEnvironment()
        for k, v in env.items():
            qenv.insert(k, v)
        self.process.setProcessEnvironment(qenv)
        self.process.readyReadStandardOutput.connect(self._on_output)
        self.process.finished.connect(self._on_finished)
        self.process.start(str(env_manager.venv_python()), args)

        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.open_folder_btn.setEnabled(False)

    def _cancel_run(self):
        if self.process:
            self.process.kill()

    def _on_output(self):
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self.log.appendPlainText(line)
            m = PROGRESS_RE.search(line)
            if m:
                current = _to_seconds(*m.groups()[0:3])
                total = _to_seconds(*m.groups()[3:6])
                if total > 0:
                    self.total_duration_sec = total
                    pct = min(95, int(current / total * 95))  # reserve 5% pour la diarisation/fusion
                    self.progress.setValue(pct)

    def _on_finished(self, exit_code, _status):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if exit_code == 0:
            self.progress.setValue(100)
            self.open_folder_btn.setEnabled(True)
            self.log.appendPlainText("\n=== Traitement termine avec succes ===")
            self._maybe_offer_speaker_naming()
        else:
            self.log.appendPlainText(f"\n=== Le traitement s'est arrete (code {exit_code}) ===")

    def _maybe_offer_speaker_naming(self):
        if self.skip_diarization_check.isChecked() or not self.last_out_dir:
            return
        summary_path = os.path.join(self.last_out_dir, "speakers_summary.json")
        if not os.path.isfile(summary_path):
            return
        dialog = SpeakerNamingDialog(self.last_out_dir, self)
        dialog.exec()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setOrganizationName(ORG)

    if not env_manager.is_ready():
        system_python = env_manager.find_system_python()
        if not system_python:
            QMessageBox.critical(
                None, "Python requis",
                "Aucun Python 3.10+ n'a ete trouve sur ce poste. Installez Python depuis "
                "python.org (cochez \"Add python.exe to PATH\" pendant l'installation) "
                "puis relancez cse-transcribe."
            )
            webbrowser.open("https://www.python.org/downloads/")
            sys.exit(1)

        dialog = BootstrapDialog()
        dialog.start(system_python)
        dialog.exec()
        if dialog.failed():
            sys.exit(1)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
