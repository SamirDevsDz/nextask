"""Échantillonneur central : métriques système (1 s) + liste des processus (2 s)."""
import time
from collections import deque

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

from .common import BackgroundTask

HISTORY = 60
PROC_ATTRS = ["pid", "ppid", "name", "username", "memory_info", "num_threads", "status",
              "exe", "create_time", "cpu_times", "io_counters", "nice"]


def _collect_processes(prev_io, ncpu):
    now = time.time()
    procs, io_now = [], {}
    for p in psutil.process_iter(PROC_ATTRS, ad_value=None):
        if p.pid == 0:   # « Processus inactif du système » : fausserait les totaux
            continue
        try:
            cpu = p.cpu_percent(None) / ncpu   # normalisé 0-100 % comme Windows
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            cpu = 0.0
        i = p.info
        io = i.get("io_counters")
        rb = getattr(io, "read_bytes", 0) or 0
        wb = getattr(io, "write_bytes", 0) or 0
        io_now[i["pid"]] = (rb, wb, now)
        rrate = wrate = 0.0
        if i["pid"] in prev_io:
            prb, pwb, pt = prev_io[i["pid"]]
            dt = max(now - pt, 0.001)
            rrate, wrate = max(rb - prb, 0) / dt, max(wb - pwb, 0) / dt
        ct = i.get("cpu_times")
        procs.append({
            "pid": i["pid"], "ppid": i.get("ppid") or 0,
            "name": i.get("name") or "?",
            "user": (i.get("username") or "").split("\\")[-1],
            "cpu": cpu,
            "mem": getattr(i.get("memory_info"), "rss", 0) or 0,
            "threads": i.get("num_threads") or 0,
            "status": i.get("status") or "",
            "exe": i.get("exe") or "",
            "create": i.get("create_time") or 0,
            "cpu_time": (ct.user + ct.system) if ct else 0.0,
            "read": rb, "write": wb, "read_rate": rrate, "write_rate": wrate,
            "nice": i.get("nice"),
        })
    return procs, io_now


class Sampler(QObject):
    updated = Signal()          # métriques système rafraîchies
    procs_updated = Signal()    # liste des processus rafraîchie

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ncpu = psutil.cpu_count() or 1
        self.ncores = psutil.cpu_count(logical=False) or self.ncpu
        h = lambda: deque([0.0] * HISTORY, maxlen=HISTORY)  # noqa: E731
        self.hist = {"cpu": h(), "mem": h(), "disk": h(), "net_up": h(), "net_down": h(),
                     "freq": h(), "disk_r": h(), "disk_w": h()}
        self.core_hist = [h() for _ in range(self.ncpu)]
        self.disk_hist, self.net_hist = {}, {}
        self.cpu = 0.0
        self.per_cpu = [0.0] * self.ncpu
        self.freq = None
        self.vm = psutil.virtual_memory()
        self.swap = psutil.swap_memory()
        self.disk_rates = {}   # disque -> (lecture/s, écriture/s, actif %)
        self.net_rates = {}    # interface -> (envoi/s, réception/s)
        self.procs = []
        self.boot = psutil.boot_time()

        psutil.cpu_percent(percpu=True)
        self._last_t = time.time()
        self._last_disk = self._safe(lambda: psutil.disk_io_counters(perdisk=True)) or {}
        self._last_net = self._safe(lambda: psutil.net_io_counters(pernic=True)) or {}
        self._prev_io = {}
        self._proc_task = BackgroundTask(_collect_processes, self._procs_done)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._n = 0

    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return None

    def start(self, interval_ms=1000):
        self.timer.start(interval_ms)
        self._proc_task.start(self._prev_io, self.ncpu)

    def set_interval(self, ms):
        self.timer.setInterval(ms)

    def _tick(self):
        now = time.time()
        dt = max(now - self._last_t, 0.001)
        self._last_t = now

        self.per_cpu = psutil.cpu_percent(percpu=True)
        self.cpu = sum(self.per_cpu) / len(self.per_cpu)
        self.hist["cpu"].append(self.cpu)
        for i, v in enumerate(self.per_cpu[: len(self.core_hist)]):
            self.core_hist[i].append(v)

        self.freq = self._safe(psutil.cpu_freq)
        self.hist["freq"].append(self.freq.current if self.freq else 0)
        self.vm = psutil.virtual_memory()
        self.swap = self._safe(psutil.swap_memory) or self.swap
        self.hist["mem"].append(self.vm.percent)

        # disques
        disks = self._safe(lambda: psutil.disk_io_counters(perdisk=True)) or {}
        tot_r = tot_w = 0.0
        max_busy = 0.0
        for name, c in disks.items():
            if name.startswith(("loop", "ram")):
                continue
            p = self._last_disk.get(name)
            if not p:
                continue
            r = max(c.read_bytes - p.read_bytes, 0) / dt
            w = max(c.write_bytes - p.write_bytes, 0) / dt
            if hasattr(c, "busy_time"):
                busy = (c.busy_time - p.busy_time) / (dt * 10)
            else:
                busy = ((c.read_time - p.read_time) + (c.write_time - p.write_time)) / (dt * 10)
            busy = max(0.0, min(busy, 100.0))
            self.disk_rates[name] = (r, w, busy)
            self.disk_hist.setdefault(name, deque([0.0] * HISTORY, maxlen=HISTORY)).append(busy)
            tot_r, tot_w = tot_r + r, tot_w + w
            max_busy = max(max_busy, busy)
        self._last_disk = disks
        self.hist["disk"].append(max_busy)
        self.hist["disk_r"].append(tot_r)
        self.hist["disk_w"].append(tot_w)

        # réseau
        nets = self._safe(lambda: psutil.net_io_counters(pernic=True)) or {}
        up = down = 0.0
        for name, c in nets.items():
            if name.lower().startswith(("lo", "loopback")):
                continue
            p = self._last_net.get(name)
            if not p:
                continue
            s = max(c.bytes_sent - p.bytes_sent, 0) / dt
            rcv = max(c.bytes_recv - p.bytes_recv, 0) / dt
            self.net_rates[name] = (s, rcv)
            self.net_hist.setdefault(name, (deque([0.0] * HISTORY, maxlen=HISTORY),
                                            deque([0.0] * HISTORY, maxlen=HISTORY)))
            self.net_hist[name][0].append(s)
            self.net_hist[name][1].append(rcv)
            up, down = up + s, down + rcv
        self._last_net = nets
        self.hist["net_up"].append(up)
        self.hist["net_down"].append(down)

        self._n += 1
        if self._n % 2 == 0:
            self._proc_task.start(self._prev_io, self.ncpu)
        self.updated.emit()

    def _procs_done(self, res):
        self.procs, self._prev_io = res
        self.procs_updated.emit()

    # raccourcis
    @property
    def net_up(self):
        return self.hist["net_up"][-1]

    @property
    def net_down(self):
        return self.hist["net_down"][-1]

    @property
    def uptime(self):
        return time.time() - self.boot
