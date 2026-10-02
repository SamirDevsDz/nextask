"""Report : rapport de diagnostic en un clic (HTML / PDF / résumé texte pour ticket GLPI)."""
import html
import os
import platform
import socket
import time
from datetime import datetime

import psutil
from PySide6.QtGui import QGuiApplication, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QGridLayout, QCheckBox, QLineEdit, QPlainTextEdit, QLabel,
                               QPushButton, QTextBrowser, QFileDialog, QSplitter, QWidget, QFrame)

from core import audit
from core import security_checks as sc
from core.common import IS_WIN, BackgroundTask, fmt_bytes, fmt_duration, fmt_ts, ps_json, as_list, run_cmd
from core.widgets import Page
from pages.sysinfo import cpu_name

SECTIONS = [
    ("system", "Système et ressources", True),
    ("health", "Alertes santé + Flight Recorder (24 h)", True),
    ("posture", "Bilan de sécurité", True),
    ("procs", "Processus suspects", True),
    ("remote", "Outils d'accès à distance", True),
    ("events", "Événements de sécurité (24 h)", True),
    ("drivers", "Périphériques en erreur", True),
    ("network", "Réseau (IP, passerelle, DNS, connectivité)", True),
    ("apps", "Liste des logiciels installés", False),
    ("baseline", "Changements depuis la dernière référence", False),
]
COL = {"OK": "#16a34a", "INFO": "#2563eb", "ALERTE": "#d97706", "CRITIQUE": "#dc2626"}
e = html.escape


def _table(headers, rows):
    h = "".join(f"<th>{e(str(x))}</th>" for x in headers)
    body = ""
    for r in rows:
        cells = []
        for c in r:
            if isinstance(c, tuple):   # (texte, niveau)
                cells.append(f"<td style='color:{COL.get(c[1], '#000')};font-weight:bold'>{e(str(c[0]))}</td>")
            else:
                cells.append(f"<td>{e(str(c if c is not None else ''))}</td>")
        body += "<tr>" + "".join(cells) + "</tr>"
    return f"<table border='1' cellspacing='0' cellpadding='4' width='100%'><tr style='background:#e5e7eb'>{h}</tr>{body}</table>"


