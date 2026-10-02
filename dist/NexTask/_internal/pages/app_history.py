"""App history : consommation cumulée par application (CPU, disque), persistée sur disque."""
import json
import os
import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QLabel

from core.common import app_data_dir, fmt_bytes, fmt_duration, fmt_ts, confirm
from core.widgets import Page, TablePanel
from core import audit


class AppHistoryTracker(QObject):
    """Agrège en continu les deltas CPU / E-S par nom d'exécutable."""

    def __init__(self, sampler, parent=None):
        super().__init__(parent)
        self.sampler = sampler
        self.path = os.path.join(app_data_dir(), "app_history.json")
        self.started = time.time()
        self.apps = {}
        self._prev = {}  # pid -> (create, cpu_time, read, write)
        self._load()
        sampler.procs_updated.connect(self._update)
        t = QTimer(self)
        t.timeout.connect(self.save)
        t.start(60_000)

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            self.started = d.get("since", self.started)
            self.apps = d.get("apps", {})
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"since": self.started, "apps": self.apps}, f)
        except OSError:
            pass

    def reset(self):
        self.apps, self.started = {}, time.time()
        self.save()

    def _update(self):
        seen = {}
        for p in self.sampler.procs:
            if p["pid"] == 0:
                continue
            key = (p["pid"], p["create"])
            cur = (p["cpu_time"], p["read"], p["write"])
            seen[key] = cur
            a = self.apps.setdefault(p["name"], {"cpu": 0.0, "read": 0, "write": 0,
                                                 "launches": 0, "last": 0, "exe": p["exe"]})
            if key in self._prev:
                pc, pr, pw = self._prev[key]
                a["cpu"] += max(cur[0] - pc, 0)
                a["read"] += max(cur[1] - pr, 0)
                a["write"] += max(cur[2] - pw, 0)
                if cur[0] - pc > 0.01:
                    a["last"] = time.time()
            elif self._prev:  # nouveau processus apparu pendant le suivi
                a["launches"] += 1
                if p["create"] >= self.started:
                    a["cpu"] += cur[0]
                a["last"] = time.time()
            if p["exe"]:
                a["exe"] = p["exe"]
        self._prev = seen


class AppHistoryPage(Page):
    title = "App history"
    subtitle = "Consommation cumulée par application"

    def __init__(self, sampler, tracker, parent=None):
        super().__init__(sampler, parent)
        self.tracker = tracker
        self.since = QLabel("", objectName="muted")
        self.header_actions.addWidget(self.since)
        self.table = TablePanel(["Application", "Temps CPU", "Lectures disque", "Écritures disque",
                                 "Lancements", "Dernière activité", "Chemin"],
                                right_cols=(1, 2, 3, 4))
        self.table.set_widths([220, 110, 120, 120, 90, 150, 300])
        self.table.add_button("Réinitialiser l'historique", self._reset, danger=True)
        self.root.addWidget(self.table, 1)
        note = QLabel("Note : le réseau par application nécessite ETW/SRUM sous Windows et n'est pas "
                      "suivi dans cette version. Les données sont collectées tant que NexTask tourne.",
                      objectName="muted")
        note.setWordWrap(True)
        self.root.addWidget(note)
        sampler.procs_updated.connect(self.refresh)
        self._sorted = False

    def on_show(self):
        self.refresh()

    def refresh(self):
        if not self.isVisible():
            return
        self.since.setText(f"Depuis le {fmt_ts(self.tracker.started)}")
        rows = [[n, (fmt_duration(a["cpu"]), a["cpu"]), (fmt_bytes(a["read"]), a["read"]),
                 (fmt_bytes(a["write"]), a["write"]), a["launches"],
                 (fmt_ts(a["last"]) if a["last"] else "—", a["last"]), a.get("exe", "")]
                for n, a in self.tracker.apps.items()]
        self.table.set_rows(rows)
        if not self._sorted:
            self.table.sort_by(1)
            self._sorted = True

    def _reset(self):
        if confirm(self, "Réinitialiser", "Effacer tout l'historique des applications ?"):
            self.tracker.reset()
            audit.log("App history : réinitialisation")
            self.refresh()
