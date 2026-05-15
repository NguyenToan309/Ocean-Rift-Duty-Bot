// dashboard.js — Logic dashboard: guild picker, load data, charts, ranking, audit, export

const STATE = {
    guildId: null,
    guildList: [],
    currentSection: "overview",
    order: "desc",
    page: 1,
    logsPage: 1,
    logsUserFilter: "",
    isMod: false,
    isAdmin: false,
    chart: null,
    pendingDeleteId: null,
    // Schedule section
    scheduleView: "grid",          // grid | calendar | compliance
    scheduleWeekOffset: 0,
    pendingScheduleEditId: null,
    // Leave section
    leaveTab: "pending",
    pendingLeaveDecisionId: null,
    pendingLeaveRevertId: null,
    // WebSocket
    ws: null,
    wsReconnectTimer: null,
    wsReconnectDelay: 1000,
    // Attendance section
    attendanceData: null,           // raw response cache
    attendanceFiltered: [],         // sau filter + sort
    attendanceDetailUid: null,
};

// ── Init ──
document.addEventListener("DOMContentLoaded", async () => {
    setupNav();
    setupPeriod();
    await loadMe();
    await loadGuilds();
});

async function loadMe() {
    const me = await apiFetch("/api/dashboard/me");
    if (!me) return;
    localStorage.setItem("user_id", me.user_id);
    localStorage.setItem("username", me.username);
    document.getElementById("username-display").textContent = me.username || "User";
    // Avatar = chữ đầu của username
    const initial = (me.username || "U").trim().charAt(0).toUpperCase();
    document.getElementById("user-avatar").textContent = initial;
}

// ── Setup ──
function setupNav() {
    document.querySelectorAll(".nav-link").forEach((link) => {
        link.addEventListener("click", (e) => {
            e.preventDefault();
            switchSection(link.dataset.section);
        });
    });
}

function setupPeriod() {
    document.getElementById("period-select").addEventListener("change", (e) => {
        document.getElementById("custom-range").classList.toggle("hidden", e.target.value !== "custom");
    });
}

// ── Guild loading ──
async function loadGuilds() {
    const data = await apiFetch("/api/dashboard/me/guilds");
    if (!data) {
        // 401 → apiFetch đã redirect
        return;
    }

    const guilds = data.guilds || [];
    STATE.guildList = guilds;

    document.getElementById("loading-state").classList.add("hidden");

    if (guilds.length === 0) {
        document.getElementById("no-guild").classList.remove("hidden");
        return;
    }

    // Restore last guild from localStorage if still valid, else first
    const stored = localStorage.getItem("guild_id");
    const found = guilds.find((g) => g.guild_id === stored);
    const selected = found || guilds[0];

    STATE.guildId = selected.guild_id;
    STATE.isMod = selected.is_mod;
    STATE.isAdmin = selected.is_admin;
    localStorage.setItem("guild_id", selected.guild_id);

    // Render guild dropdown
    const sel = document.getElementById("guild-select");
    sel.innerHTML = guilds.map((g) =>
        `<option value="${g.guild_id}" ${g.guild_id === STATE.guildId ? "selected" : ""}>${escHtml(g.guild_name)}</option>`
    ).join("");
    if (guilds.length === 1) sel.disabled = true;

    // username already set by loadMe()
    renderRoleBadge(selected.role_level);

    // Toggle role-based visibility
    applyRoleVisibility();

    // Show content
    document.getElementById("content-area").classList.remove("hidden");
    loadCurrentSection();
}

function applyRoleVisibility() {
    // .mod-only: hiện cho MOD và ADMIN (export buttons, logs filter…)
    document.querySelectorAll(".mod-only").forEach((el) => el.classList.toggle("hidden", !STATE.isMod));
    // .admin-only: chỉ ADMIN (audit log nav)
    document.querySelectorAll(".admin-only").forEach((el) => el.classList.toggle("hidden", !STATE.isAdmin));
    // Tiêu đề logs section: phân biệt mod-view và member-view
    document.querySelectorAll(".logs-title-mod").forEach((el) => el.classList.toggle("hidden", !STATE.isMod));
    document.querySelectorAll(".logs-title-member").forEach((el) => el.classList.toggle("hidden", STATE.isMod));
}

function onGuildChange() {
    const newId = document.getElementById("guild-select").value;
    const g = STATE.guildList.find((x) => x.guild_id === newId);
    if (!g) return;
    STATE.guildId = newId;
    STATE.isMod = g.is_mod;
    STATE.isAdmin = g.is_admin;
    localStorage.setItem("guild_id", newId);
    renderRoleBadge(g.role_level);
    applyRoleVisibility();
    // Switch to overview if currently on audit but no longer admin
    if (!STATE.isAdmin && STATE.currentSection === "audit") {
        switchSection("overview");
    } else {
        loadCurrentSection();
    }
}

