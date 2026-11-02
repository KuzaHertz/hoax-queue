#!/usr/bin/env python3
"""
Hoax Worker — posts Threads community content from YOUR OWN computer.

Why: Threads only lets community posts come from a real logged-in browser.
Running this on your PC means your home IP + your real session, so no more
cookie pasting.

SETUP (one time):
  1. Install Python from python.org  (tick "Add python.exe to PATH")
  2. In PowerShell:
       pip install playwright
       python -m playwright install chromium
  3. Download this file, then run:
       python hoax_worker.py --login
     A browser window opens. Log in to Threads normally, then come back to the
     black window and press Enter.
  4. Start the worker:
       python hoax_worker.py

It then checks for new posts every 2 minutes and publishes them.
Leave the window open (or set up Task Scheduler to keep it running).
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

REPO = "KuzaHertz/hoax-queue"          # public job feed (read-only)
JOBS_API = f"https://api.github.com/repos/{REPO}/contents/jobs"
POLL_SECONDS = 120

BASE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(os.environ.get("LOCALAPPDATA") or BASE, "hoax-worker-profile")
DONE_PATH = os.path.join(BASE, "hoax_worker_done.json")
LOG_PATH = os.path.join(BASE, "hoax_worker.log")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_done():
    try:
        return set(json.load(open(DONE_PATH, encoding="utf-8")))
    except Exception:
        return set()


def save_done(done):
    try:
        json.dump(sorted(done), open(DONE_PATH, "w", encoding="utf-8"))
    except Exception:
        pass


def fetch_jobs():
    req = urllib.request.Request(JOBS_API, headers={"User-Agent": "hoax-worker"})
    try:
        data = json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []          # no jobs folder yet
        log(f"queue fetch failed: HTTP {e.code}")
        return []
    except Exception as e:
        log(f"queue fetch error: {e}")
        return []
    jobs = []
    for item in data if isinstance(data, list) else []:
        if not item.get("name", "").endswith(".json"):
            continue
        try:
            raw = urllib.request.urlopen(
                urllib.request.Request(item["download_url"], headers={"User-Agent": "hoax-worker"}),
                timeout=30).read()
            job = json.loads(raw)
            job["_id"] = item["name"][:-5]
            jobs.append(job)
        except Exception as e:
            log(f"job read error ({item.get('name')}): {e}")
    return jobs


def context(p, headless=True):
    return p.chromium.launch_persistent_context(
        PROFILE, headless=headless, user_agent=UA,
        viewport={"width": 1280, "height": 2400},
        locale="en-MY", timezone_id="Asia/Kuala_Lumpur",
        args=["--disable-blink-features=AutomationControlled"])


def do_login():
    from playwright.sync_api import sync_playwright
    log("opening browser for login...")
    with sync_playwright() as p:
        ctx = context(p, headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto("https://www.threads.com/", timeout=60000)
        print("\n=== Log in to Threads in the window that just opened ===")
        print("When you're logged in and can see your feed, come back here.")
        input("Press Enter to save the session... ")
        try:
            ctx.storage_state(path=os.path.join(BASE, "hoax_storage.json"))
            log("session saved.")
        except Exception as e:
            log(f"could not save session: {e}")
        ctx.close()


def post_job(job):
    """Post one job into its community. Returns permalink or None."""
    from playwright.sync_api import sync_playwright
    text = (job.get("text") or "").strip()
    community = (job.get("community") or "").strip()
    if not text or not community:
        log(f"job {job['_id']}: missing text/community, skipping")
        return None
    first_line = next((l.strip() for l in text.split("\n") if l.strip()), "")[:40]

    with sync_playwright() as p:
        ctx = context(p)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(community, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(7000)
            body = pg.inner_text("body")
            if "Log in or sign up for Threads" in body:
                log("SESSION EXPIRED — run: python hoax_worker.py --login")
                return None

            # find the community composer label ("Post about X...")
            label = pg.evaluate("""() => {
                const els = [...document.querySelectorAll('*')].filter(e =>
                    e.children.length === 0 && (e.textContent || '').trim().startsWith('Post about '));
                return els.length ? els[0].textContent.trim() : null;
            }""")
            if not label:
                log("composer not found on community page")
                return None

            clicked = pg.evaluate("""(label) => {
                const els = [...document.querySelectorAll('*')].filter(e =>
                    e.children.length === 0 && (e.textContent || '').trim() === label);
                if (!els.length) return false;
                const el = els[0];
                (el.closest('[role="button"]') || el.closest('button') || el.parentElement).click();
                return true;
            }""", label)
            if not clicked:
                log("could not open composer")
                return None

            pg.wait_for_timeout(2500)
            box = pg.locator("[role='textbox']").first
            box.click()
            pg.keyboard.type(text, delay=8)
            pg.wait_for_timeout(1200)

            # the composer's Post button is the LAST visible one
            posted = pg.evaluate("""() => {
                const btns = [...document.querySelectorAll('[role="button"], button')]
                    .filter(b => (b.textContent || '').trim() === 'Post' && b.offsetParent !== null);
                if (!btns.length) return false;
                btns[btns.length - 1].click();
                return true;
            }""")
            if not posted:
                log("Post button not found")
                return None

            pg.wait_for_timeout(8000)
            body2 = pg.inner_text("body")
            if label in body2:
                # composer closed, looks published; try to grab a permalink
                perm = pg.evaluate("""() => {
                    const a = [...document.querySelectorAll('a[href*="/post/"]')]
                        .map(x => x.href).filter(h => h.includes('yyyhertz'));
                    return a.length ? a[0] : null;
                }""")
                log(f"posted{(' -> ' + perm) if perm else ''}")
                return perm or "posted"
            log("posted but could not verify page state")
            return "posted-unverified"
        except Exception as e:
            log(f"post error: {e}")
            return None
        finally:
            ctx.close()


def main():
    if "--login" in sys.argv:
        do_login()
        return
    log("Hoax worker started. Checking for jobs every 2 minutes.")
    login_alerted = False
    while True:
        done = load_done()
        jobs = fetch_jobs()
        pending = [j for j in jobs if j["_id"] not in done]
        if pending:
            log(f"{len(pending)} new job(s)")
            for job in sorted(pending, key=lambda j: j.get("created", "")):
                result = post_job(job)
                if result and result != "posted-unverified":
                    done.add(job["_id"])
                    save_done(done)
                elif result is None:
                    log("job failed; will retry next cycle")
                    if not login_alerted and "SESSION" not in "":
                        login_alerted = True
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