def build(opts, ctx):
    """opts : sections cochées ; ctx : instantané pris dans le thread UI (procs, métriques, recorder db path…)."""
    parts, summary = [], []
    host = socket.gethostname()
    now = datetime.now()

    def section(title, content):
        parts.append(f"<h2 style='color:#1e3a8a;border-bottom:2px solid #1e3a8a'>{e(title)}</h2>{content}")

    if "system" in opts:
        vm = psutil.virtual_memory()
        osname = f"{platform.system()} {platform.release()} ({platform.version()})"
        if IS_WIN:
            o = ps_json("Get-CimInstance Win32_OperatingSystem | Select-Object Caption,BuildNumber | ConvertTo-Json -Compress") or {}
            m = ps_json("Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model | ConvertTo-Json -Compress") or {}
            b = ps_json("Get-CimInstance Win32_BIOS | Select-Object SerialNumber | ConvertTo-Json -Compress") or {}
            osname = f"{o.get('Caption', osname)} (build {o.get('BuildNumber', '')})"
            model = f"{m.get('Manufacturer', '')} {m.get('Model', '')} — N° série {b.get('SerialNumber', '')}"
        else:
            model = "—"
        up = time.time() - psutil.boot_time()
        info_rows = [("Poste", host), ("Modèle", model), ("Système", osname), ("Processeur", cpu_name()),
                     ("Mémoire", f"{fmt_bytes(vm.used)} / {fmt_bytes(vm.total)} ({vm.percent:.0f} %)"),
                     ("CPU (moyenne 10 s)", f"{ctx['cpu']:.0f} %"), ("Démarré le", f"{fmt_ts(psutil.boot_time())} ({fmt_duration(up)})"),
                     ("Utilisateur", ctx["user"])]
        content = _table(["Élément", "Valeur"], info_rows)
        procs = [p for p in ctx["procs"] if p["pid"] != 0]
        content += "<h3>Top 10 CPU</h3>" + _table(["Processus", "PID", "CPU %", "Mémoire"], [
            [p["name"], p["pid"], f"{p['cpu']:.1f}", fmt_bytes(p["mem"])] for p in sorted(procs, key=lambda p: -p["cpu"])[:10]])
        content += "<h3>Top 10 mémoire</h3>" + _table(["Processus", "PID", "Mémoire", "CPU %"], [
            [p["name"], p["pid"], fmt_bytes(p["mem"]), f"{p['cpu']:.1f}"] for p in sorted(procs, key=lambda p: -p["mem"])[:10]])
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            lvl = "CRITIQUE" if u.percent >= 90 else "ALERTE" if u.percent >= 80 else "OK"
            disks.append([part.mountpoint, part.fstype, fmt_bytes(u.total), fmt_bytes(u.free), (f"{u.percent:.0f} %", lvl)])
        content += "<h3>Disques</h3>" + _table(["Volume", "FS", "Taille", "Libre", "Utilisé"], disks)
        section("Système et ressources", content)
        summary.append(f"Poste {host} — {osname} — RAM {vm.percent:.0f} % — démarré depuis {fmt_duration(up)}")

    if "health" in opts:
        al = []
        vm = psutil.virtual_memory()
        if vm.percent > 85:
            al.append(("ALERTE", f"Mémoire élevée ({vm.percent:.0f} %)"))
        up_days = (time.time() - psutil.boot_time()) / 86400
        if up_days > 14:
            al.append(("ALERTE", f"Pas redémarré depuis {up_days:.0f} jours — redémarrage conseillé"))
        for part in psutil.disk_partitions(all=False):
            try:
                if psutil.disk_usage(part.mountpoint).percent >= 90:
                    al.append(("CRITIQUE", f"{part.mountpoint} presque plein"))
            except OSError:
                pass
        for ts, kind, detail in ctx["fr_events"]:
            al.append(("ALERTE", f"{fmt_ts(ts)} — {kind} : {detail}"))
        section("Alertes santé", _table(["Niveau", "Constat"], [[(lvl, lvl), m] for lvl, m in al])
                if al else "<p style='color:#16a34a'>Aucune alerte.</p>")
        summary += [f"[{lvl}] {m}" for lvl, m in al[:6]]

    if "posture" in opts:
        checks = sc.posture()
        score = sc.posture_score(checks)
        bad = [c for c in checks if c["status"] in ("CRITIQUE", "ALERTE")]
        section(f"Bilan de sécurité — score {score}/100" if score is not None else "Bilan de sécurité",
                _table(["Gravité", "Catégorie", "Contrôle", "Valeur", "Recommandation"],
                       [[(c["status"], c["status"]), c["cat"], c["check"], c["value"], c["advice"]]
                        for c in sorted(checks, key=lambda c: -sc.RANK[c["status"]])]))
        if score is not None:
            summary.append(f"Score sécurité : {score}/100 ({len(bad)} point(s) à corriger)")
        summary += [f"[{c['status']}] {c['check']} : {c['value']}" for c in bad if c["status"] == "CRITIQUE"][:6]

    if "procs" in opts:
        rows = [r for r in sc.suspicious_processes(ctx["procs"]) if r["score"] > 0]
        rows.sort(key=lambda r: -r["score"])
        section("Processus suspects", _table(["Risque", "Processus", "PID", "Signature", "Raisons", "SHA-256", "Chemin"],
                                             [[(r["level"], r["level"]), r["name"], r["pid"], r["sig"], r["why"], r.get("sha256", ""), r["exe"]]
                                              for r in rows[:40]]) if rows else "<p>Aucun processus à risque.</p>")
        crit = [r for r in rows if r["level"] == "CRITIQUE"]
        if crit:
            summary.append(f"{len(crit)} processus critique(s) : " + ", ".join(r["name"] for r in crit[:5]))

    if "remote" in opts:
        rows = sc.remote_access()
        section("Outils d'accès à distance", _table(["Statut", "Outil", "Détection", "Détail", "IP distantes"],
                                                    [[(r["status"], r["status"]), r["tool"], r["how"], r["detail"], r["conns"]] for r in rows])
                if rows else "<p>Aucun outil détecté.</p>")
        tools = sorted({r["tool"] for r in rows if r["status"] == "ALERTE"})
        if tools:
            summary.append("Accès distant actif : " + ", ".join(tools))

    if "events" in opts:
        events, alerts, notes = sc.security_events(24)
        content = _table(["Niveau", "Constat"], [[(s, s), m] for s, m in alerts]) if alerts else "<p style='color:#16a34a'>Rien d'anormal.</p>"
        if notes:
            content += "<p style='color:gray'>" + "<br>".join(e(n) for n in notes) + "</p>"
        important = [x for x in events if x["sev"] in ("ALERTE", "CRITIQUE")][:40]
        if important:
            content += "<h3>Événements notables</h3>" + _table(["Date", "ID", "Événement", "Utilisateur", "Source", "Détail"],
                                                               [[x["t"], x["id"], x["label"], x["user"], x["src"], x["detail"][:150]] for x in important])
        section("Événements de sécurité (24 h)", content)
        summary += [f"[{s}] {m}" for s, m in alerts if s == "CRITIQUE"][:5]

    if "drivers" in opts:
        from pages.drivers import _collect as drv
        errs = drv()["errors"]
        section("Périphériques en erreur", _table(["Périphérique", "Classe", "Code", "Statut", "ID matériel"], errs)
                if errs else "<p style='color:#16a34a'>Aucun périphérique en erreur.</p>")
        if errs:
            summary.append(f"{len(errs)} périphérique(s) en erreur : " + ", ".join(str(x[0]) for x in errs[:3]))

    if "network" in opts:
        rows = []
        stats = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            st = stats.get(name)
            if not st or not st.isup or name.lower().startswith(("lo", "loopback")):
                continue
            ip4 = ", ".join(a.address for a in addrs if getattr(a.family, "name", "") == "AF_INET")
            mac = next((a.address for a in addrs if getattr(a.family, "name", "") in ("AF_LINK", "AF_PACKET")), "")
            rows.append([name, ip4, mac, f"{st.speed} Mb/s" if st.speed else ""])
        content = _table(["Interface", "IPv4", "MAC", "Vitesse"], rows)
        tests = []
        if IS_WIN:
            gw = ps_json("Get-NetRoute -DestinationPrefix '0.0.0.0/0' -EA SilentlyContinue | Sort-Object RouteMetric | "
                         "Select-Object -First 1 NextHop,InterfaceAlias | ConvertTo-Json -Compress") or {}
            dns = as_list(ps_json("Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object ServerAddresses | "
                                  "Select-Object InterfaceAlias,ServerAddresses | ConvertTo-Json -Compress"))
            tests.append(["Passerelle par défaut", f"{gw.get('NextHop', '?')} ({gw.get('InterfaceAlias', '')})"])
            tests += [[f"DNS ({d.get('InterfaceAlias')})", ", ".join(as_list(d.get("ServerAddresses")))] for d in dns]
            if gw.get("NextHop"):
                ok = "TTL=" in run_cmd(["ping", "-n", "2", "-w", "1000", gw["NextHop"]], 10).upper()
                tests.append(["Ping passerelle", ("OK", "OK") if ok else ("ÉCHEC", "CRITIQUE")])
        ok = "TTL=" in run_cmd(["ping", "-n" if IS_WIN else "-c", "2", "8.8.8.8"], 15).upper()
        tests.append(["Ping Internet (8.8.8.8)", ("OK", "OK") if ok else ("ÉCHEC", "CRITIQUE")])
        try:
            socket.getaddrinfo("www.microsoft.com", 443)
            tests.append(["Résolution DNS (microsoft.com)", ("OK", "OK")])
        except socket.gaierror:
            tests.append(["Résolution DNS (microsoft.com)", ("ÉCHEC", "CRITIQUE")])
            summary.append("[CRITIQUE] Résolution DNS en échec")
        if not ok:
            summary.append("[CRITIQUE] Pas d'accès Internet (ping 8.8.8.8)")
        section("Réseau", content + "<h3>Tests de connectivité</h3>" + _table(["Test", "Résultat"], tests))

    if "apps" in opts:
        from pages.installed_apps import _collect as apps
        a = sorted(apps(False), key=lambda x: x["name"].lower())
        section(f"Logiciels installés ({len(a)})", _table(["Nom", "Version", "Éditeur", "Installé le"],
                                                          [[x["name"], x["ver"], x["pub"], x["date"]] for x in a]))

    if "baseline" in opts:
        from pages.baseline import Store, take_snapshot, diff, CATEGORIES
        st = Store()
        lst = st.list()
        if lst:
            rows = diff(st.get(lst[0][0]), take_snapshot())
            section(f"Changements depuis la référence #{lst[0][0]} « {lst[0][2]} » du {fmt_ts(lst[0][1])}",
                    _table(["Catégorie", "Élément", "Changement", "Avant", "Après"],
                           [[CATEGORIES.get(c, c), k, ch, a, b] for c, k, ch, a, b in rows[:300]]) if rows else "<p>Aucun changement.</p>")
            if rows:
                summary.append(f"{len(rows)} changement(s) depuis la référence « {lst[0][2]} »")
        else:
            section("Changements depuis la référence", "<p>Aucune référence enregistrée (module Baseline).</p>")

    head = (f"<h1 style='color:#111827'>Rapport de diagnostic — {e(host)}</h1>"
            f"<p><b>Date :</b> {now:%Y-%m-%d %H:%M} &nbsp; <b>Ticket :</b> {e(ctx['ticket'] or '—')} &nbsp; "
            f"<b>Technicien :</b> {e(ctx['tech'] or '—')}</p>")
    if ctx["notes"]:
        head += f"<p><b>Contexte :</b> {e(ctx['notes'])}</p>"
    head += "<h2 style='color:#1e3a8a'>Synthèse</h2><ul>" + "".join(f"<li>{e(s)}</li>" for s in summary) + "</ul>"
    doc = (f"<html><head><meta charset='utf-8'><title>Diagnostic {e(host)}</title>"
           "<style>body{font-family:'Segoe UI',Arial,sans-serif;font-size:10pt;color:#111}"
           "th{text-align:left}td{vertical-align:top}</style></head><body>"
           + head + "".join(parts) + f"<p style='color:gray'>Généré par NexTask le {now:%Y-%m-%d %H:%M}</p></body></html>")
    text = (f"Diagnostic {host} — {now:%Y-%m-%d %H:%M}\nTicket : {ctx['ticket'] or '—'}  Technicien : {ctx['tech'] or '—'}\n"
            + (f"Contexte : {ctx['notes']}\n" if ctx["notes"] else "") + "\n".join(f"- {s}" for s in summary)
            + "\n(Rapport complet en pièce jointe.)")
    return doc, text