function renderRoleBadge(role) {
    const el = document.getElementById("role-badge");
    const map = {
        DUTY_ADMIN: { text: "Admin", cls: "bg-red-500/10 text-red-400 border-red-500/20" },
        DUTY_MOD:   { text: "Mod",   cls: "bg-purple-500/10 text-purple-400 border-purple-500/20" },
        DUTY_MEMBER:{ text: "Member",cls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
    };
    const cfg = map[role] || { text: role, cls: "bg-zinc-800 text-zinc-400 border-zinc-700" };
    el.textContent = cfg.text;
    el.className = `inline-block mt-0.5 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider rounded-full border ${cfg.cls}`;
}

// Source pill metadata
const SOURCE_META = {
    ocr:     { label: "OCR",  icon: "camera",        cls: "bg-indigo-500/10 text-indigo-400 border-indigo-500/20" },
    forward: { label: "Text", icon: "message-square",cls: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
    message: { label: "Auto", icon: "send",          cls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
    manual:  { label: "Tay",  icon: "edit-3",        cls: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
};

// Helper: re-render Lucide icons (gọi sau khi update DOM)
function refreshIcons() {
    if (window.lucide) lucide.createIcons();
}

// ── Section switching ──
function switchSection(name) {
    STATE.currentSection = name;
    document.querySelectorAll(".nav-link").forEach((l) => l.classList.remove("active"));
    document.querySelector(`[data-section="${name}"]`)?.classList.add("active");

    ["overview", "ranking", "logs", "audit", "attendance", "schedule", "leave"].forEach((s) => {
        const el = document.getElementById(`section-${s}`);
        if (el) el.classList.toggle("hidden", s !== name);
    });

    loadCurrentSection();
}

function loadCurrentSection() {
    if (!STATE.guildId) return;
    const fn = {
        overview: loadOverview,
        ranking: () => loadRanking(1),
        logs: () => loadLogs(1),
        audit: loadAudit,
        attendance: () => loadAttendance(false),
        schedule: () => loadScheduleSection(false),
        leave: () => loadLeaveSection(false),
    }[STATE.currentSection];
    fn?.();
    // Re-render Lucide icons sau khi update content
    setTimeout(refreshIcons, 50);
}

// ── Build query params ──
function buildParams(extra = {}) {
    const params = new URLSearchParams({
        guild_id: STATE.guildId,
        period: document.getElementById("period-select").value,
        ...extra,
    });
    if (params.get("period") === "custom") {
        const from = document.getElementById("date-from").value;
        const to = document.getElementById("date-to").value;
        if (!from || !to) return null;
        params.set("date_from", from);
        params.set("date_to", to);
    }
    return params;
}

// ── Overview ──
async function loadOverview() {
    const params = buildParams();
    if (!params) return;

    const [overview, chart] = await Promise.all([
        apiFetch(`/api/dashboard/overview?${params}`),
        apiFetch(`/api/dashboard/chart?${params}`),
    ]);

    if (overview) renderOverview(overview);
    if (chart) renderChart(chart);
}

function renderOverview(data) {
    const totalSessions = data.total_sessions ?? 0;
    const totalMinutes = data.total_minutes ?? 0;
    const totalMembers = data.total_members ?? 0;
    const avgMin = totalSessions > 0 ? Math.round(totalMinutes / totalSessions) : 0;

    // Stat cards
    document.getElementById("stat-sessions").textContent = totalSessions.toLocaleString("vi-VN");
    document.getElementById("stat-time").textContent = data.total_hhmm || "0 phút";
    document.getElementById("stat-members").textContent = totalMembers;
    document.getElementById("stat-avg").textContent = minutesToHhmm(avgMin);

    // Hero card
    const periodLabels = {
        day: "Hôm nay", week: "Tuần này", month: "Tháng này",
        quarter: "Quý này", all: "Toàn bộ thời gian", custom: "Khoảng tùy chỉnh",
    };
    const period = document.getElementById("period-select").value;
    document.getElementById("hero-period-label").textContent = periodLabels[period] || period;

    const username = localStorage.getItem("username") || "bạn";
    document.getElementById("hero-username").textContent = username;

    const guild = STATE.guildList.find(g => g.guild_id === STATE.guildId);
    document.getElementById("hero-guild").textContent = guild?.guild_name || "—";

    // Hero metric — large total hours
    const hours = Math.floor(totalMinutes / 60);
    const mins = totalMinutes % 60;
    document.getElementById("hero-total-hours").textContent =
        hours > 0 ? `${hours}g ${mins.toString().padStart(2, "0")}p` : `${mins}p`;

    document.getElementById("hero-headline").textContent =
        totalSessions > 0
            ? `${totalSessions} ca trực hoàn thành trong kỳ`
            : "Chưa có ca trực nào trong kỳ này";

    // Hero quick-stats
    const qS = document.getElementById("hero-q-sessions");
    const qM = document.getElementById("hero-q-members");
    const qA = document.getElementById("hero-q-avg");
    if (qS) qS.textContent = " " + totalSessions.toLocaleString("vi-VN") + " ";
    if (qM) qM.textContent = " " + totalMembers + " ";
    if (qA) qA.textContent = " " + minutesToHhmm(avgMin) + " ";

    // Top 5 — premium layout
    const top5El = document.getElementById("top5-list");
    if (!data.top5 || data.top5.length === 0) {
        top5El.innerHTML = `<div class="top5-empty">Chưa có dữ liệu trong khoảng thời gian này</div>`;
        return;
    }
    const maxMin = Math.max(...data.top5.map(u => u.total_minutes));
    top5El.innerHTML = data.top5.map((u, i) => {
        const rankCls = i === 0 ? "top1" : i === 1 ? "top2" : i === 2 ? "top3" : "";
        const rankIcon = i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `${i + 1}`;
        const pct = maxMin > 0 ? (u.total_minutes / maxMin) * 100 : 0;
        return `
            <div class="top5-row">
                <div class="top5-rank ${rankCls}">${rankIcon}</div>
                <div class="top5-name">
                    <div class="top5-name-text">${escHtml(u.username)}</div>
                    <div class="top5-bar-wrap"><div class="top5-bar-fill" style="width: ${pct}%"></div></div>
                </div>
                <div class="top5-meta">
                    <span class="top5-time">${u.total_hhmm}</span>
                    <span class="top5-sessions">${u.sessions} ca</span>
                </div>
            </div>
        `;
    }).join("");
}

function renderChart(data) {
    const ctx = document.getElementById("duty-chart").getContext("2d");
    if (STATE.chart) STATE.chart.destroy();

    if (!data.labels || data.labels.length === 0) {
        ctx.canvas.style.display = "none";
        const card = ctx.canvas.closest(".chart-card");
        let empty = card.querySelector(".chart-empty");
        if (!empty) {
            empty = document.createElement("p");
            empty.className = "chart-empty empty-msg";
            empty.textContent = "Chưa có dữ liệu để vẽ biểu đồ";
            card.appendChild(empty);
        }
        return;
    }
    ctx.canvas.style.display = "block";
    ctx.canvas.closest(".chart-card").querySelector(".chart-empty")?.remove();

    const gradient = ctx.createLinearGradient(0, 0, 0, 240);
    gradient.addColorStop(0, "rgba(99, 102, 241, 0.28)");
    gradient.addColorStop(0.6, "rgba(99, 102, 241, 0.06)");
    gradient.addColorStop(1, "rgba(99, 102, 241, 0)");

    STATE.chart = new Chart(ctx, {
        type: "line",
        data: {
            labels: data.labels,
            datasets: [{
                label: "Thời gian trực (phút)",
                data: data.data,
                borderColor: "rgba(124, 127, 245, 1)",
                backgroundColor: gradient,
                borderWidth: 1.75,
                tension: 0.45,
                fill: true,
                pointRadius: 0,
                pointHoverRadius: 5,
                pointBackgroundColor: "rgba(124, 127, 245, 1)",
                pointBorderColor: "#11141A",
                pointBorderWidth: 2,
                pointHoverBackgroundColor: "rgba(124, 127, 245, 1)",
                pointHoverBorderColor: "#fff",
                pointHoverBorderWidth: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            layout: { padding: { top: 4, right: 4, bottom: 0, left: 0 } },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "rgba(8, 10, 14, 0.96)",
                    titleColor: "#F4F4F5",
                    titleFont: { weight: "600", size: 11, family: "Be Vietnam Pro" },
                    bodyColor: "#A1A1AA",
                    bodyFont: { size: 12, family: "Be Vietnam Pro" },
                    borderColor: "rgba(99, 102, 241, 0.35)",
                    borderWidth: 1,
                    padding: { top: 8, right: 12, bottom: 8, left: 12 },
                    cornerRadius: 8,
                    displayColors: false,
                    titleMarginBottom: 4,
                    callbacks: {
                        label: (ctx) => `${ctx.parsed.y} phút · ${minutesToHhmm(ctx.parsed.y)}`,
                    },
                },
            },
            scales: {
                x: {
                    ticks: {
                        color: "#5C606A",
                        font: { size: 10.5, family: "JetBrains Mono", weight: 500 },
                        padding: 6,
                        maxRotation: 0,
                    },
                    grid: { display: false },
                    border: { display: false },
                },
                y: {
                    ticks: {
                        color: "#5C606A",
                        font: { size: 10.5, family: "JetBrains Mono", weight: 500 },
                        padding: 8,
                        callback: (v) => v + "p",
                    },
                    grid: {
                        color: "rgba(255, 255, 255, 0.035)",
                        drawTicks: false,
                    },
                    border: { display: false },
                    beginAtZero: true,
                },
            },
        },
    });
}

// ── Ranking ──
async function loadRanking(page = 1) {
    STATE.page = page;
    const params = buildParams({ order: STATE.order, page, page_size: 20 });
    if (!params) return;

    const data = await apiFetch(`/api/dashboard/ranking?${params}`);
    if (!data) return;

    const tbody = document.getElementById("ranking-body");
    if (!data.items || data.items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" class="loading">Chưa có dữ liệu trong khoảng thời gian này</td></tr>`;
        document.getElementById("ranking-pagination").innerHTML = "";
        return;
    }

    const maxMin = Math.max(...data.items.map(r => r.total_minutes));
    const rankColor = ["text-yellow-400", "text-zinc-300", "text-orange-400"];
    tbody.innerHTML = data.items.map((r) => {
        const pct = maxMin > 0 ? (r.total_minutes / maxMin * 100).toFixed(0) : 0;
        const colorCls = r.rank <= 3 ? rankColor[r.rank - 1] : "text-zinc-500";
        const rankLabel = r.rank <= 3
            ? `<span class="font-semibold tabular-nums ${colorCls}">${r.rank}</span>`
            : `<span class="text-zinc-500 tabular-nums">#${r.rank}</span>`;
        return `
            <tr class="border-b border-zinc-800/60 hover:bg-zinc-800/30 transition-colors">
                <td class="px-5 py-3">${rankLabel}</td>
                <td class="px-5 py-3"><span class="font-medium text-white">${escHtml(r.username)}</span></td>
                <td class="px-5 py-3">
                    <div class="flex items-center gap-3">
                        <span class="tabular-nums text-zinc-300 min-w-[90px]">${r.total_hhmm}</span>
                        <div class="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                            <div class="h-full bg-gradient-to-r from-indigo-500 to-indigo-400 rounded-full" style="width:${pct}%"></div>
                        </div>
                    </div>
                </td>
                <td class="px-5 py-3 text-right">
                    <span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">${r.sessions} ca</span>
                </td>
            </tr>
        `;
    }).join("");

    // Server-side total chưa được expose — pagination dựa vào page_size
    renderPagination(data.items.length, 20, page);
}

function toggleOrder() {
    STATE.order = STATE.order === "desc" ? "asc" : "desc";
    const btn = document.getElementById("order-btn");
    const arrow = STATE.order === "desc" ? "arrow-down" : "arrow-up";
    btn.innerHTML = `<i data-lucide="${arrow}" class="icon-sm"></i> ${STATE.order === "desc" ? "Nhiều nhất" : "Ít nhất"}`;
    refreshIcons();
    loadRanking(1);
}

function renderPagination(itemsCount, pageSize, current) {
    const el = document.getElementById("ranking-pagination");
    const hasNext = itemsCount === pageSize;
    if (current === 1 && !hasNext) { el.innerHTML = ""; return; }
    const btnCls = "h-8 px-3 rounded-lg bg-zinc-900 border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800 text-zinc-300 hover:text-white text-[12px] font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed";
    el.innerHTML = `
        <button class="${btnCls}" ${current === 1 ? "disabled" : ""} onclick="loadRanking(${current - 1})">← Trước</button>
        <span class="text-[12px] text-zinc-500 px-3 tabular-nums">Trang ${current}</span>
        <button class="${btnCls}" ${!hasNext ? "disabled" : ""} onclick="loadRanking(${current + 1})">Sau →</button>
    `;
}

// ── Logs (chi tiết từng entry với delete) ──
async function loadLogs(page = 1) {
    STATE.logsPage = page;
    const period = document.getElementById("period-select").value;
    const params = new URLSearchParams({
        guild_id: STATE.guildId,
        period: period === "custom" ? "custom" : period,
        page,
        page_size: 20,
    });
    if (period === "custom") {
        const from = document.getElementById("date-from").value;
        const to = document.getElementById("date-to").value;
        if (!from || !to) return;
        params.set("date_from", from);
        params.set("date_to", to);
    }
    if (STATE.logsUserFilter) params.set("user_id", STATE.logsUserFilter);

    const data = await apiFetch(`/api/dashboard/logs?${params}`);
    if (!data) return;

    const tbody = document.getElementById("logs-body");
    if (!data.items || data.items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="loading">Chưa có log nào trong khoảng thời gian này</td></tr>`;
        document.getElementById("logs-pagination").innerHTML = "";
        return;
    }

    tbody.innerHTML = data.items.map((log) => {
        // Chỉ ADMIN mới được xóa log (member và mod đều KHÔNG xóa được)
        const canDelete = STATE.isAdmin;
        const meta = SOURCE_META[log.source] || { label: log.source, icon: "circle", cls: "bg-zinc-800 text-zinc-400 border-zinc-700" };
        return `
            <tr class="border-b border-zinc-800/60 hover:bg-zinc-800/30 transition-colors">
                <td class="px-5 py-3"><span class="font-mono text-[12px] px-1.5 py-0.5 bg-zinc-950 border border-zinc-800 rounded text-zinc-400">#${log.id}</span></td>
                <td class="px-5 py-3"><span class="font-medium text-white">${escHtml(log.username)}</span></td>
                <td class="px-5 py-3 text-zinc-400 text-[13px] tabular-nums">${formatDate(log.started_at)}</td>
                <td class="px-5 py-3 text-zinc-400 text-[13px] tabular-nums">${formatDate(log.ended_at)}</td>
                <td class="px-5 py-3"><span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">${log.duration_hhmm}</span></td>
                <td class="px-5 py-3">
                    <span class="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-semibold rounded-full border ${meta.cls}">
                        <i data-lucide="${meta.icon}" class="icon-sm"></i>
                        ${meta.label}
                    </span>
                </td>
                <td class="px-5 py-3 text-right">
                    ${canDelete ? `<button onclick="askDelete(${log.id}, '${escHtml(log.username).replace(/'/g, "&#39;")}', '${log.duration_hhmm}')"
                        class="w-8 h-8 grid place-items-center rounded-lg text-zinc-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                        title="Xóa log #${log.id}">
                        <i data-lucide="trash-2" class="icon-sm"></i>
                    </button>` : ""}
                </td>
            </tr>
        `;
    }).join("");

    // Re-render Lucide icons trong table mới
    setTimeout(refreshIcons, 0);

    renderLogsPagination(data.total, data.page_size, data.page);
}

function renderLogsPagination(total, pageSize, current) {
    const el = document.getElementById("logs-pagination");
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (totalPages <= 1) { el.innerHTML = ""; return; }
    el.innerHTML = `
        <button class="page-btn" ${current === 1 ? "disabled" : ""} onclick="loadLogs(${current - 1})">← Trước</button>
        <span class="page-info">Trang ${current} / ${totalPages} • ${total} log</span>
        <button class="page-btn" ${current >= totalPages ? "disabled" : ""} onclick="loadLogs(${current + 1})">Sau →</button>
    `;
}

function applyLogsFilter() {
    const v = document.getElementById("logs-user-filter").value.trim();
    STATE.logsUserFilter = v;
    loadLogs(1);
}

function clearLogsFilter() {
    document.getElementById("logs-user-filter").value = "";
    STATE.logsUserFilter = "";
    loadLogs(1);
}

// Apply filter on Enter trong input
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("logs-user-filter")?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            applyLogsFilter();
        }
    });
});

// ── Delete confirmation ──
function askDelete(logId, username, duration) {
    STATE.pendingDeleteId = logId;
    document.getElementById("confirm-modal-text").innerHTML =
        `Xóa log <code>#${logId}</code> của <strong>${escHtml(username)}</strong> (${duration})?<br><br>` +
        `<span style="color:var(--text-muted);font-size:13px">Hành động này không thể hoàn tác. Audit log sẽ ghi lại.</span>`;
    document.getElementById("confirm-modal").classList.remove("hidden");
}

function closeConfirm() {
    STATE.pendingDeleteId = null;
    document.getElementById("confirm-modal").classList.add("hidden");
}

async function confirmDelete() {
    const id = STATE.pendingDeleteId;
    if (!id) return;
    closeConfirm();

    const params = new URLSearchParams({ guild_id: STATE.guildId });
    const resp = await fetch(`/api/dashboard/logs/${id}?${params}`, {
        method: "DELETE",
        credentials: "include",
    });

    if (resp.status === 401) { window.location.href = "/"; return; }
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        showToast(err.detail || `Xóa thất bại (${resp.status})`, "error");
        return;
    }

    showToast(`✅ Đã xóa log #${id}`, "success");
    loadLogs(STATE.logsPage);
}

// ── Audit ──
async function loadAudit() {
    const data = await apiFetch(`/api/audit/logs?guild_id=${STATE.guildId}&page_size=50`);
    if (!data) return;

    const tbody = document.getElementById("audit-body");
    if (!data.items || data.items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" class="loading">Chưa có audit log</td></tr>`;
        return;
    }

    const PILL_OK   = "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
    const PILL_ERR  = "bg-red-500/10 text-red-400 border-red-500/20";
    const PILL_WARN = "bg-amber-500/10 text-amber-400 border-amber-500/20";
    const PILL_INFO = "bg-blue-500/10 text-blue-400 border-blue-500/20";
    const PILL_PUR  = "bg-purple-500/10 text-purple-400 border-purple-500/20";
    const PILL_GREY = "bg-zinc-800 text-zinc-400 border-zinc-700";

    const actionLabels = {
        LOGIN_SUCCESS:         { text: "Đăng nhập",        cls: PILL_OK },
        LOGIN_FAILED:          { text: "Đăng nhập thất bại", cls: PILL_ERR },
        LOGIN_2FA_FAILED:      { text: "2FA sai",          cls: PILL_ERR },
        ACCOUNT_LOCKED:        { text: "Khóa tài khoản",   cls: PILL_WARN },
        LOG_UPLOADED:          { text: "Lưu log",          cls: PILL_OK },
        LOG_DELETED:           { text: "Xóa log",          cls: PILL_WARN },
        EXPORT_CSV:            { text: "Xuất CSV",         cls: PILL_INFO },
        EXPORT_EXCEL:          { text: "Xuất Excel",       cls: PILL_INFO },
        SETUP_GUILD:           { text: "Setup guild",      cls: PILL_PUR },
        CHANGE_ROLE_CONFIG:    { text: "Đổi role config",  cls: PILL_PUR },
        CHANGE_CHANNEL_CONFIG: { text: "Đổi channel",      cls: PILL_PUR },
        LOG_REJECTED:          { text: "Từ chối log",      cls: PILL_ERR },
    };

    tbody.innerHTML = data.items.map((log) => {
        const a = actionLabels[log.action] || { text: log.action, cls: PILL_GREY };
        const detail = log.detail || {};
        const importantKeys = ["for_user", "for_username", "duration_minutes", "log_id", "source", "rows", "period", "auto"];
        const summary = Object.entries(detail)
            .filter(([k]) => importantKeys.includes(k))
            .map(([k, v]) => `<span class="text-zinc-500">${escHtml(k)}</span> <span class="text-zinc-200 font-medium">${escHtml(String(v))}</span>`)
            .join(" <span class='text-zinc-700 mx-1'>·</span> ");
        return `
            <tr class="border-b border-zinc-800/60 hover:bg-zinc-800/30 transition-colors">
                <td class="px-5 py-3 text-zinc-400 text-[12px] tabular-nums">${formatDate(log.created_at)}</td>
                <td class="px-5 py-3"><span class="font-medium text-white">${escHtml(log.username || "—")}</span></td>
                <td class="px-5 py-3"><span class="px-2 py-0.5 text-[11px] font-semibold rounded-full border ${a.cls}">${escHtml(a.text)}</span></td>
                <td class="px-5 py-3 text-[12px]">${summary || `<code class="px-1.5 py-0.5 bg-zinc-950 border border-zinc-800 rounded text-zinc-500">${escHtml(JSON.stringify(detail))}</code>`}</td>
            </tr>
        `;
    }).join("");
}

// ── Export ──
async function exportFile(format) {
    if (!STATE.guildId) return;
    if (!STATE.isMod) {
        showToast("Bạn cần quyền DUTY_MOD để xuất file", "error");
        return;
    }

    showToast(`Đang chuẩn bị file ${format.toUpperCase()}…`, "info");

    const params = buildParams({ format });
    if (!params) {
        showToast("Vui lòng chọn khoảng thời gian hợp lệ", "error");
        return;
    }

    // Bước 1: lấy one-time download token
    const data = await apiFetch(`/api/export/prepare?${params}`, { method: "POST" });
    if (!data?.download_url) return;

    // Bước 2: fetch file → blob → trigger download (giữ user ở dashboard)
    try {
        const resp = await fetch(data.download_url, { credentials: "include" });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.detail || `Tải file thất bại (${resp.status})`, "error");
            return;
        }

        // Lấy filename từ Content-Disposition header
        const cd = resp.headers.get("Content-Disposition") || "";
        const match = cd.match(/filename="?([^";]+)"?/i);
        const filename = match ? match[1] : `duty_log.${format === "csv" ? "csv" : "xlsx"}`;

        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);

        showToast(`✅ Đã tải xong ${filename}`, "success");
    } catch (e) {
        showToast("Lỗi khi tải file", "error");
    }
}

