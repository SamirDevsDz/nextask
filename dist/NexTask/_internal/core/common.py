"""Utilitaires partagés : OS, formatage, exécution en arrière-plan, admin."""
import os
import sys
import subprocess
import traceback
from datetime import datetime

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QMessageBox

IS_WIN = sys.platform.startswith("win")
APP_NAME = "NexTask"


def app_data_dir() -> str:
    base = os.environ.get("APPDATA") if IS_WIN else os.path.expanduser("~/.local/share")
    path = os.path.join(base or os.path.expanduser("~"), APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------- formatage
def fmt_bytes(n, suffix="") -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if abs(n) < 1024 or unit == "To":
            return f"{n:.0f} {unit}{suffix}" if unit == "o" else f"{n:.1f} {unit}{suffix}"
        n /= 1024
    return f"{n:.1f} To{suffix}"


def fmt_rate(n) -> str:
    return fmt_bytes(n, "/s")


def fmt_duration(seconds) -> str:
    seconds = int(seconds or 0)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d}j {h:02d}:{m:02d}:{s:02d}" if d else f"{h:02d}:{m:02d}:{s:02d}"


def fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "—"


# ---------------------------------------------------------------- système
NO_WINDOW = 0x08000000 if IS_WIN else 0


def run_cmd(args, timeout=30) -> str:
    """Exécute une commande et renvoie stdout (texte). Ne lève jamais."""
    try:
        out = subprocess.run(
            args, capture_output=True, timeout=timeout,
            creationflags=NO_WINDOW, shell=isinstance(args, str),
        )
        raw = out.stdout or out.stderr
        for enc in ("utf-8", "cp850", "cp1252", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return f"ERREUR: {e}"


def powershell(script: str, timeout=60) -> str:
    return run_cmd(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)


def is_admin() -> bool:
    if IS_WIN:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def relaunch_as_admin():
    if not IS_WIN:
        return False
    import ctypes
    params = " ".join(f'"{a}"' for a in sys.argv)
    exe = sys.executable
    if getattr(sys, "frozen", False):  # exe PyInstaller
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


def open_location(path: str):
    if not path:
        return
    if IS_WIN:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) if os.path.isfile(path) else path])


def confirm(parent, title, text) -> bool:
    return QMessageBox.question(parent, title, text,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes


def info(parent, title, text):
    QMessageBox.information(parent, title, text)


# ---------------------------------------------------------------- tâches de fond
class _Signals(QObject):
    done = Signal(object)
    error = Signal(str)


class _Job(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()

    def run(self):
        try:
            res = self.fn(*self.args, **self.kwargs)
        except Exception:  # noqa: BLE001
            res, err = None, traceback.format_exc()
        else:
            err = None
        try:  # la fenêtre a pu être fermée entre-temps
            if err:
                self.signals.error.emit(err)
            else:
                self.signals.done.emit(res)
        except RuntimeError:
            pass


class BackgroundTask:
    """Lance fn dans un thread ; évite les exécutions qui se chevauchent."""

    def __init__(self, fn, on_done, on_error=None):
        self.fn, self.on_done, self.on_error = fn, on_done, on_error
        self.busy = False
        self._job = None

    def start(self, *args, **kwargs):
        if self.busy:
            return False
        self.busy = True
        job = _Job(self.fn, *args, **kwargs)
        job.signals.done.connect(self._finish)
        job.signals.error.connect(self._fail)
        self._job = job  # garde une référence aux signaux
        QThreadPool.globalInstance().start(job)
        return True

    def _finish(self, res):
        self.busy = False
        self.on_done(res)

    def _fail(self, tb):
        self.busy = False
        print(tb, file=sys.stderr)
        if self.on_error:
            self.on_error(tb)
