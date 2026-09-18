# DeskGuard

Records your webcam automatically when you activate DeskGuard's virtual lock
(by default Ctrl+Alt+L), or when your Windows session locks in native mode,
and stops as soon as you enter the unlock code. Comes with a local web
dashboard to browse, filter, and play back clips, and to change recording
settings without touching code. Everything stays on your machine.

## Files

| File | Purpose |
|------|---------|
| `deskguard.py` | The recorder — run this in the background; the webcam is activated only during a lock session in hotkey mode |
| `dashboard.py` | The review UI — run when you want to browse clips or change settings |
| `deskguard_config.py` | Shared config loader used by both of the above |
| `config.json` | Your settings — created automatically on first run |
| `recordings/clips/videos/` | Video files only |
| `recordings/clips/metadata/` | Per-clip JSON metadata |
| `recordings/clips/snapshots/` | Identification snapshots |
| `recordings/clips/thumbnails/` | Dashboard thumbnails and playback cache images |
| `logs/` | Where runtime logs land |

## What the recorder does

- In `lock_mode: "hotkey"`, registers a global hotkey and shows a full-screen
  DeskGuard overlay. Entering `unlock_code` closes it and stops recording.
- In `lock_mode: "native"`, hooks Windows' native session lock/unlock event.
- Starts recording your default webcam when the selected lock mode activates.
- Detects **motion** (frame-difference based) and **people** (OpenCV's
  built-in HOG detector) independently, logging timestamped events for
  each and drawing a box around detected people in the footage.
- Writes a `.json` metadata file for each clip (start/end time,
  resolution, detection events) — this is what the dashboard reads to
  filter and tag clips.
- Keeps total storage across all clips under your configured cap (default
  5 GB) by deleting the oldest clips first. A per-clip safety stop guards
  against a single unusually long lock session filling the disk.
- Logs every event (lock, unlock, detections, deletions, errors) with a
  timestamp to `logs/deskguard_events.log`.

## What the dashboard does

Run `python dashboard.py` and open `http://127.0.0.1:5151` (binds to
localhost only — not reachable from other machines on your network):

- **Recordings list** — every clip with a thumbnail, time, duration, size,
  and tags (Person / Motion). Filter to "Person detected," "Motion only,"
  or "No detections."
- **Inline playback** — click Play to expand a clip and watch it right in
  the list, no separate page.
- **Delete** — remove a clip (and its metadata/thumbnail) straight from
  the list.
- **Settings** — change camera index, resolution (320x240 up to 1280x720),
  frame rate, total/per-clip storage caps, and detection sensitivity for
  both motion and person detection. Changes take effect starting with the
  *next* lock/unlock cycle, not whatever's currently recording.
- **Storage meter** in the sidebar showing how much of your cap is used.

## Setup

### Standalone Windows deployment

For a device without a Python development setup, copy the project folder to
the Windows device and double-click `DeskGuard_Build.bat`. It installs every
required dependency and creates standalone executables in `dist/`. Then run
`DeskGuard_Run.bat` to start the recorder, watchdog, and dashboard together.
Open `http://127.0.0.1:5151` for the dashboard. DeskGuard is Windows-only
because it uses Win32 webcam, lock, hotkey, and input-hook APIs.

### Run from Python

1. Install Python 3.9+ on Windows if you don't have it.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Start the recorder:
   ```
   python deskguard.py
   ```
   Press Ctrl+Alt+L to test — the DeskGuard overlay should appear. Enter the
   configured `unlock_code` (the sample config uses `1234`) to dismiss it.
4. In a separate terminal, start the dashboard:
   ```
   python dashboard.py
   ```
   Open `http://127.0.0.1:5151` to browse.

### Run the dashboard as a Windows service with NSSM

NSSM (the Non-Sucking Service Manager) can keep the DeskGuard dashboard
running in the background and start it automatically with Windows. The
included `DeskGuard_NSSM_Setup.bat` installs and controls a service named
`DeskGuardDashboard`.

NSSM is used for the **dashboard only**. Do not install `deskguard.py` or
`watchdog.py` as NSSM services: Windows services run in Session 0, while the
recorder and watchdog must run in the logged-in user's interactive session to
access the webcam, receive lock notifications, and install input hooks. Use
`DeskGuard_TaskScheduler_Setup.bat` for those two processes instead.

#### Install and start the dashboard service