// ── Utils ──
async function apiFetch(url, opts = {}) {
    try {
        const resp = await fetch(url, { credentials: "include", ...opts });
        if (resp.status === 401) {
            // Token hết hạn/invalid → logout server-side để xoá cookie, rồi redirect.
            // Tránh infinite loop: / sẽ check cookie tồn tại + redirect /dashboard.
            try {
                await fetch("/auth/logout", { method: "POST", credentials: "include" });
            } catch (_) { /* ignore */ }
            localStorage.clear();
            window.location.href = "/";
            return null;
        }
        if (resp.status === 403) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.detail || "Không đủ quyền truy cập", "error");
            return null;
        }
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.detail || `Lỗi server (${resp.status})`, "error");
            // Hide loading state để user thấy error rõ ràng thay vì spinner mãi
            document.getElementById("loading-state")?.classList.add("hidden");
            return null;
        }
        return await resp.json();
    } catch (e) {
        showToast("Mất kết nối server", "error");
        document.getElementById("loading-state")?.classList.add("hidden");
        return null;
    }
}

async function logout() {
    if (!confirm("Bạn có chắc muốn đăng xuất?")) return;
    await fetch("/auth/logout", { method: "POST", credentials: "include" });
    localStorage.removeItem("guild_id");
    localStorage.removeItem("user_id");
    localStorage.removeItem("username");
    window.location.href = "/";
}

function showToast(msg, type = "success") {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.className = `toast ${type}`;
    el.classList.remove("hidden");
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => el.classList.add("hidden"), 3500);
}

