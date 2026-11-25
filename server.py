import os
import re
from flask import Flask, jsonify, request, send_from_directory, Response
from solver_engine import SolverEngine
from queue_manager import QueueManager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR)
queue_mgr = QueueManager()

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

_TRACK_KEYWORDS = {
    "python2": {"python", "python2", "py", "بايثون", "بيثون", "بثون", "بايسون"},
    "java1": {"java1", "js1", "1ث", "اولى", "أولى", "اولي", "أولي", "42"},
    "java2": {"java2", "js2", "2ث", "تانية", "ثانية", "تاني", "ثاني", "54"},
    "auto_js": {"auto", "auto_js", "تلقائي", "ذكي", "جافا", "java", "js"},
}


def _opt_int(val):
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _normalize_digits(text):
    return (text or "").translate(_ARABIC_DIGITS)


def _detect_track_token(tok):
    low = tok.strip().lower().strip("()[]{}.,-")
    for subj, words in _TRACK_KEYWORDS.items():
        if low in words:
            return subj
    return None


def _parse_single_line(raw_line, default_subject="auto_js"):
    """Forgiving parser for WhatsApp/Excel/text student rows.

    Supports any order and separators, e.g.:
      أحمد | 475441535 | 123456
      470819199 Xfi7?T3h يوسف بايثون
      سارة محمد\t477920943\tD?mcpAw6
      475441535:123456
    """
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None

    # Split on structured delimiters first if present, otherwise whitespace
    if any(sep in line for sep in ("|", ",", ";", "\t")):
        parts = [p.strip() for p in re.split(r"[|,;\t]+", line) if p.strip()]
        # If delimiter split gave <= 2 chunks and one has spaces, flatten words when needed
        tokens = []
        for p in parts:
            sub_tok = _detect_track_token(p)
            if sub_tok:
                tokens.append(p)
            elif len(parts) >= 2:
                tokens.append(p)
            else:
                tokens.extend(p.split())
    else:
        # Handle simple user:pass format with no spaces
        if ":" in line and " " not in line and line.count(":") == 1:
            tokens = [t.strip() for t in line.split(":", 1) if t.strip()]
        else:
            tokens = [t.strip() for t in line.split() if t.strip()]

    if not tokens:
        return None

    detected_subject = None
    remaining = []
    for tok in tokens:
        matched_subj = _detect_track_token(tok)
        if matched_subj and detected_subject is None:
            detected_subject = matched_subj
        else:
            remaining.append(tok)

    if len(remaining) < 2:
        return None

    # Identify purely numeric student code token (4..15 digits after Arabic digit normalization)
    code_idx = None
    for i, tok in enumerate(remaining):
        norm = _normalize_digits(tok)
        if re.fullmatch(r"\d{4,15}", norm):
            code_idx = i
            break

    username = ""
    password = ""
    label_parts = []

    if code_idx is not None:
        username = _normalize_digits(remaining[code_idx])
        if code_idx + 1 < len(remaining):
            password = remaining[code_idx + 1]
            label_parts = [remaining[j] for j in range(len(remaining)) if j not in (code_idx, code_idx + 1)]
        else:
            # Code was at the end, password is likely the preceding token
            password = remaining[code_idx - 1]
            label_parts = [remaining[j] for j in range(len(remaining)) if j not in (code_idx, code_idx - 1)]
    else:
        # No purely numeric code found; use positional heuristic
        if len(remaining) == 2:
            username, password = remaining[0], remaining[1]
        else:
            # If first token looks non-ASCII (e.g. Arabic name), treat as label
            if any(ord(ch) > 127 for ch in remaining[0]):
                label_parts = [remaining[0]]
                username = remaining[1]
                password = remaining[2]
            else:
                username = remaining[0]
                password = remaining[1]
                label_parts = remaining[2:]

    if not username or not password:
        return None

    return {
        "label": " ".join(label_parts).strip(),
        "username": username.strip(),
        "password": password.strip(),
        "subject": detected_subject or default_subject,
    }


def _parse_bulk_lines(raw_text, default_subject="auto_js"):
    items = []
    for line in (raw_text or "").splitlines():
        parsed = _parse_single_line(line, default_subject=default_subject)
        if parsed:
            items.append(parsed)
    return items


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/subjects", methods=["GET"])
def get_subjects():
    return jsonify({"subjects": SolverEngine.SUBJECT_LABELS})


# ---------------------------------------------------------
# Legacy Single-Session Endpoints (Backward Compatible)
# ---------------------------------------------------------
@app.route("/api/solve/start", methods=["POST"])
def start_solve():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    label = (data.get("label") or "").strip()
    subject = data.get("subject", "auto_js")
    headless = bool(data.get("headless", True))
    mode = data.get("mode", "full")
    target_chapter = _opt_int(data.get("target_chapter"))
    chapter_from = _opt_int(data.get("chapter_from"))
    chapter_to = _opt_int(data.get("chapter_to"))

    if not username or not password:
        return jsonify({"ok": False, "error": "يرجى إدخال كود الطالب وكلمة المرور."}), 400

    job = queue_mgr.add_job(
        username=username,
        password=password,
        label=label,
        subject=subject,
        headless=headless,
        mode=mode,
        target_chapter=target_chapter,
        chapter_from=chapter_from,
        chapter_to=chapter_to,
    )
    return jsonify({
        "ok": True,
        "message": f"تمت إضافة {job.display_name()} إلى الطابور.",
        "job": job.to_summary(),
    })


@app.route("/api/solve/status", methods=["GET"])
def solve_status():
    since = int(request.args.get("since", 0))
    return jsonify(queue_mgr.get_legacy_status(since=since))


