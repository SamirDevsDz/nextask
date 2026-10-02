"""Connections : connexions TCP/UDP par processus, DNS inverse, réputation IP, blocage pare-feu."""
import ipaddress
import socket
import webbrowser
from concurrent.futures import ThreadPoolExecutor

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QComboBox, QCheckBox

from core.common import IS_WIN, BackgroundTask, run_cmd, confirm, info, is_admin
from core.widgets import Page, TablePanel

STATE_FR = {"ESTABLISHED": "Établie", "LISTEN": "Écoute", "TIME_WAIT": "TIME_WAIT",
            "CLOSE_WAIT": "CLOSE_WAIT", "SYN_SENT": "SYN envoyé", "NONE": "—"}


def _is_external(ip):
    try:
        a = ipaddress.ip_address(ip)
        return not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_unspecified)
    except ValueError:
        return False


def _collect():
    names = {}
    for p in psutil.process_iter(["name", "exe"], ad_value=""):
        names[p.pid] = (p.info["name"], p.info["exe"])
    rows = []
    for c in psutil.net_connections(kind="inet"):
        proto = ("TCP" if c.type == socket.SOCK_STREAM else "UDP") + ("6" if c.family == socket.AF_INET6 else "")
        n, exe = names.get(c.pid, ("?", ""))
        rows.append({
            "name": n or ("Système" if c.pid in (0, 4) else "?"), "pid": c.pid or 0, "proto": proto,
            "lip": c.laddr.ip if c.laddr else "", "lport": c.laddr.port if c.laddr else 0,
            "rip": c.raddr.ip if c.raddr else "", "rport": c.raddr.port if c.raddr else 0,
            "state": STATE_FR.get(c.status, c.status), "exe": exe,
        })
    return rows


def _resolve(ips):
    def one(ip):
        try:
            return ip, socket.gethostbyaddr(ip)[0]
        except (OSError, UnicodeError):
            return ip, "—"
    with ThreadPoolExecutor(16) as ex:
        return dict(ex.map(one, ips))


class ConnectionsPage(Page):
    title = "Connections"
    subtitle = "Qui parle à qui sur le réseau"

    COLS = ["Processus", "PID", "Proto", "Adresse locale", "Port local", "Adresse distante",
            "Port distant", "État", "Hôte distant", "Chemin"]

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        self.table = TablePanel(self.COLS, key_col=0, right_cols=(1, 4, 6))
        self.table.set_widths([170, 70, 60, 130, 80, 150, 90, 100, 240, 300])
        self.filter = QComboBox()
        self.filter.addItems(["Toutes", "Établies", "En écoute", "Externes uniquement"])
        self.filter.currentTextChanged.connect(lambda _: self._apply())
        self.table.toolbar.insertWidget(1, self.filter)
        self.dns = QCheckBox("DNS inverse")
        self.dns.setChecked(True)
        self.table.toolbar.insertWidget(2, self.dns)
        t = self.table
        t.add_button("Fin du processus", self._kill, needs_selection=True, danger=True)
        t.add_context("Copier l'adresse distante", lambda r: QGuiApplication.clipboard().setText(r[5]))
        t.add_context("Réputation IP (AbuseIPDB)", lambda r: r[5] and webbrowser.open(f"https://www.abuseipdb.com/check/{r[5]}"))
        t.add_context("Infos IP (ipinfo.io)", lambda r: r[5] and webbrowser.open(f"https://ipinfo.io/{r[5]}"))
        t.add_context("VirusTotal", lambda r: r[5] and webbrowser.open(f"https://www.virustotal.com/gui/ip-address/{r[5]}"))
        t.add_context("-", None)
        if IS_WIN:
            t.add_context("Bloquer cette IP (pare-feu Windows)…", self._block)
        t.add_context("Fin du processus", self._kill)
        self.root.addWidget(self.table, 1)
        self.rows = []
        self.cache = {}
        self.task = BackgroundTask(_collect, self._show, lambda tb: self.table.status.setText(
            "Accès refusé : relancez en administrateur pour voir toutes les connexions."))
        self.dns_task = BackgroundTask(_resolve, self._resolved)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.isVisible() and self.task.start())
        self.timer.start(3000)

    def on_show(self):
        self.task.start()

    def _show(self, rows):
        self.rows = rows
        self._apply()
        if self.dns.isChecked():
            todo = list({r["rip"] for r in rows if r["rip"] and r["rip"] not in self.cache
                         and _is_external(r["rip"])})[:40]
            if todo:
                self.dns_task.start(todo)

    def _resolved(self, res):
        self.cache.update(res)
        self._apply()

    def _apply(self):
        f = self.filter.currentText()
        out = []
        n_est = n_ext = 0
        for r in self.rows:
            ext = _is_external(r["rip"])
            n_est += r["state"] == "Établie"
            n_ext += ext
            if f == "Établies" and r["state"] != "Établie":
                continue
            if f == "En écoute" and r["state"] != "Écoute":
                continue
            if f == "Externes uniquement" and not ext:
                continue
            host = self.cache.get(r["rip"], "") if ext else ("local" if r["rip"] else "")
            out.append([r["name"], r["pid"], r["proto"], r["lip"], r["lport"], r["rip"],
                        r["rport"] or "", r["state"], host, r["exe"]])
        self.table.set_rows(out)
        self.table.status.setText(f"{len(out)} affichée(s) • {len(self.rows)} au total • "
                                  f"{n_est} établies • {n_ext} vers Internet")

    def _kill(self, row):
        if not confirm(self, "Fin du processus", f"Terminer « {row[0]} » (PID {row[1]}) ?"):
            return
        try:
            psutil.Process(int(row[1])).kill()
        except psutil.Error as e:
            info(self, "Erreur", str(e))

    def _block(self, row):
        ip = row[5]
        if not ip:
            return
        if not is_admin():
            info(self, "Droits requis", "Relancez NexTask en administrateur pour créer une règle de pare-feu.")
            return
        if confirm(self, "Bloquer l'IP", f"Créer une règle de pare-feu Windows bloquant tout trafic sortant "
                                         f"et entrant vers {ip} ?\n(Règle nommée « NexTask block {ip} », "
                                         "supprimable dans wf.msc.)"):
            out = run_cmd(["netsh", "advfirewall", "firewall", "add", "rule", f"name=NexTask block {ip}",
                           "dir=out", "action=block", f"remoteip={ip}"])
            out += run_cmd(["netsh", "advfirewall", "firewall", "add", "rule", f"name=NexTask block {ip}",
                            "dir=in", "action=block", f"remoteip={ip}"])
            info(self, "Pare-feu", out.strip() or "Règles créées.")
