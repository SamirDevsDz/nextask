"""Identity & Shares : jonction Entra ID / domaine, GPO, certificats, partages SMB, comptes locaux."""
import os
import re
import tempfile
from datetime import datetime

from PySide6.QtWidgets import (QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QPlainTextEdit,
                               QComboBox)

from core import audit
from core.common import IS_WIN, BackgroundTask, run_cmd, ps_json, as_list, powershell, confirm, info
from core.widgets import Page, TablePanel, STATUS_COLORS

JOIN_KEYS = ["AzureAdJoined", "EnterpriseJoined", "DomainJoined", "DomainName", "WorkplaceJoined", "TenantName",
             "TenantId", "DeviceId", "DeviceAuthStatus", "AzureAdPrt", "AzureAdPrtUpdateTime", "WorkplaceTenantName",
             "IsDeviceJoined", "IsUserAzureAD", "NgcSet", "KeySignTest", "MdmUrl"]


def _join():
    if not IS_WIN:
        return [["Plateforme", "Windows uniquement", "INFO"]]
    out = run_cmd(["dsregcmd", "/status"], 30)
    rows = []
    for line in out.splitlines():
        m = re.match(r"\s*([A-Za-z]+)\s*:\s*(.+)$", line)
        if m and m.group(1) in JOIN_KEYS:
            k, v = m.group(1), m.group(2).strip()
            lvl = "OK" if v == "YES" else "INFO"
            if k == "AzureAdPrt" and v == "NO":
                lvl = "ALERTE"
            if k == "DeviceAuthStatus" and v != "SUCCESS":
                lvl = "ALERTE"
            rows.append([k, v, lvl])
    cs = ps_json("Get-CimInstance Win32_ComputerSystem | Select-Object Domain,PartOfDomain,Workgroup | ConvertTo-Json -Compress") or {}
    rows.append(["Domaine / groupe (WMI)", cs.get("Domain") if cs.get("PartOfDomain") else f"Groupe de travail {cs.get('Workgroup', '')}", "INFO"])
    sc = run_cmd(["nltest", "/sc_query:" + str(cs.get("Domain"))], 20) if cs.get("PartOfDomain") else ""
    if sc:
        ok = "NERR_Success" in sc or "Success" in sc
        rows.append(["Canal sécurisé avec le DC", "OK" if ok else sc.strip().splitlines()[-1], "OK" if ok else "CRITIQUE"])
    rows.append(["Utilisateur courant", run_cmd(["whoami", "/upn"], 10).strip() or run_cmd(["whoami"], 10).strip(), "INFO"])
    return rows


def _gpo(scope):
    if not IS_WIN:
        return "Windows uniquement."
    return run_cmd(["gpresult", "/r", "/scope", scope], 120)


CERT_PS = r"""
$o=@(); foreach($st in 'Cert:\LocalMachine\My','Cert:\CurrentUser\My','Cert:\LocalMachine\WebHosting'){
  try{ Get-ChildItem $st -EA Stop | ForEach-Object { $o += [pscustomobject]@{ st=$st -replace 'Cert:\\',''; s=$_.Subject; i=$_.Issuer;
    na=$_.NotAfter.ToString('yyyy-MM-dd'); d=[int]($_.NotAfter-(Get-Date)).TotalDays; th=$_.Thumbprint; pk=$_.HasPrivateKey;
    eku=(@($_.EnhancedKeyUsageList | ForEach-Object {$_.FriendlyName}) -join ', ') } } }catch{} }
ConvertTo-Json -InputObject @($o) -Compress
"""


def _certs():
    return as_list(ps_json(CERT_PS, 60)) if IS_WIN else []


SMB_PS = {
    "shares": "Get-SmbShare -EA Stop | Select-Object Name,Path,Description,CurrentUsers,ShareType | ConvertTo-Json -Compress",
    "sessions": "Get-SmbSession -EA Stop | Select-Object SessionId,ClientComputerName,ClientUserName,NumOpens,SecondsExists,Dialect | ConvertTo-Json -Compress",
    "open": "Get-SmbOpenFile -EA Stop | Select-Object FileId,ClientComputerName,ClientUserName,Path | ConvertTo-Json -Compress",
    "mapped": "Get-SmbMapping -EA Stop | Select-Object LocalPath,RemotePath,Status | ConvertTo-Json -Compress",
}


def _smb(kind):
    return as_list(ps_json(SMB_PS[kind], 60)) if IS_WIN else []


