# DeskGuard

Records your webcam automatically whenever your Windows session locks
(Win+L, walk-away auto-lock, Ctrl+Alt+Del > Lock — anything that fires a
lock event), and stops as soon as you unlock. Comes with a local web
dashboard to browse, filter, and play back clips, and to change recording
settings without touching code. Everything stays on your machine.

## Files

| File | Purpose |
|------|---------|
| `deskguard.py` | The recorder — run this in the background, always on |
| `dashboard.py` | The review UI — run when you want to browse clips or change settings |
| `deskguard_config.py` | Shared config loader used by both of the above |
| `config.json` | Your settings — created automatically on first run |
| `recordings/` | Where clips, thumbnails, and per-clip metadata land |
| `logs/` | Where runtime logs land |

## What the recorder does

- Hooks Windows' native session lock/unlock event — no polling, no
  keylogging, just listens for the OS telling it "this session just locked."
- Starts recording your default webcam the instant it locks, stops the
  instant you unlock.
- Detects **motion** (frame-difference based) and **people** (OpenCV's
  built-in HOG detector) independently, logging timestamped events for
  each and drawing a box around detected people in the footage.
- Writes a `.json` metadata sidecar next to each clip (start/end time,
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

1. Install Python 3.9+ on Windows if you don't have it.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Start the recorder:
   ```
   python deskguard.py
   ```
   Lock your screen (Win+L) to test — a new file should appear in
   `recordings/` and the console should print "Session LOCKED - starting
   recording."
4. In a separate terminal, start the dashboard:
   ```
   python dashboard.py
   ```
   Open `http://127.0.0.1:5151` to browse.

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
