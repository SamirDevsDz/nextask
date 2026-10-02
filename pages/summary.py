"""Vue d'ensemble : tableau de bord de supervision (KPI, charge, posture de sécurité, top processus, alertes)."""
import platform
import socket
import time

import psutil
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QWidget

from core import design as d
from core import security_checks as sc
from core.common import BackgroundTask, fmt_bytes, fmt_rate, fmt_duration
from core.widgets import Page, StatTile, TablePanel, LineGraph, RingGauge, AlertList, card, SERIES
from pages.sysinfo import cpu_name


def _legend(items):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(14)
    for label, color in items:
        lb = QLabel(f"<span style='color:{d.adapt(color).name()}; font-size:15px'>●</span> {label}")
        lb.setObjectName("muted")
        h.addWidget(lb)
    return w


class SummaryPage(Page):
    title = "Vue d'ensemble"
    subtitle = "État du poste en temps réel"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        self.host_lbl = QLabel("", objectName="muted")
        self.header_actions.addWidget(self.host_lbl)

        # --- rangée KPI
        grid = QGridLayout()
        grid.setSpacing(14)
        self.t_cpu = StatTile("Processeur", SERIES["cpu"], icon="cpu")
        self.t_mem = StatTile("Mémoire", SERIES["mem"], icon="memory")
        self.t_disk = StatTile("Disque", SERIES["disk"], icon="drive")
        self.t_net = StatTile("Réseau", SERIES["net"], auto_scale=True, icon="net", value_fmt=fmt_rate)
        self.t_net.graph.color2 = QColor(SERIES["net2"])
        for i, t in enumerate((self.t_cpu, self.t_mem, self.t_disk, self.t_net)):
            grid.addWidget(t, 0, i)
        self.root.addLayout(grid)

        # --- rangée 2 : charge + posture
        row2 = QHBoxLayout()
        row2.setSpacing(14)
        load, ll = card()
        head = QHBoxLayout()
        head.addWidget(QLabel("Charge système", objectName="section"))
        head.addStretch()
        head.addWidget(_legend([("CPU", SERIES["cpu"]), ("Mémoire", SERIES["mem"])]))
        ll.addLayout(head)
        self.load_graph = LineGraph(SERIES["cpu"], 100, color2=SERIES["mem"])
        self.load_graph.setMinimumHeight(140)
        ll.addWidget(self.load_graph, 1)
        row2.addWidget(load, 2)

        post, pl = card(name="cardAccent")
        pl.addWidget(QLabel("Posture de sécurité", objectName="section"))
        mid = QHBoxLayout()
        self.ring = RingGauge("score", SERIES["cpu"], size=136, thickness=11, suffix="")
        mid.addWidget(self.ring)
        mid.addSpacing(10)
        stats = QVBoxLayout()
        stats.setSpacing(6)
        self.post_crit = QLabel("—")
        self.post_warn = QLabel("—")
        self.post_ok = QLabel("—")
        for w in (self.post_crit, self.post_warn, self.post_ok):
            w.setTextFormat(Qt.RichText)
            stats.addWidget(w)
        self.post_when = QLabel("", objectName="muted")
        stats.addWidget(self.post_when)
        stats.addStretch()
        mid.addLayout(stats, 1)
        pl.addLayout(mid)
        btn = QPushButton("Ouvrir le bilan complet  →")
        btn.setObjectName("ghost")
        btn.clicked.connect(self._open_security)
        pl.addWidget(btn, 0, Qt.AlignLeft)
        row2.addWidget(post, 1)
        self.root.addLayout(row2, 4)

        # --- rangée 3 : top processus, alertes, système
        row3 = QHBoxLayout()
        row3.setSpacing(14)
        tp, tl = card()
        tl.addWidget(QLabel("Processus les plus actifs", objectName="section"))
        self.top = TablePanel(["Processus", "PID", "CPU", "Mémoire"], key_col=1, right_cols=(1,))
        self.top.make_compact()
        self.top.status.hide()
        self.top.set_bar_columns({2: 100, 3: psutil.virtual_memory().total})
        self.top.set_widths([170, 60, 100, 100])
        self.top.view.setStyleSheet("QTableView { border: none; background: transparent; }")
        tl.addWidget(self.top)
        row3.addWidget(tp, 3)

        al, alay = card()
        alay.addWidget(QLabel("Alertes santé", objectName="section"))
        self.alerts = AlertList()
        alay.addWidget(self.alerts, 1)
        row3.addWidget(al, 2)

        sy, syl = card()
        syl.addWidget(QLabel("Système", objectName="section"))
        self.sys_lbl = QLabel()
        self.sys_lbl.setWordWrap(True)
        self.sys_lbl.setTextFormat(Qt.RichText)
        syl.addWidget(self.sys_lbl)
        syl.addStretch()
        row3.addWidget(sy, 2)
        self.root.addLayout(row3, 5)

        ip = "—"
        try:
            for name, addrs in psutil.net_if_addrs().items():
                for a in addrs:
                    if getattr(a.family, "name", "") == "AF_INET" and not a.address.startswith(("127.", "169.254")):
                        ip = a.address
                        raise StopIteration
        except StopIteration:
            pass
        self._facts = [("Poste", socket.gethostname()), ("Système", f"{platform.system()} {platform.release()}"),
                       ("Processeur", cpu_name()), ("Cœurs", f"{sampler.ncores} cœurs · {sampler.ncpu} threads"),
                       ("Mémoire", fmt_bytes(psutil.virtual_memory().total)), ("Adresse IP", ip)]
        self.host_lbl.setText(f"{socket.gethostname()}  ·  {ip}")
        sampler.procs_updated.connect(self._procs)
        self.posture_task = BackgroundTask(sc.posture, self._posture_done)
        self._posture_at = 0

    # ------------------------------------------------------------
    def _open_security(self):
        win = self.window()
        from pages.security import SecurityPage
        if hasattr(win, "goto_cls"):
            win.goto_cls(SecurityPage)

    def on_show(self):
        self._procs()
        if time.time() - self._posture_at > 600:
            self._posture_at = time.time()
            self.post_when.setText("Analyse en cours…")
            self.posture_task.start()

    def _posture_done(self, checks):
        score = sc.posture_score(checks)
        crit = sum(c["status"] == "CRITIQUE" for c in checks)
        warn = sum(c["status"] == "ALERTE" for c in checks)
        ok = sum(c["status"] == "OK" for c in checks)
        if score is None:
            self.ring.set_value(0, text="—")
        else:
            col = d.SERIES["disk"] if score >= 80 else d.SERIES["net"] if score >= 60 else "#f87171"
            self.ring.set_value(score, color=col, text=str(score))
        self.post_crit.setText(f"<span style='color:{d.T('crit')}'>●</span> <b>{crit}</b> critique(s)")
        self.post_warn.setText(f"<span style='color:{d.T('warn')}'>●</span> <b>{warn}</b> alerte(s)")
        self.post_ok.setText(f"<span style='color:{d.T('ok')}'>●</span> <b>{ok}</b> contrôle(s) conforme(s)")
        self.post_when.setText("Bilan indisponible hors Windows" if score is None
                               else f"Mis à jour à {time.strftime('%H:%M')}")

    def on_tick(self):
        s = self.sampler
        f = f" · {s.freq.current / 1000:.2f} GHz" if s.freq and s.freq.current else ""
        self.t_cpu.set(f"{s.cpu:.0f} %", f"{len(s.procs)} processus{f}", s.hist["cpu"])
        self.t_mem.set(f"{s.vm.percent:.0f} %", f"{fmt_bytes(s.vm.used)} / {fmt_bytes(s.vm.total)}", s.hist["mem"])
        self.t_disk.set(f"{s.hist['disk'][-1]:.0f} %",
                        f"L {fmt_rate(s.hist['disk_r'][-1])} · É {fmt_rate(s.hist['disk_w'][-1])}", s.hist["disk"])
        self.t_net.set(fmt_rate(s.net_down), f"réception · envoi {fmt_rate(s.net_up)}", s.hist["net_down"], s.hist["net_up"])
        self.load_graph.set_data(s.hist["cpu"], s.hist["mem"])
        rows = "".join(f"<tr><td style='color:{d.T('muted')}; padding:3px 14px 3px 0'>{k}</td>"
                       f"<td style='padding:3px 0'>{v}</td></tr>" for k, v in self._facts)
        rows += (f"<tr><td style='color:{d.T('muted')}; padding:3px 14px 3px 0'>Démarré depuis</td>"
                 f"<td>{fmt_duration(s.uptime)}</td></tr>")
        self.sys_lbl.setText(f"<table>{rows}</table>")
        self._alerts()

    def _alerts(self):
        s = self.sampler
        out = []
        recent = list(s.hist["cpu"])[-10:]
        if sum(recent) / len(recent) > 85:
            out.append(("CRITIQUE", "Processeur au-delà de 85 % depuis 10 s"))
        if s.vm.percent > 90:
            out.append(("CRITIQUE", f"Mémoire saturée ({s.vm.percent:.0f} %)"))
        elif s.vm.percent > 80:
            out.append(("ALERTE", f"Mémoire élevée ({s.vm.percent:.0f} %)"))
        for p in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(p.mountpoint)
            except Exception:  # noqa: BLE001
                continue
            if u.percent >= 90 and u.total > 1 << 30:
                out.append(("CRITIQUE", f"{p.mountpoint} presque plein ({u.percent:.0f} %)"))
        if s.swap and s.swap.percent > 80:
            out.append(("ALERTE", f"Fichier d'échange à {s.swap.percent:.0f} %"))
        if s.uptime > 14 * 86400:
            out.append(("INFO", f"Pas redémarré depuis {s.uptime / 86400:.0f} jours"))
        bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if bat and not bat.power_plugged and bat.percent < 20:
            out.append(("ALERTE", f"Batterie faible ({bat.percent:.0f} %)"))
        self.alerts.set_items(out)

    def _procs(self):
        if not self.isVisible():
            return
        ps = [p for p in self.sampler.procs if p["name"] != "System Idle Process"]
        top = sorted(ps, key=lambda p: (p["cpu"], p["mem"]), reverse=True)[:9]
        self.top.set_rows([[p["name"], p["pid"], (f"{p['cpu']:.1f} %", p["cpu"]),
                            (fmt_bytes(p["mem"]), p["mem"])] for p in top])
