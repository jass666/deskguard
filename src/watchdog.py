"""
watchdog.py - DeskGuard's answer to "what if someone kills the process".

Nothing running in the same process as deskguard.py can survive that
process being killed (Ctrl+Alt+Del -> Task Manager -> End Task escapes
input_lock.py by design - see that file's docstring for why that specific
gap cannot be closed). So this runs as a SEPARATE process, watching
deskguard.py from the outside.

How it works
------------
While a virtual lock (or native lock) is active, deskguard.py writes
logs/heartbeat.json every `heartbeat_interval_sec` seconds:

    {"pid": 12345, "ts": "2026-09-16T18:24:51.123456", "locked": true}

This process polls that file. If the heartbeat goes stale (older than
`watchdog_timeout_sec`) OR the recorded pid has actually exited, WHILE
`locked` was true the last time we saw a live heartbeat, it calls the
real Windows LockWorkStation() API immediately - the same lock you get
from Win+L. That's the actual OS secure-desktop lock, requiring the
real Windows password, not bypassable via Task Manager the way the
virtual overlay is.

By that point in the timeline: the overlay had already been up, mouse
dead, camera rolling, for however long it took someone to notice the
lock, find Ctrl+Alt+Del, open Task Manager, and end the process -
typically several seconds. The recording from that window is what
identifies them; the fallback native lock is what stops the situation
from just continuing as if nothing happened.

This is intentionally a separate, small, dependency-light script so it
has as little as possible in common with deskguard.py to fail alongside
it. Run it as its own Task Scheduler entry ("run at logon", same as the
recorder) so it's a genuinely separate process tree.

Note this is one-directional: this watches deskguard.py, not the other
way around. If you also want deskguard.py to notice *this* process
dying and restart it, that's a natural follow-up but isn't included
here - flag it if you want it added.
"""

import ctypes
from ctypes import wintypes
import datetime
import json
import logging
import os
import time

from deskguard_config import load_config, LOGS_DIR

HEARTBEAT_PATH = os.path.join(LOGS_DIR, "heartbeat.json")
WATCHDOG_LOG = os.path.join(LOGS_DIR, "watchdog_events.log")

os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    filename=WATCHDOG_LOG,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def log(msg):
    print(msg)
    logging.info(msg)


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                        ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.LockWorkStation.restype = wintypes.BOOL


def pid_is_alive(pid):
    """True if a process with this pid exists and hasn't exited.

    Uses raw kernel32 calls instead of psutil/pywin32 so this script's
    only dependency is the Python standard library plus ctypes - fewer
    ways for it to fail to start in the first place.
    """
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
    )
    if not handle:
        return False
    try:
        exit_code = ctypes.wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def read_heartbeat():
    try:
        with open(HEARTBEAT_PATH, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def trigger_fallback_lock(reason):
    log(f"INCIDENT: {reason} while a lock was active. "
        f"Triggering real Windows lock (LockWorkStation).")
    ok = user32.LockWorkStation()
    if not ok:
        err = ctypes.get_last_error()
        log(f"ERROR: LockWorkStation() failed (WinError {err}). "
            f"The machine is UNPROTECTED right now - check manually.")
    else:
        log("Real Windows lock engaged.")


def main():
    if os.name != "nt":
        raise SystemExit("watchdog.py only runs on Windows.")

    cfg = load_config()
    timeout = float(cfg.get("watchdog_timeout_sec", 6))
    poll_every = max(1.0, timeout / 3.0)

    log(f"Watchdog started. Polling {HEARTBEAT_PATH} every {poll_every:.1f}s, "
        f"stale/dead threshold {timeout:.1f}s.")

    already_handled_pid = None  # avoid re-triggering for the same dead pid

    while True:
        hb = read_heartbeat()

        if hb is None:
            time.sleep(poll_every)
            continue

        pid = hb.get("pid")
        locked = bool(hb.get("locked"))
        ts_raw = hb.get("ts")

        try:
            ts = datetime.datetime.fromisoformat(ts_raw)
            age = (datetime.datetime.now() - ts).total_seconds()
        except (TypeError, ValueError):
            age = float("inf")

        stale = age > timeout
        alive = pid_is_alive(pid) if pid else False

        if locked and (stale or not alive) and pid != already_handled_pid:
            reason = "recorder process appears to have exited" if not alive \
                else f"heartbeat went stale ({age:.1f}s old)"
            trigger_fallback_lock(reason)
            already_handled_pid = pid
        elif alive and not stale:
            already_handled_pid = None  # recorder is healthy again, reset

        time.sleep(poll_every)


if __name__ == "__main__":
    main()
