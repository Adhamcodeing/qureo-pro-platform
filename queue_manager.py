import threading
import datetime
import time
from solver_engine import SolverEngine


class QueueJob:
    """Represents a single student solving job in the sequential FIFO queue."""

    def __init__(self, seq, username, password, label="", subject="auto_js",
                 headless=True, mode="full", target_chapter=None, chapter_from=None, chapter_to=None):
        self.id = f"job_{seq}_{int(time.time() * 1000) % 10000}"
        self.seq = seq
        self.label = (label or "").strip()
        self.username = username.strip()
        self.password = password.strip()
        self.subject = subject
        self.headless = bool(headless)
        self.mode = mode
        self.target_chapter = target_chapter
        self.chapter_from = chapter_from
        self.chapter_to = chapter_to
        self.status = "queued"  # queued | running | done | error | stopped
        self.created_at = datetime.datetime.now().strftime("%H:%M:%S")
        self.engine = SolverEngine()

    def display_name(self):
        return self.label if self.label else self.username

    def to_summary(self):
        st = self.engine.get_status(since=0)
        if self.status == "queued":
            stage = "في انتظار الدور..."
        else:
            stage = st["current_stage"]
        return {
            "id": self.id,
            "seq": self.seq,
            "label": self.label,
            "display_name": self.display_name(),
            "username": self.username,
            "subject": self.subject,
            "subject_label": SolverEngine.SUBJECT_LABELS.get(self.subject, self.subject),
            "mode": self.mode,
            "target_chapter": self.target_chapter,
            "chapter_from": self.chapter_from,
            "chapter_to": self.chapter_to,
            "status": self.status,
            "created_at": self.created_at,
            "current_stage": stage,
            "duration": st["duration"],
            "progress_done": st["progress_done"],
            "progress_total": st["progress_total"],
            "total_logs": st["total_logs"],
            "has_screenshot": st["has_screenshot"],
        }


