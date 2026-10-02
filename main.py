"""NexTask — console d'administration et de supervision Windows (Python + PySide6).

Lancer :  python main.py        (idéalement en administrateur sous Windows)
Raccourcis : Ctrl+K palette · Ctrl+B menu · Ctrl+1…9 pages · Ctrl+T thème · F5 actualiser
"""
import os
import sys

from PySide6.QtCore import QSettings, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import (QApplication, QMainWindow, QHBoxLayout, QVBoxLayout, QStackedWidget, QLabel,
                               QSystemTrayIcon, QMenu, QStyle, QGraphicsOpacityEffect, QWidget)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import design  # noqa: E402
from core.common import APP_NAME, IS_WIN, is_admin, relaunch_as_admin, fmt_duration, tracker  # noqa: E402
from core.sampler import Sampler  # noqa: E402
from core.shell import (Sidebar, TopBar, BusyBar, CommandPalette, Central, ToastStatusBar, shortcut)  # noqa: E402
from core.theme import stylesheet  # noqa: E402
from core.widgets import IconChip  # noqa: E402
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

# Architecture de l'information : 5 groupes métier + paramètres en pied de menu
NAV = [
    ("Surveillance", [
        ("grid", "Vue d'ensemble", SummaryPage),
        ("activity", "Performance", PerformancePage),
        ("list", "Processus", ProcessesPage),
        ("zap", "Énergie & fréquence", PowerPage),
        ("record", "Enregistreur", FlightRecorderPage),
        ("history", "Historique des apps", AppHistoryPage),
    ]),
    ("Système", [
        ("info", "Infos système", SysInfoPage),
        ("play", "Démarrage", StartupPage),
        ("sliders", "Services", ServicesPage),
        ("chip", "Pilotes", DriversPage),
        ("package", "Logiciels", InstalledAppsPage),
        ("drive", "Espace disque", DiskSpacePage),
        ("users", "Utilisateurs", UsersPage),
    ]),
    ("Réseau", [
        ("globe", "Connexions", ConnectionsPage),
        ("radar", "Outils réseau", NetworkToolsPage),
    ]),
    ("Sécurité", [
        ("shield", "Sécurité", SecurityPage),
        ("layers", "Référence (baseline)", BaselinePage),
        ("key", "Identité & partages", IdentityPage),
    ]),
    ("Opérations", [
        ("wrench", "Dépannage", ToolboxPage),
        ("file", "Rapport de diagnostic", ReportPage),
    ]),
]
FOOTER = [("gear", "Paramètres", SettingsPage)]
RATES = [500, 1000, 2000, 5000]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(APP_NAME, APP_NAME)
        self.setWindowTitle(f"{APP_NAME} — Console d'administration" + ("  [Administrateur]" if is_admin() else ""))
        self.resize(1400, 860)
        self.setMinimumSize(1080, 680)
        self.mode = self.settings.value("theme", "dark")
        design.set_mode(self.mode)

        self.sampler = Sampler(self)
        self.history = AppHistoryTracker(self.sampler)
        self.recorder = Recorder(self.sampler)

        # --- structure : [sidebar | (topbar, busy, pages)]
        self.central = Central()
        self.setCentralWidget(self.central)
        h = QHBoxLayout(self.central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        entries = [(g, ic, label, cls) for g, items in NAV for ic, label, cls in items]
        entries += [("", ic, label, cls) for ic, label, cls in FOOTER]
        self.entries = entries
        self.nav = Sidebar([(g, [(ic, lb) for ic, lb, _ in items]) for g, items in NAV],
                           [(ic, lb) for ic, lb, _ in FOOTER])
        h.addWidget(self.nav)
        right = QWidget()
        v = QVBoxLayout(right)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.top = TopBar(is_admin(), IS_WIN)
        v.addWidget(self.top)
        self.busy = BusyBar()
        v.addWidget(self.busy)
        self.stack = QStackedWidget(objectName="pages")
        v.addWidget(self.stack, 1)
        h.addWidget(right, 1)

        self.pages = []
        for group, ic, label, cls in entries:
            kwargs = {}
            if cls is AppHistoryPage:
                kwargs["tracker"] = self.history
            if cls in (FlightRecorderPage, ReportPage):
                kwargs["recorder"] = self.recorder
            page = cls(self.sampler, **kwargs)
            page.set_heading(label)
            self.stack.addWidget(page)
            self.pages.append(page)
        self.nav.selected.connect(self._switch)
        self.nav.set_collapsed(self.settings.value("ui/collapsed", False, type=bool), animate=False)

        # --- barre d'état fine (les messages des pages deviennent des toasts)
        sb = ToastStatusBar(self.central)
        self.setStatusBar(sb)
        self.lbl = QLabel("")
        sb.addWidget(self.lbl, 1)
        self.ver = QLabel(f"{APP_NAME} · v3")
        sb.addPermanentWidget(self.ver)

        # --- barre supérieure
        self.top.rate.setCurrentIndex(int(self.settings.value("rate", 1)))
        self.top.rate.currentIndexChanged.connect(self._rate)
        self.top.theme_requested.connect(self._toggle_theme)
        self.top.elevate_requested.connect(self._elevate)
        self.top.palette_requested.connect(self.open_palette)
        tracker.changed.connect(self.busy.set_count)

        # --- raccourcis clavier
        shortcut(self, "Ctrl+K", self.open_palette)
        shortcut(self, "Ctrl+B", self._toggle_nav)
        shortcut(self, "Ctrl+T", self._toggle_theme)
        shortcut(self, "F5", lambda: self.stack.currentWidget().on_show())
        for n in range(1, 10):
            shortcut(self, f"Ctrl+{n}", lambda n=n: self.nav.select(n - 1))

        self._apply_theme()
        self._setup_tray()
        self.recorder.event.connect(self._notify)
        self._events = 0
        self._quitting = False
        self.sampler.updated.connect(self._tick)
        self.sampler.start(RATES[self.top.rate.currentIndex()])
        start = str(self.settings.value("page_label", "Vue d'ensemble"))
        idx = next((i for i, e in enumerate(entries) if e[2] == start), 0)
        self.nav.select(idx)

    # ------------------------------------------------------------ navigation
    def _switch(self, i):
        if not 0 <= i < len(self.pages):
            return
        if getattr(self, "_cur", None) == i and self.stack.currentIndex() == i:
            self.nav.select(i, emit=False)
            return
        page = self.pages[i]
        group, _, label, _ = self.entries[i]
        self.nav.select(i, emit=False)
        self._cur = i
        self._update_crumb()
        self.stack.setCurrentWidget(page)
        self.settings.setValue("page_label", label)
        if label == "Enregistreur":
            self._events = 0
            self.nav.set_badge(i, "")
        self._fade(page)
        page.on_show()

    def _update_crumb(self):
        group, _, label, _ = self.entries[self._cur]
        strong = f"<span style='color:{design.T('text')}; font-weight:600'>{label}</span>"
        self.top.crumb.setText(f"{group}  <span style='color:{design.T('faint')}'>/</span>  {strong}" if group else strong)

    def _fade(self, w):
        old = getattr(self, "_fade_anim", None)
        if old is not None:
            old.stop()
            tgt = old.property("page")
            if tgt is not None:
                tgt.setGraphicsEffect(None)
        eff = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(eff)
        a = QPropertyAnimation(eff, b"opacity", w)
        a.setProperty("page", w)
        a.setDuration(170)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.finished.connect(lambda: w.graphicsEffect() is eff and w.setGraphicsEffect(None))
        a.start()
        self._fade_anim = a

    def goto_cls(self, cls):
        for i, p in enumerate(self.pages):
            if isinstance(p, cls):
                self.nav.select(i)
                return p

    def open_palette(self):
        cmds = [(ic, label, group or "Paramètres", (lambda i=i: self.nav.select(i)))
                for i, (group, ic, label, _) in enumerate(self.entries)]

        def run_page(cls, method):
            def go():
                p = self.goto_cls(cls)
                getattr(p, method)()
            return go
        cmds += [
            ("shield", "Lancer le bilan de sécurité", "Action", run_page(SecurityPage, "run_posture")),
            ("shield", "Rechercher les processus suspects", "Action", run_page(SecurityPage, "run_procs")),
            ("shield", "Détecter les outils d'accès à distance", "Action", run_page(SecurityPage, "run_remote")),
            ("shield", "Analyser la persistance", "Action", run_page(SecurityPage, "run_persist")),
            ("file", "Générer un rapport de diagnostic", "Action", run_page(ReportPage, "generate")),
            ("layers", "Comparer à la dernière référence", "Action", run_page(BaselinePage, "_compare")),
            ("wrench", "Ouvrir le journal d'audit", "Action", lambda: (self.goto_cls(ToolboxPage).tabs_audit())),
            ("sun" if self.mode == "dark" else "moon", "Basculer le thème", "Ctrl+T", self._toggle_theme),
            ("menu", "Replier / déplier le menu", "Ctrl+B", self._toggle_nav),
        ]
        if IS_WIN and not is_admin():
            cmds.append(("admin", "Relancer en administrateur", "Action", self._elevate))
        self._palette = CommandPalette(self, cmds)
        self._palette.open_centered()

    def _toggle_nav(self):
        self.nav.toggle_collapsed()
        self.settings.setValue("ui/collapsed", self.nav.collapsed)

    # ------------------------------------------------------------ rafraîchissement
    def _tick(self):
        s = self.sampler
        self.top.set_metrics(s.cpu, s.vm.percent)
        self.lbl.setText(f"{len(s.procs)} processus   ·   démarré depuis {fmt_duration(s.uptime)}   ·   "
                         f"↓ {s.net_down / 1024:.0f} Ko/s  ↑ {s.net_up / 1024:.0f} Ko/s")
        self.nav.status_box.setText(f"<span style='color:{'#34d399' if is_admin() else '#fbbf24'}'>●</span> "
                                    f"{'Session administrateur' if is_admin() else 'Droits limités'}<br>"
                                    f"Surveillance active · {RATES[self.top.rate.currentIndex()] / 1000:g} s")
        page = self.stack.currentWidget()
        if page is not None:
            page.on_tick()

    def _rate(self, i):
        self.sampler.set_interval(RATES[i])
        self.settings.setValue("rate", i)

    def _toggle_theme(self):
        self.mode = "light" if self.mode == "dark" else "dark"
        self.settings.setValue("theme", self.mode)
        self._apply_theme()
        self.central.toast(f"Thème {'clair' if self.mode == 'light' else 'sombre'} activé", "OK", 2000)

    def _apply_theme(self):
        QApplication.instance().setStyleSheet(stylesheet(self.mode))
        self.top.refresh_theme()
        for chip in self.findChildren(IconChip):
            chip.refresh()
        if hasattr(self, "_cur"):
            self._update_crumb()
        self.update()

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
        for label, fn in (("Ouvrir NexTask", self._restore), ("Sécurité", lambda: self._goto(SecurityPage)),
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
        self.goto_cls(cls)

    def _notify(self, kind, detail):
        self._events += 1
        idx = next(i for i, e in enumerate(self.entries) if e[3] is FlightRecorderPage)
        self.nav.set_badge(idx, self._events)
        self.central.toast(f"{kind} — {detail}", "ALERTE", 6000)
        if self.tray and self.settings.value("ui/notify", True, type=bool) and not self.isActiveWindow():
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
