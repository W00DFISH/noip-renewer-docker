#!/usr/bin/env python3
"""No-IP Renewer Web App v2 — Flask + APScheduler + Playwright"""

import os, re, time, json, threading, logging, urllib.request
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app       = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

CONFIG_FILE   = "/data/config.json"
UPSTREAM_REPO = "W00DFISH/noip-renewer-docker"

run_logs   = []
run_status = {"running": False, "last_run": None, "last_result": None}

# ── Config ─────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "username":         "",
    "password":         "",
    "totp_key":         "",
    "schedule_enabled": False,
    "run_every_days":   1,
    "run_at_hour":      9,
    "gmt_offset":       7,
    "current_sha":      "",
    "current_version":  "",
}

def load_config():
    try:
        cfg = json.load(open(CONFIG_FILE))
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return dict(DEFAULT_CONFIG)

def save_config(cfg):
    os.makedirs("/data", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

# ── Version ────────────────────────────────────────────────────────────────────
def get_version():
    try:
        return open("/app/VERSION").read().strip()
    except Exception:
        return "unknown"

def get_build_time():
    try:
        gmt7 = timezone(timedelta(hours=7))
        ts   = os.path.getmtime("/app/VERSION")
        return datetime.fromtimestamp(ts, tz=gmt7).strftime("%Y-%m-%d %H:%M:%S GMT+7")
    except Exception:
        return "unknown"

APP_VERSION = get_version()
APP_BUILT   = get_build_time()

# ── GitHub API ─────────────────────────────────────────────────────────────────
def github_get(path):
    url = f"https://api.github.com/repos/{UPSTREAM_REPO}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "noip-renewer"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def get_latest_commit():
    data = github_get("commits/main")
    return {
        "sha":     data["sha"][:7],
        "message": data["commit"]["message"].split("\n")[0][:100],
        "date":    data["commit"]["author"]["date"][:10],
        "version": None,
    }

def get_commits(limit=15):
    commits = github_get(f"commits?per_page={limit}")
    return [{"sha": c["sha"][:7],
             "message": c["commit"]["message"].split("\n")[0][:100],
             "date": c["commit"]["author"]["date"][:10]}
            for c in commits]

# ── Logging ────────────────────────────────────────────────────────────────────
def add_log(msg):
    gmt7 = timezone(timedelta(hours=7))
    ts   = datetime.now(gmt7).strftime("%H:%M:%S")
    run_logs.append(f"[{ts}] {msg}")
    if len(run_logs) > 300:
        run_logs.pop(0)

# ── Playwright renew ───────────────────────────────────────────────────────────
def do_renew(cfg=None):
    global run_status
    if run_status["running"]:
        return
    if cfg is None:
        cfg = load_config()

    username = cfg.get("username", "")
    password = cfg.get("password", "")
    totp_key = cfg.get("totp_key", "")

    if not username or not password:
        add_log("❌ Missing username or password.")
        return

    run_logs.clear()
    gmt7 = timezone(timedelta(hours=7))
    run_status.update({
        "running":     True,
        "last_run":    datetime.now(gmt7).strftime("%Y-%m-%d %H:%M:%S GMT+7"),
        "last_result": None,
    })

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWT

        add_log("🚀 Starting browser...")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()

            add_log("🔐 Logging in...")
            page.goto("https://www.noip.com/login?ref_url=console", wait_until="networkidle", timeout=30_000)
            page.fill("#username", username)
            page.fill("#password", password)
            page.click("#clogs-captcha-button")
            try: page.wait_for_load_state("networkidle", timeout=10_000)
            except: pass

            cur = page.url
            add_log(f"Post-login: {cur}")

            if "2fa" in cur or "verify" in cur:
                add_log("🔑 2FA detected...")
                if not totp_key:
                    raise RuntimeError("2FA required but TOTP Key not set!")
                import pyotp
                code = pyotp.TOTP(totp_key).now()
                add_log(f"TOTP code: {code}")
                challenge = page.locator("#challenge_code").first
                challenge.click()
                page.keyboard.type(code, delay=50)
                page.click('button[name="submit"]', timeout=10_000)
                try: page.wait_for_load_state("networkidle", timeout=15_000)
                except: pass
                add_log(f"Post-2FA: {page.url}")

            add_log("✅ Login successful!")

            renewed = []
            while True:
                add_log("📋 Loading DNS records...")
                page.goto("https://my.noip.com/dns/records", wait_until="networkidle", timeout=30_000)
                time.sleep(2)

                if "login" in page.url:
                    raise RuntimeError("Session lost")

                try: page.locator("#zone-collection-wrapper").wait_for(timeout=15_000)
                except PWT:
                    add_log("No zone wrapper.")
                    break

                banners = page.locator('[id^="expiration-banner-hostname-"]').all()
                add_log(f"Found {len(banners)} host(s) needing confirmation.")
                if not banners:
                    add_log("✅ All good — nothing to confirm!")
                    break

                host = banners[0]
                host_name = "unknown"
                try:
                    h4 = host.locator("h4").first.inner_text(timeout=2_000)
                    host_name = re.sub(r'Expires in \d+ days - ', '', h4).strip()
                except: pass

                add_log(f"[{host_name}] Confirming...")
                confirmed = False

                try:
                    for btn in host.locator("button").all():
                        if btn.inner_text(timeout=1_000).strip().lower() == "confirm":
                            btn.click()
                            confirmed = True
                            add_log(f"[{host_name}] Clicked Confirm ✓")
                            time.sleep(2)
                            break
                except Exception as e:
                    add_log(f"[{host_name}] Button error: {e}")

                if not confirmed:
                    try:
                        hx_url = host.locator("button[hx-get]").first.get_attribute("hx-get", timeout=2_000)
                        if hx_url:
                            r = page.evaluate(f"""async()=>{{
                                const r=await fetch('{hx_url}',{{method:'GET',credentials:'include',
                                headers:{{'HX-Request':'true','HX-Current-URL':window.location.href}}}});
                                return{{status:r.status,ok:r.ok}};}}""")
                            if r.get("ok"):
                                confirmed = True
                                add_log(f"[{host_name}] HTMX confirmed ✓")
                    except Exception as e:
                        add_log(f"[{host_name}] HTMX error: {e}")

                if confirmed:
                    renewed.append(host_name)
                else:
                    add_log(f"[{host_name}] ❌ Could not confirm")
                    break

            browser.close()

        if renewed:
            run_status["last_result"] = f"success|✅ Renewed {len(renewed)}: {', '.join(renewed)}"
        else:
            run_status["last_result"] = "info|ℹ️ No hosts needed confirmation"
        add_log(run_status["last_result"].split("|")[1])

    except Exception as e:
        err = str(e)[:300]
        add_log(f"❌ Fatal: {err}")
        run_status["last_result"] = f"error|❌ Error: {err}"
    finally:
        run_status["running"] = False

# ── Schedule ───────────────────────────────────────────────────────────────────
def apply_schedule(cfg):
    scheduler.remove_all_jobs()
    if not cfg.get("schedule_enabled"):
        return
    offset   = int(cfg.get("gmt_offset", 7))
    run_hour = int(cfg.get("run_at_hour", 9))
    utc_hour = (run_hour - offset) % 24
    every    = int(cfg.get("run_every_days", 1))
    day_flt  = f"*/{every}" if every > 1 else "*"
    scheduler.add_job(func=do_renew, trigger=CronTrigger(hour=utc_hour, minute=0, day=day_flt),
                      id="noip_renew", replace_existing=True)
    add_log(f"⏰ Schedule: every {every} day(s) at {run_hour:02d}:00 (GMT+{offset})")

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def landing():
    return render_template("landing.html", version=APP_VERSION, built=APP_BUILT)

@app.route("/setup")
def setup_guide():
    return render_template("setup.html", version=APP_VERSION, built=APP_BUILT)

@app.route("/config")
def config_page():
    return render_template("index.html", config=load_config(), version=APP_VERSION, built=APP_BUILT)

@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.json or {}
    cfg  = load_config()
    for k in DEFAULT_CONFIG:
        if k in data:
            cfg[k] = data[k]
    save_config(cfg)
    apply_schedule(cfg)
    return jsonify({"ok": True})

@app.route("/api/run", methods=["POST"])
def api_run():
    if run_status["running"]:
        return jsonify({"ok": False, "error": "Already running"})
    cfg = load_config()
    threading.Thread(target=do_renew, args=(cfg,), daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/status")
def api_status():
    job      = scheduler.get_job("noip_renew")
    next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M UTC") if job and job.next_run_time else None
    return jsonify({
        "running":     run_status["running"],
        "last_run":    run_status["last_run"],
        "last_result": run_status["last_result"],
        "logs":        run_logs[-150:],
        "next_run":    next_run,
    })

@app.route("/api/version")
def api_version():
    cfg = load_config()
    return jsonify({"version": APP_VERSION, "built": APP_BUILT, "current_sha": cfg.get("current_sha","")})

@app.route("/api/changelog")
def api_changelog():
    try:
        entries = get_commits(limit=15)
        return jsonify({"ok": True, "entries": entries})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/check_update")
def api_check_update():
    try:
        cfg     = load_config()
        latest  = get_latest_commit()
        current = cfg.get("current_sha", "")[:7]
        current_ver = cfg.get("current_version", APP_VERSION)
        has_update  = latest["sha"] != current
        return jsonify({
            "ok":              True,
            "has_update":      has_update,
            "latest":          latest["sha"],
            "current":         current,
            "current_version": current_ver,
            "message":         latest["message"],
            "date":            latest["date"],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

update_logs   = []
update_running = False

def do_update():
    global update_running
    update_logs.clear()
    update_running = True
    try:
        import subprocess
        update_logs.append("[INFO] Starting self-update...")
        env = os.environ.copy()
        env["DOCKER_API_VERSION"] = "1.43"
        proc = subprocess.Popen(
            ["/usr/local/bin/update.sh"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env,
        )
        for line in proc.stdout:
            update_logs.append(line.rstrip())
            log.info(f"[UPDATE] {line.rstrip()}")
        proc.wait()
        if proc.returncode == 0:
            update_logs.append("[OK] Update complete — container restarting...")
        else:
            update_logs.append(f"[ERROR] Update failed (code {proc.returncode})")
            update_running = False
    except Exception as e:
        update_logs.append(f"[ERROR] {e}")
        update_running = False

@app.route("/api/update", methods=["POST"])
def api_update():
    global update_running
    try:
        if update_running:
            return jsonify({"ok": False, "error": "Already running"})
        if not os.path.exists("/var/run/docker.sock"):
            return jsonify({"ok": False, "error": "Docker socket not mounted. Add to docker-compose volumes."})
        threading.Thread(target=do_update, daemon=True).start()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/update_status")
def api_update_status():
    return jsonify({"running": update_running, "logs": update_logs[-50:]})

if __name__ == "__main__":
    cfg = load_config()
    apply_schedule(cfg)
    app.run(host="0.0.0.0", port=7895, debug=False, threaded=True)
