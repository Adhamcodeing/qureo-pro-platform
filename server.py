import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, jsonify, request, send_from_directory, Response, redirect
from solver_engine import SolverEngine
from real_solver_engine import RealQueueManager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR)
real_queue_mgr = RealQueueManager()

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
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None

    if any(sep in line for sep in ("|", ",", ";", "\t")):
        parts = [p.strip() for p in re.split(r"[|,;\t]+", line) if p.strip()]
        tokens = []
        for p in parts:
            sub_tok = _detect_track_token(p)
            if sub_tok or len(parts) >= 2:
                tokens.append(p)
            else:
                tokens.extend(p.split())
    else:
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
            password = remaining[code_idx - 1]
            label_parts = [remaining[j] for j in range(len(remaining)) if j not in (code_idx, code_idx - 1)]
    else:
        if len(remaining) == 2:
            username, password = remaining[0], remaining[1]
        else:
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


@app.route("/real-solver")
def real_solver_redirect():
    return redirect("/")


@app.route("/api/subjects", methods=["GET"])
def get_subjects():
    return jsonify({"subjects": SolverEngine.SUBJECT_LABELS})


@app.route("/api/queue", methods=["GET"])
def queue_alias():
    return jsonify(real_queue_mgr.get_snapshot())


@app.route("/api/queue/parse", methods=["POST"])
def parse_bulk_preview():
    data = request.get_json(silent=True) or {}
    raw_text = data.get("raw_text") or ""
    default_subject = data.get("subject", "auto_js")
    items = _parse_bulk_lines(raw_text, default_subject=default_subject)
    return jsonify({"ok": True, "items": items, "count": len(items)})


@app.route("/api/real-queue", methods=["GET"])
def real_queue_list():
    return jsonify(real_queue_mgr.get_snapshot())


@app.route("/api/real-queue/add", methods=["POST"])
def real_queue_add():
    data = request.get_json(silent=True) or {}
    username = _normalize_digits((data.get("username") or "").strip())
    password = (data.get("password") or "").strip()
    label = (data.get("label") or "").strip()
    subject = data.get("subject", "auto_js")
    headless = bool(data.get("headless", True))
    mode = data.get("mode", "real_full")
    target_chapter = _opt_int(data.get("target_chapter"))
    chapter_from = _opt_int(data.get("chapter_from"))
    chapter_to = _opt_int(data.get("chapter_to"))
    natural_mode = bool(data.get("natural_mode", False))
    realistic_delay = bool(data.get("realistic_delay", False))

    if not username or not password:
        return jsonify({"ok": False, "error": "يرجى إدخال كود الطالب وكلمة المرور."}), 400

    job_summary = real_queue_mgr.add_job(
        username=username,
        password=password,
        label=label,
        subject=subject,
        headless=headless,
        mode=mode,
        target_chapter=target_chapter,
        chapter_from=chapter_from,
        chapter_to=chapter_to,
        natural_mode=natural_mode,
        realistic_delay=realistic_delay,
    )
    return jsonify({"ok": True, "message": f"تمت إضافة {job_summary['display_name']} إلى الطابور.", "job": job_summary})


@app.route("/api/real-queue/bulk", methods=["POST"])
def real_queue_bulk():
    data = request.get_json(silent=True) or {}
    subject = data.get("subject", "auto_js")
    headless = bool(data.get("headless", True))
    mode = data.get("mode", "real_full")
    natural_mode = bool(data.get("natural_mode", False))
    realistic_delay = bool(data.get("realistic_delay", False))

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
                "natural_mode": entry.get("natural_mode", natural_mode),
                "realistic_delay": entry.get("realistic_delay", realistic_delay),
            })
    else:
        raw_text = data.get("raw_text") or ""
        items = _parse_bulk_lines(raw_text, default_subject=subject)

    if not items:
        return jsonify({"ok": False, "error": "لم يتم العثور على طلاب صالحين."}), 400

    added = real_queue_mgr.add_bulk(
        items,
        default_subject=subject,
        default_headless=headless,
        default_mode=mode,
        default_natural_mode=natural_mode,
        default_realistic_delay=realistic_delay,
    )
    return jsonify({"ok": True, "count": len(added), "message": f"تمت إضافة {len(added)} طالب إلى الطابور بنجاح.", "jobs": added})


