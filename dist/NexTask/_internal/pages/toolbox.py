"""Toolbox : réparations courantes en un clic, Windows Update, journal d'audit."""
import glob
import os
import shutil
import time

import psutil
from PySide6.QtWidgets import (QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                               QLabel, QPushButton, QPlainTextEdit, QSplitter)

from core import audit
from core.common import IS_WIN, BackgroundTask, run_cmd, powershell, ps_json, as_list, confirm, is_admin, fmt_ts, fmt_bytes
from core.widgets import Page, TablePanel, STATUS_COLORS


# ===================================================================== actions
def _running(names):
    names = {n.lower() for n in names}
    return sorted({p.info["name"] for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() in names})


def _purge(patterns):
    """Supprime le contenu des dossiers donnés (fichiers verrouillés ignorés)."""
    freed, errors, n = 0, 0, 0
    for pat in patterns:
        for d in glob.glob(os.path.expandvars(pat)):
            if not os.path.isdir(d):
                continue
            for entry in os.scandir(d):
                try:
                    if entry.is_dir(follow_symlinks=False):
                        size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(entry.path) for f in fs
                                   if os.path.exists(os.path.join(dp, f)))
                        shutil.rmtree(entry.path)
                    else:
                        size = entry.stat().st_size
                        os.remove(entry.path)
                    freed += size
                    n += 1
                except OSError:
                    errors += 1
    return f"{n} élément(s) supprimé(s), {fmt_bytes(freed)} libérés, {errors} ignoré(s) (verrouillés/protégés)."


def _clear_teams():
    run = _running(["ms-teams.exe", "teams.exe"])
    if run:
        return f"Fermez d'abord Teams ({', '.join(run)}) puis relancez l'action."
    return _purge([r"%APPDATA%\Microsoft\Teams\Cache", r"%APPDATA%\Microsoft\Teams\GPUCache",
                   r"%APPDATA%\Microsoft\Teams\Code Cache", r"%APPDATA%\Microsoft\Teams\blob_storage",
                   r"%APPDATA%\Microsoft\Teams\databases", r"%APPDATA%\Microsoft\Teams\IndexedDB",
                   r"%APPDATA%\Microsoft\Teams\Local Storage", r"%APPDATA%\Microsoft\Teams\tmp",
                   r"%LOCALAPPDATA%\Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams"])


def _clear_browsers():
    run = _running(["chrome.exe", "msedge.exe"])
    if run:
        return f"Fermez d'abord le navigateur ({', '.join(run)}) puis relancez l'action."
    pats = []
    for base in (r"%LOCALAPPDATA%\Google\Chrome\User Data", r"%LOCALAPPDATA%\Microsoft\Edge\User Data"):
        for prof in ("Default", "Profile *"):
            for sub in ("Cache\\Cache_Data", "Code Cache", "GPUCache", "Service Worker\\CacheStorage"):
                pats.append(os.path.join(base, prof, sub))
    return _purge(pats) + "\n(Historique, mots de passe et cookies conservés.)"


def _restart_explorer():
    out = powershell("Stop-Process -Name explorer -Force -EA SilentlyContinue; Start-Sleep 2; "
                     "if(-not (Get-Process explorer -EA SilentlyContinue)){ Start-Process explorer }; 'OK'")
    return out


