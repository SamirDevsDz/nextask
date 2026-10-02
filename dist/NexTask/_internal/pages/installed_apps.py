"""Installed Apps : inventaire des logiciels installés, désinstallation."""
import json
import subprocess
import webbrowser

from PySide6.QtWidgets import QCheckBox

from core.common import IS_WIN, BackgroundTask, fmt_bytes, run_cmd, powershell, open_location, confirm, info
from core.widgets import Page, TablePanel

if IS_WIN:
    import winreg
    UNINSTALL = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "Machine (64 bits)"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", "Machine (32 bits)"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", "Utilisateur"),
    ]


def _val(k, name, default=""):
    try:
        return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def _collect(include_store):
    apps = []
    if IS_WIN:
        seen = set()
        for hive, path, scope in UNINSTALL:
            try:
                root = winreg.OpenKey(hive, path)
            except OSError:
                continue
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub) as k:
                        name = _val(k, "DisplayName")
                        if not name or _val(k, "SystemComponent", 0) == 1 or _val(k, "ParentKeyName"):
                            continue
                        ver = _val(k, "DisplayVersion")
                        if (name, ver) in seen:
                            continue
                        seen.add((name, ver))
                        d = str(_val(k, "InstallDate"))
                        size_kb = _val(k, "EstimatedSize", 0) or 0
                        apps.append({
                            "name": name, "ver": ver, "pub": _val(k, "Publisher"),
                            "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else "",
                            "size": int(size_kb) * 1024 if str(size_kb).isdigit() else 0,
                            "loc": _val(k, "InstallLocation"), "scope": scope,
                            "uninst": _val(k, "QuietUninstallString") or _val(k, "UninstallString"),
                        })
                except OSError:
                    continue
        if include_store:
            out = powershell("Get-AppxPackage | Where-Object {-not $_.IsFramework -and $_.SignatureKind -ne 'System'} | "
                             "Select-Object Name,Version,Publisher,InstallLocation,PackageFullName | ConvertTo-Json -Compress", 90)
            try:
                data = json.loads(out)
                for a in data if isinstance(data, list) else [data]:
                    apps.append({"name": a["Name"], "ver": a["Version"], "pub": (a["Publisher"] or "").split(",")[0].replace("CN=", ""),
                                 "date": "", "size": 0, "loc": a["InstallLocation"] or "", "scope": "Microsoft Store",
                                 "uninst": f"powershell -Command Remove-AppxPackage '{a['PackageFullName']}'"})
            except (ValueError, KeyError, TypeError):
                pass
    else:
        out = run_cmd(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Maintainer}\t${Installed-Size}\n"])
        for line in out.splitlines():
            p = line.split("\t")
            if len(p) == 4:
                apps.append({"name": p[0], "ver": p[1], "pub": p[2], "date": "",
                             "size": int(p[3]) * 1024 if p[3].isdigit() else 0, "loc": "",
                             "scope": "dpkg", "uninst": ""})
    return apps


class InstalledAppsPage(Page):
    title = "Installed Apps"
    subtitle = "Logiciels installés"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        self.table = TablePanel(["Nom", "Version", "Éditeur", "Installé le", "Taille", "Portée",
                                 "Emplacement", "Désinstallation"], right_cols=(4,))
        self.table.set_widths([280, 110, 200, 100, 90, 130, 260, 300])
        self.store = QCheckBox("Inclure les apps Microsoft Store")
        self.store.setVisible(IS_WIN)
        self.store.toggled.connect(lambda _: self.load())
        self.table.toolbar.insertWidget(1, self.store)
        self.table.add_button("Actualiser", self.load)
        self.table.add_button("Désinstaller…", self._uninstall, needs_selection=True, danger=True)
        self.table.add_context("Désinstaller…", self._uninstall)
        self.table.add_context("Ouvrir l'emplacement", lambda r: open_location(r[6]))
        self.table.add_context("Rechercher en ligne",
                               lambda r: webbrowser.open(f"https://duckduckgo.com/?q={r[0]} {r[1]}"))
        self.root.addWidget(self.table, 1)
        self.task = BackgroundTask(_collect, self._show)
        self._loaded = False

    def on_show(self):
        if not self._loaded:
            self.load()

    def load(self):
        if self.task.start(self.store.isChecked()):
            self.table.status.setText("Inventaire en cours…")

    def _show(self, apps):
        self._loaded = True
        total = sum(a["size"] for a in apps)
        self.table.set_rows([[a["name"], a["ver"], a["pub"], a["date"],
                              (fmt_bytes(a["size"]) if a["size"] else "—", a["size"]),
                              a["scope"], a["loc"], a["uninst"]] for a in apps])
        self.table.sort_by(0, desc=False)
        self.table.status.setText(f"{len(apps)} logiciels • taille déclarée totale {fmt_bytes(total)}")

    def _uninstall(self, row):
        cmd = row[7]
        if not cmd:
            info(self, "Désinstaller", "Aucune commande de désinstallation déclarée pour ce logiciel.")
            return
        if confirm(self, "Désinstaller", f"Lancer la désinstallation de « {row[0]} » ?\n\nCommande :\n{cmd}"):
            try:
                subprocess.Popen(cmd, shell=True)
            except OSError as e:
                info(self, "Erreur", str(e))
