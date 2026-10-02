"""Disk Space : occupation des volumes + analyseur de dossiers (style WinDirStat/TreeSize)."""
import heapq
import os
import subprocess
import tempfile

import psutil
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QWidget, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QFileDialog, QLabel, QSplitter, QFrame, QComboBox)

from core.common import IS_WIN, BackgroundTask, fmt_bytes, open_location
from core.widgets import Page, TablePanel, UsageBar

MAX_FILES_PER_DIR = 40


class _Cancel:
    flag = False


def scan(root, cancel):
    """Parcours itératif. Renvoie (index dossiers, top fichiers, nb fichiers, erreurs)."""
    index = {}                # dossier -> [taille, nb_fichiers, [(nom, taille, est_dossier)]]
    top = []                  # tas des 200 plus gros fichiers
    order, stack = [], [root]
    errors = 0
    while stack:
        if cancel.flag:
            return None
        d = stack.pop()
        order.append(d)
        files, dirs, fsize, fcount = [], [], 0, 0
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            dirs.append(e.path)
                            stack.append(e.path)
                        else:
                            s = e.stat(follow_symlinks=False).st_size
                            fsize += s
                            fcount += 1
                            files.append((e.name, s, False))
                            if len(top) < 200:
                                heapq.heappush(top, (s, e.path))
                            elif s > top[0][0]:
                                heapq.heapreplace(top, (s, e.path))
                    except OSError:
                        errors += 1
        except OSError:
            errors += 1
        files.sort(key=lambda x: x[1], reverse=True)
        rest = files[MAX_FILES_PER_DIR:]
        files = files[:MAX_FILES_PER_DIR]
        if rest:
            files.append((f"[{len(rest)} autres fichiers]", sum(f[1] for f in rest), False))
        index[d] = [fsize, fcount, files, dirs]
    # agrégation ascendante (ordre inverse du parcours = enfants avant parents)
    for d in reversed(order):
        size, count, files, dirs = index[d]
        children = list(files)
        for sub in dirs:
            if sub in index:
                ss, sc = index[sub][0], index[sub][1]
                size += ss
                count += sc
                children.append((os.path.basename(sub) or sub, ss, True))
        children.sort(key=lambda x: x[1], reverse=True)
        index[d] = [size, count, children, None]
    big = sorted(top, reverse=True)
    return index, big, errors


def _temp_dirs():
    cands = [tempfile.gettempdir()]
    if IS_WIN:
        cands += [os.path.expandvars(r"%WINDIR%\Temp"), os.path.expandvars(r"%WINDIR%\SoftwareDistribution\Download"),
                  os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\INetCache"),
                  os.path.expandvars(r"%LOCALAPPDATA%\CrashDumps")]
    else:
        cands += [os.path.expanduser("~/.cache")]
    out = []
    for c in cands:
        if os.path.isdir(c):
            total = 0
            for dp, _, fns in os.walk(c):
                for f in fns:
                    try:
                        total += os.path.getsize(os.path.join(dp, f))
                    except OSError:
                        pass
            out.append((c, total))
    return out