function escHtml(str) {
    return String(str ?? "").replace(/[&<>"']/g, (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
}

function formatDate(iso) {
    if (!iso) return "--";
    const d = new Date(iso);
    return d.toLocaleString("vi-VN", { hour12: false });
}

function minutesToHhmm(m) {
    if (m == null || m < 0) return "0 phút";
    const h = Math.floor(m / 60);
    const mm = m % 60;
    if (h === 0) return `${mm} phút`;
    if (mm === 0) return `${h} giờ`;
    return `${h} giờ ${mm} phút`;
}


// ════════════════════════════════════════════════════════════════════════════
// ── SCHEDULE SECTION ───────────────────────────────────────────────────────
// ════════════════════════════════════════════════════════════════════════════

const WEEKDAY_SHORT = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
const WEEKDAY_LABELS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"];

function loadScheduleSection(forceRefresh = false) {
    // Highlight current view button
    document.querySelectorAll(".schedule-view-btn").forEach((b) => b.classList.remove("active-tab"));
    document.querySelector(`[data-schedule-view="${STATE.scheduleView}"]`)?.classList.add("active-tab");

    // Show only current pane
    ["grid", "calendar", "compliance"].forEach((v) => {
        const el = document.getElementById(`schedule-view-${v}`);
        if (el) el.classList.toggle("hidden", v !== STATE.scheduleView);
    });

    if (STATE.scheduleView === "grid") loadScheduleGrid();
    else if (STATE.scheduleView === "calendar") loadScheduleCalendar();
    else if (STATE.scheduleView === "compliance") loadScheduleCompliance();
}

function switchScheduleView(view) {
    STATE.scheduleView = view;
    loadScheduleSection(false);
}

async function loadScheduleGrid() {
    const params = buildParams();
    if (!params) return;
    const data = await apiFetch(`/api/schedule/grid?${params}`);
    if (!data) return;

    // Toggle Discord ID column visibility (Q5=c)
    document.querySelectorAll(".mod-only-col").forEach((el) =>
        el.classList.toggle("hidden", !data.is_mod_view));

    const tbody = document.getElementById("schedule-grid-body");
    if (!data.items || data.items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-zinc-500 italic py-10">Chưa có ai đăng ký lịch</td></tr>`;
        return;
    }

    const myUid = localStorage.getItem("user_id");
    tbody.innerHTML = data.items.map((row) => {
        const onLeaveBadge = row.on_leave_today
            ? `<span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20" title="${row.leave_dates.join(', ')}">🏖 Đang nghỉ</span>`
            : (row.leave_dates.length > 0
                ? `<span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-zinc-800 text-zinc-400 border border-zinc-700" title="Đã nghỉ: ${row.leave_dates.join(', ')}">${row.leave_dates.length} ngày</span>`
                : `<span class="text-zinc-600 text-[11px]">—</span>`);

        const schedulePills = row.schedules.map((s) => {
            const cross = s.crosses_midnight ? "🌙" : "";
            const isOwner = String(row.user_id) === myUid || (!row.user_id && row.username === localStorage.getItem("username"));
            const canDelete = STATE.isMod || isOwner;
            const canEdit = isOwner;
            const editBtn = canEdit
                ? `<button onclick="askEditSchedule(${s.id}, ${s.weekday}, '${s.start_time}', '${s.end_time}')" class="ml-1 text-zinc-500 hover:text-indigo-400" title="Sửa">✏️</button>`
                : "";
            const delBtn = canDelete
                ? `<button onclick="askDeleteSchedule(${s.id})" class="ml-1 text-zinc-500 hover:text-red-400" title="Xoá">🗑</button>`
                : "";
            return `<span class="inline-flex items-center gap-1 px-2 py-0.5 mr-1 mb-1 rounded-md bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 text-[12px] font-medium">
                ${WEEKDAY_SHORT[s.weekday]} <span class="text-zinc-500">·</span> <span class="font-mono">${s.start_time}–${s.end_time}</span>${cross}
                ${editBtn}${delBtn}
            </span>`;
        }).join("");

        const idCell = row.user_id
            ? `<td class="px-5 py-3 mod-only-col text-zinc-500 font-mono text-[11px]">${row.user_id}</td>`
            : `<td class="px-5 py-3 mod-only-col"></td>`;

        return `
            <tr class="border-b border-zinc-800/60 hover:bg-zinc-800/30 transition-colors">
                <td class="px-5 py-3"><span class="font-medium text-white">${escHtml(row.username)}</span></td>
                ${idCell}
                <td class="px-5 py-3 max-w-[400px]">${schedulePills || '<span class="text-zinc-600 text-[12px]">Chưa có</span>'}</td>
                <td class="px-5 py-3 text-right tabular-nums text-zinc-300">${minutesToHhmm(row.total_minutes_per_week)}</td>
                <td class="px-5 py-3 text-right">
                    ${row.missed_count > 0
                        ? `<span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-red-500/10 text-red-400 border border-red-500/20">${row.missed_count}</span>`
                        : `<span class="text-zinc-600">0</span>`}
                </td>
                <td class="px-5 py-3 text-center">${onLeaveBadge}</td>
                <td class="px-5 py-3 text-right"></td>
            </tr>
        `;
    }).join("");
    setTimeout(refreshIcons, 0);
}

async function loadScheduleCalendar() {
    const params = new URLSearchParams({ guild_id: STATE.guildId, week_offset: STATE.scheduleWeekOffset });
    const data = await apiFetch(`/api/schedule/calendar?${params}`);
    if (!data) return;

    document.getElementById("schedule-week-label").textContent =
        `Tuần bắt đầu ${formatDateShort(data.monday)}`;

    const grid = document.getElementById("schedule-calendar-grid");
    grid.innerHTML = data.days.map((d) => {
        const items = d.schedules.map((s) => {
            const leaveTag = s.on_leave ? `<span class="ml-1 text-[10px] text-amber-400">🏖</span>` : "";
            const cross = s.crosses_midnight ? `<span class="text-[10px] text-zinc-500">🌙</span>` : "";
            return `<div class="text-[12px] px-2 py-1 mb-1 rounded bg-zinc-900 border border-zinc-800 ${s.on_leave ? 'opacity-50' : ''}">
                <div class="font-medium text-zinc-200 truncate">${escHtml(s.username)}${leaveTag}</div>
                <div class="text-[11px] text-zinc-500 font-mono">${s.start_time}–${s.end_time} ${cross}</div>
            </div>`;
        }).join("") || `<div class="text-[11px] text-zinc-600 italic">Trống</div>`;
        const todayClass = d.is_today ? "border-indigo-500/50 bg-indigo-500/5" : "border-zinc-800 bg-zinc-900/40";
        return `<div class="rounded-lg border ${todayClass} p-2.5 min-h-[120px]">
            <div class="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">${d.weekday_short} · ${formatDateShort(d.date)}${d.is_today ? ' 🔵' : ''}</div>
            ${items}
        </div>`;
    }).join("");
}

function changeWeek(offset) {
    if (offset === 0) STATE.scheduleWeekOffset = 0;
    else STATE.scheduleWeekOffset += offset;
    loadScheduleCalendar();
}

async function loadScheduleCompliance() {
    const period = document.getElementById("period-select").value;
    const params = new URLSearchParams({ guild_id: STATE.guildId, period });
    const data = await apiFetch(`/api/schedule/compliance?${params}`);
    if (!data) return;

    // Summary
    const c = data.summary.counters || {};
    const summary = document.getElementById("schedule-compliance-summary");
    summary.innerHTML = `
        ${complianceCard("✅ Đúng giờ", c.on_time || 0, "text-emerald-400 bg-emerald-500/10 border-emerald-500/20")}
        ${complianceCard("⏰ Thiếu giờ", c.late || 0, "text-amber-400 bg-amber-500/10 border-amber-500/20")}
        ${complianceCard("🚫 Vắng", c.missed || 0, "text-red-400 bg-red-500/10 border-red-500/20")}
        ${complianceCard("🆓 Ngoài lịch", c.off_schedule || 0, "text-zinc-300 bg-zinc-700/30 border-zinc-600/50")}
        ${complianceCard("🏖 Nghỉ phép", c.on_leave || 0, "text-blue-400 bg-blue-500/10 border-blue-500/20")}
    `;

    const tbody = document.getElementById("schedule-compliance-body");
    if (!data.items || data.items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-zinc-500 italic py-10">Không có dữ liệu trong kỳ này</td></tr>`;
        return;
    }
    const STATUS_META = {
        on_time:      { icon: "✅", cls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
        late:         { icon: "⏰", cls: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
        missed:       { icon: "🚫", cls: "bg-red-500/10 text-red-400 border-red-500/20" },
        off_schedule: { icon: "🆓", cls: "bg-zinc-700/30 text-zinc-300 border-zinc-600/50" },
        on_leave:     { icon: "🏖", cls: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
    };
    tbody.innerHTML = data.items.slice(0, 200).map((it) => {
        const meta = STATUS_META[it.status] || { icon: "•", cls: "bg-zinc-800 text-zinc-400 border-zinc-700" };
        const slot = it.weekday_short ? `${it.weekday_short} ${formatTime(it.scheduled_start)}–${formatTime(it.scheduled_end)}` : "ngoài lịch";
        return `<tr class="border-b border-zinc-800/60">
            <td class="px-5 py-2 text-zinc-400 text-[12px] tabular-nums">${formatDateShort(it.occurrence_date)}</td>
            <td class="px-5 py-2 text-white">${escHtml(it.username)}</td>
            <td class="px-5 py-2 text-zinc-400 text-[12px] font-mono">${slot}</td>
            <td class="px-5 py-2 text-right tabular-nums">${it.overlap_minutes}p</td>
            <td class="px-5 py-2 text-center"><span class="px-2 py-0.5 text-[11px] font-semibold rounded-full border ${meta.cls}">${meta.icon} ${it.status}</span></td>
        </tr>`;
    }).join("");
}

function complianceCard(label, count, cls) {
    return `<div class="rounded-lg border ${cls} p-3 text-center">
        <div class="text-[11px] font-semibold uppercase tracking-wider opacity-70">${label}</div>
        <div class="text-2xl font-bold tabular-nums mt-0.5">${count}</div>
    </div>`;
}

// ── Schedule edit/delete ──
function askEditSchedule(id, weekday, start, end) {
    STATE.pendingScheduleEditId = id;
    document.getElementById("sched-edit-weekday").value = weekday;
    document.getElementById("sched-edit-start").value = start;
    document.getElementById("sched-edit-end").value = end;
    document.getElementById("schedule-edit-modal").classList.remove("hidden");
}
function closeScheduleEditModal() {
    STATE.pendingScheduleEditId = null;
    document.getElementById("schedule-edit-modal").classList.add("hidden");
}
async function submitScheduleEdit() {
    const id = STATE.pendingScheduleEditId;
    if (!id) return;
    const body = {
        weekday: parseInt(document.getElementById("sched-edit-weekday").value),
        start_time: document.getElementById("sched-edit-start").value,
        end_time: document.getElementById("sched-edit-end").value,
    };
    const resp = await fetch(`/api/schedule/${id}?guild_id=${STATE.guildId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
    });
    if (resp.status === 401) { window.location.href = "/"; return; }
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        showToast(err.detail || "Sửa lịch thất bại", "error");
        return;
    }
    closeScheduleEditModal();
    showToast("✅ Đã sửa lịch", "success");
    loadScheduleSection(true);
}
async function askDeleteSchedule(id) {
    if (!confirm(`Xoá lịch entry #${id}?`)) return;
    const resp = await fetch(`/api/schedule/${id}?guild_id=${STATE.guildId}`, {
        method: "DELETE", credentials: "include",
    });
    if (resp.status === 401) { window.location.href = "/"; return; }
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        showToast(err.detail || "Xoá thất bại", "error");
        return;
    }
    showToast("🗑 Đã xoá lịch", "success");
    loadScheduleSection(true);
}


// ════════════════════════════════════════════════════════════════════════════
// ── LEAVE SECTION ──────────────────────────────────────────────────────────
// ════════════════════════════════════════════════════════════════════════════

function switchLeaveTab(tab) {
    STATE.leaveTab = tab;
    document.querySelectorAll(".leave-tab-btn").forEach((b) => b.classList.remove("active-tab"));
    document.querySelector(`[data-leave-tab="${tab}"]`)?.classList.add("active-tab");

    // Pending dùng card layout, các tab khác dùng table
    document.getElementById("leave-pane-pending").classList.toggle("hidden", tab !== "pending");
    document.getElementById("leave-pane-processed").classList.toggle("hidden", tab === "pending");

    loadLeaveSection(false);
}

async function loadLeaveSection(forceRefresh = false) {
    const tab = STATE.leaveTab;
    const params = new URLSearchParams({ guild_id: STATE.guildId, page: 1, page_size: 100 });
    if (tab === "pending") params.set("status", "pending");
    else if (tab === "approved") params.set("status", "approved");
    else if (tab === "rejected") params.set("status", "rejected");
    // 'all' không filter status

    const data = await apiFetch(`/api/leave/list?${params}`);
    if (!data) return;

    // Update tab counters
    const counts = data.counts || {};
    document.getElementById("leave-count-pending").textContent = counts.pending || 0;
    document.getElementById("leave-count-approved").textContent = counts.approved || 0;
    document.getElementById("leave-count-rejected").textContent = counts.rejected || 0;
    // Sidebar badge
    const badge = document.getElementById("leave-pending-badge");
    if (counts.pending > 0) {
        badge.classList.remove("hidden");
        badge.textContent = counts.pending;
    } else {
        badge.classList.add("hidden");
    }

    if (tab === "pending") {
        renderLeavePendingCards(data.items);
    } else {
        renderLeaveProcessedTable(data.items);
    }
    setTimeout(refreshIcons, 0);
}

function renderLeavePendingCards(items) {
    const pane = document.getElementById("leave-pane-pending");
    if (!items || items.length === 0) {
        pane.innerHTML = `<div class="bg-zinc-900/60 border border-zinc-800 rounded-xl p-10 text-center text-zinc-500 italic">Không có đơn nào đang chờ duyệt 🎉</div>`;
        return;
    }
    pane.innerHTML = items.map((req) => {
        const isResign = req.type === "resign";
        const typeLabel = isResign
            ? `<span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-red-500/10 text-red-400 border border-red-500/20">🚪 Out ngành</span>`
            : `<span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">🏖 Xin nghỉ</span>`;
        const dateRange = req.end_date
            ? `${formatDateShort(req.start_date)} → ${formatDateShort(req.end_date)} (${req.days_count} ngày)`
            : `Từ ${formatDateShort(req.start_date)} (vĩnh viễn)`;
        const adminOnly = STATE.isAdmin
            ? `<button onclick="askLeaveDecision(${req.id}, ${isResign})" class="h-9 px-4 rounded-lg bg-indigo-500 hover:bg-indigo-600 text-white text-[13px] font-medium transition-colors">⚖ Duyệt / Từ chối</button>`
            : `<span class="text-[12px] text-zinc-500 italic">Chỉ Admin mới được duyệt qua web</span>`;
        return `
            <div class="bg-zinc-900/60 border border-zinc-800 rounded-xl p-5 hover:border-zinc-700 transition-colors">
                <div class="flex items-start justify-between flex-wrap gap-3">
                    <div class="flex-1 min-w-[300px]">
                        <div class="flex items-center gap-2 mb-2 flex-wrap">
                            <span class="font-mono text-[12px] px-1.5 py-0.5 bg-zinc-950 border border-zinc-800 rounded text-zinc-400">#${req.id}</span>
                            ${typeLabel}
                            <span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">⏳ Chờ duyệt</span>
                        </div>
                        <h3 class="text-[15px] font-semibold text-white">${escHtml(req.username)}</h3>
                        <div class="text-[12px] text-zinc-500 mt-0.5 font-mono">${req.user_id}</div>
                        <div class="text-[13px] text-zinc-300 mt-2"><i data-lucide="calendar" class="icon-sm inline-block mr-1 text-zinc-500"></i> ${dateRange}</div>
                        <div class="mt-3 p-3 bg-zinc-950 border border-zinc-800 rounded-lg text-[13px] text-zinc-300">
                            <div class="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1">Lý do</div>
                            ${escHtml(req.reason)}
                        </div>
                        <div class="text-[11px] text-zinc-500 mt-2">Gửi lúc: ${formatDate(req.created_at)}</div>
                    </div>
                    <div class="flex flex-col items-end gap-2 shrink-0">
                        ${adminOnly}
                        <button onclick="loadLeaveHistory('${req.user_id}', '${escHtml(req.username)}')" class="h-8 px-3 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-[12px] transition-colors">📜 Lịch sử nghỉ</button>
                    </div>
                </div>
            </div>
        `;
    }).join("");
}

function renderLeaveProcessedTable(items) {
    const tbody = document.getElementById("leave-processed-body");
    if (!items || items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-zinc-500 italic py-10">Chưa có đơn nào</td></tr>`;
        return;
    }
    tbody.innerHTML = items.map((req) => {
        const isResign = req.type === "resign";
        const typeIcon = isResign ? "🚪" : "🏖";
        const dateRange = req.end_date
            ? `${formatDateShort(req.start_date)}→${formatDateShort(req.end_date)}`
            : `${formatDateShort(req.start_date)} (∞)`;
        const statusBadge = {
            approved: `<span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">✅ Duyệt</span>`,
            rejected: `<span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-red-500/10 text-red-400 border border-red-500/20">❌ Từ chối</span>`,
            pending: `<span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">⏳</span>`,
            cancelled: `<span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-zinc-700/40 text-zinc-400 border border-zinc-600">Huỷ</span>`,
        }[req.status] || req.status;
        const revertBtn = (STATE.isAdmin && req.status !== "pending")
            ? `<button onclick="askLeaveRevert(${req.id})" class="text-zinc-500 hover:text-amber-400 text-[12px]" title="Revert">⏪</button>`
            : "";
        return `<tr class="border-b border-zinc-800/60 hover:bg-zinc-800/30">
            <td class="px-5 py-2.5 font-mono text-[11px] text-zinc-400">#${req.id}</td>
            <td class="px-5 py-2.5"><div class="font-medium text-white">${escHtml(req.username)}</div><div class="text-[11px] text-zinc-500 font-mono">${req.user_id}</div></td>
            <td class="px-5 py-2.5">${typeIcon} ${isResign ? 'Out' : 'Nghỉ'}</td>
            <td class="px-5 py-2.5 text-zinc-400 text-[12px] font-mono">${dateRange}</td>
            <td class="px-5 py-2.5">${statusBadge}</td>
            <td class="px-5 py-2.5 text-[12px] text-zinc-400">${req.decided_by ? `<@${req.decided_by}>` : '—'}</td>
            <td class="px-5 py-2.5 text-right">${revertBtn}</td>
        </tr>`;
    }).join("");
}

// ── Leave decision modal ──
function askLeaveDecision(id, isResign) {
    STATE.pendingLeaveDecisionId = id;
    document.getElementById("leave-modal-title").textContent =
        isResign ? "⚖ Duyệt đơn xin out ngành" : "⚖ Duyệt đơn xin nghỉ phép";
    // Find the leave req in last loaded list to show info
    const card = document.querySelector(`#leave-pane-pending [onclick*="askLeaveDecision(${id}"]`)?.closest("div.bg-zinc-900\\/60");
    document.getElementById("leave-modal-info").innerHTML =
        isResign
            ? `⚠️ Đây là đơn <strong class="text-red-400">XIN OUT NGÀNH</strong>. Khi duyệt, hệ thống sẽ <strong>tự xoá lịch trực + gỡ tất cả role cleanup</strong>.`
            : `Đơn xin nghỉ phép tạm thời. Bot sẽ không nhắc trực trong khoảng nghỉ.`;
    document.getElementById("leave-decision-note").value = "";
    document.getElementById("leave-decision-modal").classList.remove("hidden");
}
function closeLeaveModal() {
    STATE.pendingLeaveDecisionId = null;
    document.getElementById("leave-decision-modal").classList.add("hidden");
}
async function submitLeaveDecision(approved) {
    const id = STATE.pendingLeaveDecisionId;
    if (!id) return;
    const note = document.getElementById("leave-decision-note").value.trim();
    if (!approved && !note) {
        document.getElementById("leave-note-required").classList.remove("hidden");
        showToast("Bắt buộc phải có ghi chú khi từ chối", "error");
        return;
    }
    const resp = await fetch(`/api/leave/${id}/decision?guild_id=${STATE.guildId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ approved, note }),
    });
    if (resp.status === 401) { window.location.href = "/"; return; }
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        showToast(err.detail || "Duyệt thất bại", "error");
        return;
    }
    closeLeaveModal();
    showToast(approved ? "✅ Đã duyệt — bot sẽ DM member" : "❌ Đã từ chối — bot sẽ DM member", "success");
    loadLeaveSection(true);
}

// ── Leave revert modal ──
function askLeaveRevert(id) {
    STATE.pendingLeaveRevertId = id;
    document.getElementById("leave-revert-reason").value = "";
    document.getElementById("leave-revert-modal").classList.remove("hidden");
}
function closeRevertModal() {
    STATE.pendingLeaveRevertId = null;
    document.getElementById("leave-revert-modal").classList.add("hidden");
}
async function submitRevert() {
    const id = STATE.pendingLeaveRevertId;
    if (!id) return;
    const reason = document.getElementById("leave-revert-reason").value.trim();
    if (!reason) {
        showToast("Bắt buộc phải có lý do revert", "error");
        return;
    }
    const resp = await fetch(`/api/leave/${id}/revert?guild_id=${STATE.guildId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ reason }),
    });
    if (resp.status === 401) { window.location.href = "/"; return; }
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        showToast(err.detail || "Revert thất bại", "error");
        return;
    }
    const data = await resp.json();
    closeRevertModal();
    showToast(data.warning || "⏪ Đã revert đơn về PENDING", "info");
    loadLeaveSection(true);
}

async function loadLeaveHistory(userId, username) {
    const data = await apiFetch(`/api/leave/user/${userId}/history?guild_id=${STATE.guildId}`);
    if (!data) return;
    const items = data.items || [];
    const lines = items.map((r) => {
        const range = r.end_date ? `${formatDateShort(r.start_date)}→${formatDateShort(r.end_date)}` : formatDateShort(r.start_date);
        const statusEmoji = { approved: "✅", rejected: "❌", pending: "⏳" }[r.status] || "•";
        return `${statusEmoji} ${r.type} · ${range} — ${r.reason.slice(0, 60)}`;
    }).join("\n");
    alert(`📜 Lịch sử ${username}:\n\n${lines || 'Chưa có đơn nào trước đó'}`);
}


// ════════════════════════════════════════════════════════════════════════════
// ── ATTENDANCE SECTION (chấm công nhân viên) ──────────────────────────────
// ════════════════════════════════════════════════════════════════════════════

async function loadAttendance(forceRefresh = false) {
    const params = buildParams();
    if (!params) return;
    const data = await apiFetch(`/api/dashboard/attendance?${params}`);
    if (!data) return;

    STATE.attendanceData = data;

    // Toggle Discord ID column visibility
    document.querySelectorAll(".mod-only-col").forEach((el) =>
        el.classList.toggle("hidden", !data.is_mod_view));

    // Render summary
    const s = data.summary;
    const summaryEl = document.getElementById("attendance-summary");
    summaryEl.innerHTML = `
        ${attendanceCard("👥 Tổng thành viên", s.total_members, "indigo")}
        ${attendanceCard("🟢 Đã trực", s.active_members, "emerald")}
        ${attendanceCard("📋 Tổng ca", s.total_sessions.toLocaleString("vi-VN"), "purple")}
        ${attendanceCard("⏱ Tổng giờ", s.total_hhmm, "amber")}
        ${attendanceCard("📊 TB/người", minutesToHhmm(s.avg_minutes_per_member), "blue")}
    `;

    // Apply current filter+sort then render table
    filterAttendance();
    setTimeout(refreshIcons, 0);
}

function attendanceCard(label, value, colorName) {
    const palette = {
        indigo:  "text-indigo-400 bg-indigo-500/10 border-indigo-500/20",
        emerald: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
        purple:  "text-purple-400 bg-purple-500/10 border-purple-500/20",
        amber:   "text-amber-400 bg-amber-500/10 border-amber-500/20",
        blue:    "text-blue-400 bg-blue-500/10 border-blue-500/20",
        red:     "text-red-400 bg-red-500/10 border-red-500/20",
    };
    return `<div class="rounded-lg border ${palette[colorName] || palette.indigo} p-3">
        <div class="text-[11px] font-semibold uppercase tracking-wider opacity-80">${label}</div>
        <div class="text-2xl font-bold tabular-nums mt-0.5 text-white">${value}</div>
    </div>`;
}

function filterAttendance() {
    if (!STATE.attendanceData) return;
    const items = STATE.attendanceData.items || [];
    const search = (document.getElementById("attendance-search")?.value || "").trim().toLowerCase();
    const status = document.getElementById("attendance-filter-status")?.value || "all";

    let filtered = items.filter((it) => {
        // Search filter
        if (search) {
            const name = it.username.toLowerCase();
            const uid = (it.user_id || "").toLowerCase();
            if (!name.includes(search) && !uid.includes(search)) return false;
        }
        // Status filter
        if (status === "active" && it.session_count === 0) return false;
        if (status === "inactive" && it.session_count > 0) return false;
        if (status === "has_schedule" && !it.has_schedule) return false;
        if (status === "no_schedule" && it.has_schedule) return false;
        return true;
    });

    STATE.attendanceFiltered = filtered;
    sortAttendance();   // sort + render
}

function sortAttendance() {
    if (!STATE.attendanceFiltered) return;
    const sortBy = document.getElementById("attendance-sort")?.value || "total_desc";
    const list = [...STATE.attendanceFiltered];
    const cmp = {
        total_desc:    (a, b) => b.total_minutes - a.total_minutes,
        total_asc:     (a, b) => a.total_minutes - b.total_minutes,
        sessions_desc: (a, b) => b.session_count - a.session_count,
        sessions_asc:  (a, b) => a.session_count - b.session_count,
        rate_desc:     (a, b) => (b.compliance.rate ?? -1) - (a.compliance.rate ?? -1),
        rate_asc:      (a, b) => (a.compliance.rate ?? 999) - (b.compliance.rate ?? 999),
        name_asc:      (a, b) => a.username.toLowerCase().localeCompare(b.username.toLowerCase()),
        last_log_desc: (a, b) => new Date(b.last_log_at || 0) - new Date(a.last_log_at || 0),
        missed_desc:   (a, b) => b.compliance.missed - a.compliance.missed,
    }[sortBy] || ((a, b) => 0);
    list.sort(cmp);
    renderAttendanceTable(list);
}

function renderAttendanceTable(items) {
    const tbody = document.getElementById("attendance-body");
    const countEl = document.getElementById("attendance-count");

    if (!items || items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="text-center text-zinc-500 italic py-10">Không có nhân viên nào khớp filter</td></tr>`;
        countEl.textContent = "";
        return;
    }

    countEl.textContent = `Hiển thị ${items.length} / ${STATE.attendanceData.items.length} nhân viên`;

    tbody.innerHTML = items.map((it, idx) => {
        // Compliance badge
        let complCell;
        if (!it.has_schedule) {
            complCell = `<span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-zinc-800 text-zinc-500 border border-zinc-700" title="Chưa đăng ký lịch trực">— Chưa đăng ký</span>`;
        } else if (it.compliance.rate === null) {
            complCell = `<span class="text-zinc-600 text-[11px]">—</span>`;
        } else {
            const rate = it.compliance.rate;
            const cls = rate >= 90 ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                       : rate >= 70 ? "text-amber-400 bg-amber-500/10 border-amber-500/20"
                       : "text-red-400 bg-red-500/10 border-red-500/20";
            const tip = `Đúng giờ: ${it.compliance.on_time} • Trễ: ${it.compliance.late} • Vắng: ${it.compliance.missed}`;
            complCell = `<div class="inline-flex items-center gap-1.5 px-2 py-0.5 text-[11px] font-semibold rounded-full border ${cls}" title="${tip}">
                ${rate.toFixed(0)}%
                <span class="text-[10px] opacity-70">(${it.compliance.on_time}/${it.compliance.on_time + it.compliance.late + it.compliance.missed})</span>
            </div>`;
        }

        // Last log
        let lastLogCell;
        if (!it.last_log_at) {
            lastLogCell = `<span class="text-red-400 text-[12px]">Chưa có log nào</span>`;
        } else {
            const days = it.last_log_age_days;
            const ageLabel = days === 0 ? "Hôm nay" : days === 1 ? "Hôm qua" : `${days} ngày trước`;
            const ageCls = days <= 1 ? "text-emerald-400" : days <= 7 ? "text-zinc-300" : "text-amber-400";
            lastLogCell = `<div class="text-[12px] ${ageCls}">${ageLabel}</div><div class="text-[10px] text-zinc-500 font-mono">${formatDate(it.last_log_at)}</div>`;
        }

        // Status icons in name column
        const statusIcons = [];
        if (it.session_count === 0) statusIcons.push(`<span title="Chưa trực trong kỳ" class="text-red-400">🚫</span>`);
        if (!it.has_schedule) statusIcons.push(`<span title="Chưa đăng ký lịch" class="text-amber-400">⚠</span>`);

        const idCell = it.user_id
            ? `<td class="px-5 py-3 mod-only-col text-zinc-500 font-mono text-[11px]">${it.user_id}</td>`
            : `<td class="px-5 py-3 mod-only-col"></td>`;

        // Quick action: click row → mở detail modal
        const onclick = `onclick="openAttendanceDetail('${it.user_id || ''}', '${escHtml(it.username).replace(/'/g, '&#39;')}')"`;

        return `<tr class="border-b border-zinc-800/60 hover:bg-zinc-800/40 transition-colors cursor-pointer" ${onclick}>
            <td class="px-5 py-3 text-zinc-500 tabular-nums text-[12px]">${idx + 1}</td>
            <td class="px-5 py-3">
                <div class="font-medium text-white">${escHtml(it.username)} ${statusIcons.join(" ")}</div>
            </td>
            ${idCell}
            <td class="px-5 py-3 text-right tabular-nums">
                <span class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">${it.session_count}</span>
            </td>
            <td class="px-5 py-3 text-right tabular-nums text-zinc-200">${it.total_hhmm}</td>
            <td class="px-5 py-3 text-right tabular-nums text-zinc-400 text-[12px]">${it.avg_minutes ? minutesToHhmm(it.avg_minutes) : '—'}</td>
            <td class="px-5 py-3 text-center">${complCell}</td>
            <td class="px-5 py-3">${lastLogCell}</td>
            <td class="px-5 py-3 text-right">
                <button onclick="event.stopPropagation(); openAttendanceDetail('${it.user_id || ''}', '${escHtml(it.username).replace(/'/g, '&#39;')}')"
                        class="text-zinc-500 hover:text-indigo-400 text-[12px]" title="Xem chi tiết">
                    <i data-lucide="eye" class="icon-sm"></i>
                </button>
            </td>
        </tr>`;
    }).join("");
    setTimeout(refreshIcons, 0);
}

