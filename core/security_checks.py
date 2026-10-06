"""Collecteurs de sécurité réutilisables (page Sécurité, rapport, référence).

Chaque fonction est bloquante : à appeler dans un BackgroundTask.
Statuts : OK / INFO / ALERTE / CRITIQUE.
"""
import hashlib
import os
import re
import tempfile
from collections import Counter

import psutil

from .common import IS_WIN, ps_json, as_list, run_cmd

if IS_WIN:
    import winreg

RANK = {"OK": 0, "INFO": 1, "ALERTE": 2, "CRITIQUE": 3}


# ===================================================================== utilitaires
def reg(hive, path, name, default=None):
    if not IS_WIN:
        return default
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def reg_exists(hive, path):
    if not IS_WIN:
        return False
    try:
        winreg.CloseKey(winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY))
        return True
    except OSError:
        return False


USER_WRITABLE = (r"\appdata\\", r"\temp\\", r"\tmp\\", r"\downloads\\", r"\téléchargements\\",
                 r"\users\public\\", r"\desktop\\", r"\bureau\\", r"\$recycle.bin\\", r"\perflogs\\")
LOLBIN_PATTERNS = [
    (r"powershell.*\s-(e|en|enc|encodedcommand)\s", "PowerShell avec commande encodée"),
    (r"powershell.*-w(indowstyle)?\s+hidden", "PowerShell fenêtre cachée"),
    (r"(iex|invoke-expression).*(downloadstring|iwr|invoke-webrequest)", "Téléchargement + exécution PowerShell"),
    (r"mshta(\.exe)?\s+(http|javascript|vbscript)", "mshta exécutant du code distant"),
    (r"regsvr32.*/i:\s*http", "regsvr32 /i:http (Squiblydoo)"),
    (r"rundll32.*(javascript|http)", "rundll32 suspect"),
    (r"certutil.*-urlcache", "certutil utilisé pour télécharger"),
    (r"bitsadmin.*/transfer", "bitsadmin utilisé pour télécharger"),
    (r"(wscript|cscript).*\.(vbs|js|jse|vbe)", "Script WSH"),
    (r"https?://", "URL dans la commande"),
]


def command_risk(cmd: str):
    """Score + raisons pour une ligne de commande / un chemin."""
    c = os.path.expandvars(cmd or "").lower()
    score, why = 0, []
    if any(u in c for u in USER_WRITABLE):
        score += 2
        why.append("emplacement modifiable par l'utilisateur")
    for pat, label in LOLBIN_PATTERNS:
        if re.search(pat, c):
            score += 3 if "url" not in label.lower() else 1
            why.append(label)
    return score, why


def risk_level(score):
    return "CRITIQUE" if score >= 5 else "ALERTE" if score >= 2 else "OK"


# ===================================================================== 1. bilan de sécurité
POSTURE_PS = r"""
$r=@{}
try{$m=Get-MpComputerStatus -EA Stop; $r.def_av=$m.AntivirusEnabled; $r.def_rt=$m.RealTimeProtectionEnabled;
    $r.def_age=$m.AntivirusSignatureAge; $r.def_tamper=$m.IsTamperProtected; $r.def_mode=[string]$m.AMRunningMode}catch{$r.def_err=$_.Exception.Message}
try{$r.fw=@(Get-NetFirewallProfile -PolicyStore ActiveStore -EA Stop | ForEach-Object { @{n=[string]$_.Name; e=[bool]$_.Enabled} })}catch{
  try{$r.fw=@(Get-NetFirewallProfile -EA Stop | ForEach-Object { @{n=[string]$_.Name; e=[bool]$_.Enabled} })}catch{}}
try{$r.net=@(Get-NetConnectionProfile -EA Stop | ForEach-Object { [string]$_.NetworkCategory })}catch{}
try{$r.wsc_av=@(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct -EA Stop | ForEach-Object {
    @{n=[string]$_.displayName; s=[int64]$_.productState; p=[string]$_.pathToSignedProductExe} })}catch{$r.wsc='na'}
try{$r.wsc_fw=@(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName FirewallProduct -EA Stop | ForEach-Object {
    @{n=[string]$_.displayName; s=[int64]$_.productState} })}catch{}
try{$b=Get-BitLockerVolume -MountPoint $env:SystemDrive -EA Stop; $r.bl=[string]$b.ProtectionStatus; $r.bl_pct=$b.EncryptionPercentage}catch{$r.bl='?'}
try{$r.smb1=[bool](Get-SmbServerConfiguration -EA Stop).EnableSMB1Protocol}catch{}
try{$r.admins=@(Get-LocalGroupMember -SID 'S-1-5-32-544' -EA Stop | ForEach-Object {[string]$_.Name})}catch{
  try{$g=(New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')).Translate([Security.Principal.NTAccount]).Value.Split('\')[1];
      $r.admins=@(([ADSI]"WinNT://./$g,group").Invoke('Members') | ForEach-Object { $_.GetType().InvokeMember('Name','GetProperty',$null,$_,$null) })}catch{}}
try{$h=Get-HotFix -EA Stop | Where-Object InstalledOn | Sort-Object InstalledOn -Descending | Select-Object -First 1;
    $r.hf_id=[string]$h.HotFixID; $r.hf_date=$h.InstalledOn.ToString('yyyy-MM-dd'); $r.hf_days=[int]((Get-Date)-$h.InstalledOn).TotalDays}catch{}
try{$r.secureboot=[string](Confirm-SecureBootUEFI -EA Stop)}catch{$r.secureboot='?'}
try{$g=Get-LocalUser -EA Stop | Where-Object {$_.SID.Value -like '*-501'}; $r.guest=[bool]$g.Enabled}catch{}
try{$a=Get-LocalUser -EA Stop | Where-Object {$_.SID.Value -like '*-500'}; $r.builtin_admin=[bool]$a.Enabled}catch{}
try{$r.psv2=[string](Get-WindowsOptionalFeature -Online -FeatureName MicrosoftWindowsPowerShellV2Root -EA Stop).State}catch{}
try{$r.chassis=@((Get-CimInstance Win32_SystemEnclosure -EA Stop).ChassisTypes | ForEach-Object {[int]$_})}catch{}
$os=Get-CimInstance Win32_OperatingSystem; $r.os=[string]$os.Caption; $r.build=[string]$os.BuildNumber
$r | ConvertTo-Json -Compress -Depth 4
"""


