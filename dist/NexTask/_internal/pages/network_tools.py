"""Network Tools : ping, traceroute, DNS, test de ports, IP publique, infos réseau."""
import re
import socket
import time
import urllib.request

from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QPushButton, QPlainTextEdit, QComboBox, QLabel,
                               QTabWidget, QWidget, QVBoxLayout)

from core.common import IS_WIN, BackgroundTask, run_cmd, ps_json, as_list, ps_quote
from core.widgets import Page

HOST_RE = re.compile(r"^[A-Za-z0-9.\-:_%]{1,253}$")


def _ping(host):
    return run_cmd(["ping", "-n" if IS_WIN else "-c", "4", host], 30)


def _trace(host):
    if IS_WIN:
        return run_cmd(["tracert", "-d", "-h", "25", "-w", "800", host], 120)
    return run_cmd(["traceroute", "-n", "-m", "25", host], 120)


def _dns(host):
    lines = []
    try:
        infos = socket.getaddrinfo(host, None)
        addrs = sorted({i[4][0] for i in infos})
        lines.append(f"Résolution système : {', '.join(addrs)}")
    except socket.gaierror as e:
        lines.append(f"Résolution système : échec ({e})")
    try:
        lines.append(f"DNS inverse : {socket.gethostbyaddr(host)[0]}")
    except (OSError, UnicodeError):
        pass
    if IS_WIN:
        for t in ("A", "AAAA", "CNAME", "MX", "NS", "TXT"):
            data = ps_json(f"Resolve-DnsName -Name {ps_quote(host)} -Type {t} -DnsOnly -EA SilentlyContinue | "
                           "Select-Object Name,Type,TTL,IPAddress,NameHost,NameExchange,Preference,Strings | ConvertTo-Json -Compress", 20)
            for r in as_list(data):
                val = r.get("IPAddress") or r.get("NameHost") or r.get("NameExchange") or " ".join(as_list(r.get("Strings")))
                if val:
                    pref = f" (priorité {r['Preference']})" if r.get("Preference") else ""
                    lines.append(f"{t:<6} {r.get('Name', '')}  →  {val}{pref}  TTL {r.get('TTL', '')}")
        srv = run_cmd(["nslookup", host], 15)
        lines += ["", "--- nslookup (serveur DNS utilisé) ---", srv.strip()]
    else:
        lines += ["", run_cmd(["sh", "-c", f"command -v dig >/dev/null && dig +short ANY {host} || getent hosts {host}"], 15)]
    return "\n".join(lines)


def _ports(host, ports):
    out = []
    for p in ports:
        t0 = time.time()
        try:
            with socket.create_connection((host, p), timeout=3):
                out.append(f"Port {p:<6} OUVERT   ({(time.time() - t0) * 1000:.0f} ms)")
        except socket.timeout:
            out.append(f"Port {p:<6} filtré / délai dépassé")
        except OSError as e:
            out.append(f"Port {p:<6} FERMÉ    ({e.strerror or e})")
    return f"Test TCP vers {host}\n" + "\n".join(out)


def _public_ip():
    out = []
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                out.append(f"{url} → {r.read().decode().strip()}")
                break
        except OSError as e:
            out.append(f"{url} → échec ({e})")
    return "\n".join(out)


INFO_CMDS = {
    "Configuration IP complète": (["ipconfig", "/all"], ["ip", "addr"]),
    "Table de routage": (["route", "print"], ["ip", "route"]),
    "Table ARP (voisins)": (["arp", "-a"], ["ip", "neigh"]),
    "Wi-Fi : interface et signal": (["netsh", "wlan", "show", "interfaces"], ["sh", "-c", "iwconfig 2>&1 || nmcli dev wifi"]),
    "Wi-Fi : profils enregistrés": (["netsh", "wlan", "show", "profiles"], ["nmcli", "con", "show"]),
    "Serveurs DNS & suffixes": (["powershell", "-NoProfile", "-Command", "Get-DnsClientServerAddress | Format-Table -AutoSize | Out-String -Width 200"],
                                ["cat", "/etc/resolv.conf"]),
    "Cache DNS": (["ipconfig", "/displaydns"], ["sh", "-c", "resolvectl statistics 2>&1"]),
    "Fichier hosts": (None, ["cat", "/etc/hosts"]),
    "Proxy WinHTTP": (["netsh", "winhttp", "show", "proxy"], ["sh", "-c", "env | grep -i proxy"]),
    "Ports en écoute (netstat)": (["netstat", "-ano", "-p", "TCP"], ["ss", "-tlnp"]),
}


