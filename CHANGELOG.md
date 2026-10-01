# Changelog

All notable changes to **DeskGuard** are documented here.

Project created and maintained by **Jaswant Kanojia**.

**Latest release date:** 01-10-2026

---

## v1.7 – Canonical Packaged Runtime Configuration
**Date:** 01-10-2026

### Fixed
- **Recurring missing overlay / dead hotkey after packaged launches.** The
  source and dashboard processes read `config\config.json`, but older
  PyInstaller executables treated `dist` as their data root. That created a
  second configuration tree and allowed the packaged recorder to fall back to
  native/default mode, so `Ctrl+Alt+L` was never registered even though the
  dashboard showed hotkey mode.
- Frozen builds now resolve `dist\*.exe` runtime data to the project root,
  using the same `config\config.json`, `logs`, and `recordings` as the source
  processes. Standalone folders that contain the executable directly keep
  their previous behavior.
- `DeskGuard_Run.bat` and `DeskGuard_Build.bat` synchronize the packaged
  compatibility config files while older executables are being phased out.
- The build now stops before deleting `dist` when an elevated or orphaned
  DeskGuard process still holds an executable, avoiding a partial distribution
  that falsely reports a successful start.
- The run script now validates that all three packaged executables exist before
  launching and verifies the recorder and dashboard processes afterward,
  instead of reporting success after a partial build.
- Replaced batch `timeout` delays with `ping`-based delays so builds launched
  from redirected or non-interactive consoles do not emit the misleading
  "Input redirection is not supported" message.

### Verification
- Rebuilt all three PyInstaller executables successfully on 01-10-2026.
- Confirmed the packaged dashboard returned HTTP 200 at
  `http://127.0.0.1:5151` after `DeskGuard_Run.bat`.

### Upgrade note
- Rebuild the executables once with `scripts\DeskGuard_Build.bat`, then start
  with `scripts\DeskGuard_Run.bat`. Existing old executables can still read
  stale `dist` configuration until they are replaced.

---

## v1.6 – Silent-Failure Fixes, Startup Diagnostics + Kill Switch
**Date:** 28-09-2026

### Why
The recorder stopped responding to the lock hotkey (Ctrl+Alt+L) and showed no
sign of starting. The last log entries were from 25-09-2026: the recorder had
worked normally until then, and after that nothing was logged at all - no
startup line and no error. Under `pythonw.exe` / `--noconsole` builds, every
failure on the start-up path was invisible, so the cause could not be seen.
This release makes those failures visible and closes the paths that could
leave the hotkey dead.

### Fixed
- **Overlay crash no longer disables the hotkey.** The lock overlay runs on
  its own thread. If it raised an exception, the thread died silently while
  `virtual_lock_active` stayed `True`, so every later Ctrl+Alt+L was ignored
  and the camera kept running. The overlay is now wrapped: crashes are logged
  with a traceback, and the lock state, heartbeat, recording, and camera are
  reset if the overlay exits without a correct unlock.
- **`CameraSupervisor` no longer shadows `threading.Thread._stop`.** The
  stop event was named `_stop`, overwriting a method Python's `Thread` uses
  internally, which could break thread shutdown. Renamed to `_stop_evt`.

### Added
- **Hotkey logging.** Every press logs "Hotkey pressed."; a press ignored
  because a lock is already flagged active logs that too.
- **Hotkey registration errors are now visible.** A failed `RegisterHotKey`
  logs the WinError code (1409 = already registered by another program or
  another DeskGuard instance) and shows a message box pointing to Dashboard
  Settings, instead of exiting silently.
- **Instance-guard exit is logged.** A second recorder that exits because one
  is already running now writes a log line explaining what to do, instead of
  leaving no trace.
- **Crash logging.** Uncaught exceptions on the main thread or any worker
  thread are written to `deskguard_events.log`, and a "DeskGuard recorder
  starting (pid N)" line is logged at launch so a successful start is
  distinguishable from a silent failure.
- **`scripts\DeskGuard_KillSwitch.bat` / `.ps1`** - one-click emergency stop.
  Self-elevates, then: disables the `DeskGuardRecorder`, `DeskGuardWatchdog`,
  and `DeskGuard Public Share` tasks; kills the watchdog *before* the recorder
  (otherwise the watchdog fires `LockWorkStation()` when the recorder dies
  mid-lock); kills the recorder; stops the `DeskGuardDashboard` NSSM service
  and sets it to Disabled; kills the dashboard and the zrok share; removes
  `heartbeat.json`; releases any cursor clip; and verifies nothing is left,
  including port 5151. Processes are matched by exe name (`dist\*.exe`
  builds) or by command line (`src\deskguard.py`, `watchdog.py`,
  `dashboard.py`). `DeskGuard_KillSwitch.bat restore` re-enables everything.
  All actions are logged to `logs\killswitch.log`. If stuck behind the
  overlay, Ctrl+Alt+Del -> Task Manager -> Run new task -> the `.bat`.