_PROFILE_OF = {"DomainAuthenticated": "Domain", "Private": "Private", "Public": "Public"}


def _wsc_product(x):
    """Décode productState du Centre de sécurité Windows (WSC).
    Format non documenté officiellement par Microsoft mais stable et largement utilisé :
    octet du milieu 0x10/0x11 = protection activée ; dernier octet 0x00 = signatures à jour."""
    try:
        state = int(x.get("s") or 0)
    except (TypeError, ValueError):
        return None
    name = x.get("n") or "?"
    path = (x.get("p") or "").lower()
    mid, low = (state >> 8) & 0xFF, state & 0xFF
    low_name = name.lower()
    ms = (low_name in ("windows defender", "microsoft defender antivirus", "microsoft defender", "windows firewall",
                       "pare-feu windows", "pare-feu windows defender", "windows defender firewall")
          or low_name.startswith(("windows defender", "microsoft defender"))
          or "windows defender" in path or "windowsdefender" in path)
    return {"name": name, "enabled": mid in (0x10, 0x11), "uptodate": low == 0x00, "microsoft": ms,
            "state": hex(state)}


def posture():
    """Liste de contrôles : {cat, check, status, value, advice}."""
    out = []

    def add(cat, check, status, value, advice=""):
        out.append({"cat": cat, "check": check, "status": status, "value": str(value), "advice": advice})

    if not IS_WIN:
        add("Système", "Plateforme", "INFO", "Bilan complet disponible sous Windows uniquement")
        fw = run_cmd(["sh", "-c", "command -v ufw >/dev/null && ufw status | head -1"])
        add("Pare-feu", "ufw", "INFO", fw.strip() or "non installé")
        return out

    d = ps_json(POSTURE_PS, 120) or {}
    HKLM = winreg.HKEY_LOCAL_MACHINE

    # --- Antivirus : on interroge d'abord le Centre de sécurité Windows (WSC), qui connaît les produits tiers.
    avs = [p for p in (_wsc_product(x) for x in as_list(d.get("wsc_av"))) if p]
    third_av = [a for a in avs if not a["microsoft"]]
    active_av = [a for a in avs if a["enabled"]]
    active_third = [a for a in third_av if a["enabled"]]
    if avs:
        if active_av:
            stale = [a for a in active_av if not a["uptodate"]]
            add("Antivirus", "Protection antivirus active (Centre de sécurité)", "ALERTE" if stale else "OK",
                ", ".join(f"{a['name']}{' (signatures non à jour)' if not a['uptodate'] else ''}" for a in active_av),
                "Mettre à jour les signatures de l'antivirus." if stale else "")
        else:
            add("Antivirus", "Protection antivirus active (Centre de sécurité)", "CRITIQUE",
                "Aucun antivirus actif : " + ", ".join(a["name"] for a in avs),
                "Activer l'antivirus installé ou réactiver Microsoft Defender.")
        if len([a for a in active_av if not a["microsoft"]]) > 1:
            add("Antivirus", "Plusieurs antivirus tiers actifs", "ALERTE",
                ", ".join(a["name"] for a in active_av if not a["microsoft"]),
                "Garder un seul moteur temps réel (conflits, lenteurs).")
    elif d.get("wsc") == "na":
        add("Antivirus", "Centre de sécurité Windows", "INFO",
            "Non disponible (Windows Server ?) — évaluation basée sur Defender seul")

    if "def_av" in d:
        mode = d.get("def_mode", "") or "?"
        if active_third:
            names = ", ".join(a["name"] for a in active_third)
            add("Antivirus", "Microsoft Defender", "INFO", f"Mode « {mode} » — remplacé par {names}",
                "Normal : Defender passe en mode passif quand un antivirus tiers est actif.")
        else:
            add("Antivirus", "Moteur Microsoft Defender chargé", "OK" if d.get("def_av") else "CRITIQUE",
                "Oui" if d.get("def_av") else f"Non ({mode})",
                "" if d.get("def_av") else "Aucun antivirus tiers détecté : réactiver Defender.")
            add("Antivirus", "Protection en temps réel (Defender)", "OK" if d.get("def_rt") else "CRITIQUE",
                "Activée" if d.get("def_rt") else "Désactivée", "Réactiver la protection en temps réel.")
            age = d.get("def_age")
            if age is not None:
                add("Antivirus", "Âge des signatures (Defender)", "OK" if age <= 3 else "ALERTE" if age <= 7 else "CRITIQUE",
                    f"{age} jour(s)", "Forcer une mise à jour : Update-MpSignature.")
            add("Antivirus", "Protection contre les falsifications", "OK" if d.get("def_tamper") else "ALERTE",
                "Activée" if d.get("def_tamper") else "Désactivée", "Activer Tamper Protection (Sécurité Windows).")
    elif not avs:
        add("Antivirus", "Microsoft Defender", "INFO", d.get("def_err", "Non disponible (autre antivirus/EDR ?)"))

    # --- Pare-feu : état effectif (GPO incluses) ; un pare-feu tiers actif remplace celui de Windows
    fws = [p for p in (_wsc_product(x) for x in as_list(d.get("wsc_fw"))) if p]
    third_fw = [f for f in fws if f["enabled"] and not f["microsoft"]]
    if third_fw:
        add("Pare-feu", "Pare-feu actif (Centre de sécurité)", "OK", ", ".join(f["name"] for f in third_fw))
    in_use = {_PROFILE_OF.get(c, c) for c in as_list(d.get("net"))}
    for p in as_list(d.get("fw")):
        name = p.get("n")
        if p.get("e"):
            add("Pare-feu", f"Pare-feu Windows — profil {name}", "OK", "Activé")
        elif third_fw:
            add("Pare-feu", f"Pare-feu Windows — profil {name}", "INFO",
                f"Désactivé — géré par {third_fw[0]['name']}", "Normal si le pare-feu tiers filtre bien ce profil.")
        else:
            used = name in in_use
            add("Pare-feu", f"Pare-feu Windows — profil {name}", "CRITIQUE" if used or not in_use else "ALERTE",
                "Désactivé" + (" (profil du réseau actuel)" if used else " (profil non utilisé actuellement)" if in_use else ""),
                "Aucun pare-feu tiers détecté : activer le pare-feu Windows sur ce profil.")

    # --- Chiffrement / démarrage
    bl = d.get("bl", "?")
    mobile = any(int(c) in (8, 9, 10, 11, 12, 14, 18, 21, 30, 31, 32) for c in as_list(d.get("chassis")))
    bl_status = "OK" if bl == "On" else "INFO" if bl == "?" else ("ALERTE" if mobile or not d.get("chassis") else "INFO")
    add("Chiffrement", f"BitLocker ({os.environ.get('SystemDrive', 'C:')})", bl_status,
        {"On": "Protégé", "Off": "Non protégé", "?": "Inconnu (droits admin requis)"}.get(bl, bl)
        + ("" if bl != "Off" else " — portable" if mobile else " — poste fixe" if d.get("chassis") else ""),
        "Portable : chiffrer le disque système (risque de vol)." if mobile else
        "Poste fixe : recommandé si des données sensibles y sont stockées.")
    sb = d.get("secureboot", "?")
    add("Démarrage", "Secure Boot", "OK" if sb == "True" else "INFO" if sb == "?" else "ALERTE",
        {"True": "Activé", "False": "Désactivé", "?": "Inconnu (admin requis / BIOS legacy)"}.get(sb, sb))

    # --- Comptes
    uac = reg(HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", "EnableLUA", 1)
    add("Comptes", "Contrôle de compte (UAC)", "OK" if uac == 1 else "CRITIQUE",
        "Activé" if uac == 1 else "Désactivé", "Réactiver l'UAC (EnableLUA=1).")
    cpba = reg(HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", "ConsentPromptBehaviorAdmin", 5)
    add("Comptes", "Invite UAC administrateurs", "ALERTE" if cpba == 0 else "OK",
        "Élévation sans invite" if cpba == 0 else f"Niveau {cpba}", "Éviter l'élévation silencieuse.")
    admins = as_list(d.get("admins"))
    if admins:
        add("Comptes", "Administrateurs locaux", "ALERTE" if len(admins) > 3 else "INFO",
            f"{len(admins)} : " + ", ".join(admins), "Limiter le groupe aux comptes nécessaires (LAPS).")
    if "guest" in d:
        add("Comptes", "Compte Invité", "ALERTE" if d["guest"] else "OK", "Activé" if d["guest"] else "Désactivé")
    if "builtin_admin" in d:
        add("Comptes", "Administrateur intégré (RID 500)", "ALERTE" if d["builtin_admin"] else "OK",
            "Activé" if d["builtin_admin"] else "Désactivé", "Désactiver ou gérer via LAPS.")
    auto = str(reg(HKLM, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon", "AutoAdminLogon", "0"))
    add("Comptes", "Ouverture de session automatique", "CRITIQUE" if auto == "1" else "OK",
        "Activée (mot de passe en clair possible)" if auto == "1" else "Désactivée")

    # --- Durcissement
    if "smb1" in d:
        add("Réseau", "SMBv1 (serveur)", "CRITIQUE" if d["smb1"] else "OK", "Activé" if d["smb1"] else "Désactivé",
            "Désactiver SMBv1 (WannaCry).")
    rdp_off = reg(HKLM, r"SYSTEM\CurrentControlSet\Control\Terminal Server", "fDenyTSConnections", 1)
    nla = reg(HKLM, r"SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp", "UserAuthentication", 1)
    if rdp_off == 0:
        add("Réseau", "Bureau à distance (RDP)", "OK" if nla == 1 else "CRITIQUE",
            "Activé avec NLA" if nla == 1 else "Activé SANS NLA", "Exiger NLA ; restreindre RDP au VPN/admin.")
    else:
        add("Réseau", "Bureau à distance (RDP)", "OK", "Désactivé")
    llmnr = reg(HKLM, r"SOFTWARE\Policies\Microsoft\Windows NT\DNSClient", "EnableMulticast", None)
    add("Réseau", "LLMNR", "OK" if llmnr == 0 else "ALERTE", "Désactivé" if llmnr == 0 else "Actif (défaut)",
        "Désactiver par GPO (empoisonnement Responder).")
    wd = reg(HKLM, r"SYSTEM\CurrentControlSet\Control\SecurityProviders\WDigest", "UseLogonCredential", 0)
    add("Identifiants", "WDigest (mots de passe en mémoire)", "CRITIQUE" if wd == 1 else "OK",
        "Activé" if wd == 1 else "Désactivé", "UseLogonCredential=0.")
    ppl = reg(HKLM, r"SYSTEM\CurrentControlSet\Control\Lsa", "RunAsPPL", 0)
    add("Identifiants", "Protection LSA (RunAsPPL)", "OK" if ppl in (1, 2) else "ALERTE",
        "Activée" if ppl in (1, 2) else "Désactivée", "Activer RunAsPPL contre le vol d'identifiants (Mimikatz).")
    if d.get("psv2"):
        add("Durcissement", "PowerShell v2", "ALERTE" if d["psv2"] == "Enabled" else "OK",
            "Installé" if d["psv2"] == "Enabled" else "Absent", "Supprimer PowerShell 2.0 (contournement de journalisation).")
    sbl = reg(HKLM, r"SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging", "EnableScriptBlockLogging", 0)
    add("Journalisation", "PowerShell Script Block Logging", "OK" if sbl == 1 else "ALERTE",
        "Activé" if sbl == 1 else "Désactivé", "Activer par GPO (visibilité SOC).")

    # --- Mises à jour
    if d.get("hf_date"):
        days = d.get("hf_days", 0)
        add("Mises à jour", "Dernier correctif installé", "OK" if days <= 35 else "ALERTE" if days <= 60 else "CRITIQUE",
            f"{d.get('hf_id')} le {d['hf_date']} ({days} j)", "Lancer Windows Update.")
    pending = (reg_exists(HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired")
               or reg_exists(HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"))
    add("Mises à jour", "Redémarrage en attente", "ALERTE" if pending else "OK", "Oui" if pending else "Non",
        "Redémarrer pour finaliser les mises à jour.")
    add("Système", "Version", "INFO", f"{d.get('os', '')} (build {d.get('build', '')})")
    return out


def posture_score(checks):
    scored = [c for c in checks if c["status"] != "INFO"]
    if not scored:
        return None
    pts = sum({"OK": 1, "ALERTE": 0.4, "CRITIQUE": 0}[c["status"]] for c in scored)
    return round(100 * pts / len(scored))


# ===================================================================== 2. processus suspects
SYSTEM_NAMES = {"svchost.exe", "lsass.exe", "csrss.exe", "winlogon.exe", "services.exe", "smss.exe",
                "wininit.exe", "spoolsv.exe", "taskhostw.exe", "dllhost.exe", "conhost.exe",
                "rundll32.exe", "lsm.exe", "sihost.exe", "fontdrvhost.exe"}
_hash_cache = {}


def sha256(path, max_size=300 * 1024 * 1024):
    try:
        st = os.stat(path)
        key = (path, st.st_mtime, st.st_size)
        if key in _hash_cache:
            return _hash_cache[key]
        if st.st_size > max_size:
            return "(fichier trop volumineux)"
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _hash_cache[key] = h.hexdigest()
        return _hash_cache[key]
    except OSError:
        return ""


def signatures(paths):
    """{chemin: (statut, éditeur)} via Get-AuthenticodeSignature (lot)."""
    if not IS_WIN or not paths:
        return {}
    fd, tmp = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(paths))
    script = (f"Get-Content -LiteralPath '{tmp}' -Encoding UTF8 | ForEach-Object {{ $s=Get-AuthenticodeSignature -LiteralPath $_;"
              " [pscustomobject]@{p=$_; s=[string]$s.Status; c=if($s.SignerCertificate){$s.SignerCertificate.Subject}else{''}} }"
              " | ConvertTo-Json -Compress")
    try:
        res = as_list(ps_json(script, 180))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    out = {}
    for r in res:
        cn = re.search(r"CN=([^,]+)", r.get("c") or "")
        out[r.get("p")] = (r.get("s") or "?", cn.group(1).strip('"') if cn else "")
    return out


def suspicious_processes(procs):
    """procs : liste du Sampler. Renvoie une ligne par processus avec score de risque."""
    exes = sorted({p["exe"] for p in procs if p["exe"]})
    sigs = signatures(exes)
    rmm = _rmm_index()
    sysroot = os.environ.get("SystemRoot", r"C:\Windows").lower()
    rows = []
    for p in procs:
        exe = p["exe"]
        score, why = 0, []
        status, signer = sigs.get(exe, ("N/A" if not IS_WIN else "?", ""))
        if not exe:
            status = "inaccessible"
        elif IS_WIN:
            if status == "NotSigned":
                score += 2
                why.append("non signé")
            elif status not in ("Valid", "?"):
                score += 3
                why.append(f"signature {status}")
        s2, w2 = command_risk(exe)
        score += s2
        why += w2
        name = p["name"].lower()
        if exe and IS_WIN and name in SYSTEM_NAMES:
            d = os.path.dirname(exe).lower()
            if d not in (sysroot + r"\system32", sysroot + r"\syswow64", sysroot):
                score += 5
                why.append("imite un processus système hors de System32")
        tool = next((t for t, pats in rmm.items() if any(x in name for x in pats)), None)
        if tool:
            score += 1
            why.append(f"outil d'accès distant ({tool})")
        rows.append({**p, "sig": status, "signer": signer, "score": score,
                     "level": risk_level(score), "why": ", ".join(why)})
    for r in rows:   # empreintes : seulement pour ce qui mérite un coup d'œil (rapide)
        r["sha256"] = sha256(r["exe"]) if r["exe"] and r["score"] > 0 else ""
    return rows


# ===================================================================== 3. accès à distance
RMM_TOOLS = {
    "AnyDesk": ["anydesk"], "TeamViewer": ["teamviewer", "tv_w32", "tv_x64"], "RustDesk": ["rustdesk"],
    "ScreenConnect / ConnectWise": ["screenconnect", "connectwisecontrol"], "Splashtop": ["splashtop", "srservice", "strwinclt"],
    "LogMeIn / GoTo": ["logmein", "lmiguardian", "gotoassist", "goto resolve"], "VNC": ["vnc"],
    "Ammyy Admin": ["ammyy"], "UltraViewer": ["ultraviewer"], "Supremo": ["supremo"], "DWService": ["dwagent", "dwservice"],
    "Atera": ["atera"], "NinjaOne": ["ninjarmm", "ninjaone"], "Kaseya": ["kaseya", "agentmon"], "Radmin": ["radmin", "rserver3"],
    "Chrome Remote Desktop": ["remoting_host", "chrome remote desktop"], "Assistance rapide": ["quickassist"],
    "Parsec": ["parsec"], "MeshCentral": ["meshagent"], "NetSupport": ["client32", "netsupport"],
    "Zoho Assist": ["zohoassist", "zaservice"], "Remote Utilities": ["rutserv", "rfusclient", "remote utilities"],
    "BeyondTrust / Bomgar": ["bomgar"], "Action1": ["action1"], "Getscreen": ["getscreen"], "Level": ["level.exe", "levelagent"],
}


def _rmm_index():
    return RMM_TOOLS


def _match(text):
    t = (text or "").lower()
    return next((tool for tool, pats in RMM_TOOLS.items() if any(p in t for p in pats)), None)


def remote_access(installed_apps=None):
    """Détecte les outils d'accès distant : processus, services, logiciels installés + état RDP."""
    found = []
    conns = {}
    try:
        for c in psutil.net_connections(kind="inet"):
            if c.pid and c.raddr:
                conns.setdefault(c.pid, set()).add(c.raddr.ip)
    except (psutil.Error, OSError):
        pass
    for p in psutil.process_iter(["name", "exe", "username"], ad_value=""):
        tool = _match(p.info["name"]) or _match(p.info["exe"])
        if tool:
            ips = conns.get(p.pid, set())
            found.append({"tool": tool, "how": "Processus actif", "detail": f"{p.info['name']} (PID {p.pid}) — {p.info['exe']}",
                          "status": "ALERTE" if ips else "INFO",
                          "conns": ", ".join(sorted(ips))[:200] or "aucune"})
    if IS_WIN:
        for s in psutil.win_service_iter():
            try:
                d = s.as_dict()
            except (psutil.Error, OSError):
                continue
            tool = _match(d["name"]) or _match(d["display_name"]) or _match(d["binpath"])
            if tool:
                found.append({"tool": tool, "how": f"Service ({d['status']}, {d['start_type']})",
                              "detail": f"{d['display_name']} — {d['binpath']}",
                              "status": "ALERTE" if d["start_type"] == "automatic" else "INFO", "conns": ""})
    if installed_apps is None:
        from pages.installed_apps import _collect as _apps
        installed_apps = _apps(False)
    for a in installed_apps:
        tool = _match(a["name"])
        if tool:
            found.append({"tool": tool, "how": "Logiciel installé", "detail": f"{a['name']} {a['ver']} ({a['pub']})",
                          "status": "INFO", "conns": ""})
    if IS_WIN:
        rdp_off = reg(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Terminal Server", "fDenyTSConnections", 1)
        listening = any(c.status == "LISTEN" and c.laddr and c.laddr.port == 3389
                        for c in _safe_conns())
        found.append({"tool": "Bureau à distance Windows (RDP)", "how": "Configuration",
                      "detail": ("Activé" if rdp_off == 0 else "Désactivé") + (" — écoute sur 3389" if listening else ""),
                      "status": "ALERTE" if rdp_off == 0 else "OK", "conns": ""})
    return found


def _safe_conns():
    try:
        return psutil.net_connections(kind="tcp")
    except (psutil.Error, OSError):
        return []


# ===================================================================== 4. persistance
TASKS_PS = r"""
Get-ScheduledTask -EA SilentlyContinue | Where-Object { $_.TaskPath -notlike '\Microsoft\*' } | ForEach-Object {
  [pscustomobject]@{ n=$_.TaskName; p=$_.TaskPath; s=[string]$_.State; u=[string]$_.Principal.UserId;
    a=(@($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)".Trim() }) -join ' | ');
    t=(@($_.Triggers | ForEach-Object { $_.CimClass.CimClassName -replace 'MSFT_Task','' -replace 'Trigger','' }) -join ',') }
} | ConvertTo-Json -Compress
"""
WMI_PS = r"""
$o=@(); try{ Get-CimInstance -Namespace root/subscription -ClassName __EventConsumer -EA Stop | ForEach-Object {
  $o += [pscustomobject]@{ n=[string]$_.Name; c=[string]$_.CimClass.CimClassName;
    v=[string]($_.CommandLineTemplate + $_.ScriptText + $_.ExecutablePath) } } }catch{}
ConvertTo-Json -InputObject @($o) -Compress
"""


def _service_path_risk(binpath):
    score, why = command_risk(binpath)
    b = (binpath or "").strip()
    low = b.lower()
    if b and not b.startswith('"') and " " in b.split(".exe")[0] and ".exe" in low:
        score += 2
        why.append("chemin non entre guillemets (élévation de privilèges)")
    if b and not any(x in low for x in ("\\windows\\", "\\program files", "%systemroot%", "\\systemroot\\",
                                         "system32", "\\programdata\\microsoft\\windows defender")):
        score += 1
        why.append("hors des dossiers système / Program Files")
    return score, why


def persistence():
    """Toutes les sources classiques de persistance avec un score de risque."""
    items = []

    def add(kind, name, cmd, detail, score, why):
        items.append({"kind": kind, "name": name, "cmd": cmd, "detail": detail,
                      "score": score, "level": risk_level(score), "why": ", ".join(why)})

    from pages.startup import _collect as startup_items
    for s in startup_items():
        sc, why = command_risk(s["cmd"])
        add("Démarrage", s["name"], s["cmd"], f"{s['source']} — {'activé' if s['enabled'] else 'désactivé'}", sc, why)
    if not IS_WIN:
        return items
    for t in as_list(ps_json(TASKS_PS, 90)):
        sc, why = command_risk(t.get("a", ""))
        if t.get("u", "").upper() in ("SYSTEM", "S-1-5-18") and sc:
            sc += 1
            why.append("s'exécute en SYSTEM")
        add("Tâche planifiée", (t.get("p") or "") + (t.get("n") or ""), t.get("a", ""),
            f"{t.get('s')} — déclencheur : {t.get('t') or '?'} — compte : {t.get('u') or '?'}", sc, why)
    for w in as_list(ps_json(WMI_PS, 60)):
        sc, why = command_risk(w.get("v", ""))
        add("Abonnement WMI", w.get("n", ""), w.get("v", ""), w.get("c", ""), sc + 3, why + ["consommateur WMI (rare en légitime)"])
    for s in psutil.win_service_iter():
        try:
            d = s.as_dict()
        except (psutil.Error, OSError):
            continue
        sc, why = _service_path_risk(d["binpath"] or "")
        if sc:
            add("Service", d["name"], d["binpath"], f"{d['display_name']} — {d['status']}, {d['start_type']}", sc, why)
    HKLM = winreg.HKEY_LOCAL_MACHINE
    ifeo = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"
    try:
        with winreg.OpenKey(HKLM, ifeo, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                dbg = reg(HKLM, f"{ifeo}\\{sub}", "Debugger")
                if dbg:
                    add("IFEO Debugger", sub, dbg, "Détournement de lancement d'exécutable", 5, ["clé Debugger IFEO"])
    except OSError:
        pass
    wl = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
    shell = str(reg(HKLM, wl, "Shell", "explorer.exe"))
    if shell.strip().lower() not in ("explorer.exe", ""):
        add("Winlogon", "Shell", shell, "Shell de session modifié", 5, ["Shell ≠ explorer.exe"])
    ui = str(reg(HKLM, wl, "Userinit", ""))
    if ui and ui.strip().rstrip(",").lower() not in (r"c:\windows\system32\userinit.exe",):
        add("Winlogon", "Userinit", ui, "Programme lancé à l'ouverture de session", 4, ["Userinit modifié"])
    appinit = reg(HKLM, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows", "AppInit_DLLs", "")
    if appinit and reg(HKLM, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows", "LoadAppInit_DLLs", 0) == 1:
        add("AppInit_DLLs", "AppInit_DLLs", appinit, "DLL injectée dans chaque processus", 5, ["AppInit_DLLs actif"])
    return items


# ===================================================================== 5. événements de sécurité
EVENT_LABELS = {
    4625: "Échec de connexion", 4624: "Connexion RDP réussie", 4720: "Compte créé", 4732: "Ajout à un groupe local",
    4740: "Compte verrouillé", 1102: "Journal Sécurité effacé", 104: "Journal système effacé",
    7045: "Nouveau service installé", 1116: "Defender : menace détectée", 1117: "Defender : action sur menace",
    5001: "Defender : temps réel désactivé",
}
LOGON_TYPES = {"2": "interactif", "3": "réseau", "4": "batch", "5": "service", "7": "déverrouillage",
               "8": "réseau (clair)", "9": "runas /netonly", "10": "RDP", "11": "cache"}


def _events_ps(hours):
    ms = int(hours * 3600 * 1000)
    return rf"""
$st=(Get-Date).AddHours(-{hours}); $out=New-Object System.Collections.ArrayList
function Add-Ev($e){{ [void]$out.Add([pscustomobject]@{{id=$e.Id; t=$e.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'); log=$e.LogName;
   p=@($e.Properties | ForEach-Object {{[string]$_.Value}}); m=(([string]$e.Message -split "`n")[0]).Trim()}}) }}
$q=@(@{{LogName='Security';Id=4625,4720,4732,4740,1102;StartTime=$st}},
     @{{LogName='System';Id=7045,104;StartTime=$st}},
     @{{LogName='Microsoft-Windows-Windows Defender/Operational';Id=1116,1117,5001;StartTime=$st}})
foreach($f in $q){{ try{{ Get-WinEvent -FilterHashtable $f -MaxEvents 3000 -EA Stop | ForEach-Object {{ Add-Ev $_ }} }}
  catch{{ [void]$out.Add([pscustomobject]@{{id=-1;t='';log=$f.LogName;p=@();m=$_.Exception.Message}}) }} }}
try{{ Get-WinEvent -LogName Security -MaxEvents 500 -EA Stop -FilterXPath "*[System[(EventID=4624) and TimeCreated[timediff(@SystemTime) <= {ms}]] and EventData[Data[@Name='LogonType']='10']]" | ForEach-Object {{ Add-Ev $_ }} }}catch{{}}
ConvertTo-Json -InputObject @($out) -Compress -Depth 3
"""


def security_events(hours=24):
    """Renvoie (événements, alertes, notes)."""
    if not IS_WIN:
        return [], [], ["Journaux d'événements Windows uniquement."]
    raw = as_list(ps_json(_events_ps(hours), 180))
    events, notes = [], []
    for e in raw:
        eid, p = e.get("id"), [str(x) for x in as_list(e.get("p"))]
        if eid == -1:
            m = e.get("m", "")
            if not re.search(r"match|correspond|aucun", m, re.I):
                notes.append(f"{e.get('log')} : {m[:160]}")
            continue
        g = (lambda i: p[i] if i < len(p) else "")
        user = src = detail = ""
        sev = "ALERTE"
        if eid == 4625:
            user, src = f"{g(6)}\\{g(5)}".strip("\\"), g(19) or g(13)
            detail = f"type {LOGON_TYPES.get(g(10), g(10))} — {g(18) or ''}".strip(" —")
            sev = "INFO"
        elif eid == 4624:
            user, src, detail = f"{g(6)}\\{g(5)}".strip("\\"), g(18), f"poste {g(11)}"
            sev = "INFO"
        elif eid == 4720:
            user, detail = g(0), f"créé par {g(4)}"
        elif eid == 4732:
            user, detail = g(0) or g(1), f"ajouté à {g(2)} par {g(6)}"
            sev = "CRITIQUE" if g(4) == "S-1-5-32-544" else "ALERTE"
        elif eid == 4740:
            user, src = g(0), g(1)
        elif eid in (1102, 104):
            sev, detail = "CRITIQUE", e.get("m", "")
        elif eid == 7045:
            user, detail = g(4), f"{g(0)} — {g(1)}"
            sc, why = _service_path_risk(g(1))
            sev = risk_level(sc + 1) if sc else "INFO"
        elif eid in (1116, 1117, 5001):
            sev, detail = "CRITIQUE", e.get("m", "")
        events.append({"t": e.get("t", ""), "log": e.get("log", "").split("/")[0], "id": eid,
                       "label": EVENT_LABELS.get(eid, str(eid)), "user": user, "src": src,
                       "detail": detail or e.get("m", ""), "sev": sev})
    alerts = []
    fails = Counter((ev["user"], ev["src"]) for ev in events if ev["id"] == 4625)
    for (u, s), n in fails.most_common():
        if n >= 10:
            alerts.append(("CRITIQUE", f"Force brute probable : {n} échecs pour « {u} » depuis {s or 'local'}"))
        elif n >= 5:
            alerts.append(("ALERTE", f"{n} échecs de connexion pour « {u} » depuis {s or 'local'}"))
    for ev in events:
        if ev["sev"] == "CRITIQUE":
            alerts.append(("CRITIQUE", f"{ev['t']} — {ev['label']} {ev['user']} {ev['detail'][:120]}"))
    rdp = [ev for ev in events if ev["id"] == 4624]
    if rdp:
        alerts.append(("INFO", f"{len(rdp)} connexion(s) RDP réussie(s) sur la période"))
    return events, alerts, notes


def local_admins():
    if not IS_WIN:
        return []
    d = ps_json("@(Get-LocalGroupMember -SID 'S-1-5-32-544' -EA SilentlyContinue | ForEach-Object {[string]$_.Name}) "
                "| ConvertTo-Json -Compress", 30)
    return [str(x) for x in as_list(d)]