ACTIONS = [
    # (titre, description, admin, confirmation, fonction)
    ("Vider le cache DNS", "ipconfig /flushdns — résout les sites qui ne se chargent plus après un changement DNS.",
     False, False, lambda: run_cmd(["ipconfig", "/flushdns"])),
    ("Renouveler l'adresse IP", "ipconfig /release puis /renew — coupe le réseau quelques secondes.",
     False, True, lambda: run_cmd(["ipconfig", "/release"], 60) + "\n" + run_cmd(["ipconfig", "/renew"], 90)),
    ("Réinitialiser Winsock et la pile IP", "netsh winsock reset + netsh int ip reset. Redémarrage requis ensuite.",
     True, True, lambda: run_cmd(["netsh", "winsock", "reset"]) + "\n" + run_cmd(["netsh", "int", "ip", "reset"])),
    ("Vider la file d'impression", "Arrête le spouleur, supprime les travaux bloqués, redémarre le spouleur.",
     True, True, lambda: powershell("Stop-Service Spooler -Force -EA Stop; "
                                    "Remove-Item \"$env:SystemRoot\\System32\\spool\\PRINTERS\\*\" -Force -EA SilentlyContinue; "
                                    "Start-Service Spooler; 'OK - file d''impression vidée'", 60)),
    ("Redémarrer l'Explorateur Windows", "Barre des tâches / menu Démarrer figés.", False, False, _restart_explorer),
    ("Redémarrer le service audio", "Pas de son : redémarre Audiosrv et AudioEndpointBuilder.",
     True, False, lambda: powershell("Restart-Service AudioEndpointBuilder -Force -EA Stop; Restart-Service Audiosrv -Force; 'OK'", 60)),
    ("Synchroniser l'heure", "w32tm /resync — erreurs Kerberos / certificats dues à une horloge décalée.",
     True, False, lambda: run_cmd(["w32tm", "/resync", "/force"], 60)),
    ("Forcer l'application des GPO", "gpupdate /force (ordinateur + utilisateur).",
     False, False, lambda: run_cmd(["gpupdate", "/force"], 300)),
    ("Vider le cache Teams", "Teams lent, ne charge pas, mauvais compte. Teams doit être fermé.",
     False, True, _clear_teams),
    ("Vider le cache Chrome / Edge", "Cache web uniquement (pas l'historique ni les mots de passe). Navigateurs fermés.",
     False, True, _clear_browsers),
    ("Vider les fichiers temporaires", "%TEMP% de l'utilisateur (+ C:\\Windows\\Temp si admin).",
     False, True, lambda: _purge([r"%TEMP%"] + ([r"%SystemRoot%\Temp"] if is_admin() else []))),
    ("Réparer les fichiers système (SFC)", "sfc /scannow — 10 à 30 minutes.",
     True, True, lambda: run_cmd(["sfc", "/scannow"], 3600)),
    ("Réparer l'image Windows (DISM)", "DISM /Online /Cleanup-Image /RestoreHealth — 10 à 40 minutes, Internet requis.",
     True, True, lambda: run_cmd(["DISM", "/Online", "/Cleanup-Image", "/RestoreHealth"], 3600)),
    ("Réinitialiser Windows Update", "Arrête wuauserv/bits, vide SoftwareDistribution\\Download, redémarre les services.",
     True, True, lambda: powershell("Stop-Service wuauserv,bits -Force -EA SilentlyContinue; "
                                    "Remove-Item \"$env:SystemRoot\\SoftwareDistribution\\Download\\*\" -Recurse -Force -EA SilentlyContinue; "
                                    "Start-Service bits,wuauserv; 'OK - composants Windows Update réinitialisés'", 120)),
    ("Mettre à jour les signatures Defender", "Update-MpSignature.",
     True, False, lambda: powershell("Update-MpSignature -EA Stop; 'OK'", 300)),
    ("Analyse rapide Defender", "Start-MpScan -ScanType QuickScan (quelques minutes).",
     True, False, lambda: powershell("Start-MpScan -ScanType QuickScan -EA Stop; 'OK - analyse terminée'", 1800)),
]


