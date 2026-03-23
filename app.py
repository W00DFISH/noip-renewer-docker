#!/usr/bin/env python3
"""No-IP Renewer Web App — Flask + APScheduler + Playwright"""

import os, re, time, json, threading, logging, urllib.request
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

CONFIG_FILE = "/data/config.json"
run_logs    = []
run_status  = {"running": False, "last_run": None, "last_result": None}

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "username":      "",
    "password":      "",
    "totp_key":      "",
    "schedule_enabled": False,
    "run_every_days": 1,
    "run_at_hour":   9,
    "gmt_offset":    7,
    "upstream_repo": "",
    "current_sha":   "",
}

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
    except Exception:
        return dict(DEFAULT_CONFIG)

def save_config(cfg):
    os.makedirs("/data", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

# ── Logging ───────────────────────────────────────────────────────────────────
def add_log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    run_logs.append(f"[{ts}] {msg}")
    if len(run_logs) > 300:
        run_logs.pop(0)

# ── Playwright renew ──────────────────────────────────────────────────────────
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
        add_log("❌ Missing username or password — aborting.")
        return

    run_logs.clear()
    run_status.update({"running": True, "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "last_result": None})

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWT

        add_log("🚀 Starting browser...")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()

            # Login
            add_log("🔐 Logging in...")
            page.goto("https://www.noip.com/login?ref_url=console", wait_until="networkidle", timeout=30_000)
            page.fill("#username", username)
            page.fill("#password", password)
            page.click("#clogs-captcha-button")
            try: page.wait_for_load_state("networkidle", timeout=10_000)
            except: pass

            cur = page.url
            add_log(f"Post-login: {cur}")

            # 2FA
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

            # Confirm loop
            renewed = []
            while True:
                add_log("📋 Loading DNS records...")
                page.goto("https://my.noip.com/dns/records", wait_until="networkidle", timeout=30_000)
                time.sleep(2)

                if "login" in page.url:
                    raise RuntimeError("Session lost — redirected to login")

                try: page.locator("#zone-collection-wrapper").wait_for(timeout=15_000)
                except PWT:
                    add_log("No zone wrapper found.")
                    break

                banners = page.locator('[id^="expiration-banner-hostname-"]').all()
                add_log(f"Found {len(banners)} host(s) needing confirmation.")
                if not banners:
                    add_log("✅ All hosts confirmed — nothing to do!")
                    break

                host = banners[0]
                host_name = "unknown"
                try:
                    h4 = host.locator("h4").first.inner_text(timeout=2_000)
                    host_name = re.sub(r'Expires in \d+ days - ', '', h4).strip()
                except: pass

                add_log(f"[{host_name}] Confirming...")
                confirmed = False

                # Try button click
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

                # Fallback HTMX
                if not confirmed:
                    try:
                        hx_url = host.locator("button[hx-get]").first.get_attribute("hx-get", timeout=2_000)
                        if hx_url:
                            add_log(f"[{host_name}] HTMX: {hx_url}")
                            r = page.evaluate(f"""async()=>{{const r=await fetch('{hx_url}',{{method:'GET',credentials:'include',headers:{{'HX-Request':'true','HX-Current-URL':window.location.href}}}});return{{status:r.status,ok:r.ok}};}}""")
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
            run_status["last_result"] = f"success|✅ Renewed {len(renewed)} host(s): {', '.join(renewed)}"
        else:
            run_status["last_result"] = "info|ℹ️ No hosts needed confirmation"
        add_log(run_status["last_result"].split("|")[1])

    except Exception as e:
        err = str(e)[:300]
        add_log(f"❌ Fatal: {err}")
        run_status["last_result"] = f"error|❌ Error: {err}"
    finally:
        run_status["running"] = False

# ── Schedule management ───────────────────────────────────────────────────────
def apply_schedule(cfg):
    scheduler.remove_all_jobs()
    if not cfg.get("schedule_enabled"):
        return

    offset   = int(cfg.get("gmt_offset", 7))
    run_hour = int(cfg.get("run_at_hour", 9))
    # Convert local hour to UTC
    utc_hour = (run_hour - offset) % 24

    every_days = int(cfg.get("run_every_days", 1))
    day_filter = f"*/{every_days}" if every_days > 1 else "*"

    scheduler.add_job(
        func=do_renew,
        trigger=CronTrigger(hour=utc_hour, minute=0, day=day_filter),
        id="noip_renew",
        replace_existing=True,
    )
    add_log(f"⏰ Schedule set: every {every_days} day(s) at {run_hour:02d}:00 local (GMT+{offset})")

# ── Update check ──────────────────────────────────────────────────────────────
def check_upstream(cfg):
    repo = cfg.get("upstream_repo", "").strip()
    if not repo:
        return None, None
    try:
        url = f"https://api.github.com/repos/{repo}/commits/main"
        req = urllib.request.Request(url, headers={"User-Agent": "noip-renewer"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        latest_sha = data["sha"][:7]
        current_sha = cfg.get("current_sha", "")[:7]
        message = data["commit"]["message"].split("\n")[0][:80]
        return latest_sha, current_sha, message
    except Exception as e:
        return None, None, str(e)

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def landing():
    return render_template("landing.html")

@app.route("/setup")
def setup_guide():
    return render_template("setup.html")

@app.route("/config")
def config_page():
    cfg = load_config()
    return render_template("index.html", config=cfg)

@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.json or {}
    cfg = load_config()
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
    cfg = load_config()
    next_run = None
    job = scheduler.get_job("noip_renew")
    if job:
        next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M UTC") if job.next_run_time else None
    return jsonify({
        "running":     run_status["running"],
        "last_run":    run_status["last_run"],
        "last_result": run_status["last_result"],
        "logs":        run_logs[-150:],
        "next_run":    next_run,
        "schedule_on": cfg.get("schedule_enabled", False),
    })

@app.route("/api/check_update")
def api_check_update():
    cfg = load_config()
    result = check_upstream(cfg)
    if result[0] is None:
        return jsonify({"ok": False, "error": result[2]})
    latest, current, message = result
    has_update = latest != current
    return jsonify({"ok": True, "has_update": has_update, "latest": latest, "current": current, "message": message})


update_logs = []
update_running = False

def do_update():
    global update_running
    update_logs.clear()
    update_running = True
    try:
        import subprocess, shlex
        update_logs.append("[INFO] Starting self-update...")
        proc = subprocess.Popen(
            ["/usr/local/bin/update.sh"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
        )
        for line in proc.stdout:
            line = line.rstrip()
            update_logs.append(line)
            log.info(f"[UPDATE] {line}")
        proc.wait()
        if proc.returncode == 0:
            update_logs.append("[OK] Update complete — container restarting...")
        else:
            update_logs.append(f"[ERROR] Update failed with code {proc.returncode}")
            update_running = False
    except Exception as e:
        update_logs.append(f"[ERROR] {e}")
        update_running = False


@app.route("/api/update", methods=["POST"])
def api_update():
    global update_running
    if update_running:
        return jsonify({"ok": False, "error": "Update already running"})
    threading.Thread(target=do_update, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/update_status")
def api_update_status():
    return jsonify({"running": update_running, "logs": update_logs[-50:]})

if __name__ == "__main__":
    cfg = load_config()
    apply_schedule(cfg)
    app.run(host="0.0.0.0", port=7895, debug=False, threaded=True)
