"""Test de fumée : démarre NexTask sans écran, ouvre chacune des pages, vérifie qu'aucune exception n'est levée.

Usage :  python tests/smoke_test.py      (code de sortie 0 = OK, 1 = échec)
Utilisé par la compilation GitHub avant de construire l'exécutable.
"""
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

errors = []
sys.excepthook = lambda *exc: errors.append("".join(traceback.format_exception(*exc)))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import main  # noqa: E402
from core import design  # noqa: E402

app = QApplication(sys.argv)
w = main.MainWindow()
w.resize(1400, 860)
w.show()
pages = list(range(len(w.entries)))
state = {"i": 0}


def finish():
    fails = design.audit_contrast()
    if fails:
        errors.append("Contraste insuffisant : " + "; ".join(fails))
    print(f"{len(pages)} pages ouvertes, {len(errors)} erreur(s)")
    for e in errors:
        print(e)
    sys.stdout.flush()
    # os._exit : ne pas attendre les analyses PowerShell encore en cours en arrière-plan
    os._exit(1 if errors else 0)


def step():
    i = state["i"]
    if i >= len(pages):
        w._toggle_theme()      # vérifie aussi la bascule de thème
        w._toggle_theme()
        QTimer.singleShot(500, finish)
        return
    try:
        w.nav.select(pages[i])
        print(f"  ok  {w.entries[pages[i]][2]}")
    except Exception:  # noqa: BLE001
        errors.append(traceback.format_exc())
    state["i"] += 1
    QTimer.singleShot(700, step)


QTimer.singleShot(1500, step)
QTimer.singleShot(120_000, lambda: (errors.append("Délai dépassé (120 s)"), finish()))
app.exec()
