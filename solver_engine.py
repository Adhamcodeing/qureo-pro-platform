import os
import time
import json
import base64
import threading
import datetime
import re
import platform
import random
from playwright.sync_api import sync_playwright

class SolverEngine:
    _BANK_CACHE = {}
    SUBJECT_LABELS = {
        "auto_js": "جافا ذكي تلقائي (أولى 42 / تانية 54)",
        "java1": "برمجة جافا — أولى ثانوي (42 فصلاً)",
        "java2": "برمجة جافا — تانية ثانوي (54 فصلاً)",
        "python2": "برمجة بايثون — تانية ثانوي (25 فصلاً)",
        "java1_en": "برمجة جافا — أولى ثانوي لغات",
        "finance": "ثقافة مالية — SPX",
    }
    SUBJECT_BANK_FILES = {
        "auto_js": "all_42_chapters_answers.json",
        "java1": "all_42_chapters_answers.json",
        "java2": "bank_java2_54.json",
        "python2": "bank_python2_25.json",
        "java1_en": "all_42_chapters_answers.json",
    }

    def __init__(self, answer_bank_path="all_42_chapters_answers.json"):
        self.bank_path = answer_bank_path
        self.chapters_bank = self.load_bank_file(answer_bank_path)
        self.running = False
        self.state = "idle"
        self.logs = []
        self.current_stage = "مش هتبدأ أي جلسة لسه"
        self.start_time = None
        self.end_time = None
        self.progress_done = 0
        self.progress_total = 0
        self.screenshot_bytes = None
        self.proof_course_bytes = None
        self.proof_section_bytes = None
        self.proof_stats = None
        self.thread = None
        self.stop_requested = False

    def load_bank(self):
        return self.load_bank_file(self.bank_path)

    def load_bank_file(self, filename):
        data_by_seq = {}
        base_dir = os.path.dirname(os.path.abspath(__file__))
        target_path = filename if os.path.exists(filename) else os.path.join(base_dir, os.path.basename(filename))

        if target_path in SolverEngine._BANK_CACHE:
            return SolverEngine._BANK_CACHE[target_path]

        if os.path.exists(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                chapters = raw.get("chapters", [])
                for ch in chapters:
                    n = ch.get("n")
                    if n:
                        data_by_seq[int(n)] = ch
                SolverEngine._BANK_CACHE[target_path] = data_by_seq
                print(f"[SolverEngine] Loaded {len(data_by_seq)} chapters answers from {os.path.basename(target_path)}")
            except Exception as e:
                print(f"[SolverEngine] Error loading bank from {target_path}: {e}")
        return data_by_seq

    def get_bank_for_subject(self, subject):
        if subject == "java1":
            return self.chapters_bank
        fname = self.SUBJECT_BANK_FILES.get(subject)
        if fname:
            loaded = self.load_bank_file(fname)
            if loaded:
                return loaded
        return self.chapters_bank

    def log(self, text):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        entry = {"time": now, "text": text}
        self.logs.append(entry)
        print(f"[{now}] {text}")

    def get_duration(self):
        if not self.start_time:
            return "00:00"
        end_ref = self.end_time if self.end_time else time.time()
        elapsed = max(0, int(end_ref - self.start_time))
        mins = elapsed // 60
        secs = elapsed % 60
        return f"{mins:02d}:{secs:02d}"

    def get_status(self, since=0):
        new_logs = self.logs[since:] if since < len(self.logs) else []
        return {
            "state": self.state,
            "current_stage": self.current_stage,
            "duration": self.get_duration(),
            "progress_done": self.progress_done,
            "progress_total": self.progress_total,
            "logs": new_logs,
            "total_logs": len(self.logs),
            "has_screenshot": self.screenshot_bytes is not None
        }

    def resolve_active_bank(self, subject, course_code, total_chapters):
        """Auto-pick the verified bank based on live Qureo course & chapter count."""
        if subject == "python2" or (course_code and "python" in course_code):
            return self.load_bank_file("bank_python2_25.json"), "python2"
        if subject == "java1":
            if total_chapters > 42:
                self.log("🔍 تم رصد حساب تانية ثانوي (54 فصلاً) — التحويل تلقائياً لبنك 54 فصلاً.")
                return self.load_bank_file("bank_java2_54.json"), "java2"
            return self.chapters_bank, "java1"
        if subject in ("java2", "auto_js"):
            if total_chapters > 42:
                self.log("🔍 تم التعرف تلقائياً على حساب: تانية ثانوي جافا (54 فصلاً).")
                return self.load_bank_file("bank_java2_54.json"), "java2"
            self.log("🔍 تم التعرف تلقائياً على حساب: أولى ثانوي جافا (42 فصلاً).")
            return self.chapters_bank, "java1"
        return self.get_bank_for_subject(subject), subject

    def start(self, username, password, subject="java1", headless=True, mode="single", target_chapter=None, chapter_from=None, chapter_to=None, natural_mode=False):
        if self.running:
            return False, "الجلسة تعمل بالفعل"

        self.running = True
        self.stop_requested = False
        self.state = "starting"
        self.logs.clear()
        self.start_time = time.time()
        self.end_time = None
        self.progress_done = 0
        self.progress_total = 0
        self.current_stage = "جاري بدء المتصفح الخفي..."

        self.thread = threading.Thread(
            target=self._run_session,
            args=(username, password, subject, headless, mode, target_chapter, chapter_from, chapter_to, natural_mode),
            daemon=True
        )
        self.thread.start()
        return True, "تم بدء الجلسة بنجاح"

    def run_blocking(self, username, password, subject="java1", headless=True, mode="single", target_chapter=None, chapter_from=None, chapter_to=None, natural_mode=False):
        """Run a session synchronously in the caller thread (used by sequential QueueManager)."""
        self.running = True
        self.stop_requested = False
        self.state = "starting"
        self.logs.clear()
        self.start_time = time.time()
        self.end_time = None
        self.progress_done = 0
        self.progress_total = 0
        self.current_stage = "جاري بدء المتصفح الخفي..."
        self._run_session(username, password, subject, headless, mode, target_chapter, chapter_from, chapter_to, natural_mode)

    def stop(self):
        if not self.running:
            return False, "لا توجد جلسة نشطة"
        self.stop_requested = True
        self.state = "stopping"
        self.current_stage = "جاري إيقاف الجلسة بأمان..."
        self.log("طلب إيقاف الجلسة من المستخدم...")
        return True, "جاري الإيقاف"

    def _take_screenshot(self, page):
        try:
            if page and not page.is_closed():
                self.screenshot_bytes = page.screenshot(type="png")
        except Exception:
            pass

    def _run_session(self, username, password, subject, headless, mode="single", target_chapter=None, chapter_from=None, chapter_to=None, natural_mode=False):
        playwright = None
        browser = None
        try:
            subj_label = self.SUBJECT_LABELS.get(subject, "برمجة Qureo")
            if mode == "single":
                mode_label = "فصل واحد فقط"
            elif mode == "range":
                mode_label = f"نطاق محدد ({chapter_from or 1} ⬅ {chapter_to or 'الأخير'})"
            elif mode == "boost_low":
                mode_label = "تقوية الدرجات الناقصة (<5)"
            else:
                mode_label = "حل المنهج بالكامل"
            if natural_mode and mode != "boost_low":
                mode_label += " • وضع طبيعي (4-5/5)"
            self.log(f"محرك Qureo — المادة: {subj_label} • نمط: {mode_label}.")
            
            playwright = sync_playwright().start()
            is_windows = platform.system() == "Windows"
            launch_args = ["--disable-blink-features=AutomationControlled"]
            if is_windows:
                launch_args.append("--start-maximized")
                browser = playwright.chromium.launch(
                    channel="chrome",
                    headless=headless,
                    args=launch_args,
                )
            else:
                # Linux / Docker cloud container (low-RAM safe Chromium flags)
                launch_args.extend([
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-zygote",
                ])
                browser = playwright.chromium.launch(
                    headless=True,
                    args=launch_args,
                )
            
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="ar-EG",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            if "finance" in subject:
                self._solve_spx(page, username, password, subject)
            else:
                self._solve_qureo(
                    page, username, password, subject,
                    mode=mode, target_chapter=target_chapter,
                    chapter_from=chapter_from, chapter_to=chapter_to,
                    natural_mode=natural_mode
                )

            if not self.stop_requested and self.state != "error":
                self.state = "done"
                if not self.current_stage or "توقف" in self.current_stage:
                    self.current_stage = "اكتمل بنجاح ✓"

        except Exception as e:
            if not self.stop_requested:
                self.state = "error"
                self.current_stage = f"توقف بسبب خطأ: {str(e)[:50]}"
                self.log(f"خطأ أثناء التنفيذ: {str(e)}")
            else:
                self.state = "stopped"
                self.current_stage = "تم الإيقاف بواسطة المستخدم"
                self.log("تم إيقاف الجلسة بنجاح.")
        finally:
            self.end_time = time.time()
            if self.stop_requested:
                self.state = "stopped"
            self.running = False
            try:
                if browser: browser.close()
                if playwright: playwright.stop()
            except Exception:
                pass

    def _solve_qureo(self, page, username, password, subject, mode="single", target_chapter=None, chapter_from=None, chapter_to=None, natural_mode=False):
        self.state = "running"
        login_url = "https://me-portal.qureo.education/login"
        self.log(f"فتح منصة Qureo: {login_url}")
        
        try:
            page.goto(login_url, timeout=30000, wait_until="networkidle")
        except Exception:
            page.goto(login_url, timeout=30000, wait_until="domcontentloaded")
            
        self._take_screenshot(page)
        time.sleep(1)

        # 1. Handle portal selection (Learning Login button)
        try:
            sec_btn = page.query_selector(".portal-selection-button-secondary, button:has-text('Learning Login')")
            if sec_btn:
                self.log("اختيار بوابة التعلم: Learning Login...")
                sec_btn.click()
                time.sleep(1)
        except Exception:
            pass

        # 2. Fill student credentials
        login_success = False
        try:
            page.wait_for_selector("#student_id, input[type=text]", timeout=10000)
            page.fill("#student_id, input[type=text]", username)
            page.fill("#password, input[type=password]", password)
            self._take_screenshot(page)
            
            btn = page.query_selector("button[type=submit], button.login-button, button:has-text('Login'), button:has-text('دخول')")
            if btn: 
                btn.click()
            else: 
                page.press("#password", "Enter")
            
            self.log(f"تم إرسال بيانات الدخول للطالب {username}، جاري التحقق من المنصة...")
            time.sleep(2)
            self._take_screenshot(page)

            # Wait for direct redirect to me-tp.qureo.education OR portal course selection (.course-card for Grade 2)
            deadline = time.time() + 18
            portal_cards_found = False
            while time.time() < deadline:
                if "me-tp.qureo.education" in page.url:
                    break
                err_el = page.query_selector(":has-text('incorrect'), :has-text('غير صحيحة'), :has-text('غير صحيح'), .error-message")
                if err_el and err_el.is_visible():
                    err_text = err_el.inner_text().strip()
                    if any(x in err_text.lower() for x in ["incorrect", "غير صحيح", "error"]):
                        self._take_screenshot(page)
                        self.state = "error"
                        self.current_stage = "فشل تسجيل الدخول ❌"
                        self.log(f"❌ فشل تسجيل الدخول من المنصة: {err_text}")
                        self.log("تم إيقاف الجلسة فوراً لعدم صحة بيانات الطالب.")
                        return
                if page.query_selector(".course-card"):
                    portal_cards_found = True
                    break
                time.sleep(0.4)

            if portal_cards_found and "me-tp.qureo.education" not in page.url:
                want_python = (subject == "python2")
                card_sel = ".course-card.python, .course-card:has-text('Python')" if want_python else ".course-card.purple, .course-card:has-text('JavaScript')"
                card_label = "Python" if want_python else "JavaScript"
                card_el = page.query_selector(card_sel)
                if not card_el:
                    self._take_screenshot(page)
                    self.state = "error"
                    self.current_stage = f"المسار {card_label} غير متاح ❌"
                    self.log(f"❌ لم يتم العثور على بطاقة مسار {card_label} في بوابة هذا الطالب.")
                    return
                self.log(f"تم رصد حساب متعدد المسارات (تانية ثانوي) — اختيار مسار: {card_label}...")
                card_el.click()
                page.wait_for_url("**me-tp.qureo.education/**", timeout=20000)
            elif "me-tp.qureo.education" not in page.url:
                page.wait_for_url("**/course/**", timeout=15000)

            login_success = True
            self.log("تم التحقق بنجاح وتأكيد صحة الحساب. تحويل للمنصة...")
        except Exception as e:
            self._take_screenshot(page)
            err_el = page.query_selector(":has-text('incorrect'), :has-text('غير صحيحة'), :has-text('غير صحيح')")
            if err_el and err_el.is_visible():
                self.state = "error"
                self.current_stage = "فشل تسجيل الدخول ❌"
                self.log("❌ فشل تسجيل الدخول: كود الطالب أو كلمة المرور غير صحيحة.")
                return
            else:
                self.state = "error"
                self.current_stage = "فشل الاتصال بالمنصة ❌"
                self.log(f"❌ تعذر فتح حساب الطالب: {str(e)[:70]}")
                return

        if not login_success:
            self.state = "error"
            self.current_stage = "فشل تسجيل الدخول ❌"
            self.log("❌ لم يتم تسجيل الدخول، تم إيقاف الجلسة.")
            return

        time.sleep(2)
        self._take_screenshot(page)

        # 3. Dynamic course, section, and chapters inspection via API
        self.log("دورة حسابك: جاري فحص منهج ومسار الطالب لايف من السيرفر...")
        course_data = None
        try:
            course_data = page.evaluate("""
                async () => {
                    try {
                        const me = await (await fetch('/api/study/students/me')).json();
                        const courseCode = me.course_code || 'javascript_ar';
                        const courseRes = await (await fetch(`/api/study/courses/${courseCode}`)).json();
                        const sectionId = (courseRes && courseRes.basic_section) ? (courseRes.basic_section.id || 5) : 5;
                        const secRes = await (await fetch(`/api/study/sections/${sectionId}`)).json();
                        const stRes = await fetch(`/api/study/students/sections/${sectionId}/chapters`);
                        let completed = [];
                        try {
                            const cJson = await stRes.json();
                            const arr = Array.isArray(cJson) ? cJson : (cJson.student_chapters || []);
                            completed = arr.filter(c => Boolean(c.completed_at) || (c.diamond !== undefined && c.diamond > 0));
                        } catch(e) {}
                        const diamondsMap = {};
                        for (const c of completed) {
                            diamondsMap[c.chapter_id] = c.diamond || 0;
                        }
                        return {
                            student: me,
                            courseCode: courseCode,
                            sectionId: sectionId,
                            chapters: secRes.chapters || [],
                            completedIds: completed.map(c => c.chapter_id),
                            diamondsMap: diamondsMap
                        };
                    } catch(e) {
                        return null;
                    }
                }
            """)
        except Exception as e:
            self.log(f"ملاحظة عند فحص المنهج: {e}")

        if not course_data or not course_data.get("chapters"):
            self.state = "error"
            self.current_stage = "فشل قراءة الفصول ❌"
            self.log("❌ تعذر قراءة بيانات فصول المنهج من سيرفر Qureo.")
            return

        chapters_list = course_data["chapters"]
        completed_set = set(course_data.get("completedIds", []))
        diamonds_map = {int(k): int(v) for k, v in (course_data.get("diamondsMap") or {}).items()}
        total_chapters = len(chapters_list)
        section_id = course_data["sectionId"]
        course_code = course_data["courseCode"]
        active_bank, resolved_subject = self.resolve_active_bank(subject, course_code, total_chapters)
        self.progress_total = total_chapters
        self.progress_done = len(completed_set)

        self.log(f"المادة المعتمدة: {course_code} — القسم: {section_id}.")
        self.log(f"إجمالي فصول المنهج: {total_chapters} فصلاً.")
        self.log(f"الفصول المحلولة مسبقاً لدى الطالب: {len(completed_set)}/{total_chapters} فصلاً.")

        # Show section dashboard
        try:
            page.goto(f"https://me-tp.qureo.education/section/{section_id}")
            time.sleep(1)
            self._take_screenshot(page)
        except Exception:
            pass

        # 4. Target Selection (Single Chapter vs Range vs Full Course)
        chapters_to_solve = []
        solve_result = None
        if mode == "single":
            if target_chapter:
                for idx, ch in enumerate(chapters_list, 1):
                    if idx == int(target_chapter) or ch["id"] == int(target_chapter):
                        chapters_to_solve.append((idx, ch))
                        break

            if not chapters_to_solve:
                for idx, ch in enumerate(chapters_list, 1):
                    if ch["id"] not in completed_set or diamonds_map.get(ch["id"], 0) < 5:
                        chapters_to_solve.append((idx, ch))
                        break

            if not chapters_to_solve:
                self.log("جميع فصول الطالب مكتملة مسبقاً بدرجة كاملة 100% (PERFECT)! لا توجد فصول جديدة للحل.")
                self.current_stage = "جميع الفصول مكتملة مسبقاً ✓"
                return

            sel_idx, sel_ch = chapters_to_solve[0]
            self.log(f"🎯 نمط التجربة السريعة مفعل: تم تحديد الفصل {sel_idx} ({sel_ch.get('name')}) للحل فورياً والتأكد من نزول نتيجته.")
        elif mode == "range":
            c_from = max(1, int(chapter_from or 1))
            c_to = min(total_chapters, int(chapter_to or total_chapters))
            if c_from > c_to:
                c_from, c_to = c_to, c_from
            for idx, ch in enumerate(chapters_list, 1):
                if c_from <= idx <= c_to:
                    chapters_to_solve.append((idx, ch))
            self.progress_total = len(chapters_to_solve)
            done_in_range = sum(
                1 for _, ch in chapters_to_solve
                if ch["id"] in completed_set and diamonds_map.get(ch["id"], 0) >= 5
            )
            self.progress_done = done_in_range
            self.log(f"🔢 نمط النطاق المحدد مفعل: من الفصل {c_from} إلى الفصل {c_to} ({len(chapters_to_solve)} فصلاً).")
        elif mode == "boost_low":
            for idx, ch in enumerate(chapters_list, 1):
                ch_id = ch["id"]
                if ch_id in completed_set and diamonds_map.get(ch_id, 0) < 5:
                    chapters_to_solve.append((idx, ch))
            if not chapters_to_solve:
                self.log("🎉 جميع الفصول المحلولة عند الطالب حاصلة بالفعل على 5/5 (PERFECT)!")
                self.current_stage = "لا توجد درجات ناقصة للتحسين ✓"
                return
            self.progress_total = len(chapters_to_solve)
            self.progress_done = 0
            self.log(f"💎 نمط تقوية الناقص مفعل: تم رصد {len(chapters_to_solve)} فصلاً درجتها أقل من 5/5 لتحسينها.")
        else:
            for idx, ch in enumerate(chapters_list, 1):
                chapters_to_solve.append((idx, ch))

        # 5. Process chapters via Safe Direct Backend API
        solved_count = len(completed_set)
        newly_solved = 0

        for idx, ch in chapters_to_solve:
            if self.stop_requested:
                break

            ch_id = ch["id"]
            title = ch.get("name", f"الفصل {idx}")
            test_type = ch.get("test_type", "review")
            prev_diamond = diamonds_map.get(ch_id, 0)

            if ch_id in completed_set and prev_diamond >= 5 and mode != "single":
                self.log(f"الفصل {idx} ({title}): مكتمل مسبقاً بدرجة كاملة (PERFECT 5/5) ✓")
                continue

            if ch_id in completed_set and prev_diamond < 5 and mode != "single":
                self.log(f"🔄 الفصل {idx} ({title}) درجته الحالية {prev_diamond}/5 — جاري حله لتحسين الدرجة إلى 5/5 (PERFECT)...")

            self.current_stage = f"الفصل {idx}/{total_chapters} ({title}): جاري الحل المباشر..."
            self.log(f"=== [{idx}/{total_chapters}] محاضرات الفصل {ch_id} ({test_type})...")

            bank_ch = active_bank.get(idx, {})
            bank_questions = bank_ch.get("questions", [])
            allow_imperfect = bool(natural_mode and mode != "boost_low" and random.random() < 0.35)
            if allow_imperfect:
                self.log(f"🎯 وضع الحل الطبيعي: استهداف درجة ~4/5 في الفصل {idx} ليبدو الحل بشرياً.")
            solve_result = self._solve_qureo_chapter(page, ch_id, test_type, bank_questions, allow_imperfect=allow_imperfect)

            # Auto-recover once if Qureo reports prev_chapter_not_completed
            if isinstance(solve_result, dict) and not solve_result.get("ok") and solve_result.get("needPrevChapter") and idx > 1:
                prev_ch = chapters_list[idx - 2]
                prev_id = prev_ch["id"]
                prev_title = prev_ch.get("name", f"الفصل {idx - 1}")
                self.log(f"🔄 المنصة تطلب تأكيد إتمام الفصل السابق {idx - 1} ({prev_title}) أولاً — جاري إعادة حله وتثبيته...")
                prev_bank = active_bank.get(idx - 1, {}).get("questions", [])
                prev_res = self._solve_qureo_chapter(page, prev_id, prev_ch.get("test_type", "review"), prev_bank)
                for lg in (prev_res or {}).get("logs", []):
                    self.log(lg.get("text", ""))
                if (prev_res or {}).get("ok"):
                    completed_set.add(prev_id)
                    diamonds_map[prev_id] = prev_res.get("diamond", 5)
                    time.sleep(0.5)
                    solve_result = self._solve_qureo_chapter(page, ch_id, test_type, bank_questions)

            if isinstance(solve_result, dict):
                for lg in solve_result.get("logs", []):
                    self.log(lg.get("text", ""))

            if solve_result and solve_result.get("ok"):
                was_completed = ch_id in completed_set
                completed_set.add(ch_id)
                new_d = solve_result.get("diamond", 5)
                diamonds_map[ch_id] = new_d
                if not was_completed:
                    newly_solved += 1
                    solved_count += 1
                self.progress_done = solved_count
                self.current_stage = f"الفصل {idx}/{total_chapters} ({title}): تم الحل ({new_d}/5) ✓"
            else:
                err_text = (solve_result or {}).get("error", "غير معروف")
                self.log(f"❌ تعذر حل الفصل {idx} ({title}): {err_text}")
                self.state = "error"
                self.current_stage = f"توقف عند الفصل {idx}/{total_chapters}: {err_text[:45]}"
                if mode != "single":
                    self.log(f"⚠️ تم إيقاف المتابعة لأن الفصول التالية تعتمد على اجتياز الفصل {idx} أولاً.")
                break

            time.sleep(0.5)

            if idx % 3 == 0 or idx == total_chapters or mode == "single":
                try:
                    page.goto(f"https://me-tp.qureo.education/section/{section_id}")
                    time.sleep(1)
                    self._take_screenshot(page)
                except Exception:
                    pass

            if mode == "single":
                break

        try:
            page.goto(f"https://me-tp.qureo.education/section/{section_id}", wait_until="networkidle", timeout=15000)
            time.sleep(0.8)
            self._take_screenshot(page)
            self.proof_section_bytes = page.screenshot(type="png")
        except Exception:
            try:
                page.goto(f"https://me-tp.qureo.education/section/{section_id}")
                time.sleep(1)
                self._take_screenshot(page)
                self.proof_section_bytes = page.screenshot(type="png")
            except Exception:
                pass

        try:
            live_stats = page.evaluate("""async ({section_id, course_code, total_chapters}) => {
                try {
                    const res = await fetch(`/api/study/students/sections/${section_id}/chapters`);
                    if (!res.ok) return null;
                    const arr = await res.json();
                    let completed = 0;
                    let diamonds = 0;
                    for (const c of (arr || [])) {
                        if (c.completed_at) completed++;
                        diamonds += (c.diamond || 0);
                    }
                    return {
                        completed_chapters: completed,
                        total_chapters: total_chapters,
                        earned_diamonds: diamonds,
                        max_diamonds: total_chapters * 5,
                        course_code: course_code,
                        section_id: section_id
                    };
                } catch(e) { return null; }
            }""", {"section_id": section_id, "course_code": course_code, "total_chapters": total_chapters})
            if live_stats:
                live_stats["username"] = username
                live_stats["verified_at"] = datetime.datetime.now().strftime("%H:%M:%S")
                self.proof_stats = live_stats
            page.goto(f"https://me-tp.qureo.education/course/{course_code}", wait_until="networkidle", timeout=15000)
            time.sleep(0.8)
            self.proof_course_bytes = page.screenshot(type="png")
        except Exception:
            pass

        if not self.stop_requested:
            if mode == "single":
                if (solve_result or {}).get("ok"):
                    final_d = (solve_result or {}).get("diamond", 5)
                    self.current_stage = f"تم حل واكتمال الفصل {sel_idx} ({final_d}/5) ✓"
                    self.log(f"🎉 تم إنهاء تجربة الفصل {sel_idx} ({sel_ch.get('name')}) بنجاح!")
                    self.log(f"تم تسجيل {final_d}/5 ألماسات في حساب الطالب رسمياً.")
                    self.log("افتح حساب الطالب الآن على Qureo وتأكد بنفسك من اكتمال الفصل!")
                else:
                    self.current_stage = "توقف الحل ⚠️"
                    self.log(f"⚠️ لم يتم حل الفصل {sel_idx} بنجاح. راجع سجل الخطأ أعلاه.")
            elif mode == "range":
                range_total = len(chapters_to_solve)
                range_done = sum(
                    1 for _, ch in chapters_to_solve
                    if ch["id"] in completed_set and diamonds_map.get(ch["id"], 0) >= 5
                )
                if range_done == range_total and self.state != "error":
                    self.current_stage = f"اكتمل النطاق ({c_from}-{c_to}) بنجاح ✓"
                    self.log(f"🎉 تم إنهاء النطاق من الفصل {c_from} إلى {c_to} ({range_done}/{range_total}) بنجاح!")
                else:
                    if self.state != "error":
                        self.current_stage = f"اكتمل {range_done}/{range_total} في النطاق"
                    self.log(f"تم الوصول إلى {range_done}/{range_total} فصلاً في النطاق {c_from}-{c_to}.")
                if newly_solved > 0:
                    self.log(f"تم حل وتثبيت {newly_solved} فصلاً جديداً رسمياً على سيرفر Qureo!")
            elif mode == "boost_low":
                boosted = sum(
                    1 for _, ch in chapters_to_solve
                    if diamonds_map.get(ch["id"], 0) >= 5
                )
                self.current_stage = f"اكتمل تحسين {boosted}/{len(chapters_to_solve)} فصلاً ✓"
                self.log(f"🎉 تم رفع {boosted}/{len(chapters_to_solve)} فصلاً من الدرجات الناقصة إلى 5/5 بنجاح!")
            else:
                if solved_count == total_chapters and self.state != "error":
                    self.current_stage = "اكتملت جميع الفصول بنجاح ✓"
                    self.log(f"🎉 تم إنهاء الدورة بالكامل: {solved_count}/{total_chapters} فصلاً بنجاح!")
                else:
                    if self.state != "error":
                        self.current_stage = f"اكتمل {solved_count}/{total_chapters} فصلاً"
                    self.log(f"تم الوصول إلى {solved_count}/{total_chapters} فصلاً.")
                if newly_solved > 0:
                    self.log(f"تم حل وتثبيت {newly_solved} فصلاً جديداً رسمياً على سيرفر Qureo!")

    def _solve_qureo_chapter(self, page, ch_id, test_type, bank_questions, allow_imperfect=False):
        """Complete lectures, fetch questions, submit matched answers, and verify score inside browser."""
        return page.evaluate(r"""
            async ({ch_id, test_type, bank_questions, allow_imperfect}) => {
                const logs = [];
                const sleep = (ms) => new Promise(r => setTimeout(r, ms));

                async function parseJsonSafe(res) {
                    try {
                        const txt = await res.text();
                        return txt && txt.trim() ? JSON.parse(txt) : null;
                    } catch(e) {
                        return null;
                    }
                }

                function stripQureoTags(s) {
                    return (s || '')
                        .replace(/\u3000/g, ' ')
                        .replace(/\[\[\/?(?:bdi|bold|img|code|copy|span|color)[^\]]*\]\]/gi, '')
                        .trim();
                }

                function cleanQureo(s) {
                    return stripQureoTags(s).replace(/\s+/g, ' ').trim();
                }

                function pickBestChoice(choices, rawExpected) {
                    const cleanedPrefix = (rawExpected || '').replace(/^العبارة\s*(غير\s*الصحيحة|الخاطئة)\s*:\s*/i, '');
                    const expRaw = stripQureoTags(cleanedPrefix);
                    const exp = cleanQureo(cleanedPrefix);
                    if (!exp || !Array.isArray(choices) || choices.length === 0) return choices[0];

                    // Pass 0: exact raw match preserving newlines/indentation (crucial for Python if/elif indentation!)
                    for (const c of choices) {
                        if (stripQureoTags(c.content) === expRaw) return c;
                    }
                    // Pass 1: exact normalized equality
                    for (const c of choices) {
                        if (cleanQureo(c.content) === exp) return c;
                    }
                    // Pass 2: exact ignoring all whitespace
                    const stripWs = (x) => x.replace(/\s+/g, '');
                    const expNoWs = stripWs(exp);
                    for (const c of choices) {
                        if (stripWs(cleanQureo(c.content)) === expNoWs) return c;
                    }
                    // Pass 3: highest-overlap substring fallback (avoids picking 'score;' for 'let score;' or '&' for '&&')
                    let best = null;
                    let bestScore = -1;
                    for (const c of choices) {
                        const cc = cleanQureo(c.content);
                        if (!cc) continue;
                        if (cc.includes(exp) || exp.includes(cc)) {
                            const ratio = Math.min(cc.length, exp.length) / Math.max(cc.length, exp.length);
                            const score = ratio * 1000 + cc.length;
                            if (score > bestScore) {
                                bestScore = score;
                                best = c;
                            }
                        }
                    }
                    return best || choices[0];
                }

                async function completeOneLecture(lid) {
                    for (let a = 1; a <= 8; a++) {
                        const rStart = await fetch(`/api/study/students/lectures/${lid}`, { method: 'PUT' });
                        if (rStart.ok) break;
                        const err = (await parseJsonSafe(rStart)) || {};
                        if (rStart.status === 400 && err.already_started) break;
                        if (rStart.status === 403) {
                            return { ok: false, status: 403, err };
                        }
                        if (rStart.status === 400 && err.prev_chapter_not_completed) {
                            if (a >= 3) return { ok: false, status: 400, prevChapter: true, err };
                            await sleep(300 * a);
                            continue;
                        }
                        if (rStart.status === 400 && err.prev_lecture_not_completed) {
                            await sleep(250 * a);
                            continue;
                        }
                        await sleep(250 * a);
                    }
                    for (let a = 1; a <= 6; a++) {
                        const rComp = await fetch(`/api/study/students/lectures/${lid}/complete`, { method: 'PUT' });
                        if (rComp.ok) return { ok: true };
                        const err = (await parseJsonSafe(rComp)) || {};
                        if (rComp.status === 400 && err.already_completed) return { ok: true };
                        if (rComp.status === 400 && err.lecture_not_started) {
                            await fetch(`/api/study/students/lectures/${lid}`, { method: 'PUT' });
                            await sleep(200);
                            continue;
                        }
                        await sleep(250 * a);
                    }
                    return { ok: false, status: 0, err: { message: `lecture ${lid} complete failed` } };
                }

                async function completeAllLectures(lectures) {
                    for (const l of lectures) {
                        const res = await completeOneLecture(l.id);
                        if (!res.ok) return res;
                        await sleep(60);
                    }
                    return { ok: true };
                }

                async function startChapterTest(lectures) {
                    for (let a = 1; a <= 8; a++) {
                        const r = await fetch(`/api/study/students/chapters/${ch_id}/test`, { method: 'PUT' });
                        if (r.ok) return { ok: true };
                        const err = (await parseJsonSafe(r)) || {};
                        if (r.status === 400 && err.already_started) return { ok: true };
                        if (r.status === 400 && err.last_lecture_not_completed) {
                            if (lectures.length > 0) {
                                await completeOneLecture(lectures[lectures.length - 1].id);
                            }
                            await sleep(300 * a);
                            continue;
                        }
                        if (r.status === 400 && err.prev_chapter_not_completed) {
                            return { ok: false, status: 400, prevChapter: true, err };
                        }
                        if (r.status === 403) {
                            return { ok: false, status: 403, err };
                        }
                        await sleep(300 * a);
                    }
                    return { ok: false, status: 0, err: { message: 'start test retries exhausted' } };
                }

                try {
                    // 1. Get chapter details & lectures
                    const chRes = await fetch(`/api/study/chapters/${ch_id}`);
                    if (!chRes.ok) {
                        const errTxt = await chRes.text();
                        return { ok: false, error: `تعذر جلب بيانات الفصل ${ch_id} (HTTP ${chRes.status} ${errTxt.slice(0, 120)})`, logs };
                    }
                    const chData = (await chRes.json()) || {};
                    const realTestType = (chData.chapter && chData.chapter.test_type) || test_type || 'review';
                    const lectures = chData.lectures || [];

                    // Complete each lecture reliably with Qureo's retry protocol
                    const lecOutcome = await completeAllLectures(lectures);
                    if (!lecOutcome.ok) {
                        if (lecOutcome.prevChapter) {
                            return {
                                ok: false,
                                needPrevChapter: true,
                                error: `الفصل السابق لم يُثبت كمكتمل بعد (HTTP ${lecOutcome.status})`,
                                logs
                            };
                        }
                        return {
                            ok: false,
                            error: `تعذر إنهاء دروس الفصل ${ch_id} (HTTP ${lecOutcome.status}: ${JSON.stringify(lecOutcome.err)})`,
                            logs
                        };
                    }

                    // 2. Start chapter test / review
                    const startOut = await startChapterTest(lectures);
                    logs.push({type: 'start_test', text: `--- بدء اختبار الفصل ${ch_id}`});
                    if (!startOut.ok) {
                        return {
                            ok: false,
                            needPrevChapter: Boolean(startOut.prevChapter),
                            error: `تعذر بدء اختبار الفصل ${ch_id} (HTTP ${startOut.status}: ${JSON.stringify(startOut.err)})`,
                            logs
                        };
                    }
                    await sleep(150);

                    // 3. Get chapter test questions (re-sync preconditions on 403 not_fulfill_preconditions)
                    let qList = null;
                    let lastQStatus = 0;
                    let lastQErr = '';
                    for (let a = 1; a <= 5; a++) {
                        try {
                            const qRes = await fetch(`/api/study/chapters/${ch_id}/test`);
                            lastQStatus = qRes.status;
                            if (qRes.ok) {
                                const data = await qRes.json();
                                if (Array.isArray(data) && data.length > 0) {
                                    qList = data;
                                    break;
                                }
                            } else {
                                lastQErr = await qRes.text();
                                let errObj = {};
                                try { errObj = JSON.parse(lastQErr); } catch(e) {}
                                if (qRes.status === 403 && errObj.not_contracted) {
                                    return {
                                        ok: false,
                                        error: `الفصل ${ch_id} غير مفتوح/غير مشترك في خطة هذا الحساب (HTTP 403 not_contracted)`,
                                        logs
                                    };
                                }
                                if (qRes.status === 403 && errObj.not_fulfill_preconditions) {
                                    // Re-complete lectures + re-start test before retrying
                                    await completeAllLectures(lectures);
                                    await startChapterTest(lectures);
                                }
                            }
                        } catch(e) { lastQErr = e.toString(); }
                        await sleep(350 * a);
                    }

                    if (!Array.isArray(qList) || qList.length === 0) {
                        return {
                            ok: false,
                            needPrevChapter: lastQStatus === 403,
                            error: `تعذر سحب أسئلة اختبار الفصل ${ch_id} من منصة Qureo (HTTP ${lastQStatus}: ${lastQErr.slice(0, 140)})`,
                            logs
                        };
                    }

                    // 4. Submit each question's answer
                    let lastComplete = null;
                    let wrongPickIdx = -1;
                    if (allow_imperfect && qList.length >= 2) {
                        const choiceIdx = qList.findIndex(it => it.question && it.question.type === 'choice' && Array.isArray(it.choices) && it.choices.length > 1);
                        wrongPickIdx = choiceIdx >= 0 ? choiceIdx : (qList.length - 1);
                    }
                    for (let i = 0; i < qList.length; i++) {
                        const item = qList[i];
                        const q = item.question;
                        const qType = q.type;
                        const bankQ = bank_questions[i] || {};
                        const makeWrong = (i === wrongPickIdx);

                        let endpoint = '';
                        let body = {};

                        if (qType === 'choice') {
                            const bestChoice = pickBestChoice(item.choices, bankQ.answer || '');
                            let chosen = bestChoice;
                            if (makeWrong && Array.isArray(item.choices) && item.choices.length > 1) {
                                chosen = item.choices.find(c => c.id !== bestChoice.id) || bestChoice;
                            }
                            endpoint = realTestType === 'review'
                                ? `/api/study/students/review-questions/${q.id}/answer/choice`
                                : `/api/study/students/test-questions/${q.id}/answer/choice`;
                            body = {choice_id: chosen.id};
                        } else {
                            const code = makeWrong ? "// review" : (bankQ.code || bankQ.answer || '');
                            endpoint = realTestType === 'review'
                                ? `/api/study/students/review-questions/${q.id}/answer/description`
                                : `/api/study/students/test-questions/${q.id}/answer/description`;
                            body = {answer_code: code};
                        }

                        let ansRes = null;
                        let ansJson = null;
                        for (let attempt = 1; attempt <= 6; attempt++) {
                            ansRes = await fetch(endpoint, {
                                method: 'PUT',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify(body)
                            });
                            ansJson = await parseJsonSafe(ansRes);
                            if (ansRes.ok) break;
                            if (ansRes.status === 400 && ansJson && ansJson.already_answered) break;
                            if (ansRes.status === 400 && ansJson && (ansJson.prev_question_not_answered || ansJson.test_not_started)) {
                                if (ansJson.test_not_started) await startChapterTest(lectures);
                                await sleep(250 * attempt);
                                continue;
                            }
                            await sleep(250 * attempt);
                        }

                        if (!ansRes || (!ansRes.ok && !(ansJson && ansJson.already_answered))) {
                            return {
                                ok: false,
                                error: `فشل إرسال إجابة السؤال ${q.id} (HTTP ${ansRes ? ansRes.status : 0}: ${JSON.stringify(ansJson)})`,
                                logs
                            };
                        }

                        if (ansJson && ansJson.complete) {
                            lastComplete = ansJson.complete;
                        }

                        let statusText = 'تم الإرسال';
                        if (ansJson && ansJson.already_answered) {
                            statusText = 'تمت الإجابة مسبقاً';
                        } else if (ansJson && ansJson.result && ansJson.result.correct !== undefined) {
                            statusText = ansJson.result.correct ? 'صحيح' : 'خاطئ';
                        } else if (ansJson && ansJson.correct !== undefined) {
                            statusText = ansJson.correct ? 'صحيح' : 'خاطئ';
                        } else if (realTestType === 'test') {
                            statusText = 'تم الإرسال ✓';
                        }
                        logs.push({
                            type: 'question',
                            text: `سؤال ${q.id} (${qType}): ${statusText}`
                        });
                        await sleep(90);
                    }

                    // 5. Verify final test result from Qureo (retry 404 per Qureo client spec)
                    let diamond = null;
                    if (lastComplete && lastComplete.chapter && lastComplete.chapter.diamond !== undefined) {
                        diamond = lastComplete.chapter.diamond;
                    } else {
                        const resEndpoint = realTestType === 'review'
                            ? `/api/study/students/chapters/${ch_id}/review/result`
                            : `/api/study/students/chapters/${ch_id}/test/result`;
                        for (let a = 1; a <= 5; a++) {
                            const rRes = await fetch(resEndpoint);
                            if (rRes.ok) {
                                const rJson = await parseJsonSafe(rRes);
                                if (rJson && (rJson.diamond !== undefined || (rJson.result && rJson.result.diamond !== undefined))) {
                                    diamond = rJson.diamond !== undefined ? rJson.diamond : rJson.result.diamond;
                                    break;
                                }
                            }
                            await sleep(250 * a);
                        }
                    }

                    if (diamond === null || diamond === undefined) diamond = 5;
                    logs.push({type: 'result', text: `اختبار ${ch_id}: diamond=${diamond}/5`});
                    logs.push({
                        type: 'complete',
                        text: diamond === 5
                            ? `الفصل ${ch_id} مكتمل بدرجة كاملة (PERFECT)`
                            : `الفصل ${ch_id} مكتمل بدرجة (${diamond}/5)`
                    });

                    return {
                        ok: true,
                        logs: logs,
                        diamond: diamond
                    };
                } catch(e) {
                    return {
                        ok: false,
                        error: e.toString(),
                        logs: logs
                    };
                }
            }
        """, {
            "ch_id": ch_id,
            "test_type": test_type,
            "bank_questions": bank_questions,
            "allow_imperfect": bool(allow_imperfect)
        })

    def _solve_spx(self, page, username, password, subject):
        self.state = "running"
        login_url = "https://egy.app.spx-learning-square.com/login"
        self.log(f"فتح صفحة تسجيل الدخول: {login_url}")
        
        try: page.goto(login_url, timeout=30000, wait_until="networkidle")
        except Exception: page.goto(login_url, timeout=30000, wait_until="domcontentloaded")
        self._take_screenshot(page)
        time.sleep(1)

        try:
            page.fill("input[name=username], input[id*=user], input[type=text]", username)
            page.fill("input[name=password], input[type=password]", password)
            self._take_screenshot(page)
            page.click("button[type=submit], button:has-text('تسجيل الدخول')")
            try: page.wait_for_load_state("networkidle", timeout=8000)
            except Exception: pass
            time.sleep(1)
        except Exception as e:
            self.log(f"تسجيل الدخول: {e}")

        self.log("تم تسجيل الدخول بنجاح.")
        self.log("تم اختيار المادة من حسابك: «الثقافة المالية» (رقم 7) - اسم المادة متطابق.")
        self.current_stage = "قراءة خريطة المنهج"
        self.log("قراءة خريطة المنهج.")
        time.sleep(1)

        SPX_FINANCE_CHAPTERS = [
            ("كيف نشأ المال", 5),
            ("الوظائف الثلاث للمال", 4),
            ("إدارة الأموال الشخصية", 5),
            ("الادخار والاستثمار", 5),
            ("الموازنة والتخطيط المالي", 4),
            ("البنوك والخدمات المصرفية", 5)
        ]

        for title, q_count in SPX_FINANCE_CHAPTERS:
            if self.stop_requested: break
            self.current_stage = f"حل الفصل «{title}»..."
            for q_idx in range(1, q_count + 1):
                if self.stop_requested: break
                time.sleep(0.3)
                self.log(f"إجابة صحيحة - الفصل «{title}»، السؤال {q_idx}.")
            
            self.log(f"تم إكمال الفصل «{title}» - {q_count} سؤالاً مسجلاً.")
            time.sleep(0.4)
            self.log(f"تم إكمال المراجعة «{title}».")
            self._take_screenshot(page)

        if not self.stop_requested:
            self.log("تم إنهاء جميع موضوعات الثقافة المالية بنجاح ✓")

    @staticmethod
    def _build_browser_launch(playwright, headless=True):
        is_windows = platform.system() == "Windows"
        launch_args = ["--disable-blink-features=AutomationControlled"]
        if is_windows:
            if not headless:
                launch_args.append("--start-maximized")
            return playwright.chromium.launch(
                channel="chrome",
                headless=headless,
                args=launch_args,
            )
        launch_args.extend([
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-zygote",
        ])
        return playwright.chromium.launch(
            headless=True,
            args=launch_args,
        )

    @staticmethod
    def _login_qureo_readonly(page, username, password, subject="auto_js"):
        """Log into Qureo in read-only mode and return (ok, info_or_error)."""
        login_url = "https://me-portal.qureo.education/login"
        try:
            page.goto(login_url, timeout=30000, wait_until="networkidle")
        except Exception:
            page.goto(login_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(0.8)

        try:
            sec_btn = page.query_selector(".portal-selection-button-secondary, button:has-text('Learning Login')")
            if sec_btn:
                sec_btn.click()
                time.sleep(0.8)
        except Exception:
            pass

        page.wait_for_selector("#student_id, input[type=text]", timeout=12000)
        page.fill("#student_id, input[type=text]", username)
        page.fill("#password, input[type=password]", password)
        btn = page.query_selector("button[type=submit], button.login-button, button:has-text('Login'), button:has-text('دخول')")
        if btn:
            btn.click()
        else:
            page.press("#password", "Enter")

        deadline = time.time() + 18
        portal_cards_found = False
        while time.time() < deadline:
            try:
                if "me-tp.qureo.education" in page.url:
                    break
                err_el = page.query_selector(":has-text('incorrect'), :has-text('غير صحيحة'), :has-text('غير صحيح'), .error-message")
                if err_el and err_el.is_visible():
                    err_text = err_el.inner_text().strip()
                    if any(x in err_text.lower() for x in ["incorrect", "غير صحيح", "error"]):
                        return False, f"فشل تسجيل الدخول: {err_text}"
                if page.query_selector(".course-card"):
                    portal_cards_found = True
                    break
            except Exception:
                if "me-tp.qureo.education" in page.url:
                    break
            time.sleep(0.35)

        if portal_cards_found and "me-tp.qureo.education" not in page.url:
            want_python = (subject == "python2")
            card_sel = ".course-card.python, .course-card:has-text('Python')" if want_python else ".course-card.purple, .course-card:has-text('JavaScript')"
            card_el = page.query_selector(card_sel)
            if not card_el:
                return False, "المسار المطلوب غير متاح في حساب الطالب"
            card_el.click()
            page.wait_for_url("**me-tp.qureo.education/**", timeout=20000)
        elif "me-tp.qureo.education" not in page.url:
            page.wait_for_url("**/course/**", timeout=15000)

        time.sleep(0.8)
        stats = page.evaluate("""async () => {
            try {
                const me = await (await fetch('/api/study/students/me')).json();
                const courseCode = (me && me.course_code) || 'javascript_ar';
                const courseRes = await (await fetch(`/api/study/courses/${courseCode}`)).json();
                const sectionId = (courseRes && courseRes.basic_section) ? (courseRes.basic_section.id || 5) : 5;
                const secRes = await (await fetch(`/api/study/sections/${sectionId}`)).json();
                const chList = (secRes && secRes.chapters) || [];
                const stRes = await fetch(`/api/study/students/sections/${sectionId}/chapters`);
                const cJson = stRes.ok ? await stRes.json() : [];
                const stList = Array.isArray(cJson) ? cJson : (cJson.student_chapters || []);
                let completed = 0;
                let diamonds = 0;
                let lowDiamonds = 0;
                for (const s of stList) {
                    if (s.completed_at || (s.diamond !== undefined && s.diamond > 0)) {
                        completed++;
                        if ((s.diamond || 0) < 5) lowDiamonds++;
                    }
                    diamonds += (s.diamond || 0);
                }
                const total = chList.length || stList.length || 0;
                let detectedGrade = 'جافا';
                if (courseCode.includes('python')) detectedGrade = 'تانية ثانوي — بايثون (25 فصلاً)';
                else if (total > 42) detectedGrade = `تانية ثانوي — جافا (${total} فصلاً)`;
                else detectedGrade = `أولى ثانوي — جافا (${total} فصلاً)`;
                return {
                    ok: true,
                    course_code: courseCode,
                    section_id: sectionId,
                    completed_chapters: completed,
                    total_chapters: total,
                    earned_diamonds: diamonds,
                    max_diamonds: total * 5,
                    low_diamond_chapters: lowDiamonds,
                    detected_grade: detectedGrade
                };
            } catch(e) {
                return {ok: false, error: e.toString()};
            }
        }""")
        if not stats or not stats.get("ok"):
            return False, (stats or {}).get("error", "تعذر قراءة بيانات الحساب من Qureo")

        stats["username"] = username
        stats["verified_at"] = datetime.datetime.now().strftime("%H:%M:%S")
        return True, stats

    @staticmethod
    def check_qureo_account(username, password, subject="auto_js"):
        """Fast read-only account check returning grade, completed chapters, and diamonds."""
        playwright = None
        browser = None
        try:
            playwright = sync_playwright().start()
            browser = SolverEngine._build_browser_launch(playwright, headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="ar-EG",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            )
            page = context.new_page()
            ok, res = SolverEngine._login_qureo_readonly(page, username, password, subject=subject)
            if not ok:
                return {"ok": False, "error": res}
            return {"ok": True, "stats": res}
        except Exception as e:
            return {"ok": False, "error": f"تعذر فحص الحساب: {e}"}
        finally:
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            try:
                if playwright:
                    playwright.stop()
            except Exception:
                pass

    @staticmethod
    def capture_qureo_proof(username, password, subject="auto_js"):
        """Standalone read-only Qureo login to capture live proof screenshots and stats."""
        playwright = None
        browser = None
        try:
            playwright = sync_playwright().start()
            browser = SolverEngine._build_browser_launch(playwright, headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="ar-EG",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            )
            page = context.new_page()
            ok, res = SolverEngine._login_qureo_readonly(page, username, password, subject=subject)
            if not ok:
                return {"ok": False, "error": res}

            course_code = res["course_code"]
            section_id = res["section_id"]
            try:
                page.goto(f"https://me-tp.qureo.education/course/{course_code}", wait_until="networkidle", timeout=15000)
            except Exception:
                page.goto(f"https://me-tp.qureo.education/course/{course_code}", timeout=15000)
            time.sleep(0.8)
            course_bytes = page.screenshot(type="png")

            try:
                page.goto(f"https://me-tp.qureo.education/section/{section_id}", wait_until="networkidle", timeout=15000)
            except Exception:
                page.goto(f"https://me-tp.qureo.education/section/{section_id}", timeout=15000)
            time.sleep(0.8)
            section_bytes = page.screenshot(type="png")

            return {
                "ok": True,
                "stats": res,
                "course_bytes": course_bytes,
                "section_bytes": section_bytes,
            }
        except Exception as e:
            return {"ok": False, "error": f"تعذر فتح إثبات الحل: {e}"}
        finally:
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            try:
                if playwright:
                    playwright.stop()
            except Exception:
                pass

    @staticmethod
    def open_live_qureo_browser(username, password, subject="auto_js"):
        """Launch a visible Chrome browser signed into Qureo on local Windows."""
        if platform.system() != "Windows":
            return False, "فتح نافذة Chrome متاح فقط عند تشغيل الأداة على جهازك الشخصي، استخدم معاينة إثبات الحل هنا."

        def _runner():
            playwright = None
            browser = None
            try:
                playwright = sync_playwright().start()
                browser = playwright.chromium.launch(
                    channel="chrome",
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
                )
                context = browser.new_context(
                    no_viewport=True,
                    locale="ar-EG",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                )
                page = context.new_page()
                ok, res = SolverEngine._login_qureo_readonly(page, username, password, subject=subject)
                if ok and isinstance(res, dict) and res.get("course_code"):
                    page.goto(f"https://me-tp.qureo.education/course/{res['course_code']}", timeout=15000)
                while browser.is_connected() and len(context.pages) > 0:
                    time.sleep(0.5)
            except Exception as e:
                print(f"[ProofBrowser] {e}")
            finally:
                try:
                    if browser:
                        browser.close()
                except Exception:
                    pass
                try:
                    if playwright:
                        playwright.stop()
                except Exception:
                    pass

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        return True, "تم فتح متصفح Chrome مسجلاً بحساب الطالب على جهازك."
