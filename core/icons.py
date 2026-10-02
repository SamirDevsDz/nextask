"""Jeu d'icônes vectorielles maison (SVG 24×24, trait 1.8) rendu à la couleur et taille voulues."""
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap, QGuiApplication
from PySide6.QtSvg import QSvgRenderer

_P = {
    "grid": '<rect x="3.5" y="3.5" width="7" height="7" rx="1.8"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.8"/>'
            '<rect x="3.5" y="13.5" width="7" height="7" rx="1.8"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.8"/>',
    "activity": '<polyline points="3,12 7,12 10,5 14,19 17,12 21,12"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/>'
            '<circle cx="4.5" cy="18" r="1"/>',
    "history": '<path d="M3.5 12a8.5 8.5 0 1 0 2.5-6"/><path d="M3.5 4v4h4"/><path d="M12 8v4l3 2"/>',
    "record": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3" fill="{c}"/>',
    "zap": '<polygon points="13,3 5,14 11,14 10,21 19,9 13,9"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/><circle cx="12" cy="7.8" r=".6" fill="{c}"/>',
    "play": '<circle cx="12" cy="12" r="8.5"/><polygon points="10,8.5 16,12 10,15.5"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17" cy="9" r="2.5"/>'
             '<path d="M15.6 14.2c3 .2 5.4 2.6 5.4 5.8"/>',
    "sliders": '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/>'
               '<circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "chip": '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/><rect x="10" y="10" width="4" height="4" rx=".8"/>'
            '<path d="M9.5 3v3.5M14.5 3v3.5M9.5 17.5V21M14.5 17.5V21M3 9.5h3.5M3 14.5h3.5M17.5 9.5H21M17.5 14.5H21"/>',
    "package": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9M8 5.3l8 4.4"/>',
    "drive": '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5 13l2.5-8h9L19 13"/>'
             '<circle cx="16.5" cy="16.5" r=".8" fill="{c}"/><path d="M7 16.5h5"/>',
    "globe": '<circle cx="12" cy="12" r="8.5"/><ellipse cx="12" cy="12" rx="3.8" ry="8.5"/><path d="M3.5 12h17"/>',
    "radar": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12l6-6"/>'
             '<circle cx="12" cy="12" r="1" fill="{c}"/>',
    "shield": '<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 12.5l9 5 9-5"/><path d="M3 16.5l9 5 9-5"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3M14 9l2 2"/>',
    "wrench": '<path d="M14.7 5.3a4.2 4.2 0 0 0-5.2 5.4L3.5 16.7l3.8 3.8 6-6a4.2 4.2 0 0 0 5.4-5.2l-2.6 2.6-2.8-.6-.6-2.8z"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="7"/>'
            '<path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20.5 20.5l-4.5-4.5"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4'
           'M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "chev_l": '<path d="M15 5l-7 7 7 7"/>',
    "chev_r": '<path d="M9 5l7 7-7 7"/>',
    "bell": '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    "admin": '<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="M12 8v5"/><circle cx="12" cy="16" r=".7" fill="{c}"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.5 4.5L20 16"/>'
               '<path d="M20 20v-4h-4"/>',
    "cpu": '<rect x="5" y="5" width="14" height="14" rx="2.5"/><rect x="9" y="9" width="6" height="6" rx="1"/>'
           '<path d="M9 2.5V5M15 2.5V5M9 19v2.5M15 19v2.5M2.5 9H5M2.5 15H5M19 9h2.5M19 15h2.5"/>',
    "memory": '<rect x="3" y="7" width="18" height="10" rx="2"/><path d="M7 7v10M11 7v10M15 7v10M5 17v3M19 17v3"/>',
    "net": '<path d="M7 17V5M7 5L4 8M7 5l3 3"/><path d="M17 7v12M17 19l-3-3M17 19l3-3"/>',
    "alert": '<path d="M12 3.5l9 16H3z"/><path d="M12 10v4"/><circle cx="12" cy="16.8" r=".7" fill="{c}"/>',
    "tick": '<path d="M5 12.5l4.5 4.5L19 7.5" stroke-width="3"/>',
    "check": '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12.2l2.4 2.4 4.6-4.8"/>',
    "command": '<path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3z"/>',
    "logo": '<path d="M12 2.5l8.5 5v9L12 21.5 3.5 16.5v-9z" fill="{c}" fill-opacity=".14"/>'
            '<polyline points="6.5,13 9.5,13 11,9 13,16 14.5,11.5 17.5,11.5"/>',
}


def _svg(name, color):
    body = _P.get(name, _P["grid"]).replace("{c}", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


@lru_cache(maxsize=512)
def pixmap(name, color, size=18):
    app = QGuiApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(_svg(name, color).encode()))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name, color, size=18, active_color=None):
    ic = QIcon(pixmap(name, color, size))
    if active_color:
        ic.addPixmap(pixmap(name, active_color, size), QIcon.Selected)
        ic.addPixmap(pixmap(name, active_color, size), QIcon.Active)
    return ic


NAMES = sorted(_P)
