# Changelog

All notable changes to **DeskGuard** are documented here.

Project created and maintained by **Jaswant Kanojia**.

**Latest release date:** 16-09-2026

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
