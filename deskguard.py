"""
DeskGuard v1.2 - Records webcam footage whenever the Windows session is
locked, and stops when you unlock.

WHAT CHANGED IN v1.2 (and why)
------------------------------
v1.1.1 logged this limitation: "the webcam driver tested does not deliver
frames after the session is locked ... the resulting MP4 may be an empty,
approximately 257-byte file."

Root cause: on Windows 10 1803+ camera access is brokered by the Windows
Camera Frame Server. When the session locks, the input desktop switches to
the secure (Winlogon) desktop and the Frame Server refuses to hand a camera
stream to a process that asks for one *from a locked session*. The old code
called cv2.VideoCapture() inside the lock handler - i.e. at exactly the
moment the OS will not grant it - so isOpened() succeeded (DirectShow graph
built) but every cap.read() returned False, the loop spun on `continue`
until unlock, and VideoWriter closed a header-only file.

Fix: never open the camera after the lock. A single CameraSupervisor thread
opens the capture once at startup (while unlocked, when the grant is given)
and keeps reading from it forever. An already-granted stream generally keeps
flowing across the lock boundary. The lock handler now only starts/stops the
VideoWriter; it never touches the device.

Also added:
  - Sleep inhibitor (SetThreadExecutionState) so the machine cannot drop to
    sleep/modern standby mid-recording, which kills capture regardless.
  - Freeze detection: if frames stop changing after lock, that is logged
    explicitly instead of silently producing a static clip.
  - Empty clips are deleted rather than left as 257-byte files.
  - Automatic camera reopen with backoff if the device is lost.

NOTE: because the camera is held open permanently, the webcam indicator LED
stays lit whenever DeskGuard is running. Set "keep_camera_open": false in
config.json to go back to v1.1 open-on-lock behaviour (not recommended).

Requires (Windows only):
    pip install -r requirements.txt

Run:
    python deskguard.py
    (or pythonw.exe deskguard.py for no console window, see README)
"""

import os
import sys
import time
import ctypes
import getpass
import threading
import datetime
import glob
import json
import logging
import tkinter as tk

import cv2
import numpy as np
import win32gui
import win32con
import win32ts
import win32api

from deskguard_config import load_config, RECORDINGS_DIR, LOGS_DIR, LOG_FILE
from input_lock import InputLock

HEARTBEAT_PATH = os.path.join(LOGS_DIR, "heartbeat.json")

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
os.makedirs(RECORDINGS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def log(msg):
    print(msg)
    logging.info(msg)


# ---------------------------------------------------------------------------
# Keep the machine awake while recording
# ---------------------------------------------------------------------------
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_AWAYMODE_REQUIRED = 0x00000040


def inhibit_sleep(on):
    """Per-thread sleep inhibitor. Call from the thread that must stay alive.

    Without this, a locked laptop hits its idle sleep timer a few minutes in
    and the recording dies halfway through - which looks identical to the
    frame-server problem in the logs, so it is worth ruling out.
    """
    try:
        if on:
            flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
            if ctypes.windll.kernel32.SetThreadExecutionState(flags) == 0:
                # AWAYMODE is not supported on every machine; retry without it.
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED
                )
        else:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    except Exception as e:  # never let a power API failure kill the recorder
        log(f"WARNING: could not set sleep inhibitor: {e}")


def write_heartbeat(locked):
    """Refreshes logs/heartbeat.json for watchdog.py to poll.

    Written on a fixed interval regardless of lock state (see
    SessionWatcher._heartbeat_loop) so a stale timestamp reliably means
    "this process stopped running/responding", not "it just hasn't
    locked recently".
    """
    payload = {
        "pid": os.getpid(),
        "ts": datetime.datetime.now().isoformat(),
        "locked": bool(locked),
    }
    tmp_path = HEARTBEAT_PATH + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(payload, f)
        os.replace(tmp_path, HEARTBEAT_PATH)  # atomic, same trick as save_config
    except OSError as e:
        log(f"WARNING: could not write heartbeat: {e}")


def frame_signature(frame):
    """Cheap hash of a frame, used only to notice a frozen stream."""
    return int(frame[::16, ::16, 0].astype(np.int64).sum())


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
# Camera supervisor - owns the device for the lifetime of the process
# ---------------------------------------------------------------------------
BACKENDS = {
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "any": cv2.CAP_ANY,
}


