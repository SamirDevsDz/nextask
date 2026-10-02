"""Thèmes clair / sombre (QSS)."""

PALETTES = {
    "dark": dict(bg="#1b1d23", side="#16181d", card="#23262e", text="#e6e8ee", muted="#9aa1ad",
                 border="#2f333d", sel="#2b3a55", hover="#262a33", alt="#20232a", input="#1f2229"),
    "light": dict(bg="#f6f7f9", side="#eef0f4", card="#ffffff", text="#1f2328", muted="#6b7280",
                  border="#dfe3ea", sel="#dbe7fb", hover="#e6e9ef", alt="#f9fafb", input="#ffffff"),
}


def stylesheet(mode="dark", accent="#3b82f6"):
    c = PALETTES[mode]
    return f"""
* {{ font-family: "Segoe UI Variable", "Segoe UI", "Inter", sans-serif; font-size: 13px; }}
QMainWindow, QWidget#central, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget
    {{ background: {c['bg']}; color: {c['text']}; }}
QWidget {{ color: {c['text']}; }}
QLabel {{ background: transparent; }}
QLabel#pageTitle {{ font-size: 20px; font-weight: 600; }}
QLabel#bigValue {{ font-size: 22px; font-weight: 600; }}
QLabel#muted {{ color: {c['muted']}; }}
QLabel#section {{ font-size: 14px; font-weight: 600; margin-top: 6px; }}
QLabel#badgeAdmin {{ color: #22c55e; }}
QLabel#badgeUser {{ color: #f59e0b; }}
QFrame#card {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QFrame#sep {{ color: {c['border']}; }}

QListWidget#sidebar {{ background: {c['side']}; border: none; border-right: 1px solid {c['border']};
    padding: 8px 6px; outline: 0; }}
QListWidget#sidebar::item {{ padding: 9px 10px; border-radius: 8px; margin: 1px 2px; }}
QListWidget#sidebar::item:hover {{ background: {c['hover']}; }}
QListWidget#sidebar::item:selected {{ background: {c['sel']}; color: {c['text']}; }}
QListWidget#sidebar::item:disabled {{ color: {accent}; }}

QListWidget#perfList::item {{ padding: 8px 10px; border-radius: 6px; }}
QListWidget#perfList::item:selected {{ background: {c['sel']}; color: {c['text']}; }}
QTableView, QTreeWidget, QTreeView, QListWidget, QPlainTextEdit, QTextEdit {{
    background: {c['card']}; alternate-background-color: {c['alt']};
    border: 1px solid {c['border']}; border-radius: 8px; selection-background-color: {c['sel']};
    selection-color: {c['text']}; gridline-color: {c['border']}; }}
QHeaderView::section {{ background: {c['card']}; color: {c['muted']}; border: none;
    border-bottom: 1px solid {c['border']}; padding: 5px 8px; font-weight: 600; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {c['input']}; border: 1px solid {c['border']};
    border-radius: 6px; padding: 5px 8px; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {accent}; }}
QComboBox QAbstractItemView {{ background: {c['card']}; border: 1px solid {c['border']}; }}
QPushButton {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 6px;
    padding: 6px 12px; }}
QPushButton:hover {{ background: {c['hover']}; }}
QPushButton:disabled {{ color: {c['muted']}; }}
QPushButton#primary {{ background: {accent}; color: white; border: none; }}
QPushButton#danger {{ color: #ef4444; }}
QPushButton:checked {{ background: {c['sel']}; }}
QProgressBar {{ background: {c['border']}; border: none; border-radius: 5px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 5px; }}
QProgressBar[level="mid"]::chunk {{ background: #f59e0b; }}
QProgressBar[level="high"]::chunk {{ background: #ef4444; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 7px 14px; color: {c['muted']}; border: none; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {accent}; }}
QMenu {{ background: {c['card']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['sel']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {accent}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QStatusBar {{ background: {c['side']}; color: {c['muted']}; border-top: 1px solid {c['border']}; }}
QToolTip {{ background: {c['card']}; color: {c['text']}; border: 1px solid {c['border']}; }}
"""
