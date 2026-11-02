# Hoax Worker — setup (Windows)

This little program posts your Threads community content from **your own PC**,
so you never have to paste a cookie again.

---

## 1. Install Python (one time)
Download: https://www.python.org/downloads/

On the first install screen, **tick the box "Add python.exe to PATH"** — this matters.
Then click Install Now.

## 2. Install the browser tool
Press **Win + X** → open **Terminal** (or **PowerShell**), then paste each line and press Enter:

```powershell
pip install playwright
python -m playwright install chromium
```

The second line downloads about 150 MB. Wait for it to finish.

## 3. Download the worker

```powershell
cd $HOME\Downloads
curl -O https://raw.githubusercontent.com/KuzaHertz/hoax-queue/main/hoax_worker.py
```

## 4. Log in once

```powershell
python hoax_worker.py --login
```

A browser window opens. **Log in to Threads normally** (password, 2FA if it asks).
When you can see your feed, go back to the black window and press **Enter**.
The window closes and the login is saved on your PC.

## 5. Start the worker

```powershell
python hoax_worker.py
```

Leave that window open. It checks for new posts every 2 minutes and publishes them.
You'll see a line in the window each time it posts.

---

## Good to know
- **If the PC sleeps**, posts wait and go out when it wakes. Nothing is lost.
- **If it says SESSION EXPIRED**, run step 4 again (log in once more).
- **To stop it**, close the window or press Ctrl + C.
- It only makes normal outgoing connections. Nothing is opened on your router.
- Logs are written to `hoax_worker.log` next to the script.