class CameraSupervisor(threading.Thread):
    """Opens the webcam once, while the session is unlocked, and keeps it open.

    This is the whole point of v1.2: the capture grant is obtained before the
    lock, so the Frame Server never has to decide whether to hand a stream to
    a locked session. Consumers pull the newest frame via latest().
    """

    def __init__(self, cfg):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.width, self.height = cfg["resolution"]
        self.record_fps = cfg["fps"]
        self.idle_fps = max(1, int(cfg.get("idle_fps", 2)))
        self.backend = BACKENDS.get(str(cfg.get("capture_backend", "dshow")).lower(),
                                    cv2.CAP_DSHOW)

        self._cap = None
        self._lock = threading.Lock()
        self._frame = None
        self._frame_id = 0
        self._frame_time = 0.0
        self._stop = threading.Event()
        self._recording = threading.Event()  # set => pump at full fps
        self._consecutive_failures = 0

    # -- public API ---------------------------------------------------------
    def latest(self):
        """Returns (frame_copy, frame_id, capture_time) or (None, 0, 0.0)."""
        with self._lock:
            if self._frame is None:
                return None, 0, 0.0
            return self._frame.copy(), self._frame_id, self._frame_time

    def set_recording(self, on):
        if on:
            self._recording.set()
        else:
            self._recording.clear()

    def shutdown(self):
        self._stop.set()

    # -- internals ----------------------------------------------------------
    def _open(self):
        self._close()
        cap = cv2.VideoCapture(self.cfg["camera_index"], self.backend)
        if not cap.isOpened():
            log("ERROR: could not open webcam - is another app (Zoom/Teams) holding it?")
            cap.release()
            return False

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.record_fps)
        # Small buffer so a locked-session backlog does not make footage lag.
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        # Prove the stream actually delivers before declaring success - an
        # opened-but-dead capture is exactly the v1.1.1 failure mode.
        for _ in range(10):
            ok, frame = cap.read()
            if ok and frame is not None:
                self._cap = cap
                actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                log(f"Camera opened and streaming ({actual_w}x{actual_h}, "
                    f"backend={self.cfg.get('capture_backend', 'dshow')}).")
                return True
            time.sleep(0.1)

        log("ERROR: camera opened but delivered no frames - treating as failed.")
        cap.release()
        return False

    def _close(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def run(self):
        backoff = 1.0
        while not self._stop.is_set():
            if self._cap is None:
                if self._open():
                    backoff = 1.0
                    self._consecutive_failures = 0
                else:
                    # Never give up - the blocking app may close, or the user
                    # may unlock and free the device.
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, 30.0)
                    continue

            target_fps = self.record_fps if self._recording.is_set() else self.idle_fps
            interval = 1.0 / max(1, target_fps)
            loop_start = time.time()

            ok, frame = self._cap.read()
            if ok and frame is not None:
                self._consecutive_failures = 0
                if frame.shape[1] != self.width or frame.shape[0] != self.height:
                    frame = cv2.resize(frame, (self.width, self.height))
                with self._lock:
                    self._frame = frame
                    self._frame_id += 1
                    self._frame_time = time.time()
            else:
                self._consecutive_failures += 1
                if self._consecutive_failures in (15, 60):
                    log(f"WARNING: {self._consecutive_failures} consecutive failed "
                        f"reads{' WHILE LOCKED' if self._recording.is_set() else ''} "
                        f"- camera stream may have been revoked.")
                if self._consecutive_failures >= 120:
                    log("Camera stream lost - reopening device.")
                    self._close()
                    self._consecutive_failures = 0
                    continue

            sleep_for = interval - (time.time() - loop_start)
            if sleep_for > 0:
                self._stop.wait(sleep_for)

        self._close()


