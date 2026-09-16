"""
DeskGuard Dashboard - a local web UI to browse recordings, filter by
motion/person detection, play clips, delete old ones, and change recording
settings (resolution, fps, detection sensitivity, storage caps).

This binds to 127.0.0.1 only - it is not reachable from other machines,
by design, since it serves footage from around your desk.

Requires:
    pip install -r requirements.txt

Run (separately from deskguard.py - they run side by side):
    python dashboard.py
Then open http://127.0.0.1:5151 in a browser.
"""

import os
import json
import datetime

import cv2
from flask import Flask, request, redirect, url_for, send_from_directory, abort, Response

from deskguard_config import load_config, save_config, RECORDINGS_DIR, RESOLUTION_PRESETS

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
def list_recordings(tag_filter="all"):
    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    items = []
    for fname in os.listdir(RECORDINGS_DIR):
        if not fname.endswith(".mp4"):
            continue
        path = os.path.join(RECORDINGS_DIR, fname)
        meta_path = os.path.join(RECORDINGS_DIR, fname[:-4] + ".json")

        meta = None
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
            except (json.JSONDecodeError, OSError):
                meta = None

        stat = os.stat(path)
        if meta:
            start = meta.get("start")
            end = meta.get("end")
            person_events = meta.get("person_events", [])
            motion_events = meta.get("motion_events", [])
            size_bytes = meta.get("size_bytes", stat.st_size)
        else:
            # legacy clip recorded before metadata sidecars existed
            start = datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()
            end = None
            person_events = []
            motion_events = []
            size_bytes = stat.st_size

        duration_sec = None
        if start and end:
            try:
                duration_sec = (
                    datetime.datetime.fromisoformat(end) - datetime.datetime.fromisoformat(start)
                ).total_seconds()
            except ValueError:
                duration_sec = None

        has_person = len(person_events) > 0
        has_motion = len(motion_events) > 0

        if tag_filter == "person" and not has_person:
            continue
        if tag_filter == "motion" and not (has_motion and not has_person):
            continue
        if tag_filter == "clean" and (has_person or has_motion):
            continue

        items.append({
            "file": fname,
            "start": start,
            "duration_sec": duration_sec,
            "size_mb": size_bytes / (1024 * 1024),
            "has_person": has_person,
            "has_motion": has_motion,
            "person_count": len(person_events),
            "motion_count": len(motion_events),
            "mtime": stat.st_mtime,
        })

    items.sort(key=lambda i: i["mtime"], reverse=True)
    return items


def folder_size_gb():
    total = 0
    for fname in os.listdir(RECORDINGS_DIR):
        if fname.endswith(".mp4"):
            total += os.path.getsize(os.path.join(RECORDINGS_DIR, fname))
    return total / (1024 ** 3)


def thumbnail_path(fname):
    return os.path.join(RECORDINGS_DIR, fname[:-4] + ".thumb.jpg")


def ensure_thumbnail(fname):
    thumb_path = thumbnail_path(fname)
    if os.path.exists(thumb_path):
        return thumb_path
    video_path = os.path.join(RECORDINGS_DIR, fname)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_count // 2))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    cv2.imwrite(thumb_path, frame)
    return thumb_path


def fmt_duration(sec):
    if sec is None:
        return "—"
    sec = int(sec)
    m, s = divmod(sec, 60)
    return f"{m}:{s:02d}"


def fmt_time(iso_str):
    if not iso_str:
        return "—"
    try:
        dt = datetime.datetime.fromisoformat(iso_str)
        return dt.strftime("%d %b, %H:%M:%S")
    except ValueError:
        return iso_str


