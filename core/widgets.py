"""Widgets réutilisables : graphe, tuile, tableau filtrable, page de base."""
import csv

from PySide6.QtCore import (Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
                            QPointF, QRectF)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QAction, QGuiApplication
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTableView,
                               QPushButton, QHeaderView, QAbstractItemView, QMenu, QFileDialog,
                               QFrame, QProgressBar)

ACCENT = "#3b82f6"
STATUS_COLORS = {"OK": "#22c55e", "INFO": "#60a5fa", "ALERTE": "#f59e0b", "CRITIQUE": "#ef4444"}
COLORS = {"cpu": "#3b82f6", "mem": "#a855f7", "disk": "#22c55e", "net": "#f59e0b",
          "gpu": "#ef4444", "freq": "#06b6d4"}


# ======================================================================= graphe
class LineGraph(QWidget):
    """Graphe glissant simple dessiné au QPainter (aucune dépendance)."""

    def __init__(self, color=ACCENT, max_value=100.0, auto_scale=False, points=60,
                 color2=None, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.color2 = QColor(color2) if color2 else None
        self.max_value = max_value
        self.auto_scale = auto_scale
        self.points = points
        self.series = []
        self.series2 = []
        self.caption = ""
        self.setMinimumHeight(60)

    def set_data(self, values, values2=None, caption=""):
        self.series = list(values)[-self.points:]
        self.series2 = list(values2)[-self.points:] if values2 is not None else []
        self.caption = caption
        self.update()

    def _scale(self):
        if not self.auto_scale:
            return self.max_value
        m = max([1.0] + self.series + self.series2)
        return m * 1.15

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(self.color.darker(160), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)
        grid = QPen(QColor(128, 128, 128, 45), 1)
        p.setPen(grid)
        for i in range(1, 4):
            y = r.top() + r.height() * i / 4
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        for i in range(1, 6):
            x = r.left() + r.width() * i / 6
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        scale = self._scale() or 1
        for data, col in ((self.series, self.color), (self.series2, self.color2)):
            if len(data) < 2 or col is None:
                continue
            step = r.width() / (self.points - 1)
            x0 = r.right() - step * (len(data) - 1)
            path = QPainterPath()
            for i, v in enumerate(data):
                pt = QPointF(x0 + i * step, r.bottom() - min(v / scale, 1.0) * r.height())
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            fill = QPainterPath(path)
            fill.lineTo(QPointF(r.right(), r.bottom()))
            fill.lineTo(QPointF(x0, r.bottom()))
            fill.closeSubpath()
            fc = QColor(col)
            fc.setAlpha(50)
            p.fillPath(fill, fc)
            p.setPen(QPen(col, 1.6))
            p.drawPath(path)
        if self.caption:
            p.setPen(self.palette().text().color())
            p.drawText(r.adjusted(6, 4, -6, -4), Qt.AlignTop | Qt.AlignRight, self.caption)
        p.end()


# ======================================================================= tuile
class StatTile(QFrame):
    def __init__(self, title, color=ACCENT, max_value=100, auto_scale=False, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        top = QHBoxLayout()
        self.title = QLabel(title)
        self.title.setObjectName("muted")
        self.value = QLabel("—")
        self.value.setObjectName("bigValue")
        top.addWidget(self.title)
        top.addStretch()
        lay.addLayout(top)
        lay.addWidget(self.value)
        self.sub = QLabel("")
        self.sub.setObjectName("muted")
        lay.addWidget(self.sub)
        self.graph = LineGraph(color, max_value, auto_scale)
        self.graph.setFixedHeight(54)
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
        lay.setContentsMargins(0, 4, 0, 4)
        self.label = QLabel(label)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.detail = QLabel("")
        self.detail.setObjectName("muted")
        lay.addWidget(self.label)
        lay.addWidget(self.bar)
        lay.addWidget(self.detail)

    def set(self, pct, detail):
        self.bar.setValue(int(pct))
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

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid():
            return None
        cell = self.rows[idx.row()][idx.column()]
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return str(cell[0]) if isinstance(cell, tuple) else ("" if cell is None else str(cell))
        if role == Qt.UserRole:
            key = cell[1] if isinstance(cell, tuple) else cell
            if key is None:
                return -1
            return key if isinstance(key, (int, float)) else str(key).lower()
        if role == Qt.ForegroundRole and isinstance(cell, tuple) and len(cell) > 2 and cell[2]:
            return QColor(cell[2])
        if role == Qt.TextAlignmentRole and idx.column() in self.align_right:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
        return None

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


class _Proxy(QSortFilterProxyModel):
    def lessThan(self, a, b):
        x, y = a.data(Qt.UserRole), b.data(Qt.UserRole)
        try:
            return x < y
        except TypeError:
            return str(x) < str(y)


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
        self.toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(320)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.toolbar.addWidget(self.search)
        self.toolbar.addStretch()
        lay.addLayout(self.toolbar)

        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(24)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setWordWrap(False)
        h = self.view.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setStretchLastSection(True)
        h.setDefaultSectionSize(130)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.view)

        self.status = QLabel("")
        self.status.setObjectName("muted")
        lay.addWidget(self.status)
        self._ctx = []
        self._sel_buttons = []
        self.view.selectionModel().selectionChanged.connect(self._sel_changed)
        self._export_btn = self.add_button("Exporter CSV", self.export_csv)
        self.proxy.sort(-1)
        h.setSortIndicator(-1, Qt.AscendingOrder)

    def make_compact(self):
        """Version minimale : sans recherche, export ni tri (ordre fourni conservé)."""
        self.search.hide()
        self._export_btn.hide()
        self.view.setSortingEnabled(False)
        self.proxy.sort(-1)

    # -- API
    def add_button(self, label, callback, needs_selection=False, danger=False):
        b = QPushButton(label)
        if danger:
            b.setObjectName("danger")
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
                if row[self.key_col] == sel_key:
                    pidx = self.proxy.mapFromSource(self.model.index(r, 0))
                    if pidx.isValid():
                        self.view.selectRow(pidx.row())
                    break
        self.view.verticalScrollBar().setValue(sb)
        self.status.setText(f"{self.proxy.rowCount()} élément(s)")
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
        self.root.setContentsMargins(22, 16, 22, 14)
        self.root.setSpacing(10)
        head = QHBoxLayout()
        t = QLabel(self.title)
        t.setObjectName("pageTitle")
        head.addWidget(t)
        if self.subtitle:
            s = QLabel(self.subtitle)
            s.setObjectName("muted")
            head.addWidget(s)
        head.addStretch()
        self.header_actions = head
        self.root.addLayout(head)

    def on_show(self):
        """Appelé quand la page devient visible."""

    def on_tick(self):
        """Appelé chaque seconde quand la page est visible."""


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setObjectName("sep")
    return f
