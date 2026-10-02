"""Design system NexTask — tokens (couleurs, typo, espacements, rayons) pour les thèmes sombre et clair.

Règles :
- grille d'espacement de 4 px ; rayons 6 / 10 / 14 ;
- texte ≥ 4,5:1 et éléments graphiques ≥ 3:1 sur leur surface (vérifié par `audit_contrast()`) ;
- la couleur n'est jamais le seul indicateur : les sévérités ont toujours un libellé.
"""
from PySide6.QtGui import QColor

SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
RADIUS = {"sm": 6, "md": 10, "lg": 14}
FONT_UI = '"Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", "Inter", sans-serif'
FONT_MONO = '"Cascadia Mono", "JetBrains Mono", "Consolas", monospace'

PALETTES = {
    # Console SOC : bleu nuit profond, accents cyan / violet
    "dark": {
        "bg": "#0a0f1e", "bg_grad": "#0d1428", "sidebar": "#080c19", "surface": "#10172b",
        "surface2": "#151e38", "elevated": "#1a2444", "border": "#1f2b4d", "border_strong": "#2c3b66",
        "text": "#e7ecfb", "text2": "#b7c1dd", "muted": "#8d99bd", "faint": "#5b6890",
        "accent": "#22d3ee", "accent2": "#a78bfa", "accent_text": "#04111a",
        "ok": "#34d399", "info": "#60a5fa", "warn": "#fbbf24", "crit": "#f87171",
        "sel": "#16304f", "hover": "#141d36", "grid": "#1b2647",
    },
    "light": {
        "bg": "#f3f6fb", "bg_grad": "#eef2f9", "sidebar": "#0d1428", "surface": "#ffffff",
        "surface2": "#f6f8fc", "elevated": "#ffffff", "border": "#dfe5f1", "border_strong": "#c6d0e4",
        "text": "#0f172a", "text2": "#334155", "muted": "#566179", "faint": "#8a94aa",
        "accent": "#0e7490", "accent2": "#6d28d9", "accent_text": "#ffffff",
        "ok": "#047857", "info": "#1d4ed8", "warn": "#b45309", "crit": "#b91c1c",
        "sel": "#dff3f8", "hover": "#eef3fa", "grid": "#e6ebf4",
    },
}

# Séries de graphes (teintes vives pour le sombre ; assombries automatiquement en clair)
SERIES = {"cpu": "#22d3ee", "mem": "#a78bfa", "disk": "#34d399", "net": "#fbbf24",
          "net2": "#f472b6", "freq": "#38bdf8", "gpu": "#fb7185"}

SEVERITY = {"OK": "ok", "INFO": "info", "ALERTE": "warn", "CRITIQUE": "crit"}

_mode = "dark"


def set_mode(mode):
    global _mode
    _mode = mode if mode in PALETTES else "dark"


def mode():
    return _mode


def T(name):
    """Couleur (hex) du token pour le thème courant."""
    return PALETTES[_mode][name]


def qc(name, alpha=None):
    c = QColor(T(name))
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def adapt(hex_color):
    """Couleur de série adaptée au thème (assombrie sur fond clair pour garder ≥ 3:1)."""
    c = QColor(hex_color)
    if _mode == "light":
        c = c.darker(165)
    return c


def severity_color(level):
    return T(SEVERITY.get(level, "info"))


# ------------------------------------------------------------------ contraste WCAG
def _lum(hex_color):
    c = QColor(hex_color)
    out = []
    for v in (c.redF(), c.greenF(), c.blueF()):
        out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def audit_contrast():
    """Vérifie les paires critiques. Renvoie la liste des échecs (vide = conforme)."""
    fails = []
    for m, p in PALETTES.items():
        for fg, bgs, minimum in (
            ("text", ("bg", "surface", "surface2", "elevated"), 7.0),
            ("text2", ("bg", "surface", "surface2"), 4.5),
            ("muted", ("bg", "surface", "surface2"), 4.5),
            ("accent", ("bg", "surface"), 3.0),
            ("ok", ("surface",), 3.0), ("info", ("surface",), 3.0),
            ("warn", ("surface",), 3.0), ("crit", ("surface",), 3.0),
        ):
            for bg in bgs:
                r = contrast(p[fg], p[bg])
                if r < minimum:
                    fails.append(f"{m}: {fg} sur {bg} = {r:.2f} (< {minimum})")
        r = contrast(p["accent_text"], p["accent"])
        if r < 4.5:
            fails.append(f"{m}: accent_text sur accent = {r:.2f}")
        if m == "dark" or m == "light":
            r = contrast("#e7ecfb", p["sidebar"])   # sidebar toujours sombre
            if r < 7:
                fails.append(f"{m}: texte sidebar = {r:.2f}")
    return fails
