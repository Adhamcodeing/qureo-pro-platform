document.addEventListener("DOMContentLoaded", () => {
    const SUBJECT_NAMES = {
        auto_js: "🤖 جافا ذكي تلقائي",
        python2: "🐍 بايثون (25)",
        java1: "☕ جافا أولى (42)",
        java2: "⚡ جافا تانية (54)",
    };

    const STATUS_AR = {
        running: "قيد الحل الآن",
        queued: "في الانتظار",
        done: "مكتمل ✓",
        error: "خطأ ⚠️",
        stopped: "متوقف",
    };

    // State
    let activeTab = "single";
    let selectedSubject = "auto_js";
    let selectedMode = "full";
    let activeBoardTab = "waiting";
    let selectedLogJobId = null;
    let lastLogCount = 0;
    let isPollingLogs = false;
    let previewOpen = false;
    let lastScreenshotJob = null;

    // Elements
    const tabSingle = document.getElementById("tabSingle");
    const tabBulk = document.getElementById("tabBulk");
    const panelSingle = document.getElementById("panelSingle");
    const panelBulk = document.getElementById("panelBulk");

    const singleLabel = document.getElementById("singleLabel");
    const usernameInput = document.getElementById("username");
    const passwordInput = document.getElementById("password");
    const btnTogglePw = document.getElementById("btnTogglePw");

    const bulkRowsBody = document.getElementById("bulkRowsBody");
    const btnAddRow = document.getElementById("btnAddRow");
    const btnClearRows = document.getElementById("btnClearRows");
    const btnTogglePaste = document.getElementById("btnTogglePaste");
    const smartPasteDrawer = document.getElementById("smartPasteDrawer");
    const bulkPasteText = document.getElementById("bulkPasteText");
    const btnSmartParse = document.getElementById("btnSmartParse");

    const subjectGrid = document.getElementById("subjectGrid");
    const modePills = document.querySelectorAll(".mode-pill");
    const rangeInputsBox = document.getElementById("rangeInputsBox");
    const singleChapterBox = document.getElementById("singleChapterBox");
    const chapterFromInput = document.getElementById("chapterFromInput");
    const chapterToInput = document.getElementById("chapterToInput");
    const chapterNumInput = document.getElementById("chapterNumInput");

    const headlessCheck = document.getElementById("headlessCheck");
    const queueForm = document.getElementById("queueForm");
    const btnAddQueue = document.getElementById("btnAddQueue");
    const btnAddLabel = document.getElementById("btnAddLabel");
    const queueControlRow = document.getElementById("queueControlRow");
    const btnSkipCurrent = document.getElementById("btnSkipCurrent");
    const btnStopAll = document.getElementById("btnStopAll");
    const formToast = document.getElementById("formToast");

    const hdrActivePill = document.getElementById("hdrActivePill");
    const hdrActiveDot = document.getElementById("hdrActiveDot");
    const hdrActiveName = document.getElementById("hdrActiveName");
    const hdrQueuedCount = document.getElementById("hdrQueuedCount");
    const hdrDoneCount = document.getElementById("hdrDoneCount");

    const activeHeroCard = document.getElementById("activeHeroCard");
    const heroStateBadge = document.getElementById("heroStateBadge");
    const heroTitle = document.getElementById("heroTitle");
    const heroSub = document.getElementById("heroSub");
    const heroTimer = document.getElementById("heroTimer");
    const heroStageText = document.getElementById("heroStageText");
    const heroProgressCount = document.getElementById("heroProgressCount");
    const heroProgressBar = document.getElementById("heroProgressBar");

    const boardTabWaiting = document.getElementById("boardTabWaiting");
    const boardTabFinished = document.getElementById("boardTabFinished");
    const waitingBadge = document.getElementById("waitingBadge");
    const finishedBadge = document.getElementById("finishedBadge");
    const btnClearFinished = document.getElementById("btnClearFinished");
    const queuedList = document.getElementById("queuedList");
    const finishedList = document.getElementById("finishedList");

    const terminalJobTitle = document.getElementById("terminalJobTitle");
    const terminalLog = document.getElementById("terminalLog");
    const btnClearLogs = document.getElementById("btnClearLogs");
    const btnTogglePreview = document.getElementById("btnTogglePreview");
    const previewDrawer = document.getElementById("previewDrawer");
    const livePreviewImg = document.getElementById("livePreviewImg");
    const previewEmpty = document.getElementById("previewEmpty");

    // -----------------------------------------
    // Helpers & Row Builder
    // -----------------------------------------
    function showToast(msg, ok = true) {
        formToast.textContent = msg;
        formToast.className = `toast-msg ${ok ? "ok" : "err"}`;
        formToast.classList.remove("hidden");
        setTimeout(() => formToast.classList.add("hidden"), 4500);
    }

    function escapeHtml(str) {
        return String(str || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function createBulkRow(data = {}, focusField = false) {
        const tr = document.createElement("tr");
        const subj = data.subject || selectedSubject;
        tr.innerHTML = `
            <td class="row-num"></td>
            <td><input type="text" class="b-label" placeholder="مثال: أحمد" value="${escapeHtml(data.label || "")}"></td>
            <td><input type="text" class="b-user" placeholder="كود الطالب" dir="ltr" value="${escapeHtml(data.username || "")}"></td>
            <td><input type="text" class="b-pass" placeholder="كلمة المرور" dir="ltr" value="${escapeHtml(data.password || "")}"></td>
            <td>
                <select class="b-subj">
                    <option value="auto_js" ${subj === "auto_js" ? "selected" : ""}>جافا ذكي</option>
                    <option value="python2" ${subj === "python2" ? "selected" : ""}>بايثون (2ث)</option>
                    <option value="java1" ${subj === "java1" ? "selected" : ""}>أولى (42)</option>
                    <option value="java2" ${subj === "java2" ? "selected" : ""}>تانية (54)</option>
                </select>
            </td>
            <td><button type="button" class="row-del-btn" title="حذف الصف">✕</button></td>
        `;

        tr.querySelector(".row-del-btn").addEventListener("click", () => {
            if (bulkRowsBody.children.length > 1) {
                tr.remove();
            } else {
                tr.querySelectorAll("input").forEach(inp => inp.value = "");
            }
            renumberBulkRows();
            updateSubmitButtonLabel();
        });

        tr.querySelectorAll("input").forEach(inp => {
            inp.addEventListener("input", updateSubmitButtonLabel);
            inp.addEventListener("keydown", (ev) => {
                if (ev.key === "Enter") {
                    ev.preventDefault();
                    if (tr === bulkRowsBody.lastElementChild) {
                        createBulkRow({}, true);
                    } else {
                        const nextRow = tr.nextElementSibling;
                        nextRow?.querySelector(".b-label")?.focus();
                    }
                }
            });
        });

        bulkRowsBody.appendChild(tr);
        renumberBulkRows();
        updateSubmitButtonLabel();
        if (focusField) {
            tr.querySelector(".b-label")?.focus();
        }
    }

    function renumberBulkRows() {
        [...bulkRowsBody.children].forEach((tr, idx) => {
            const cell = tr.querySelector(".row-num");
            if (cell) cell.textContent = idx + 1;
        });
    }

    function collectBulkRows() {
        const items = [];
        [...bulkRowsBody.children].forEach(tr => {
            const label = tr.querySelector(".b-label")?.value.trim() || "";
            const username = tr.querySelector(".b-user")?.value.trim() || "";
            const password = tr.querySelector(".b-pass")?.value.trim() || "";
            const subject = tr.querySelector(".b-subj")?.value || selectedSubject;
            if (username && password) {
                items.push({ label, username, password, subject });
            }
        });
        return items;
    }

    function updateSubmitButtonLabel() {
        if (activeTab === "single") {
            btnAddLabel.textContent = "أضف الطالب للطابور وابدأ";
        } else {
            const validCount = collectBulkRows().length;
            btnAddLabel.textContent = validCount > 0
                ? `أضف (${validCount}) طلاب للطابور وابدأ`
                : "أضف الطلاب للطابور وابدأ";
        }
    }

    // Seed initial 2 clean empty rows for bulk mode
    createBulkRow();
    createBulkRow();

    // -----------------------------------------
    // UI Events
    // -----------------------------------------
    function switchEntryTab(tab) {
        activeTab = tab;
        tabSingle.classList.toggle("active", tab === "single");
        tabBulk.classList.toggle("active", tab === "bulk");
        panelSingle.classList.toggle("hidden", tab !== "single");
        panelBulk.classList.toggle("hidden", tab !== "bulk");
        updateSubmitButtonLabel();
    }

    tabSingle.addEventListener("click", () => switchEntryTab("single"));
    tabBulk.addEventListener("click", () => switchEntryTab("bulk"));

    btnTogglePw.addEventListener("click", () => {
        const isPw = passwordInput.type === "password";
        passwordInput.type = isPw ? "text" : "password";
    });

    btnAddRow.addEventListener("click", () => createBulkRow({}, true));
    btnClearRows.addEventListener("click", () => {
        bulkRowsBody.innerHTML = "";
        createBulkRow({}, true);
    });

    btnTogglePaste.addEventListener("click", () => {
        smartPasteDrawer.classList.toggle("hidden");
        if (!smartPasteDrawer.classList.contains("hidden")) {
            bulkPasteText.focus();
        }
    });

    btnSmartParse.addEventListener("click", async () => {
        const rawText = bulkPasteText.value.trim();
        if (!rawText) {
            showToast("الصق أسطر الطلاب أولاً ثم اضغط تفريغ.", false);
            return;
        }
        try {
            const res = await fetch("/api/queue/parse", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ raw_text: rawText, subject: selectedSubject }),
            });
            const data = await res.json();
            if (!data.items || data.items.length === 0) {
                showToast("لم أتمكن من استخراج كود وباسورد صالحين من النص.", false);
                return;
            }
            // Remove completely empty rows before appending parsed students
            [...bulkRowsBody.children].forEach(tr => {
                const u = tr.querySelector(".b-user")?.value.trim();
                const p = tr.querySelector(".b-pass")?.value.trim();
                const l = tr.querySelector(".b-label")?.value.trim();
                if (!u && !p && !l) tr.remove();
            });
            data.items.forEach(item => createBulkRow(item));
            bulkPasteText.value = "";
            smartPasteDrawer.classList.add("hidden");
            showToast(`تم تفريغ ${data.items.length} طالب بنجاح داخل الجدول! راجعهم واضغط إضافة.`);
        } catch (e) {
            showToast("تعذر الاتصال بالسيرفر لتحليل النص.", false);
        }
    });

    // Subject card selector
    subjectGrid.querySelectorAll(".subject-card").forEach(card => {
        card.addEventListener("click", () => {
            subjectGrid.querySelectorAll(".subject-card").forEach(c => c.classList.remove("selected"));
            card.classList.add("selected");
            selectedSubject = card.dataset.subject;
            // Suggest sensible default chapter_to when switching tracks
            if (selectedSubject === "python2") {
                if (Number(chapterToInput.value) > 25) chapterToInput.value = 25;
            } else if (selectedSubject === "java1") {
                if (Number(chapterToInput.value) === 54 || Number(chapterToInput.value) === 25) chapterToInput.value = 42;
            } else if (selectedSubject === "java2") {
                if (Number(chapterToInput.value) === 42 || Number(chapterToInput.value) === 25) chapterToInput.value = 54;
            }
        });
    });

    // Mode pills selector
    modePills.forEach(pill => {
        pill.addEventListener("click", () => {
            modePills.forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            pill.querySelector("input").checked = true;
            selectedMode = pill.dataset.mode;
            rangeInputsBox.classList.toggle("hidden", selectedMode !== "range");
            singleChapterBox.classList.toggle("hidden", selectedMode !== "single");
        });
    });

    // Board tabs
    boardTabWaiting.addEventListener("click", () => {
        activeBoardTab = "waiting";
        boardTabWaiting.classList.add("active");
        boardTabFinished.classList.remove("active");
        queuedList.classList.remove("hidden");
        finishedList.classList.add("hidden");
    });
    boardTabFinished.addEventListener("click", () => {
        activeBoardTab = "finished";
        boardTabFinished.classList.add("active");
        boardTabWaiting.classList.remove("active");
        finishedList.classList.remove("hidden");
        queuedList.classList.add("hidden");
    });

    btnClearFinished.addEventListener("click", async () => {
        await fetch("/api/queue/clear", { method: "POST" });
        fetchQueueState();
    });

    btnSkipCurrent.addEventListener("click", async () => {
        const res = await fetch("/api/queue/skip", { method: "POST" });
        const data = await res.json();
        showToast(data.message || "تم طلب التخطي", data.ok);
        fetchQueueState();
    });

    btnStopAll.addEventListener("click", async () => {
        const res = await fetch("/api/queue/stop", { method: "POST" });
        const data = await res.json();
        showToast(data.message || "تم طلب إيقاف الطابور", data.ok);
        fetchQueueState();
    });

    btnClearLogs.addEventListener("click", () => {
        terminalLog.innerHTML = `<div class="log-line muted">تم مسح شاشة السجل محلياً...</div>`;
    });

    btnTogglePreview.addEventListener("click", () => {
        previewOpen = !previewOpen;
        previewDrawer.classList.toggle("hidden", !previewOpen);
        btnTogglePreview.textContent = previewOpen ? "🙈 إخفاء المعاينة" : "🖥️ معاينة المتصفح";
        if (previewOpen) refreshPreviewImage();
    });

    // -----------------------------------------
    // Submit Form -> Add Single or Bulk Table
    // -----------------------------------------
    queueForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const headless = headlessCheck.checked;
        const targetChapter = selectedMode === "single" && chapterNumInput.value
            ? Number(chapterNumInput.value) : null;
        const chapterFrom = selectedMode === "range" && chapterFromInput.value
            ? Number(chapterFromInput.value) : null;
        const chapterTo = selectedMode === "range" && chapterToInput.value
            ? Number(chapterToInput.value) : null;

        btnAddQueue.disabled = true;
        try {
            if (activeTab === "single") {
                const payload = {
                    label: singleLabel.value.trim(),
                    username: usernameInput.value.trim(),
                    password: passwordInput.value.trim(),
                    subject: selectedSubject,
                    headless,
                    mode: selectedMode,
                    target_chapter: targetChapter,
                    chapter_from: chapterFrom,
                    chapter_to: chapterTo,
                };
                const res = await fetch("/api/queue/add", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    showToast(data.error || "تعذر إضافة الطالب", false);
                } else {
                    showToast(data.message, true);
                    singleLabel.value = "";
                    usernameInput.value = "";
                    passwordInput.value = "";
                    selectedLogJobId = data.job?.id || null;
                    lastLogCount = 0;
                    terminalLog.innerHTML = "";
                }
            } else {
                const items = collectBulkRows();
                if (!items.length) {
                    showToast("أضف صفاً واحداً على الأقل بكود طالب وكلمة مرور.", false);
                    return;
                }
                const payload = {
                    items,
                    subject: selectedSubject,
                    headless,
                    mode: selectedMode,
                    target_chapter: targetChapter,
                    chapter_from: chapterFrom,
                    chapter_to: chapterTo,
                };
                const res = await fetch("/api/queue/bulk", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    showToast(data.error || "تعذر إضافة القائمة", false);
                } else {
                    showToast(data.message, true);
                    bulkRowsBody.innerHTML = "";
                    createBulkRow();
                    createBulkRow();
                    if (data.jobs && data.jobs.length) {
                        selectedLogJobId = data.jobs[0].id;
                        lastLogCount = 0;
                        terminalLog.innerHTML = "";
                    }
                }
            }
            await fetchQueueState();
        } catch (err) {
            showToast("حدث خطأ في الاتصال بالسيرفر المحلي.", false);
        } finally {
            btnAddQueue.disabled = false;
        }
    });

    // -----------------------------------------
    // Live Rendering & Polling
    // -----------------------------------------
    function formatModeChip(job) {
        if (job.mode === "single") {
            return job.target_chapter ? `فصل ${job.target_chapter}` : "فصل واحد";
        }
        if (job.mode === "range") {
            return `من ${job.chapter_from || 1} إلى ${job.chapter_to || "الكل"}`;
        }
        return "المنهج بالكامل";
    }

    function renderActiveHero(active, snapshot) {
        if (active) {
            activeHeroCard.classList.add("is-running");
            hdrActivePill.classList.add("running");
            hdrActiveDot.classList.remove("idle");
            hdrActiveName.textContent = active.display_name;

            heroStateBadge.className = "hero-state-badge running";
            heroStateBadge.textContent = "جاري الحل بالمتصفح الآن";
            heroTitle.textContent = `${active.display_name}`;
            heroSub.textContent = `${SUBJECT_NAMES[active.subject] || active.subject_label} • ${formatModeChip(active)}`;
            heroTimer.textContent = active.duration || "00:00";
            heroStageText.textContent = active.current_stage || "جاري التنفيذ...";
            const done = active.progress_done || 0;
            const total = active.progress_total || 0;
            const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 8;
            heroProgressCount.textContent = `${done} / ${total} فصل (${pct}%)`;
            heroProgressBar.style.width = `${pct}%`;
            queueControlRow.classList.remove("hidden");
        } else {
            activeHeroCard.classList.remove("is-running");
            hdrActivePill.classList.remove("running");
            hdrActiveDot.classList.add("idle");
            hdrActiveName.textContent = "جاهز";

            const latest = snapshot.finished && snapshot.finished.length ? snapshot.finished[0] : null;
            if (latest) {
                const stCls = latest.status === "done" ? "done" : latest.status === "error" ? "error" : "";
                heroStateBadge.className = `hero-state-badge ${stCls}`;
                heroStateBadge.textContent = STATUS_AR[latest.status] || latest.status;
                heroTitle.textContent = `آخر جلسة: ${latest.display_name}`;
                heroSub.textContent = `${SUBJECT_NAMES[latest.subject] || latest.subject_label} • ${formatModeChip(latest)}`;
                heroTimer.textContent = latest.duration || "00:00";
                heroStageText.textContent = latest.current_stage || "انتهت الجلسة";
                const done = latest.progress_done || 0;
                const total = latest.progress_total || 0;
                const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : (latest.status === "done" ? 100 : 0);
                heroProgressCount.textContent = `${done} / ${total} فصل (${pct}%)`;
                heroProgressBar.style.width = `${pct}%`;
            } else {
                heroStateBadge.className = "hero-state-badge";
                heroStateBadge.textContent = "متوقف / جاهز";
                heroTitle.textContent = "لا يوجد طالب قيد الحل الآن";
                heroSub.textContent = "أضف طالباً أو مجموعة طلاب (أولى وتانية معاً) وسيتولى المحرك تشغيلهم بالتتابع تلقائياً.";
                heroTimer.textContent = "00:00";
                heroStageText.textContent = "في انتظار أوامر التشغيل...";
                heroProgressCount.textContent = "0 / 0 فصل (0%)";
                heroProgressBar.style.width = "0%";
            }
            queueControlRow.classList.toggle("hidden", (snapshot.counts?.queued || 0) === 0);
        }
    }

    function renderQueueLists(snapshot) {
        const queued = snapshot.queued || [];
        const finished = snapshot.finished || [];

        hdrQueuedCount.textContent = queued.length;
        hdrDoneCount.textContent = finished.filter(j => j.status === "done").length;
        waitingBadge.textContent = queued.length;
        finishedBadge.textContent = finished.length;
        btnClearFinished.classList.toggle("hidden", finished.length === 0);

        if (!queued.length) {
            queuedList.innerHTML = `<div class="board-empty">لا يوجد طلاب في قائمة الانتظار حالياً</div>`;
        } else {
            queuedList.innerHTML = queued.map((j, idx) => `
                <div class="queue-item">
                    <div class="q-main">
                        <div class="q-title-row">
                            <span class="q-pos">#${idx + 1}</span>
                            <span class="q-name">${escapeHtml(j.label || j.username)}</span>
                            <span class="q-code">${escapeHtml(j.username)}</span>
                        </div>
                        <div class="q-pills">
                            <span class="q-chip">${escapeHtml(SUBJECT_NAMES[j.subject] || j.subject_label)}</span>
                            <span class="q-chip">${escapeHtml(formatModeChip(j))}</span>
                        </div>
                    </div>
                    <div class="q-actions">
                        <button type="button" class="q-btn" data-act="top" data-id="${j.id}" title="تقديم للأول">⏫</button>
                        <button type="button" class="q-btn" data-act="up" data-id="${j.id}" title="أعلى">▲</button>
                        <button type="button" class="q-btn" data-act="down" data-id="${j.id}" title="أسفل">▼</button>
                        <button type="button" class="q-btn del" data-act="del" data-id="${j.id}" title="حذف">✕</button>
                    </div>
                </div>
            `).join("");
        }

        if (!finished.length) {
            finishedList.innerHTML = `<div class="board-empty">السجل المنتهي فارغ</div>`;
        } else {
            finishedList.innerHTML = finished.map(j => `
                <div class="queue-item">
                    <div class="q-main">
                        <div class="q-title-row">
                            <span class="q-name">${escapeHtml(j.label || j.username)}</span>
                            <span class="q-code">${escapeHtml(j.username)}</span>
                        </div>
                        <div class="q-pills">
                            <span class="q-chip status-${j.status}">${STATUS_AR[j.status] || j.status}</span>
                            <span class="q-chip">${escapeHtml(SUBJECT_NAMES[j.subject] || j.subject_label)}</span>
                            <span class="q-chip">${j.progress_done}/${j.progress_total} • ${j.duration}</span>
                        </div>
                    </div>
                    <div class="q-actions">
                        <button type="button" class="q-btn" data-act="logs" data-id="${j.id}">👁 السجل</button>
                        <button type="button" class="q-btn" data-act="retry" data-id="${j.id}">🔄 إعادة</button>
                    </div>
                </div>
            `).join("");
        }
    }

    // Delegated click handler for queue actions
    document.addEventListener("click", async (e) => {
        const btn = e.target.closest(".q-btn");
        if (!btn) return;
        const act = btn.dataset.act;
        const id = btn.dataset.id;
        if (!id) return;

        if (act === "top" || act === "up" || act === "down") {
            await fetch(`/api/queue/${id}/move`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ direction: act }),
            });
            fetchQueueState();
        } else if (act === "del") {
            await fetch(`/api/queue/${id}`, { method: "DELETE" });
            fetchQueueState();
        } else if (act === "retry") {
            await fetch(`/api/queue/${id}/retry`, { method: "POST" });
            fetchQueueState();
        } else if (act === "logs") {
            selectedLogJobId = id;
            lastLogCount = 0;
            terminalLog.innerHTML = "";
            pollJobLogs();
        }
    });

    function appendLogs(lines) {
        if (!lines || !lines.length) return;
        const frag = document.createDocumentFragment();
        lines.forEach(entry => {
            const txt = typeof entry === "string" ? entry : (entry?.text || "");
            const tm = typeof entry === "object" && entry?.time ? `[${entry.time}] ` : "";
            const div = document.createElement("div");
            let cls = "log-line";
            if (txt.includes("✓") || txt.includes("🎉") || txt.includes("PERFECT")) cls += " ok";
            else if (txt.includes("❌") || txt.includes("فشل") || txt.includes("خطأ")) cls += " err";
            else if (txt.includes("⚠️") || txt.includes("تخطي")) cls += " warn";
            else if (txt.includes("===") || txt.includes("🔍") || txt.includes("🎯") || txt.includes("🔢")) cls += " head";
            div.className = cls;
            div.textContent = `${tm}${txt}`;
            frag.appendChild(div);
        });
        terminalLog.appendChild(frag);
        terminalLog.scrollTop = terminalLog.scrollHeight;
    }

    async function pollJobLogs() {
        if (isPollingLogs) return;
        isPollingLogs = true;
        try {
            const url = selectedLogJobId
                ? `/api/queue/logs?job_id=${encodeURIComponent(selectedLogJobId)}&since=${lastLogCount}`
                : `/api/queue/logs?since=${lastLogCount}`;
            const res = await fetch(url);
            if (!res.ok) return;
            const data = await res.json();
            if (data.job) {
                terminalJobTitle.textContent = data.job.display_name;
            }
            if (data.logs && data.logs.length) {
                appendLogs(data.logs);
                lastLogCount = data.total_logs;
            }
            if (previewOpen) {
                refreshPreviewImage(data.has_screenshot);
            }
        } finally {
            isPollingLogs = false;
        }
    }

    function refreshPreviewImage(hasShot = true) {
        if (!previewOpen) return;
        const targetId = selectedLogJobId;
        const src = targetId
            ? `/api/queue/${encodeURIComponent(targetId)}/screenshot?t=${Date.now()}`
            : `/api/screenshot?t=${Date.now()}`;
        if (!hasShot && lastScreenshotJob === targetId) return;
        lastScreenshotJob = targetId;
        const loader = new Image();
        loader.onload = () => {
            livePreviewImg.src = loader.src;
            livePreviewImg.classList.remove("hidden");
            previewEmpty.classList.add("hidden");
        };
        loader.onerror = () => {
            livePreviewImg.classList.add("hidden");
            previewEmpty.classList.remove("hidden");
        };
        loader.src = src;
    }

    async function fetchQueueState() {
        try {
            const res = await fetch("/api/queue");
            if (!res.ok) return;
            const snapshot = await res.json();

            renderActiveHero(snapshot.active, snapshot);
            renderQueueLists(snapshot);

            // Auto-follow active job logs if user hasn't pinned an old job
            const desiredJob = snapshot.active?.id || snapshot.default_view_id;
            if (desiredJob && desiredJob !== selectedLogJobId && snapshot.active?.id === desiredJob) {
                selectedLogJobId = desiredJob;
                lastLogCount = 0;
                terminalLog.innerHTML = "";
            } else if (!selectedLogJobId && desiredJob) {
                selectedLogJobId = desiredJob;
                lastLogCount = 0;
            }

            await pollJobLogs();
        } catch (err) {
            // Silent retry on next interval
        }
    }

    fetchQueueState();
    setInterval(fetchQueueState, 1200);
});
