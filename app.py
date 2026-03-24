#!/usr/bin/env python3
"""No-IP Renewer Web App — Multi-account edition"""

import os, re, time, json, threading, logging, urllib.request, base64
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
GMT7          = timezone(timedelta(hours=7))

run_logs       = []
run_status     = {"running": False, "last_run": None, "last_result": None}
update_logs    = []
update_running = False
RUN_HISTORY_FILE = "/data/run_history.json"

def load_history():
    try:
        entries = json.load(open(RUN_HISTORY_FILE))
        # Keep only last 7 days
        cutoff = datetime.now(GMT7).timestamp() - 7 * 86400
        return [e for e in entries if e.get("ts", 0) > cutoff]
    except: return []

def save_history_entry(entry):
    history = load_history()
    history.append(entry)
    # Keep max 200 entries
    history = history[-200:]
    os.makedirs("/data", exist_ok=True)
    with open(RUN_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

# ── Config ─────────────────────────────────────────────────────────────────────
def load_config():
    try:
        cfg = json.load(open(CONFIG_FILE))
        cfg.setdefault("accounts", [])
        cfg.setdefault("current_sha", "")
        cfg.setdefault("current_version", "")
        return cfg
    except Exception:
        return {"accounts": [], "current_sha": "", "current_version": ""}

def save_config(cfg):
    os.makedirs("/data", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

# ── Version ────────────────────────────────────────────────────────────────────
def get_version():
    try: return open("/app/VERSION").read().strip()
    except: return "unknown"

def get_build_time():
    try:
        ts = os.path.getmtime("/app/VERSION")
        return datetime.fromtimestamp(ts, tz=GMT7).strftime("%Y-%m-%d %H:%M:%S GMT+7")
    except: return "unknown"

APP_VERSION = get_version()
APP_BUILT   = get_build_time()

# ── GitHub API ─────────────────────────────────────────────────────────────────
def github_get(path):
    url = f"https://api.github.com/repos/{UPSTREAM_REPO}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "noip-renewer"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

# ── Logging ────────────────────────────────────────────────────────────────────
def add_log(msg):
    ts = datetime.now(GMT7).strftime("%H:%M:%S")
    run_logs.append(f"[{ts}] {msg}")
    if len(run_logs) > 300: run_logs.pop(0)

# ── Playwright: renew single account ───────────────────────────────────────────
def renew_account(username, password, totp_key):
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWT

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()

            add_log(f"🔐 Logging in as {username}...")
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

                digit_inputs = [d for d in page.locator('input[type="number"], input[type="tel"]').all() if d.is_visible()]
                if len(digit_inputs) >= 6:
                    add_log("Typing into 6 digit inputs...")
                    for i, digit in enumerate(code):
                        digit_inputs[i].click()
                        digit_inputs[i].fill(digit)
                        time.sleep(0.15)
                    time.sleep(0.5)
                else:
                    add_log("Typing full code...")
                    first = page.locator('input[type="number"], input[type="tel"]').first
                    first.click()
                    page.keyboard.type(code, delay=150)

                # Try multiple submit methods
                submitted = False
                for selector in ['button[name="submit"]', 'button[type="submit"]', 'input[type="submit"]', 'button.btn-primary']:
                    try:
                        page.click(selector, timeout=3_000)
                        submitted = True
                        add_log(f"Submitted via {selector}")
                        break
                    except: pass
                if not submitted:
                    page.keyboard.press("Enter")
                    add_log("Submitted via Enter")

                try: page.wait_for_url(lambda url: "2fa" not in url and "verify" not in url, timeout=15_000)
                except:
                    try: page.wait_for_load_state("networkidle", timeout=10_000)
                    except: pass

                add_log(f"Post-2FA: {page.url}")
                if "2fa" in page.url or "verify" in page.url:
                    raise RuntimeError("2FA verification failed — check TOTP key or code expired")

            add_log("✅ Login successful!")

            renewed = []
            while True:
                add_log("📋 Loading DNS records...")
                # Retry up to 3 times — my.noip.com sometimes aborts on first load
                for attempt in range(3):
                    try:
                        page.goto("https://my.noip.com/dns/records",
                                  wait_until="domcontentloaded", timeout=30_000)
                        time.sleep(3)
                        break
                    except Exception as e:
                        add_log(f"Retry {attempt+1}/3: {str(e)[:80]}")
                        time.sleep(2)
                else:
                    raise RuntimeError("Could not load my.noip.com after 3 attempts")
                if "login" in page.url:
                    raise RuntimeError("Session lost")
                try: page.locator("#zone-collection-wrapper, .dns-records, table, .expiration-banner, [hx-get*='/touch']").first.wait_for(timeout=15_000)
                except PWT: add_log("No records wrapper."); break

                # Find all Confirm buttons (hx-get*="/touch" is the new No-IP UI)
                confirm_btns = page.locator('button[hx-get*="/touch"]').all()
                confirm_btns = [b for b in confirm_btns if b.is_visible()]

                if not confirm_btns:
                    add_log("✅ No hosts need confirmation — all good!")
                    break

                add_log(f"Found {len(confirm_btns)} host(s) needing confirmation.")

                host = confirm_btns[0]
                host_name = "unknown"
                try:
                    hx_url = host.get_attribute("hx-get", timeout=1_000) or ""
                    host_id = hx_url.split("/")[-2] if hx_url else "?"
                    # Look for hostname in nearby elements: heading, strong, td, span
                    for ancestor_xpath in [
                        "xpath=ancestor::tr[1]",
                        "xpath=ancestor::div[contains(@class,'alert')][1]",
                        "xpath=ancestor::div[contains(@class,'row')][1]",
                        "xpath=preceding::*[contains(@class,'hostname') or contains(@class,'host-name')][1]",
                    ]:
                        try:
                            txt = host.locator(ancestor_xpath).inner_text(timeout=500)
                            # Extract hostname pattern (word.ddns.net etc)
                            import re as _re
                            m = _re.search(r'[\w\-]+\.[\w\.\-]+\.\w+', txt)
                            if m:
                                host_name = m.group(0); break
                            # Fallback: first non-empty line
                            lines = [l.strip() for l in txt.split("\n") if l.strip() and "Confirm" not in l and "Expires" not in l]
                            if lines: host_name = lines[0][:40]; break
                        except: pass
                    if host_name == "unknown": host_name = f"host-{host_id}"
                except: pass

                add_log(f"[{host_name}] Confirming...")

                # Click the button directly (HTMX handles the request)
                confirmed = False
                try:
                    host.click()
                    confirmed = True
                    add_log(f"[{host_name}] ✓ Clicked Confirm")
                    time.sleep(2)
                except Exception as e:
                    add_log(f"Button click err: {e}")

                # Fallback: call hx-get URL via fetch
                if not confirmed:
                    try:
                        hx_url = host.get_attribute("hx-get", timeout=1_000)
                        if hx_url:
                            r = page.evaluate(f"""async()=>{{
                                const r=await fetch('{hx_url}',{{
                                    method:'GET',credentials:'include',
                                    headers:{{'HX-Request':'true','HX-Current-URL':window.location.href}}
                                }});return r.ok;
                            }}""")
                            if r: confirmed = True; add_log(f"[{host_name}] HTMX ✓")
                    except Exception as e: add_log(f"HTMX err: {e}")

                if confirmed: renewed.append(host_name)
                else: add_log(f"[{host_name}] ❌ Could not confirm"); break

            browser.close()
            return renewed, None
    except Exception as e:
        return [], str(e)[:200]

# ── Run ────────────────────────────────────────────────────────────────────────
def do_renew(account_id=None):
    global run_status
    if run_status["running"]: return
    cfg = load_config()
    accounts = cfg.get("accounts", [])
    if account_id:
        accounts = [a for a in accounts if a["id"] == account_id]
    if not accounts:
        add_log("❌ No accounts configured.")
        return

    run_logs.clear()
    run_status.update({"running": True, "last_run": datetime.now(GMT7).strftime("%Y-%m-%d %H:%M:%S GMT+7"), "last_result": None})
    try:
        all_renewed, all_errors = [], []
        for acc in accounts:
            add_log(f"--- {acc.get('username','')} ---")
            renewed, err = renew_account(acc.get("username",""), acc.get("password",""), acc.get("totp_key",""))
            all_renewed.extend(renewed)
            if err: all_errors.append(f"{acc.get('username','?')}: {err}")

        if all_renewed:
            run_status["last_result"] = f"success|✅ Renewed {len(all_renewed)}: {', '.join(all_renewed)}"
        elif all_errors:
            run_status["last_result"] = f"error|❌ {'; '.join(all_errors)}"
        else:
            run_status["last_result"] = "info|ℹ️ No hosts needed confirmation"
        result_msg = run_status["last_result"].split("|")[1]
        add_log(result_msg)
        # Save to run history
        save_history_entry({
            "ts":      datetime.now(GMT7).timestamp(),
            "time":    datetime.now(GMT7).strftime("%Y-%m-%d %H:%M:%S GMT+7"),
            "trigger": "manual" if not account_id else f"scheduled:{account_id}",
            "result":  run_status["last_result"].split("|")[0],
            "summary": result_msg,
            "renewed": all_renewed,
        })
    except Exception as e:
        run_status["last_result"] = f"error|❌ {str(e)[:200]}"
        add_log(f"❌ {str(e)[:200]}")
        save_history_entry({
            "ts":      datetime.now(GMT7).timestamp(),
            "time":    datetime.now(GMT7).strftime("%Y-%m-%d %H:%M:%S GMT+7"),
            "trigger": "manual",
            "result":  "error",
            "summary": str(e)[:200],
            "renewed": [],
        })
    finally:
        run_status["running"] = False

# ── Schedule ───────────────────────────────────────────────────────────────────
def apply_schedule(cfg):
    scheduler.remove_all_jobs()
    for acc in cfg.get("accounts", []):
        hour   = int(acc.get("run_at_hour", 9))
        offset = int(acc.get("gmt_offset", 7))
        every  = int(acc.get("run_every_days", 1))
        utc_h  = (hour - offset) % 24
        day_f  = f"*/{every}" if every > 1 else "*"
        acc_id = acc["id"]
        scheduler.add_job(func=do_renew, kwargs={"account_id": acc_id},
            trigger=CronTrigger(hour=utc_h, minute=0, day=day_f),
            id=f"renew_{acc_id}", replace_existing=True)

# ── Update ─────────────────────────────────────────────────────────────────────
def do_update():
    global update_running
    update_logs.clear(); update_running = True
    try:
        import subprocess
        update_logs.append("[INFO] Starting self-update...")
        env = os.environ.copy(); env["DOCKER_API_VERSION"] = "1.43"
        proc = subprocess.Popen(["/usr/local/bin/update.sh"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        for line in proc.stdout: update_logs.append(line.rstrip())
        proc.wait()
        if proc.returncode == 0: update_logs.append("[OK] Update complete — container restarting...")
        else: update_logs.append(f"[ERROR] Failed (code {proc.returncode})"); update_running = False
    except Exception as e:
        update_logs.append(f"[ERROR] {e}"); update_running = False

def init_sha():
    cfg = load_config()
    if cfg.get("current_sha"): return
    try:
        data = github_get("commits/main")
        cfg["current_sha"] = data["sha"][:7]
        cfg["current_version"] = get_version()
        save_config(cfg)
    except Exception as e:
        log.warning(f"Could not init SHA: {e}")

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def landing():
    return render_template("landing.html", version=APP_VERSION, built=APP_BUILT)

@app.route("/setup")
def setup_guide():
    return render_template("setup.html", version=APP_VERSION, built=APP_BUILT)

@app.route("/config")
def config_page():
    return render_template("index.html", version=APP_VERSION, built=APP_BUILT)

@app.route("/api/accounts")
def api_accounts():
    cfg = load_config()
    safe = [{"id": a["id"], "username": a["username"],
             "run_every_days": a.get("run_every_days",1),
             "run_at_hour": a.get("run_at_hour",9),
             "gmt_offset": a.get("gmt_offset",7)}
            for a in cfg.get("accounts",[])]
    return jsonify({"ok": True, "accounts": safe})

@app.route("/api/account/<acc_id>")
def api_account_get(acc_id):
    cfg = load_config()
    acc = next((a for a in cfg.get("accounts",[]) if a["id"] == acc_id), None)
    if not acc: return jsonify({"ok": False, "error": "Not found"})
    return jsonify({"ok": True, "account": acc})

@app.route("/api/account/save", methods=["POST"])
def api_account_save():
    import uuid
    data = request.json or {}
    cfg  = load_config()
    accounts = cfg.get("accounts", [])
    acc_id = data.get("id")
    if acc_id:
        found = False
        for a in accounts:
            if a["id"] == acc_id: a.update(data); found = True; break
        if not found: accounts.append(data)
    else:
        data["id"] = str(uuid.uuid4())[:8]
        accounts.append(data)
    cfg["accounts"] = accounts
    save_config(cfg); apply_schedule(cfg)
    safe = [{"id": a["id"], "username": a["username"],
             "run_every_days": a.get("run_every_days",1),
             "run_at_hour": a.get("run_at_hour",9),
             "gmt_offset": a.get("gmt_offset",7)}
            for a in accounts]
    return jsonify({"ok": True, "accounts": safe})

@app.route("/api/account/delete", methods=["POST"])
def api_account_delete():
    data = request.json or {}
    cfg  = load_config()
    cfg["accounts"] = [a for a in cfg.get("accounts",[]) if a["id"] != data.get("id")]
    save_config(cfg); apply_schedule(cfg)
    return jsonify({"ok": True})

@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.json or {}
    cfg  = load_config()
    for k in ["current_sha","current_version"]:
        if k in data: cfg[k] = data[k]
    save_config(cfg)
    return jsonify({"ok": True})

@app.route("/api/run", methods=["POST"])
def api_run():
    if run_status["running"]: return jsonify({"ok": False, "error": "Already running"})
    data = request.json or {}
    threading.Thread(target=do_renew, kwargs={"account_id": data.get("account_id")}, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/status")
def api_status():
    return jsonify({"running": run_status["running"], "last_run": run_status["last_run"],
                    "last_result": run_status["last_result"], "logs": run_logs[-150:]})

@app.route("/api/changelog")
def api_changelog():
    try:
        commits = github_get("commits?per_page=20")
        entries = []
        for c in commits:
            dt = datetime.strptime(c["commit"]["author"]["date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(GMT7)
            msg = c["commit"]["message"].split("\n")[0][:100]
            # Extract version number from commit message if present (e.g. "v1.0.14 - Fix ...")
            entries.append({"sha": c["sha"][:7], "message": msg, "date": dt.strftime("%Y-%m-%d %H:%M GMT+7")})
        return jsonify({"ok": True, "entries": entries})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/history")
def api_history():
    try:
        history = load_history()
        return jsonify({"ok": True, "entries": list(reversed(history))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/check_update")
def api_check_update():
    try:
        cfg    = load_config()
        data   = github_get("commits/main")
        latest = data["sha"][:7]
        current = cfg.get("current_sha","")[:7]
        message = data["commit"]["message"].split("\n")[0][:100]
        dt = datetime.strptime(data["commit"]["author"]["date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(GMT7)
        try:
            vd = github_get("contents/VERSION")
            latest_ver = base64.b64decode(vd["content"]).decode().strip()
        except: latest_ver = "?"
        return jsonify({"ok": True, "has_update": latest != current, "latest": latest, "current": current,
                        "current_version": cfg.get("current_version", APP_VERSION), "latest_version": latest_ver,
                        "message": message, "date": dt.strftime("%Y-%m-%d %H:%M GMT+7")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/update", methods=["POST"])
def api_update():
    global update_running
    try:
        if update_running: return jsonify({"ok": False, "error": "already_running", "logs": update_logs[-50:]})
        if not os.path.exists("/var/run/docker.sock"): return jsonify({"ok": False, "error": "Docker socket not mounted."})
        threading.Thread(target=do_update, daemon=True).start()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/update_status")
def api_update_status():
    return jsonify({"running": update_running, "logs": update_logs[-50:]})

@app.route("/api/update_reset", methods=["POST"])
def api_update_reset():
    global update_running
    update_running = False; update_logs.clear()
    return jsonify({"ok": True})

@app.route("/api/version")
def api_version():
    cfg = load_config()
    return jsonify({"version": APP_VERSION, "built": APP_BUILT, "current_sha": cfg.get("current_sha","")})

if __name__ == "__main__":
    init_sha()
    cfg = load_config()
    apply_schedule(cfg)
    app.run(host="0.0.0.0", port=7895, debug=False, threaded=True)