// ── Detail modal: tabs Tổng quan / Theo ngày ──
function switchAttDetailTab(tab) {
    document.querySelectorAll(".att-tab-btn").forEach((b) => b.classList.remove("active-tab"));
    document.querySelector(`[data-att-tab="${tab}"]`)?.classList.add("active-tab");
    document.getElementById("att-pane-overview").classList.toggle("hidden", tab !== "overview");
    document.getElementById("att-pane-daily").classList.toggle("hidden", tab !== "daily");
    if (tab === "daily" && STATE.attendanceDetailUid) {
        loadAttendanceDaily(STATE.attendanceDetailUid);
    }
    setTimeout(refreshIcons, 0);
}

async function loadAttendanceDaily(userId) {
    if (!userId) {
        document.getElementById("att-daily-timeline").innerHTML =
            `<div class="text-center text-zinc-500 italic py-10">Discord ID bị ẩn — không tải được dữ liệu chi tiết theo ngày</div>`;
        return;
    }
    const period = document.getElementById("period-select").value;
    const params = new URLSearchParams({ guild_id: STATE.guildId, user_id: userId, period });
    if (period === "custom") {
        const from = document.getElementById("date-from").value;
        const to = document.getElementById("date-to").value;
        if (from && to) {
            params.set("date_from", from);
            params.set("date_to", to);
        }
    }

    document.getElementById("att-daily-timeline").innerHTML =
        `<div class="text-center text-zinc-500 italic py-10">Đang tải…</div>`;

    const data = await apiFetch(`/api/dashboard/attendance/daily?${params}`);
    if (!data) return;

    // Summary cards
    const c = data.summary.counters;
    const sumEl = document.getElementById("att-daily-summary");
    sumEl.innerHTML = `
        ${attendanceCard("✅ Đúng giờ", c.on_time || 0, "emerald")}
        ${attendanceCard("⏰ Trễ giờ", c.late || 0, "amber")}
        ${attendanceCard("🚫 Vắng", c.missed || 0, "red")}
        ${attendanceCard("🆓 Ngoài lịch", c.off_schedule || 0, "blue")}
        ${attendanceCard("🏖 Nghỉ phép", c.on_leave || 0, "purple")}
        ${attendanceCard("⏳ Không lịch", c.no_schedule || 0, "indigo")}
    `;

    // Build timeline (1 day = 1 card)
    const STATUS_META = {
        on_time:      { icon: "✅", label: "Đúng giờ",       cls: "border-emerald-500/40 bg-emerald-500/5" },
        late:         { icon: "⏰", label: "Trễ giờ",         cls: "border-amber-500/40 bg-amber-500/5" },
        missed:       { icon: "🚫", label: "Vắng",            cls: "border-red-500/40 bg-red-500/5" },
        off_schedule: { icon: "🆓", label: "Trực ngoài lịch", cls: "border-blue-500/40 bg-blue-500/5" },
        on_leave:     { icon: "🏖", label: "Nghỉ phép",       cls: "border-purple-500/40 bg-purple-500/5" },
        no_schedule:  { icon: "⏳", label: "Không có lịch",   cls: "border-zinc-700 bg-zinc-800/20" },
    };
    const SOURCE = { ocr: "📸", forward: "💬", message: "📨", manual: "✍️" };

    const timeline = data.days.map((day) => {
        const meta = STATUS_META[day.status] || STATUS_META.no_schedule;
        const todayBadge = day.is_today
            ? `<span class="ml-2 px-1.5 py-0.5 text-[10px] font-bold rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">HÔM NAY</span>`
            : "";
        const futureBadge = day.is_future
            ? `<span class="ml-2 px-1.5 py-0.5 text-[10px] font-medium rounded bg-zinc-800 text-zinc-500 border border-zinc-700">CHƯA TỚI</span>`
            : "";
        const dateStr = formatDateLong(day.date);

        // Schedule rendering
        let scheduleHtml = "";
        if (day.schedules.length > 0) {
            const items = day.schedules.map((s) => {
                const cross = s.crosses_midnight ? " 🌙" : "";
                return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 text-[11px] font-mono">
                    📅 ${s.start_time}–${s.end_time}${cross}
                </span>`;
            }).join(" ");
            scheduleHtml = `<div class="text-[11px] text-zinc-500 mb-1">Lịch đăng ký:</div><div class="mb-2">${items}</div>`;
        } else if (day.status !== "on_leave") {
            scheduleHtml = `<div class="text-[11px] text-zinc-600 italic mb-2">Không có lịch trực hôm nay</div>`;
        }

        // Leave rendering
        let leaveHtml = "";
        if (day.leave) {
            const lr = day.leave;
            const range = lr.end_date
                ? `${formatDateShort(lr.start_date)}→${formatDateShort(lr.end_date)}`
                : `từ ${formatDateShort(lr.start_date)}`;
            const typeLabel = lr.type === "resign" ? "🚪 Out ngành" : "🏖 Nghỉ phép";
            leaveHtml = `<div class="px-3 py-2 rounded-lg bg-purple-500/10 border border-purple-500/30 text-[12px] text-purple-200 mt-2">
                ${typeLabel} <span class="text-zinc-400 font-mono ml-1">(${range})</span><br>
                <span class="text-zinc-300 text-[11px]">"${escHtml(lr.reason).slice(0, 200)}${lr.reason.length > 200 ? '…' : ''}"</span>
            </div>`;
        }

        // Logs rendering
        let logsHtml = "";
        if (day.logs.length > 0) {
            const items = day.logs.map((log) => {
                const linkBadge = log.schedule_id
                    ? `<span class="text-[10px] text-emerald-400 ml-1" title="Khớp với lịch đăng ký">🔗</span>`
                    : `<span class="text-[10px] text-zinc-500 ml-1" title="Ngoài lịch đăng ký">🆓</span>`;
                return `<div class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-950 border border-zinc-800 text-[12px]">
                    <span class="font-mono text-[10px] text-zinc-500">#${log.id}</span>
                    <span class="text-zinc-300 tabular-nums">${formatTime(log.started_at)}–${formatTime(log.ended_at)}</span>
                    <span class="text-[14px]" title="${log.source}">${SOURCE[log.source] || "•"}</span>
                    <span class="ml-auto px-1.5 py-0.5 text-[10px] font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">${minutesToHhmm(log.duration_minutes)}</span>
                    ${linkBadge}
                </div>`;
            }).join("");
            logsHtml = `<div class="text-[11px] text-zinc-500 mt-2 mb-1">Đã chấm công (${day.logs.length} ca):</div>
                <div class="space-y-1">${items}</div>`;
        }

        // Compliance bar (nếu có lịch)
        let progressHtml = "";
        if (day.scheduled_minutes > 0 && day.status !== "on_leave") {
            const pct = day.compliance_pct ?? 0;
            const barCls = pct >= 100 ? "bg-emerald-500" : pct >= 70 ? "bg-amber-500" : "bg-red-500";
            progressHtml = `<div class="mt-2">
                <div class="flex items-center justify-between text-[10px] text-zinc-500 mb-1">
                    <span>Tiến độ ngày: <strong class="text-zinc-300">${minutesToHhmm(day.worked_minutes)}</strong> / ${minutesToHhmm(day.scheduled_minutes)}</span>
                    <span class="font-semibold tabular-nums ${pct >= 100 ? 'text-emerald-400' : pct >= 70 ? 'text-amber-400' : 'text-red-400'}">${pct.toFixed(0)}%</span>
                </div>
                <div class="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                    <div class="h-full ${barCls} rounded-full transition-all" style="width: ${Math.min(pct, 100)}%"></div>
                </div>
            </div>`;
        } else if (day.worked_minutes > 0) {
            // Off-schedule but worked
            progressHtml = `<div class="mt-2 text-[11px] text-blue-400">
                ⏱ Đã trực <strong>${minutesToHhmm(day.worked_minutes)}</strong> ngoài lịch đăng ký
            </div>`;
        }

        return `<div class="rounded-xl border ${meta.cls} p-3.5 transition-colors hover:bg-opacity-30">
            <div class="flex items-center justify-between flex-wrap gap-2 mb-2">
                <div class="flex items-center gap-2">
                    <span class="text-2xl">${meta.icon}</span>
                    <div>
                        <div class="font-semibold text-white text-[14px]">${day.weekday_label}, ${dateStr}${todayBadge}${futureBadge}</div>
                        <div class="text-[11px] text-zinc-400 mt-0.5">${meta.label}</div>
                    </div>
                </div>
            </div>
            ${scheduleHtml}
            ${logsHtml}
            ${leaveHtml}
            ${progressHtml}
        </div>`;
    }).join("");

    document.getElementById("att-daily-timeline").innerHTML = timeline || `<div class="text-center text-zinc-500 italic py-10">Không có dữ liệu</div>`;
    setTimeout(refreshIcons, 0);
}

function formatDateLong(iso) {
    if (!iso) return "—";
    const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
    return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
}

// ── Detail modal ──
function openAttendanceDetail(userId, username) {
    const items = STATE.attendanceData?.items || [];
    const target = items.find((it) =>
        (it.user_id && it.user_id === userId) || it.username === username
    );
    if (!target) return;

    STATE.attendanceDetailUid = userId || null;

    document.getElementById("att-detail-name").textContent = target.username;
    document.getElementById("att-detail-uid").textContent = target.user_id || "(Discord ID ẩn — chỉ Mod+ thấy)";

    // Stats grid
    document.getElementById("att-detail-stats").innerHTML = `
        ${attendanceCard("📋 Số ca", target.session_count, "indigo")}
        ${attendanceCard("⏱ Tổng giờ", target.total_hhmm, "emerald")}
        ${attendanceCard("📊 TB/ca", target.avg_minutes ? minutesToHhmm(target.avg_minutes) : "—", "amber")}
        ${attendanceCard("🏆 Dài nhất", target.longest_minutes ? minutesToHhmm(target.longest_minutes) : "—", "purple")}
    `;

    // Compliance breakdown
    let complHtml;
    if (!target.has_schedule) {
        complHtml = `<div class="col-span-3 rounded-lg border border-zinc-700 bg-zinc-800/40 p-3 text-center text-zinc-400 text-[13px]">
            ⚠ Nhân viên này <strong>chưa đăng ký lịch trực</strong> — không tính tỷ lệ tuân thủ.
        </div>`;
    } else {
        const c = target.compliance;
        const total = c.on_time + c.late + c.missed;
        const rate = c.rate ?? 0;
        complHtml = `
            ${attendanceCard("✅ Đúng giờ", c.on_time, "emerald")}
            ${attendanceCard("⏰ Trễ giờ", c.late, "amber")}
            ${attendanceCard("🚫 Vắng", c.missed, "red")}
        `;
        complHtml += `<div class="col-span-3 rounded-lg border border-indigo-500/20 bg-indigo-500/5 p-3 text-center">
            <div class="text-[11px] font-semibold uppercase tracking-wider text-indigo-300/70">Tỷ lệ đúng giờ trong kỳ</div>
            <div class="text-3xl font-bold text-indigo-300 tabular-nums mt-1">${rate ? rate.toFixed(0) + '%' : '—'}</div>
            <div class="text-[11px] text-zinc-400 mt-1">${c.on_time}/${total} ca đúng giờ ${c.on_leave > 0 ? `· ${c.on_leave} ngày nghỉ phép` : ''}</div>
        </div>`;
    }
    document.getElementById("att-detail-compliance").innerHTML = complHtml;

    // Logs in period — fetch
    loadAttendanceUserLogs(userId, username);

    // Default tab: Tổng quan
    switchAttDetailTab("overview");

    document.getElementById("attendance-detail-modal").classList.remove("hidden");
    setTimeout(refreshIcons, 0);
}

async function loadAttendanceUserLogs(userId, username) {
    const period = document.getElementById("period-select").value;
    const params = new URLSearchParams({
        guild_id: STATE.guildId,
        period,
        page: 1,
        page_size: 30,
    });
    if (userId) params.set("user_id", userId);

    const data = await apiFetch(`/api/dashboard/logs?${params}`);
    const logsEl = document.getElementById("att-detail-logs");
    if (!data || !data.items || data.items.length === 0) {
        logsEl.innerHTML = `<div class="text-center text-zinc-500 italic py-6">Chưa có ca trực nào trong kỳ</div>`;
        return;
    }
    const SOURCE = { ocr: "📸", forward: "💬", message: "📨", manual: "✍️" };
    logsEl.innerHTML = data.items.map((log) => {
        const src = SOURCE[log.source] || "•";
        return `<div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-zinc-950 border border-zinc-800 hover:border-zinc-700 transition-colors">
            <span class="font-mono text-[11px] text-zinc-500 shrink-0">#${log.id}</span>
            <span class="text-[12px] text-zinc-300 tabular-nums shrink-0">${formatDate(log.started_at)} → ${formatDate(log.ended_at)}</span>
            <span class="ml-auto px-2 py-0.5 text-[10px] font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">${log.duration_hhmm}</span>
            <span class="text-[14px]" title="${log.source}">${src}</span>
        </div>`;
    }).join("");
}

function closeAttendanceDetail() {
    STATE.attendanceDetailUid = null;
    document.getElementById("attendance-detail-modal").classList.add("hidden");
}

function gotoLogsForUser() {
    const uid = STATE.attendanceDetailUid;
    closeAttendanceDetail();
    if (uid) STATE.logsUserFilter = uid;
    switchSection("logs");
}


// ════════════════════════════════════════════════════════════════════════════
// ── WEBSOCKET (real-time updates) ──────────────────────────────────────────
// ════════════════════════════════════════════════════════════════════════════

function connectWS() {
    if (!STATE.guildId) return;
    if (STATE.ws && STATE.ws.readyState === WebSocket.OPEN) return;
    if (STATE.ws) { try { STATE.ws.close(); } catch (_) {} }

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${window.location.host}/ws?guild_id=${STATE.guildId}`;
    setWsStatus("connecting", "amber");

    const ws = new WebSocket(url);
    STATE.ws = ws;

    ws.onopen = () => {
        STATE.wsReconnectDelay = 1000;
        setWsStatus("online", "emerald");
        // Ping mỗi 25s để giữ connection alive (tránh proxy timeout)
        STATE.wsPingTimer = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) ws.send("ping");
        }, 25000);
    };

    ws.onmessage = (e) => {
        if (e.data === "pong") return;
        try {
            const event = JSON.parse(e.data);
            handleWsEvent(event);
        } catch (err) {
            console.warn("WS parse fail:", err);
        }
    };

    ws.onclose = () => {
        clearInterval(STATE.wsPingTimer);
        setWsStatus("offline", "zinc");
        // Reconnect with exponential backoff (max 30s)
        STATE.wsReconnectTimer = setTimeout(connectWS, STATE.wsReconnectDelay);
        STATE.wsReconnectDelay = Math.min(STATE.wsReconnectDelay * 2, 30000);
    };

    ws.onerror = (e) => {
        console.warn("WS error:", e);
    };
}

function setWsStatus(text, color) {
    const dot = document.getElementById("ws-dot");
    const status = document.getElementById("ws-status");
    if (!dot || !status) return;
    status.textContent = text;
    dot.className = `w-1.5 h-1.5 rounded-full bg-${color}-${color === 'zinc' ? '700' : '400'}`;
    if (color === "emerald") dot.classList.add("animate-pulse");
}

function handleWsEvent(event) {
    console.log("[WS]", event);
    // Auto refresh section nếu liên quan
    switch (event.type) {
        case "schedule_updated":
        case "schedule_deleted":
            if (STATE.currentSection === "schedule") loadScheduleSection(false);
            break;
        case "leave_decided":
        case "leave_reverted":
        case "leave_created":
            // Refresh sidebar badge
            apiFetch(`/api/leave/list?guild_id=${STATE.guildId}&page_size=1`).then((d) => {
                const counts = d?.counts || {};
                document.getElementById("leave-count-pending").textContent = counts.pending || 0;
                document.getElementById("leave-count-approved").textContent = counts.approved || 0;
                document.getElementById("leave-count-rejected").textContent = counts.rejected || 0;
                const badge = document.getElementById("leave-pending-badge");
                if (counts.pending > 0) { badge.classList.remove("hidden"); badge.textContent = counts.pending; }
                else badge.classList.add("hidden");
            });
            if (STATE.currentSection === "leave") loadLeaveSection(false);
            break;
    }
}


// ── Helpers thêm ──
function formatDateShort(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });
}
function formatTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

// ── Connect WS sau khi guild được chọn ──
const __originalLoadGuilds = loadGuilds;
loadGuilds = async function() {
    await __originalLoadGuilds.apply(this, arguments);
    if (STATE.guildId) connectWS();
};
const __originalOnGuildChange = onGuildChange;
onGuildChange = function() {
    __originalOnGuildChange.apply(this, arguments);
    if (STATE.ws) { try { STATE.ws.close(); } catch(_){} }
    connectWS();
};