@app.route("/api/real-queue/logs", methods=["GET"])
def real_queue_logs():
    job_id = request.args.get("job_id")
    since = int(request.args.get("since", 0))
    if not job_id:
        return jsonify({"logs": [], "state": "idle", "total_logs": 0})
    res = real_queue_mgr.get_job_logs(job_id, since=since)
    if not res:
        return jsonify({"ok": False, "error": "الطلب غير موجود"}), 404
    job = real_queue_mgr.get_job(job_id)
    res["job"] = job.to_summary() if job else None
    return jsonify(res)


@app.route("/api/real-queue/<job_id>", methods=["DELETE"])
def real_queue_delete(job_id):
    ok, msg = real_queue_mgr.remove_job(job_id)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 404)


@app.route("/api/real-queue/stop", methods=["POST"])
def real_queue_stop():
    real_queue_mgr.stop_all()
    return jsonify({"ok": True, "message": "تم إرسال إشارة الإيقاف للطابور."})


@app.route("/api/real-queue/clear", methods=["POST"])
def real_queue_clear():
    real_queue_mgr.clear_finished()
    return jsonify({"ok": True, "message": "تم مسح المهام المنتهية."})


@app.route("/api/real-queue/retry-failed", methods=["POST"])
def real_queue_retry_failed():
    count = real_queue_mgr.retry_failed()
    return jsonify({"ok": True, "count": count, "message": f"تمت إعادة {count} مهمة إلى الطابور."})


@app.route("/api/real-queue/<job_id>/screenshot", methods=["GET"])
def real_queue_screenshot(job_id):
    job = real_queue_mgr.get_job(job_id)
    if job and job.engine.screenshot_bytes:
        return Response(job.engine.screenshot_bytes, mimetype="image/png")
    return "", 204


@app.route("/api/real-queue/<job_id>/proof", methods=["POST"])
def real_queue_proof(job_id):
    job = real_queue_mgr.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "الطلب غير موجود"}), 404
    data = request.get_json(silent=True) or {}
    force = bool(data.get("force", False))
    if not force and (job.engine.proof_course_bytes or job.engine.proof_section_bytes):
        return jsonify({
            "ok": True, "cached": True, "stats": job.engine.proof_stats,
            "has_course": bool(job.engine.proof_course_bytes), "has_section": bool(job.engine.proof_section_bytes),
        })
    result = SolverEngine.capture_qureo_proof(job.username, job.password, subject=job.subject)
    if not result.get("ok"):
        return jsonify({"ok": False, "error": result.get("error", "تعذر جلب إثبات الحل")}), 400
    job.engine.proof_course_bytes = result.get("course_bytes")
    job.engine.proof_section_bytes = result.get("section_bytes")
    job.engine.proof_stats = result.get("stats")
    return jsonify({
        "ok": True, "cached": False, "stats": job.engine.proof_stats,
        "has_course": bool(job.engine.proof_course_bytes), "has_section": bool(job.engine.proof_section_bytes),
    })


@app.route("/api/real-queue/<job_id>/proof/image/<kind>", methods=["GET"])
def real_queue_proof_image(job_id, kind):
    job = real_queue_mgr.get_job(job_id)
    if not job:
        return "", 404
    img = job.engine.proof_course_bytes if kind == "course" else job.engine.proof_section_bytes
    if not img:
        return "", 204
    headers = {}
    if request.args.get("download") == "1":
        headers["Content-Disposition"] = f'attachment; filename="qureo-real-proof-{job.username}-{kind}.png"'
    return Response(img, mimetype="image/png", headers=headers)


@app.route("/api/real-queue/<job_id>/open-browser", methods=["POST"])
def real_queue_open_browser(job_id):
    job = real_queue_mgr.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "الطلب غير موجود"}), 404
    ok, msg = SolverEngine.open_live_qureo_browser(job.username, job.password, subject=job.subject)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Qureo Pro Real Platform Server Running at http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
