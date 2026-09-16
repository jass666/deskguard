"""
DeskGuard - Records webcam footage whenever the Windows session is locked
(Win+L, auto-lock on idle, Ctrl+Alt+Del > Lock, etc.), and stops when you
unlock. Detects motion and people, tags each clip with a metadata sidecar
file, and enforces a total storage cap across the recordings folder.

All tunable settings live in config.json (created with defaults on first
run) - edit it directly, or use dashboard.py's Settings page.

Requires (Windows only):
    pip install -r requirements.txt

Run:
    python deskguard.py
    (or use pythonw.exe to run with no console window, see README)
"""

import os
import sys
import time
import threading
import datetime
import glob
import json
import logging

import cv2
import numpy as np
import win32gui
import win32con
import win32ts
import win32api

from deskguard_config import load_config, RECORDINGS_DIR, LOG_FILE

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
os.makedirs(RECORDINGS_DIR, exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def log(msg):
    print(msg)
    logging.info(msg)


# ---------------------------------------------------------------------------
# Storage management
# ---------------------------------------------------------------------------
def folder_size_bytes(folder):
    total = 0
    for f in glob.glob(os.path.join(folder, "*.mp4")):
        try:
            total += os.path.getsize(f)
        except OSError:
            pass
    return total


def enforce_storage_cap(max_total_storage_gb):
    """Delete oldest clips (+ their metadata/thumbnail) until under the cap."""
    cap_bytes = max_total_storage_gb * 1024 * 1024 * 1024
    files = sorted(
        glob.glob(os.path.join(RECORDINGS_DIR, "*.mp4")),
        key=os.path.getmtime,
    )
    while folder_size_bytes(RECORDINGS_DIR) > cap_bytes and files:
        oldest = files.pop(0)
        for related in (oldest, oldest[:-4] + ".json", oldest[:-4] + ".thumb.jpg"):
            try:
                if os.path.exists(related):
                    os.remove(related)
            except OSError as e:
                log(f"Could not delete {related}: {e}")
        log(f"Storage cap reached - deleted oldest clip: {os.path.basename(oldest)}")


# ---------------------------------------------------------------------------
# Recording worker
# ---------------------------------------------------------------------------
class RecordingSession:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return  # already recording
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _run(self):
        cfg = load_config()  # re-read at the start of every lock, so dashboard changes apply
        width, height = cfg["resolution"]
        fps = cfg["fps"]

        enforce_storage_cap(cfg["max_total_storage_gb"])

        start_dt = datetime.datetime.now()
        timestamp = start_dt.strftime("%Y%m%d_%H%M%S")
        filename = f"lock_{timestamp}.mp4"
        filepath = os.path.join(RECORDINGS_DIR, filename)
        meta_path = os.path.join(RECORDINGS_DIR, f"lock_{timestamp}.json")

        cap = cv2.VideoCapture(cfg["camera_index"], cv2.CAP_DSHOW)
        if not cap.isOpened():
            log("ERROR: could not open webcam - is it in use by another app?")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)

        fourcc = cv2.VideoWriter_fourcc(*cfg["codec"])
        writer = cv2.VideoWriter(filepath, fourcc, fps, (width, height))

        hog = None
        if cfg["detect_person"]:
            hog = cv2.HOGDescriptor()
            hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        metadata = {
            "file": filename,
            "start": start_dt.isoformat(),
            "end": None,
            "resolution": [width, height],
            "fps": fps,
            "person_events": [],
            "motion_events": [],
        }

        log(f"Recording started -> {filename}")

        frame_count = 0
        frame_interval = 1.0 / fps
        person_check_every_n = max(1, int(fps * cfg["person_check_interval_sec"]))
        prev_gray = None
        last_motion_log = 0.0

        try:
            while not self._stop_event.is_set():
                loop_start = time.time()

                ok, frame = cap.read()
                if not ok:
                    log("WARNING: dropped frame / camera read failed")
                    time.sleep(0.2)
                    continue

                frame = cv2.resize(frame, (width, height))
                frame_count += 1
                now = time.time()

                if cfg["detect_motion"]:
                    prev_gray, motion_logged = self._run_motion_detection(
                        frame, prev_gray, cfg, metadata, now, last_motion_log
                    )
                    if motion_logged:
                        last_motion_log = now

                if hog is not None and frame_count % person_check_every_n == 0:
                    self._run_person_detection(hog, frame, cfg, metadata, width, height)

                ts_label = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cv2.putText(
                    frame, ts_label, (8, height - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA,
                )

                writer.write(frame)

                per_clip_cap_bytes = cfg["per_clip_safety_gb"] * 1024 * 1024 * 1024
                if os.path.exists(filepath) and os.path.getsize(filepath) > per_clip_cap_bytes:
                    log("Per-clip safety limit reached - stopping this clip early.")
                    break

                elapsed = time.time() - loop_start
                sleep_for = frame_interval - elapsed
                if sleep_for > 0:
                    time.sleep(sleep_for)

        finally:
            cap.release()
            writer.release()
            metadata["end"] = datetime.datetime.now().isoformat()
            try:
                metadata["size_bytes"] = os.path.getsize(filepath) if os.path.exists(filepath) else 0
            except OSError:
                metadata["size_bytes"] = 0
            with open(meta_path, "w") as f:
                json.dump(metadata, f, indent=2)
            log(f"Recording stopped -> {filename}")
            enforce_storage_cap(cfg["max_total_storage_gb"])

    def _run_motion_detection(self, frame, prev_gray, cfg, metadata, now, last_motion_log):
        """Returns (updated_prev_gray, motion_was_logged_this_call)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if prev_gray is None:
            return gray, False

        diff = cv2.absdiff(prev_gray, gray)
        thresh = cv2.threshold(diff, cfg["motion_threshold"], 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        motion_found = any(cv2.contourArea(c) >= cfg["motion_min_area"] for c in contours)

        if motion_found and (now - last_motion_log) >= cfg["motion_log_cooldown_sec"]:
            ts_label = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log(f"Motion detected at {ts_label}")
            metadata["motion_events"].append({"time": ts_label})
            return gray, True

        return gray, False

    def _run_person_detection(self, hog, frame, cfg, metadata, width, height):
        small = cv2.resize(frame, (320, 240))
        rects, weights = hog.detectMultiScale(
            small, winStride=(8, 8), padding=(8, 8), scale=1.05
        )
        for (x, y, w, h), weight in zip(rects, weights):
            if weight >= cfg["person_confidence_threshold"]:
                ts_label = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log(f"Person detected at {ts_label} (confidence {float(weight):.2f})")
                metadata["person_events"].append({"time": ts_label, "confidence": float(weight)})
                sx, sy = width / 320, height / 240
                cv2.rectangle(
                    frame,
                    (int(x * sx), int(y * sy)),
                    (int((x + w) * sx), int((y + h) * sy)),
                    (0, 0, 255), 2,
                )


# ---------------------------------------------------------------------------
# Windows session lock/unlock hook
# ---------------------------------------------------------------------------
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0


class SessionWatcher:
    def __init__(self):
        self.session = RecordingSession()
        self.hwnd = None

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_WTSSESSION_CHANGE:
            if wparam == WTS_SESSION_LOCK:
                log("Session LOCKED - starting recording.")
                self.session.start()
            elif wparam == WTS_SESSION_UNLOCK:
                log("Session UNLOCKED - stopping recording.")
                self.session.stop()
            return 0
        elif msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def run(self):
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self._wnd_proc
        wc.lpszClassName = "DeskGuardSessionWatcher"
        wc.hInstance = win32api.GetModuleHandle(None)
        class_atom = win32gui.RegisterClass(wc)

        self.hwnd = win32gui.CreateWindow(
            class_atom, "DeskGuardSessionWatcher", 0, 0, 0, 0, 0, 0, 0,
            wc.hInstance, None,
        )

        win32ts.WTSRegisterSessionNotification(self.hwnd, NOTIFY_FOR_THIS_SESSION)
        log("DeskGuard started. Watching for session lock/unlock. Press Ctrl+C in this console to quit.")

        try:
            win32gui.PumpMessages()
        finally:
            win32ts.WTSUnRegisterSessionNotification(self.hwnd)
            self.session.stop()


if __name__ == "__main__":
    if os.name != "nt":
        sys.exit("DeskGuard only runs on Windows (uses Win32 session notifications).")
    watcher = SessionWatcher()
    watcher.run()
