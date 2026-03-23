# 🔄 No-IP Renewer — Docker Edition

**Automatically confirm your No-IP free hostnames before they expire.**  
Runs inside Docker on your Synology NAS — residential IP, no cloud blocks, no manual clicks.

<div align="center">

![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-Chromium-45BA4B?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

</div>

---

## ✨ Features

| | |
|---|---|
| 🏠 **Runs on your NAS** | Uses your residential IP — No-IP never blocks it |
| 🔐 **2FA Support** | Handles No-IP TOTP 2FA automatically |
| ⏰ **Smart Scheduler** | Set run time in your local timezone, it runs automatically |
| 📊 **Live Log** | Watch every step in real-time from the web UI |
| 🔄 **One-click Update** | Pull latest code from GitHub and restart — all from the UI |
| 💾 **Persistent Config** | Credentials and schedule saved in Docker volume |
| 🌐 **Web UI** | Full config interface at `http://nas-ip:7895` |

---

## 🌐 Web UI Pages

| URL | Description |
|---|---|
| `http://nas-ip:7895/` | Landing page |
| `http://nas-ip:7895/setup` | Step-by-step Portainer setup guide |
| `http://nas-ip:7895/config` | Config, schedule, run, live log |

---

## 🚀 Quick Start (Portainer)

### Step 1 — Fork this repo

Click **"Use this template"** → **"Create a new repository"** → set to **Private**.

### Step 2 — Create Stack in Portainer

1. Portainer → **Stacks → Add stack**
2. Name: `noip-renewer`
3. Select **"Repository"** tab:
   - Repository URL: `https://github.com/W00DFISH/noip-renewer-docker`
   - Reference: `main`
   - Compose path: `docker-compose.yml`
4. Click **"Deploy the stack"**

> First build takes 3–5 minutes (installs Chromium). Subsequent starts are instant.

### Step 3 — Open the Web UI

Go to `http://nas-ip:7895` → **⚙️ Config** → enter your credentials → **Save** → **▶ Run Now**

---

## ⚙️ Environment Variables

Only 2 optional variables in `docker-compose.yml` — everything else is configured via the web UI:

| Variable | Default | Description |
|---|---|---|
| `CONTAINER_NAME` | `noip-renewer` | Container name for self-restart on update |
| `GITHUB_REPO` | `https://github.com/W00DFISH/noip-renewer-docker` | Repo URL for self-update |

> ⚠️ **Do NOT put No-IP credentials in docker-compose.** Enter them in the web UI instead — they are stored securely in a Docker volume.

---

## 🔐 Getting Your TOTP Key (2FA users)

1. Log in to No-IP → **Account → Security → Two-Factor Authentication**
2. When setting up 2FA, next to the QR code there is a plain-text key like `JBSWY3DPEHPK3PXP`
3. Paste it into the **TOTP Key** field in the web UI

> If you already set up 2FA and didn't save the key — **disable then re-enable 2FA** to get a new one.

---

## 📁 File Structure

```
.
├── Dockerfile                  # Python 3.12 + Playwright Chromium + Docker CLI
├── docker-compose.yml          # Portainer stack config
├── app.py                      # Flask web app + APScheduler + Playwright runner
├── update.sh                   # Self-update script (git pull + docker restart)
├── requirements.txt            # flask, playwright, pyotp, apscheduler, requests
├── templates/
│   ├── landing.html            # Landing page with features overview
│   ├── setup.html              # Step-by-step Portainer setup guide
│   └── index.html              # Config UI with run, schedule, live log
└── README.md
```

---

## 🔄 Self-Update Flow

When you click **"⬇️ Update Now"** in the web UI:

```
1. git clone latest code from GitHub → /tmp
2. Copy app.py + templates into running container
3. Save new commit SHA to config
4. docker restart noip-renewer (via Docker socket)
5. Container restarts with new code — page reloads automatically
```

No SSH. No Portainer. No manual steps.

---

## 📊 Reading the Live Log

| Log line | Meaning |
|---|---|
| `✅ Login successful!` | Logged in to No-IP |
| `Found N host(s) needing confirmation` | N hosts expiring soon |
| `✓ hostname confirmed!` | Host successfully renewed ✅ |
| `❌ Could not confirm` | Something went wrong — check log details |
| `Session lost — redirected to login` | Credentials wrong or session expired |

---

## 🛠️ Manual Docker Run (without Portainer)

```bash
# Build
docker build -t noip-renewer-web .

# Run
docker run -d \
  --name noip-renewer \
  -p 7895:7895 \
  -v noip_data:/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --restart unless-stopped \
  noip-renewer-web
```

---

## 📝 Notes

- **Why Docker on NAS and not GitHub Actions?** No-IP blocks datacenter IPs (Azure/GitHub). Your NAS uses a residential IP which is never blocked.
- **Why Playwright and not the DynDNS API?** The DynDNS API updates the IP but does **not** reset the 30-day confirmation timer on free accounts. Browser automation is required to click the Confirm button.
- **Is it safe to store credentials in the app?** Credentials are stored in a Docker volume on your own NAS, encrypted at the filesystem level. They never leave your machine.

---

## 👤 Author

**W00DFISH** — [github.com/W00DFISH](https://github.com/W00DFISH)
