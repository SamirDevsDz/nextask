"""Coque de l'application : barre latérale groupée repliable, barre supérieure, palette de commandes, toasts."""
from PySide6.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup, QPoint, Signal, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QButtonGroup, QScrollArea,
                               QWidget, QDialog, QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QComboBox,
                               QStatusBar, QStyledItemDelegate, QStyle)
from PySide6.QtCore import QRect

from . import design as d
from . import icons
from .widgets import Toast, soft_shadow

SIDEBAR_TEXT = "#b7c1dd"
SIDEBAR_ACTIVE = "#22d3ee"


# ======================================================================= barre latérale
class NavButton(QPushButton):
    def __init__(self, icon_name, label, parent=None):
        super().__init__(label.replace("&", "&&"), parent)
        self.setObjectName("navItem")
        self.icon_name, self.label = icon_name, label
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(18, 18))
        self.setMinimumHeight(32)
        self._refresh_icon()
        self.toggled.connect(lambda _: self._refresh_icon())
        self.badge = QLabel(self)
        self.badge.hide()
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setStyleSheet("background: #f87171; color: #1a0606; border-radius: 8px; font-size: 10px;"
                                 "font-weight: 700; padding: 0 5px;")
        self.setToolTip(label)

    def _refresh_icon(self):
        self.setIcon(icons.icon(self.icon_name, SIDEBAR_ACTIVE if self.isChecked() else SIDEBAR_TEXT, 18))

    def set_badge(self, text):
        if not text:
            self.badge.hide()
            return
        self.badge.setText(str(text))
        self.badge.adjustSize()
        self.badge.setFixedHeight(16)
        self.badge.setMinimumWidth(16)
        self.badge.show()
        self._place_badge()

    def _place_badge(self):
        self.badge.move(self.width() - self.badge.width() - 10, (self.height() - 16) // 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_badge()

    def set_collapsed(self, c):
        self.setText("" if c else self.label.replace("&", "&&"))
        self.setStyleSheet("text-align: center; padding: 8px 0;" if c else "")


class Sidebar(QFrame):
    selected = Signal(int)
    EXPANDED, COLLAPSED = 236, 68

    def __init__(self, groups, footer, parent=None):
        """groups = [(titre, [(icone, libellé), ...]), ...] ; footer = [(icone, libellé)]"""
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.collapsed = False
        self.setFixedWidth(self.EXPANDED)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 12)
        lay.setSpacing(2)

        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 8)
        self.logo = QLabel()
        self.logo.setPixmap(icons.pixmap("logo", SIDEBAR_ACTIVE, 30))
        brand.addWidget(self.logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.brand = QLabel("NexTask", objectName="brand")
        self.brand_sub = QLabel("Console d'administration", objectName="brandSub")
        col.addWidget(self.brand)
        col.addWidget(self.brand_sub)
        brand.addLayout(col)
        brand.addStretch()
        self.toggle = QPushButton(objectName="navToggle")
        self.toggle.setIcon(icons.icon("chev_l", "#8d99bd", 16))
        self.toggle.setToolTip("Replier / déplier le menu (Ctrl+B)")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.clicked.connect(self.toggle_collapsed)
        brand.addWidget(self.toggle)
        lay.addLayout(brand)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
                             "QScrollBar:vertical { width: 6px; } QScrollBar::handle:vertical { background: #1f2b4d; }")
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons, self.group_labels = [], []
        for title, items in groups:
            gl = QLabel(title.upper(), objectName="navGroup")
            self.group_labels.append(gl)
            il.addWidget(gl)
            for icon_name, label in items:
                self._add(il, icon_name, label)
        il.addStretch()
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #16213d;")
        lay.addWidget(sep)
        for icon_name, label in footer:
            self._add(lay, icon_name, label)
        self.status_box = QLabel()
        self.status_box.setWordWrap(True)
        self.status_box.setStyleSheet("color: #8d99bd; font-size: 11px; padding: 6px 8px 0 10px;")
        lay.addWidget(self.status_box)

        self.anim = QParallelAnimationGroup(self)
        for prop in (b"minimumWidth", b"maximumWidth"):
            a = QPropertyAnimation(self, prop)
            a.setDuration(220)
            a.setEasingCurve(QEasingCurve.OutCubic)
            self.anim.addAnimation(a)

    def _add(self, layout, icon_name, label):
        b = NavButton(icon_name, label)
        idx = len(self.buttons)
        self.group.addButton(b, idx)
        b.clicked.connect(lambda _=False, i=idx: self.selected.emit(i))
        layout.addWidget(b)
        self.buttons.append(b)

    def select(self, i, emit=True):
        if 0 <= i < len(self.buttons):
            self.buttons[i].setChecked(True)
            if emit:
                self.selected.emit(i)

    def set_badge(self, i, text):
        if 0 <= i < len(self.buttons):
            self.buttons[i].set_badge(text)

    def set_collapsed(self, c, animate=True):
        self.collapsed = c
        target = self.COLLAPSED if c else self.EXPANDED
        for w in (self.brand, self.brand_sub, self.status_box, *self.group_labels):
            w.setVisible(not c)
        for b in self.buttons:
            b.set_collapsed(c)
        self.toggle.setIcon(icons.icon("chev_r" if c else "chev_l", "#8d99bd", 16))
        if animate:
            for k in range(self.anim.animationCount()):
                a = self.anim.animationAt(k)
                a.setStartValue(self.width())
                a.setEndValue(target)
            self.anim.start()
        else:
            self.setFixedWidth(target)

    def toggle_collapsed(self):
        self.set_collapsed(not self.collapsed)


