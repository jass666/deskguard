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

When the recorder is dead or its heartbeat is stale, this process also
restarts it automatically. If the stale heartbeat belongs to a still-live
but hung recorder, the exact heartbeat pid is terminated first. Restarting is
rate-limited so a broken installation cannot create a process storm.
"""

import ctypes
from ctypes import wintypes
import datetime
import json
import logging
import os
import subprocess
import sys
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
PROCESS_TERMINATE = 0x0001
STILL_ACTIVE = 259

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                        ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateProcess.restype = wintypes.BOOL
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


def terminate_pid(pid):
    """Terminate only the process named by the recorder heartbeat."""
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)


def recorder_command():
    """Return the same recorder command family used by this installation."""
    if getattr(sys, "frozen", False):
        root = os.path.dirname(sys.executable)
        return [os.path.join(root, "DeskGuardRecorder.exe")], root
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    recorder = os.path.join(root, "src", "deskguard.py")
    return [sys.executable, recorder], root


def restart_recorder(previous_pid, stale):
    """Replace a dead/hung recorder without creating duplicate instances."""
    if stale and previous_pid and pid_is_alive(previous_pid):
        if terminate_pid(previous_pid):
            log(f"Auto-recovery: terminated hung recorder pid {previous_pid}.")
        else:
            log(f"WARNING: auto-recovery could not terminate recorder pid {previous_pid}.")
            return False

    command, cwd = recorder_command()
    try:
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(command, cwd=cwd, close_fds=True,
                         creationflags=creationflags)
        log("Auto-recovery: recorder relaunched.")
        return True
    except OSError as e:
        log(f"ERROR: auto-recovery could not relaunch recorder: {e}")
        return False


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
    last_restart_at = 0.0
    restart_cooldown = max(15.0, float(cfg.get("watchdog_restart_cooldown_sec", 30)))

    while True:
        hb = read_heartbeat()

        if hb is None:
            now = time.time()
            if now - last_restart_at >= restart_cooldown:
                if restart_recorder(None, False):
                    last_restart_at = now
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

        unhealthy = stale or not alive
        if unhealthy:
            reason = "recorder process appears to have exited" if not alive \
                else f"heartbeat went stale ({age:.1f}s old)"
            if locked and pid != already_handled_pid:
                trigger_fallback_lock(reason)
                already_handled_pid = pid
            now = time.time()
            if now - last_restart_at >= restart_cooldown:
                if restart_recorder(pid, stale):
                    last_restart_at = now
        elif alive and not stale:
            already_handled_pid = None  # recorder is healthy again, reset

        time.sleep(poll_every)


if __name__ == "__main__":
    main()