### Known issues / notes
- `heartbeat.json` replace occasionally fails with `WinError 5` when the
  watchdog has the file open at the same moment. The recorder falls back to a
  direct write and logs a warning; this is harmless and expected.
- Recording fails (logged, not crashed) if another app such as Zoom or Teams
  is holding the webcam when the lock is activated; the camera supervisor
  keeps retrying with backoff.
- Start-up failures from an old recorder process still running, or from a
  Scheduled Task pointing at a stale `pythonw.exe` path, are now logged or
  shown, but the fix is still manual: end the old process, or re-run
  `DeskGuard_TaskScheduler_Setup.bat`.

### Files Changed
| File | Change |
|------|--------|
| `src/deskguard.py` | Modified - overlay crash handling, hotkey/start-up logging, `_stop_evt` rename |
| `scripts/DeskGuard_KillSwitch.bat` | New - launcher |
| `scripts/DeskGuard_KillSwitch.ps1` | New - stop/restore logic |

---

## v1.5 – Persistent zrok Dashboard Access

### Added
- Added a reserved zrok public name for the remote dashboard:
  `https://deskguard.shares.zrok.io`.
- Added `DeskGuard_Zrok_Setup.bat` for first-time Windows zrok setup,
  reserved-name creation, and startup-task registration.
- Added `Start_DeskGuard_Public.ps1` to start the local dashboard and reconnect
  the reserved zrok share after Windows logon.
- Added `Open_DeskGuard_Dashboard.bat` and `Open_DeskGuard_Dashboard.ps1` to
  start the dashboard when needed, open its stable local URL automatically,
  and report detected LAN addresses.
- Added inclusive start and end date filters to the dashboard recordings view;
  date selections remain active with detection filters and playback controls.
- Documented zrok setup, the dashboard-only authentication model, the hosted
  zrok interstitial, and the security considerations for remote recordings.

### Security
- The zrok enable token and dashboard password are intentionally not stored
  in the repository. The remote URL relies on DeskGuard's own dashboard login.

### Fixed
- Fixed the dashboard's single-clip Delete button returning a 500 error.
  `delete_clip_assets()` was accidentally registered as its own route on the
  same URL/method as `delete_recording()`; since it has no return value,
  Werkzeug always dispatched incoming requests to it first, and Flask raised
  `TypeError: view function did not return a valid response` on every click
  (the files were already deleted by that point, so the error masked a
  working delete). It's now a plain helper called by `delete_recording()` and
  `delete_selected_recordings()`, not a route of its own.
- Fixed storage-cap accounting and eviction counting each clip's
  `.browser.mp4` playback-cache copy as if it were a separate recording.
  `folder_size_bytes()` and `enforce_storage_cap()` globbed `*.mp4`, which
  also matched the H.264 copies generated for dashboard playback, roughly
  doubling the reported/enforced size for any clip that had been viewed and
  occasionally causing the oldest-first eviction to delete a cache file
  instead of an actual recording. Both now operate only on original clip
  files, and evicting a clip now also removes its `.browser.mp4` copy so it
  can't be orphaned.

---

## v1.4 – Dashboard Controls, Detection Reliability + Recording Management

### Added
- Added a dashboard Settings field for changing the virtual lock overlay's
  unlock code without editing `config.json`.
- Added dashboard toggles for enabling or disabling person detection and
  motion detection independently for new recordings.
- Constrained `opencv-python` to the 4.x line because OpenCV 5 removes the
  HOG people-detector API required for person movement detection.
- Improved person detection by preserving the camera aspect ratio and using a
  larger detection frame, making person boxes more reliable on 16:9 webcams.
- Added cached H.264 conversion for dashboard playback because browsers do not
  consistently decode the recorder's `mp4v` files.
- Fixed dashboard playback conversion by ensuring FFmpeg temporary outputs
  retain an `.mp4` suffix so the correct container is selected.
- Added a dedicated `recordings/clips/` folder for video recordings and
  related metadata, keeping dashboard/service logs separate.
- Further separated clip assets into `videos`, `metadata`, `snapshots`, and
  `thumbnails`; `videos` now contains video files only.
- Added a dashboard Refresh control for reloading the current recordings view.
- Added multi-select clip deletion with Select all support; associated metadata,
  snapshots, thumbnails, and browser cache files are deleted together.
- Fixed fast-forward playback by writing frames at the configured real-time
  cadence even when the camera supplies duplicate frames.
- Added portable Windows deployment scripts that install dependencies and build
  standalone recorder, watchdog, and dashboard executables with PyInstaller.

### Fixed
- Fixed recordings not being created when the installed OpenCV build does not
  include `HOGDescriptor`; person detection now disables itself with a warning
  while video recording continues.
- Added runtime protection so a person-detector error cannot stop video
  recording for the rest of the session.
- Added recording-worker exception logging and cleanup so writer or detection
  failures no longer terminate silently.
- Added a single-recorder guard and heartbeat-write fallback to prevent
  competing recorder instances or transient Windows file-sharing errors from
  interrupting lock-session recording.
- Verified a real virtual-lock session saves an MP4, metadata sidecar, and
  identification snapshot.

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