# ======================================================================= barre supérieure
class TopBar(QFrame):
    palette_requested = Signal()
    theme_requested = Signal()
    elevate_requested = Signal()

    def __init__(self, is_admin, can_elevate, parent=None):
        super().__init__(parent)
        self.setObjectName("topbar")
        self.setFixedHeight(58)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 0, 18, 0)
        lay.setSpacing(10)
        self.crumb = QLabel("", objectName="muted")
        lay.addWidget(self.crumb)
        lay.addStretch()
        self.search = QPushButton("  Rechercher ou exécuter…", objectName="searchBox")
        self.search.setCursor(Qt.PointingHandCursor)
        self.search.clicked.connect(self.palette_requested)
        self.kbd = QLabel("Ctrl K", self.search)
        lay.addWidget(self.search)
        lay.addSpacing(6)
        self.cpu_chip = QLabel()
        self.mem_chip = QLabel()
        for c in (self.cpu_chip, self.mem_chip):
            c.setObjectName("mono")
            lay.addWidget(c)
        self.rate = QComboBox()
        self.rate.addItems(["0,5 s", "1 s", "2 s", "5 s"])
        self.rate.setToolTip("Fréquence de rafraîchissement")
        self.rate.setFixedWidth(78)
        lay.addWidget(self.rate)
        self.theme_btn = QPushButton(objectName="ghost")
        self.theme_btn.setToolTip("Basculer le thème clair / sombre (Ctrl+T)")
        self.theme_btn.setFixedSize(36, 34)
        self.theme_btn.clicked.connect(self.theme_requested)
        lay.addWidget(self.theme_btn)
        self.admin = QPushButton(objectName="chip")
        self.admin.setText(" Administrateur" if is_admin else " Droits limités")
        self.admin_state = is_admin
        self.admin.setToolTip("Session élevée : toutes les fonctions sont disponibles" if is_admin
                              else "Cliquez pour relancer NexTask en administrateur")
        if can_elevate and not is_admin:
            self.admin.setCursor(Qt.PointingHandCursor)
            self.admin.clicked.connect(self.elevate_requested)
        lay.addWidget(self.admin)
        self.refresh_theme()

    def refresh_theme(self):
        self.search.setIcon(icons.icon("search", d.T("muted"), 16))
        self.kbd.setStyleSheet(f"color: {d.T('muted')}; background: {d.T('surface2')}; border: 1px solid {d.T('border')};"
                               "border-radius: 5px; padding: 1px 6px; font-size: 11px;")
        self.kbd.adjustSize()
        self.theme_btn.setIcon(icons.icon("sun" if d.mode() == "dark" else "moon", d.T("text2"), 18))
        col = d.T("ok") if self.admin_state else d.T("warn")
        self.admin.setIcon(icons.icon("shield" if self.admin_state else "admin", col, 16))
        self.admin.setStyleSheet(f"color: {col};")

    def _place_kbd(self):
        self.kbd.move(self.search.width() - self.kbd.width() - 10, (self.search.height() - self.kbd.height()) // 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_kbd()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._place_kbd)

    def set_metrics(self, cpu, mem):
        def chip(lbl, name, v, col):
            sev = d.T("crit") if v >= 90 else d.T("warn") if v >= 75 else col
            lbl.setText(f"<span style='color:{sev}'>●</span> {name} <b>{v:.0f}%</b>")
        chip(self.cpu_chip, "CPU", cpu, d.adapt(d.SERIES["cpu"]).name())
        chip(self.mem_chip, "RAM", mem, d.adapt(d.SERIES["mem"]).name())


class BusyBar(QProgressBar):
    def __init__(self):
        super().__init__()
        self.setObjectName("busy")
        self.setRange(0, 0)
        self.setTextVisible(False)
        self.setFixedHeight(2)
        self.setVisible(False)

    def set_count(self, n):
        self.setVisible(n > 0)


# ======================================================================= palette de commandes
class _PaletteDelegate(QStyledItemDelegate):
    def paint(self, p, opt, idx):
        p.save()
        if opt.state & QStyle.State_Selected:
            p.setRenderHint(p.RenderHint.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(d.qc("sel"))
            p.drawRoundedRect(opt.rect.adjusted(2, 1, -2, -1), 7, 7)
        ic = idx.data(Qt.DecorationRole)
        r = opt.rect
        if ic:
            ic.paint(p, QRect(r.left() + 12, r.center().y() - 9, 18, 18))
        p.setPen(d.qc("text"))
        p.drawText(r.adjusted(42, 0, -120, 0), Qt.AlignVCenter | Qt.AlignLeft, idx.data(Qt.DisplayRole) or "")
        p.setPen(d.qc("muted"))
        p.drawText(r.adjusted(0, 0, -14, 0), Qt.AlignVCenter | Qt.AlignRight, idx.data(Qt.UserRole + 1) or "")
        p.restore()

    def sizeHint(self, opt, idx):
        s = super().sizeHint(opt, idx)
        s.setHeight(38)
        return s


class CommandPalette(QDialog):
    """Palette Ctrl+K : navigation et actions par recherche (flèches + Entrée, Échap pour fermer)."""

    def __init__(self, parent, commands):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Popup)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.commands = commands      # [(icone, libellé, détail, callable)]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        frame = QFrame(objectName="palette")
        soft_shadow(frame, 40, 150)
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(0)
        self.input = QLineEdit(objectName="paletteInput")
        self.input.setPlaceholderText("Aller à une page ou lancer une action…")
        self.input.addAction(icons.icon("search", d.T("muted"), 18), QLineEdit.LeadingPosition)
        self.input.textChanged.connect(self._filter)
        self.input.installEventFilter(self)
        lay.addWidget(self.input)
        self.list = QListWidget(objectName="paletteList")
        self.list.setIconSize(QSize(18, 18))
        self.list.setItemDelegate(_PaletteDelegate(self.list))
        self.list.itemActivated.connect(self._run)
        self.list.itemClicked.connect(self._run)
        lay.addWidget(self.list)
        hint = QLabel("↑ ↓ naviguer   ·   Entrée exécuter   ·   Échap fermer", objectName="muted")
        hint.setContentsMargins(16, 6, 16, 0)
        lay.addWidget(hint)
        self.resize(620, 460)
        self._filter("")

    def _filter(self, text):
        self.list.clear()
        words = text.lower().split()
        for ic, label, detail, fn in self.commands:
            hay = f"{label} {detail}".lower()
            if all(w in hay for w in words):
                it = QListWidgetItem(icons.icon(ic, d.T("text2"), 18), label)
                it.setData(Qt.UserRole, fn)
                it.setData(Qt.UserRole + 1, detail)
                self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, e):
        if obj is self.input and e.type() == e.Type.KeyPress:
            k = e.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                r = self.list.currentRow() + (1 if k == Qt.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(r, self.list.count() - 1)))
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                it = self.list.currentItem()
                if it:
                    self._run(it)
                return True
            if k == Qt.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, e)

    def _run(self, item):
        fn = item.data(Qt.UserRole)
        self.close()
        if fn:
            QTimer.singleShot(0, fn)

    def open_centered(self):
        p = self.parent()
        g = p.geometry()
        self.move(g.center().x() - self.width() // 2, g.top() + 70)
        self.input.clear()
        self._filter("")
        self.show()
        self.input.setFocus()


# ======================================================================= hôte des toasts
class Central(QWidget):
    def __init__(self):
        super().__init__(objectName="central")
        self._toasts = []

    def toast(self, text, level="INFO", ms=3500):
        t = Toast(self, text, level, ms)
        t.show()
        self._toasts.append(t)
        self._layout_toasts(new=t)

    def _layout_toasts(self, new=None):
        y = self.height() - 20
        for t in reversed(self._toasts):
            y -= t.height()
            target = QPoint(self.width() - t.width() - 22, y)
            if t is new:
                t.move(target + QPoint(0, 30))
                t.anim.setStartValue(t.pos())
                t.anim.setEndValue(target)
                t.anim.start()
            else:
                t.move(target)
            y -= 10

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_toasts()


def guess_level(text):
    t = text.lower()
    if any(w in t for w in ("erreur", "échec", "refusé", "impossible")):
        return "CRITIQUE"
    if any(w in t for w in ("attention", "en cours", "…")):
        return "INFO"
    if any(w in t for w in ("terminé", "enregistr", "copié", "appliqué", "repris", "suspendu", "ok", "envoyé")):
        return "OK"
    return "INFO"


class ToastStatusBar(QStatusBar):
    """Barre d'état fine ; showMessage() (utilisé par toutes les pages) devient un toast."""

    def __init__(self, central):
        super().__init__()
        self.central = central

    def showMessage(self, text, timeout=0):  # noqa: N802 (API Qt)
        if text:
            self.central.toast(text, guess_level(text), max(2500, min(timeout or 3500, 8000)))


def shortcut(parent, keys, fn):
    s = QShortcut(QKeySequence(keys), parent)
    s.activated.connect(fn)
    return s