class ReportPage(Page):
    title = "Report"
    subtitle = "Rapport de diagnostic à joindre à un ticket"

    def __init__(self, sampler, recorder=None, parent=None):
        super().__init__(sampler, parent)
        self.recorder = recorder
        split = QSplitter()
        left = QFrame(objectName="card")
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("Informations", objectName="section"))
        g = QGridLayout()
        self.ticket = QLineEdit()
        self.ticket.setPlaceholderText("ex. GLPI #1234")
        self.tech = QLineEdit(os.environ.get("USERNAME") or os.environ.get("USER") or "")
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Symptômes signalés par l'utilisateur…")
        self.notes.setMaximumHeight(90)
        g.addWidget(QLabel("Ticket"), 0, 0)
        g.addWidget(self.ticket, 0, 1)
        g.addWidget(QLabel("Technicien"), 1, 0)
        g.addWidget(self.tech, 1, 1)
        lv.addLayout(g)
        lv.addWidget(self.notes)
        lv.addWidget(QLabel("Sections", objectName="section"))
        self.checks = {}
        for key, label, default in SECTIONS:
            cb = QCheckBox(label)
            cb.setChecked(default)
            self.checks[key] = cb
            lv.addWidget(cb)
        self.go = QPushButton("Générer le rapport")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.generate)
        lv.addWidget(self.go)
        self.state = QLabel("Durée : 30 s à 2 min selon les sections (admin conseillé).", objectName="muted")
        self.state.setWordWrap(True)
        lv.addWidget(self.state)
        lv.addStretch()
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        hb = QHBoxLayout()
        self.b_html = QPushButton("Enregistrer en HTML")
        self.b_pdf = QPushButton("Enregistrer en PDF")
        self.b_txt = QPushButton("Copier la synthèse (pour le ticket)")
        for b, fn in ((self.b_html, self.save_html), (self.b_pdf, self.save_pdf), (self.b_txt, self.copy_text)):
            b.setEnabled(False)
            b.clicked.connect(fn)
            hb.addWidget(b)
        hb.addStretch()
        rv.addLayout(hb)
        self.view = QTextBrowser()
        self.view.setStyleSheet("background: white; color: black;")
        rv.addWidget(self.view, 1)
        split.addWidget(right)
        split.setSizes([330, 900])
        self.root.addWidget(split, 1)
        self.task = BackgroundTask(build, self._done, lambda tb: self.state.setText("Erreur : " + tb.strip().splitlines()[-1]))
        self.html = self.text = ""

    def generate(self):
        opts = {k for k, cb in self.checks.items() if cb.isChecked()}
        fr = []
        if self.recorder is not None:
            try:
                fr = self.recorder.events(time.time() - 86400)[:20]
            except Exception:  # noqa: BLE001
                fr = []
        ctx = {"procs": list(self.sampler.procs), "cpu": sum(list(self.sampler.hist["cpu"])[-10:]) / 10,
               "ticket": self.ticket.text().strip(), "tech": self.tech.text().strip(),
               "notes": self.notes.toPlainText().strip(), "fr_events": fr,
               "user": os.environ.get("USERNAME") or os.environ.get("USER") or ""}
        if self.task.start(opts, ctx):
            self._t0 = time.time()
            self.go.setEnabled(False)
            self.state.setText("Collecte en cours…")

    def _done(self, res):
        self.html, self.text = res
        self.view.setHtml(self.html)
        self.go.setEnabled(True)
        for b in (self.b_html, self.b_pdf, self.b_txt):
            b.setEnabled(True)
        self.state.setText(f"Rapport prêt en {time.time() - self._t0:.0f} s.")
        audit.log("Rapport de diagnostic généré", self.ticket.text().strip() or socket.gethostname())

    def _path(self, ext):
        base = os.path.join(os.path.expanduser("~"), "Documents")
        name = f"diag_{socket.gethostname()}_{datetime.now():%Y%m%d_%H%M}" + (f"_{self.ticket.text().strip()}" if self.ticket.text().strip() else "")
        name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer", os.path.join(base, f"{name}.{ext}"), f"*.{ext}")
        return path

    def save_html(self):
        path = self._path("html")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.html)
            self.state.setText(f"Enregistré : {path}")

    def save_pdf(self):
        path = self._path("pdf")
        if not path:
            return
        w = QPdfWriter(path)
        w.setPageSize(QPageSize(QPageSize.A4))
        w.setResolution(110)
        doc = QTextDocument()
        doc.setHtml(self.html)
        doc.setPageSize(w.pageLayout().paintRectPixels(w.resolution()).size().toSizeF())
        doc.print_(w)
        self.state.setText(f"Enregistré : {path}")

    def copy_text(self):
        QGuiApplication.clipboard().setText(self.text)
        self.state.setText("Synthèse copiée — collez-la dans le ticket GLPI et joignez le PDF.")
