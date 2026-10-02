"""Services : liste des services, démarrer / arrêter / redémarrer / type de démarrage."""
import psutil
from PySide6.QtWidgets import QInputDialog, QComboBox

from core.common import IS_WIN, BackgroundTask, run_cmd, powershell, confirm, info
from core.widgets import Page, TablePanel
from core import audit

STATUS_FR = {"running": "En cours", "stopped": "Arrêté", "start_pending": "Démarrage…",
             "stop_pending": "Arrêt…", "paused": "En pause", "pause_pending": "Pause…",
             "continue_pending": "Reprise…"}
START_FR = {"automatic": "Automatique", "manual": "Manuel", "disabled": "Désactivé"}
START_SC = {"Automatique": "auto", "Automatique (différé)": "delayed-auto",
            "Manuel": "demand", "Désactivé": "disabled"}


def _collect():
    rows = []
    if IS_WIN:
        for s in psutil.win_service_iter():
            try:
                d = s.as_dict()
            except (psutil.Error, OSError):
                continue
            rows.append([d["name"], d["display_name"], STATUS_FR.get(d["status"], d["status"]),
                         START_FR.get(d["start_type"], d["start_type"]), d["pid"] or "",
                         d["username"] or "", d["binpath"] or "", d.get("description") or ""])
    else:
        enabled = {}
        for line in run_cmd(["systemctl", "list-unit-files", "--type=service", "--no-legend",
                             "--no-pager"]).splitlines():
            p = line.split()
            if len(p) >= 2:
                enabled[p[0]] = p[1]
        for line in run_cmd(["systemctl", "list-units", "--type=service", "--all", "--no-legend",
                             "--no-pager", "--plain"]).splitlines():
            p = line.split(None, 4)
            if len(p) < 4:
                continue
            rows.append([p[0], p[4] if len(p) > 4 else "", "En cours" if p[3] == "running" else p[3],
                         enabled.get(p[0], ""), "", "", "", ""])
    return rows


class ServicesPage(Page):
    title = "Services"
    subtitle = "Services Windows" if IS_WIN else "Services systemd"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        self.table = TablePanel(["Nom", "Nom complet", "État", "Démarrage", "PID", "Compte",
                                 "Chemin", "Description"], right_cols=(4,))
        self.table.set_widths([180, 260, 100, 110, 70, 160, 300, 300])
        self.filter = QComboBox()
        self.filter.addItems(["Tous", "En cours", "Arrêté"])
        self.filter.currentTextChanged.connect(lambda _: self._apply())
        self.table.toolbar.insertWidget(1, self.filter)
        t = self.table
        t.add_button("Actualiser", self.load)
        t.add_button("Démarrer", lambda r: self._action("start", r), needs_selection=True)
        t.add_button("Arrêter", lambda r: self._action("stop", r), needs_selection=True, danger=True)
        t.add_button("Redémarrer", lambda r: self._action("restart", r), needs_selection=True)
        t.add_context("Démarrer", lambda r: self._action("start", r))
        t.add_context("Arrêter", lambda r: self._action("stop", r))
        t.add_context("Redémarrer", lambda r: self._action("restart", r))
        t.add_context("Type de démarrage…", self._start_type)
        self.root.addWidget(self.table, 1)
        self.rows = []
        self.task = BackgroundTask(_collect, self._show)
        self.act = BackgroundTask(self._run_action, self._action_done)
        self._loaded = False

    def on_show(self):
        if not self._loaded:
            self.load()

    def load(self):
        if self.task.start():
            self.table.status.setText("Chargement des services…")

    def _show(self, rows):
        self._loaded = True
        self.rows = rows
        self._apply()

    def _apply(self):
        f = self.filter.currentText()
        self.table.set_rows([r for r in self.rows if f == "Tous" or r[2] == f])

    # ------------------------------------------------------------ actions
    @staticmethod
    def _run_action(verb, name):
        if IS_WIN:
            ps = {"start": "Start-Service", "stop": "Stop-Service -Force",
                  "restart": "Restart-Service -Force"}[verb]
            safe = name.replace("'", "''")
            return powershell(f"{ps} -Name '{safe}' -ErrorAction Stop; 'OK'", 60)
        return run_cmd(["systemctl", verb, name], 60) or "OK"

    def _action(self, verb, row):
        labels = {"start": "Démarrer", "stop": "Arrêter", "restart": "Redémarrer"}
        if verb != "start" and not confirm(self, labels[verb],
                                           f"{labels[verb]} le service « {row[1] or row[0]} » ?\n"
                                           "Les services dépendants peuvent être affectés."):
            return
        self._last = (labels[verb], row[0])
        if self.act.start(verb, row[0]):
            self.window().statusBar().showMessage(f"{labels[verb]} {row[0]}…")

    def _action_done(self, out):
        out = (out or "").strip()
        act, name = getattr(self, "_last", ("Service", "?"))
        audit.log(f"Service : {act}", name, "OK" if out.endswith("OK") else f"ÉCHEC : {out[-200:]}")
        if out and not out.endswith("OK"):
            info(self, "Résultat", out[-800:] + "\n\nAstuce : la plupart des actions exigent les droits administrateur.")
        self.window().statusBar().showMessage("Terminé", 3000)
        self.load()

    def _start_type(self, row):
        if not IS_WIN:
            choice, ok = QInputDialog.getItem(self, "Démarrage", row[0], ["enable", "disable"], 0, False)
            if ok and confirm(self, "Démarrage", f"systemctl {choice} {row[0]} ?"):
                out = run_cmd(["systemctl", choice, row[0]]) or "OK"
                audit.log(f"Service : {choice}", row[0], out)
                info(self, "Résultat", out)
                self.load()
            return
        names = list(START_SC)
        choice, ok = QInputDialog.getItem(self, "Type de démarrage", f"Service {row[0]} :", names, 0, False)
        if ok and confirm(self, "Type de démarrage", f"Passer « {row[0]} » en {choice} ?"):
            out = run_cmd(["sc", "config", row[0], "start=", START_SC[choice]])
            audit.log("Service : type de démarrage", f"{row[0]} -> {choice}",
                      "OK" if "SUCCESS" in out.upper() or "RÉUSSI" in out.upper() else out)
            info(self, "Résultat", out)
            self.load()
