"""Journal d'audit des actions (SQLite) + envoi syslog optionnel (Security Onion, Wazuh, Graylog…)."""
import getpass
import os
import socket
import sqlite3
import threading
import time
from datetime import datetime, timezone

from PySide6.QtCore import QSettings

from .common import APP_NAME, app_data_dir

_DB = os.path.join(app_data_dir(), "audit.db")
_lock = threading.Lock()
SEVERITY = {"info": 6, "notice": 5, "warning": 4, "error": 3, "critical": 2}


def _conn():
    c = sqlite3.connect(_DB)
    c.execute("CREATE TABLE IF NOT EXISTS audit(ts REAL, user TEXT, action TEXT, target TEXT, result TEXT)")
    return c


def log(action: str, target: str = "", result: str = "OK"):
    """Trace une action effectuée dans NexTask (qui, quand, quoi, résultat)."""
    user = getpass.getuser()
    res = (result or "OK").strip()[:500]
    with _lock:
        try:
            c = _conn()
            c.execute("INSERT INTO audit VALUES (?,?,?,?,?)", (time.time(), user, action, str(target)[:500], res))
            c.commit()
            c.close()
        except sqlite3.Error:
            pass
    syslog(f'action="{action}" target="{target}" user="{user}" result="{res[:120]}"',
           "notice" if res.upper().startswith("OK") else "warning")


def entries(limit=2000):
    with _lock:
        try:
            c = _conn()
            rows = c.execute("SELECT * FROM audit ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            c.close()
            return rows
        except sqlite3.Error:
            return []


def syslog_config():
    s = QSettings(APP_NAME, APP_NAME)
    return (s.value("syslog/enabled", False, type=bool), s.value("syslog/host", "", type=str),
            s.value("syslog/port", 514, type=int), s.value("syslog/proto", "UDP", type=str))


def syslog(message: str, severity: str = "info", force=False):
    """Envoie un message RFC 5424 (facility local0). Silencieux si désactivé ou en échec."""
    enabled, host, port, proto = syslog_config()
    if not (enabled or force) or not host:
        return False
    pri = 16 * 8 + SEVERITY.get(severity, 6)
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    msg = f"<{pri}>1 {ts} {socket.gethostname()} {APP_NAME} {os.getpid()} - - {message}"
    try:
        if proto.upper() == "TCP":
            with socket.create_connection((host, port), timeout=3) as s:
                s.sendall((msg + "\n").encode("utf-8"))
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(msg.encode("utf-8"), (host, port))
        return True
    except OSError:
        return False
