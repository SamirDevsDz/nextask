"""Feuille de style globale générée depuis les tokens du design system (core/design.py)."""
from . import design as d


def _check_image(color):
    """Écrit l'icône de coche (PNG) dans le dossier de données et renvoie son chemin pour le QSS."""
    import os
    from .common import app_data_dir
    from . import icons
    path = os.path.join(app_data_dir(), f"check_{color.strip('#')}.png")
    if not os.path.exists(path):
        svg_pm = icons.pixmap("tick", color, 14)
        svg_pm.save(path)
    return path.replace("\\", "/")


def stylesheet(mode="dark"):
    d.set_mode(mode)
    c = d.PALETTES[mode]
    r = d.RADIUS
    check = _check_image(c["accent_text"])
    return f"""
* {{ font-family: {d.FONT_UI}; font-size: 13px; }}
QMainWindow, QWidget#central {{ background: {c['bg']}; }}
QStackedWidget#pages, QStackedWidget#pages > QWidget, QScrollArea, QScrollArea > QWidget > QWidget
    {{ background: {c['bg']}; }}
QWidget {{ color: {c['text']}; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {c['elevated']}; color: {c['text']}; border: 1px solid {c['border_strong']};
    border-radius: {r['sm']}px; padding: 6px 8px; }}

/* ---------- typographie ---------- */
QLabel#pageTitle {{ font-size: 22px; font-weight: 650; letter-spacing: -0.2px; }}
QLabel#pageSubtitle, QLabel#muted {{ color: {c['muted']}; }}
QLabel#section {{ font-size: 13px; font-weight: 650; color: {c['text2']}; letter-spacing: 0.2px; }}
QLabel#bigValue, QLabel#kpiValue {{ font-size: 26px; font-weight: 650; font-family: {d.FONT_UI}; }}
QLabel#kpiLabel {{ color: {c['muted']}; font-size: 12px; font-weight: 600; letter-spacing: 0.6px; }}
QLabel#mono {{ font-family: {d.FONT_MONO}; }}
QLabel#badgeAdmin {{ color: {c['ok']}; background: transparent; }}
QLabel#badgeUser {{ color: {c['warn']}; background: transparent; }}

/* ---------- surfaces ---------- */
QFrame#card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r['lg']}px; }}
QFrame#cardAccent {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {c['surface2']}, stop:1 {c['surface']});
    border: 1px solid {c['border_strong']}; border-radius: {r['lg']}px; }}
QFrame#sep {{ color: {c['border']}; background: {c['border']}; max-height: 1px; border: none; }}
QFrame#topbar {{ background: {c['bg']}; border-bottom: 1px solid {c['border']}; }}

/* ---------- barre latérale ---------- */
QFrame#sidebar {{ background: {c['sidebar']}; border-right: 1px solid {'#16213d' if mode == 'dark' else '#1c2747'}; }}
QLabel#brand {{ color: #e7ecfb; font-size: 16px; font-weight: 700; letter-spacing: 0.3px; }}
QLabel#brandSub {{ color: #8d99bd; font-size: 11px; }}
QLabel#navGroup {{ color: #6f7ca3; font-size: 10.5px; font-weight: 700; letter-spacing: 1.2px; padding: 7px 14px 1px 14px; }}
QPushButton#navItem {{ background: transparent; color: #b7c1dd; border: none; border-radius: {r['md']}px;
    text-align: left; padding: 5px 12px; font-size: 13px; }}
QPushButton#navItem:hover {{ background: #121a33; color: #e7ecfb; }}
QPushButton#navItem:checked {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #11314f, stop:1 #0f1a35);
    color: #ffffff; font-weight: 600; border-left: 3px solid #22d3ee; padding-left: 9px; }}
QPushButton#navItem:focus {{ outline: none; border: 1px solid #22d3ee; }}
QPushButton#navToggle {{ background: transparent; border: none; border-radius: {r['sm']}px; padding: 6px; }}
QPushButton#navToggle:hover {{ background: #121a33; }}

/* ---------- boutons ---------- */
QPushButton {{ background: {c['surface2']}; color: {c['text']}; border: 1px solid {c['border']};
    border-radius: {r['sm'] + 2}px; padding: 7px 14px; min-height: 18px; }}
QPushButton:hover {{ background: {c['hover']}; border-color: {c['border_strong']}; }}
QPushButton:pressed {{ background: {c['sel']}; }}
QPushButton:focus {{ border: 1px solid {c['accent']}; outline: none; }}
QPushButton:disabled {{ color: {c['faint']}; background: {c['surface']}; border-color: {c['border']}; }}
QPushButton:checked {{ background: {c['sel']}; border-color: {c['accent']}; color: {c['text']}; }}
QPushButton#primary {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {c['accent']}, stop:1 {c['accent2']});
    color: {c['accent_text']}; border: none; font-weight: 650; }}
QPushButton#primary:hover {{ background: {c['accent']}; }}
QPushButton#primary:disabled {{ background: {c['surface2']}; color: {c['faint']}; }}
QPushButton#danger {{ color: {c['crit']}; border-color: {c['border']}; }}
QPushButton#danger:hover {{ background: {c['crit']}; color: {'#1a0606' if mode == 'dark' else '#ffffff'}; border-color: {c['crit']}; }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {c['text2']}; }}
QPushButton#ghost:hover {{ background: {c['hover']}; border-color: {c['border']}; }}
QPushButton#chip {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 14px;
    padding: 4px 12px; color: {c['text2']}; }}
QPushButton#searchBox {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r['md']}px;
    color: {c['muted']}; text-align: left; padding: 7px 12px; min-width: 260px; }}
QPushButton#searchBox:hover {{ border-color: {c['accent']}; color: {c['text2']}; }}

/* ---------- champs ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{ background: {c['surface']};
    border: 1px solid {c['border']}; border-radius: {r['sm'] + 2}px; padding: 6px 10px;
    selection-background-color: {c['accent']}; selection-color: {c['accent_text']}; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {c['border_strong']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{ border: 1px solid {c['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c['elevated']}; border: 1px solid {c['border_strong']};
    selection-background-color: {c['sel']}; selection-color: {c['text']}; outline: 0; padding: 4px; }}
QPlainTextEdit, QTextBrowser {{ font-family: {d.FONT_MONO}; font-size: 12px; }}
QCheckBox {{ spacing: 8px; color: {c['text2']}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {c['border_strong']};
    background: {c['surface']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']};
    image: url("{check}"); }}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}

/* ---------- tableaux / listes ---------- */
QTableView, QTreeWidget, QTreeView, QListWidget {{ background: {c['surface']}; alternate-background-color: {c['surface2']};
    border: 1px solid {c['border']}; border-radius: {r['md']}px; gridline-color: {c['border']};
    selection-background-color: {c['sel']}; selection-color: {c['text']}; outline: 0; }}
QTableView::item, QTreeView::item {{ padding: 2px 6px; border: none; }}
QTableView::item:hover, QTreeView::item:hover {{ background: {c['hover']}; }}
QTableView::item:selected, QTreeView::item:selected {{ background: {c['sel']}; color: {c['text']}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {c['surface']}; color: {c['muted']}; border: none;
    border-bottom: 1px solid {c['border']}; padding: 8px 8px; font-size: 11.5px; font-weight: 650;
    text-transform: uppercase; letter-spacing: 0.4px; }}
QHeaderView::section:hover {{ color: {c['text']}; }}
QTableCornerButton::section {{ background: {c['surface']}; border: none; }}
QListWidget::item {{ padding: 6px 8px; border-radius: {r['sm']}px; }}
QListWidget::item:hover {{ background: {c['hover']}; }}
QListWidget::item:selected {{ background: {c['sel']}; color: {c['text']}; }}
QListWidget#perfList {{ background: transparent; border: none; }}
QListWidget#perfList::item {{ padding: 10px 12px; margin: 2px 0; border-radius: {r['md']}px;
    border: 1px solid transparent; }}
QListWidget#perfList::item:selected {{ background: {c['surface2']}; border: 1px solid {c['border_strong']}; }}

/* ---------- onglets ---------- */
QTabWidget::pane {{ border: none; top: -1px; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 8px 16px; margin-right: 4px;
    border: none; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:hover {{ color: {c['text']}; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}

/* ---------- divers ---------- */
QProgressBar {{ background: {c['surface2']}; border: none; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ border-radius: 4px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
    stop:0 {c['accent']}, stop:1 {c['accent2']}); }}
QProgressBar[level="mid"]::chunk {{ background: {c['warn']}; }}
QProgressBar[level="high"]::chunk {{ background: {c['crit']}; }}
QProgressBar#busy {{ background: transparent; max-height: 2px; border-radius: 0; }}
QProgressBar#busy::chunk {{ background: {c['accent']}; border-radius: 0; }}
QMenu {{ background: {c['elevated']}; border: 1px solid {c['border_strong']}; border-radius: {r['md']}px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: {r['sm']}px; }}
QMenu::item:selected {{ background: {c['sel']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border_strong']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['border_strong']}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0; background: none; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['surface2']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {c['text']}; border: 3px solid {c['accent']}; width: 10px; height: 10px;
    margin: -6px 0; border-radius: 8px; }}
QSplitter::handle {{ background: transparent; width: 8px; }}
QStatusBar {{ background: {c['bg']}; color: {c['muted']}; border-top: 1px solid {c['border']}; }}
QStatusBar QLabel {{ color: {c['muted']}; }}
QStatusBar::item {{ border: none; }}
QMessageBox, QInputDialog, QDialog {{ background: {c['elevated']}; }}
QMessageBox QLabel {{ color: {c['text']}; }}
QTextBrowser {{ border-radius: {r['md']}px; }}

/* ---------- palette de commandes / toasts ---------- */
QFrame#palette {{ background: {c['elevated']}; border: 1px solid {c['border_strong']}; border-radius: {r['lg']}px; }}
QLineEdit#paletteInput {{ background: transparent; border: none; border-bottom: 1px solid {c['border']};
    border-radius: 0; font-size: 16px; padding: 14px 16px; }}
QListWidget#paletteList {{ background: transparent; border: none; padding: 6px; }}
QListWidget#paletteList::item {{ padding: 9px 12px; border-radius: {r['sm']}px; color: {c['text2']}; }}
QListWidget#paletteList::item:selected {{ background: {c['sel']}; color: {c['text']}; }}
QFrame#toast {{ background: {c['elevated']}; border: 1px solid {c['border_strong']}; border-radius: {r['md']}px; }}
"""