# ---------------------------------------------------------------------------
# Recording worker - consumes frames, never opens the device
# ---------------------------------------------------------------------------
class RecordingSession:
    def __init__(self, camera):
        self.camera = camera
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

    @staticmethod
    def _open_segment(cfg, width, height, fps):
        """Starts one segment's file + writer + metadata dict.

        Segmenting exists so that killing the process mid-lock (the one
        thing input_lock.py cannot prevent - see its docstring) loses at
        most the current segment, not the entire lock session. Each
        segment is a fully independent, playable MP4 with its own JSON
        sidecar, same as today's single-clip-per-lock files were.
        """
        start_dt = datetime.datetime.now()
        timestamp = start_dt.strftime("%Y%m%d_%H%M%S_%f")
        filename = f"lock_{timestamp}.mp4"
        filepath = os.path.join(RECORDINGS_DIR, filename)
        meta_path = os.path.join(RECORDINGS_DIR, f"lock_{timestamp}.json")

        fourcc = cv2.VideoWriter_fourcc(*cfg["codec"])
        writer = cv2.VideoWriter(filepath, fourcc, fps, (width, height))

        metadata = {
            "file": filename,
            "start": start_dt.isoformat(),
            "end": None,
            "windows_user": getpass.getuser(),
            "resolution": [width, height],
            "fps": fps,
            "person_events": [],
            "motion_events": [],
            "frames_written": 0,
            "warnings": [],
        }
        log(f"Recording segment started -> {filename}")
        return writer, filepath, meta_path, metadata, filename

    @staticmethod
    def _finalize_segment(writer, filepath, meta_path, metadata, frames_written,
                           discard_empty):
        writer.release()
        metadata["end"] = datetime.datetime.now().isoformat()
        metadata["frames_written"] = frames_written

        if frames_written == 0 and discard_empty:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except OSError:
                pass
            log("Segment produced ZERO frames - empty clip discarded. "
                "The camera did not stream while locked; run "
                "camera_lock_probe.py to find a backend that does.")
            return

        try:
            metadata["size_bytes"] = os.path.getsize(filepath) if os.path.exists(filepath) else 0
        except OSError:
            metadata["size_bytes"] = 0
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)
        log(f"Segment finalized -> {metadata['file']} ({frames_written} frames)")

    def _run(self):
        cfg = load_config()
        width, height = self.camera.width, self.camera.height
        fps = cfg["fps"]
        freeze_after = float(cfg.get("freeze_detect_sec", 8))
        discard_empty = bool(cfg.get("discard_empty_clips", True))
        segment_seconds = float(cfg.get("segment_seconds", 15))

        enforce_storage_cap(cfg["max_total_storage_gb"])
        inhibit_sleep(True)
        self.camera.set_recording(True)

        hog = None
        if cfg["detect_person"]:
            hog = cv2.HOGDescriptor()
            hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        writer, filepath, meta_path, metadata, filename = self._open_segment(
            cfg, width, height, fps
        )
        segment_started_at = time.time()

        frames_written = 0          # this segment only
        total_frames_written = 0    # whole lock session, for the final log line
        last_frame_id = 0
        frame_interval = 1.0 / fps
        person_check_every_n = max(1, int(fps * cfg["person_check_interval_sec"]))
        prev_gray = None
        last_motion_log = 0.0
        last_new_frame_at = time.time()
        last_signature = None
        freeze_reported = False
        starvation_reported = False
        first_frame_saved = False
        per_clip_cap_bytes = cfg["per_clip_safety_gb"] * 1024 * 1024 * 1024

        try:
            while not self._stop_event.is_set():
                loop_start = time.time()

                frame, frame_id, _ = self.camera.latest()

                if frame is None or frame_id == last_frame_id:
                    # No new frame yet. Distinguish "camera never delivered
                    # anything after lock" from "just a slow tick".
                    starved_for = time.time() - last_new_frame_at
                    if starved_for > freeze_after and not starvation_reported:
                        msg = (f"No new frames for {starved_for:.0f}s after lock - "
                               f"the camera stream was almost certainly revoked by "
                               f"Windows. See README troubleshooting.")
                        log("WARNING: " + msg)
                        metadata["warnings"].append(msg)
                        starvation_reported = True
                    time.sleep(0.05)
                    continue

                last_frame_id = frame_id
                last_new_frame_at = time.time()
                now = last_new_frame_at

                if not first_frame_saved:
                    # Guaranteed identification shot: written the instant the
                    # first frame arrives, completely independent of the video
                    # segment pipeline below. If a segment file, codec, or
                    # disk write ever fails, this still exists - the whole
                    # point of the lock is "who did it", and this is the
                    # fastest, least-dependent way to answer that.
                    snap_path = os.path.join(
                        RECORDINGS_DIR,
                        f"{os.path.splitext(filename)[0]}_snapshot.jpg",
                    )
                    try:
                        cv2.imwrite(snap_path, frame)
                        log(f"Instant identification snapshot saved -> "
                            f"{os.path.basename(snap_path)}")
                    except Exception as e:
                        log(f"WARNING: could not save instant snapshot: {e}")
                    first_frame_saved = True

                # A stream that ticks but never changes = frozen last frame.
                sig = frame_signature(frame)
                if last_signature is not None and sig == last_signature:
                    if (now - last_new_frame_at) > freeze_after and not freeze_reported:
                        msg = "Frames are arriving but identical - stream appears frozen."
                        log("WARNING: " + msg)
                        metadata["warnings"].append(msg)
                        freeze_reported = True
                last_signature = sig

                if cfg["detect_motion"]:
                    prev_gray, motion_logged = self._run_motion_detection(
                        frame, prev_gray, cfg, metadata, now, last_motion_log
                    )
                    if motion_logged:
                        last_motion_log = now

                if hog is not None and total_frames_written % person_check_every_n == 0:
                    self._run_person_detection(hog, frame, cfg, metadata, width, height)

                ts_label = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cv2.putText(
                    frame, ts_label, (8, height - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA,
                )

                writer.write(frame)
                frames_written += 1
                total_frames_written += 1

                size_cap_hit = False
                if frames_written % 30 == 0 and os.path.exists(filepath):
                    if os.path.getsize(filepath) > per_clip_cap_bytes:
                        size_cap_hit = True

                rotate_due = (time.time() - segment_started_at) >= segment_seconds

                if size_cap_hit or rotate_due:
                    self._finalize_segment(
                        writer, filepath, meta_path, metadata, frames_written, discard_empty
                    )
                    if size_cap_hit:
                        log("Per-clip safety limit reached mid-segment - "
                            "starting a fresh segment early.")
                    if self._stop_event.is_set():
                        break
                    writer, filepath, meta_path, metadata, filename = self._open_segment(
                        cfg, width, height, fps
                    )
                    segment_started_at = time.time()
                    frames_written = 0
                    freeze_reported = False
                    starvation_reported = False
                    # prev_gray/last_signature intentionally carry over so
                    # motion/freeze detection stays continuous across the
                    # segment boundary instead of re-baselining each time.

                sleep_for = frame_interval - (time.time() - loop_start)
                if sleep_for > 0:
                    time.sleep(sleep_for)

        finally:
            self._finalize_segment(
                writer, filepath, meta_path, metadata, frames_written, discard_empty
            )
            self.camera.set_recording(False)
            inhibit_sleep(False)
            log(f"Recording stopped for this lock session "
                f"({total_frames_written} frames total).")
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
WM_HOTKEY = 0x0312
HOTKEY_ID = 1
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004


class VirtualLockOverlay:
    """Full-screen app lock released by the configured code.

    This is a convenience lock, not the Windows secure desktop.
    """

    def __init__(self, unlock_code, on_unlock, block_input=True):
        self.unlock_code = str(unlock_code)
        self.on_unlock = on_unlock
        self.block_input = block_input

    def show(self):
        input_lock = InputLock() if self.block_input else None

        root = tk.Tk()
        root.title("DeskGuard locked")
        root.configure(bg="#101820")
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", lambda: None)
        root.bind("<Alt-F4>", lambda _event: "break")
        root.bind("<Escape>", lambda _event: "break")
        try:
            root.attributes("-fullscreen", True)
        except tk.TclError:
            root.state("zoomed")
        root.focus_force()
        root.grab_set()

        if input_lock is not None:
            try:
                input_lock.start()
                log("Input lock engaged: mouse dead, escape combos blocked. "
                    "(Ctrl+Alt+Del cannot be blocked by design - see input_lock.py.)")
            except OSError as e:
                log(f"WARNING: {e} Overlay is up but NOT enforcing input block.")
                input_lock = None

        panel = tk.Frame(root, bg="#101820")
        panel.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(panel, text="DeskGuard", fg="#70d6ff", bg="#101820",
                 font=("Segoe UI", 30, "bold")).pack(pady=(0, 12))
        tk.Label(panel, text="This computer is protected", fg="white",
                 bg="#101820", font=("Segoe UI", 18)).pack(pady=(0, 22))
        entry = tk.Entry(panel, show="•", width=24, justify="center",
                         font=("Segoe UI", 18), relief="flat")
        entry.pack(ipady=8, pady=(0, 10))
        message = tk.Label(panel, text="Enter your unlock code", fg="#b7c9d3",
                           bg="#101820", font=("Segoe UI", 11))
        message.pack(pady=(0, 12))

        def try_unlock(_event=None):
            if entry.get() == self.unlock_code:
                if input_lock is not None:
                    input_lock.stop()
                self.on_unlock()
                root.grab_release()
                root.destroy()
            else:
                entry.delete(0, tk.END)
                message.configure(text="Incorrect code", fg="#ff8a80")
                entry.focus_set()

        entry.bind("<Return>", try_unlock)
        tk.Button(panel, text="Unlock", command=try_unlock,
                  font=("Segoe UI", 12), padx=24, pady=6).pack()
        entry.focus_set()
        try:
            root.mainloop()
        finally:
            # Safety net: if the window ever goes away through some path
            # other than a correct unlock (it shouldn't, given
            # WM_DELETE_WINDOW/Alt-F4/Escape are all suppressed above),
            # make sure input is never left permanently blocked.
            if input_lock is not None:
                input_lock.stop()


def hotkey_flags(cfg):
    flags = 0
    for modifier in str(cfg.get("hotkey_modifiers", "ctrl+alt")).lower().split("+"):
        if modifier.strip() in ("ctrl", "control"):
            flags |= MOD_CONTROL
        elif modifier.strip() == "alt":
            flags |= MOD_ALT
        elif modifier.strip() == "shift":
            flags |= MOD_SHIFT
    return flags


class SessionWatcher:
    def __init__(self, cfg):
        self.cfg = cfg
        self.camera = CameraSupervisor(cfg)
        self.session = RecordingSession(self.camera)
        self.hwnd = None
        self.virtual_lock_active = False
        self._locked_for_heartbeat = False   # what watchdog.py cares about
        self._heartbeat_stop = threading.Event()

    def _heartbeat_loop(self):
        interval = float(self.cfg.get("heartbeat_interval_sec", 2))
        while not self._heartbeat_stop.is_set():
            write_heartbeat(self._locked_for_heartbeat)
            self._heartbeat_stop.wait(interval)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_WTSSESSION_CHANGE:
            if wparam == WTS_SESSION_LOCK:
                log("Session LOCKED - starting recording.")
                self._locked_for_heartbeat = True
                write_heartbeat(True)  # update immediately, don't wait for the tick
                self.session.start()
            elif wparam == WTS_SESSION_UNLOCK:
                log("Session UNLOCKED - stopping recording.")
                self._locked_for_heartbeat = False
                write_heartbeat(False)
                # Stop on a helper thread so a slow writer flush cannot stall
                # the message pump and drop the next lock notification.
                threading.Thread(target=self.session.stop, daemon=True).start()
            return 0
        elif msg == WM_HOTKEY and wparam == HOTKEY_ID:
            if not self.virtual_lock_active:
                self._activate_virtual_lock()
            return 0
        elif msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _activate_virtual_lock(self):
        self.virtual_lock_active = True
        self._locked_for_heartbeat = True
        write_heartbeat(True)
        log("Virtual lock activated - starting recording.")
        self.session.start()

        def unlock():
            log("Virtual lock unlocked - stopping recording.")
            self._locked_for_heartbeat = False
            write_heartbeat(False)
            threading.Thread(target=self.session.stop, daemon=True).start()
            self.virtual_lock_active = False

        threading.Thread(
            target=VirtualLockOverlay(
                self.cfg.get("unlock_code", "1234"), unlock,
                block_input=bool(self.cfg.get("block_input", True)),
            ).show,
            daemon=True,
        ).start()

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

        native_mode = str(self.cfg.get("lock_mode", "native")).lower() != "hotkey"
        if native_mode:
            win32ts.WTSRegisterSessionNotification(self.hwnd, NOTIFY_FOR_THIS_SESSION)
        else:
            key = str(self.cfg.get("hotkey_key", "L"))[0].upper()
            if not win32api.RegisterHotKey(self.hwnd, HOTKEY_ID,
                                           hotkey_flags(self.cfg), ord(key)):
                raise RuntimeError(f"Could not register hotkey for {key}.")

        if self.cfg.get("keep_camera_open", True):
            self.camera.start()
            log("Camera supervisor started - device held open across lock events.")
        else:
            log("keep_camera_open is false - v1.1 behaviour, expect empty clips.")

        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat_thread.start()
        log("Heartbeat thread started - watchdog.py can now supervise this process.")

        if native_mode:
            log("DeskGuard started in native lock mode. Watching for session lock/unlock.")
        else:
            log(f"DeskGuard started in virtual lock mode. Press {self.cfg.get('hotkey_modifiers', 'ctrl+alt')}+{key} to lock.")

        try:
            win32gui.PumpMessages()
        finally:
            if native_mode:
                win32ts.WTSUnRegisterSessionNotification(self.hwnd)
            else:
                win32api.UnregisterHotKey(self.hwnd, HOTKEY_ID)
            self._heartbeat_stop.set()
            heartbeat_thread.join(timeout=5)
            self.session.stop()
            self.camera.shutdown()


if __name__ == "__main__":
    if os.name != "nt":
        sys.exit("DeskGuard only runs on Windows (uses Win32 session notifications).")
    config = load_config()
    watcher = SessionWatcher(config)
    watcher.run()
