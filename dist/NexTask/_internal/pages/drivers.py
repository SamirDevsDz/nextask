"""Drivers : pilotes de périphériques (signature, version, date), pilotes noyau, périphériques en erreur."""
import json
from datetime import datetime

from PySide6.QtWidgets import QTabWidget, QComboBox

from core.common import IS_WIN, BackgroundTask, powershell, run_cmd
from core.widgets import Page, TablePanel


def _ps_json(script):
    out = powershell(script + " | ConvertTo-Json -Compress", 120)
    try:
        d = json.loads(out) if out.strip() else []
        return d if isinstance(d, list) else [d]
    except ValueError:
        return []


def _date(v):
    if isinstance(v, str) and v.startswith("/Date("):
        try:
            return datetime.fromtimestamp(int(v[6:19]) / 1000).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    return str(v or "")[:10]


def _collect():
    res = {"pnp": [], "kernel": [], "errors": []}
    if IS_WIN:
        for d in _ps_json("Get-CimInstance Win32_PnPSignedDriver | Where-Object DeviceName | "
                          "Select-Object DeviceName,DeviceClass,DriverProviderName,DriverVersion,DriverDate,IsSigned,Signer,InfName"):
            res["pnp"].append([d.get("DeviceName"), d.get("DeviceClass") or "", d.get("DriverProviderName") or "",
                               d.get("DriverVersion") or "", _date(d.get("DriverDate")),
                               "Oui" if d.get("IsSigned") else "NON", d.get("Signer") or "", d.get("InfName") or ""])
        for d in _ps_json("Get-CimInstance Win32_SystemDriver | Select-Object Name,DisplayName,State,StartMode,PathName"):
            res["kernel"].append([d.get("Name"), d.get("DisplayName"), d.get("State"), d.get("StartMode"),
                                  d.get("PathName") or ""])
        for d in _ps_json("Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 } | "
                          "Select-Object Name,PNPClass,ConfigManagerErrorCode,Status,DeviceID"):
            res["errors"].append([d.get("Name") or "(inconnu)", d.get("PNPClass") or "",
                                  d.get("ConfigManagerErrorCode"), d.get("Status") or "", d.get("DeviceID") or ""])
    else:
        for line in run_cmd(["lsmod"]).splitlines()[1:]:
            p = line.split()
            if len(p) >= 3:
                res["kernel"].append([p[0], "", "chargé", f"utilisé par {p[2]}", p[3] if len(p) > 3 else ""])
    return res


class DriversPage(Page):
    title = "Drivers"
    subtitle = "Pilotes et périphériques"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        self.tabs = QTabWidget()
        self.pnp = TablePanel(["Périphérique", "Classe", "Fournisseur", "Version", "Date",
                               "Signé", "Signataire", "INF"])
        self.pnp.set_widths([280, 110, 180, 130, 100, 60, 220, 110])
        self.flt = QComboBox()
        self.flt.addItems(["Tous", "Non signés uniquement", "Plus de 5 ans"])
        self.flt.currentTextChanged.connect(lambda _: self._apply())
        self.pnp.toolbar.insertWidget(1, self.flt)
        self.pnp.add_button("Actualiser", self.load)
        self.kernel = TablePanel(["Nom", "Nom complet", "État", "Démarrage", "Fichier"])
        self.kernel.set_widths([160, 280, 90, 100, 400])
        self.err = TablePanel(["Périphérique", "Classe", "Code erreur", "Statut", "ID matériel"])
        self.err.set_widths([280, 110, 90, 90, 400])
        self.tabs.addTab(self.pnp, "Pilotes de périphériques")
        self.tabs.addTab(self.kernel, "Pilotes noyau")
        self.tabs.addTab(self.err, "Périphériques en erreur")
        self.root.addWidget(self.tabs, 1)
        self.data = {"pnp": []}
        self.task = BackgroundTask(_collect, self._show)
        self._loaded = False

    def on_show(self):
        if not self._loaded:
            self.load()

    def load(self):
        if self.task.start():
            self.pnp.status.setText("Interrogation WMI… (10-30 s)")

    def _show(self, d):
        self._loaded = True
        self.data = d
        self._apply()
        self.kernel.set_rows(d["kernel"])
        self.err.set_rows(d["errors"])
        self.tabs.setTabText(2, f"Périphériques en erreur ({len(d['errors'])})")

    def _apply(self):
        f = self.flt.currentText()
        limit = f"{datetime.now().year - 5}"
        rows = [r for r in self.data["pnp"]
                if f == "Tous" or (f.startswith("Non") and r[5] == "NON") or (f.startswith("Plus") and r[4] and r[4] < limit)]
        self.pnp.set_rows(rows)
        unsigned = sum(1 for r in self.data["pnp"] if r[5] == "NON")
        self.pnp.status.setText(f"{len(rows)} affiché(s) • {len(self.data['pnp'])} pilotes • {unsigned} non signé(s)")
