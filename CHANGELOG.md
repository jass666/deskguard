# Changelog

All notable changes to **DeskGuard** are documented here.

Project created and maintained by **Jaswant Kanojia**.

**Latest release date:** 17-09-2026

---

## Unreleased

### Added
- Added a dashboard Settings field for changing the virtual lock overlay's
  unlock code without editing `config.json`.

---

## v1.3 - Virtual Lock Input Blocking + Kill-Resistance
**Date:** 17-09-2026

### Why
Native Windows lock mode is where the camera-frame-revocation bug lives
(see v1.2 below) - the driver simply won't hand frames to a process once
the *real* secure desktop is up. Rather than keep fighting that, this
release makes `hotkey`/virtual-lock mode a real substitute for native
lock instead of a weaker fallback: the session is never actually locked
by Windows, so the camera never sees a lock event and keeps recording
normally, while a full-screen overlay plus real input blocking take over
the "keep this desk secure" job.

### Added
- **`input_lock.py`** - global low-level Win32 hooks (`WH_MOUSE_LL`,
  `WH_KEYBOARD_LL`). While the virtual lock overlay is up: the mouse is
  completely dead (movement, all buttons, both wheels) and the cursor is
  pinned/hidden; the Windows key, Alt+Tab, Ctrl+Esc, Ctrl+Shift+Esc, and
  Alt+F4 are all swallowed before the OS acts on them. Normal typing
  still reaches the unlock-code field untouched. Documented limit:
  Ctrl+Alt+Del cannot be blocked by any userland process - it's routed
  to Winlogon via the Secure Attention Sequence before any hook sees it.
  Toggle with `"block_input"` in config.json.
- **`watchdog.py`** - a separate process that polls a heartbeat file
  written by `deskguard.py` (`logs/heartbeat.json`, refreshed every
  `heartbeat_interval_sec`). If the recorder's heartbeat goes stale or
  its pid actually exits *while a lock was active* - i.e. someone got to
  Ctrl+Alt+Del -> Task Manager -> End Task, the one thing input_lock.py
  cannot stop - the watchdog immediately calls the real
  `LockWorkStation()` API. This turns "the recorder got killed" from a
  clean escape into: the machine is now under the actual Windows lock
  screen, and whatever was captured in the seconds it took to reach
  Task Manager is already saved to disk.
- **Segmented recording** - lock sessions now write a new clip file
  every `segment_seconds` (default 15s) instead of one file for the
  whole session. A kill mid-lock now costs at most the current segment,
  not the whole recording. Motion/freeze detection state carries across
  segment boundaries so nothing resets mid-session.
