"""
Shared config for DeskGuard: both deskguard.py (the recorder) and
dashboard.py (the review UI) read/write the same config.json, so changing
a setting in the dashboard takes effect on the next recording without
editing code.
"""

import json
import os
import sys

if getattr(sys, "frozen", False):
    # PyInstaller one-file builds unpack modules into a temporary directory;
    # runtime data must live beside the executable instead.
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
CLIPS_DIR = os.path.join(RECORDINGS_DIR, "clips")
VIDEO_DIR = os.path.join(CLIPS_DIR, "videos")
METADATA_DIR = os.path.join(CLIPS_DIR, "metadata")
SNAPSHOTS_DIR = os.path.join(CLIPS_DIR, "snapshots")
THUMBNAILS_DIR = os.path.join(CLIPS_DIR, "thumbnails")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "deskguard_events.log")

DEFAULTS = {
    "lock_mode": "native",
    "hotkey_modifiers": "ctrl+alt",
    "hotkey_key": "L",
    "unlock_code": "1234",
    "dashboard_password": "227842",
    "camera_index": 0,
    "resolution": [640, 480],       # [width, height]
    "fps": 8,
    "codec": "mp4v",
    "max_total_storage_gb": 5,
    "per_clip_safety_gb": 4,
    "detect_person": True,
    "detect_motion": True,
    "person_check_interval_sec": 2,
    "person_confidence_threshold": 0.5,
    "motion_threshold": 25,          # pixel intensity diff threshold
    "motion_min_area": 500,          # min contour area (px) to count as motion
    "motion_log_cooldown_sec": 5,    # don't log motion more than once per N sec
    "keep_camera_open": True,        # native mode compatibility; hotkey mode is on-demand
    "block_input": True,             # mouse/escape-combo lock during virtual lock
    "segment_seconds": 15,           # rotate to a new clip file every N seconds,
                                      # so killing the process mid-lock loses at
                                      # most the current segment, not the whole session
    "heartbeat_interval_sec": 2,     # how often deskguard.py refreshes heartbeat.json
    "watchdog_timeout_sec": 6,       # watchdog.py's stale/dead threshold
}

RESOLUTION_PRESETS = [
    [320, 240],
    [640, 480],
    [960, 720],
    [1280, 720],
]


def load_config():
    """Read config.json, filling in any missing keys with defaults."""
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                on_disk = json.load(f)
            cfg.update(on_disk)
        except (json.JSONDecodeError, OSError):
            pass  # fall back to defaults if the file is corrupt/unreadable
    else:
        save_config(cfg)
    return cfg


def save_config(cfg):
    os.makedirs(BASE_DIR, exist_ok=True)
    tmp_path = CONFIG_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp_path, CONFIG_PATH)  # atomic write, avoids a half-written file being read
