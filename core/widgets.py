"""Composants visuels NexTask : graphes lissés, jauges, tuiles KPI, tableaux enrichis, page de base, toasts."""
import csv

from PySide6.QtCore import (Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QPointF, QRectF,
                            QVariantAnimation, QEasingCurve, QTimer, QPropertyAnimation)
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QAction, QGuiApplication, QLinearGradient,
                           QFont, QFontMetrics, QBrush, QConicalGradient)
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTableView, QPushButton,
                               QHeaderView, QAbstractItemView, QMenu, QFileDialog, QFrame, QProgressBar,
                               QStyledItemDelegate, QStyle, QGraphicsDropShadowEffect,
                               QStyleOptionViewItem)

from . import design as d
from . import icons

SERIES = d.SERIES
COLORS = SERIES                       # compatibilité V1/V2
ACCENT = SERIES["cpu"]
# Couleurs « moyennes » des sévérités : le délégué de pastilles les adapte au thème
STATUS_COLORS = {"OK": "#10b981", "INFO": "#3b82f6", "ALERTE": "#f59e0b", "CRITIQUE": "#ef4444"}
_STATUS_BY_COLOR = {v.lower(): k for k, v in STATUS_COLORS.items()}


def _smooth_path(pts):
    """Courbe Catmull-Rom → Bézier passant par tous les points."""
    path = QPainterPath(pts[0])
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else p2
        c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6, p1.y() + (p2.y() - p0.y()) / 6)
        c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6, p2.y() - (p3.y() - p1.y()) / 6)
        path.cubicTo(c1, c2, p2)
    return path