# ---------------------------------------------------------------------------
# Shared layout
# ---------------------------------------------------------------------------
BASE_CSS = """
:root {
  --bg: #14171a;
  --panel: #1c2024;
  --border: #2a2f35;
  --text: #e8e6e1;
  --muted: #8b9198;
  --amber: #ffb000;
  --person: #e85d4a;
  --motion: #4a9ee8;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.5;
}
.shell { display: flex; min-height: 100vh; }
.sidebar {
  width: 220px;
  flex-shrink: 0;
  background: var(--panel);
  border-right: 1px solid var(--border);
  padding: 24px 18px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}
.brand {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text);
}
.brand span { color: var(--amber); }
.nav-group { display: flex; flex-direction: column; gap: 2px; }
.nav-label { font-size: 12px; color: var(--muted); margin-bottom: 6px; }
.nav-link {
  display: block;
  padding: 7px 10px;
  border-radius: 4px;
  color: var(--muted);
  text-decoration: none;
  font-size: 14px;
  border-left: 2px solid transparent;
}
.nav-link:hover { color: var(--text); }
.nav-link.active {
  color: var(--text);
  background: rgba(255, 176, 0, 0.08);
  border-left: 2px solid var(--amber);
}
.storage-box { margin-top: auto; font-size: 12px; color: var(--muted); }
.storage-bar {
  height: 4px;
  background: #2a2f35;
  border-radius: 2px;
  margin-top: 6px;
  overflow: hidden;
}
.storage-fill { height: 100%; background: var(--amber); }
.main { flex: 1; padding: 32px 40px; max-width: 980px; }
h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px 0; }
.subtitle { color: var(--muted); font-size: 14px; margin-bottom: 24px; }
.ledger { border-top: 1px solid var(--border); }
.row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 4px;
  border-bottom: 1px solid var(--border);
}
.thumb {
  width: 96px;
  height: 64px;
  object-fit: cover;
  border-radius: 3px;
  background: #0e1012;
  flex-shrink: 0;
}
.row-main { flex: 1; min-width: 0; }
.row-time { font-size: 14px; }
.row-meta { font-size: 12.5px; color: var(--muted); margin-top: 2px; }
.tags { display: flex; gap: 6px; margin-left: 12px; }
.tag {
  font-size: 11.5px;
  padding: 2px 8px;
  border-radius: 3px;
  white-space: nowrap;
}
.tag-person { background: rgba(232, 93, 74, 0.15); color: var(--person); }
.tag-motion { background: rgba(74, 158, 232, 0.15); color: var(--motion); }
.row-actions { display: flex; gap: 10px; align-items: center; }
a.btn, button.btn {
  font-size: 13px;
  color: var(--muted);
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 5px 10px;
  cursor: pointer;
  text-decoration: none;
  font-family: inherit;
}
a.btn:hover, button.btn:hover { color: var(--text); border-color: var(--muted); }
.player-row { padding: 12px 4px 20px 4px; border-bottom: 1px solid var(--border); }
.player-row video { width: 100%; max-height: 480px; background: #000; border-radius: 4px; }
.filters { display: flex; gap: 6px; margin-bottom: 20px; }
.filter-chip {
  font-size: 13px;
  padding: 6px 12px;
  border-radius: 14px;
  border: 1px solid var(--border);
  color: var(--muted);
  text-decoration: none;
}
.filter-chip.active { color: var(--bg); background: var(--amber); border-color: var(--amber); font-weight: 600; }
.empty { color: var(--muted); padding: 40px 0; text-align: center; }
form.settings { display: flex; flex-direction: column; gap: 20px; max-width: 480px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field label { font-size: 13px; color: var(--muted); }
.field input[type=number], .field select {
  background: var(--panel);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 8px 10px;
  border-radius: 4px;
  font-size: 14px;
  font-family: inherit;
}
.checkbox-field { display: flex; align-items: center; gap: 8px; flex-direction: row; }
.section-label { font-size: 13px; color: var(--amber); margin-top: 8px; letter-spacing: 0.01em; }
.save-btn {
  align-self: flex-start;
  background: var(--amber);
  color: #14171a;
  border: none;
  padding: 9px 18px;
  border-radius: 4px;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  font-family: inherit;
}
.saved-note { color: var(--amber); font-size: 13px; margin-bottom: 16px; }
.hint { color: var(--muted); font-size: 12.5px; margin-top: -2px; }
"""


def layout(active, body_html):
    return f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DeskGuard</title>
