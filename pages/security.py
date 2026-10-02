"""Security : bilan du poste, processus suspects, accès distant, persistance, événements."""
import webbrowser

import psutil
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QCheckBox, QComboBox)

from core import audit
from core import security_checks as sc
from core.common import IS_WIN, BackgroundTask, open_location, confirm, info, powershell, ps_quote
from core.widgets import Page, TablePanel, STATUS_COLORS


def _st(level):
    """Cellule colorée triable par gravité."""
    return (level, sc.RANK.get(level, 0), STATUS_COLORS.get(level))


class _Tab(QWidget):
    def __init__(self, button_label, hint=""):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 8, 0, 0)
        top = QHBoxLayout()
        self.run = QPushButton(button_label)
        self.run.setObjectName("primary")
        top.addWidget(self.run)
        self.state = QLabel(hint, objectName="muted")
        self.state.setWordWrap(True)
        top.addWidget(self.state, 1)
        self.top = top
        self.lay.addLayout(top)


class SecurityPage(Page):
    title = "Security"
    subtitle = "Bilan de sécurité et chasse aux menaces sur ce poste"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        self._build_posture()
        self._build_procs()
        self._build_remote()
        self._build_persist()
        self._build_events()
        self._loaded = False
        self.last = {}   # derniers résultats (réutilisés par le rapport)

    def on_show(self):
        if not self._loaded:
            self._loaded = True
            self.run_posture()

    # ============================================================ bilan
    def _build_posture(self):
        t = _Tab("Lancer le bilan", "Antivirus, pare-feu, BitLocker, UAC, SMBv1, RDP/NLA, LSA, mises à jour…")
        self.score = QLabel("—")
        self.score.setStyleSheet("font-size: 26px; font-weight: 700;")
        t.top.insertWidget(0, self.score)
        self.posture_tbl = TablePanel(["Gravité", "Catégorie", "Contrôle", "Valeur", "Recommandation"])
        self.posture_tbl.set_widths([90, 120, 260, 300, 400])
        t.lay.addWidget(self.posture_tbl, 1)
        t.run.clicked.connect(self.run_posture)
        self.tabs.addTab(t, "Bilan du poste")
        self.t_posture = t
        self.task_posture = BackgroundTask(sc.posture, self._posture_done)

    def run_posture(self):
        if self.task_posture.start():
            self.t_posture.state.setText("Analyse en cours (10-30 s)…")

    def _posture_done(self, checks):
        self.last["posture"] = checks
        score = sc.posture_score(checks)
        col = ("gray" if score is None else "#22c55e" if score >= 80 else "#f59e0b" if score >= 60 else "#ef4444")
        self.score.setText(f"{score}/100" if score is not None else "—")
        self.score.setStyleSheet(f"font-size: 26px; font-weight: 700; color: {col};")
        n_crit = sum(c["status"] == "CRITIQUE" for c in checks)
        n_warn = sum(c["status"] == "ALERTE" for c in checks)
        self.t_posture.state.setText(f"{len(checks)} contrôles • {n_crit} critique(s) • {n_warn} alerte(s)"
                                     + "  — certains contrôles exigent les droits admin.")
        self.posture_tbl.set_rows([[_st(c["status"]), c["cat"], c["check"], c["value"], c["advice"]] for c in checks])
        self.posture_tbl.sort_by(0)

    # ============================================================ processus
    def _build_procs(self):
        t = _Tab("Analyser les processus", "Signature numérique, emplacement, imitation de processus système, "
                                            "outils d'accès distant. SHA-256 calculé pour les éléments à risque.")
        self.only_susp = QCheckBox("Suspects uniquement")
        self.only_susp.setChecked(True)
        self.only_susp.toggled.connect(lambda _: self._procs_apply())
        t.top.addWidget(self.only_susp)
        tb = TablePanel(["Risque", "Score", "Processus", "PID", "Signature", "Éditeur", "Raisons", "SHA-256", "Chemin"],
                        key_col=3, right_cols=(1, 3))
        tb.set_widths([85, 55, 170, 65, 100, 180, 320, 200, 320])
        tb.add_button("VirusTotal (hash)", self._vt, needs_selection=True)
        tb.add_button("Fin de tâche", self._kill, needs_selection=True, danger=True)
        tb.add_context("Rechercher le hash sur VirusTotal", self._vt)
        tb.add_context("Copier le SHA-256", lambda r: QGuiApplication.clipboard().setText(r[7]))
        tb.add_context("Ouvrir l'emplacement", lambda r: open_location(r[8]))
        tb.add_context("Fin de tâche", self._kill)
        t.lay.addWidget(tb, 1)
        t.run.clicked.connect(self.run_procs)
        self.procs_tbl, self.t_procs = tb, t
        self.tabs.addTab(t, "Processus suspects")
        self.task_procs = BackgroundTask(sc.suspicious_processes, self._procs_done)
        self.proc_rows = []

    def run_procs(self):
        if self.task_procs.start(list(self.sampler.procs)):
            self.t_procs.state.setText("Vérification des signatures en cours (peut prendre 30 s)…")

    def _procs_done(self, rows):
        self.proc_rows = rows
        self.last["procs"] = rows
        n = sum(r["score"] > 0 for r in rows)
        self.t_procs.state.setText(f"{len(rows)} processus analysés • {n} à examiner • "
                                   f"{sum(r['level'] == 'CRITIQUE' for r in rows)} critique(s)")
        self._procs_apply()

    def _procs_apply(self):
        rows = [r for r in self.proc_rows if not self.only_susp.isChecked() or r["score"] > 0]
        self.procs_tbl.set_rows([[_st(r["level"]), r["score"], r["name"], r["pid"], r["sig"], r["signer"],
                                  r["why"], r.get("sha256", ""), r["exe"]] for r in rows])
        self.procs_tbl.sort_by(1)

    def _vt(self, row):
        if row[7] and len(row[7]) == 64:
            webbrowser.open(f"https://www.virustotal.com/gui/file/{row[7]}")
        else:
            info(self, "VirusTotal", "Pas d'empreinte calculée pour ce processus (score 0 ou fichier inaccessible).")

    def _kill(self, row):
        if not confirm(self, "Fin de tâche", f"Terminer « {row[2]} » (PID {row[3]}) ?"):
            return
        try:
            psutil.Process(int(row[3])).kill()
            audit.log("Fin de tâche (sécurité)", f"{row[2]} (PID {row[3]}) {row[7]}")
        except psutil.Error as e:
            audit.log("Fin de tâche (sécurité)", f"{row[2]} (PID {row[3]})", f"ÉCHEC : {e}")
            info(self, "Erreur", str(e))

    # ============================================================ accès distant
    def _build_remote(self):
        t = _Tab("Détecter", "AnyDesk, TeamViewer, RustDesk, ScreenConnect, Splashtop, VNC, Atera, MeshAgent… "
                             "+ état du RDP. « ALERTE » = actif avec connexions ou démarrage automatique.")
        tb = TablePanel(["Gravité", "Outil", "Détection", "Détail", "IP distantes"])
        tb.set_widths([85, 200, 200, 420, 260])
        t.lay.addWidget(tb, 1)
        t.run.clicked.connect(self.run_remote)
        self.remote_tbl, self.t_remote = tb, t
        self.tabs.addTab(t, "Accès à distance")
        self.task_remote = BackgroundTask(sc.remote_access, self._remote_done)

    def run_remote(self):
        if self.task_remote.start():
            self.t_remote.state.setText("Recherche en cours…")

    def _remote_done(self, rows):
        self.last["remote"] = rows
        tools = {r["tool"] for r in rows if not r["tool"].startswith("Bureau à distance")}
        self.t_remote.state.setText(f"{len(tools)} outil(s) détecté(s) : {', '.join(sorted(tools)) or 'aucun'}")
        self.remote_tbl.set_rows([[_st(r["status"]), r["tool"], r["how"], r["detail"], r["conns"]] for r in rows])
        self.remote_tbl.sort_by(0)

    # ============================================================ persistance
    def _build_persist(self):
        t = _Tab("Analyser la persistance", "Clés Run, dossiers Démarrage, tâches planifiées (hors Microsoft), "
                                             "abonnements WMI, services à chemin anormal, IFEO, Winlogon, AppInit_DLLs.")
        self.only_risk = QCheckBox("À risque uniquement")
        self.only_risk.toggled.connect(lambda _: self._persist_apply())
        t.top.addWidget(self.only_risk)
        tb = TablePanel(["Risque", "Score", "Type", "Nom", "Commande / cible", "Détail", "Raisons"], key_col=3,
                        right_cols=(1,))
        tb.set_widths([85, 55, 130, 220, 380, 280, 300])
        tb.add_context("Copier la commande", lambda r: QGuiApplication.clipboard().setText(r[4]))
        if IS_WIN:
            tb.add_button("Désactiver la tâche planifiée", self._disable_task, needs_selection=True, danger=True)
            tb.add_context("Désactiver la tâche planifiée", self._disable_task)
        t.lay.addWidget(tb, 1)
        t.run.clicked.connect(self.run_persist)
        self.persist_tbl, self.t_persist = tb, t
        self.tabs.addTab(t, "Persistance")
        self.task_persist = BackgroundTask(sc.persistence, self._persist_done)
        self.persist_rows = []

    def run_persist(self):
        if self.task_persist.start():
            self.t_persist.state.setText("Analyse en cours (20-60 s)…")

    def _persist_done(self, rows):
        self.persist_rows = rows
        self.last["persist"] = rows
        self.t_persist.state.setText(f"{len(rows)} entrées • {sum(r['score'] > 0 for r in rows)} à risque")
        self._persist_apply()

    def _persist_apply(self):
        rows = [r for r in self.persist_rows if not self.only_risk.isChecked() or r["score"] > 0]
        self.persist_tbl.set_rows([[_st(r["level"]), r["score"], r["kind"], r["name"], r["cmd"], r["detail"], r["why"]]
                                   for r in rows])
        self.persist_tbl.sort_by(1)

    def _disable_task(self, row):
        if row[2] != "Tâche planifiée":
            info(self, "Tâche planifiée", "Sélectionnez une ligne de type « Tâche planifiée ».")
            return
        full = row[3]
        path, name = full.rsplit("\\", 1) if "\\" in full else ("\\", full)
        if not confirm(self, "Désactiver", f"Désactiver la tâche planifiée « {full} » ?\n(Réversible dans taskschd.msc.)"):
            return
        out = powershell(f"Disable-ScheduledTask -TaskPath {ps_quote(path + chr(92))} -TaskName {ps_quote(name)} "
                         "-EA Stop | Out-Null; 'OK'", 30)
        audit.log("Tâche planifiée : désactivation", full, out.strip()[-200:])
        info(self, "Résultat", out.strip() or "OK")
        self.run_persist()

    # ============================================================ événements
    def _build_events(self):
        t = _Tab("Analyser les journaux", "Échecs de connexion (4625), RDP (4624 type 10), comptes créés (4720), "
                                           "ajouts aux groupes (4732), verrouillages (4740), journaux effacés (1102/104), "
                                           "nouveaux services (7045), Defender (1116/1117/5001). Admin requis.")
        self.period = QComboBox()
        self.period.addItems(["24 h", "72 h", "7 jours"])
        t.top.insertWidget(1, self.period)
        self.alerts_lbl = QLabel("")
        self.alerts_lbl.setWordWrap(True)
        t.lay.addWidget(self.alerts_lbl)
        tb = TablePanel(["Gravité", "Date", "Journal", "ID", "Événement", "Utilisateur", "Source / IP", "Détail"],
                        right_cols=(3,))
        tb.set_widths([85, 150, 90, 55, 210, 200, 140, 400])
        tb.add_context("Infos IP (AbuseIPDB)", lambda r: r[6] and r[6] not in ("-", "::1", "127.0.0.1")
                       and webbrowser.open(f"https://www.abuseipdb.com/check/{r[6]}"))
        t.lay.addWidget(tb, 1)
        t.run.clicked.connect(self.run_events)
        self.events_tbl, self.t_events = tb, t
        self.tabs.addTab(t, "Événements de sécurité")
        self.task_events = BackgroundTask(sc.security_events, self._events_done)

    def run_events(self):
        hours = {"24 h": 24, "72 h": 72, "7 jours": 168}[self.period.currentText()]
        if self.task_events.start(hours):
            self.t_events.state.setText("Lecture des journaux (peut prendre 1 min)…")

    def _events_done(self, res):
        events, alerts, notes = res
        self.last["events"] = res
        col = {"CRITIQUE": "#ef4444", "ALERTE": "#f59e0b", "INFO": "#60a5fa"}
        html = "<br>".join(f"<span style='color:{col.get(s, '')}'>● {m}</span>" for s, m in alerts[:12])
        if notes:
            html += "<br><span style='color:gray'>" + "<br>".join(notes) + "</span>"
        self.alerts_lbl.setText(html or "<span style='color:#22c55e'>● Rien d'anormal sur la période</span>")
        self.t_events.state.setText(f"{len(events)} événement(s)")
        self.events_tbl.set_rows([[_st(e["sev"]), (e["t"], e["t"]), e["log"], e["id"], e["label"], e["user"], e["src"],
                                   e["detail"]] for e in events])
        self.events_tbl.sort_by(1)
        crit = [m for s, m in alerts if s == "CRITIQUE"]
        if crit:
            audit.syslog(f'security_alerts="{len(crit)}" first="{crit[0][:200]}"', "warning")

