"""Baseline : photo « état de référence » du poste puis comparaison (qu'est-ce qui a changé ?)."""
import json
import os
import socket
import sqlite3
import time

import psutil
from PySide6.QtWidgets import (QHBoxLayout, QPushButton, QLabel, QComboBox, QInputDialog, QSplitter, QWidget,
                               QVBoxLayout)

from core import audit
from core import security_checks as sc
from core.common import IS_WIN, BackgroundTask, app_data_dir, fmt_ts, ps_json, as_list, confirm
from core.widgets import Page, TablePanel, STATUS_COLORS

CATEGORIES = {
    "services": "Services", "startup": "Démarrage", "apps": "Logiciels", "drivers": "Pilotes",
    "ports": "Ports en écoute", "admins": "Administrateurs locaux", "tasks": "Tâches planifiées",
    "hotfixes": "Correctifs (KB)",
}


def take_snapshot(progress=None):
    snap = {}
    if IS_WIN:
        svc = {}
        for s in psutil.win_service_iter():
            try:
                d = s.as_dict()
                svc[d["name"]] = f"démarrage={d['start_type']} | {d['binpath']}"
            except (psutil.Error, OSError):
                continue
        snap["services"] = svc
    from pages.startup import _collect as st
    snap["startup"] = {f"{i['name']} [{i['source']}]": f"{i['cmd']} | {'activé' if i['enabled'] else 'désactivé'}" for i in st()}
    from pages.installed_apps import _collect as apps
    snap["apps"] = {f"{a['name']} [{a['scope']}]": a["ver"] for a in apps(False)}
    from pages.drivers import _collect as drv
    d = drv()
    snap["drivers"] = {f"{r[0]} ({r[7]})": f"{r[3]} | signé={r[5]}" for r in d["pnp"]} or \
                      {r[0]: r[2] for r in d["kernel"]}
    ports = {}
    try:
        names = {p.pid: p.info["name"] for p in psutil.process_iter(["name"])}
        for c in psutil.net_connections(kind="inet"):
            if c.status == "LISTEN" or (c.type == socket.SOCK_DGRAM and not c.raddr):
                proto = "TCP" if c.type == socket.SOCK_STREAM else "UDP"
                if c.laddr and c.laddr.port < 49152:   # on ignore les ports éphémères
                    ports[f"{proto}/{c.laddr.port}"] = names.get(c.pid, "?")
    except (psutil.Error, OSError):
        pass
    snap["ports"] = ports
    snap["admins"] = {a: "membre" for a in sc.local_admins()}
    if IS_WIN:
        snap["tasks"] = {(t.get("p") or "") + (t.get("n") or ""): f"{t.get('a', '')} | {t.get('s', '')}"
                         for t in as_list(ps_json(sc.TASKS_PS, 90))}
        snap["hotfixes"] = {str(h.get("HotFixID")): str(h.get("Description") or "") for h in
                            as_list(ps_json("Get-HotFix | Select-Object HotFixID,Description | ConvertTo-Json -Compress", 60))}
    return snap


def diff(old, new):
    rows = []
    for cat in CATEGORIES:
        a, b = old.get(cat, {}), new.get(cat, {})
        if not a and not b:
            continue
        for k in sorted(set(a) | set(b)):
            if k not in a:
                rows.append((cat, k, "Ajouté", "", b[k]))
            elif k not in b:
                rows.append((cat, k, "Supprimé", a[k], ""))
            elif a[k] != b[k]:
                rows.append((cat, k, "Modifié", a[k], b[k]))
    return rows


class Store:
    def __init__(self):
        self.db = sqlite3.connect(os.path.join(app_data_dir(), "baseline.db"))
        self.db.execute("CREATE TABLE IF NOT EXISTS snapshot(id INTEGER PRIMARY KEY, ts REAL, label TEXT, host TEXT, data TEXT)")

    def add(self, label, data):
        self.db.execute("INSERT INTO snapshot(ts,label,host,data) VALUES (?,?,?,?)",
                        (time.time(), label, socket.gethostname(), json.dumps(data)))
        self.db.commit()

    def list(self):
        return self.db.execute("SELECT id, ts, label, host, length(data) FROM snapshot ORDER BY ts DESC").fetchall()

    def get(self, sid):
        r = self.db.execute("SELECT data FROM snapshot WHERE id=?", (sid,)).fetchone()
        return json.loads(r[0]) if r else {}

    def delete(self, sid):
        self.db.execute("DELETE FROM snapshot WHERE id=?", (sid,))
        self.db.commit()


CHANGE_COLORS = {"Ajouté": STATUS_COLORS["ALERTE"], "Supprimé": STATUS_COLORS["INFO"], "Modifié": "#a855f7"}


