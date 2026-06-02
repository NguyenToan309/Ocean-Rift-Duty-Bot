/**
 * api.ts — Typed fetch client cho FastAPI backend.
 * Cookies HttpOnly tự gửi qua credentials: 'include'.
 *
 * Mọi method dưới đây sẽ adapt response shape của backend sang shape
 * mà UI mong đợi (vd: backend trả `{guilds: [...]}` → trả về `Guild[]`).
 * Khi backend thay đổi response, CHỈ phải sửa file này.
 */

export class APIError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

type FetchOpts = {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | undefined | null>;
};

function buildUrl(path: string, query?: FetchOpts['query']): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null) continue;
    params.append(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export async function apiFetch<T = unknown>(
  path: string,
  opts: FetchOpts = {},
): Promise<T> {
  const url = buildUrl(path, opts.query);
  const init: RequestInit = {
    method: opts.method || 'GET',
    credentials: 'include',
    headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
    signal: opts.signal,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  };

  let resp: Response;
  try {
    resp = await fetch(url, init);
  } catch (err) {
    throw new APIError(0, `Lỗi mạng: ${(err as Error).message}`);
  }

  if (resp.status === 204) return undefined as T;

  const contentType = resp.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');
  const payload = isJson ? await resp.json().catch(() => ({})) : await resp.text();

  if (!resp.ok) {
    const detail =
      (isJson && (payload.detail || payload.error)) ||
      (typeof payload === 'string' ? payload : `HTTP ${resp.status}`);
    throw new APIError(resp.status, String(detail));
  }
  return payload as T;
}

// ============================================================
// TYPES — shape mà UI sử dụng (đã được adapt từ backend response)
// ============================================================

// IMPORTANT: Discord user_id là 64-bit (vd 1119880453671899196) — vượt giới hạn
// JS Number (2^53). Phải giữ STRING xuyên suốt. KHÔNG được Number() conversion.

export interface Me {
  user_id: string;
  discord_id: string;
  username: string;
  global_name: string | null;
  avatar_url: string | null;
  is_2fa_enabled: boolean;
  is_bot_owner: boolean;
}

// ----- ADMIN OVERVIEW (bot owner only) -----
export interface AdminInstallation {
  guild_id: string;
  guild_name: string;
  icon_url: string | null;
  banner_url: string | null;
  member_count: number | null;
  presence_count: number | null;
  boost_level: number | null;
  boost_count: number | null;
  features: string[];
  preferred_locale: string | null;
  owner: { id: string; username: string; avatar_url: string | null } | null;
  inviter: { id: string; username: string } | null;
  bot_joined_at: string | null;
  bot_permissions: string | null;
  setup_status: 'configured' | 'pending';
  setup_at: string | null;
  log_channel_id: string | null;
  timezone: string | null;
  is_active: boolean | null;
  role_map_count: number;
  duty_log_count: number;
  last_duty_log_at: string | null;
  unique_users_logged: number;
}

export interface AdminAuthorization {
  discord_id: string;
  username: string;
  discriminator: string | null;
  avatar_url: string | null;
  first_login_at: string | null;
  last_login_at: string | null;
  last_login_ip: string | null;
  is_2fa_enabled: boolean;
  failed_login_attempts: number;
  locked_until: string | null;
  total_logins: number;
  last_action_at: string | null;
}

export interface AdminOverview {
  installations: AdminInstallation[];
  authorizations: AdminAuthorization[];
  totals: {
    total_installs: number;
    configured: number;
    pending: number;
    total_authorizations: number;
    with_2fa: number;
    active_last_7d: number;
    total_duty_logs: number;
    unique_users_global: number;
  };
  fetched_at: string;
  cache_hit: boolean;
}

export interface Guild {
  id: string;
  name: string;
  icon_url: string | null;
  role: 'ADMIN' | 'MOD' | 'MEMBER';
  is_admin: boolean;
  is_mod: boolean;
  timezone?: string;
}

export interface OverviewStats {
  total_sessions: number;
  total_minutes: number;
  active_members: number;
  total_members: number;
  avg_minutes_per_session: number;
  compliance_rate: number | null;
  top_users: Array<{
    user_id: string;
    username: string;
    avatar_url: string | null;
    total_minutes: number;
    session_count: number;
  }>;
}

export interface ChartPoint {
  date: string;
  value: number;
}

export interface RankingRow {
  rank: number;
  user_id: string;
  username: string;
  avatar_url: string | null;
  total_minutes: number;
  session_count: number;
}

export interface AttendanceUser {
  user_id: string;
  username: string;
  avatar_url: string | null;
  // Giờ trực thường (luôn có)
  session_count: number;
  total_minutes: number;
  avg_minutes: number;
  longest_minutes: number;
  shortest_minutes: number;
  first_log_at: string | null;
  last_log_at: string | null;
  last_log_age_days: number | null;
  // Tuân thủ ca theo lịch (chỉ ý nghĩa khi has_schedule = true)
  has_schedule: boolean;
  total_scheduled: number;
  on_time: number;
  late: number;
  missed: number;
  on_leave: number;
  compliance_rate: number | null;
}

export interface DutyLog {
  id: number;
  user_id: string;
  username: string;
  avatar_url: string | null;
  started_at: string;
  ended_at: string;
  duration_minutes: number;
  source: string;
  message_id: string | null;
  image_url: string | null;
  is_valid: boolean;
}

export interface ScheduleSlot {
  id: number;
  user_id: string;
  username: string;
  avatar_url: string | null;
  role_name: string | null;
  department: string | null;
  weekday: number;
  start_time: string;
  end_time: string;
  crosses_midnight: boolean;
}

export interface ScheduleGrid {
  week_start: string;
  days: Array<{ weekday: number; date: string; slots: ScheduleSlot[] }>;
}

export interface ComplianceRow {
  user_id: string;
  username: string;
  total: number;
  on_time: number;
  late: number;
  missed: number;
  on_leave: number;
  rate: number;
}

export interface LeaveRequest {
  id: number;
  user_id: string;
  username: string;
  avatar_url: string | null;
  type: string;
  type_label: string;
  start_date: string;
  end_date: string;
  duration_days: number;
  reason: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  created_at: string;
  processed_at: string | null;
  processed_by: string | null;
}

export interface AuditLog {
  id: number;
  user_id: string;
  username: string;
  action: string;
  detail: Record<string, unknown>;
  created_at: string;
}

// ----- STAFF -----
export type StaffGroup = 'LANH_DAO' | 'Y_TE' | 'DAO_TAO';
export type SystemRole = 'DUTY_ADMIN' | 'DUTY_MOD' | 'DUTY_MEMBER';

export interface PositionMeta {
  code: string;          // VD: "VIEN_TRUONG"
  label: string;         // "Viện Trưởng"
  group: StaffGroup;
  color: string;         // hex "#EF4444"
  icon: string;          // emoji
  level: number;         // 1 = cao nhất
}

export interface GroupMeta {
  code: StaffGroup;
  label: string;
  color: string;
  icon: string;
  order: number;
}

export interface StaffMember {
  id: number;
  guild_id: string;
  user_id: string;       // Discord ID (snowflake, string-safe)
  username: string;
  avatar_url: string | null;
  position: string;
  position_label: string;
  position_group: StaffGroup;
  position_color: string;
  position_icon: string;
  position_level: number;
  department: string | null;
  note: string | null;
  is_active: boolean;
  joined_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface StaffListResponse {
  items: StaffMember[];
  total: number;
  counts_by_group: Record<StaffGroup, number>;
}

// ============================================================
// HELPERS — type label cho leave + status normalization
// ============================================================

const LEAVE_TYPE_LABELS: Record<string, string> = {
  leave: 'Nghỉ phép',
  resign: 'Thôi việc',
  sick: 'Nghỉ ốm',
  annual: 'Nghỉ phép năm',
  personal: 'Việc riêng',
  compensate: 'Nghỉ bù',
};

function diffDays(start?: string | null, end?: string | null): number {
  if (!start || !end) return 0;
  const s = new Date(start).getTime();
  const e = new Date(end).getTime();
  return Math.max(0, Math.round((e - s) / 86400000)) + 1;
}

// ============================================================
// ENDPOINTS
// ============================================================

export const api = {
  // ----- AUTH -----
  me: async (): Promise<Me> => {
    const r = await apiFetch<{ user_id: string; username: string; global_name?: string | null; avatar_url?: string | null; is_2fa_enabled?: boolean; is_bot_owner?: boolean }>(
      '/api/dashboard/me',
    );
    return {
      user_id: String(r.user_id),
      discord_id: String(r.user_id),
      username: r.username || '',
      global_name: r.global_name ?? null,
      avatar_url: r.avatar_url ?? null,
      is_2fa_enabled: r.is_2fa_enabled ?? false,
      is_bot_owner: r.is_bot_owner ?? false,
    };
  },

  // ----- ADMIN (bot owner only) -----
  adminOverview: () => apiFetch<AdminOverview>('/api/admin/overview'),
  adminRefresh: () =>
    apiFetch<{ refreshed: boolean; ts: string }>('/api/admin/overview/refresh', {
      method: 'POST',
    }),

  // ----- SETUP — role_map theo guild -----
  setupGetRoles: (guild_id: string) =>
    apiFetch<{
      guild_id: string;
      guild_name: string;
      role_map: Record<
        'DUTY_ADMIN' | 'DUTY_MOD' | 'DUTY_MEMBER',
        { role_id: string; role_name: string | null } | null
      >;
    }>('/api/setup/roles', { query: { guild_id } }),

  // ----- BRANDING — public endpoint, không cần auth -----
  branding: () => apiFetch<{ system_name: string }>('/api/branding'),

  // ----- ADMIN system settings (bot owner only) -----
  systemSettingsGet: () =>
    apiFetch<{
      settings: Record<
        'system_name' | 'bot_activity_text',
        { value: string; updated_at: string | null; updated_by: string | null; max_length: number | null }
      >;
    }>('/api/admin/system-settings'),

  systemSettingsUpdate: (updates: Record<string, string>, note: string) =>
    apiFetch<{ updated: string[]; changes: Record<string, { before: string | null; after: string }> }>(
      '/api/admin/system-settings',
      { method: 'PUT', body: { updates, note } },
    ),

  myGuilds: async (): Promise<Guild[]> => {
    const resp = await apiFetch<{
      guilds: Array<{
        guild_id: string;
        guild_name: string;
        timezone: string;
        role_level: 'DUTY_ADMIN' | 'DUTY_MOD' | 'DUTY_MEMBER';
        is_admin: boolean;
        is_mod: boolean;
        icon_url?: string | null;
      }>;
    }>('/api/dashboard/me/guilds');
    return (resp.guilds || []).map((g) => ({
      id: g.guild_id,
      name: g.guild_name,
      icon_url: g.icon_url ?? null,
      role: g.role_level === 'DUTY_ADMIN' ? 'ADMIN' : g.role_level === 'DUTY_MOD' ? 'MOD' : 'MEMBER',
      is_admin: g.is_admin,
      is_mod: g.is_mod,
      timezone: g.timezone,
    }));
  },

  verify2FA: (otp_code: string) =>
    apiFetch<{ success: boolean }>('/auth/verify-2fa', {
      method: 'POST',
      body: { otp_code },
    }),
  logout: () => apiFetch<void>('/auth/logout', { method: 'POST' }),
  refresh: () => apiFetch<void>('/auth/refresh', { method: 'POST' }),

  // ----- DASHBOARD -----
  overview: async (guild_id: string, period: string, start?: string, end?: string): Promise<OverviewStats> => {
    const r = await apiFetch<{
      total_sessions: number;
      total_minutes: number;
      total_members: number;
      total_hhmm: string;
      top5: Array<{ user_id?: string | null; username: string; avatar_url?: string | null; total_minutes: number; sessions: number }>;
    }>('/api/dashboard/overview', {
      query: { guild_id, period, date_from: start, date_to: end },
    });
    const totalSessions = r.total_sessions || 0;
    return {
      total_sessions: totalSessions,
      total_minutes: r.total_minutes || 0,
      total_members: r.total_members || 0,
      // Backend chưa có active_members cho overview — dùng số top users có data
      active_members: (r.top5 || []).filter((u) => u.sessions > 0).length || r.total_members || 0,
      avg_minutes_per_session: totalSessions > 0 ? Math.round((r.total_minutes || 0) / totalSessions) : 0,
      // Backend overview chưa compute compliance — lấy từ /attendance hoặc /schedule/compliance riêng
      compliance_rate: null,
      top_users: (r.top5 || []).map((u, i) => ({
        user_id: String(u.user_id || `__top_${i}`),
        username: u.username,
        avatar_url: u.avatar_url ?? null,
        total_minutes: u.total_minutes,
        session_count: u.sessions,
      })),
    };
  },

  chart: async (guild_id: string, period: string): Promise<ChartPoint[]> => {
    const r = await apiFetch<{ labels: string[]; data: number[] }>('/api/dashboard/chart', {
      query: { guild_id, period },
    });
    const labels = r.labels || [];
    const data = r.data || [];
    return labels.map((label, i) => {
      // "2026-05-11" → "11/05"
      const d = new Date(label);
      const display = Number.isNaN(d.getTime())
        ? label
        : `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`;
      return { date: display, value: data[i] || 0 };
    });
  },

  ranking: async (
    guild_id: string,
    period: string,
    mode: 'top' | 'bottom' = 'top',
    limit = 20,
    start?: string,
    end?: string,
  ): Promise<RankingRow[]> => {
    const r = await apiFetch<{
      page: number;
      page_size: number;
      items: Array<{
        rank: number;
        user_id: string | number;
        username: string;
        avatar_url?: string | null;
        total_minutes: number;
        sessions: number;
      }>;
    }>('/api/dashboard/ranking', {
      query: {
        guild_id,
        period,
        order: mode === 'top' ? 'desc' : 'asc',
        page: 1,
        page_size: limit,
        date_from: start,
        date_to: end,
      },
    });
    return (r.items || []).map((it) => ({
      rank: it.rank,
      user_id: String(it.user_id ?? ''),
      username: it.username,
      avatar_url: it.avatar_url ?? null,
      total_minutes: it.total_minutes || 0,
      session_count: it.sessions || 0,
    }));
  },

  attendance: async (guild_id: string, period: string, start?: string, end?: string): Promise<AttendanceUser[]> => {
    const r = await apiFetch<{
      items: Array<{
        user_id: string | null;
        username: string;
        avatar_url?: string | null;
        session_count: number;
        total_minutes: number;
        avg_minutes: number;
        longest_minutes: number;
        shortest_minutes: number;
        first_log_at: string | null;
        last_log_at: string | null;
        last_log_age_days: number | null;
        has_schedule: boolean;
        compliance: { rate: number | null; on_time: number; late: number; missed: number; on_leave: number };
      }>;
    }>('/api/dashboard/attendance', {
      query: { guild_id, period, date_from: start, date_to: end },
    });
    return (r.items || []).map((it, i) => {
      const c = it.compliance || ({} as any);
      return {
        user_id: it.user_id ? String(it.user_id) : `__row_${i}`,
        username: it.username,
        avatar_url: it.avatar_url ?? null,
        // Giờ trực thường
        session_count: it.session_count || 0,
        total_minutes: it.total_minutes || 0,
        avg_minutes: it.avg_minutes || 0,
        longest_minutes: it.longest_minutes || 0,
        shortest_minutes: it.shortest_minutes || 0,
        first_log_at: it.first_log_at,
        last_log_at: it.last_log_at,
        last_log_age_days: it.last_log_age_days,
        // Tuân thủ ca
        has_schedule: !!it.has_schedule,
        total_scheduled: (c.on_time || 0) + (c.late || 0) + (c.missed || 0) + (c.on_leave || 0),
        on_time: c.on_time || 0,
        late: c.late || 0,
        missed: c.missed || 0,
        on_leave: c.on_leave || 0,
        compliance_rate: c.rate ?? null,
      };
    });
  },

  attendanceDaily: async (guild_id: string, user_id: string | number, start: string, end: string) => {
    // Backend trả {days: [{date, status, worked_minutes, scheduled_minutes, schedules, logs, leave, ...}]}
    // start/end PHẢI là DD/MM/YYYY — backend get_custom_range không nhận ISO.
    const r = await apiFetch<{
      summary?: {
        counters: Record<string, number>;
        total_worked_minutes: number;
        total_worked_hhmm: string;
        total_scheduled_minutes: number;
        total_scheduled_hhmm: string;
        overall_compliance_pct: number | null;
      };
      days?: Array<{
        date: string;
        weekday_label: string;
        weekday_short: string;
        is_today: boolean;
        is_future: boolean;
        status: string;
        worked_minutes: number;
        scheduled_minutes: number;
        compliance_pct: number | null;
        schedules: Array<{ id: number; start_time: string; end_time: string; crosses_midnight: boolean }>;
        logs: Array<{
          id: number;
          started_at: string;
          ended_at: string;
          duration_minutes: number;
          source: string | null;
          schedule_id: number | null;
        }>;
        leave: { id: number; type: string; reason: string } | null;
      }>;
    }>('/api/dashboard/attendance/daily', {
      query: { guild_id, user_id, date_from: start, date_to: end },
    });
    return {
      summary: r.summary || null,
      days: (r.days || []).map((d) => ({
        date: d.date,
        weekday_label: d.weekday_label,
        weekday_short: d.weekday_short,
        is_today: !!d.is_today,
        is_future: !!d.is_future,
        status: d.status,
        minutes: d.worked_minutes || 0,
        scheduled_minutes: d.scheduled_minutes || 0,
        compliance_pct: d.compliance_pct,
        schedules: d.schedules || [],
        logs: d.logs || [],
        leave: d.leave,
      })),
    };
  },

  logs: async (
    guild_id: string,
    page = 1,
    page_size = 20,
    user_id?: string,
    search?: string,
    period?: string,
  ): Promise<{ items: DutyLog[]; total: number; page: number; page_size: number }> => {
    const r = await apiFetch<{
      total: number;
      page: number;
      page_size: number;
      items: Array<{
        id: number;
        user_id: string;
        username: string;
        avatar_url?: string | null;
        started_at: string;
        ended_at: string;
        duration_minutes: number;
        source?: string;
        message_id?: string | null;
        image_url?: string | null;
      }>;
    }>('/api/dashboard/logs', {
      query: { guild_id, page, page_size, user_id, search, period: period || 'all' },
    });
    return {
      total: r.total || 0,
      page: r.page || page,
      page_size: r.page_size || page_size,
      items: (r.items || []).map((it) => ({
        id: it.id,
        user_id: String(it.user_id ?? ''),
        username: it.username,
        avatar_url: it.avatar_url ?? null,
        started_at: it.started_at,
        ended_at: it.ended_at,
        duration_minutes: it.duration_minutes,
        source: it.source || 'OCR',
        message_id: it.message_id ?? null,
        image_url: it.image_url ?? null,
        is_valid: true,
      })),
    };
  },

  deleteLog: (guild_id: string, log_id: number, note: string) =>
    apiFetch<void>(`/api/dashboard/logs/${log_id}`, {
      method: 'DELETE',
      query: { guild_id, note },
    }),

  // Mass rename: đổi username tất cả log của old_name → new_name trong 1 guild.
  // Use case: nhân viên đổi tên character ingame, đồng bộ lại log cũ.
  renameLogs: (guild_id: string, old_name: string, new_name: string, note: string) =>
    apiFetch<{ success: boolean; affected_logs: number; affected_user_ids: string[] }>(
      '/api/dashboard/logs/rename',
      {
        method: 'POST',
        body: { guild_id, old_name, new_name, note },
      },
    ),

  // Rebind: đổi current_ingame_name trong binding cho 1 user_id.
  // KHÁC với rename — KHÔNG đổi log cũ, chỉ đổi tên mà bot expect ở lần chấm sau.
  rebindUser: (guild_id: string, target_user_id: string, new_ingame_name: string, note: string) =>
    apiFetch<{ success: boolean; original_ingame_name: string; old_name: string; new_name: string }>(
      '/api/dashboard/logs/rebind',
      {
        method: 'POST',
        body: { guild_id, target_user_id, new_ingame_name, note },
      },
    ),

  listBindings: (guild_id: string) =>
    apiFetch<{
      items: Array<{
        discord_user_id: string;
        original_ingame_name: string;
        current_ingame_name: string;
        is_renamed: boolean;
        rebind_count: number;
        log_count: number;
        first_seen_at: string | null;
        last_seen_at: string | null;
        history: Array<{ from: string; to: string; by: string; by_name?: string; at: string; reason: string; via?: string }>;
      }>;
    }>('/api/dashboard/logs/bindings', { query: { guild_id } }),

  // Wipe all duty_logs trong guild — chỉ bot owner. Confirm 2 lần ở UI.
  wipeGuildLogs: (guild_id: string, confirm_phrase: string) =>
    apiFetch<{ success: boolean; deleted_logs: number; reset_bindings: number; guild_id: string }>(
      '/api/admin/wipe-logs',
      {
        method: 'POST',
        body: { guild_id, confirm_phrase },
      },
    ),

  // ----- SCHEDULE -----
  // Backend /grid trả {items: [{user_id, username, schedules: [{weekday, start_time, end_time, ...}]}]}
  // — group by user. Frontend cần group by day để render calendar grid.
  // → Convert: flatten schedules ra rồi group by weekday.
  scheduleGrid: async (guild_id: string, period = 'week'): Promise<ScheduleGrid> => {
    const r = await apiFetch<{
      items: Array<{
        user_id: string | null;
        username: string;
        avatar_url?: string | null;
        schedules: Array<{
          id: number;
          weekday: number;
          start_time: string;
          end_time: string;
          crosses_midnight: boolean;
          role_name?: string | null;
          department?: string | null;
        }>;
      }>;
    }>('/api/schedule/grid', { query: { guild_id, period } });

    // Build days[0..6] với slots
    const days: ScheduleGrid['days'] = Array.from({ length: 7 }, (_, wd) => ({
      weekday: wd,
      date: '',
      slots: [],
    }));

    // ISO date của thứ 2 tuần này (UTC, đủ dùng cho frontend display)
    const now = new Date();
    const dow = (now.getDay() + 6) % 7; // 0 = Mon
    const monday = new Date(now);
    monday.setDate(now.getDate() - dow);
    for (let i = 0; i < 7; i++) {
      const d = new Date(monday);
      d.setDate(monday.getDate() + i);
      days[i].date = d.toISOString().slice(0, 10);
    }

    for (const user of r.items || []) {
      for (const s of user.schedules || []) {
        const wd = s.weekday;
        if (wd < 0 || wd > 6) continue;
        days[wd].slots.push({
          id: s.id,
          user_id: user.user_id ? String(user.user_id) : '',
          username: user.username,
          avatar_url: user.avatar_url ?? null,
          role_name: s.role_name ?? null,
          department: s.department ?? null,
          weekday: wd,
          start_time: s.start_time,
          end_time: s.end_time,
          crosses_midnight: !!s.crosses_midnight,
        });
      }
    }

    return { week_start: days[0].date, days };
  },

  // Backend /calendar dùng week_offset, KHÔNG hỗ trợ year/month → ta build
  // calendar tháng CLIENT-SIDE từ /grid (schedules recurring theo weekday).
  // QUAN TRỌNG: dùng period='week' để tránh `compute_compliance` quét 130 năm
  // (period='all') → hang vĩnh viễn. Schedules là recurring weekly nên 1 tuần đủ.
  scheduleCalendar: async (guild_id: string, year: number, month: number) => {
    const grid = await api.scheduleGrid(guild_id, 'week');
    // Map mỗi ngày trong tháng → slots dựa trên weekday
    const daysInMonth = new Date(year, month, 0).getDate();
    const slotsByWeekday: Record<number, any[]> = {};
    for (const d of grid.days) {
      slotsByWeekday[d.weekday] = d.slots;
    }
    const days: Array<{ date: string; slots: any[] }> = [];
    for (let d = 1; d <= daysInMonth; d++) {
      const date = new Date(year, month - 1, d);
      const wd = (date.getDay() + 6) % 7;
      const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
      days.push({ date: dateStr, slots: slotsByWeekday[wd] || [] });
    }
    return { days };
  },

  // Backend /compliance trả 1 row/occurrence (user × ngày × ca).
  // Frontend cần 1 row/user. → Group by user_id, sum on_time/late/missed/on_leave.
  scheduleCompliance: async (guild_id: string, period: string): Promise<ComplianceRow[]> => {
    const r = await apiFetch<{
      summary: { rate_on_time: number; counters: Record<string, number>; total_in_schedule: number };
      items: Array<{
        user_id: string;
        username: string;
        status: 'on_time' | 'late' | 'missed' | 'on_leave' | 'off_schedule';
        occurrence_date: string;
      }>;
    }>('/api/schedule/compliance', { query: { guild_id, period } });

    const grouped = new Map<string, ComplianceRow>();
    for (const it of r.items || []) {
      const key = it.user_id;
      let row = grouped.get(key);
      if (!row) {
        row = {
          user_id: String(it.user_id),
          username: it.username || '—',
          total: 0,
          on_time: 0,
          late: 0,
          missed: 0,
          on_leave: 0,
          rate: 0,
        };
        grouped.set(key, row);
      }
      if (it.status === 'on_time') row.on_time++;
      else if (it.status === 'late') row.late++;
      else if (it.status === 'missed') row.missed++;
      else if (it.status === 'on_leave') row.on_leave++;
    }
    // Compute rate per user
    const out: ComplianceRow[] = [];
    for (const row of grouped.values()) {
      const countable = row.on_time + row.late + row.missed;
      row.total = countable;
      row.rate = countable > 0 ? (row.on_time / countable) * 100 : 0;
      out.push(row);
    }
    // Sort: rate ascending (kém nhất lên đầu — Q11=a)
    out.sort((a, b) => a.rate - b.rate);
    return out;
  },

  scheduleCreate: (
    guild_id: string,
    body: {
      user_id: string;
      weekday: number;
      start_time: string;
      end_time: string;
      note: string;
    },
  ) =>
    apiFetch<{ success: boolean; schedule: any }>('/api/schedule', {
      method: 'POST',
      query: { guild_id },
      body,
    }),

  /**
   * Admin set lại toàn bộ lịch user cho 1 khung giờ.
   * Weekday KHÔNG trong list → deactivate. Khung giờ khác KHÔNG bị động.
   */
  scheduleBulkReplace: (
    guild_id: string,
    body: {
      user_id: string;
      weekdays: number[];      // 0=T2..6=CN
      start_time: string;
      end_time: string;
      note: string;
    },
  ) =>
    apiFetch<{
      success: boolean;
      created: number[];
      updated: number[];
      removed: number[];
    }>('/api/schedule/bulk-replace', {
      method: 'POST',
      query: { guild_id },
      body,
    }),

  scheduleUpdate: (
    guild_id: string,
    schedule_id: number,
    data: Partial<{
      weekday: number;
      start_time: string;
      end_time: string;
      role_name: string;
      note: string;    // lý do — bắt buộc khi admin sửa lịch người khác
    }>,
  ) =>
    apiFetch<unknown>(`/api/schedule/${schedule_id}`, {
      method: 'PUT',
      query: { guild_id },
      body: data,
    }),

  scheduleDelete: (guild_id: string, schedule_id: number, note?: string) =>
    apiFetch<void>(`/api/schedule/${schedule_id}`, {
      method: 'DELETE',
      query: { guild_id, note },
    }),

  // ----- NOTIFICATION SETTINGS -----
  notificationSettings: (guild_id: string) =>
    apiFetch<{ notification_settings: Record<string, boolean> }>(
      '/api/dashboard/notification-settings',
      { query: { guild_id } },
    ),

  notificationSettingsUpdate: (
    guild_id: string,
    settings: Record<string, boolean>,
    note: string,
  ) =>
    apiFetch<{ success: boolean; notification_settings: Record<string, boolean> }>(
      '/api/dashboard/notification-settings',
      { method: 'PUT', query: { guild_id }, body: { settings, note } },
    ),

  // Batch resolve avatars + usernames cho user_id từ Discord (cache 10p ở backend).
  resolveUsers: (user_ids: string[]) =>
    apiFetch<{
      results: Record<string, {
        user_id: string;
        username: string;
        global_name: string;
        avatar_url: string;
      }>;
    }>('/api/dashboard/resolve-users', {
      method: 'POST',
      body: { user_ids },
    }),

  // ----- LEAVE -----
  leaveList: async (guild_id: string, status?: string): Promise<LeaveRequest[]> => {
    // Frontend pass 'PENDING'/'APPROVED'/'REJECTED'/'RESIGN' → map sang backend.
    let backendStatus: string | undefined;
    let requestType: string | undefined;
    if (status === 'RESIGN') {
      requestType = 'resign';
    } else if (status) {
      backendStatus = status.toLowerCase();
    }
    const r = await apiFetch<{
      items: Array<{
        id: number;
        user_id: string;
        username: string;
        avatar_url?: string | null;
        type: string;
        status: string;
        start_date: string | null;
        end_date: string | null;
        days_count: number | null;
        reason: string;
        decided_at: string | null;
        decided_by: string | null;
        processed_at: string | null;
      }>;
    }>('/api/leave/list', {
      query: { guild_id, status: backendStatus, request_type: requestType },
    });
    return (r.items || []).map((it) => ({
      id: it.id,
      user_id: String(it.user_id ?? ''),
      username: it.username,
      avatar_url: it.avatar_url ?? null,
      type: it.type,
      type_label: LEAVE_TYPE_LABELS[it.type] || it.type,
      start_date: it.start_date || '',
      end_date: it.end_date || it.start_date || '',
      duration_days: it.days_count ?? diffDays(it.start_date, it.end_date),
      reason: it.reason || '',
      status: (it.status?.toUpperCase() as 'PENDING' | 'APPROVED' | 'REJECTED') || 'PENDING',
      created_at: it.decided_at || '',
      processed_at: it.processed_at,
      processed_by: it.decided_by ? String(it.decided_by) : null,
    }));
  },

  leaveDecision: (
    guild_id: string,
    leave_id: number,
    decision: 'APPROVED' | 'REJECTED',
    note?: string,
  ) =>
    apiFetch<{ success: boolean }>(`/api/leave/${leave_id}/decision`, {
      method: 'POST',
      query: { guild_id },
      body: { approved: decision === 'APPROVED', note: note || '' },
    }),

  leaveRevert: (guild_id: string, leave_id: number, reason: string) =>
    apiFetch<{ success: boolean }>(`/api/leave/${leave_id}/revert`, {
      method: 'POST',
      query: { guild_id },
      body: { reason },
    }),

  // ----- AUDIT -----
  auditLogs: async (
    guild_id: string,
    page = 1,
    page_size = 50,
    action?: string,
    user_id?: string,
  ): Promise<{
    items: AuditLog[];
    total: number;
    resolved: Record<string, { type: 'user' | 'channel' | 'role'; name: string }>;
  }> => {
    const r = await apiFetch<any>('/api/audit/logs', {
      query: { guild_id, page, page_size, action, user_id },
    });
    const items = r.items || r.logs || [];
    return {
      total: r.total ?? items.length,
      resolved: r.resolved || {},
      items: items.map((it: any) => ({
        id: it.id,
        user_id: String(it.user_id ?? ''),
        username: it.username || '—',
        action: it.action,
        detail: it.detail || {},
        created_at: it.created_at,
      })),
    };
  },

  // ----- EXPORT -----
  // Backend dùng QUERY params, KHÔNG body.
  // mode='logs' (default): raw duty logs
  // mode='ranking': aggregate 1 row/user (cho bảng xếp hạng)
  exportPrepare: async (
    guild_id: string,
    format: 'csv' | 'excel',
    period: string,
    options: { start?: string; end?: string; mode?: 'logs' | 'ranking' } = {},
  ) => {
    const r = await apiFetch<{
      download_url: string;
      expires_in_minutes?: number;
      token?: string;
    }>('/api/export/prepare', {
      method: 'POST',
      query: {
        guild_id,
        format,
        period,
        mode: options.mode || 'logs',
        date_from: options.start,
        date_to: options.end,
      },
    });
    return {
      download_url: r.download_url,
      token: r.token || '',
      expires_at: r.expires_in_minutes ? `${r.expires_in_minutes} phút` : '',
    };
  },

  // ----- STAFF MANAGEMENT -----

  staffPositions: () =>
    apiFetch<{ positions: PositionMeta[]; groups: GroupMeta[] }>('/api/staff/positions'),

  staffList: (
    guild_id: string,
    opts: {
      group?: StaffGroup;
      position?: string;
      is_active?: boolean;
      search?: string;
    } = {},
  ) =>
    apiFetch<StaffListResponse>('/api/staff/list', {
      query: {
        guild_id,
        group: opts.group,
        position: opts.position,
        is_active: opts.is_active,
        search: opts.search,
      },
    }),

  staffDetail: (guild_id: string, user_id: string) =>
    apiFetch<{ staff: StaffMember }>(`/api/staff/${user_id}`, {
      query: { guild_id },
    }),

  staffAdd: (
    guild_id: string,
    body: {
      user_id: string;
      username: string;
      position: string;
      joined_at?: string;
      note: string;
    },
  ) =>
    apiFetch<{ success: boolean; staff: StaffMember }>('/api/staff', {
      method: 'POST',
      query: { guild_id },
      body,
    }),

  staffUpdate: (
    guild_id: string,
    user_id: string,
    body: {
      position?: string;
      username?: string;
      is_active?: boolean;
      joined_at?: string | null;
      note: string;     // BẮT BUỘC
    },
  ) =>
    apiFetch<{ success: boolean; staff: StaffMember; changes: Record<string, { before: unknown; after: unknown }> }>(
      `/api/staff/${user_id}`,
      { method: 'PUT', query: { guild_id }, body },
    ),

  staffRemove: (guild_id: string, user_id: string, note: string, hard = false) =>
    apiFetch<{ success: boolean }>(`/api/staff/${user_id}`, {
      method: 'DELETE',
      query: { guild_id, note, hard },
    }),

  staffGetPositionRoleMap: (guild_id: string) =>
    apiFetch<{ position_role_map: Record<string, SystemRole>; valid_system_roles: SystemRole[] }>(
      '/api/staff/config/position-roles',
      { query: { guild_id } },
    ),

  staffUpdatePositionRoleMap: (
    guild_id: string,
    map: Record<string, SystemRole | ''>,
    note: string,
  ) =>
    apiFetch<{ success: boolean; position_role_map: Record<string, SystemRole> }>(
      '/api/staff/config/position-roles',
      {
        method: 'PUT',
        query: { guild_id },
        body: { map, note },
      },
    ),
};

// ============================================================
// ERROR FORMATTING HELPER — convert mọi error shape → string
// FastAPI 422 trả detail là array of validation errors → tránh "[object Object]"
// ============================================================
export function formatError(err: unknown): string {
  if (err instanceof APIError) {
    const d = err.detail;
    // Pydantic validation: array of { loc, msg, type }
    if (Array.isArray(d)) {
      return d
        .map((e: any) => {
          if (typeof e === 'string') return e;
          if (e && typeof e === 'object') {
            const loc = Array.isArray(e.loc) ? e.loc.slice(1).join('.') : '';
            return loc ? `${loc}: ${e.msg || JSON.stringify(e)}` : (e.msg || JSON.stringify(e));
          }
          return String(e);
        })
        .join(' | ');
    }
    if (typeof d === 'object' && d !== null) {
      return JSON.stringify(d);
    }
    return String(d || err.message || `HTTP ${err.status}`);
  }
  if (err instanceof Error) return err.message;
  if (typeof err === 'string') return err;
  try {
    return JSON.stringify(err);
  } catch {
    return String(err);
  }
}
