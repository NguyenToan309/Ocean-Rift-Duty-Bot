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
    document.querySelectorAll(".mod-only").forEach((el) => el.classList.toggle("hidden", !STATE.isMod));
    document.querySelectorAll(".nav-mod").forEach((el) => el.classList.toggle("hidden", !STATE.isMod));
    document.querySelectorAll(".logs-title-mod").forEach((el) => el.classList.toggle("hidden", !STATE.isMod));
    document.querySelectorAll(".logs-title-member").forEach((el) => el.classList.toggle("hidden", STATE.isMod));

    // Show content
    document.getElementById("content-area").classList.remove("hidden");
    loadCurrentSection();
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
    document.querySelectorAll(".mod-only").forEach((el) => el.classList.toggle("hidden", !STATE.isMod));
    document.querySelectorAll(".nav-mod").forEach((el) => el.classList.toggle("hidden", !STATE.isMod));
    document.querySelectorAll(".logs-title-mod").forEach((el) => el.classList.toggle("hidden", !STATE.isMod));
    document.querySelectorAll(".logs-title-member").forEach((el) => el.classList.toggle("hidden", STATE.isMod));
    // Switch to overview if currently on audit but no longer admin
    if (!STATE.isMod && STATE.currentSection === "audit") {
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

    ["overview", "ranking", "logs", "audit"].forEach((s) => {
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

    // Headline: ngắn gọn về kỳ
    const hours = Math.floor(totalMinutes / 60);
    const mins = totalMinutes % 60;
    document.getElementById("hero-total-hours").textContent =
        hours > 0 ? `${hours}g ${mins.toString().padStart(2, "0")}p` : `${mins}p`;

    document.getElementById("hero-headline").textContent =
        totalSessions > 0
            ? `${totalSessions} ca trực · ${totalMembers} thành viên tham gia`
            : "Chưa có ca trực nào trong kỳ này";

    const top5El = document.getElementById("top5-list");
    if (!data.top5 || data.top5.length === 0) {
        top5El.innerHTML = `<p class="empty-msg">Chưa có dữ liệu trong khoảng thời gian này</p>`;
        return;
    }

    const maxMin = Math.max(...data.top5.map(u => u.total_minutes));
    const rankColor = ["text-yellow-400", "text-zinc-300", "text-orange-400"];
    top5El.innerHTML = data.top5.map((u, i) => {
        const colorCls = rankColor[i] || "text-zinc-500";
        const pct = maxMin > 0 ? Math.round((u.total_minutes / maxMin) * 100) : 0;
        return `
            <div class="relative grid grid-cols-[28px_1fr_auto_auto] items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-zinc-800/40 transition-colors overflow-hidden">
                <div class="top5-bar" style="--bar: ${pct}%"></div>
                <div class="text-center font-semibold text-[13px] tabular-nums ${colorCls} relative z-10">${i + 1}</div>
                <div class="font-medium text-white text-[14px] truncate relative z-10">${escHtml(u.username)}</div>
                <div class="text-[13px] text-zinc-300 tabular-nums relative z-10">${u.total_hhmm}</div>
                <div class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 relative z-10">${u.sessions} ca</div>
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

    const gradient = ctx.createLinearGradient(0, 0, 0, 260);
    gradient.addColorStop(0, "rgba(99,102,241,0.32)");
    gradient.addColorStop(1, "rgba(99,102,241,0)");

    STATE.chart = new Chart(ctx, {
        type: "line",
        data: {
            labels: data.labels,
            datasets: [{
                label: "Thời gian trực (phút)",
                data: data.data,
                borderColor: "rgba(99,102,241,1)",
                backgroundColor: gradient,
                borderWidth: 2,
                tension: 0.4,
                fill: true,
                pointRadius: 3,
                pointHoverRadius: 6,
                pointBackgroundColor: "rgba(99,102,241,1)",
                pointBorderColor: "#16181E",
                pointBorderWidth: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "rgba(11,12,17,0.96)",
                    titleColor: "#FAFAFA",
                    titleFont: { weight: "600", size: 12 },
                    bodyColor: "#D4D5D8",
                    bodyFont: { size: 12 },
                    borderColor: "rgba(99,102,241,0.4)",
                    borderWidth: 1,
                    padding: 10,
                    cornerRadius: 8,
                    displayColors: false,
                    callbacks: {
                        label: (ctx) => `${ctx.parsed.y} phút · ${minutesToHhmm(ctx.parsed.y)}`,
                    },
                },
            },
            scales: {
                x: {
                    ticks: { color: "#6A6D76", font: { size: 11 } },
                    grid: { display: false },
                    border: { display: false },
                },
                y: {
                    ticks: { color: "#6A6D76", font: { size: 11 }, padding: 8 },
                    grid: { color: "rgba(255,255,255,0.04)" },
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

// Cache user_id từ guild list (sub claim không có sẵn vì cookie HttpOnly)
function currentUserId() {
    // Server cần expose; tạm thời lấy từ localStorage nếu set sau login
    return localStorage.getItem("user_id");
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
            return null;
        }
        return await resp.json();
    } catch (e) {
        showToast("Mất kết nối server", "error");
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
