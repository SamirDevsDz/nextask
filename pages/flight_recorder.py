"""Flight Recorder : enregistre l'état de la machine en continu (SQLite) pour rejouer
« ce qui s'est passé » lors d'un ralentissement."""
import csv
import json
import os
import sqlite3
import time

from PySide6.QtCore import QObject, QTimer, Qt, QSettings, QPointF, Signal
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSpinBox, QCheckBox, QComboBox, QSlider,
                               QFileDialog, QPushButton, QSplitter, QWidget, QVBoxLayout)

from core.common import APP_NAME, app_data_dir, fmt_bytes, fmt_rate, fmt_ts, confirm
from core.widgets import Page, LineGraph, TablePanel, COLORS
from core import design as d
from core import audit


class Recorder(QObject):
    event = Signal(str, str)   # (type, détail) — notifications + syslog

    def __init__(self, sampler, parent=None):
        super().__init__(parent)
        self.sampler = sampler
        self.cfg = QSettings(APP_NAME, APP_NAME)
        self.db = sqlite3.connect(os.path.join(app_data_dir(), "flight_recorder.db"))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS snap(ts REAL PRIMARY KEY, cpu REAL, mem REAL, disk REAL,
                net_up REAL, net_down REAL, top_cpu TEXT, top_mem TEXT, nproc INT);
            CREATE TABLE IF NOT EXISTS event(ts REAL, kind TEXT, detail TEXT);
            CREATE INDEX IF NOT EXISTS ev_ts ON event(ts);""")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.capture)
        self._last_event = {}
        self.apply_settings()

    # réglages persistés
    @property
    def enabled(self):
        return self.cfg.value("fr/enabled", True, type=bool)

    @property
    def interval(self):
        return self.cfg.value("fr/interval", 5, type=int)

    @property
    def retention_h(self):
        return self.cfg.value("fr/retention", 24, type=int)

    @property
    def cpu_thr(self):
        return self.cfg.value("fr/cpu_thr", 90, type=int)

    @property
    def mem_thr(self):
        return self.cfg.value("fr/mem_thr", 90, type=int)

    def apply_settings(self):
        if self.enabled:
            self.timer.start(self.interval * 1000)
        else:
            self.timer.stop()

    def capture(self):
        s = self.sampler
        if not s.procs:
            return
        now = time.time()
        procs = [p for p in s.procs if p["pid"] != 0 and p["name"] != "System Idle Process"]
        top_cpu = [(p["name"], p["pid"], round(p["cpu"], 1)) for p in
                   sorted(procs, key=lambda p: p["cpu"], reverse=True)[:8]]
        top_mem = [(p["name"], p["pid"], p["mem"]) for p in
                   sorted(procs, key=lambda p: p["mem"], reverse=True)[:8]]
        cpu_avg = sum(list(s.hist["cpu"])[-self.interval:]) / max(1, min(self.interval, 60))
        self.db.execute("INSERT OR REPLACE INTO snap VALUES (?,?,?,?,?,?,?,?,?)",
                        (now, cpu_avg, s.vm.percent, s.hist["disk"][-1], s.net_up, s.net_down,
                         json.dumps(top_cpu), json.dumps(top_mem), len(procs)))
        # événements (anti-spam : 1 par type / 2 min)
        if cpu_avg >= self.cpu_thr:
            self._event(now, "CPU élevé", f"{cpu_avg:.0f} % — {top_cpu[0][0]} ({top_cpu[0][2]} %)")
        if s.vm.percent >= self.mem_thr:
            self._event(now, "Mémoire élevée", f"{s.vm.percent:.0f} % — {top_mem[0][0]} ({fmt_bytes(top_mem[0][2])})")
        if s.hist["disk"][-1] >= 95:
            self._event(now, "Disque saturé", f"{s.hist['disk'][-1]:.0f} % d'activité")
        self.db.execute("DELETE FROM snap WHERE ts < ?", (now - self.retention_h * 3600,))
        self.db.execute("DELETE FROM event WHERE ts < ?", (now - self.retention_h * 3600 * 7,))
        self.db.commit()

    def _event(self, now, kind, detail):
        if now - self._last_event.get(kind, 0) < 120:
            return
        self._last_event[kind] = now
        self.db.execute("INSERT INTO event VALUES (?,?,?)", (now, kind, detail))
        audit.syslog(f'event="{kind}" detail="{detail}"', "warning")
        self.event.emit(kind, detail)

    def snaps(self, since):
        return self.db.execute("SELECT * FROM snap WHERE ts >= ? ORDER BY ts", (since,)).fetchall()

    def events(self, since):
        return self.db.execute("SELECT * FROM event WHERE ts >= ? ORDER BY ts DESC", (since,)).fetchall()

    def clear(self):
        self.db.execute("DELETE FROM snap")
        self.db.execute("DELETE FROM event")
        self.db.commit()

    def close(self):
        try:
            self.db.commit()
            self.db.close()
        except sqlite3.Error:
            pass


class TimelineGraph(LineGraph):
    def __init__(self):
        super().__init__(COLORS["cpu"], 100, color2=COLORS["mem"], points=2)
        self.marker = None
        self.setMinimumHeight(180)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.marker is None or len(self.series) < 2:
            return
        p = QPainter(self)
        r = self.rect().adjusted(1, 1, -1, -1)
        x = r.left() + r.width() * self.marker / (len(self.series) - 1)
        p.setPen(QPen(QColor(d.T("warn")), 2))
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        p.end()


class FlightRecorderPage(Page):
    title = "Flight Recorder"
    subtitle = "Boîte noire : rejouez l'état passé de la machine"

    RANGES = {"Dernière heure": 3600, "6 dernières heures": 6 * 3600, "24 dernières heures": 86400,
              "15 dernières minutes": 900}

    def __init__(self, sampler, recorder, parent=None):
        super().__init__(sampler, parent)
        self.rec = recorder
        # réglages (carte) + actions
        from core.widgets import card
        cfg, cl = card(QHBoxLayout, (16, 10, 16, 10))
        self.en = QCheckBox("Enregistrement actif")
        self.en.setChecked(recorder.enabled)
        self.iv = self._spin(1, 300, recorder.interval, " s")
        self.ret = self._spin(1, 168, recorder.retention_h, " h")
        self.ct = self._spin(10, 100, recorder.cpu_thr, " %")
        self.mt = self._spin(10, 100, recorder.mem_thr, " %")
        cl.addWidget(self.en)
        cl.addSpacing(12)
        for w, lbl in ((self.iv, "Intervalle"), (self.ret, "Rétention"), (self.ct, "Seuil CPU"), (self.mt, "Seuil RAM")):
            cl.addWidget(QLabel(lbl, objectName="muted"))
            w.setMinimumWidth(84)
            cl.addWidget(w)
            cl.addSpacing(8)
        cl.addStretch()
        self.en.toggled.connect(self._save)
        for w in (self.iv, self.ret, self.ct, self.mt):
            w.valueChanged.connect(self._save)
        self.root.addWidget(cfg)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(QLabel("Période", objectName="muted"))
        self.range = QComboBox()
        self.range.addItems(list(self.RANGES))
        self.range.setMinimumWidth(180)
        self.range.currentTextChanged.connect(lambda _: self.load())
        bar.addWidget(self.range)
        bar.addStretch()
        b = QPushButton("Actualiser")
        b.clicked.connect(self.load)
        bar.addWidget(b)
        ex = QPushButton("Exporter CSV")
        ex.clicked.connect(self.export)
        bar.addWidget(ex)
        clr = QPushButton("Effacer l'historique")
        clr.setObjectName("danger")
        clr.clicked.connect(self._clear)
        bar.addWidget(clr)
        self.root.addLayout(bar)

        self.graph = TimelineGraph()
        self.root.addWidget(QLabel("CPU (cyan) et mémoire (violet) — glissez le curseur ou survolez la courbe pour rejouer",
                                   objectName="muted"))
        self.root.addWidget(self.graph)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self._scrub)
        self.root.addWidget(self.slider)
        self.at = QLabel("", objectName="section")
        self.root.addWidget(self.at)

        split = QSplitter()
        self.t_cpu = TablePanel(["Processus", "PID", "CPU %"], key_col=1, right_cols=(1, 2))
        self.t_mem = TablePanel(["Processus", "PID", "Mémoire"], key_col=1, right_cols=(1, 2))
        self.t_ev = TablePanel(["Date", "Événement", "Détail"])
        self.t_ev.set_widths([150, 120, 300])
        self.t_ev.view.doubleClicked.connect(self._jump_event)
        for title, t in (("Top CPU à cet instant", self.t_cpu), ("Top mémoire à cet instant", self.t_mem),
                         ("Événements détectés (double-clic = aller à)", self.t_ev)):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(QLabel(title, objectName="section"))
            if t is not self.t_ev:
                t.make_compact()
                t.set_widths([170, 70, 80])
            v.addWidget(t)
            split.addWidget(w)
        self.root.addWidget(split, 1)
        self.snaps = []
        self.live = QTimer(self)
        self.live.timeout.connect(lambda: self.isVisible() and self.slider.value() == self.slider.maximum()
                                  and self.load())
        self.live.start(15_000)

    def _spin(self, lo, hi, val, suffix):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setSuffix(suffix)
        return s

    def _save(self, *_):
        c = self.rec.cfg
        c.setValue("fr/enabled", self.en.isChecked())
        c.setValue("fr/interval", self.iv.value())
        c.setValue("fr/retention", self.ret.value())
        c.setValue("fr/cpu_thr", self.ct.value())
        c.setValue("fr/mem_thr", self.mt.value())
        self.rec.apply_settings()

    def on_show(self):
        self.load()

    def load(self):
        since = time.time() - self.RANGES[self.range.currentText()]
        self.snaps = self.rec.snaps(since)
        at_end = self.slider.value() == self.slider.maximum()
        self.graph.points = max(2, len(self.snaps))
        self.graph.set_data([r[1] for r in self.snaps], [r[2] for r in self.snaps],
                            caption=f"{len(self.snaps)} instantanés")
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, len(self.snaps) - 1))
        if at_end:
            self.slider.setValue(self.slider.maximum())
        self.slider.blockSignals(False)
        self._scrub(self.slider.value())
        self.t_ev.set_rows([[(fmt_ts(e[0]), e[0]), e[1], e[2]] for e in self.rec.events(since)])

    def _scrub(self, i):
        if not self.snaps:
            self.at.setText("Aucune donnée encore — l'enregistrement démarre automatiquement.")
            self.graph.marker = None
            return
        i = min(i, len(self.snaps) - 1)
        ts, cpu, mem, disk, up, down, tc, tm, n = self.snaps[i]
        self.graph.marker = i
        self.graph.update()
        self.at.setText(f"{fmt_ts(ts)}   —   CPU {cpu:.0f} %   •   RAM {mem:.0f} %   •   Disque {disk:.0f} %   •   "
                        f"↑ {fmt_rate(up)}  ↓ {fmt_rate(down)}   •   {n} processus")
        self.t_cpu.set_rows([[a, b, (f"{c:.1f}", c)] for a, b, c in json.loads(tc)])
        self.t_mem.set_rows([[a, b, (fmt_bytes(c), c)] for a, b, c in json.loads(tm)])

    def _jump_event(self, idx):
        row = self.t_ev.raw_selected()
        if not row or not self.snaps:
            return
        ts = row[0][1]
        best = min(range(len(self.snaps)), key=lambda k: abs(self.snaps[k][0] - ts))
        self.slider.setValue(best)

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Exporter", "flight_recorder.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["date", "cpu_%", "ram_%", "disque_%", "envoi_o_s", "reception_o_s",
                        "top_cpu", "top_mem", "nb_processus"])
            for r in self.snaps:
                w.writerow([fmt_ts(r[0])] + [round(x, 2) if isinstance(x, float) else x for x in r[1:]])

    def _clear(self):
        if confirm(self, "Effacer", "Supprimer tout l'historique enregistré ?"):
            self.rec.clear()
            audit.log("Flight Recorder : historique effacé")
            self.load()
