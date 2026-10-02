"""Processes : liste, tri, recherche, fin de tâche, priorité, suspension, détails."""
import webbrowser

import psutil
from PySide6.QtWidgets import QInputDialog, QDialog, QVBoxLayout, QPlainTextEdit, QCheckBox

from core.common import IS_WIN, fmt_bytes, fmt_rate, fmt_ts, open_location, confirm, info
from core.widgets import Page, TablePanel
from core import audit

if IS_WIN:
    PRIORITIES = {
        "Temps réel": psutil.REALTIME_PRIORITY_CLASS, "Haute": psutil.HIGH_PRIORITY_CLASS,
        "Supérieure à la normale": psutil.ABOVE_NORMAL_PRIORITY_CLASS,
        "Normale": psutil.NORMAL_PRIORITY_CLASS,
        "Inférieure à la normale": psutil.BELOW_NORMAL_PRIORITY_CLASS,
        "Basse": psutil.IDLE_PRIORITY_CLASS,
    }
else:
    PRIORITIES = {"Haute (-10)": -10, "Supérieure (-5)": -5, "Normale (0)": 0,
                  "Inférieure (10)": 10, "Basse (19)": 19}
PRIO_NAME = {v: k for k, v in PRIORITIES.items()}


class ProcessesPage(Page):
    title = "Processes"
    subtitle = "Clic droit pour les actions"

    COLS = ["Nom", "PID", "Statut", "Utilisateur", "CPU %", "Mémoire", "Disque",
            "Threads", "Priorité", "Chemin"]

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        self.table = TablePanel(self.COLS, key_col=1, right_cols=(1, 4, 5, 6, 7))
        self.table.set_widths([220, 70, 90, 120, 70, 100, 100, 70, 130, 300])
        self.table.set_bar_columns({4: 100, 5: psutil.virtual_memory().total})
        self.hide_sys = QCheckBox("Masquer les processus système")
        self.table.toolbar.insertWidget(1, self.hide_sys)
        self.hide_sys.toggled.connect(self.refresh)
        self.table.add_button("Fin de tâche", self.kill, needs_selection=True, danger=True)
        self.table.add_button("Détails", self.details, needs_selection=True)
        t = self.table
        t.add_context("Fin de tâche", self.kill)
        t.add_context("Terminer l'arborescence", self.kill_tree)
        t.add_context("-", None)
        t.add_context("Suspendre", self.suspend)
        t.add_context("Reprendre", self.resume)
        t.add_context("Définir la priorité…", self.set_priority)
        t.add_context("-", None)
        t.add_context("Ouvrir l'emplacement du fichier", lambda r: open_location(r[9]))
        t.add_context("Rechercher en ligne", lambda r: webbrowser.open(
            f"https://duckduckgo.com/?q={r[0]}+process"))
        t.add_context("Propriétés / détails", self.details)
        self.root.addWidget(self.table, 1)
        sampler.procs_updated.connect(self.refresh)
        self._sorted = False

    def on_show(self):
        self.refresh()

    def refresh(self, *_):
        if not self.isVisible():
            return
        sysusers = ("system", "service local", "local service", "network service",
                    "service réseau", "root")
        rows = []
        for p in self.sampler.procs:
            if self.hide_sys.isChecked() and (not p["user"] or p["user"].lower() in sysusers):
                continue
            disk = p["read_rate"] + p["write_rate"]
            rows.append([
                p["name"], p["pid"], p["status"], p["user"],
                (f"{p['cpu']:.1f}", p["cpu"]), (fmt_bytes(p["mem"]), p["mem"]),
                (fmt_rate(disk), disk), p["threads"],
                PRIO_NAME.get(p["nice"], str(p["nice"]) if p["nice"] is not None else "—"),
                p["exe"],
            ])
        self.table.set_rows(rows)
        if not self._sorted:
            self.table.sort_by(4)
            self._sorted = True

    # ------------------------------------------------------------ actions
    def _proc(self, row):
        try:
            return psutil.Process(int(row[1]))
        except psutil.Error as e:
            info(self, "Erreur", str(e))
            return None

    def _try(self, fn, ok_msg=None, action=None, target=""):
        try:
            fn()
            if ok_msg:
                self.window().statusBar().showMessage(ok_msg, 4000)
            if action:
                audit.log(action, target)
        except psutil.AccessDenied:
            info(self, "Accès refusé", "Droits insuffisants. Relancez NexTask en administrateur.")
            if action:
                audit.log(action, target, "ÉCHEC : accès refusé")
        except psutil.Error as e:
            info(self, "Erreur", str(e))
            if action:
                audit.log(action, target, f"ÉCHEC : {e}")

    def kill(self, row):
        p = self._proc(row)
        if p and confirm(self, "Fin de tâche", f"Terminer « {row[0]} » (PID {row[1]}) ?\n"
                                               "Les données non enregistrées seront perdues."):
            self._try(p.kill, f"{row[0]} terminé", "Fin de tâche", f"{row[0]} (PID {row[1]})")

    def kill_tree(self, row):
        p = self._proc(row)
        if not p:
            return
        try:
            children = p.children(recursive=True)
        except psutil.Error:
            children = []
        if confirm(self, "Terminer l'arborescence",
                   f"Terminer « {row[0]} » et ses {len(children)} processus enfants ?"):
            def go():
                for c in children:
                    try:
                        c.kill()
                    except psutil.Error:
                        pass
                p.kill()
            self._try(go, "Arborescence terminée", "Fin d'arborescence", f"{row[0]} (PID {row[1]}) + {len(children)} enfants")

    def suspend(self, row):
        p = self._proc(row)
        if p and confirm(self, "Suspendre", f"Suspendre « {row[0]} » ?"):
            self._try(p.suspend, f"{row[0]} suspendu", "Suspension processus", f"{row[0]} (PID {row[1]})")

    def resume(self, row):
        p = self._proc(row)
        if p:
            self._try(p.resume, f"{row[0]} repris", "Reprise processus", f"{row[0]} (PID {row[1]})")

    def set_priority(self, row):
        p = self._proc(row)
        if not p:
            return
        names = list(PRIORITIES.keys())
        cur = PRIO_NAME.get(p.nice(), names[len(names) // 2]) if p.is_running() else names[0]
        choice, ok = QInputDialog.getItem(self, "Priorité", f"Priorité de {row[0]} :", names,
                                          names.index(cur) if cur in names else 0, False)
        if ok:
            self._try(lambda: p.nice(PRIORITIES[choice]), f"Priorité : {choice}", "Priorité processus", f"{row[0]} (PID {row[1]}) -> {choice}")

    def details(self, row):
        p = self._proc(row)
        if not p:
            return
        lines = []

        def add(label, fn):
            try:
                lines.append(f"{label:<22}: {fn()}")
            except psutil.Error as e:
                lines.append(f"{label:<22}: (indisponible — {type(e).__name__})")
        with p.oneshot():
            add("Nom", p.name)
            add("PID / Parent", lambda: f"{p.pid} / {p.ppid()}")
            add("Exécutable", p.exe)
            add("Ligne de commande", lambda: " ".join(p.cmdline()))
            add("Répertoire", p.cwd)
            add("Utilisateur", p.username)
            add("Démarré le", lambda: fmt_ts(p.create_time()))
            add("Statut", p.status)
            add("Mémoire (RSS)", lambda: fmt_bytes(p.memory_info().rss))
            add("Mémoire (VMS)", lambda: fmt_bytes(p.memory_info().vms))
            add("Threads", p.num_threads)
            add("Fichiers ouverts", lambda: len(p.open_files()))
            add("Connexions réseau", lambda: len(p.net_connections()))
            if IS_WIN:
                add("Handles", p.num_handles)
            add("Enfants", lambda: ", ".join(f"{c.name()}({c.pid})" for c in p.children()) or "aucun")
        try:
            mods = [m.path for m in p.memory_maps()][:60]
            lines += ["", "Modules / DLL chargés (60 premiers) :"] + mods
        except psutil.Error:
            pass
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Détails — {row[0]}")
        dlg.resize(760, 520)
        lay = QVBoxLayout(dlg)
        txt = QPlainTextEdit("\n".join(map(str, lines)))
        txt.setReadOnly(True)
        txt.setStyleSheet("font-family: Consolas, monospace;")
        lay.addWidget(txt)
        dlg.exec()
