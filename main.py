"""NexTask — gestionnaire des tâches alternatif (Python + PySide6).

Lancer :  python main.py        (idéalement en administrateur sous Windows)
"""
import os
import sys

from PySide6.QtCore import Qt, QSettings, QSize
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QAction
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QListWidget,
                               QListWidgetItem, QStackedWidget, QLabel, QComboBox, QPushButton,
                               QStatusBar, QSystemTrayIcon, QMenu, QStyle)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.common import APP_NAME, IS_WIN, is_admin, relaunch_as_admin, fmt_duration  # noqa: E402
from core.sampler import Sampler  # noqa: E402
from core.theme import stylesheet  # noqa: E402
from pages.summary import SummaryPage  # noqa: E402
from pages.performance import PerformancePage  # noqa: E402
from pages.processes import ProcessesPage  # noqa: E402
from pages.sysinfo import SysInfoPage  # noqa: E402
from pages.app_history import AppHistoryPage, AppHistoryTracker  # noqa: E402
from pages.startup import StartupPage  # noqa: E402
from pages.users import UsersPage  # noqa: E402
from pages.services import ServicesPage  # noqa: E402
from pages.power import PowerPage  # noqa: E402
from pages.flight_recorder import FlightRecorderPage, Recorder  # noqa: E402
from pages.connections import ConnectionsPage  # noqa: E402
from pages.installed_apps import InstalledAppsPage  # noqa: E402
from pages.drivers import DriversPage  # noqa: E402
from pages.disk_space import DiskSpacePage  # noqa: E402
from pages.security import SecurityPage  # noqa: E402
from pages.network_tools import NetworkToolsPage  # noqa: E402
from pages.toolbox import ToolboxPage  # noqa: E402
from pages.baseline import BaselinePage  # noqa: E402
from pages.identity import IdentityPage  # noqa: E402
from pages.report import ReportPage  # noqa: E402
from pages.settings import SettingsPage  # noqa: E402

# (glyphe Segoe Fluent/MDL2, libellé, classe) — chaîne seule = séparateur de section
MENU = [
    ("\uE80F", "Summary", SummaryPage),
    ("\uE9D2", "Performance", PerformancePage),
    ("\uE9F5", "Processes", ProcessesPage),
    ("\uE946", "System Info", SysInfoPage),
    ("\uE81C", "App history", AppHistoryPage),
    ("\uE768", "Startup apps", StartupPage),
    ("\uE716", "Users", UsersPage),
    ("\uE90F", "Services", ServicesPage),
    "PRO",
    ("\uE945", "Power & Freq", PowerPage),
    ("\uE724", "Flight Recorder", FlightRecorderPage),
    ("\uE774", "Connections", ConnectionsPage),
    ("\uE8FD", "Installed Apps", InstalledAppsPage),
    ("\uE950", "Drivers", DriversPage),
    ("\uEDA2", "Disk Space", DiskSpacePage),
    "ADMIN",
    ("\uEA18", "Security", SecurityPage),
    ("\uE839", "Network Tools", NetworkToolsPage),
    ("\uEC7A", "Toolbox", ToolboxPage),
    ("\uE722", "Baseline", BaselinePage),
    ("\uE77B", "Identity & Shares", IdentityPage),
    ("\uE8A5", "Report", ReportPage),
    "",
    ("\uE713", "Settings", SettingsPage),
]


