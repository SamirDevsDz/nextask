"""Performance : graphes détaillés CPU / mémoire / disques / réseau."""
import math

import psutil
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QPainterPath
from PySide6.QtWidgets import (QHBoxLayout, QListWidget, QListWidgetItem, QStackedWidget, QWidget, QStyledItemDelegate, QStyle,
                               QVBoxLayout, QLabel, QGridLayout, QPushButton)

from core.common import fmt_bytes, fmt_rate, fmt_duration
from core.widgets import Page, LineGraph, COLORS, SERIES
from core import design as d
from pages.sysinfo import cpu_name


def _kv_grid(pairs):
    w = QWidget()
    g = QGridLayout(w)
    g.setContentsMargins(0, 8, 0, 0)
    g.setHorizontalSpacing(28)
    labels = {}
    for i, key in enumerate(pairs):
        k = QLabel(key, objectName="muted")
        v = QLabel("—")
        v.setStyleSheet("font-size: 16px; font-weight: 650;")
        g.addWidget(k, (i // 4) * 2, i % 4)
        g.addWidget(v, (i // 4) * 2 + 1, i % 4)
        labels[key] = v
    return w, labels


class _Detail(QWidget):
    def __init__(self, title, subtitle, color, keys, auto=False, two=False):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        h = QHBoxLayout()
        t = QLabel(title)
        t.setStyleSheet("font-size: 17px; font-weight: 650;")
        h.addWidget(t)
        h.addStretch()
        self.sub = QLabel(subtitle, objectName="muted")
        h.addWidget(self.sub)
        lay.addLayout(h)
        self.graph = LineGraph(color, 100, auto, value_fmt=(fmt_rate if auto else None),
                               color2=QColor(color).lighter(160).name() if two else None)
        self.graph.setMinimumHeight(260)
        self.extra = QVBoxLayout()
        lay.addWidget(self.graph, 1)
        lay.addLayout(self.extra)
        kv, self.kv = _kv_grid(keys)
        lay.addWidget(kv)

    def set(self, key, val):
        if key in self.kv:
            self.kv[key].setText(val)


class _PerfDelegate(QStyledItemDelegate):
    """Élément de la liste Performance : titre, valeur et mini-courbe colorée."""

    def sizeHint(self, opt, idx):
        sz = super().sizeHint(opt, idx)
        sz.setHeight(62)
        return sz

    def paint(self, p, opt, idx):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(opt.rect).adjusted(2, 3, -2, -3)
        sel = bool(opt.state & QStyle.State_Selected)
        if sel or opt.state & QStyle.State_MouseOver:
            p.setPen(QPen(d.qc("border_strong" if sel else "border"), 1))
            p.setBrush(d.qc("surface2" if sel else "hover"))
            p.drawRoundedRect(r, 10, 10)
        col = d.adapt(idx.data(Qt.UserRole + 1) or SERIES["cpu"])
        if sel:
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(r.left(), r.top() + 12, 3, r.height() - 24), 1.5, 1.5)
        lines = (idx.data(Qt.DisplayRole) or "").split("\n")
        f = QFont(opt.font)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(d.qc("text"))
        p.drawText(QRectF(r.left() + 14, r.top() + 8, r.width() * 0.55, 20), Qt.AlignLeft | Qt.AlignVCenter, lines[0])
        p.setFont(opt.font)
        p.setPen(d.qc("muted"))
        if len(lines) > 1:
            p.drawText(QRectF(r.left() + 14, r.top() + 30, r.width() * 0.62, 20), Qt.AlignLeft | Qt.AlignVCenter, lines[1])
        data = idx.data(Qt.UserRole + 2) or []
        if len(data) > 2:
            box = QRectF(r.right() - 78, r.top() + 12, 66, r.height() - 24)
            mx = max(max(data), 1e-9) if idx.data(Qt.UserRole + 3) else 100.0
            step = box.width() / (len(data) - 1)
            pts = [QPointF(box.left() + i * step, box.bottom() - min(v / mx, 1) * box.height()) for i, v in enumerate(data)]
            path = QPainterPath(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            fill = QPainterPath(path)
            fill.lineTo(box.bottomRight())
            fill.lineTo(box.bottomLeft())
            c2 = QColor(col)
            c2.setAlpha(45)
            p.fillPath(fill, c2)
            p.setPen(QPen(col, 1.6))
            p.drawPath(path)
        p.restore()


class PerformancePage(Page):
    title = "Performance"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        body = QHBoxLayout()
        self.list = QListWidget(objectName="perfList")
        self.list.setItemDelegate(_PerfDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setFixedWidth(280)
        self.list.setSpacing(2)
        self.stack = QStackedWidget()
        body.addWidget(self.list)
        body.addWidget(self.stack, 1)
        self.root.addLayout(body, 1)
        self.items = []  # (type, clé, widget détail, mini-graphe item)

        # CPU
        self.cpu = _Detail("Processeur", cpu_name(), COLORS["cpu"],
                           ["Utilisation", "Vitesse", "Processus", "Threads",
                            "Cœurs", "Processeurs logiques", "Temps d'activité"])
        self.toggle = QPushButton("Afficher par processeur logique")
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self._toggle_cores)
        self.cpu.extra.addWidget(self.toggle, 0, Qt.AlignLeft)
        self.core_grid_w = QWidget()
        cg = QGridLayout(self.core_grid_w)
        cg.setSpacing(4)
        n = sampler.ncpu
        cols = max(1, math.ceil(math.sqrt(n)))
        self.core_graphs = []
        for i in range(n):
            g = LineGraph(COLORS["cpu"])
            g.setMinimumHeight(40)
            cg.addWidget(g, i // cols, i % cols)
            self.core_graphs.append(g)
        self.core_grid_w.hide()
        self.cpu.layout().insertWidget(2, self.core_grid_w, 1)
        self._add("cpu", None, "Processeur", self.cpu)

        # Mémoire
        self.mem = _Detail("Mémoire", fmt_bytes(psutil.virtual_memory().total), COLORS["mem"],
                           ["Utilisée", "Disponible", "En cache", "Total",
                            "Échange utilisé", "Échange total", "Utilisation"])
        self._add("mem", None, "Mémoire", self.mem)

        # Disques
        for name in sorted(sampler.disk_hist.keys() or self._disk_names()):
            d = _Detail(f"Disque {name}", "", COLORS["disk"],
                        ["Temps d'activité", "Lecture", "Écriture"])
            self._add("disk", name, f"Disque {name}", d)

        # Réseau
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        for name, st in stats.items():
            if not st.isup or name.lower().startswith(("lo", "loopback")):
                continue
            ipv4 = next((a.address for a in addrs.get(name, []) if a.family.name == "AF_INET"), "—")
            d = _Detail(name, f"IPv4 {ipv4}", COLORS["net"], ["Envoi", "Réception", "Vitesse lien",
                                                              "IPv4", "MTU"], auto=True, two=True)
            d.set("IPv4", ipv4)
            d.set("Vitesse lien", f"{st.speed} Mb/s" if st.speed else "—")
            d.set("MTU", str(st.mtu))
            self._add("net", name, name, d)
        self.list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.list.setCurrentRow(0)

    @staticmethod
    def _disk_names():
        try:
            return [n for n in psutil.disk_io_counters(perdisk=True) if not n.startswith(("loop", "ram"))]
        except Exception:  # noqa: BLE001
            return []

    def _add(self, kind, key, label, widget):
        it = QListWidgetItem(label)
        it.setData(Qt.UserRole + 1, {"cpu": SERIES["cpu"], "mem": SERIES["mem"], "disk": SERIES["disk"],
                                     "net": SERIES["net"]}[kind])
        it.setData(Qt.UserRole + 3, kind == "net")
        self.list.addItem(it)
        self.stack.addWidget(widget)
        self.items.append((kind, key, widget, it))

    def _toggle_cores(self, on):
        self.core_grid_w.setVisible(on)
        self.cpu.graph.setVisible(not on)

    def on_tick(self):
        s = self.sampler
        for kind, key, w, it in self.items:
            if kind == "cpu":
                it.setData(Qt.UserRole + 2, list(s.hist["cpu"])[-30:])
                it.setText(f"Processeur\n{s.cpu:.0f} %  {s.freq.current / 1000:.2f} GHz" if s.freq
                           else f"Processeur\n{s.cpu:.0f} %")
                if w.isVisible():
                    w.graph.set_data(s.hist["cpu"], caption="% utilisation — 60 s")
                    for g, h in zip(self.core_graphs, s.core_hist):
                        g.set_data(h, caption=f"{h[-1]:.0f}%")
                    threads = sum(p["threads"] for p in s.procs)
                    w.set("Utilisation", f"{s.cpu:.0f} %")
                    w.set("Vitesse", f"{s.freq.current / 1000:.2f} GHz" if s.freq else "—")
                    w.set("Processus", str(len(s.procs)))
                    w.set("Threads", str(threads))
                    w.set("Cœurs", str(s.ncores))
                    w.set("Processeurs logiques", str(s.ncpu))
                    w.set("Temps d'activité", fmt_duration(s.uptime))
            elif kind == "mem":
                vm = s.vm
                it.setData(Qt.UserRole + 2, list(s.hist["mem"])[-30:])
                it.setText(f"Mémoire\n{fmt_bytes(vm.used)} / {fmt_bytes(vm.total)} ({vm.percent:.0f} %)")
                if w.isVisible():
                    w.graph.set_data(s.hist["mem"], caption="% utilisation")
                    w.set("Utilisée", fmt_bytes(vm.used))
                    w.set("Disponible", fmt_bytes(vm.available))
                    w.set("En cache", fmt_bytes(getattr(vm, "cached", 0) or getattr(vm, "buffers", 0)))
                    w.set("Total", fmt_bytes(vm.total))
                    w.set("Échange utilisé", fmt_bytes(s.swap.used))
                    w.set("Échange total", fmt_bytes(s.swap.total))
                    w.set("Utilisation", f"{vm.percent:.0f} %")
            elif kind == "disk":
                r, wr, busy = s.disk_rates.get(key, (0, 0, 0))
                if key in s.disk_hist:
                    it.setData(Qt.UserRole + 2, list(s.disk_hist[key])[-30:])
                it.setText(f"Disque {key}\n{busy:.0f} % d'activité")
                if w.isVisible() and key in s.disk_hist:
                    w.graph.set_data(s.disk_hist[key], caption="% temps d'activité")
                    w.set("Temps d'activité", f"{busy:.0f} %")
                    w.set("Lecture", fmt_rate(r))
                    w.set("Écriture", fmt_rate(wr))
            elif kind == "net":
                up, down = s.net_rates.get(key, (0, 0))
                if key in s.net_hist:
                    it.setData(Qt.UserRole + 2, list(s.net_hist[key][1])[-30:])
                it.setText(f"{key}\n↓ {fmt_rate(down)}  ↑ {fmt_rate(up)}")
                if w.isVisible() and key in s.net_hist:
                    w.graph.set_data(s.net_hist[key][1], s.net_hist[key][0],
                                     caption="réception (plein) / envoi (clair)")
                    w.set("Envoi", fmt_rate(up))
                    w.set("Réception", fmt_rate(down))
