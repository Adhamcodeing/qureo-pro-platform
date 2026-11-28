(() => {
    let activeTab = "single";
    let parsedBulkItems = [];
    let selectedJobId = null;
    let lastLogIndex = 0;
    let currentFilter = "all";
    let searchTerm = "";
    let cachedJobs = [];
    let latestProofStats = null;

    const $ = (id) => document.getElementById(id);

    function showToast(msg, isErr = false) {
        const box = $("toastBox");
        const el = document.createElement("div");
        el.textContent = msg;
        el.style.cssText = `padding:10px 16px; margin-top:8px; border-radius:11px; font-weight:700; font-size:0.85rem; color:#fff; background:${isErr ? "#dc2626" : "#059669"}; box-shadow:0 8px 24px rgba(0,0,0,0.4);`;
        box.appendChild(el);
        setTimeout(() => el.remove(), 3200);
    }

    // Tabs
    $("tabSingle").addEventListener("click", () => switchTab("single"));
    $("tabBulk").addEventListener("click", () => switchTab("bulk"));
    function switchTab(tab) {
        activeTab = tab;
        $("tabSingle").classList.toggle("active", tab === "single");
        $("tabBulk").classList.toggle("active", tab === "bulk");
        $("singlePanel").style.display = tab === "single" ? "block" : "none";
        $("bulkPanel").style.display = tab === "bulk" ? "block" : "none";
    }

    // Live line counter for massive bulk paste
    $("smartPasteInput").addEventListener("input", () => {
        const lines = $("smartPasteInput").value.split(/\r?\n/).filter((l) => l.trim().length > 0);
        $("liveLineCount").textContent = `${lines.length} سطر`;
    });

    // Mode cards
    $("modeCards").querySelectorAll(".mode-card").forEach((btn) => {
        btn.addEventListener("click", () => {
            $("modeCards").querySelectorAll(".mode-card").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            const m = btn.dataset.mode;
            $("modeSelect").value = m;
            $("rangeInputs").style.display = m === "real_range" ? "grid" : "none";
            $("singleChapterInputWrap").style.display = m === "real_single" ? "flex" : "none";
        });
    });

    // Queue filters & search
    $("queueFilters").querySelectorAll(".filter-pill").forEach((pill) => {
        pill.addEventListener("click", () => {
            $("queueFilters").querySelectorAll(".filter-pill").forEach((p) => p.classList.remove("active"));
            pill.classList.add("active");
            currentFilter = pill.dataset.filter;
            renderQueueList();
        });
    });
    $("queueSearch").addEventListener("input", (e) => {
        searchTerm = (e.target.value || "").trim().toLowerCase();
        renderQueueList();
    });

    // Bulk parser
    $("parseBulkBtn").addEventListener("click", async () => {
        const raw_text = $("smartPasteInput").value.trim();
        const subject = $("bulkSubjectSelect").value;
        if (!raw_text) return showToast("الصق قائمة الطلاب أولاً", true);
        try {
            const r = await fetch("/api/queue/parse", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ raw_text, subject }),
            });
            const data = await r.json();
            if (!data.ok) return showToast(data.error || "فشل التحليل", true);
            parsedBulkItems = data.items || [];
            const box = $("parsedPreview");
            box.style.display = "block";
            box.innerHTML = `✅ تم التعرف بنجاح على <strong>${parsedBulkItems.length}</strong> طالب صالح وجاهز للإضافة للطابور.`;
        } catch (e) {
            showToast("تعذر الاتصال بالسيرفر", true);
        }
    });

    // Submit Form
    $("realQueueForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        const mode = $("modeSelect").value;
        const headless = $("headlessCheck").checked;
        const natural_mode = $("naturalModeCheck").checked;
        const realistic_delay = $("realisticDelayCheck").checked;
        const target_chapter = parseInt($("targetChapterInput").value || "1", 10);
        const chapter_from = parseInt($("chapterFromInput").value || "1", 10);
        const chapter_to = parseInt($("chapterToInput").value || "5", 10);

        if (activeTab === "single") {
            const username = $("usernameInput").value.trim();
            const password = $("passwordInput").value.trim();
            const label = $("labelInput").value.trim();
            const subject = $("subjectSelect").value;
            if (!username || !password) return showToast("يرجى إدخال كود الطالب وكلمة المرور", true);

            const r = await fetch("/api/real-queue/add", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    username, password, label, subject, headless, mode,
                    target_chapter, chapter_from, chapter_to, natural_mode, realistic_delay,
                }),
            });
            const data = await r.json();
            if (!data.ok) return showToast(data.error || "حدث خطأ", true);
            showToast(data.message);
            selectedJobId = data.job.id;
            lastLogIndex = 0;
            $("logBox").innerHTML = "";
            refreshQueue();
        } else {
            const subject = $("bulkSubjectSelect").value;
            let items = parsedBulkItems;
            if (!items.length && $("smartPasteInput").value.trim()) {
                const pr = await fetch("/api/queue/parse", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ raw_text: $("smartPasteInput").value.trim(), subject }),
                });
                const pd = await pr.json();
                items = pd.items || [];
            }
            if (!items.length) return showToast("لم يتم العثور على طلاب صالحين في القائمة", true);

            const enriched = items.map((it) => ({
                ...it,
                mode,
                target_chapter,
                chapter_from,
                chapter_to,
                natural_mode,
                realistic_delay,
            }));
            const r = await fetch("/api/real-queue/bulk", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    items: enriched,
                    subject,
                    headless,
                    mode,
                    natural_mode,
                    realistic_delay,
                }),
            });
            const data = await r.json();
            if (!data.ok) return showToast(data.error || "حدث خطأ", true);
            showToast(data.message);
            parsedBulkItems = [];
            $("parsedPreview").style.display = "none";
            if (data.jobs && data.jobs[0]) {
                selectedJobId = data.jobs[0].id;
                lastLogIndex = 0;
                $("logBox").innerHTML = "";
            }
            refreshQueue();
        }
    });

    // Queue actions
    $("stopAllBtn").addEventListener("click", async () => {
        await fetch("/api/real-queue/stop", { method: "POST" });
        showToast("تم إرسال إشارة الإيقاف");
        refreshQueue();
    });

    $("clearDoneBtn").addEventListener("click", async () => {
        await fetch("/api/real-queue/clear", { method: "POST" });
        refreshQueue();
    });

    $("retryFailedBtn").addEventListener("click", async () => {
        const r = await fetch("/api/real-queue/retry-failed", { method: "POST" });
        const d = await r.json();
        showToast(d.message || "تمت إعادة المحاولة");
        refreshQueue();
    });

    $("copyDoneBtn").addEventListener("click", async () => {
        const doneJobs = cachedJobs.filter((j) => j.status === "done");
        if (!doneJobs.length) return showToast("لا يوجد طلاب مكتملون للنسخ بعد", true);
        const txt = doneJobs.map((j, idx) => `${idx + 1}. ${j.display_name} (${j.username}) — ${j.current_stage}`).join("\n");
        await navigator.clipboard.writeText(`✅ تقرير Qureo Pro (${doneJobs.length} طالب):\n${txt}`);
        showToast(`تم نسخ تقرير ${doneJobs.length} طالب بنجاح`);
    });

    function statusBadge(st) {
        const map = {
            queued: ["⏳ انتظار", "#f59e0b"],
            running: ["⚙️ شغال", "#10b981"],
            done: ["✅ مكتمل", "#34d399"],
            error: ["❌ خطأ", "#ef4444"],
            stopped: ["⏹ متوقف", "#94a3b8"],
        };
        const [txt, col] = map[st] || [st, "#94a3b8"];
        return `<span style="color:${col}; font-weight:800; font-size:0.75rem;">${txt}</span>`;
    }

    function renderQueueList() {
        const list = $("queueList");
        const filtered = cachedJobs.filter((j) => {
            if (currentFilter !== "all" && j.status !== currentFilter) return false;
            if (searchTerm) {
                const hay = `${j.display_name} ${j.username} ${j.subject_label}`.toLowerCase();
                if (!hay.includes(searchTerm)) return false;
            }
            return true;
        });

        if (!filtered.length) {
            list.innerHTML = `<div class="queue-empty">لا توجد مهام مطابقة حالياً</div>`;
            return;
        }

        // Render up to 120 visible cards smoothly for huge batches
        const visible = filtered.slice(0, 120);
        list.innerHTML = visible.map((j) => {
            const isSel = j.id === selectedJobId;
            const tot = j.progress_total || 0;
            const done = j.progress_done || 0;
            const pct = tot > 0 ? Math.min(100, Math.round((done / tot) * 100)) : (j.status === "done" ? 100 : 0);
            return `
            <div class="q-card ${isSel ? "selected" : ""}" data-id="${j.id}">
                <div class="q-card-top">
                    <span class="q-name">${j.seq}. ${j.display_name}</span>
                    ${statusBadge(j.status)}
                </div>
                <div class="q-sub">
                    <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${j.current_stage}</span>
                    <span class="mono">${done}/${tot || "-"}</span>
                </div>
                <div class="q-mini-bar"><div class="q-mini-fill" style="width:${pct}%"></div></div>
            </div>`;
        }).join("");

        list.querySelectorAll(".q-card").forEach((el) => {
            el.addEventListener("click", () => {
                selectedJobId = el.dataset.id;
                lastLogIndex = 0;
                $("logBox").innerHTML = "";
                renderQueueList();
                pollSelectedLogs();
            });
        });
    }

    async function refreshQueue() {
        try {
            const r = await fetch("/api/real-queue");
            const data = await r.json();
            cachedJobs = data.jobs || [];

            $("hdrQueuedCount").textContent = data.counts.queued;
            $("hdrDoneCount").textContent = data.counts.done;
            $("queueTotalCount").textContent = data.counts.total;

            if (data.counts.error > 0) {
                $("hdrErrChip").style.display = "inline-flex";
                $("hdrErrCount").textContent = data.counts.error;
            } else {
                $("hdrErrChip").style.display = "none";
            }

            if (data.counts.total > 0) {
                $("batchStrip").style.display = "block";
                const finished = data.counts.done + data.counts.error;
                const pct = Math.round((finished / data.counts.total) * 100);
                $("batchStripText").textContent = `تقدم الدفعة الكلية: ${finished} من ${data.counts.total} طالب`;
                $("batchStripPct").textContent = `${pct}%`;
                $("batchProgressFill").style.width = `${pct}%`;
            } else {
                $("batchStrip").style.display = "none";
            }

            const running = cachedJobs.find((j) => j.status === "running");
            $("hdrActiveName").textContent = running ? running.display_name : "جاهز";
            $("hdrActiveDot").className = running ? "status-dot running" : "status-dot idle";

            if (!selectedJobId && data.active_job_id) {
                selectedJobId = data.active_job_id;
            }
            renderQueueList();
        } catch (e) {}
    }

    async function pollSelectedLogs() {
        if (!selectedJobId) return;
        try {
            const r = await fetch(`/api/real-queue/logs?job_id=${encodeURIComponent(selectedJobId)}&since=${lastLogIndex}`);
            if (!r.ok) return;
            const data = await r.json();
            const job = data.job;
            if (job) {
                $("monitorTitle").textContent = `🖥️ ${job.display_name} (${job.subject_label})`;
                $("monitorStage").textContent = job.current_stage;
                const tot = job.progress_total || 0;
                const done = job.progress_done || 0;
                $("monitorProgressText").textContent = `${done} / ${tot}`;
                $("monitorProgressFill").style.width = tot > 0 ? `${Math.min(100, Math.round((done / tot) * 100))}%` : "0%";
                $("proofBtn").style.display = (job.status === "done" || job.has_proof) ? "inline-flex" : "none";
                $("openBrowserBtn").style.display = "inline-flex";
                if (job.has_screenshot) {
                    $("liveScreenshot").src = `/api/real-queue/${job.id}/screenshot?t=${Date.now()}`;
                    $("liveScreenshot").style.display = "block";
                    $("noScreenshotMsg").style.display = "none";
                }
            }
            if (Array.isArray(data.logs) && data.logs.length) {
                const box = $("logBox");
                for (const line of data.logs) {
                    const div = document.createElement("div");
                    if (typeof line === "string") {
                        div.textContent = line;
                    } else if (line && typeof line === "object") {
                        div.textContent = line.time ? `[${line.time}] ${line.text || ""}` : (line.text || JSON.stringify(line));
                    }
                    box.appendChild(div);
                }
                lastLogIndex = data.total_logs;
                box.scrollTop = box.scrollHeight;
            }
        } catch (e) {}
    }

    // Proof modal & WhatsApp report
    $("proofBtn").addEventListener("click", async () => {
        if (!selectedJobId) return;
        $("proofModal").style.display = "flex";
        $("proofStatsBox").textContent = "جاري جلب إثبات الحل من Qureo...";
        $("proofCourseImg").style.display = "none";
        $("proofSectionImg").style.display = "none";
        const r = await fetch(`/api/real-queue/${selectedJobId}/proof`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ force: false }),
        });
        const data = await r.json();
        if (!data.ok) {
            $("proofStatsBox").textContent = data.error || "تعذر جلب الإثبات";
            return;
        }
        const st = data.stats || {};
        latestProofStats = st;
        $("proofStatsBox").textContent = `✅ الفصول: ${st.completed_chapters || 0}/${st.total_chapters || 0} • 💎 الألماس: ${st.total_diamonds || 0}/${st.max_diamonds || 0}`;
        if (data.has_course) {
            $("proofCourseImg").src = `/api/real-queue/${selectedJobId}/proof/image/course?t=${Date.now()}`;
            $("proofCourseImg").style.display = "block";
        }
        if (data.has_section) {
            $("proofSectionImg").src = `/api/real-queue/${selectedJobId}/proof/image/section?t=${Date.now()}`;
            $("proofSectionImg").style.display = "block";
        }
    });

    $("copyWhatsappBtn").addEventListener("click", async () => {
        const job = cachedJobs.find((j) => j.id === selectedJobId);
        if (!job) return;
        const st = latestProofStats || job.proof_stats || {};
        const msg = [
            "✅ تم حل منصة Qureo بالكامل (حل حقيقي بالأكواد)",
            `👤 الطالب: ${job.display_name} (${job.username})`,
            `📚 المادة: ${job.subject_label}`,
            `✅ الفصول: ${st.completed_chapters ?? job.progress_done}/${st.total_chapters ?? job.progress_total}`,
            `💎 الألماس: ${st.total_diamonds ?? "-"}/${st.max_diamonds ?? "-"}`,
            `🕒 الوقت: ${new Date().toLocaleTimeString("ar-EG")}`,
        ].join("\n");
        await navigator.clipboard.writeText(msg);
        showToast("تم نسخ تقرير الواتساب بنجاح 📲");
    });

    $("openBrowserBtn").addEventListener("click", async () => {
        if (!selectedJobId) return;
        showToast("جاري فتح حساب الطالب في المتصفح...");
        const r = await fetch(`/api/real-queue/${selectedJobId}/open-browser`, { method: "POST" });
        const d = await r.json();
        showToast(d.message || (d.ok ? "تم الفتح" : "تعذر الفتح"), !d.ok);
    });

    $("closeProofBtn").addEventListener("click", () => {
        $("proofModal").style.display = "none";
    });

    setInterval(() => {
        refreshQueue();
        pollSelectedLogs();
    }, 1500);
    refreshQueue();
})();