class BaselinePage(Page):
    title = "Baseline"
    subtitle = "Référence du poste et détection des changements"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        self.store = Store()
        bar = QHBoxLayout()
        self.b_new = QPushButton("Créer une référence maintenant")
        self.b_new.setObjectName("primary")
        self.b_new.clicked.connect(self._new)
        bar.addWidget(self.b_new)
        bar.addSpacing(20)
        bar.addWidget(QLabel("Comparer"))
        self.a = QComboBox()
        self.b = QComboBox()
        self.a.setMinimumWidth(260)
        self.b.setMinimumWidth(260)
        bar.addWidget(self.a)
        bar.addWidget(QLabel("avec"))
        bar.addWidget(self.b)
        self.b_cmp = QPushButton("Comparer")
        self.b_cmp.clicked.connect(self._compare)
        bar.addWidget(self.b_cmp)
        bar.addStretch()
        self.root.addLayout(bar)
        self.state = QLabel("Astuce : créez une référence sur un poste « propre » (après installation/masterisation), "
                            "puis comparez après un incident ou une mise à jour.", objectName="muted")
        self.state.setWordWrap(True)
        self.root.addWidget(self.state)

        split = QSplitter()
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Références enregistrées", objectName="section"))
        self.snaps = TablePanel(["ID", "Date", "Libellé", "Poste"], key_col=0, right_cols=(0,))
        self.snaps.make_compact()
        self.snaps.set_widths([40, 140, 180, 120])
        self.snaps.add_button("Supprimer", self._delete, needs_selection=True, danger=True)
        lv.addWidget(self.snaps)
        split.addWidget(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("Changements", objectName="section")
        rv.addWidget(self.summary)
        self.diff_tbl = TablePanel(["Catégorie", "Élément", "Changement", "Avant", "Après"])
        self.diff_tbl.set_widths([150, 300, 100, 300, 300])
        rv.addWidget(self.diff_tbl)
        split.addWidget(right)
        split.setSizes([420, 900])
        self.root.addWidget(split, 1)

        self.snap_task = BackgroundTask(take_snapshot, self._snap_done)
        self.cmp_task = BackgroundTask(self._cmp_job, self._cmp_done)
        self._label = ""
        self.refresh_list()

    def refresh_list(self):
        rows = self.store.list()
        self.snaps.set_rows([[r[0], (fmt_ts(r[1]), r[1]), r[2], r[3]] for r in rows])
        for combo, current in ((self.a, True), (self.b, False)):
            combo.clear()
            if not current:
                combo.addItem("État actuel du poste", None)
            for r in rows:
                combo.addItem(f"#{r[0]} {fmt_ts(r[1])} — {r[2]}", r[0])
        if self.b.count() and self.a.count():
            self.b.setCurrentIndex(0)

    def _new(self):
        label, ok = QInputDialog.getText(self, "Nouvelle référence", "Libellé (ex. « Poste propre après masterisation ») :")
        if not ok:
            return
        self._label = label.strip() or "Référence"
        if self.snap_task.start():
            self.state.setText("Capture en cours (services, logiciels, pilotes, ports, tâches, correctifs… 30-90 s)…")
            self.b_new.setEnabled(False)

    def _snap_done(self, data):
        self.store.add(self._label, data)
        n = sum(len(v) for v in data.values())
        self.state.setText(f"Référence « {self._label} » enregistrée ({n} éléments).")
        self.b_new.setEnabled(True)
        audit.log("Baseline : référence créée", self._label)
        self.refresh_list()

    def _cmp_job(self, sid_a, sid_b):
        old = self.store.get(sid_a)
        new = self.store.get(sid_b) if sid_b else take_snapshot()
        return diff(old, new)

    def _compare(self):
        sid_a = self.a.currentData()
        if sid_a is None:
            self.state.setText("Créez d'abord une référence.")
            return
        if self.cmp_task.start(sid_a, self.b.currentData()):
            self.state.setText("Comparaison en cours" + (" (capture de l'état actuel…)" if self.b.currentData() is None else "…"))

    def _cmp_done(self, rows):
        counts = {k: sum(r[2] == k for r in rows) for k in CHANGE_COLORS}
        self.summary.setText(f"Changements : {len(rows)}  —  " + "  •  ".join(f"{v} {k.lower()}(s)" for k, v in counts.items()))
        self.state.setText(f"Comparaison terminée : {self.a.currentText()}  →  {self.b.currentText()}")
        self.diff_tbl.set_rows([[CATEGORIES.get(c, c), k, (ch, ch, CHANGE_COLORS[ch]), a, b] for c, k, ch, a, b in rows])

    def _delete(self, row):
        if confirm(self, "Supprimer", f"Supprimer la référence #{row[0]} « {row[2]} » ?"):
            self.store.delete(int(row[0]))
            audit.log("Baseline : référence supprimée", f"#{row[0]} {row[2]}")
            self.refresh_list()
