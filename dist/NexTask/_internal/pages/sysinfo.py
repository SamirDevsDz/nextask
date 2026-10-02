"""System Info : inventaire matériel et logiciel (OS, CPU, RAM, carte mère, GPU, disques, réseau)."""
import json
import platform
import socket
from functools import lru_cache

import psutil
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QPushButton, QLabel

from core.common import IS_WIN, BackgroundTask, fmt_bytes, fmt_ts, fmt_duration, powershell


@lru_cache(maxsize=1)
def cpu_name() -> str:
    if IS_WIN:
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "Processeur inconnu"


CIM_QUERIES = {
    "Système d'exploitation": ("Win32_OperatingSystem",
                               "Caption,Version,BuildNumber,OSArchitecture,InstallDate,RegisteredUser,SerialNumber"),
    "Ordinateur": ("Win32_ComputerSystem", "Manufacturer,Model,Domain,SystemType,TotalPhysicalMemory,UserName"),
    "Carte mère": ("Win32_BaseBoard", "Manufacturer,Product,SerialNumber,Version"),
    "BIOS": ("Win32_BIOS", "Manufacturer,SMBIOSBIOSVersion,ReleaseDate,SerialNumber"),
    "Processeur (WMI)": ("Win32_Processor",
                         "Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,L2CacheSize,L3CacheSize,SocketDesignation,VirtualizationFirmwareEnabled"),
    "Barrettes mémoire": ("Win32_PhysicalMemory", "BankLabel,Capacity,Speed,Manufacturer,PartNumber"),
    "Carte graphique": ("Win32_VideoController",
                        "Name,DriverVersion,AdapterRAM,VideoModeDescription,CurrentRefreshRate"),
    "Disques physiques": ("Win32_DiskDrive", "Model,Size,InterfaceType,MediaType,SerialNumber,Status"),
    "Moniteurs": ("Win32_DesktopMonitor", "Name,ScreenWidth,ScreenHeight"),
}


def _collect():
    data = {}
    vm = psutil.virtual_memory()
    data["Résumé"] = [{
        "Nom de l'ordinateur": socket.gethostname(),
        "Système": f"{platform.system()} {platform.release()}",
        "Version": platform.version(),
        "Architecture": platform.machine(),
        "Processeur": cpu_name(),
        "Cœurs / threads": f"{psutil.cpu_count(False)} / {psutil.cpu_count()}",
        "Mémoire totale": fmt_bytes(vm.total),
        "Démarrage": fmt_ts(psutil.boot_time()),
        "Temps d'activité": fmt_duration(__import__("time").time() - psutil.boot_time()),
        "Python": platform.python_version(),
    }]
    if IS_WIN:
        for label, (cls, props) in CIM_QUERIES.items():
            out = powershell(f"Get-CimInstance {cls} | Select-Object {props} | ConvertTo-Json -Compress", 40)
            try:
                obj = json.loads(out) if out.strip() else []
                data[label] = obj if isinstance(obj, list) else [obj]
            except json.JSONDecodeError:
                data[label] = [{"Erreur": out.strip()[:200]}]
    else:
        dmi = {}
        for k in ("sys_vendor", "product_name", "board_vendor", "board_name", "bios_vendor", "bios_version"):
            try:
                with open(f"/sys/class/dmi/id/{k}", encoding="utf-8") as f:
                    dmi[k] = f.read().strip()
            except OSError:
                pass
        if dmi:
            data["Ordinateur / carte mère"] = [dmi]
    # stockage logique
    parts = []
    for p in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(p.mountpoint)
            parts.append({"Lecteur": p.mountpoint, "Système de fichiers": p.fstype,
                          "Taille": fmt_bytes(u.total), "Libre": fmt_bytes(u.free),
                          "Utilisé": f"{u.percent:.0f} %"})
        except Exception:  # noqa: BLE001
            continue
    data["Volumes"] = parts
    # réseau
    nets = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        d = {"Interface": name, "État": "actif" if stats.get(name) and stats[name].isup else "inactif"}
        for a in addrs:
            fam = getattr(a.family, "name", str(a.family))
            if fam == "AF_INET":
                d["IPv4"] = f"{a.address} / {a.netmask}"
            elif fam == "AF_INET6":
                d.setdefault("IPv6", a.address)
            elif fam in ("AF_LINK", "AF_PACKET"):
                d["MAC"] = a.address
        if stats.get(name) and stats[name].speed:
            d["Vitesse"] = f"{stats[name].speed} Mb/s"
        nets.append(d)
    data["Cartes réseau"] = nets
    return data


def _fmt(key, val):
    if val is None:
        return "—"
    if key in ("Capacity", "Size", "AdapterRAM", "TotalPhysicalMemory") and str(val).isdigit():
        return fmt_bytes(int(val))
    if isinstance(val, str) and val.startswith("/Date("):
        try:
            return fmt_ts(int(val[6:19]) / 1000)
        except ValueError:
            pass
    return str(val)


from core.widgets import Page  # noqa: E402


class SysInfoPage(Page):
    title = "System Info"
    subtitle = "Inventaire matériel et logiciel"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Propriété", "Valeur"])
        self.tree.setColumnWidth(0, 300)
        self.state = QLabel("", objectName="muted")
        b = QPushButton("Actualiser")
        b.clicked.connect(self.load)
        c = QPushButton("Copier le rapport")
        c.clicked.connect(self.copy)
        self.header_actions.addWidget(self.state)
        self.header_actions.addWidget(b)
        self.header_actions.addWidget(c)
        self.root.addWidget(self.tree, 1)
        self.task = BackgroundTask(_collect, self._show)
        self._loaded = False

    def on_show(self):
        if not self._loaded:
            self.load()

    def load(self):
        if self.task.start():
            self.state.setText("Collecte en cours… (WMI peut prendre quelques secondes)")

    def _show(self, data):
        self._loaded = True
        self.state.setText("")
        self.tree.clear()
        for section, items in data.items():
            top = QTreeWidgetItem([section, f"{len(items)} élément(s)" if len(items) > 1 else ""])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            for i, obj in enumerate(items):
                parent = top
                if len(items) > 1:
                    parent = QTreeWidgetItem([f"#{i + 1}", ""])
                    top.addChild(parent)
                for k, v in (obj or {}).items():
                    parent.addChild(QTreeWidgetItem([str(k), _fmt(k, v)]))
            top.setExpanded(True)
        self.tree.expandAll()

    def copy(self):
        lines = []
        for i in range(self.tree.topLevelItemCount()):
            self._dump(self.tree.topLevelItem(i), 0, lines)
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.window().statusBar().showMessage("Rapport copié dans le presse-papiers", 3000)

    def _dump(self, item, depth, out):
        out.append("  " * depth + item.text(0) + (f" : {item.text(1)}" if item.text(1) else ""))
        for j in range(item.childCount()):
            self._dump(item.child(j), depth + 1, out)


