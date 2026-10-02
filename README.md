# NexTask — gestionnaire des tâches alternatif (inspiré de TMOG)

Outil Windows en **Python + PySide6 + psutil** : 21 modules (supervision, sécurité, dépannage, rapport), thème clair/sombre, journal d'audit, syslog, sans dépendance lourde.

## Démarrage rapide (Windows)

1. Installer Python 3.10+ (cocher « Add to PATH »).
2. Double-cliquer **`run.bat`** (installe PySide6 + psutil au 1er lancement).
3. Pour tout voir (services, connexions de tous les processus, températures) : bouton **« Relancer en admin »** dans la barre d'état.
4. Pour un `.exe` autonome : **`build.bat`** → `dist\NexTask\NexTask.exe` (demande l'élévation UAC automatiquement).

## Interface (v3)

- **Design system** (`core/design.py`) : thème « console SOC » sombre + thème clair, tokens de couleurs, espacements (grille de 4 px) et rayons ; contrastes vérifiés automatiquement (`audit_contrast()` : texte ≥ 4,5:1, éléments graphiques ≥ 3:1).
- **Navigation** : menu latéral groupé (Surveillance, Système, Réseau, Sécurité, Opérations), repliable, icônes vectorielles maison, badge d'alertes sur l'Enregistreur.
- **Palette de commandes** `Ctrl+K` : aller à n'importe quelle page ou lancer une action (bilan de sécurité, rapport, comparaison de référence…).
- **Raccourcis** : `Ctrl+K` palette · `Ctrl+B` replier le menu · `Ctrl+1…9` pages · `Ctrl+T` thème · `F5` actualiser la page.
- **Composants** : graphes lissés avec dégradé et valeur au survol, jauges circulaires animées, tuiles KPI, pastilles de sévérité (couleur + libellé) et mini-barres dans les tableaux, états vides explicites, notifications « toast », barre d'activité pendant les analyses.

## Modules

| Module | Ce qu'il fait | Actions |
|---|---|---|
| **Summary** | Tuiles CPU / RAM / disque / réseau, top CPU & mémoire, alertes santé | — |
| **Performance** | Graphes 60 s CPU (global ou par cœur), mémoire, chaque disque, chaque carte réseau | — |
| **Processes** | Liste triable/filtrable : CPU, RAM, disque/s, threads, priorité, chemin | Fin de tâche, terminer l'arborescence, suspendre/reprendre, priorité, emplacement, détails (cmdline, DLL, fichiers, connexions) |
| **System Info** | OS, carte mère, BIOS, CPU, barrettes RAM, GPU, disques, volumes, cartes réseau (WMI) | Copier le rapport |
| **App history** | Temps CPU et E/S disque cumulés par application, persistés (`%APPDATA%\NexTask`) | Réinitialiser |
| **Startup apps** | Registre Run (HKCU/HKLM/32 bits) + dossiers Démarrage | Activer/désactiver (même mécanisme `StartupApproved` que Windows, réversible) |
| **Users** | Ressources par utilisateur + sessions ouvertes | Déconnecter, fermer la session |
| **Services** | Tous les services : état, type de démarrage, PID, compte, binaire | Démarrer, arrêter, redémarrer, changer le type de démarrage |
| **Power & Freq** | Fréquence CPU, charge, batterie, températures, plans d'alimentation | Changer de plan, rapport batterie, rapport énergie `powercfg` |
| **Flight Recorder** | Boîte noire SQLite : instantanés toutes les N s + événements (CPU/RAM/disque > seuil) | Rejouer avec le curseur, aller à un événement, export CSV |
| **Connections** | Connexions TCP/UDP par processus, DNS inverse, filtre « vers Internet » | Réputation IP (AbuseIPDB, VirusTotal, ipinfo), **bloquer l'IP dans le pare-feu**, tuer le processus |
| **Installed Apps** | Logiciels (registre Uninstall) + apps Store en option | Désinstaller, emplacement, export CSV |
| **Drivers** | Pilotes PnP (version, date, signature), pilotes noyau, périphériques en erreur | Filtres « non signés » / « plus de 5 ans » |
| **Disk Space** | Volumes, caches/temp, analyseur de dossiers (arbre + 200 plus gros fichiers) | Ouvrir dans l'Explorateur, Nettoyage de disque |

### Modules ADMIN (V2)

| Module | Ce qu'il fait | Actions |
|---|---|---|
| **Security › Bilan du poste** | Score /100 : Defender (actif, temps réel, âge signatures, Tamper), pare-feu par profil, BitLocker, Secure Boot, UAC, admins locaux, Invité, RID 500, AutoAdminLogon, SMBv1, RDP/NLA, LLMNR, WDigest, LSA RunAsPPL, PowerShell v2, Script Block Logging, dernier KB, redémarrage en attente | Export CSV |
| **Security › Processus suspects** | Signature Authenticode, emplacement modifiable, imitation de processus système hors System32, LOLBins, outils RMM ; SHA-256 des éléments à risque | VirusTotal par hash, copier hash, fin de tâche |
| **Security › Accès à distance** | AnyDesk, TeamViewer, RustDesk, ScreenConnect, Splashtop, VNC, Atera, NinjaOne, MeshAgent… (processus, services, logiciels) + IP connectées + état RDP | — |
| **Security › Persistance** | Clés Run, dossiers Démarrage, tâches planifiées hors Microsoft, abonnements WMI, services à chemin anormal ou non entre guillemets, IFEO Debugger, Winlogon Shell/Userinit, AppInit_DLLs | Désactiver une tâche planifiée |
| **Security › Événements** | 4625 (+ détection force brute), 4624 type 10 (RDP), 4720, 4732 (alerte si Administrateurs), 4740, 1102/104, 7045, Defender 1116/1117/5001 — 24 h / 72 h / 7 j | Réputation IP |
| **Network Tools** | Ping, traceroute, DNS (A/AAAA/CNAME/MX/NS/TXT + nslookup), test de ports TCP (plages), IP publique ; ipconfig, routes, ARP, Wi-Fi, DNS, cache DNS, hosts, proxy, netstat | — |
| **Toolbox › Réparations** | 16 actions : cache DNS, renouveler IP, Winsock/IP reset, file d'impression, Explorateur, audio, heure, gpupdate, caches Teams / Chrome / Edge, temp, SFC, DISM, reset Windows Update, signatures et analyse Defender | Confirmation + audit |
| **Toolbox › Windows Update** | Historique (échecs + code HRESULT), mises à jour en attente | — |
| **Toolbox › Journal d'audit** | Qui / quand / quoi / résultat pour **toutes** les actions faites dans NexTask | Export CSV |
| **Baseline** | Référence du poste (services, démarrage, logiciels, pilotes, ports en écoute, admins locaux, tâches, KB) puis comparaison avec l'état actuel ou entre deux références | Export du différentiel |
| **Identity & Shares** | `dsregcmd /status` (Entra ID / domaine / PRT), canal sécurisé DC, GPO (`gpresult`), certificats (expirés / < 30 j), partages SMB, sessions, fichiers ouverts, lecteurs mappés, comptes locaux | Fermer session/fichier SMB, rapport GPO HTML |
| **Report** | Rapport de diagnostic (synthèse + sections au choix) avec n° de ticket, technicien, contexte | HTML, **PDF**, synthèse texte à coller dans GLPI |
| **Settings** | Notifications Windows, réduction dans la zone de notification, lancement à l'ouverture de session, **syslog RFC 5424 UDP/TCP** (Security Onion, Wazuh, Graylog) | Message de test |

Toutes les tables : recherche, tri par colonne, clic droit, **export CSV**. Toute action destructive demande une confirmation.

## Structure

```
main.py              fenêtre, menu latéral, barre d'état
core/common.py       utilitaires (formatage, commandes, admin, threads)
core/sampler.py      collecte centrale (métriques 1 s, processus 2 s, en arrière-plan)
core/widgets.py      graphe, tuiles, tableau filtrable, page de base
core/theme.py        thèmes QSS
core/audit.py        journal d'audit SQLite + envoi syslog
core/security_checks.py  collecteurs sécurité (réutilisés par Security, Report, Baseline)
pages/*.py           un fichier par module
```

Ajouter un module = créer `pages/mon_module.py` (classe héritant de `Page`) + une ligne dans `MENU` de `main.py`.

## Limites connues

- V1 validée sur Windows. **V2 (modules ADMIN)** : testée sous Linux hors écran + syntaxe de tous les scripts PowerShell vérifiée avec le parseur PowerShell 7 ; **la logique Windows (registre, WMI, journaux d'événements, Defender) reste à valider sur ton poste**.
- Lancer en **administrateur** pour : BitLocker, Secure Boot, journal Sécurité, sessions SMB, GPO ordinateur, réparations 🛡.
- Le démarrage automatique en mode admin passe par une tâche planifiée « privilèges les plus élevés » (Windows bloque les programmes élevés lancés depuis la clé Run).
- Pas de GPU par processus ni de réseau par application (nécessite ETW/compteurs GPU).
- Températures : dépend des capteurs ACPI exposés ; pour des valeurs par cœur, il faudra LibreHardwareMonitor (V2).
- Fréquence par cœur : Windows n'expose qu'une valeur globale via psutil.

## Pistes V3

Vue arborescente des processus · GPU (compteurs « GPU Engine ») · réseau par processus (ETW) · températures par cœur (LibreHardwareMonitor) · export vers GLPI par API.