def _info(label):
    win, lin = INFO_CMDS[label]
    if label == "Fichier hosts" and IS_WIN:
        import os
        path = os.path.expandvars(r"%SystemRoot%\System32\drivers\etc\hosts")
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f"# {path}\n" + f.read()
        except OSError as e:
            return str(e)
    return run_cmd(win if IS_WIN else lin, 60)


class NetworkToolsPage(Page):
    title = "Network Tools"
    subtitle = "Diagnostic réseau"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        tabs = QTabWidget()
        self.root.addWidget(tabs, 1)

        # --- diagnostic
        diag = QWidget()
        v = QVBoxLayout(diag)
        v.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        self.host = QLineEdit("8.8.8.8")
        self.host.setPlaceholderText("Hôte ou IP (ex. google.com, 10.0.0.1)")
        self.host.setMaximumWidth(320)
        row.addWidget(QLabel("Cible :"))
        row.addWidget(self.host)
        self.ports = QLineEdit("80,443,3389,445,22")
        self.ports.setMaximumWidth(220)
        self.ports.setPlaceholderText("Ports (ex. 80,443,8000-8010)")
        row.addWidget(QLabel("Ports :"))
        row.addWidget(self.ports)
        row.addStretch()
        v.addLayout(row)
        btns = QHBoxLayout()
        for label, fn in (("Ping", self._do_ping), ("Traceroute", self._do_trace), ("DNS", self._do_dns),
                          ("Tester les ports", self._do_ports), ("IP publique", self._do_pub)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch()
        self.state = QLabel("", objectName="muted")
        btns.addWidget(self.state)
        v.addLayout(btns)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace;")
        v.addWidget(self.out, 1)
        tabs.addTab(diag, "Diagnostic")

        # --- infos
        inf = QWidget()
        v2 = QVBoxLayout(inf)
        v2.setContentsMargins(0, 8, 0, 0)
        r2 = QHBoxLayout()
        self.info_sel = QComboBox()
        self.info_sel.addItems(list(INFO_CMDS))
        r2.addWidget(self.info_sel)
        b = QPushButton("Afficher")
        b.setObjectName("primary")
        b.clicked.connect(self._do_info)
        r2.addWidget(b)
        r2.addStretch()
        v2.addLayout(r2)
        self.info_out = QPlainTextEdit()
        self.info_out.setReadOnly(True)
        self.info_out.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace;")
        v2.addWidget(self.info_out, 1)
        tabs.addTab(inf, "Informations réseau")

        self.task = BackgroundTask(lambda fn, *a: fn(*a), self._done)
        self.info_task = BackgroundTask(_info, self.info_out.setPlainText)

    def _target(self):
        h = self.host.text().strip()
        if not HOST_RE.match(h):
            self.state.setText("Cible invalide.")
            return None
        return h

    def _run(self, label, fn, *args):
        if self.task.start(fn, *args):
            self.state.setText(f"{label} en cours…")
            self.out.appendPlainText(f"\n===== {label} — {time.strftime('%H:%M:%S')} =====")

    def _done(self, text):
        self.state.setText("Terminé")
        self.out.appendPlainText(text.strip())

    def _do_ping(self):
        if (h := self._target()):
            self._run(f"Ping {h}", _ping, h)

    def _do_trace(self):
        if (h := self._target()):
            self._run(f"Traceroute {h}", _trace, h)

    def _do_dns(self):
        if (h := self._target()):
            self._run(f"DNS {h}", _dns, h)

    def _do_ports(self):
        h = self._target()
        if not h:
            return
        ports = []
        for part in self.ports.text().replace(" ", "").split(","):
            if re.fullmatch(r"\d+-\d+", part):
                a, b = map(int, part.split("-"))
                ports += list(range(a, min(b, a + 200) + 1))
            elif part.isdigit():
                ports.append(int(part))
        ports = [p for p in ports if 0 < p < 65536][:200]
        if ports:
            self._run(f"Ports {h}", _ports, h, ports)

    def _do_pub(self):
        self._run("IP publique", _public_ip)

    def _do_info(self):
        self.info_out.setPlainText("Chargement…")
        self.info_task.start(self.info_sel.currentText())
