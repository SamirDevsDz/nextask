"""Settings : notifications, zone de notification, démarrage automatique, syslog, données."""
import os
import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QLineEdit, QSpinBox, QComboBox,
                               QPushButton, QGridLayout)

from core import audit
from core.common import APP_NAME, IS_WIN, app_data_dir, open_location, run_cmd, is_admin
from core.widgets import Page

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _launch_cmd():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pyw}" "{os.path.abspath(sys.argv[0])}" --tray'


def _task_exists():
    out = run_cmd(["schtasks", "/query", "/tn", APP_NAME], 15)
    return APP_NAME.lower() in out.lower() and not out.startswith("ERREUR")


def autostart_enabled():
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return _task_exists()


def set_autostart(on):
    """En admin : tâche planifiée « à l'ouverture de session, privilèges les plus élevés »
    (Windows bloque les programmes élevés lancés par la clé Run). Sinon : clé Run HKCU."""
    import winreg
    if on and is_admin():
        out = run_cmd(["schtasks", "/create", "/tn", APP_NAME, "/tr", _launch_cmd(), "/sc", "onlogon",
                       "/rl", "highest", "/f"], 30)
        if "erreur" in out.lower() or "error" in out.lower():
            raise OSError(out.strip())
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _launch_cmd())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass
    if not on and _task_exists():
        run_cmd(["schtasks", "/delete", "/tn", APP_NAME, "/f"], 30)


class SettingsPage(Page):
    title = "Settings"
    subtitle = "Préférences de NexTask"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        self.s = QSettings(APP_NAME, APP_NAME)

        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.addWidget(QLabel("Comportement", objectName="section"))
        self.notif = QCheckBox("Notifications Windows quand le Flight Recorder détecte une alerte (CPU, RAM, disque)")
        self.notif.setChecked(self.s.value("ui/notify", True, type=bool))
        self.notif.toggled.connect(lambda b: self.s.setValue("ui/notify", b))
        self.tray = QCheckBox("Réduire dans la zone de notification à la fermeture (la surveillance continue)")
        self.tray.setChecked(self.s.value("ui/close_to_tray", False, type=bool))
        self.tray.toggled.connect(lambda b: self.s.setValue("ui/close_to_tray", b))
        self.auto = QCheckBox("Lancer NexTask à l'ouverture de session (réduit dans la zone de notification)")
        self.auto.setChecked(autostart_enabled())
        self.auto.setEnabled(IS_WIN)
        self.auto.toggled.connect(self._autostart)
        for w in (self.notif, self.tray, self.auto):
            v.addWidget(w)
        self.root.addWidget(card)

        card2 = QFrame(objectName="card")
        v2 = QVBoxLayout(card2)
        v2.addWidget(QLabel("Envoi syslog (Security Onion, Wazuh, Graylog, SIEM…)", objectName="section"))
        v2.addWidget(QLabel("Envoie le journal d'audit, les alertes du Flight Recorder et les alertes critiques du "
                            "module Security au format RFC 5424 (facility local0).", objectName="muted"))
        g = QGridLayout()
        en, host, port, proto = audit.syslog_config()
        self.sl_en = QCheckBox("Activer")
        self.sl_en.setChecked(en)
        self.sl_host = QLineEdit(host)
        self.sl_host.setPlaceholderText("ex. 192.168.1.50")
        self.sl_port = QSpinBox()
        self.sl_port.setRange(1, 65535)
        self.sl_port.setValue(port)
        self.sl_proto = QComboBox()
        self.sl_proto.addItems(["UDP", "TCP"])
        self.sl_proto.setCurrentText(proto)
        g.addWidget(self.sl_en, 0, 0)
        g.addWidget(QLabel("Serveur"), 1, 0)
        g.addWidget(self.sl_host, 1, 1)
        g.addWidget(QLabel("Port"), 1, 2)
        g.addWidget(self.sl_port, 1, 3)
        g.addWidget(QLabel("Protocole"), 1, 4)
        g.addWidget(self.sl_proto, 1, 5)
        v2.addLayout(g)
        hb = QHBoxLayout()
        save = QPushButton("Enregistrer")
        save.setObjectName("primary")
        save.clicked.connect(self._save_syslog)
        test = QPushButton("Envoyer un message de test")
        test.clicked.connect(self._test)
        hb.addWidget(save)
        hb.addWidget(test)
        self.sl_state = QLabel("", objectName="muted")
        hb.addWidget(self.sl_state, 1)
        v2.addLayout(hb)
        self.root.addWidget(card2)

        card3 = QFrame(objectName="card")
        v3 = QVBoxLayout(card3)
        v3.addWidget(QLabel("Données", objectName="section"))
        v3.addWidget(QLabel(f"Historique, Flight Recorder, références et journal d'audit : {app_data_dir()}", objectName="muted"))
        b = QPushButton("Ouvrir le dossier de données")
        b.clicked.connect(lambda: open_location(app_data_dir()))
        v3.addWidget(b)
        self.root.addWidget(card3)
        self.root.addStretch()

    def _autostart(self, on):
        try:
            set_autostart(on)
            audit.log("Démarrage automatique de NexTask", "activé" if on else "désactivé")
        except OSError as e:
            self.auto.blockSignals(True)
            self.auto.setChecked(not on)
            self.auto.blockSignals(False)
            audit.log("Démarrage automatique de NexTask", "", f"ÉCHEC : {e}")

    def _save_syslog(self):
        self.s.setValue("syslog/enabled", self.sl_en.isChecked())
        self.s.setValue("syslog/host", self.sl_host.text().strip())
        self.s.setValue("syslog/port", self.sl_port.value())
        self.s.setValue("syslog/proto", self.sl_proto.currentText())
        self.sl_state.setText("Enregistré.")
        audit.log("Configuration syslog", f"{self.sl_host.text().strip()}:{self.sl_port.value()}/{self.sl_proto.currentText()}"
                  f" ({'activé' if self.sl_en.isChecked() else 'désactivé'})")

    def _test(self):
        self._save_syslog()
        ok = audit.syslog('test="NexTask syslog test"', "notice", force=True)
        self.sl_state.setText("Message envoyé (vérifiez la réception côté serveur)." if ok else "Échec d'envoi (hôte/port ?).")
