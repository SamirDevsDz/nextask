"""Power & Freq : fréquence CPU, batterie, plans d'alimentation, températures."""
import json
import os
import re
import tempfile

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QComboBox,
                               QPushButton)

from core.common import IS_WIN, BackgroundTask, run_cmd, powershell, fmt_duration, info, confirm
from core.widgets import Page, StatTile, LineGraph, COLORS
from core import audit


def list_power_plans():
    plans = []
    for line in run_cmd(["powercfg", "/list"]).splitlines():
        m = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27})\s+\((.+?)\)(\s*\*)?", line, re.I)
        if m:
            plans.append((m.group(1), m.group(2), bool(m.group(3))))
    return plans


def read_temperatures():
    temps = []
    if hasattr(psutil, "sensors_temperatures"):
        try:
            for chip, entries in (psutil.sensors_temperatures() or {}).items():
                for e in entries:
                    temps.append((f"{chip} {e.label}".strip(), e.current))
        except Exception:  # noqa: BLE001
            pass
    if IS_WIN and not temps:
        out = powershell("Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
                         "-ErrorAction Stop | Select-Object InstanceName,CurrentTemperature | ConvertTo-Json -Compress", 20)
        try:
            data = json.loads(out)
            for d in data if isinstance(data, list) else [data]:
                temps.append((d["InstanceName"].split("\\")[-1], d["CurrentTemperature"] / 10 - 273.15))
        except (ValueError, KeyError, TypeError):
            pass
    return temps


