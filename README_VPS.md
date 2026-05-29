# Déploiement VPS Windows — XAUUSD ICT Bot

Guide de déploiement sur un VPS Windows Server (mono-machine : détecteur + backend).

---

## Prérequis

- Windows Server 2019/2022 (ou Windows 10/11)
- Python 3.11+ installé et dans le PATH
- MetaTrader 5 installé et connecté à ton broker
- [NSSM](https://nssm.cc/download) téléchargé (ex. `C:\tools\nssm\win64\nssm.exe`)
- Git

---

## 1. Cloner le projet

```powershell
git clone https://github.com/elabdioui/xauusd.git C:\bots\xauusd-bot
cd C:\bots\xauusd-bot
```

---

## 2. Configurer les variables d'environnement

```powershell
copy .env.example .env
notepad .env
```

Remplir toutes les valeurs (voir commentaires dans `.env.example`).  
Le fichier `.env` à la racine est chargé automatiquement par le détecteur et le backend.

> **Important — secrets à configurer avant le démarrage :**
> - `WEBHOOK_HMAC_SECRET` : générer avec `python -c "import secrets; print(secrets.token_hex(32))"`
> - `GROQ_API_KEY` : obtenir sur [console.groq.com](https://console.groq.com)
> - `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` : créer un bot via [@BotFather](https://t.me/BotFather)
> - `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` : identifiants de ton compte broker

---

## 3. Installer les dépendances

```powershell
# Backend
cd C:\bots\xauusd-bot\backend
pip install -r requirements.txt

# Détecteur
cd C:\bots\xauusd-bot\detector
pip install -r requirements.txt
```

---

## 4. Test manuel (avant d'installer les services)

**Terminal 1 — Backend :**
```powershell
cd C:\bots\xauusd-bot
.\scripts\start_backend.ps1
```
Vérifier : `http://localhost:8000/health` doit retourner `{"status":"ok"}`.

**Terminal 2 — Signal mocké :**
```powershell
cd C:\bots\xauusd-bot
python tests/send_mock_signal.py
```
Doit retourner `status: ok` et envoyer un message Telegram.

**Terminal 3 — Détecteur (MT5 doit être ouvert) :**
```powershell
.\scripts\start_detector.ps1
```

---

## 5. Installer les services Windows avec NSSM

Les services démarrent automatiquement au boot et redémarrent en cas de crash.

```powershell
# Ouvrir PowerShell en tant qu'Administrateur
cd C:\bots\xauusd-bot
.\scripts\install_nssm.ps1 -NssmPath "C:\tools\nssm\win64\nssm.exe"
```

Vérifier les services :
```powershell
Get-Service xauusd-*
```

Commandes utiles :
```powershell
Start-Service xauusd-backend
Stop-Service xauusd-detector
Restart-Service xauusd-backend
# Voir les logs en direct :
Get-Content logs\backend.log -Wait -Tail 50
Get-Content logs\detector.log -Wait -Tail 50
```

---

## 6. Anti-hibernation (si hébergeur coupe les process inactifs)

Configurer un monitor HTTP externe vers `http://<IP-VPS>:8000/health` toutes les 5 minutes.  
Service gratuit : [UptimeRobot](https://uptimerobot.com).

---

## 7. Rotation des secrets

> **Action manuelle obligatoire si les secrets ont été exposés :**
> 1. Telegram : envoyer `/revoke` à [@BotFather](https://t.me/BotFather) → générer un nouveau token
> 2. `WEBHOOK_HMAC_SECRET` : générer une nouvelle valeur et mettre à jour `.env`
> 3. `GROQ_API_KEY` : révoquer et recréer sur [console.groq.com](https://console.groq.com)
> 4. Redémarrer les services après mise à jour du `.env`

---

## 8. Structure des logs

Les logs sont dans `logs/` à la racine du projet (rotation automatique à 10 MB, 5 fichiers) :

```
logs/
├── detector.log        ← logs du détecteur MT5
├── backend.log         ← logs du backend (si lancé via NSSM)
└── backend-error.log   ← stderr backend
```

---

## Architecture

```
VPS Windows Server
├── xauusd-backend  (service NSSM) → backend/main.py  :8000
│     LLM Groq + Telegram + News ForexFactory
└── xauusd-detector (service NSSM) → detector/main.py
      MT5 → scan XAUUSD → webhook HTTP localhost:8000/signal
```