def icon_font():
    fams = set(QFontDatabase.families())
    for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if f in fams:
            return f
    return None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(APP_NAME, APP_NAME)
        self.setWindowTitle(f"{APP_NAME} — Gestionnaire des tâches" + ("  [Administrateur]" if is_admin() else ""))
        self.resize(1280, 800)

        self.sampler = Sampler(self)
        self.history = AppHistoryTracker(self.sampler)
        self.recorder = Recorder(self.sampler)

        central = QWidget(objectName="central")
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.side = QListWidget(objectName="sidebar")
        self.side.setFixedWidth(210)
        self.side.setIconSize(QSize(18, 18))
        self.stack = QStackedWidget()
        lay.addWidget(self.side)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        ifont = icon_font()
        self.pages = []
        for entry in MENU:
            if isinstance(entry, str):
                it = QListWidgetItem(f"{entry}  ─────────────" if entry else "")
                it.setFlags(Qt.NoItemFlags)
                f = it.font()
                f.setPointSize(8)
                it.setFont(f)
                self.side.addItem(it)
                self.pages.append(None)
                continue
            glyph, label, cls = entry
            it = QListWidgetItem(f"{glyph}   {label}" if ifont else label)
            if ifont:
                f = QFont()
                f.setFamilies([ifont, "Segoe UI"])
                f.setPointSize(10)
                it.setFont(f)
            self.side.addItem(it)
            kwargs = {}
            if cls is AppHistoryPage:
                kwargs["tracker"] = self.history
            if cls in (FlightRecorderPage, ReportPage):
                kwargs["recorder"] = self.recorder
            page = cls(self.sampler, **kwargs)
            self.stack.addWidget(page)
            self.pages.append(page)
        self.side.currentRowChanged.connect(self._switch)

        # barre d'état
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.lbl = QLabel("")
        sb.addWidget(self.lbl, 1)
        admin = QLabel("● Administrateur" if is_admin() else "● Utilisateur standard (droits limités)")
        admin.setObjectName("badgeAdmin" if is_admin() else "badgeUser")
        sb.addPermanentWidget(admin)
        if IS_WIN and not is_admin():
            b = QPushButton("Relancer en admin")
            b.clicked.connect(self._elevate)
            sb.addPermanentWidget(b)
        sb.addPermanentWidget(QLabel("Rafraîchissement :"))
        self.rate = QComboBox()
        self.rate.addItems(["0,5 s", "1 s", "2 s", "5 s"])
        self.rate.setCurrentIndex(int(self.settings.value("rate", 1)))
        self.rate.currentIndexChanged.connect(self._rate)
        sb.addPermanentWidget(self.rate)
        self.theme_btn = QPushButton()
        self.theme_btn.clicked.connect(self._toggle_theme)
        sb.addPermanentWidget(self.theme_btn)
        self.mode = self.settings.value("theme", "dark")
        self._apply_theme()

        self._setup_tray()
        self.recorder.event.connect(self._notify)
        self._quitting = False

        self.sampler.updated.connect(self._tick)
        self.sampler.start([500, 1000, 2000, 5000][self.rate.currentIndex()])
        self.side.setCurrentRow(int(self.settings.value("page", 0)))

    # ------------------------------------------------------------------
    def _switch(self, row):
        page = self.pages[row] if 0 <= row < len(self.pages) else None
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        self.settings.setValue("page", row)
        page.on_show()

    def _tick(self):
        s = self.sampler
        self.lbl.setText(f"CPU {s.cpu:.0f} %   •   Mémoire {s.vm.percent:.0f} %   •   "
                         f"Processus {len(s.procs)}   •   Démarré depuis {fmt_duration(s.uptime)}")
        page = self.stack.currentWidget()
        if page is not None:
            page.on_tick()

    def _rate(self, i):
        self.sampler.set_interval([500, 1000, 2000, 5000][i])
        self.settings.setValue("rate", i)

    def _toggle_theme(self):
        self.mode = "light" if self.mode == "dark" else "dark"
        self.settings.setValue("theme", self.mode)
        self._apply_theme()

    def _apply_theme(self):
        QApplication.instance().setStyleSheet(stylesheet(self.mode))
        self.theme_btn.setText("Thème clair" if self.mode == "dark" else "Thème sombre")

    def _elevate(self):
        if relaunch_as_admin():
            QApplication.quit()

    # ------------------------------------------------------------ zone de notification
    def _setup_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = QApplication.instance().windowIcon()
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(APP_NAME)
        m = QMenu()
        for label, fn in (("Ouvrir NexTask", self._restore), ("Security", lambda: self._goto(SecurityPage)),
                          ("Rapport de diagnostic", lambda: self._goto(ReportPage)), (None, None),
                          ("Quitter", self._quit)):
            if label is None:
                m.addSeparator()
                continue
            a = QAction(label, m)
            a.triggered.connect(fn)
            m.addAction(a)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: r == QSystemTrayIcon.Trigger and self._restore())
        self._tray_menu = m
        self.tray.show()

    def _restore(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _goto(self, cls):
        self._restore()
        for i, p in enumerate(self.pages):
            if isinstance(p, cls):
                self.side.setCurrentRow(i)

    def _notify(self, kind, detail):
        if self.tray and self.settings.value("ui/notify", True, type=bool):
            self.tray.showMessage(f"{APP_NAME} — {kind}", detail, QSystemTrayIcon.Warning, 8000)

    def _quit(self):
        self._quitting = True
        self.close()

    def closeEvent(self, e):
        if (not self._quitting and self.tray is not None
                and self.settings.value("ui/close_to_tray", False, type=bool)):
            e.ignore()
            self.hide()
            self.tray.showMessage(APP_NAME, "NexTask continue la surveillance en arrière-plan.",
                                  QSystemTrayIcon.Information, 3000)
            return
        self.history.save()
        self.recorder.close()
        if self.tray:
            self.tray.hide()
        super().closeEvent(e)
        QApplication.quit()


def main():
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NexTask.App")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nextask.ico")
    if os.path.exists(ico):
        app.setWindowIcon(QIcon(ico))
    app.setQuitOnLastWindowClosed(False)
    w = MainWindow()
    if "--tray" in sys.argv and w.tray is not None:
        w.hide()
    else:
        w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
