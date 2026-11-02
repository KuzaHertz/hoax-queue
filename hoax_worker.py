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
    # Login runs in a normal-sized window (no huge viewport); posting runs headless.
    kwargs = dict(
        headless=headless,
        user_agent=UA,
        locale="en-MY",
        timezone_id="Asia/Kuala_Lumpur",
        device_scale_factor=1,
        args=["--disable-blink-features=AutomationControlled",
              "--force-device-scale-factor=1", "--window-size=1280,900"],
    )
    if headless:
        kwargs["viewport"] = {"width": 1280, "height": 1000}
    else:
        kwargs["viewport"] = None          # use the real window size, fits any screen
    return p.chromium.launch_persistent_context(PROFILE, **kwargs)


def do_login():
    from playwright.sync_api import sync_playwright
    log("opening browser for login...")
    with sync_playwright() as p:
        ctx = context(p, headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto("https://www.threads.com/", timeout=60000)
        try:
            pg.bring_to_front()
        except Exception:
            pass
        # Instagram/Threads login pages render zoomed with the form below the fold.
        # Zoom out and scroll so the form is visible on normal screens.
        pg.wait_for_timeout(3000)
        for _ in range(2):
            try:
                pg.keyboard.press("Control+Minus")
            except Exception:
                break
        pg.wait_for_timeout(1500)
        try:
            pg.mouse.wheel(0, 1200)
        except Exception:
            pass
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
    """Post one job into its community. Returns permalink/'posted' or None."""
    from playwright.sync_api import sync_playwright
    text = (job.get("text") or "").strip()
    community = (job.get("community") or "").strip()
    if not text or not community:
        log(f"job {job['_id']}: missing text/community, skipping")
        return None
    first_line = next((l.strip() for l in text.split("\n") if l.strip()), "")
    frag = first_line[:40]
    shot = os.path.join(BASE, f"fail_{job['_id']}.png")

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

            label = pg.evaluate("""() => {
                const els = [...document.querySelectorAll('*')].filter(e =>
                    e.children.length === 0 && (e.textContent || '').trim().startsWith('Post about '));
                return els.length ? els[0].textContent.trim() : null;
            }""")
            if not label:
                log("composer not found on community page")
                pg.screenshot(path=shot)
                return None

            pg.evaluate("""(label) => {
                const els = [...document.querySelectorAll('*')].filter(e =>
                    e.children.length === 0 && (e.textContent || '').trim() === label);
                if (!els.length) return;
                const el = els[0];
                (el.closest('[role="button"]') || el.closest('button') || el.parentElement).click();
            }""", label)
            pg.wait_for_timeout(3000)

            # Type into the composer and CONFIRM the text actually landed.
            typed_ok = False
            for attempt in range(3):
                try:
                    box = pg.locator("[contenteditable='true'][role='textbox']").first
                    box.click(timeout=10000)
                    pg.wait_for_timeout(400)
                    pg.keyboard.press("Control+A")
                    pg.keyboard.press("Delete")
                    pg.keyboard.type(text, delay=12)
                    pg.wait_for_timeout(1200)
                    got = pg.evaluate("""() => {
                        const el = document.querySelector("[contenteditable='true'][role='textbox']");
                        return el ? (el.innerText || el.textContent || '') : '';
                    }""")
                    if frag[:25].lower() in (got or '').lower():
                        typed_ok = True
                        break
                    log(f"typing attempt {attempt+1}: text not in composer, retrying")
                except Exception as e:
                    log(f"typing attempt {attempt+1} error: {e}")
                pg.wait_for_timeout(800)

            if not typed_ok:
                log("could not enter text into composer")
                pg.screenshot(path=shot)
                return None

            # Click the composer's Post button (last visible one).
            clicked = pg.evaluate("""() => {
                const btns = [...document.querySelectorAll('[role="button"], button')]
                    .filter(b => (b.textContent || '').trim() === 'Post' && b.offsetParent !== null);
                if (!btns.length) return false;
                btns[btns.length - 1].click();
                return true;
            }""")
            if not clicked:
                log("Post button not found")
                pg.screenshot(path=shot)
                return None

            pg.wait_for_timeout(9000)

            # VERIFY on the profile: the post must actually be there.
            try:
                pg.goto("https://www.threads.com/@yyyhertz", wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_timeout(7000)
                prof = pg.inner_text("body")
                if frag[:30].lower() in prof.lower():
                    log("VERIFIED on profile")
                    return "posted"
            except Exception as e:
                log(f"profile verification error: {e}")

            log("NOT verified on profile — will retry next cycle")
            pg.screenshot(path=shot)
            return None
        except Exception as e:
            log(f"post error: {e}")
            try:
                pg.screenshot(path=shot)
            except Exception:
                pass
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
                if result == "posted":
                    done.add(job["_id"])
                    save_done(done)
                    log(f"job {job['_id']} marked done")
                else:
                    log(f"job {job['_id']} failed; will retry next cycle")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
