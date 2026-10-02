"""Summary : vue d'ensemble (tuiles, top processus, alertes santé)."""
import platform
import socket

import psutil
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QFrame, QHBoxLayout

from core.common import fmt_bytes, fmt_rate, fmt_duration
from core.widgets import Page, StatTile, TablePanel, COLORS
from pages.sysinfo import cpu_name


class SummaryPage(Page):
    title = "Summary"
    subtitle = "Vue d'ensemble de la machine"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.t_cpu = StatTile("Processeur", COLORS["cpu"])
        self.t_mem = StatTile("Mémoire", COLORS["mem"])
        self.t_disk = StatTile("Disque (activité)", COLORS["disk"])
        self.t_net = StatTile("Réseau", COLORS["net"], auto_scale=True)
        for i, t in enumerate((self.t_cpu, self.t_mem, self.t_disk, self.t_net)):
            grid.addWidget(t, 0, i)
        self.root.addLayout(grid)

        mid = QHBoxLayout()
        mid.setSpacing(12)
        # carte système
        card = QFrame(objectName="card")
        cl = QVBoxLayout(card)
        cl.addWidget(QLabel("Système", objectName="section"))
        self.sys_lbl = QLabel()
        self.sys_lbl.setWordWrap(True)
        cl.addWidget(self.sys_lbl)
        cl.addWidget(QLabel("Alertes santé", objectName="section"))
        self.alerts = QLabel()
        self.alerts.setWordWrap(True)
        cl.addWidget(self.alerts)
        cl.addStretch()
        card.setMinimumWidth(330)
        mid.addWidget(card)

        self.top_cpu = TablePanel(["Processus", "PID", "CPU %"], key_col=1, right_cols=(1, 2))
        self.top_mem = TablePanel(["Processus", "PID", "Mémoire"], key_col=1, right_cols=(1, 2))
        for title, t in (("Top CPU", self.top_cpu), ("Top mémoire", self.top_mem)):
            box = QVBoxLayout()
            box.addWidget(QLabel(title, objectName="section"))
            t.make_compact()
            t.set_widths([180, 70, 80])
            box.addWidget(t)
            mid.addLayout(box, 1)
        self.root.addLayout(mid, 1)

        self._static = (f"<b>{socket.gethostname()}</b><br>"
                        f"{platform.system()} {platform.release()} ({platform.version()})<br>"
                        f"{cpu_name()}<br>"
                        f"{self.sampler.ncores} cœurs / {self.sampler.ncpu} threads — "
                        f"RAM {fmt_bytes(psutil.virtual_memory().total)}")
        sampler.procs_updated.connect(self._procs)

    def on_tick(self):
        s = self.sampler
        f = f" @ {s.freq.current / 1000:.2f} GHz" if s.freq and s.freq.current else ""
        self.t_cpu.set(f"{s.cpu:.0f} %", f"{len(s.procs)} processus{f}", s.hist["cpu"])
        self.t_mem.set(f"{s.vm.percent:.0f} %",
                       f"{fmt_bytes(s.vm.used)} / {fmt_bytes(s.vm.total)}", s.hist["mem"])
        self.t_disk.set(f"{s.hist['disk'][-1]:.0f} %",
                        f"L {fmt_rate(s.hist['disk_r'][-1])} • É {fmt_rate(s.hist['disk_w'][-1])}",
                        s.hist["disk"])
        self.t_net.set(f"↓ {fmt_rate(s.net_down)}", f"↑ {fmt_rate(s.net_up)}",
                       s.hist["net_down"], s.hist["net_up"])
        self.t_net.graph.color2 = self.t_net.graph.color.lighter(150)
        self.sys_lbl.setText(self._static + f"<br>Démarré depuis : {fmt_duration(s.uptime)}")
        self._alerts()

    def on_show(self):
        self._procs()

    def _alerts(self):
        s = self.sampler
        out = []
        recent = list(s.hist["cpu"])[-10:]
        if sum(recent) / len(recent) > 85:
            out.append("🔴 CPU > 85 % depuis 10 s")
        if s.vm.percent > 90:
            out.append(f"🔴 Mémoire saturée ({s.vm.percent:.0f} %)")
        elif s.vm.percent > 80:
            out.append(f"🟠 Mémoire élevée ({s.vm.percent:.0f} %)")
        for p in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(p.mountpoint)
            except Exception:  # noqa: BLE001
                continue
            if u.percent >= 90:
                out.append(f"🔴 {p.mountpoint} presque plein ({u.percent:.0f} %)")
        if s.swap and s.swap.percent > 80:
            out.append(f"🟠 Fichier d'échange à {s.swap.percent:.0f} %")
        bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if bat and not bat.power_plugged and bat.percent < 20:
            out.append(f"🟠 Batterie faible ({bat.percent:.0f} %)")
        self.alerts.setText("<br>".join(out) if out else "🟢 Aucun problème détecté")

    def _procs(self):
        if not self.isVisible():
            return
        ps = [p for p in self.sampler.procs if p["pid"] not in (0,) and p["name"] != "System Idle Process"]
        top = sorted(ps, key=lambda p: p["cpu"], reverse=True)[:8]
        self.top_cpu.set_rows([[p["name"], p["pid"], (f"{p['cpu']:.1f}", p["cpu"])] for p in top])
        top = sorted(ps, key=lambda p: p["mem"], reverse=True)[:8]
        self.top_mem.set_rows([[p["name"], p["pid"], (fmt_bytes(p["mem"]), p["mem"])] for p in top])
