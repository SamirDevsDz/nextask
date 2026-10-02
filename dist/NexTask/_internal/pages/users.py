"""Users : sessions ouvertes + ressources consommées par utilisateur."""
from collections import defaultdict

import psutil
from PySide6.QtWidgets import QLabel

from core.common import IS_WIN, fmt_bytes, fmt_rate, fmt_ts, run_cmd, confirm, info, is_admin
from core.widgets import Page, TablePanel
from core import audit


def _win_sessions():
    """Parse « query user » (indépendant de la langue : ID = 1er nombre)."""
    out = run_cmd(["query", "user"], 10)
    res = {}
    for line in out.splitlines()[1:]:
        toks = line.strip().lstrip(">").split()
        for i, t in enumerate(toks):
            if t.isdigit():
                res[toks[0].lower()] = {"id": t, "state": toks[i + 1] if i + 1 < len(toks) else ""}
                break
    return res


class UsersPage(Page):
    title = "Users"
    subtitle = "Sessions et consommation par utilisateur"

    def __init__(self, sampler, parent=None):
        super().__init__(sampler, parent)
        self.root.addWidget(QLabel("Ressources par utilisateur", objectName="section"))
        self.res = TablePanel(["Utilisateur", "Processus", "CPU %", "Mémoire", "Disque"],
                              right_cols=(1, 2, 3, 4))
        self.res.set_widths([240, 90, 90, 120, 120])
        self.root.addWidget(self.res, 2)
        self.root.addWidget(QLabel("Sessions ouvertes", objectName="section"))
        self.sess = TablePanel(["Utilisateur", "Terminal", "Hôte", "Ouverte le", "ID session", "État"])
        self.sess.set_widths([200, 120, 160, 160, 90, 120])
        if IS_WIN:
            self.sess.add_button("Déconnecter", self._disconnect, needs_selection=True)
            self.sess.add_button("Fermer la session", self._logoff, needs_selection=True, danger=True)
        self.root.addWidget(self.sess, 1)
        sampler.procs_updated.connect(self.refresh)
        self._n = 0

    def on_show(self):
        self._n = 0
        self.refresh()

    def refresh(self):
        if not self.isVisible():
            return
        agg = defaultdict(lambda: [0, 0.0, 0, 0.0])
        for p in self.sampler.procs:
            a = agg[p["user"] or "(système / inaccessible)"]
            a[0] += 1
            a[1] += p["cpu"]
            a[2] += p["mem"]
            a[3] += p["read_rate"] + p["write_rate"]
        self.res.set_rows([[u, a[0], (f"{a[1]:.1f}", a[1]), (fmt_bytes(a[2]), a[2]),
                            (fmt_rate(a[3]), a[3])] for u, a in agg.items()])
        if self._n % 5 == 0:   # sessions : toutes les ~10 s
            ws = _win_sessions() if IS_WIN else {}
            rows = []
            for u in psutil.users():
                s = ws.get(u.name.lower(), {})
                rows.append([u.name, u.terminal or "console", u.host or "local", fmt_ts(u.started),
                             s.get("id", "—"), s.get("state", "")])
            self.sess.set_rows(rows)
        self._n += 1

    def _disconnect(self, row):
        if row[4] == "—":
            return
        if confirm(self, "Déconnecter", f"Déconnecter la session de {row[0]} (les applications restent ouvertes) ?"):
            out = run_cmd(["tsdiscon", row[4]]) or "OK"
            audit.log("Session : déconnexion", f"{row[0]} (session {row[4]})", out)
            info(self, "Résultat", out)

    def _logoff(self, row):
        if row[4] == "—":
            return
        if not is_admin():
            info(self, "Droits requis", "Fermer la session d'un autre utilisateur nécessite les droits administrateur.")
        if confirm(self, "Fermer la session",
                   f"Fermer la session de {row[0]} ?\nSes applications seront fermées sans sauvegarde."):
            out = run_cmd(["logoff", row[4]]) or "OK"
            audit.log("Session : fermeture", f"{row[0]} (session {row[4]})", out)
            info(self, "Résultat", out)