# ===================================================================== Windows Update
WU_HISTORY = r"""
$s=New-Object -ComObject Microsoft.Update.Session; $h=$s.CreateUpdateSearcher(); $n=$h.GetTotalHistoryCount()
@($h.QueryHistory(0,[math]::Min($n,80)) | Where-Object { $_.Title } | ForEach-Object {
  [pscustomobject]@{ d=$_.Date.ToString('yyyy-MM-dd HH:mm'); t=$_.Title; r=[int]$_.ResultCode; h=('0x{0:X8}' -f $_.HResult) } }) | ConvertTo-Json -Compress
"""
WU_PENDING = r"""
$s=New-Object -ComObject Microsoft.Update.Session; $r=$s.CreateUpdateSearcher().Search("IsInstalled=0 and IsHidden=0")
@($r.Updates | ForEach-Object { [pscustomobject]@{ t=$_.Title; sz=[int64]$_.MaxDownloadSize; c=(@($_.Categories | ForEach-Object {$_.Name}) -join ', ');
  rb=[bool]$_.RebootRequired } }) | ConvertTo-Json -Compress
"""
RESULT = {0: ("Non démarré", "INFO"), 1: ("En cours", "INFO"), 2: ("Réussi", "OK"), 3: ("Réussi avec erreurs", "ALERTE"),
          4: ("Échec", "CRITIQUE"), 5: ("Annulé", "ALERTE")}