# ======================================================================= graphe
class LineGraph(QWidget):
    """Graphe temps réel : courbe lissée, dégradé, halo, survol avec valeur."""

    def __init__(self, color=ACCENT, max_value=100.0, auto_scale=False, points=60,
                 color2=None, parent=None, value_fmt=None, frame=True):
        super().__init__(parent)
        self.color = QColor(color)
        self.color2 = QColor(color2) if color2 else None
        self.max_value = max_value
        self.auto_scale = auto_scale
        self.points = points
        self.series, self.series2 = [], []
        self.caption = ""
        self.frame = frame
        self.value_fmt = value_fmt or (lambda v: f"{v:.0f} %" if not self.auto_scale else f"{v:.1f}")
        self._hover = None
        self.setMouseTracking(True)
        self.setMinimumHeight(48)

    def set_data(self, values, values2=None, caption=""):
        self.series = list(values)[-self.points:]
        self.series2 = list(values2)[-self.points:] if values2 is not None else []
        self.caption = caption
        self.update()

    def _scale(self):
        if not self.auto_scale:
            return self.max_value or 1
        return max([1.0] + self.series + self.series2) * 1.18

    def _plot_rect(self):
        return QRectF(self.rect()).adjusted(1, 1, -1, -1)

    def mouseMoveEvent(self, e):
        self._hover = e.position().x()
        self.update()

    def leaveEvent(self, _):
        self._hover = None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot_rect()
        if self.frame:
            p.setPen(QPen(d.qc("border"), 1))
            p.setBrush(d.qc("surface2", 90))
            p.drawRoundedRect(r, 8, 8)
        p.setPen(QPen(d.qc("grid"), 1, Qt.DashLine))
        for i in range(1, 4):
            y = r.top() + r.height() * i / 4
            p.drawLine(QPointF(r.left() + 6, y), QPointF(r.right() - 6, y))
        scale = self._scale()
        step = r.width() / max(self.points - 1, 1)
        hover_vals = []
        for data, base in ((self.series2, self.color2), (self.series, self.color)):
            if len(data) < 2 or base is None:
                continue
            col = d.adapt(base.name())
            x0 = r.right() - step * (len(data) - 1)
            pts = [QPointF(x0 + i * step, r.bottom() - 2 - min(max(v, 0) / scale, 1.0) * (r.height() - 6))
                   for i, v in enumerate(data)]
            line = _smooth_path(pts)
            fill = QPainterPath(line)
            fill.lineTo(QPointF(pts[-1].x(), r.bottom()))
            fill.lineTo(QPointF(pts[0].x(), r.bottom()))
            fill.closeSubpath()
            g = QLinearGradient(0, r.top(), 0, r.bottom())
            top = QColor(col)
            top.setAlpha(110 if d.mode() == "dark" else 70)
            bot = QColor(col)
            bot.setAlpha(0)
            g.setColorAt(0, top)
            g.setColorAt(1, bot)
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(r, 8, 8)
            p.setClipPath(clip)
            p.fillPath(fill, g)
            glow = QColor(col)
            glow.setAlpha(55)
            p.setPen(QPen(glow, 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(line)
            p.setPen(QPen(col, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(line)
            p.restore()
            # point courant
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(pts[-1], 3, 3)
            if self._hover is not None:
                i = round((self._hover - x0) / step)
                if 0 <= i < len(data):
                    hover_vals.append((pts[i], data[i], col))
        if hover_vals:
            x = hover_vals[0][0].x()
            p.setPen(QPen(d.qc("muted", 160), 1, Qt.DashLine))
            p.drawLine(QPointF(x, r.top() + 4), QPointF(x, r.bottom() - 4))
            text = "   ".join(self.value_fmt(v) for _, v, _ in reversed(hover_vals))
            for pt, _, col in hover_vals:
                p.setPen(QPen(d.qc("surface"), 2))
                p.setBrush(col)
                p.drawEllipse(pt, 4.5, 4.5)
            fm = QFontMetrics(self.font())
            w = fm.horizontalAdvance(text) + 16
            bx = min(max(x - w / 2, r.left() + 4), r.right() - w - 4)
            box = QRectF(bx, r.top() + 6, w, fm.height() + 8)
            p.setPen(QPen(d.qc("border_strong"), 1))
            p.setBrush(d.qc("elevated"))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(d.qc("text"))
            p.drawText(box, Qt.AlignCenter, text)
        elif self.caption:
            p.setPen(d.qc("muted"))
            f = QFont(self.font())
            f.setPointSizeF(max(f.pointSizeF() - 1, 7))
            p.setFont(f)
            p.drawText(r.adjusted(10, 6, -10, -6), Qt.AlignTop | Qt.AlignRight, self.caption)
        p.end()


# ======================================================================= jauge circulaire
class RingGauge(QWidget):
    """Jauge circulaire animée (0-100) avec valeur centrale et libellé."""

    def __init__(self, label="", color=ACCENT, size=120, thickness=10, parent=None, suffix="%"):
        super().__init__(parent)
        self.label, self.color, self.thickness, self.suffix = label, QColor(color), thickness, suffix
        self.setFixedSize(size, size)
        self._value = 0.0
        self.text_override = None
        self.anim = QVariantAnimation(self, duration=600, easingCurve=QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._step)

    def _step(self, v):
        self._value = float(v)
        self.update()

    def set_value(self, v, color=None, text=None):
        if color:
            self.color = QColor(color)
        self.text_override = text
        self.anim.stop()
        self.anim.setStartValue(self._value)
        self.anim.setEndValue(float(max(0, min(v, 100))))
        self.anim.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.thickness
        r = QRectF(t / 2 + 2, t / 2 + 2, self.width() - t - 4, self.height() - t - 4)
        p.setPen(QPen(d.qc("border"), t, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, 0, 360 * 16)
        col = d.adapt(self.color.name())
        g = QConicalGradient(r.center(), 90)
        g.setColorAt(0, col)
        g.setColorAt(1, col.lighter(140) if d.mode() == "dark" else col.darker(120))
        span = -int(360 * 16 * self._value / 100)
        glow = QColor(col)
        glow.setAlpha(45)
        p.setPen(QPen(glow, t + 6, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, 90 * 16, span)
        p.setPen(QPen(QBrush(g), t, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, 90 * 16, span)
        p.setPen(d.qc("text"))
        f = QFont(self.font())
        f.setPixelSize(int(self.height() * 0.22))
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        txt = self.text_override if self.text_override is not None else f"{self._value:.0f}{self.suffix}"
        p.drawText(r.adjusted(0, -8, 0, -8), Qt.AlignCenter, txt)
        if self.label:
            f2 = QFont(self.font())
            f2.setPixelSize(max(10, int(self.height() * 0.095)))
            p.setFont(f2)
            p.setPen(d.qc("muted"))
            p.drawText(r.adjusted(0, int(self.height() * 0.24), 0, 0), Qt.AlignCenter, self.label)
        p.end()


# ======================================================================= tuile KPI
class IconChip(QLabel):
    def __init__(self, name, color, size=34):
        super().__init__()
        self.name, self.col, self.sz = name, color, size
        self.setFixedSize(size, size)
        self.refresh()

    def refresh(self):
        col = d.adapt(self.col)
        bg = QColor(col)
        bg.setAlpha(38)
        self.setStyleSheet(f"background: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()});"
                           f"border-radius: {self.sz // 3}px;")
        self.setPixmap(icons.pixmap(self.name, col.name(), int(self.sz * 0.55)))
        self.setAlignment(Qt.AlignCenter)


class StatTile(QFrame):
    """Tuile KPI : pastille d'icône, libellé, grande valeur, détail, sparkline."""

    def __init__(self, title, color=ACCENT, max_value=100, auto_scale=False, parent=None, icon="activity",
                 value_fmt=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.accent = color
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.chip = IconChip(icon, color)
        top.addWidget(self.chip)
        self.title = QLabel(title.upper())
        self.title.setObjectName("kpiLabel")
        top.addWidget(self.title)
        top.addStretch()
        lay.addLayout(top)
        self.value = QLabel("—")
        self.value.setObjectName("kpiValue")
        lay.addSpacing(4)
        lay.addWidget(self.value)
        self.sub = QLabel("")
        self.sub.setObjectName("muted")
        lay.addWidget(self.sub)
        self.graph = LineGraph(color, max_value, auto_scale, frame=False, value_fmt=value_fmt)
        self.graph.setFixedHeight(56)
        lay.addWidget(self.graph)

    def set(self, value, sub="", series=None, series2=None):
        self.value.setText(value)
        self.sub.setText(sub)
        if series is not None:
            self.graph.set_data(series, series2)


class UsageBar(QWidget):
    """Libellé + barre de progression (disques, etc.)."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(5)
        head = QHBoxLayout()
        self.label = QLabel(label)
        self.label.setStyleSheet("font-weight: 600;")
        self.pct = QLabel("")
        self.pct.setObjectName("muted")
        head.addWidget(self.label)
        head.addStretch()
        head.addWidget(self.pct)
        lay.addLayout(head)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.detail = QLabel("")
        self.detail.setObjectName("muted")
        lay.addWidget(self.bar)
        lay.addWidget(self.detail)

    def set(self, pct, detail):
        self.bar.setValue(int(pct))
        self.pct.setText(f"{pct:.0f} %")
        self.bar.setProperty("level", "high" if pct >= 90 else "mid" if pct >= 75 else "ok")
        self.bar.style().unpolish(self.bar)
        self.bar.style().polish(self.bar)
        self.detail.setText(detail)


# ======================================================================= tableau
class TableModel(QAbstractTableModel):
    """Cellule = valeur simple ou tuple (texte affiché, clé de tri[, couleur])."""

    def __init__(self, headers):
        super().__init__()
        self.headers = headers
        self.rows = []
        self.align_right = set()
        self.bar_cols = {}      # colonne -> max (None = max de la colonne)
        self._bar_max = {}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def _key(self, cell):
        key = cell[1] if isinstance(cell, tuple) else cell
        if key is None:
            return -1
        return key if isinstance(key, (int, float)) else str(key).lower()

    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid():
            return None
        cell = self.rows[idx.row()][idx.column()]
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return str(cell[0]) if isinstance(cell, tuple) else ("" if cell is None else str(cell))
        if role == Qt.UserRole:
            return self._key(cell)
        if role == Qt.UserRole + 1 and isinstance(cell, tuple) and len(cell) > 2 and cell[2]:
            return cell[2]            # couleur → pastille
        if role == Qt.UserRole + 2 and idx.column() in self.bar_cols:
            k = self._key(cell)
            m = self._bar_max.get(idx.column()) or 1
            return max(0.0, min(float(k) / m, 1.0)) if isinstance(k, (int, float)) else None
        if role == Qt.TextAlignmentRole and idx.column() in self.align_right:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal and section < len(self.headers):
            return self.headers[section]
        return None

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        for c, mx in self.bar_cols.items():
            if mx:
                self._bar_max[c] = mx
            else:
                vals = [self._key(r[c]) for r in rows if c < len(r)]
                vals = [v for v in vals if isinstance(v, (int, float))]
                self._bar_max[c] = max(vals) if vals else 1
        self.endResetModel()


class RichDelegate(QStyledItemDelegate):
    """Pastilles de sévérité colorées (texte + couleur) et mini-barres de valeur."""

    def paint(self, p, opt, idx):
        color = idx.data(Qt.UserRole + 1)
        bar = idx.data(Qt.UserRole + 2)
        if not color and bar is None:
            return super().paint(p, opt, idx)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if opt.state & QStyle.State_Selected:
            p.fillRect(opt.rect, d.qc("sel"))
        elif opt.state & QStyle.State_MouseOver:
            p.fillRect(opt.rect, d.qc("hover"))
        elif opt.features & QStyleOptionViewItem.ViewItemFeature.Alternate:
            p.fillRect(opt.rect, d.qc("surface2"))
        text = str(idx.data(Qt.DisplayRole) or "")
        if bar is not None:
            col = d.adapt(SERIES["cpu"])
            track = QRectF(opt.rect).adjusted(6, opt.rect.height() - 7, -6, -3)
            p.setPen(Qt.NoPen)
            p.setBrush(d.qc("surface2" if not (opt.state & QStyle.State_Selected) else "border"))
            p.drawRoundedRect(track, 2, 2)
            fillc = QColor(col)
            if bar > 0.8:
                fillc = QColor(d.T("crit"))
            elif bar > 0.5:
                fillc = QColor(d.T("warn"))
            if bar > 0.004:
                p.setBrush(fillc)
                p.drawRoundedRect(QRectF(track.left(), track.top(), max(track.width() * bar, 3), track.height()), 2, 2)
            p.setPen(d.qc("text"))
            align = idx.data(Qt.TextAlignmentRole) or int(Qt.AlignLeft | Qt.AlignVCenter)
            p.drawText(QRectF(opt.rect).adjusted(8, 0, -8, -6), int(align), text)
        else:
            sev = _STATUS_BY_COLOR.get(str(color).lower())
            c = QColor(d.severity_color(sev)) if sev else d.adapt(str(color))
            fm = QFontMetrics(opt.font)
            w = fm.horizontalAdvance(text) + 20
            h = min(opt.rect.height() - 6, 20)
            pill = QRectF(opt.rect.left() + 6, opt.rect.center().y() - h / 2 + 0.5, min(w, opt.rect.width() - 12), h)
            bg = QColor(c)
            bg.setAlpha(40 if d.mode() == "dark" else 28)
            p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 90), 1))
            p.setBrush(bg)
            p.drawRoundedRect(pill, h / 2, h / 2)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(pill.left() + 9, pill.center().y()), 2.6, 2.6)
            f = QFont(opt.font)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            p.setPen(c)
            p.drawText(pill.adjusted(15, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(text, Qt.ElideRight, int(pill.width() - 18)))
        p.restore()


class _Proxy(QSortFilterProxyModel):
    def lessThan(self, a, b):
        x, y = a.data(Qt.UserRole), b.data(Qt.UserRole)
        try:
            return x < y
        except TypeError:
            return str(x) < str(y)


class _EmptyAwareView(QTableView):
    """QTableView qui affiche un état vide explicite plutôt qu'une zone blanche."""
    empty_text = "Aucun élément à afficher"

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.model() is not None and self.model().rowCount() == 0:
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.Antialiasing)
            r = self.viewport().rect()
            pm = icons.pixmap("list", d.T("faint"), 34)
            p.drawPixmap(int(r.center().x() - 17), int(r.center().y() - 40), pm)
            p.setPen(d.qc("muted"))
            p.drawText(r.adjusted(20, 20, -20, 0), Qt.AlignCenter, self.empty_text)
            p.end()


class TablePanel(QWidget):
    """Recherche + boutons + tableau triable + menu contextuel + export CSV."""

    def __init__(self, headers, key_col=0, right_cols=(), parent=None):
        super().__init__(parent)
        self.key_col = key_col
        self.model = TableModel(headers)
        self.model.align_right = set(right_cols)
        self.proxy = _Proxy()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setSortRole(Qt.UserRole)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.toolbar = QHBoxLayout()
        self.toolbar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrer…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(300)
        self.search.addAction(icons.icon("search", d.T("muted"), 16), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._filter)
        self.toolbar.addWidget(self.search)
        self.toolbar.addStretch()
        lay.addLayout(self.toolbar)

        self.view = _EmptyAwareView()
        self.view.setModel(self.proxy)
        self.view.setItemDelegate(RichDelegate(self.view))
        self.view.setSortingEnabled(True)
        self.view.setMouseTracking(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(32)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setWordWrap(False)
        self.view.setFrameShape(QFrame.NoFrame)
        h = self.view.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setStretchLastSection(True)
        h.setDefaultSectionSize(130)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setHighlightSections(False)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.view)

        self.status = QLabel("")
        self.status.setObjectName("muted")
        lay.addWidget(self.status)
        self._ctx = []
        self._sel_buttons = []
        self.view.selectionModel().selectionChanged.connect(self._sel_changed)
        self._export_btn = self.add_button("Exporter CSV", self.export_csv, ghost=True)
        self.proxy.sort(-1)
        h.setSortIndicator(-1, Qt.AscendingOrder)

    def _filter(self, text):
        self.proxy.setFilterFixedString(text)
        self.status.setText(f"{self.proxy.rowCount()} élément(s)" + (f" — filtre « {text} »" if text else ""))

    def make_compact(self):
        """Version minimale : sans recherche, export ni tri (ordre fourni conservé)."""
        self.search.hide()
        self._export_btn.hide()
        self.view.setSortingEnabled(False)
        self.proxy.sort(-1)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.view.horizontalHeader().setStretchLastSection(False)

    def set_empty_text(self, text):
        self.view.empty_text = text
        self.view.viewport().update()

    def set_bar_columns(self, cols):
        """{colonne: max} — affiche une mini-barre proportionnelle (max None = max de la colonne)."""
        self.model.bar_cols = dict(cols)

    # -- API
    def add_button(self, label, callback, needs_selection=False, danger=False, ghost=False, icon=None):
        b = QPushButton(label)
        if danger:
            b.setObjectName("danger")
        elif ghost:
            b.setObjectName("ghost")
        if icon:
            b.setIcon(icons.icon(icon, d.T("text2"), 16))
        if needs_selection:
            b.clicked.connect(lambda: (r := self.selected_row()) is not None and callback(r))
            b.setEnabled(False)
            self._sel_buttons.append(b)
        else:
            b.clicked.connect(callback)
        self.toolbar.addWidget(b)
        return b

    def add_context(self, label, callback):
        self._ctx.append((label, callback))

    def set_widths(self, widths):
        for i, w in enumerate(widths):
            self.view.setColumnWidth(i, w)

    def set_rows(self, rows):
        sel = self.selected_row()
        sel_key = sel[self.key_col] if sel else None
        sb = self.view.verticalScrollBar().value()
        self.model.set_rows(rows)
        if sel_key is not None:
            for r, row in enumerate(rows):
                if row[self.key_col] == sel_key or (isinstance(row[self.key_col], tuple) and row[self.key_col][0] == sel_key):
                    pidx = self.proxy.mapFromSource(self.model.index(r, 0))
                    if pidx.isValid():
                        self.view.selectRow(pidx.row())
                    break
        self.view.verticalScrollBar().setValue(sb)
        txt = self.search.text()
        self.status.setText(f"{self.proxy.rowCount()} élément(s)" + (f" — filtre « {txt} »" if txt else ""))
        self._sel_changed()

    def sort_by(self, col, desc=True):
        self.view.sortByColumn(col, Qt.DescendingOrder if desc else Qt.AscendingOrder)

    def selected_row(self):
        idx = self.view.selectionModel().selectedRows()
        if not idx:
            return None
        src = self.proxy.mapToSource(idx[0])
        if 0 <= src.row() < len(self.model.rows):
            return [c[0] if isinstance(c, tuple) else c for c in self.model.rows[src.row()]]
        return None

    def raw_selected(self):
        idx = self.view.selectionModel().selectedRows()
        if not idx:
            return None
        return self.model.rows[self.proxy.mapToSource(idx[0]).row()]

    # -- interne
    def _sel_changed(self, *_):
        has = self.selected_row() is not None
        for b in self._sel_buttons:
            b.setEnabled(has)

    def _menu(self, pos):
        row = self.selected_row()
        if row is None:
            return
        m = QMenu(self)
        for label, cb in self._ctx:
            if label == "-":
                m.addSeparator()
                continue
            a = QAction(label, m)
            a.triggered.connect(lambda _=False, c=cb: c(row))
            m.addAction(a)
        m.addSeparator()
        cp = QAction("Copier la ligne", m)
        cp.triggered.connect(lambda: QGuiApplication.clipboard().setText("\t".join(map(str, row))))
        m.addAction(cp)
        m.exec(self.view.viewport().mapToGlobal(pos))

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Exporter", "export.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(self.model.headers)
            for r in range(self.proxy.rowCount()):
                w.writerow([self.proxy.index(r, c).data() for c in range(self.model.columnCount())])


# ======================================================================= page
class Page(QWidget):
    title = "Page"
    subtitle = ""

    def __init__(self, sampler, parent=None):
        super().__init__(parent)
        self.sampler = sampler
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(28, 22, 28, 18)
        self.root.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(2)
        self._title_lbl = QLabel(self.title)
        self._title_lbl.setObjectName("pageTitle")
        self._sub_lbl = QLabel(self.subtitle)
        self._sub_lbl.setObjectName("pageSubtitle")
        self._sub_lbl.setVisible(bool(self.subtitle))
        col.addWidget(self._title_lbl)
        col.addWidget(self._sub_lbl)
        head.addLayout(col)
        head.addStretch()
        self.header_actions = head
        self.root.addLayout(head)

    def set_heading(self, title, subtitle=None):
        self._title_lbl.setText(title)
        if subtitle is not None:
            self._sub_lbl.setText(subtitle)
            self._sub_lbl.setVisible(bool(subtitle))

    def on_show(self):
        """Appelé quand la page devient visible."""

    def on_tick(self):
        """Appelé chaque seconde quand la page est visible."""


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setObjectName("sep")
    return f


def card(layout_cls=QVBoxLayout, margins=(18, 16, 18, 16), name="card"):
    """Carte prête à l'emploi : renvoie (frame, layout)."""
    f = QFrame(objectName=name)
    lay = layout_cls(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(10)
    return f, lay


def soft_shadow(widget, blur=28, alpha=90):
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, 8)
    eff.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)


class AlertList(QWidget):
    """Liste d'alertes avec pastille de sévérité (couleur + libellé, jamais la couleur seule)."""

    def __init__(self):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(6)
        self._sig = None

    def set_items(self, items):
        sig = (d.mode(), tuple(items))
        if sig == self._sig:
            return
        self._sig = sig
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not items:
            items = [("OK", "Aucun problème détecté")]
        for level, text in items[:7]:
            row = QFrame()
            col = d.severity_color(level)
            row.setStyleSheet(f"QFrame {{ background: {d.T('surface2')}; border: 1px solid {d.T('border')};"
                              f"border-left: 3px solid {col}; border-radius: 8px; }}")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 7, 10, 7)
            pill = QLabel(level)
            pill.setStyleSheet(f"color: {col}; font-weight: 700; font-size: 10.5px; letter-spacing: .5px;"
                               "border: none; background: transparent;")
            pill.setFixedWidth(64)
            txt = QLabel(text)
            txt.setWordWrap(True)
            txt.setStyleSheet("border: none; background: transparent;")
            h.addWidget(pill)
            h.addWidget(txt, 1)
            self.lay.addWidget(row)
        self.lay.addStretch()


# ======================================================================= toasts
class Toast(QFrame):
    """Notification éphémère en bas à droite (succès / info / alerte / erreur)."""

    LEVEL_ICON = {"OK": "check", "INFO": "info", "ALERTE": "alert", "CRITIQUE": "alert"}

    def __init__(self, host, text, level="INFO", ms=3500):
        super().__init__(host)
        self.setObjectName("toast")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 14, 10)
        lay.setSpacing(10)
        col = d.severity_color(level)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(self.LEVEL_ICON.get(level, "info"), col, 18))
        lay.addWidget(ic)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setFixedWidth(min(QFontMetrics(lbl.font()).horizontalAdvance(text) + 8, 380))
        lay.addWidget(lbl)
        bar = QFrame(self)
        bar.setStyleSheet(f"background: {col}; border-radius: 2px;")
        bar.setGeometry(0, 8, 3, 10)
        self._bar = bar
        self.adjustSize()
        self._bar.setGeometry(0, 8, 3, self.height() - 16)
        soft_shadow(self, 30, 120)
        self._opacity = 0.0
        self.anim = QPropertyAnimation(self, b"pos", self)
        self.anim.setDuration(260)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        QTimer.singleShot(ms, self._close)
        self.mousePressEvent = lambda e: self._close()

    def _close(self):
        host = self.parent()
        if hasattr(host, "_toasts") and self in host._toasts:
            host._toasts.remove(self)
            host._layout_toasts()
        self.deleteLater()