class PowerPage(Page):
    title = "Power & Freq"
    subtitle = "Fréquences, batterie, alimentation, températures"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        grid = QGridLayout()
        grid.setSpacing(12)
        f = psutil.cpu_freq()
        self.max_freq = (f.max if f and f.max else 5000) or 5000
        self.t_freq = StatTile("Fréquence CPU", COLORS["freq"], max_value=self.max_freq * 1.1)
        self.t_load = StatTile("Charge CPU", COLORS["cpu"])
        self.t_bat = StatTile("Batterie", COLORS["disk"])
        grid.addWidget(self.t_freq, 0, 0)
        grid.addWidget(self.t_load, 0, 1)
        grid.addWidget(self.t_bat, 0, 2)
        self.root.addLayout(grid)
        self.bat_hist = []

        row = QHBoxLayout()
        row.setSpacing(12)
        # plans d'alimentation
        card = QFrame(objectName="card")
        cl = QVBoxLayout(card)
        cl.addWidget(QLabel("Plan d'alimentation", objectName="section"))
        self.plans = QComboBox()
        cl.addWidget(self.plans)
        hb = QHBoxLayout()
        b = QPushButton("Appliquer ce plan")
        b.setObjectName("primary")
        b.clicked.connect(self._apply_plan)
        hb.addWidget(b)
        rb = QPushButton("Rapport batterie")
        rb.clicked.connect(self._battery_report)
        hb.addWidget(rb)
        er = QPushButton("Rapport énergie (60 s)")
        er.clicked.connect(self._energy_report)
        hb.addWidget(er)
        hb.addStretch()
        cl.addLayout(hb)
        if not IS_WIN:
            card.setEnabled(False)
            cl.addWidget(QLabel("Plans d'alimentation : Windows uniquement.", objectName="muted"))
        cl.addWidget(QLabel("Fréquences", objectName="section"))
        self.freq_lbl = QLabel()
        cl.addWidget(self.freq_lbl)
        cl.addStretch()
        row.addWidget(card, 1)
        # températures
        card2 = QFrame(objectName="card")
        c2 = QVBoxLayout(card2)
        c2.addWidget(QLabel("Températures", objectName="section"))
        self.temp_lbl = QLabel("Lecture…")
        self.temp_lbl.setWordWrap(True)
        c2.addWidget(self.temp_lbl)
        c2.addStretch()
        row.addWidget(card2, 1)
        self.root.addLayout(row)

        self.root.addWidget(QLabel("Fréquence par cœur (si exposée par le système)", objectName="section"))
        self.core_freq = LineGraph(COLORS["freq"], self.max_freq * 1.1)
        self.core_freq.setMinimumHeight(140)
        self.root.addWidget(self.core_freq, 1)

        self.temp_task = BackgroundTask(read_temperatures, self._temps)
        self.plan_task = BackgroundTask(list_power_plans, self._plans)
        self.ttimer = QTimer(self)
        self.ttimer.timeout.connect(lambda: self.isVisible() and self.temp_task.start())
        self.ttimer.start(10_000)
        self._loaded = False

    def on_show(self):
        if not self._loaded:
            self._loaded = True
            self.temp_task.start()
            if IS_WIN:
                self.plan_task.start()

    def on_tick(self):
        s = self.sampler
        fr = s.freq
        cur = fr.current if fr else 0
        self.t_freq.set(f"{cur / 1000:.2f} GHz" if cur else "—",
                        f"min {fr.min:.0f} / max {fr.max:.0f} MHz" if fr and fr.max else "", s.hist["freq"])
        self.t_load.set(f"{s.cpu:.0f} %", f"{s.ncores} cœurs / {s.ncpu} threads", s.hist["cpu"])
        bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if bat:
            self.bat_hist = (self.bat_hist + [bat.percent])[-60:]
            left = ("branché" if bat.power_plugged else
                    fmt_duration(bat.secsleft) + " restant" if bat.secsleft and bat.secsleft > 0 else "sur batterie")
            self.t_bat.set(f"{bat.percent:.0f} %", left, self.bat_hist)
        else:
            self.t_bat.set("—", "Aucune batterie détectée (poste fixe)")
        per = None
        try:
            per = psutil.cpu_freq(percpu=True)
        except Exception:  # noqa: BLE001
            pass
        if per and len(per) > 1:
            vals = [p.current for p in per]
            self.core_freq.points = len(vals)
            self.core_freq.set_data(vals, caption=f"{len(vals)} cœurs — min {min(vals):.0f} / max {max(vals):.0f} MHz")
            self.freq_lbl.setText(f"Moyenne : {sum(vals) / len(vals):.0f} MHz")
        else:
            self.core_freq.points = 60
            self.core_freq.set_data(s.hist["freq"], caption="fréquence globale (MHz) — 60 s")
            self.freq_lbl.setText(f"Actuelle : {cur:.0f} MHz  •  Turbo/nominale max : {self.max_freq:.0f} MHz"
                                  + ("\nWindows n'expose qu'une fréquence globale via cette API." if IS_WIN else ""))

    def _temps(self, temps):
        if temps:
            self.temp_lbl.setText("<br>".join(
                f"{'🔴' if t >= 85 else '🟠' if t >= 70 else '🟢'} {n} : <b>{t:.0f} °C</b>" for n, t in temps))
        else:
            self.temp_lbl.setText("Non disponible. Sous Windows, les capteurs ACPI exigent les droits admin "
                                  "et beaucoup de PC ne les exposent pas. Pour des températures par cœur, "
                                  "il faut un pilote dédié (ex. LibreHardwareMonitor) — extension prévue en V2.")

    def _plans(self, plans):
        self._plan_list = plans
        self.plans.clear()
        for guid, name, active in plans:
            self.plans.addItem(f"{name}{'  (actif)' if active else ''}", guid)
            if active:
                self.plans.setCurrentIndex(self.plans.count() - 1)

    def _apply_plan(self):
        guid = self.plans.currentData()
        if guid:
            out = run_cmd(["powercfg", "/setactive", guid])
            audit.log("Plan d'alimentation", self.plans.currentText(), out.strip() or "OK")
            self.plan_task.start()
            self.window().statusBar().showMessage("Plan d'alimentation appliqué", 3000)

    def _battery_report(self):
        path = os.path.join(tempfile.gettempdir(), "nextask_battery_report.html")
        out = run_cmd(["powercfg", "/batteryreport", "/output", path], 60)
        if os.path.exists(path):
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            info(self, "Rapport batterie", out)

    def _energy_report(self):
        if not confirm(self, "Rapport énergie", "Analyse de 60 s en arrière-plan (droits admin requis). Continuer ?"):
            return
        path = os.path.join(tempfile.gettempdir(), "nextask_energy_report.html")
        self._energy_task = BackgroundTask(
            lambda: (run_cmd(["powercfg", "/energy", "/output", path, "/duration", "60"], 120), path),
            self._energy_done)
        self._energy_task.start()
        self.window().statusBar().showMessage("Rapport énergie en cours (60 s)…", 65000)

    def _energy_done(self, res):
        out, path = res
        if os.path.exists(path):
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            info(self, "Rapport énergie", out)