- **`DeskGuard_TaskScheduler_Setup.bat`** - registers both
  `deskguard.py` and `watchdog.py` as "run at logon" Scheduled Tasks in
  the interactive session (not NSSM - see the script header for why:
  Session 0 services can't open a camera or install input hooks tied to
  the logged-in user's desktop).
- New config keys: `block_input`, `segment_seconds`,
  `heartbeat_interval_sec`, `watchdog_timeout_sec`.
- **Instant identification snapshot** - a JPEG is saved the moment the
  first frame of a lock session arrives, completely independent of the
  video segment pipeline. If a segment file, codec, or disk write ever
  fails, this still exists - it's the fastest, least-dependent path to
  "who did it", which is the actual point of the lock.
- Segment metadata now records `windows_user` (the active Windows
  account at record time) alongside the video/detection data.

### Known limitation carried forward
Ctrl+Alt+Del itself is un-blockable by design (see above) - this was
true before this release and remains true after it. What changed is
the response: instead of silently letting the process die, the watchdog
now converts that specific escape into a real OS-level lock.

### Reliability fixes
- Fixed freeze detection so repeated identical frames are correctly reported
  after `freeze_detect_sec` instead of resetting the timer on every frame.
- Made input-lock cleanup safe when the overlay unlock path and its safety
  cleanup both run, preventing cursor visibility/state drift.
- Hardened watchdog process-liveness checks for 64-bit Windows handles.
- Added an explicit video-writer open check so unsupported codecs or invalid
  recording settings fail clearly instead of producing silent empty clips.
- Verified Python compilation, dashboard authentication/routes, and segmented
  recording with metadata and snapshot generation using a synthetic camera.

---

## v1.1.1 - Deployment Notes
**Date:** 16-09-2026

### Added
- Documented deployment of the Flask dashboard as a separate NSSM service.
- Documented exposing the dashboard through an ngrok tunnel on local port
  `5151`, with authentication recommended before public exposure.
- Documented the recommended split deployment: Task Scheduler for the
  recorder and NSSM for the dashboard/ngrok processes.

### Known limitations
- The recorder receives the Windows session-lock event, but the webcam
  driver tested does not deliver frames after the session is locked. The
  resulting MP4 may therefore be an empty, approximately 257-byte file even
  though the camera works while Windows is unlocked.
- Running the recorder through NSSM is not reliable for this workflow because
  Windows services run outside the interactive desktop session. A pre-opened
  camera capture or separate network camera is required for further testing.

---

## v1.1 - Review Dashboard
**Date:** 16-09-2026

### Added
- `dashboard.py`: a local Flask web UI (`http://127.0.0.1:5151`, localhost
  only) to browse, filter, and play back recordings, and to edit recording
  settings without touching code.
  - Recordings list with auto-generated thumbnails, duration, size, and
    Person/Motion tags; filter chips for All / Person detected / Motion
    only / No detections.
  - Inline video playback (expand a row to play, no separate page).
  - One-click delete (removes the clip, its metadata, and its thumbnail).
  - Settings page: camera index, resolution (320x240 up to 1280x720), fps,
    total/per-clip storage caps, and person/motion detection sensitivity —
    written to `config.json`, picked up by the recorder on its next
    lock/unlock cycle.
  - Storage-used meter in the sidebar.
- `deskguard_config.py`: shared config module — `config.json` is now the
  single source of truth for all tunables, read by both the recorder and
  the dashboard, created with sensible defaults on first run.
- Motion detection added to the recorder as a detector independent of
  person detection (frame-differencing + contour area threshold), so
  clips can now be tagged "Motion" even when no person is recognized.
- Per-clip `.json` metadata sidecar written alongside each `.mp4`
  (start/end time, resolution, fps, person/motion event timestamps) — this
  is what the dashboard reads instead of parsing the log file.
- `flask` added as a dependency.

### Changed
- All previously hardcoded constants in `deskguard.py` (resolution, fps,
  camera index, storage caps, detection thresholds) now come from
  `config.json`, reloaded at the start of every lock/unlock cycle.
- `enforce_storage_cap()` now also removes a deleted clip's `.json` and
  thumbnail, not just the `.mp4`.

### Files Changed
| File | Change |
|------|--------|
| `dashboard.py` | New — review UI and settings |
| `deskguard_config.py` | New — shared config load/save |
| `deskguard.py` | Modified — config-driven, motion detection, metadata sidecars |
| `requirements.txt` | Added `flask` |
| `README.md` | Documents the dashboard and updated setup flow |

---

## v1.0 - Initial Release
**Date:** 16-09-2026

### Added
- Windows session-lock webcam recorder: hooks the native
  `WM_WTSSESSION_CHANGE` session notification (via `WTSRegisterSessionNotification`)
  to detect `WTS_SESSION_LOCK` / `WTS_SESSION_UNLOCK` directly from the OS —
  no polling, fires on Win+L, idle auto-lock, or Ctrl+Alt+Del > Lock.
- Recording starts the instant the session locks and stops the instant it
  unlocks, writing an mp4 clip named `lock_<timestamp>.mp4` to a local
  `recordings/` folder.
- Person detection: OpenCV's built-in HOG + Linear SVM detector runs on the
  feed roughly every 2 seconds, draws a bounding box on detected frames, and
  logs each detection (with timestamp and confidence) so an incident can be
  found without scrubbing the full clip.
- Timestamp burned directly into each recorded frame.
- Storage cap: total size of `recordings/` is kept under 5 GB by deleting
  the oldest clips first; a 4 GB per-clip safety stop guards against an
  unusually long single lock session filling the disk.
- Event logging: lock/unlock times, person detections, clip deletions, and
  camera errors all written with timestamps to `recordings/deskguard_events.log`.
- `README.md` covering setup, running via `pythonw.exe` with no console
  window, autostart via the Windows Startup folder, and known limitations.

### Design notes
- Built after a personal item went missing from the user's own desk during
  lunch, with no CCTV coverage and no leads from asking coworkers directly.
- Chosen response was to harden the user's own desk environment rather than
  escalate to the office owner (item was low value) or treat it as a reason
  to leave the job.

### Known limitations
- Recording fails silently (logged, not crashed) if another application is
  already holding the webcam when the lock event fires.
- Person detector is a classical (non-neural) model — works fully offline
  with no extra downloads, but can miss unusual angles/lighting and can
  occasionally false-positive; treated as a pointer to check, not proof.
- Windows only — depends on Win32 session-notification APIs.

### Files Changed
| File | Change |
|------|--------|
| `deskguard.py` | New — main monitoring script |
| `requirements.txt` | New — `pywin32`, `opencv-python`, `numpy` |
| `README.md` | New — setup, autostart, and limitations |

---

*Personal desk-security tool — Jaswant Kanojia, Lucknow.*