class ToolboxPage(Page):
    title = "Toolbox"
    subtitle = "Réparations courantes, Windows Update, journal d'audit"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        tabs = QTabWidget()
        self.root.addWidget(tabs, 1)
        tabs.addTab(self._build_repairs(), "Réparations")
        tabs.addTab(self._build_wu(), "Windows Update")
        tabs.addTab(self._build_audit(), "Journal d'audit")
        tabs.currentChanged.connect(lambda i: i == 2 and self.load_audit())

    # ------------------------------------------------------------ réparations
    def _build_repairs(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        split = QSplitter()
        self.list = QListWidget(objectName="perfList")
        for title, desc, admin, _, _ in ACTIONS:
            it = QListWidgetItem(("🛡 " if admin else "") + title)
            it.setToolTip(desc)
            self.list.addItem(it)
        self.list.currentRowChanged.connect(self._select)
        split.addWidget(self.list)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 0, 0, 0)
        self.desc = QLabel("Choisissez une action à gauche.")
        self.desc.setWordWrap(True)
        rv.addWidget(self.desc)
        hb = QHBoxLayout()
        self.go = QPushButton("Exécuter")
        self.go.setObjectName("primary")
        self.go.setEnabled(False)
        self.go.clicked.connect(self._execute)
        hb.addWidget(self.go)
        self.state = QLabel("", objectName="muted")
        hb.addWidget(self.state, 1)
        rv.addLayout(hb)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace;")
        rv.addWidget(self.out, 1)
        split.addWidget(right)
        split.setSizes([320, 700])
        v.addWidget(split, 1)
        v.addWidget(QLabel("🛡 = droits administrateur requis. Chaque exécution est inscrite au journal d'audit.",
                           objectName="muted"))
        self.task = BackgroundTask(lambda f: f(), self._done)
        if not IS_WIN:
            self.desc.setText("Réparations disponibles sous Windows uniquement.")
            self.list.setEnabled(False)
        return w

    def _select(self, i):
        title, desc, admin, _, _ = ACTIONS[i]
        warn = "" if not admin or is_admin() else "<br><span style='color:#f59e0b'>Relancez NexTask en administrateur.</span>"
        self.desc.setText(f"<b>{title}</b><br>{desc}{warn}")
        self.go.setEnabled(True)

    def _execute(self):
        i = self.list.currentRow()
        if i < 0 or self.task.busy:
            return
        title, desc, admin, need_confirm, fn = ACTIONS[i]
        if need_confirm and not confirm(self, title, f"{desc}\n\nExécuter « {title} » ?"):
            return
        self._current = title
        self._t0 = time.time()
        self.task.start(fn)
        self.state.setText(f"{title} en cours…")
        self.out.appendPlainText(f"\n===== {title} — {time.strftime('%H:%M:%S')} =====")

    def _done(self, out):
        out = (out or "").strip() or "OK"
        dt = time.time() - self._t0
        self.out.appendPlainText(out)
        self.state.setText(f"Terminé en {dt:.0f} s")
        failed = out.startswith("ERREUR") or "accès refusé" in out.lower() or "access is denied" in out.lower()
        audit.log(f"Réparation : {self._current}", "", ("ÉCHEC : " if failed else "OK : ") + out.splitlines()[-1][:200])

    # ------------------------------------------------------------ Windows Update
    def _build_wu(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        hb = QHBoxLayout()
        b1 = QPushButton("Historique des installations")
        b1.clicked.connect(lambda: self._wu(WU_HISTORY, "hist"))
        b2 = QPushButton("Rechercher les mises à jour en attente")
        b2.clicked.connect(lambda: self._wu(WU_PENDING, "pending"))
        b3 = QPushButton("Ouvrir Windows Update")
        b3.clicked.connect(lambda: os.startfile("ms-settings:windowsupdate") if IS_WIN else None)  # type: ignore[attr-defined]
        for b in (b1, b2, b3):
            hb.addWidget(b)
        self.wu_state = QLabel("", objectName="muted")
        hb.addWidget(self.wu_state, 1)
        v.addLayout(hb)
        self.wu_tbl = TablePanel(["État", "Date", "Mise à jour", "Code"])
        self.wu_tbl.set_widths([150, 140, 620, 110])
        v.addWidget(self.wu_tbl, 1)
        self.wu_task = BackgroundTask(lambda s, k: (k, as_list(ps_json(s, 600))), self._wu_done)
        return w

    def _wu(self, script, kind):
        if not IS_WIN:
            self.wu_state.setText("Windows uniquement.")
            return
        if self.wu_task.start(script, kind):
            self.wu_state.setText("Interrogation de Windows Update (la recherche peut prendre 1-3 min)…")

    def _wu_done(self, res):
        kind, rows = res
        if kind == "hist":
            fails = sum(r.get("r") == 4 for r in rows)
            self.wu_state.setText(f"{len(rows)} entrées • {fails} échec(s)")
            out = []
            for r in rows:
                label, lvl = RESULT.get(r.get("r"), (str(r.get("r")), "INFO"))
                out.append([(label, lvl, STATUS_COLORS[lvl]), (r.get("d", ""), r.get("d", "")), r.get("t", ""),
                            r.get("h", "") if r.get("r") in (4, 5, 3) else ""])
            self.wu_tbl.set_rows(out)
            self.wu_tbl.sort_by(1)
        else:
            self.wu_state.setText(f"{len(rows)} mise(s) à jour en attente"
                                  + (" — redémarrage requis pour certaines" if any(r.get("rb") for r in rows) else ""))
            self.wu_tbl.set_rows([[("En attente", "ALERTE", STATUS_COLORS["ALERTE"]), r.get("c", ""), r.get("t", ""),
                                   fmt_bytes(r.get("sz", 0))] for r in rows])

    # ------------------------------------------------------------ audit
    def _build_audit(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        self.audit_tbl = TablePanel(["Date", "Utilisateur", "Action", "Cible", "Résultat"])
        self.audit_tbl.set_widths([150, 120, 240, 360, 360])
        self.audit_tbl.add_button("Actualiser", self.load_audit)
        v.addWidget(self.audit_tbl, 1)
        v.addWidget(QLabel("Toutes les actions effectuées depuis NexTask (fin de tâche, services, pare-feu, réparations…). "
                           "Envoyées aussi en syslog si configuré dans Settings.", objectName="muted"))
        return w

    def load_audit(self):
        rows = []
        for ts, user, action, target, result in audit.entries():
            col = STATUS_COLORS["CRITIQUE"] if result.upper().startswith("ÉCHEC") else None
            rows.append([(fmt_ts(ts), ts), user, action, target, (result, result, col)])
        self.audit_tbl.set_rows(rows)
        self.audit_tbl.sort_by(0)

