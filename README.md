

## Operations

See [`ops/README.md`](ops/README.md) for the full operations guide.

Quick reference:

```powershell
.\ops\bot.ps1 status       # morning health check
.\ops\bot.ps1 update       # git pull + restart (< 30 s downtime)
.\ops\bot.ps1 disconnect   # safe RDP detach — ALWAYS use this instead of closing RDP
.\ops\bot.ps1 logs         # tail detector log
```

**New VM setup:** clone repo → install MT5 → copy `.env` → run `.\ops\install.ps1` as Administrator → `.\ops\bot.ps1 status`

> **Never close the RDP window with the X button.** Use `.\ops\bot.ps1 disconnect` or the **Deconnexion Safe** desktop shortcut. Closing RDP suspends the session and kills MT5 IPC.
