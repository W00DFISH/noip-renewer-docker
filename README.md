# 🔄 No-IP Renewer — Docker Edition

**Automatically confirm your No-IP free hostnames before they expire.**  
Runs inside Docker on your Synology NAS — residential IP, no cloud blocks, no manual clicks.

<div align="center">

![Version](https://img.shields.io/badge/version-1.0.16-green?style=flat-square)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)

</div>

---

## ✨ Features

| | |
|---|---|
| 🏠 **Runs on your NAS** | Uses your residential IP — No-IP never blocks it |
| 🔐 **2FA Support** | Handles No-IP TOTP 2FA automatically |
| 👤 **Multi-account** | Manage multiple No-IP accounts from one UI |
| ⏰ **Smart Scheduler** | Set run time in your local timezone |
| 📊 **Run History** | 7-day history log showing all runs |
| 🔄 **One-click Update** | Pull from GitHub and restart from the web UI |
| 💾 **Persistent Config** | Credentials saved in Docker volume |

---

## 🌐 Web UI

| URL | Description |
|---|---|
| `http://nas-ip:7895/` | Landing page |
| `http://nas-ip:7895/setup` | Step-by-step Portainer setup guide |
| `http://nas-ip:7895/config` | Config, accounts, run, history |

---

## 🚀 Quick Start (Portainer)

1. Fork this repo → **Use this template** → **Private**
2. Portainer → **Stacks → Add stack → Repository**
   - URL: `https://github.com/W00DFISH/noip-renewer-docker`
   - Branch: `main`
   - Compose path: `docker-compose.yml`
3. Deploy → open `http://nas-ip:7895`

---

## 📁 File Structure

```
.
├── .github/workflows/
│   └── update-readme.yml    # Auto-updates this README with commit log
├── Dockerfile
├── docker-compose.yml
├── app.py                   # Flask web app + scheduler + Playwright
├── update.sh                # Self-update script
├── requirements.txt
├── VERSION
├── templates/
│   ├── landing.html
│   ├── setup.html
│   └── index.html
└── README.md
```

---

## 📋 Commit Log

| Date (GMT+7) | SHA | Message |
|---|---|---|
| *(Auto-updated by GitHub Actions on every push)* | | |
