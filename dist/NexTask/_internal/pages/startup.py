"""Startup apps : programmes lancés au démarrage (registre Run + dossiers Démarrage), activer/désactiver."""
import glob
import os
import re
import struct
import time

from core.common import IS_WIN, BackgroundTask, open_location, confirm, info
from core.widgets import Page, TablePanel
from core import audit

if IS_WIN:
    import winreg

    RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
    APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
    # (ruche, clé Run, ruche approbation, sous-clé approbation, libellé)
    REG_SOURCES = [
        (winreg.HKEY_CURRENT_USER, RUN, winreg.HKEY_CURRENT_USER, "Run", "Registre HKCU"),
        (winreg.HKEY_LOCAL_MACHINE, RUN, winreg.HKEY_LOCAL_MACHINE, "Run", "Registre HKLM"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
         winreg.HKEY_LOCAL_MACHINE, "Run32", "Registre HKLM (32 bits)"),
    ]


def _approved_state(hive, sub, name):
    """True = activé, False = désactivé (valeur binaire : 1er octet impair = désactivé)."""
    try:
        with winreg.OpenKey(hive, f"{APPROVED}\\{sub}") as k:
            val, _ = winreg.QueryValueEx(k, name)
            return not (val[0] & 1)
    except OSError:
        return True


def _exe_from_cmd(cmd):
    cmd = os.path.expandvars(cmd or "")
    m = re.match(r'^\s*"([^"]+)"', cmd)
    if m:
        return m.group(1)
    m = re.match(r"^\s*(\S+?\.(exe|bat|cmd|lnk|vbs))", cmd, re.I)
    return m.group(1) if m else cmd.split(" ")[0]


def _collect():
    items = []
    if IS_WIN:
        for hive, key, ahive, asub, label in REG_SOURCES:
            try:
                with winreg.OpenKey(hive, key) as k:
                    i = 0
                    while True:
                        try:
                            name, val, _ = winreg.EnumValue(k, i)
                        except OSError:
                            break
                        i += 1
                        items.append({"name": name, "cmd": str(val), "source": label,
                                      "enabled": _approved_state(ahive, asub, name),
                                      "ahive": ahive, "asub": asub})
            except OSError:
                continue
        folders = [
            (os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"),
             winreg.HKEY_CURRENT_USER, "Dossier Démarrage (utilisateur)"),
            (os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs\StartUp"),
             winreg.HKEY_LOCAL_MACHINE, "Dossier Démarrage (commun)"),
        ]
        for folder, ahive, label in folders:
            for f in glob.glob(os.path.join(folder, "*")):
                base = os.path.basename(f)
                if base.lower() == "desktop.ini":
                    continue
                items.append({"name": base, "cmd": f, "source": label,
                              "enabled": _approved_state(ahive, "StartupFolder", base),
                              "ahive": ahive, "asub": "StartupFolder"})
    else:
        for folder in (os.path.expanduser("~/.config/autostart"), "/etc/xdg/autostart"):
            for f in glob.glob(os.path.join(folder, "*.desktop")):
                d = {}
                try:
                    with open(f, encoding="utf-8", errors="ignore") as fh:
                        for line in fh:
                            if "=" in line:
                                k, v = line.strip().split("=", 1)
                                d.setdefault(k, v)
                except OSError:
                    continue
                items.append({"name": d.get("Name", os.path.basename(f)), "cmd": d.get("Exec", ""),
                              "source": folder, "enabled": d.get("Hidden", "false") != "true"
                              and d.get("X-GNOME-Autostart-enabled", "true") != "false", "file": f})
    return items


def set_enabled(item, enabled):
    if not IS_WIN:
        raise OSError("Activation/désactivation implémentée pour Windows uniquement.")
    # 12 octets : drapeau + 3 octets nuls + FILETIME (date de désactivation)
    ft = int((time.time() + 11644473600) * 10_000_000)
    data = (b"\x02" + b"\x00" * 11) if enabled else (b"\x03\x00\x00\x00" + struct.pack("<Q", ft))
    with winreg.CreateKeyEx(item["ahive"], f"{APPROVED}\\{item['asub']}", 0,
                            winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, item["name"], 0, winreg.REG_BINARY, data)


class StartupPage(Page):
    title = "Startup apps"
    subtitle = "Programmes lancés à l'ouverture de session"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        self.table = TablePanel(["Nom", "État", "Source", "Commande"], key_col=0)
        self.table.set_widths([240, 90, 220, 500])
        self.table.add_button("Actualiser", self.load)
        self.table.add_button("Activer", lambda r: self._toggle(True), needs_selection=True)
        self.table.add_button("Désactiver", lambda r: self._toggle(False), needs_selection=True, danger=True)
        self.table.add_context("Activer", lambda r: self._toggle(True))
        self.table.add_context("Désactiver", lambda r: self._toggle(False))
        self.table.add_context("Ouvrir l'emplacement du fichier",
                               lambda r: open_location(_exe_from_cmd(r[3])))
        self.root.addWidget(self.table, 1)
        self.items = []
        self.task = BackgroundTask(_collect, self._show)
        self._loaded = False

    def on_show(self):
        if not self._loaded:
            self.load()

    def load(self):
        self.task.start()

    def _show(self, items):
        self._loaded = True
        self.items = items
        self.table.set_rows([[i["name"], "Activé" if i["enabled"] else "Désactivé", i["source"], i["cmd"]]
                             for i in items])

    def _toggle(self, enabled):
        row = self.table.selected_row()
        if not row:
            return
        item = next((i for i in self.items if i["name"] == row[0] and i["source"] == row[2]), None)
        if not item:
            return
        verb = "activer" if enabled else "désactiver"
        if not confirm(self, "Démarrage", f"Voulez-vous {verb} « {item['name']} » au démarrage ?\n"
                                          "(Même mécanisme que le Gestionnaire des tâches Windows, réversible.)"):
            return
        try:
            set_enabled(item, enabled)
            audit.log("Démarrage : " + ("activation" if enabled else "désactivation"), item["name"])
        except PermissionError:
            audit.log("Démarrage : " + verb, item["name"], "ÉCHEC : accès refusé")
            info(self, "Accès refusé", "Les entrées HKLM / dossier commun nécessitent les droits administrateur.")
            return
        except OSError as e:
            info(self, "Erreur", str(e))
            return
        self.load()