class QueueManager:
    """Thread-safe sequential FIFO job manager wrapping SolverEngine."""

    def __init__(self):
        self._lock = threading.RLock()
        self._jobs = []
        self._seq_counter = 0
        self._worker_active = False
        self._stop_queue_flag = False
        self._last_active_id = None

    def _ensure_worker_locked(self):
        if not self._worker_active:
            self._worker_active = True
            self._stop_queue_flag = False
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()

    def _next_queued_locked(self):
        for job in self._jobs:
            if job.status == "queued":
                return job
        return None

    def _worker_loop(self):
        while True:
            with self._lock:
                if self._stop_queue_flag:
                    self._worker_active = False
                    return
                job = self._next_queued_locked()
                if not job:
                    self._worker_active = False
                    return
                job.status = "running"
                self._last_active_id = job.id

            try:
                job.engine.run_blocking(
                    job.username,
                    job.password,
                    subject=job.subject,
                    headless=job.headless,
                    mode=job.mode,
                    target_chapter=job.target_chapter,
                    chapter_from=job.chapter_from,
                    chapter_to=job.chapter_to,
                )
            except Exception as e:
                job.engine.state = "error"
                job.engine.log(f"❌ خطأ غير متوقع في العامل: {e}")

            with self._lock:
                final_state = job.engine.state
                if final_state in ("done", "error", "stopped"):
                    job.status = final_state
                else:
                    job.status = "done"

    def add_job(self, username, password, label="", subject="auto_js",
                headless=True, mode="full", target_chapter=None,
                chapter_from=None, chapter_to=None, auto_start=True):
        with self._lock:
            self._seq_counter += 1
            job = QueueJob(
                seq=self._seq_counter,
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
            self._jobs.append(job)
            if auto_start:
                self._ensure_worker_locked()
            return job

    def add_bulk(self, items, subject="auto_js", headless=True, mode="full",
                 target_chapter=None, chapter_from=None, chapter_to=None):
        added = []
        with self._lock:
            for item in items:
                u = (item.get("username") or "").strip()
                p = (item.get("password") or "").strip()
                if not u or not p:
                    continue
                lbl = (item.get("label") or "").strip()
                subj = item.get("subject") or subject
                m = item.get("mode") or mode
                tc = item.get("target_chapter") if item.get("target_chapter") is not None else target_chapter
                cf = item.get("chapter_from") if item.get("chapter_from") is not None else chapter_from
                ct = item.get("chapter_to") if item.get("chapter_to") is not None else chapter_to
                job = self.add_job(
                    u, p, label=lbl, subject=subj, headless=headless,
                    mode=m, target_chapter=tc, chapter_from=cf, chapter_to=ct, auto_start=False
                )
                added.append(job)
            if added:
                self._ensure_worker_locked()
        return added

    def get_job(self, job_id):
        with self._lock:
            for j in self._jobs:
                if j.id == job_id:
                    return j
            return None

    def remove_job(self, job_id):
        with self._lock:
            for i, j in enumerate(self._jobs):
                if j.id == job_id:
                    if j.status == "running":
                        return False, "لا يمكن حذف طالب قيد التشغيل الآن — أوقفه أولاً"
                    self._jobs.pop(i)
                    return True, "تم حذف الطلب من الطابور"
            return False, "الطلب غير موجود"

    def move_job(self, job_id, direction="top"):
        with self._lock:
            queued_indices = [i for i, j in enumerate(self._jobs) if j.status == "queued"]
            target_idx = next((i for i, j in enumerate(self._jobs) if j.id == job_id and j.status == "queued"), None)
            if target_idx is None:
                return False, "الطلب ليس في قائمة الانتظار"

            q_pos = queued_indices.index(target_idx)
            if direction == "top" and q_pos > 0:
                first_idx = queued_indices[0]
                job = self._jobs.pop(target_idx)
                self._jobs.insert(first_idx, job)
            elif direction == "up" and q_pos > 0:
                prev_idx = queued_indices[q_pos - 1]
                self._jobs[target_idx], self._jobs[prev_idx] = self._jobs[prev_idx], self._jobs[target_idx]
            elif direction == "down" and q_pos < len(queued_indices) - 1:
                next_idx = queued_indices[q_pos + 1]
                self._jobs[target_idx], self._jobs[next_idx] = self._jobs[next_idx], self._jobs[target_idx]
            return True, "تم تحديث ترتيب الطابور"

    def retry_job(self, job_id):
        with self._lock:
            job = self.get_job(job_id)
            if not job:
                return False, "الطلب غير موجود"
            if job.status == "running":
                return False, "الطلب يعمل بالفعل"
            job.engine = SolverEngine()
            job.status = "queued"
            self._ensure_worker_locked()
            return True, "تمت إعادة الطلب للطابور"

    def clear_finished(self):
        with self._lock:
            self._jobs = [j for j in self._jobs if j.status in ("queued", "running")]
            return True, "تم مسح السجل المنتهي"

    def stop_current_only(self):
        with self._lock:
            running = next((j for j in self._jobs if j.status == "running"), None)
            if not running:
                return False, "لا يوجد طلب قيد التشغيل"
            running.engine.stop()
            return True, f"جاري إيقاف {running.display_name()} والانتقال للتالي..."

    def stop_all(self):
        with self._lock:
            self._stop_queue_flag = True
            stopped_any = False
            for j in self._jobs:
                if j.status == "running":
                    j.engine.stop()
                    stopped_any = True
                elif j.status == "queued":
                    j.status = "stopped"
                    j.engine.state = "stopped"
                    j.engine.current_stage = "تم إلغاء الطابور"
                    stopped_any = True
            return stopped_any, "تم طلب إيقاف الطابور بالكامل" if stopped_any else "لا توجد مهام نشطة"

    def get_snapshot(self):
        with self._lock:
            active = None
            queued = []
            finished = []
            for j in self._jobs:
                s = j.to_summary()
                if j.status == "running":
                    active = s
                elif j.status == "queued":
                    queued.append(s)
                else:
                    finished.append(s)
            finished.reverse()  # newest finished first

            default_view_id = None
            if active:
                default_view_id = active["id"]
            elif self._last_active_id and any(j.id == self._last_active_id for j in self._jobs):
                default_view_id = self._last_active_id
            elif self._jobs:
                default_view_id = self._jobs[-1].id

            return {
                "worker_active": self._worker_active,
                "active": active,
                "queued": queued,
                "finished": finished,
                "counts": {
                    "running": 1 if active else 0,
                    "queued": len(queued),
                    "finished": len(finished),
                },
                "default_view_id": default_view_id,
            }

    def get_legacy_status(self, since=0):
        """Backward compatibility for GET /api/solve/status."""
        with self._lock:
            target = next((j for j in self._jobs if j.status == "running"), None)
            if not target and self._last_active_id:
                target = self.get_job(self._last_active_id)
            if not target and self._jobs:
                target = self._jobs[-1]
            if not target:
                return {
                    "state": "idle",
                    "current_stage": "مش هتبدأ أي جلسة لسه",
                    "duration": "00:00",
                    "progress_done": 0,
                    "progress_total": 0,
                    "logs": [],
                    "total_logs": 0,
                    "has_screenshot": False,
                }
            return target.engine.get_status(since=since)

    def get_legacy_screenshot(self):
        with self._lock:
            target = next((j for j in self._jobs if j.status == "running"), None)
            if not target and self._last_active_id:
                target = self.get_job(self._last_active_id)
            if not target and self._jobs:
                target = self._jobs[-1]
            return target.engine.screenshot_bytes if target else None