class DiskSpacePage(Page):
    title = "Disk Space"
    subtitle = "Où est passé mon espace disque ?"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        top = QHBoxLayout()
        self.vol_card = QFrame(objectName="card")
        self.vol_lay = QVBoxLayout(self.vol_card)
        self.vol_lay.addWidget(QLabel("Volumes", objectName="section"))
        top.addWidget(self.vol_card, 2)
        tcard = QFrame(objectName="card")
        tl = QVBoxLayout(tcard)
        tl.addWidget(QLabel("Fichiers temporaires & caches", objectName="section"))
        self.temp_lbl = QLabel("Calcul…")
        self.temp_lbl.setWordWrap(True)
        self.temp_lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.temp_lbl.setOpenExternalLinks(False)
        self.temp_lbl.linkActivated.connect(open_location)
        tl.addWidget(self.temp_lbl)
        if IS_WIN:
            cb = QPushButton("Ouvrir le Nettoyage de disque Windows")
            cb.clicked.connect(lambda: subprocess.Popen(["cleanmgr"]))
            tl.addWidget(cb)
        tl.addStretch()
        top.addWidget(tcard, 1)
        self.root.addLayout(top)

        bar = QHBoxLayout()
        self.target = QComboBox()
        self.target.setEditable(True)
        self.target.setMinimumWidth(320)
        bar.addWidget(QLabel("Analyser :"))
        bar.addWidget(self.target)
        b = QPushButton("Parcourir…")
        b.clicked.connect(self._browse)
        bar.addWidget(b)
        self.go = QPushButton("Lancer l'analyse")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.start_scan)
        bar.addWidget(self.go)
        self.stop = QPushButton("Annuler")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self._cancel)
        bar.addWidget(self.stop)
        self.scan_lbl = QLabel("", objectName="muted")
        bar.addWidget(self.scan_lbl)
        bar.addStretch()
        self.root.addLayout(bar)

        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Nom", "Taille", "% du parent", "Fichiers"])
        self.tree.setColumnWidth(0, 340)
        self.tree.itemExpanded.connect(self._expand)
        self.tree.itemDoubleClicked.connect(lambda it, _c: open_location(it.data(0, Qt.UserRole)))
        split.addWidget(self.tree)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel("Plus gros fichiers", objectName="section"))
        self.big = TablePanel(["Taille", "Fichier"])
        self.big.set_widths([90, 400])
        self.big.add_context("Ouvrir l'emplacement", lambda r: open_location(r[1]))
        v.addWidget(self.big)
        split.addWidget(w)
        split.setSizes([600, 450])
        self.root.addWidget(split, 1)

        self.index = {}
        self.cancel = _Cancel()
        self.task = BackgroundTask(scan, self._scanned)
        self.temp_task = BackgroundTask(_temp_dirs, self._temps)
        self.bars = {}
        self._loaded = False

    def on_show(self):
        self._volumes()
        if not self._loaded:
            self._loaded = True
            for p in psutil.disk_partitions(all=False):
                self.target.addItem(p.mountpoint)
            self.target.addItem(os.path.expanduser("~"))
            self.temp_task.start()

    def _volumes(self):
        for p in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(p.mountpoint)
            except (OSError, PermissionError):
                continue
            if p.mountpoint not in self.bars:
                b = UsageBar(f"{p.mountpoint}  ({p.fstype})")
                self.vol_lay.addWidget(b)
                self.bars[p.mountpoint] = b
            self.bars[p.mountpoint].set(u.percent, f"{fmt_bytes(u.used)} utilisés sur {fmt_bytes(u.total)} — "
                                                   f"{fmt_bytes(u.free)} libres ({100 - u.percent:.0f} %)")

    def _temps(self, items):
        self.temp_lbl.setText("<br>".join(f'<a href="{p}" style="color:#3b82f6">{p}</a> : <b>{fmt_bytes(s)}</b>' for p, s in items)
                              + "<br><span style='color:gray'>Cliquez pour ouvrir le dossier.</span>")

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Dossier à analyser", self.target.currentText())
        if d:
            self.target.setEditText(d)

    def start_scan(self):
        root = self.target.currentText().strip()
        if not os.path.isdir(root):
            self.scan_lbl.setText("Dossier introuvable.")
            return
        self.cancel = _Cancel()
        if self.task.start(root, self.cancel):
            self._root = root
            self.go.setEnabled(False)
            self.stop.setEnabled(True)
            self.scan_lbl.setText("Analyse en cours… (un disque complet peut prendre plusieurs minutes)")
            self.tree.clear()

    def _cancel(self):
        self.cancel.flag = True

    def _scanned(self, res):
        self.go.setEnabled(True)
        self.stop.setEnabled(False)
        if res is None:
            self.scan_lbl.setText("Analyse annulée.")
            return
        self.index, big, errors = res
        size, count = self.index[self._root][:2]
        self.scan_lbl.setText(f"{fmt_bytes(size)} dans {count} fichiers • {errors} élément(s) inaccessible(s)")
        self.tree.clear()
        it = self._item(self.tree, self._root, self._root, size, size, count, True)
        it.setExpanded(True)
        self.big.set_rows([[(fmt_bytes(s), s), p] for s, p in big])
        self.big.sort_by(0)

    def _item(self, parent, name, path, size, parent_size, count, is_dir):
        pct = 100 * size / parent_size if parent_size else 0
        it = QTreeWidgetItem([("📁 " if is_dir else "") + name, fmt_bytes(size), f"{pct:.1f} %",
                              str(count) if is_dir else ""])
        it.setData(0, Qt.UserRole, path)
        it.setData(1, Qt.UserRole, is_dir)
        it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        it.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
        if is_dir and self.index.get(path, [0, 0, []])[2]:
            it.addChild(QTreeWidgetItem(["…"]))  # placeholder pour chargement paresseux
        (parent.addTopLevelItem if isinstance(parent, QTreeWidget) else parent.addChild)(it)
        return it

    def _expand(self, item):
        if item.childCount() != 1 or item.child(0).text(0) != "…":
            return
        item.takeChild(0)
        path = item.data(0, Qt.UserRole)
        size, _, children, _ = self.index.get(path, [0, 0, [], None])
        for name, s, is_dir in children[:300]:
            cp = os.path.join(path, name)
            cnt = self.index.get(cp, [0, 0])[1] if is_dir else 0
            self._item(item, name, cp, s, size, cnt, is_dir)