USERS_PS = r"""
@(Get-LocalUser | ForEach-Object { [pscustomobject]@{ n=$_.Name; e=[bool]$_.Enabled;
  ll=if($_.LastLogon){$_.LastLogon.ToString('yyyy-MM-dd HH:mm')}else{''};
  pls=if($_.PasswordLastSet){$_.PasswordLastSet.ToString('yyyy-MM-dd')}else{''};
  pe=if($_.PasswordExpires){$_.PasswordExpires.ToString('yyyy-MM-dd')}else{'jamais'}; pr=[bool]$_.PasswordRequired;
  sid=$_.SID.Value; d=$_.Description } }) | ConvertTo-Json -Compress
"""


def _users():
    if not IS_WIN:
        return []
    from core.security_checks import local_admins
    admins = {a.split("\\")[-1].lower() for a in local_admins()}
    rows = as_list(ps_json(USERS_PS, 30))
    for r in rows:
        r["admin"] = r.get("n", "").lower() in admins
    return rows


def _c(text, lvl):
    return (text, text, STATUS_COLORS.get(lvl))


class IdentityPage(Page):
    title = "Identity & Shares"
    subtitle = "Jonction, GPO, certificats, partages SMB, comptes locaux"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        self.tasks = {}

        # --- jonction
        self.join_tbl = self._tab("Jonction Entra ID / domaine", ["Propriété", "Valeur"], [240, 500], _join, self._join_done)
        # --- GPO
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        hb = QHBoxLayout()
        self.gpo_scope = QComboBox()
        self.gpo_scope.addItems(["user", "computer"])
        hb.addWidget(QLabel("Portée :"))
        hb.addWidget(self.gpo_scope)
        b = QPushButton("Afficher les GPO appliquées")
        b.setObjectName("primary")
        b.clicked.connect(lambda: self._run("gpo", self.gpo_scope.currentText()))
        hb.addWidget(b)
        b2 = QPushButton("Rapport HTML complet (gpresult /h)")
        b2.clicked.connect(self._gpo_html)
        hb.addWidget(b2)
        hb.addStretch()
        v.addLayout(hb)
        v.addWidget(QLabel("La portée « computer » exige les droits administrateur.", objectName="muted"))
        self.gpo_out = QPlainTextEdit()
        self.gpo_out.setReadOnly(True)
        self.gpo_out.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace;")
        v.addWidget(self.gpo_out, 1)
        self.tabs.addTab(w, "Stratégies de groupe")
        self.tasks["gpo"] = BackgroundTask(_gpo, self.gpo_out.setPlainText)

        # --- certificats
        self.cert_tbl = self._tab("Certificats", ["État", "Expire le", "Jours", "Magasin", "Sujet", "Émetteur",
                                                  "Usages", "Clé privée", "Empreinte"],
                                  [90, 100, 60, 150, 280, 240, 200, 80, 300], _certs, self._certs_done)
        # --- SMB
        w2 = QWidget()
        v2 = QVBoxLayout(w2)
        v2.setContentsMargins(0, 8, 0, 0)
        hb2 = QHBoxLayout()
        self.smb_kind = QComboBox()
        self.smb_kind.addItem("Partages de ce poste", "shares")
        self.smb_kind.addItem("Sessions ouvertes (clients connectés)", "sessions")
        self.smb_kind.addItem("Fichiers ouverts à distance", "open")
        self.smb_kind.addItem("Lecteurs réseau mappés (ce poste → serveurs)", "mapped")
        hb2.addWidget(self.smb_kind)
        b3 = QPushButton("Afficher")
        b3.setObjectName("primary")
        b3.clicked.connect(lambda: self._run("smb", self.smb_kind.currentData()))
        hb2.addWidget(b3)
        hb2.addStretch()
        v2.addLayout(hb2)
        self.smb_tbl = TablePanel(["Col 1", "Col 2", "Col 3", "Col 4", "Col 5", "Col 6"])
        self.smb_tbl.add_button("Fermer (session / fichier)", self._smb_close, needs_selection=True, danger=True)
        v2.addWidget(self.smb_tbl, 1)
        self.tabs.addTab(w2, "Partages SMB")
        self.tasks["smb"] = BackgroundTask(lambda k: (k, _smb(k)), self._smb_done)
        self._smb_kind = "shares"

        # --- comptes locaux
        self.users_tbl = self._tab("Comptes locaux", ["Compte", "Activé", "Admin", "Dernière connexion",
                                                      "Mot de passe changé", "Expire", "Mdp requis", "Description"],
                                   [160, 70, 70, 150, 140, 100, 90, 300], _users, self._users_done)
        self.tabs.currentChanged.connect(self._auto)
        self._seen = set()

    # ------------------------------------------------------------
    def _tab(self, title, headers, widths, fn, done):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        t = TablePanel(headers)
        t.set_widths(widths)
        t.add_button("Actualiser", lambda: self._run(title))
        v.addWidget(t, 1)
        self.tabs.addTab(w, title)
        self.tasks[title] = BackgroundTask(fn, done)
        return t

    def _run(self, key, *args):
        self.tasks[key].start(*args)

    def _auto(self, i):
        title = self.tabs.tabText(i)
        if title in self.tasks and title not in self._seen:
            self._seen.add(title)
            self._run(title)

    def on_show(self):
        self._auto(self.tabs.currentIndex())

    def _join_done(self, rows):
        self.join_tbl.set_rows([[k, _c(v, lvl)] for k, v, lvl in rows])

    def _certs_done(self, certs):
        rows = []
        for c in certs:
            d = c.get("d", 0)
            lvl = "CRITIQUE" if d < 0 else "ALERTE" if d <= 30 else "OK"
            label = "Expiré" if d < 0 else "Bientôt" if d <= 30 else "Valide"
            rows.append([(label, d, STATUS_COLORS[lvl]), c.get("na"), d, c.get("st"), c.get("s"), c.get("i"),
                         c.get("eku"), "Oui" if c.get("pk") else "Non", c.get("th")])
        self.cert_tbl.set_rows(rows)
        self.cert_tbl.sort_by(2, desc=False)
        self.cert_tbl.status.setText(f"{len(rows)} certificat(s) • {sum(c.get('d', 0) <= 30 for c in certs)} expiré(s) ou < 30 jours")

    def _users_done(self, users):
        rows = []
        for u in users:
            rows.append([u.get("n"), _c("Oui" if u.get("e") else "Non", "OK" if u.get("e") else "INFO"),
                         _c("Oui", "ALERTE") if u.get("admin") else "Non", u.get("ll"), u.get("pls"), u.get("pe"),
                         _c("Oui", "OK") if u.get("pr") else _c("Non", "ALERTE"), u.get("d")])
        self.users_tbl.set_rows(rows)

    def _smb_done(self, res):
        kind, rows = res
        self._smb_kind = kind
        spec = {
            "shares": (["Nom", "Chemin", "Description", "Utilisateurs", "Type"], ["Name", "Path", "Description", "CurrentUsers", "ShareType"]),
            "sessions": (["ID session", "Client", "Utilisateur", "Fichiers ouverts", "Durée (s)", "Dialecte"],
                         ["SessionId", "ClientComputerName", "ClientUserName", "NumOpens", "SecondsExists", "Dialect"]),
            "open": (["ID fichier", "Client", "Utilisateur", "Chemin"], ["FileId", "ClientComputerName", "ClientUserName", "Path"]),
            "mapped": (["Lecteur", "Chemin distant", "État"], ["LocalPath", "RemotePath", "Status"]),
        }[kind]
        self.smb_tbl.model.headers = spec[0]
        self.smb_tbl.set_rows([[r.get(k, "") for k in spec[1]] for r in rows])
        self.smb_tbl.set_widths([120, 220, 220, 300, 120, 100])
        if not rows and IS_WIN:
            self.smb_tbl.status.setText("Aucun élément (ou droits administrateur requis pour sessions / fichiers ouverts).")

    def _smb_close(self, row):
        if self._smb_kind == "sessions":
            cmd, label = f"Close-SmbSession -SessionId {int(row[0])} -Force -EA Stop; 'OK'", f"session {row[2]}@{row[1]}"
        elif self._smb_kind == "open":
            cmd, label = f"Close-SmbOpenFile -FileId {int(row[0])} -Force -EA Stop; 'OK'", f"{row[3]} ({row[2]})"
        else:
            info(self, "SMB", "Choisissez « Sessions ouvertes » ou « Fichiers ouverts ».")
            return
        if confirm(self, "Fermer", f"Fermer {label} ?\nL'utilisateur distant peut perdre des modifications non enregistrées."):
            out = powershell(cmd, 30).strip()
            audit.log("SMB : fermeture", label, out[-200:])
            info(self, "Résultat", out)
            self._run("smb", self._smb_kind)

    def _gpo_html(self):
        if not IS_WIN:
            return
        path = os.path.join(tempfile.gettempdir(), f"gpresult_{datetime.now():%Y%m%d_%H%M%S}.html")
        out = run_cmd(["gpresult", "/h", path, "/f"], 180)
        if os.path.exists(path):
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            info(self, "gpresult", out)