1. Download NSSM from [nssm.cc](https://nssm.cc/download) and extract
   `nssm.exe`.
2. Place `nssm.exe` in either `C:\nssm\nssm.exe`, the DeskGuard project
   folder beside `DeskGuard_NSSM_Setup.bat`, or a directory on `PATH`. The
   setup script checks those locations in that order.
3. Make sure Python is available on `PATH` and that `dashboard.py` is in the
   DeskGuard project folder.
4. Right-click `DeskGuard_NSSM_Setup.bat` and choose **Run as administrator**.
5. Choose **5 — Install service**. The script configures automatic startup,
   restarts the dashboard after a crash, and starts the service.

The dashboard remains available at `http://127.0.0.1:5151`. The service name
is `DeskGuardDashboard`, and its output is written to:

```
logs/dashboard-service.log
logs/dashboard-service-error.log

### Optional remote dashboard access with zrok

DeskGuard can be reached remotely through a reserved zrok URL. The current
reserved URL is:

```
https://deskguard.shares.zrok.io
```

The zrok layer does not replace the DeskGuard dashboard login. The dashboard
password is configured in `config.json` and can be changed from Dashboard
Settings. Hosted zrok may show its safety interstitial on the first visit;
choose **Visit Share** once, after which the browser remembers the choice.

#### Initial setup on Windows

1. Download the official `zrok2.exe` release and place it at
   `.zrok\zrok2.exe`.
2. Run `DeskGuard_Zrok_Setup.bat` from this project folder.
3. Enter the zrok enable token when prompted. The token is not saved in the
   project files.
4. Start DeskGuard normally, or let the setup/startup task launch the Python
   dashboard and zrok share at Windows logon.

The setup reserves the `public:deskguard` name, which keeps the URL stable
across share restarts. `Start_DeskGuard_Public.ps1` starts the dashboard and
share without zrok Basic Auth so the browser reaches the DeskGuard login.
Keep the URL private and use a strong dashboard password; the dashboard
contains recorded video and management controls.
```

Run the setup script as administrator whenever you need to choose **1** to
start, **2** to stop, **3** to restart, **4** to view status and recent errors,
**6** to reinstall, or **7** to uninstall the service. Uninstalling the
service does not delete recordings or logs.

After changing dashboard-served settings that require a process restart (for
example the recorder hotkey), choose **3 — Restart dashboard**. If the service
does not start, choose **4 — Check status and logs** and inspect the error log.

## Running the recorder in the background (no console window)

Once you've confirmed it works, run it silently with `pythonw.exe` instead
of `python.exe`:
```
pythonw.exe deskguard.py
```
To have it start automatically every time you log in to Windows:

1. Press `Win+R`, type `shell:startup`, hit Enter — this opens your
   Startup folder.
2. Create a shortcut in that folder pointing to:
   ```
   pythonw.exe "C:\full\path\to\deskguard.py"
   ```
   (Right-click the shortcut → Properties → set "Start in" to the
   deskguard folder, so it can find `recordings/` and `config.json`
   correctly.)

The dashboard is meant to be opened on demand rather than run constantly —
start it with `python dashboard.py` whenever you want to review clips, and
close the terminal when you're done.

To stop the recorder, use Task Manager and end the `pythonw.exe` process
(or run it via `python.exe` in a console, where Ctrl+C works cleanly).

## Notes and limitations

- **Camera must be free.** If another app (Zoom, Teams, etc.) is using the
  webcam when the lock happens, recording will fail — check
  `deskguard_events.log` for "could not open webcam" if a clip is missing.
- **Storage estimate**: at 640x480 / 8fps / mp4v (the defaults), expect
  roughly 400–800 MB per hour of continuous recording. Higher resolutions
  set in the dashboard will use proportionally more.
- **Person detection** is a lightweight classical detector (not a neural
  network), so it works offline with no extra downloads, but it can miss
  people at odd angles or in low light, and can occasionally false-flag.
  Treat it as a "here's where to look first" pointer, not proof. Motion
  detection is more sensitive but less specific — it'll flag anything that
  changes in frame, including lighting shifts.
- **Legacy clips**: any `.mp4` already in `recordings/` before this version
  (with no matching `.json`) will still show up in the dashboard, just
  without detection tags or duration.
- **Privacy**: this records whoever is near your desk while your session
  is locked, including coworkers who may not know it's recording — treat
  the footage with the same care you'd want applied to your own image.
  Check your workplace's policy on personal recording devices before
  deploying this, and keep the recordings folder private (it's on your
  local disk, not synced anywhere by this script or the dashboard).
- **Virtual lock security**: the hotkey overlay is a convenience lock inside
  DeskGuard, not the Windows secure desktop. Someone who can use Task Manager
  or stop the process may bypass it. Use `lock_mode: "native"` when you need
  actual Windows session protection.
- **Dashboard access**: the web dashboard now requires a password. The initial
  password is `227842`; change it from the
  Settings page before relying on the dashboard. The same page lets you choose
  `lock_mode`, hotkey modifiers, and the hotkey key. Restart the NSSM service
  after changing the hotkey so the recorder registers the new combination.