@app.route("/api/solve/stop", methods=["POST"])
def stop_solve():
    ok, msg = queue_mgr.stop_all()
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/screenshot", methods=["GET"])
def get_screenshot():
    img = queue_mgr.get_legacy_screenshot()
    if img:
        return Response(img, mimetype="image/png")
    return "", 204


# ---------------------------------------------------------
# Sequential Queue API Endpoints
# ---------------------------------------------------------
@app.route("/api/queue", methods=["GET"])
def get_queue():
    return jsonify(queue_mgr.get_snapshot())


@app.route("/api/queue/parse", methods=["POST"])
def parse_bulk_preview():
    data = request.get_json(silent=True) or {}
    raw_text = data.get("raw_text") or ""
    default_subject = data.get("subject", "auto_js")
    items = _parse_bulk_lines(raw_text, default_subject=default_subject)
    return jsonify({"ok": True, "items": items, "count": len(items)})


@app.route("/api/queue/add", methods=["POST"])
def queue_add_single():
    data = request.get_json(silent=True) or {}
    username = _normalize_digits((data.get("username") or "").strip())
    password = (data.get("password") or "").strip()
    label = (data.get("label") or "").strip()
    subject = data.get("subject", "auto_js")
    headless = bool(data.get("headless", True))
    mode = data.get("mode", "full")
    target_chapter = _opt_int(data.get("target_chapter"))
    chapter_from = _opt_int(data.get("chapter_from"))
    chapter_to = _opt_int(data.get("chapter_to"))

    if not username or not password:
        return jsonify({"ok": False, "error": "يرجى إدخال كود الطالب وكلمة المرور."}), 400

    job = queue_mgr.add_job(
        username=username,
        password=password,
        label=label,
        subject=subject,
        headless=headless,
        mode=mode,
        target_chapter=target_chapter,
        chapter_from=chapter_from,
        chapter_to=chapter_to,
    )
    return jsonify({
        "ok": True,
        "message": f"تمت إضافة {job.display_name()} إلى الطابور.",
        "job": job.to_summary(),
    })


@app.route("/api/queue/bulk", methods=["POST"])
def queue_add_bulk():
    data = request.get_json(silent=True) or {}
    subject = data.get("subject", "auto_js")
    headless = bool(data.get("headless", True))
    mode = data.get("mode", "full")
    target_chapter = _opt_int(data.get("target_chapter"))
    chapter_from = _opt_int(data.get("chapter_from"))
    chapter_to = _opt_int(data.get("chapter_to"))

    items = []
    raw_items = data.get("items")
    if isinstance(raw_items, list):
        for entry in raw_items:
            if not isinstance(entry, dict):
                continue
            u = _normalize_digits((entry.get("username") or "").strip())
            p = (entry.get("password") or "").strip()
            if not u or not p:
                continue
            items.append({
                "label": (entry.get("label") or "").strip(),
                "username": u,
                "password": p,
                "subject": entry.get("subject") or subject,
                "mode": entry.get("mode") or mode,
                "target_chapter": _opt_int(entry.get("target_chapter")),
                "chapter_from": _opt_int(entry.get("chapter_from")),
                "chapter_to": _opt_int(entry.get("chapter_to")),
            })
    else:
        raw_text = data.get("raw_text") or ""
        items = _parse_bulk_lines(raw_text, default_subject=subject)

    if not items:
        return jsonify({
            "ok": False,
            "error": "لم يتم العثور على طلاب صالحين. تأكد من إدخال كود الطالب وكلمة المرور في كل صف.",
        }), 400

    jobs = queue_mgr.add_bulk(
        items,
        subject=subject,
        headless=headless,
        mode=mode,
        target_chapter=target_chapter,
        chapter_from=chapter_from,
        chapter_to=chapter_to,
    )
    return jsonify({
        "ok": True,
        "added_count": len(jobs),
        "jobs": [j.to_summary() for j in jobs],
        "message": f"تمت إضافة {len(jobs)} طلاب إلى الطابور بنجاح.",
    })


@app.route("/api/queue/<job_id>", methods=["DELETE"])
def queue_remove(job_id):
    ok, msg = queue_mgr.remove_job(job_id)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)


@app.route("/api/queue/<job_id>/move", methods=["POST"])
def queue_move(job_id):
    data = request.get_json(silent=True) or {}
    direction = data.get("direction", "top")
    ok, msg = queue_mgr.move_job(job_id, direction=direction)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)


@app.route("/api/queue/<job_id>/retry", methods=["POST"])
def queue_retry(job_id):
    ok, msg = queue_mgr.retry_job(job_id)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)


@app.route("/api/queue/clear", methods=["POST"])
def queue_clear():
    ok, msg = queue_mgr.clear_finished()
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/queue/skip", methods=["POST"])
def queue_skip_current():
    ok, msg = queue_mgr.stop_current_only()
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)


@app.route("/api/queue/stop", methods=["POST"])
def queue_stop_all():
    ok, msg = queue_mgr.stop_all()
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/queue/logs", methods=["GET"])
def queue_logs():
    job_id = request.args.get("job_id")
    since = int(request.args.get("since", 0))
    if job_id:
        job = queue_mgr.get_job(job_id)
        if not job:
            return jsonify({"ok": False, "error": "الطلب غير موجود"}), 404
        status = job.engine.get_status(since=since)
        status["job"] = job.to_summary()
        return jsonify(status)
    return jsonify(queue_mgr.get_legacy_status(since=since))


@app.route("/api/queue/<job_id>/screenshot", methods=["GET"])
def queue_job_screenshot(job_id):
    job = queue_mgr.get_job(job_id)
    if job and job.engine.screenshot_bytes:
        return Response(job.engine.screenshot_bytes, mimetype="image/png")
    return "", 204


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Qureo Pro Platform Server Running at http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