<style>{BASE_CSS}</style>
</head><body>
<div class="shell">
  <div class="sidebar">
    <div class="brand">DESK<span>GUARD</span></div>
    <div class="nav-group">
      <div class="nav-label">Recordings</div>
      <a class="nav-link {'active' if active=='all' else ''}" href="/?tag=all">All clips</a>
      <a class="nav-link {'active' if active=='person' else ''}" href="/?tag=person">Person detected</a>
      <a class="nav-link {'active' if active=='motion' else ''}" href="/?tag=motion">Motion only</a>
      <a class="nav-link {'active' if active=='clean' else ''}" href="/?tag=clean">No detections</a>
    </div>
    <div class="nav-group">
      <div class="nav-label">Configure</div>
      <a class="nav-link {'active' if active=='settings' else ''}" href="/settings">Settings</a>
    </div>
    <div class="storage-box">
      {storage_widget()}
    </div>
  </div>
  <div class="main">
    {body_html}
  </div>
</div>
</body></html>"""


def storage_widget():
    cfg = load_config()
    used = folder_size_gb()
    cap = cfg["max_total_storage_gb"]
    pct = min(100, (used / cap) * 100) if cap else 0
    return f"""
    <div>{used:.2f} GB of {cap} GB used</div>
    <div class="storage-bar"><div class="storage-fill" style="width:{pct:.0f}%"></div></div>
    """


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    tag = request.args.get("tag", "all")
    expand = request.args.get("expand")
    recordings = list_recordings(tag)

    if not recordings:
        rows_html = '<div class="empty">No recordings match this filter.</div>'
    else:
        rows = []
        for r in recordings:
            tags_html = ""
            if r["has_person"]:
                tags_html += f'<span class="tag tag-person">Person &times;{r["person_count"]}</span>'
            if r["has_motion"]:
                tags_html += f'<span class="tag tag-motion">Motion &times;{r["motion_count"]}</span>'

            is_open = expand == r["file"]
            toggle_url = "/" + (f'?tag={tag}' if is_open else f'?tag={tag}&expand={r["file"]}')

            rows.append(f"""
            <div class="row">
              <img class="thumb" src="/thumbnail/{r['file']}" loading="lazy">
              <div class="row-main">
                <div class="row-time">{fmt_time(r['start'])}</div>
                <div class="row-meta">{fmt_duration(r['duration_sec'])} &middot; {r['size_mb']:.0f} MB</div>
              </div>
              <div class="tags">{tags_html}</div>
              <div class="row-actions">
                <a class="btn" href="{toggle_url}">{'Close' if is_open else 'Play'}</a>
                <form method="post" action="/delete/{r['file']}" onsubmit="return confirm('Delete this clip?')">
                  <button class="btn" type="submit">Delete</button>
                </form>
              </div>
            </div>
            """)
            if is_open:
                rows.append(f"""
                <div class="player-row">
                  <video controls autoplay src="/video/{r['file']}"></video>
                </div>
                """)
        rows_html = f'<div class="ledger">{"".join(rows)}</div>'

    filters_html = "".join(
        f'<a class="filter-chip {"active" if tag==t else ""}" href="/?tag={t}">{label}</a>'
        for t, label in [("all", "All"), ("person", "Person"), ("motion", "Motion only"), ("clean", "Clean")]
    )

    body = f"""
    <h1>Recordings</h1>
    <div class="subtitle">Clips are grouped by lock/unlock cycle. Click Play to preview inline.</div>
    <div class="filters">{filters_html}</div>
    {rows_html}
    """
    return layout(tag, body)


@app.route("/video/<path:filename>")
def serve_video(filename):
    if not filename.endswith(".mp4") or "/" in filename or "\\" in filename:
        abort(404)
    return send_from_directory(RECORDINGS_DIR, filename, conditional=True)


@app.route("/thumbnail/<path:filename>")
def serve_thumbnail(filename):
    if not filename.endswith(".mp4") or "/" in filename or "\\" in filename:
        abort(404)
    thumb = ensure_thumbnail(filename)
    if not thumb:
        abort(404)
    return send_from_directory(RECORDINGS_DIR, os.path.basename(thumb), conditional=True)


@app.route("/delete/<path:filename>", methods=["POST"])
def delete_recording(filename):
    if not filename.endswith(".mp4") or "/" in filename or "\\" in filename:
        abort(404)
    base = filename[:-4]
    for ext in (".mp4", ".json", ".thumb.jpg"):
        p = os.path.join(RECORDINGS_DIR, base + ext)
        if os.path.exists(p):
            os.remove(p)
    return redirect(url_for("index", tag=request.args.get("tag", "all")))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    cfg = load_config()
    saved = False

    if request.method == "POST":
        w, h = request.form["resolution"].split("x")
        cfg["resolution"] = [int(w), int(h)]
        cfg["camera_index"] = int(request.form["camera_index"])
        cfg["fps"] = int(request.form["fps"])
        cfg["max_total_storage_gb"] = float(request.form["max_total_storage_gb"])
        cfg["per_clip_safety_gb"] = float(request.form["per_clip_safety_gb"])
        cfg["detect_person"] = "detect_person" in request.form
        cfg["detect_motion"] = "detect_motion" in request.form
        cfg["person_confidence_threshold"] = float(request.form["person_confidence_threshold"])
        cfg["motion_min_area"] = int(request.form["motion_min_area"])
        cfg["motion_log_cooldown_sec"] = int(request.form["motion_log_cooldown_sec"])
        save_config(cfg)
        cfg = load_config()
        saved = True

    res_options = "".join(
        f'<option value="{w}x{h}" {"selected" if [w, h] == cfg["resolution"] else ""}>{w} x {h}</option>'
        for w, h in RESOLUTION_PRESETS
    )

    body = f"""
    <h1>Settings</h1>
    <div class="subtitle">Changes apply starting with the next lock/unlock cycle - not the recording in progress.</div>
    {'<div class="saved-note">Settings saved.</div>' if saved else ''}
    <form class="settings" method="post">
      <div class="section-label">Camera</div>
      <div class="field">
        <label>Camera index</label>
        <input type="number" name="camera_index" value="{cfg['camera_index']}" min="0">
        <div class="hint">0 is usually the built-in/default webcam.</div>
      </div>
      <div class="field">
        <label>Resolution</label>
        <select name="resolution">{res_options}</select>
      </div>
      <div class="field">
        <label>Frame rate (fps)</label>
        <input type="number" name="fps" value="{cfg['fps']}" min="1" max="30">
        <div class="hint">Lower fps keeps file sizes down over long locked sessions.</div>
      </div>

      <div class="section-label">Storage</div>
      <div class="field">
        <label>Total storage cap (GB)</label>
        <input type="number" step="0.5" name="max_total_storage_gb" value="{cfg['max_total_storage_gb']}">
        <div class="hint">Oldest clips are deleted automatically once this is exceeded.</div>
      </div>
      <div class="field">
        <label>Per-clip safety stop (GB)</label>
        <input type="number" step="0.5" name="per_clip_safety_gb" value="{cfg['per_clip_safety_gb']}">
      </div>

      <div class="section-label">Detection</div>
      <div class="field checkbox-field">
        <input type="checkbox" name="detect_person" id="detect_person" {"checked" if cfg['detect_person'] else ""}>
        <label for="detect_person">Detect people</label>
      </div>
      <div class="field">
        <label>Person detection sensitivity (0.1 = catches more, 0.9 = fewer false positives)</label>
        <input type="number" step="0.05" min="0.1" max="0.95" name="person_confidence_threshold" value="{cfg['person_confidence_threshold']}">
      </div>
      <div class="field checkbox-field">
        <input type="checkbox" name="detect_motion" id="detect_motion" {"checked" if cfg['detect_motion'] else ""}>
        <label for="detect_motion">Detect motion</label>
      </div>
      <div class="field">
        <label>Motion sensitivity - min area (px, lower = more sensitive)</label>
        <input type="number" name="motion_min_area" value="{cfg['motion_min_area']}">
      </div>
      <div class="field">
        <label>Motion log cooldown (seconds between log entries)</label>
        <input type="number" name="motion_log_cooldown_sec" value="{cfg['motion_log_cooldown_sec']}">
      </div>

      <button class="save-btn" type="submit">Save changes</button>
    </form>
    """
    return layout("settings", body)


if __name__ == "__main__":
    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    app.run(host="127.0.0.1", port=5151, debug=False)
