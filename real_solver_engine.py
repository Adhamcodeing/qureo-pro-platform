import datetime
import gc
import random
import threading
import time
from playwright.sync_api import sync_playwright
from solver_engine import SolverEngine


class RealSolverEngine(SolverEngine):
    """
    Independent real-simulation engine:
    Writes actual model answers into every lecture's interactive `try` exercises
    via `/api/study/students/lecture-talks/{talk_id}` before/alongside completing
    lectures and solving chapter tests. Supports re-grading already-completed accounts.
    """

    def run_blocking(
        self,
        username,
        password,
        subject="auto_js",
        headless=True,
        mode="regrade_lectures",
        target_chapter=None,
        chapter_from=None,
        chapter_to=None,
        natural_mode=False,
        realistic_delay=False,
    ):
        self.running = True
        self.stop_requested = False
        self.logs.clear()
        self.state = "running"
        self.start_time = time.time()
        self.end_time = None
        self.progress_done = 0
        self.progress_total = 0
        self._last_chapter_screenshot_time = 0.0
        subj_label = self.SUBJECT_LABELS.get(subject, subject)
        mode_labels = {
            "regrade_lectures": "إعادة تصحيح وملء أكواد الدروس",
            "real_full": "حل حقيقي كامل (دروس + اختبار)",
            "real_range": f"حل حقيقي لنطاق ({chapter_from or 1} إلى {chapter_to or '?'})",
            "real_single": f"حل حقيقي لفصل {target_chapter or 'واحد'}",
        }
        mode_desc = mode_labels.get(mode, mode)
        self.current_stage = "جاري تشغيل محرك الحل الحقيقي..."
        self.log(f"محرك الحل الحقيقي — المادة: {subj_label} • النمط: {mode_desc}")
        if realistic_delay:
            self.log("⏱️ وضع المدة الزمنية الواقعية مفعل (فاصل زمني بشري بين التمارين والدروس).")

        try:
            with sync_playwright() as p:
                browser = self._build_browser_launch(p, headless=headless)
                context = browser.new_context(
                    viewport={"width": 1280, "height": 850},
                    locale="ar-EG",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                )
                context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
                page = context.new_page()

                try:
                    self._solve_qureo_real(
                        page,
                        username,
                        password,
                        subject,
                        mode=mode,
                        target_chapter=target_chapter,
                        chapter_from=chapter_from,
                        chapter_to=chapter_to,
                        natural_mode=natural_mode,
                        realistic_delay=realistic_delay,
                    )
                except Exception as e:
                    self.state = "error"
                    self.current_stage = "حدث خطأ غير متوقع ❌"
                    self.log(f"خطأ أثناء التنفيذ: {str(e)}")
                finally:
                    try:
                        browser.close()
                    except Exception:
                        pass
        except Exception as e:
            self.state = "error"
            self.current_stage = "فشل تشغيل المتصفح ❌"
            self.log(f"خطأ: {str(e)}")

        if self.state == "running":
            self.state = "stopped" if self.stop_requested else "done"
            if self.stop_requested:
                self.current_stage = "تم الإيقاف يدوياً"
        self.end_time = time.time()
        self.running = False

    def _fill_lecture_talks(self, page, ch_id, lectures, default_lang="javascript", realistic_delay=False):
        """
        Process all lectures of a chapter inside a single browser evaluation for maximum speed:
        start each lecture, fetch lecture + student state in parallel, submit all missing
        interactions (`try`, `try_partial`, `try_demo`, `choice_question`), then complete lecture.
        """
        if not lectures:
            return {"ok": True, "written": 0, "already_filled": 0, "exercises": 0, "lec_errors": []}

        res = page.evaluate(
            r"""
            async ({lectures, default_lang, realistic_delay}) => {
                const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                async function parseJsonSafe(r) {
                    try {
                        const t = await r.text();
                        return t && t.trim() ? JSON.parse(t) : null;
                    } catch(e) { return null; }
                }

                function pickSmartChoice(choices) {
                    if (!Array.isArray(choices) || choices.length === 0) return '1';
                    // Prefer choice whose after_talks shows positive feedback
                    for (const c of choices) {
                        const txt = JSON.stringify(c.after_talks || []);
                        if (txt.includes('yattane') || txt.includes('رائع') || txt.includes('صحيح') || txt.includes('ممتاز')) {
                            return String(c.value || '1');
                        }
                    }
                    return String(choices[0].value || '1');
                }

                let totalWritten = 0;
                let totalAlreadyFilled = 0;
                let totalExercises = 0;
                const lecErrors = [];

                for (const lec of lectures) {
                    const lid = lec.id;
                    const lTitle = lec.title || `درس ${lid}`;

                    // 1. Start lecture
                    let startOk = false;
                    for (let a = 1; a <= 5; a++) {
                        const rStart = await fetch(`/api/study/students/lectures/${lid}`, { method: 'PUT' });
                        if (rStart.ok) { startOk = true; break; }
                        const err = (await parseJsonSafe(rStart)) || {};
                        if (rStart.status === 400 && err.already_started) { startOk = true; break; }
                        if (rStart.status === 400 && err.prev_chapter_not_completed) {
                            return { ok: false, needPrevChapter: true, written: totalWritten, already_filled: totalAlreadyFilled, exercises: totalExercises, error: `الفصل السابق غير مكتمل في ${lTitle}` };
                        }
                        if (rStart.status === 403) break;
                        await sleep(150 * a);
                    }
                    if (!startOk) {
                        lecErrors.push(lTitle);
                        continue;
                    }

                    // 2. Fetch lecture definition & student state in parallel
                    const [lecRes, stLecRes] = await Promise.all([
                        fetch(`/api/study/lectures/${lid}`),
                        fetch(`/api/study/students/lectures/${lid}`).catch(() => null)
                    ]);
                    if (!lecRes.ok) {
                        lecErrors.push(lTitle);
                        continue;
                    }
                    const lecData = (await lecRes.json()) || {};
                    const talks = Array.isArray(lecData.talks) ? lecData.talks : [];

                    let existingMap = {};
                    if (stLecRes && stLecRes.ok) {
                        try {
                            const stLecData = (await stLecRes.json()) || {};
                            for (const st of (stLecData.talks || [])) {
                                if (st && st.value) existingMap[st.talk_id] = st.value;
                            }
                        } catch(e) {}
                    }

                    const pendingPayloads = [];
                    for (const talk of talks) {
                        if (!talk) continue;
                        let payload = null;
                        let isAlreadySame = false;
                        const prevVal = existingMap[talk.id] || {};

                        if (talk.type === 'choice_question') {
                            const choices = (talk.body && Array.isArray(talk.body.choices)) ? talk.body.choices : [];
                            if (choices.length === 0) continue;
                            const valStr = pickSmartChoice(choices);
                            totalExercises++;
                            if (prevVal.choice_question && String(prevVal.choice_question.value) === valStr) {
                                isAlreadySame = true;
                            } else {
                                payload = { value: { choice_question: { value: valStr } } };
                            }
                        } else if (talk.type === 'try') {
                            const body = talk.body || {};
                            const codes = Array.isArray(body.codes) ? body.codes : [];
                            if (codes.length === 0) continue;
                            const editableCode = codes.find(c => c && c.editable !== false) || codes[0];
                            const lang = (editableCode && editableCode.lang) || default_lang || 'javascript';
                            const edType = body.editor_type || '';
                            const placeholders = (editableCode && Array.isArray(editableCode.placeholders)) ? editableCode.placeholders : [];

                            if (edType === 'demo') {
                                totalExercises++;
                                if (prevVal.try_demo) isAlreadySame = true;
                                else payload = { value: { try_demo: { answer: '', lang: String(lang) } } };
                            } else if (edType === 'part' || placeholders.length > 0) {
                                const ansArr = placeholders
                                    .filter(ph => ph && ph.name)
                                    .map(ph => ({
                                        code: String(ph.model_answer || ph.alternative_code || ''),
                                        name: String(ph.name)
                                    }));
                                if (ansArr.length === 0) continue;
                                totalExercises++;
                                const prevPartial = prevVal.try_partial && Array.isArray(prevVal.try_partial.answers) ? prevVal.try_partial.answers : null;
                                if (prevPartial && prevPartial.length === ansArr.length && prevPartial.every((a, i) => a.name === ansArr[i].name && String(a.code || '').trim() === ansArr[i].code.trim())) {
                                    isAlreadySame = true;
                                } else {
                                    payload = { value: { try_partial: { answers: ansArr, lang: String(lang) } } };
                                }
                            } else {
                                const answerText = (editableCode && (editableCode.model_answer || editableCode.code)) || '';
                                if (!String(answerText).trim()) continue;
                                totalExercises++;
                                if (prevVal.try && String(prevVal.try.answer || '').trim() === String(answerText).trim()) {
                                    isAlreadySame = true;
                                } else {
                                    payload = { value: { try: { answer: String(answerText), lang: String(lang) } } };
                                }
                            }
                        } else {
                            continue;
                        }

                        if (isAlreadySame) totalAlreadyFilled++;
                        else if (payload) pendingPayloads.push({ talkId: talk.id, payload });
                    }

                    // 3. Submit pending talks (parallel in fast mode, sequential with delay in realistic mode)
                    async function sendOne(item) {
                        for (let a = 1; a <= 4; a++) {
                            const r = await fetch(`/api/study/students/lecture-talks/${item.talkId}`, {
                                method: 'PUT',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(item.payload)
                            });
                            if (r.ok) return true;
                            await sleep(150 * a);
                        }
                        return false;
                    }

                    if (pendingPayloads.length > 0) {
                        if (realistic_delay) {
                            for (const item of pendingPayloads) {
                                await sleep(800 + Math.floor(Math.random() * 900));
                                if (await sendOne(item)) totalWritten++;
                            }
                        } else {
                            const results = await Promise.all(pendingPayloads.map(sendOne));
                            for (const ok of results) if (ok) totalWritten++;
                        }
                    }

                    // 4. Complete lecture
                    for (let a = 1; a <= 4; a++) {
                        const rComp = await fetch(`/api/study/students/lectures/${lid}/complete`, { method: 'PUT' });
                        if (rComp.ok) break;
                        const err = (await parseJsonSafe(rComp)) || {};
                        if (rComp.status === 400 && err.already_completed) break;
                        if (rComp.status === 400 && err.lecture_not_started) {
                            await fetch(`/api/study/students/lectures/${lid}`, { method: 'PUT' });
                            await sleep(100);
                            continue;
                        }
                        await sleep(150 * a);
                    }

                    if (realistic_delay) {
                        await sleep(600 + Math.floor(Math.random() * 700));
                    }
                }

                return {
                    ok: lecErrors.length === 0 || totalExercises > 0,
                    written: totalWritten,
                    already_filled: totalAlreadyFilled,
                    exercises: totalExercises,
                    lec_errors: lecErrors
                };
            }
            """,
            {"lectures": lectures, "default_lang": default_lang, "realistic_delay": bool(realistic_delay)},
        )
        return res if isinstance(res, dict) else {"ok": False, "written": 0, "already_filled": 0, "exercises": 0, "lec_errors": ["unknown"]}

    def _solve_qureo_real(
        self,
        page,
        username,
        password,
        subject,
        mode="regrade_lectures",
        target_chapter=None,
        chapter_from=None,
        chapter_to=None,
        natural_mode=False,
        realistic_delay=False,
    ):
        login_url = "https://me-portal.qureo.education/login"
        self.log(f"فتح منصة Qureo: {login_url}")

        goto_status = "?"
        try:
            resp = page.goto(login_url, timeout=45000, wait_until="domcontentloaded")
            goto_status = resp.status if resp else "?"
        except Exception as nav_err:
            self.log(f"⚠️ تحذير عند فتح الرابط: {str(nav_err)[:100]}")
            try:
                resp = page.goto(login_url, timeout=45000, wait_until="commit")
                goto_status = resp.status if resp else "?"
            except Exception as nav_err2:
                self._take_screenshot(page)
                self.state = "error"
                self.current_stage = "فشل الاتصال بالمنصة ❌"
                self.log(f"❌ تعذر الاتصال بـ Qureo من السيرفر: {str(nav_err2)[:160]}")
                return

        login_success = False
        try:
            # Wait up to 35s for either Learning Login portal button or login form (cloud-safe)
            page.wait_for_selector(
                ".portal-selection-button-secondary, button:has-text('Learning Login'), #student_id, input[type=text]",
                timeout=35000,
            )
            self._take_screenshot(page)

            sec_btn = page.query_selector(".portal-selection-button-secondary, button:has-text('Learning Login')")
            if sec_btn and sec_btn.is_visible():
                sec_btn.click()
                time.sleep(0.8)

            page.wait_for_selector("#student_id, input[type=text]", timeout=25000)
            page.fill("#student_id, input[type=text]", username)
            page.fill("#password, input[type=password]", password)
            btn = page.query_selector("button[type=submit], button.login-button, button:has-text('Login'), button:has-text('دخول')")
            if btn:
                btn.click()
            else:
                page.press("#password", "Enter")

            self.log(f"تم إرسال بيانات الدخول للطالب {username}...")
            time.sleep(1.5)

            deadline = time.time() + 28
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
                        self.log(f"❌ فشل تسجيل الدخول: {err_text}")
                        return
                if page.query_selector(".course-card"):
                    portal_cards_found = True
                    break
                time.sleep(0.4)

            if portal_cards_found and "me-tp.qureo.education" not in page.url:
                want_python = subject == "python2"
                card_sel = ".course-card.python, .course-card:has-text('Python')" if want_python else ".course-card.purple, .course-card:has-text('JavaScript')"
                card_el = page.query_selector(card_sel)
                if not card_el:
                    self.state = "error"
                    self.current_stage = "المسار غير متاح ❌"
                    self.log("❌ لم يتم العثور على بطاقة المسار المطلوب.")
                    return
                card_el.click()
                page.wait_for_url("**me-tp.qureo.education/**", timeout=20000)
            elif "me-tp.qureo.education" not in page.url:
                page.wait_for_url("**/course/**", timeout=15000)

            login_success = True
            self.log("تم تسجيل الدخول بنجاح.")
        except Exception as e:
            self._take_screenshot(page)
            self.state = "error"
            self.current_stage = "فشل تسجيل الدخول ❌"
            diag_url = "?"
            diag_title = "?"
            diag_body = ""
            try:
                diag_url = page.url
                diag_title = page.title() or ""
                diag_body = (page.inner_text("body") or "").strip().replace("\n", " ")[:180]
            except Exception:
                pass
            self.log(f"❌ تعذر فتح حساب الطالب: {str(e)[:120]}")
            self.log(f"🔎 تشخيص مباشر — HTTP: {goto_status} | URL: {diag_url} | Title: {diag_title}")
            if diag_body:
                self.log(f"📄 نص الصفحة الظاهر: {diag_body}")
            else:
                self.log("📄 الصفحة فارغة تماماً (قد يكون السيرفر السحابي محجوباً من Qureo/WAF أو بطيئاً جداً).")
            return

        if not login_success:
            return

        time.sleep(0.3)
        self._take_screenshot(page)

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
                        courseCode,
                        sectionId,
                        chapters: secRes.chapters || [],
                        completedIds: completed.map(c => c.chapter_id),
                        diamondsMap
                    };
                } catch(e) { return null; }
            }
        """)

        if not course_data or not course_data.get("chapters"):
            self.state = "error"
            self.current_stage = "فشل قراءة الفصول ❌"
            self.log("❌ تعذر قراءة بيانات فصول المنهج.")
            return

        chapters_list = course_data["chapters"]
        completed_set = set(course_data.get("completedIds", []))
        diamonds_map = {int(k): int(v) for k, v in (course_data.get("diamondsMap") or {}).items()}
        total_chapters = len(chapters_list)
        section_id = course_data["sectionId"]
        course_code = course_data["courseCode"]
        default_lang = "python" if "python" in course_code.lower() else "javascript"
        active_bank, _ = self.resolve_active_bank(subject, course_code, total_chapters)

        chapters_to_process = []
        if mode == "real_single":
            if target_chapter:
                for idx, ch in enumerate(chapters_list, 1):
                    if idx == int(target_chapter) or ch["id"] == int(target_chapter):
                        chapters_to_process.append((idx, ch))
                        break
            if not chapters_to_process and chapters_list:
                chapters_to_process.append((1, chapters_list[0]))
        elif mode == "real_range":
            c_from = max(1, int(chapter_from or 1))
            c_to = min(total_chapters, int(chapter_to or total_chapters))
            if c_from > c_to:
                c_from, c_to = c_to, c_from
            for idx, ch in enumerate(chapters_list, 1):
                if c_from <= idx <= c_to:
                    chapters_to_process.append((idx, ch))
        else:
            # regrade_lectures or real_full
            for idx, ch in enumerate(chapters_list, 1):
                chapters_to_process.append((idx, ch))

        self.progress_total = len(chapters_to_process)
        self.progress_done = 0

        self.log(f"المسار: {course_code} | الفصول المستهدفة: {len(chapters_to_process)} | المكتملة مسبقاً: {len(completed_set)}/{total_chapters}")

        total_codes_written = 0
        total_tests_solved = 0

        for pos, (idx, ch) in enumerate(chapters_to_process, 1):
            if self.stop_requested:
                break

            ch_id = ch["id"]
            title = ch.get("name", f"الفصل {idx}")
            test_type = ch.get("test_type", "review")
            already_done = ch_id in completed_set and diamonds_map.get(ch_id, 0) >= 5

            self.current_stage = f"[{pos}/{len(chapters_to_process)}] الفصل {idx}: كتابة أكواد الدروس..."
            self.log(f"📘 [{idx}/{total_chapters}] {title} — جاري سحب الدروس وكتابة الأكواد التفاعلية...")

            # Fetch chapter lectures
            ch_info = page.evaluate(
                "async (cid) => { const r = await fetch(`/api/study/chapters/${cid}`); return r.ok ? await r.json() : null; }",
                ch_id,
            )
            lectures = (ch_info or {}).get("lectures") or []
            lec_res = self._fill_lecture_talks(
                page,
                ch_id,
                lectures,
                default_lang=default_lang,
                realistic_delay=realistic_delay,
            )

            w = lec_res.get("written", 0)
            af = lec_res.get("already_filled", 0)
            ex = lec_res.get("exercises", 0)
            total_codes_written += w
            self.log(f"   ✍️ الدروس ({len(lectures)}): تم كتابة {w} كود جديد • {af} مكتوب مسبقاً (من إجمالي {ex} تمرين).")

            # Solve test if not already 5/5 (or if in single mode)
            need_test = (not already_done) or (mode == "real_single")
            if need_test:
                self.current_stage = f"[{pos}/{len(chapters_to_process)}] الفصل {idx}: حل الاختبار النهائي..."
                bank_ch = active_bank.get(idx, {})
                bank_questions = bank_ch.get("questions", [])
                allow_imperfect = bool(natural_mode and random.random() < 0.35)
                test_res = self._solve_qureo_chapter(page, ch_id, test_type, bank_questions, allow_imperfect=allow_imperfect)
                if isinstance(test_res, dict) and test_res.get("ok"):
                    total_tests_solved += 1
                    self.log("   ✅ الاختبار النهائي: نجح بنجاح 💎")
                else:
                    err_msg = (test_res or {}).get("error", "خطأ غير معروف")
                    self.log(f"   ⚠️ الاختبار النهائي: {err_msg}")
            else:
                self.log(f"   💎 الاختبار مكتمل مسبقاً (5/5) — تم الحفاظ على الدرجة كاملة.")

            self.progress_done = pos
            if pos % 10 == 0 or pos == len(chapters_to_process):
                self._take_screenshot(page)

        if not self.stop_requested:
            try:
                page.goto(f"https://me-tp.qureo.education/section/{section_id}", timeout=15000)
                time.sleep(1)
                self._take_screenshot(page)
                self.proof_section_bytes = self.screenshot_bytes
            except Exception:
                pass
            self.state = "done"
            self.current_stage = f"اكتمل الحل الحقيقي ✓ ({total_codes_written} كود مكتوب)"
            self.log(f"🎉 اكتمل التنفيذ! إجمالي الأكواد الجديدة المكتوبة في الدروس: {total_codes_written} | الاختبارات المحلولة: {total_tests_solved}.")


class RealQueueJob:
    """Single student job for the Real Solver / Re-grader queue."""

    def __init__(
        self,
        seq,
        username,
        password,
        label="",
        subject="auto_js",
        headless=True,
        mode="regrade_lectures",
        target_chapter=None,
        chapter_from=None,
        chapter_to=None,
        natural_mode=False,
        realistic_delay=False,
    ):
        self.id = f"rjob_{seq}_{int(time.time() * 1000) % 10000}"
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
        self.natural_mode = bool(natural_mode)
        self.realistic_delay = bool(realistic_delay)
        self.status = "queued"
        self.created_at = datetime.datetime.now().strftime("%H:%M:%S")
        self.engine = RealSolverEngine()

    def display_name(self):
        return self.label if self.label else self.username

    def to_summary(self):
        st = self.engine.get_status(since=0)
        stage = "في انتظار الدور..." if self.status == "queued" else st["current_stage"]
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
            "natural_mode": self.natural_mode,
            "realistic_delay": self.realistic_delay,
            "status": self.status,
            "created_at": self.created_at,
            "current_stage": stage,
            "duration": st["duration"],
            "progress_done": st["progress_done"],
            "progress_total": st["progress_total"],
            "total_logs": st["total_logs"],
            "has_screenshot": st["has_screenshot"],
            "has_proof": bool(self.engine.proof_course_bytes or self.engine.proof_section_bytes),
            "proof_stats": self.engine.proof_stats,
        }


class RealQueueManager:
    """Thread-safe sequential FIFO queue dedicated to RealSolverEngine."""

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
                    natural_mode=job.natural_mode,
                    realistic_delay=job.realistic_delay,
                )
            except Exception as e:
                job.engine.state = "error"
                job.engine.current_stage = "خطأ غير متوقع ❌"
                job.engine.log(f"❌ خطأ غير متوقع: {e}")

            with self._lock:
                if job.engine.stop_requested or self._stop_queue_flag:
                    job.status = "stopped"
                elif job.engine.state == "done":
                    job.status = "done"
                else:
                    job.status = "error"
                # Memory hygiene for large batches (50-200+ students)
                if len(self._jobs) > 15:
                    for old_j in self._jobs[:-10]:
                        if old_j.status in ("done", "error", "stopped"):
                            old_j.engine.screenshot_bytes = None
            gc.collect()

    def add_job(self, username, password, label="", subject="auto_js", headless=True,
                mode="regrade_lectures", target_chapter=None, chapter_from=None, chapter_to=None,
                natural_mode=False, realistic_delay=False):
        with self._lock:
            self._seq_counter += 1
            job = RealQueueJob(
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
                natural_mode=natural_mode,
                realistic_delay=realistic_delay,
            )
            self._jobs.append(job)
            self._ensure_worker_locked()
            return job.to_summary()

    def add_bulk(self, items, default_subject="auto_js", default_headless=True, default_mode="regrade_lectures",
                 default_natural_mode=False, default_realistic_delay=False):
        added = []
        with self._lock:
            for item in items:
                u = (item.get("username") or "").strip()
                p = (item.get("password") or "").strip()
                if not u or not p:
                    continue
                self._seq_counter += 1
                job = RealQueueJob(
                    seq=self._seq_counter,
                    username=u,
                    password=p,
                    label=item.get("label", ""),
                    subject=item.get("subject") or default_subject,
                    headless=item.get("headless", default_headless),
                    mode=item.get("mode") or default_mode,
                    target_chapter=item.get("target_chapter"),
                    chapter_from=item.get("chapter_from"),
                    chapter_to=item.get("chapter_to"),
                    natural_mode=item.get("natural_mode", default_natural_mode),
                    realistic_delay=item.get("realistic_delay", default_realistic_delay),
                )
                self._jobs.append(job)
                added.append(job.to_summary())
            if added:
                self._ensure_worker_locked()
        return added

    def get_snapshot(self):
        with self._lock:
            jobs = [j.to_summary() for j in self._jobs]
            running_job = next((j for j in self._jobs if j.status == "running"), None)
            queued_count = sum(1 for j in self._jobs if j.status == "queued")
            done_count = sum(1 for j in self._jobs if j.status == "done")
            error_count = sum(1 for j in self._jobs if j.status == "error")
            active_id = running_job.id if running_job else (self._last_active_id or (self._jobs[-1].id if self._jobs else None))
            return {
                "worker_active": self._worker_active,
                "active_job_id": active_id,
                "counts": {
                    "total": len(self._jobs),
                    "queued": queued_count,
                    "running": 1 if running_job else 0,
                    "done": done_count,
                    "error": error_count,
                },
                "jobs": jobs,
            }

    def get_job(self, job_id):
        with self._lock:
            return next((j for j in self._jobs if j.id == job_id), None)

    def get_job_logs(self, job_id, since=0):
        job = self.get_job(job_id)
        if not job:
            return None
        st = job.engine.get_status(since=since)
        st["job_status"] = job.status
        st["display_name"] = job.display_name()
        return st

    def remove_job(self, job_id):
        with self._lock:
            job = self.get_job(job_id)
            if not job:
                return False, "الوظيفة غير موجودة"
            if job.status == "running":
                job.engine.stop()
                return True, "تم إرسال إشارة الإيقاف للطالب الحالي"
            self._jobs = [j for j in self._jobs if j.id != job_id]
            if self._last_active_id == job_id:
                self._last_active_id = self._jobs[-1].id if self._jobs else None
            return True, "تم حذف الطالب من الطابور"

    def stop_all(self):
        with self._lock:
            self._stop_queue_flag = True
            for job in self._jobs:
                if job.status == "running":
                    job.engine.stop()
                elif job.status == "queued":
                    job.status = "stopped"
        return True

    def clear_finished(self):
        with self._lock:
            self._jobs = [j for j in self._jobs if j.status in ("queued", "running")]
            if self._last_active_id and not any(j.id == self._last_active_id for j in self._jobs):
                self._last_active_id = self._jobs[-1].id if self._jobs else None
        return True

    def retry_failed(self):
        retried = 0
        with self._lock:
            for job in self._jobs:
                if job.status in ("error", "stopped"):
                    job.status = "queued"
                    job.engine.state = "idle"
                    job.engine.current_stage = "في انتظار إعادة المحاولة..."
                    retried += 1
            if retried > 0:
                self._ensure_worker_locked()
        return retried
