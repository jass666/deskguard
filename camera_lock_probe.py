"""
camera_lock_probe.py - find out exactly what your webcam does when Windows
locks, before spending any more time guessing.

There are four things that could be true on your machine, and they need
different fixes. This tells you which one you have.

Usage (run each, one at a time, from the DeskGuard folder):

    python camera_lock_probe.py --mode preopen --backend dshow
    python camera_lock_probe.py --mode preopen --backend msmf
    python camera_lock_probe.py --mode onlock  --backend dshow
    python camera_lock_probe.py --mode onlock  --backend msmf

For each run: start it, press Win+L, wait 60 seconds, unlock, press Ctrl+C.
Then read logs/probe_<mode>_<backend>.log.

  --mode preopen : opens the camera now and keeps it open across the lock
                   (this is what DeskGuard v1.2 does)
  --mode onlock  : waits for the lock, then opens the camera
                   (this is what v1.1 did, and what produced empty files)

Run only one probe at a time, and make sure DeskGuard itself is not running
- two processes competing for the camera will confuse the result.

Reading the output
------------------
  LOCKED ... frames=+8   -> the stream survives. This strategy works.
  LOCKED ... frames=+0   -> stream revoked or frozen at the lock boundary.
  LOCKED ... OPEN FAILED -> Windows refused to grant the camera while locked.
"""

import argparse
import ctypes
import datetime
import os
import sys
import time

import cv2

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

BACKENDS = {
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "any": cv2.CAP_ANY,
}

DESKTOP_SWITCHDESKTOP = 0x0100


def is_locked():
    """True when the secure (Winlogon) desktop owns input, i.e. locked.

    OpenInputDesktop fails when the input desktop belongs to Winlogon, which
    is exactly the lock screen. No polling of the session APIs needed.
    """
    user32 = ctypes.windll.user32
    hdesk = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if hdesk == 0:
        return True
    user32.CloseDesktop(hdesk)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["preopen", "onlock"], default="preopen")
    ap.add_argument("--backend", choices=list(BACKENDS), default="dshow")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    args = ap.parse_args()

    log_path = os.path.join(LOGS_DIR, f"probe_{args.mode}_{args.backend}.log")
    logf = open(log_path, "a", buffering=1)

    def emit(msg):
        line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
        print(line)
        logf.write(line + "\n")

    api = BACKENDS[args.backend]

    def open_cam():
        cap = cv2.VideoCapture(args.camera, api)
        if not cap.isOpened():
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        return cap

    emit("=" * 62)
    emit(f"PROBE START  mode={args.mode}  backend={args.backend}  camera={args.camera}")
    emit("Press Win+L, wait ~60s, unlock, then Ctrl+C here.")

    cap = None
    if args.mode == "preopen":
        cap = open_cam()
        emit("Pre-open while UNLOCKED: " + ("OK" if cap else "OPEN FAILED"))

    was_locked = False
    opened_while_locked = False
    frames_this_second = 0
    last_sig = None
    identical_streak = 0
    tick = time.time()

    try:
        while True:
            locked = is_locked()

            if locked and not was_locked:
                emit(">>> LOCK DETECTED")
                if args.mode == "onlock":
                    t0 = time.time()
                    cap = open_cam()
                    emit(f"Open attempt WHILE LOCKED: "
                         f"{'OK' if cap else 'OPEN FAILED'} "
                         f"({time.time() - t0:.1f}s)")
                    opened_while_locked = cap is not None
            elif not locked and was_locked:
                emit("<<< UNLOCK DETECTED")
                if args.mode == "onlock" and cap is not None:
                    cap.release()
                    cap = None
                    opened_while_locked = False
            was_locked = locked

            if cap is not None:
                ok, frame = cap.read()
                if ok and frame is not None:
                    frames_this_second += 1
                    sig = int(frame[::16, ::16, 0].sum())
                    if sig == last_sig:
                        identical_streak += 1
                    else:
                        identical_streak = 0
                    last_sig = sig
            else:
                time.sleep(0.05)

            if time.time() - tick >= 1.0:
                state = "LOCKED  " if locked else "unlocked"
                if cap is None:
                    detail = "no capture (OPEN FAILED)" if locked and args.mode == "onlock" \
                        else "no capture"
                else:
                    detail = f"frames=+{frames_this_second}"
                    if frames_this_second and identical_streak >= frames_this_second:
                        detail += "  [IDENTICAL - stream frozen]"
                emit(f"{state}  {detail}")
                frames_this_second = 0
                tick = time.time()

            time.sleep(0.01)

    except KeyboardInterrupt:
        emit("PROBE STOPPED by user")
    finally:
        if cap is not None:
            cap.release()
        emit(f"Log written to {log_path}")
        logf.close()


if __name__ == "__main__":
    if os.name != "nt":
        sys.exit("Windows only.")
    main()
