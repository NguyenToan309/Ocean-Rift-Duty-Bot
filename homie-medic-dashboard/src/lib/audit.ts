/**
 * audit.ts — Helpers để hiển thị audit log dễ đọc.
 *
 * Map action codes → label tiếng Việt + emoji + category (cho color coding).
 * Pretty-print detail object: dịch field names, format dates, ẩn raw IDs.
 */

export type AuditCategory = 'success' | 'danger' | 'warning' | 'info' | 'neutral';

interface ActionMeta {
  label: string;
  emoji: string;
  category: AuditCategory;
}

const ACTION_MAP: Record<string, ActionMeta> = {
  // ─── Auth ───
  LOGIN_SUCCESS:    { label: 'Đăng nhập thành công', emoji: '🔓', category: 'success' },
  LOGIN_FAILED:     { label: 'Đăng nhập thất bại', emoji: '🔒', category: 'danger' },
  LOGIN_2FA_FAILED: { label: 'Sai mã 2FA', emoji: '🔐', category: 'danger' },
  LOGOUT:           { label: 'Đăng xuất', emoji: '👋', category: 'neutral' },
  ENABLE_2FA:       { label: 'Bật 2FA', emoji: '🛡️', category: 'success' },
  ACCOUNT_LOCKED:   { label: 'Khoá tài khoản', emoji: '🚫', category: 'danger' },
  ACCOUNT_UNLOCKED: { label: 'Mở khoá tài khoản', emoji: '✅', category: 'success' },

  // ─── Export ───
  EXPORT_CSV:   { label: 'Xuất CSV', emoji: '📥', category: 'info' },
  EXPORT_EXCEL: { label: 'Xuất Excel', emoji: '📊', category: 'info' },

  // ─── Logs ───
  LOG_UPLOADED: { label: 'Tạo log chấm công', emoji: '✍️', category: 'success' },
  LOG_DELETED:  { label: 'Xoá log chấm công', emoji: '🗑️', category: 'danger' },
  LOG_REJECTED: { label: 'Từ chối log', emoji: '⛔', category: 'warning' },

  // ─── Setup ───
  CHANGE_ROLE_CONFIG:    { label: 'Đổi cấu hình role', emoji: '⚙️', category: 'warning' },
  CHANGE_CHANNEL_CONFIG: { label: 'Đổi cấu hình channel', emoji: '#️⃣', category: 'warning' },
  SETUP_GUILD:           { label: 'Khởi tạo server', emoji: '🏗️', category: 'info' },

  // ─── Schedule ───
  SCHEDULE_CREATED: { label: 'Tạo lịch trực', emoji: '➕', category: 'success' },
  SCHEDULE_UPDATED: { label: 'Sửa lịch trực', emoji: '✏️', category: 'warning' },
  SCHEDULE_DELETED: { label: 'Xoá lịch trực', emoji: '🗑️', category: 'danger' },

  // ─── Leave ───
  LEAVE_REQUESTED:  { label: 'Gửi đơn nghỉ phép', emoji: '📨', category: 'info' },
  LEAVE_APPROVED:   { label: 'Duyệt đơn nghỉ', emoji: '✅', category: 'success' },
  LEAVE_REJECTED:   { label: 'Từ chối đơn nghỉ', emoji: '❌', category: 'danger' },
  RESIGN_REQUESTED: { label: 'Gửi đơn xin out', emoji: '🚪', category: 'warning' },
  RESIGN_APPROVED:  { label: 'Duyệt đơn xin out', emoji: '✅', category: 'success' },
  RESIGN_REJECTED:  { label: 'Từ chối đơn xin out', emoji: '❌', category: 'danger' },

  // ─── Other ───
  REMIND_SENT:         { label: 'Gửi nhắc nhở ca', emoji: '🔔', category: 'info' },
  ONBOARDING_REMINDED: { label: 'Nhắc onboarding', emoji: '👋', category: 'info' },
  DISCIPLINE:          { label: 'Kỷ luật', emoji: '⚠️', category: 'warning' },
  DISMISSED:           { label: 'Sa thải', emoji: '🚪', category: 'danger' },

  // ─── Staff (NEW) ───
  STAFF_ADDED:        { label: 'Thêm nhân sự', emoji: '👤', category: 'success' },
  STAFF_UPDATED:      { label: 'Cập nhật nhân sự', emoji: '✏️', category: 'warning' },
  STAFF_REMOVED:      { label: 'Gỡ nhân sự', emoji: '🚪', category: 'danger' },
  STAFF_ROLE_SYNCED:  { label: 'Đồng bộ Discord role', emoji: '🔄', category: 'info' },
  POSITION_ROLE_MAP_CHANGED: { label: 'Đổi map chức vụ→quyền', emoji: '🔗', category: 'warning' },
};

/** Trả về meta cho action code. Fallback nếu chưa map. */
export function getActionMeta(action: string): ActionMeta {
  return ACTION_MAP[action] || {
    label: action.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()),
    emoji: '📋',
    category: 'neutral',
  };
}

// ============================================================
// Detail pretty-print
// ============================================================

/** Map field name kỹ thuật → label tiếng Việt. */
const FIELD_LABELS: Record<string, string> = {
  request_id:  'Mã đơn',
  for_user:    'Cho user',
  user_id:     'User',
  target_user: 'Đối tượng',
  by_user:     'Bởi',
  by_role:     'Quyền',
  schedule_id: 'Mã lịch',
  log_id:      'Mã log',
  channel_id:  'Channel',
  role_id:     'Role',
  weekday:     'Thứ',
  start:       'Bắt đầu',
  end:         'Kết thúc',
  start_date:  'Từ ngày',
  end_date:    'Đến ngày',
  start_time:  'Giờ bắt đầu',
  end_time:    'Giờ kết thúc',
  reason:      'Lý do',
  note:        'Lý do / Ghi chú',
  field:       'Trường',
  period:      'Kỳ',
  mode:        'Chế độ',
  rows:        'Số dòng',
  format:      'Định dạng',
  via:         'Kênh',
  duration_minutes: 'Thời lượng (phút)',
  ip:          'IP',
  changes:     'Thay đổi',
};

const WEEKDAY_LABELS = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'Chủ nhật'];

const PERIOD_LABELS: Record<string, string> = {
  day: 'Hôm nay', week: 'Tuần', month: 'Tháng', quarter: 'Quý', all: 'Tất cả', custom: 'Tuỳ chỉnh',
};

const MODE_LABELS: Record<string, string> = {
  logs: 'Log chi tiết', ranking: 'Bảng xếp hạng',
};

/** Field nào là Discord user ID (cần lookup username). */
function isUserIdField(key: string): boolean {
  return key === 'for_user' || key === 'by_user' || key === 'target_user' || key === 'user_id';
}
function isChannelField(key: string): boolean {
  return key === 'channel_id' || key.endsWith('_channel_id');
}
function isRoleField(key: string): boolean {
  return key === 'role_id' || key.endsWith('_role_id');
}

export interface ResolverMap {
  /** {id_str: name} từ backend audit response */
  resolved?: Record<string, { type: 'user' | 'channel' | 'role'; name: string }>;
  /** Map bổ sung từ client (vd: cache từ attendance, ranking…) */
  users?: Map<string, string>;
}

/**
 * Format 1 field value thông minh dựa trên key + raw value.
 * `resolver`: chứa cả backend resolved + client-side userCache.
 */
function formatFieldValue(
  key: string,
  value: unknown,
  resolver?: ResolverMap,
): string {
  if (value === null || value === undefined) return '—';

  const lookup = (id: string): string | undefined => {
    return resolver?.resolved?.[id]?.name || resolver?.users?.get(id);
  };

  // Discord user ID — show full + lookup name nếu có
  if (isUserIdField(key) && typeof value === 'string' && /^\d{15,}$/.test(value)) {
    const name = lookup(value);
    return name ? `${name}  ·  ${value}` : value;
  }

  // Channel ID
  if (isChannelField(key) && typeof value === 'string' && /^\d{15,}$/.test(value)) {
    const name = resolver?.resolved?.[value];
    if (name && name.type === 'channel') return `${name.name}  ·  ${value}`;
    return value;
  }

  // Role ID
  if (isRoleField(key) && typeof value === 'string' && /^\d{15,}$/.test(value)) {
    const name = resolver?.resolved?.[value];
    if (name && name.type === 'role') return `${name.name}  ·  ${value}`;
    return value;
  }

  // ID generic khác — show full
  if (key.endsWith('_id') && typeof value === 'string' && /^\d{15,}$/.test(value)) {
    const name = resolver?.resolved?.[value];
    if (name) return `${name.name}  ·  ${value}`;
    return value;
  }

  // Weekday number
  if (key === 'weekday' && typeof value === 'number' && value >= 0 && value <= 6) {
    return WEEKDAY_LABELS[value];
  }

  // Period
  if (key === 'period' && typeof value === 'string' && value in PERIOD_LABELS) {
    return PERIOD_LABELS[value];
  }
  if (key === 'mode' && typeof value === 'string' && value in MODE_LABELS) {
    return MODE_LABELS[value];
  }

  // Date string YYYY-MM-DD → DD/MM/YYYY
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split('-');
    return `${d}/${m}/${y}`;
  }

  // ISO datetime → DD/MM HH:MM
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
    const dt = new Date(value);
    if (!Number.isNaN(dt.getTime())) {
      const pad = (n: number) => String(n).padStart(2, '0');
      return `${pad(dt.getDate())}/${pad(dt.getMonth() + 1)} ${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
    }
  }

  // Time HH:MM:SS → HH:MM
  if (typeof value === 'string' && /^\d{2}:\d{2}(:\d{2})?$/.test(value)) {
    return value.slice(0, 5);
  }

  // Boolean → ✓/✗
  if (typeof value === 'boolean') return value ? '✓' : '✗';

  // Object — đặc biệt cho field "changes" (diff before/after)
  if (typeof value === 'object') {
    if (key === 'changes') {
      try {
        const diffs: string[] = [];
        for (const [fieldKey, change] of Object.entries(value as Record<string, any>)) {
          if (change && typeof change === 'object' && 'before' in change && 'after' in change) {
            const fieldLabel = FIELD_LABELS[fieldKey] || fieldKey;
            const b = formatFieldValue(fieldKey, change.before, resolver);
            const a = formatFieldValue(fieldKey, change.after, resolver);
            diffs.push(`${fieldLabel}: ${b} → ${a}`);
          }
        }
        return diffs.length > 0 ? diffs.join(' · ') : '—';
      } catch {
        return '[changes]';
      }
    }
    try {
      const s = JSON.stringify(value);
      return s.length > 80 ? s.slice(0, 77) + '…' : s;
    } catch {
      return '[object]';
    }
  }

  // String dài → truncate
  const s = String(value);
  return s.length > 100 ? s.slice(0, 97) + '…' : s;
}

/** Pretty-print detail JSON thành array of {label, value} chips để render. */
export interface DetailChip {
  label: string;
  value: string;
}

export function formatAuditDetail(
  detail: unknown,
  resolver?: ResolverMap,
): DetailChip[] {
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) {
    return detail ? [{ label: '', value: String(detail) }] : [];
  }
  const obj = detail as Record<string, unknown>;
  const chips: DetailChip[] = [];
  // Ưu tiên hiển thị các field quan trọng trước
  const priority = ['request_id', 'log_id', 'schedule_id', 'for_user', 'target_user', 'by_user', 'reason', 'note'];
  const seen = new Set<string>();
  for (const key of priority) {
    if (key in obj) {
      chips.push({ label: FIELD_LABELS[key] || key, value: formatFieldValue(key, obj[key], resolver) });
      seen.add(key);
    }
  }
  // Sau đó các field còn lại
  for (const [key, value] of Object.entries(obj)) {
    if (seen.has(key)) continue;
    if (value === null || value === undefined || value === '') continue;
    chips.push({ label: FIELD_LABELS[key] || key, value: formatFieldValue(key, value, resolver) });
  }
  return chips;
}

/** CSS classes cho category — tách dark/light đúng cách. */
export function categoryBadgeClass(cat: AuditCategory): string {
  switch (cat) {
    case 'success': return 'bg-green-500/15 text-green-600 dark:bg-green-500/15 dark:text-green-400 border border-green-500/30';
    case 'danger':  return 'bg-red-500/15 text-red-600 dark:bg-red-500/15 dark:text-red-400 border border-red-500/30';
    case 'warning': return 'bg-amber-500/15 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400 border border-amber-500/30';
    case 'info':    return 'bg-blue-500/15 text-blue-600 dark:bg-blue-500/15 dark:text-blue-400 border border-blue-500/30';
    case 'neutral': return 'bg-slate-500/15 text-slate-600 dark:bg-slate-500/15 dark:text-slate-300 border border-slate-500/30';
  }
}

export function categoryIconBgClass(cat: AuditCategory): string {
  switch (cat) {
    case 'success': return 'bg-green-500/15 text-green-500';
    case 'danger':  return 'bg-red-500/15 text-red-500';
    case 'warning': return 'bg-amber-500/15 text-amber-500';
    case 'info':    return 'bg-blue-500/15 text-blue-500';
    case 'neutral': return 'bg-slate-500/15 text-slate-500';
  }
}

/** Get unique action codes — dùng cho dropdown filter. */
export function getAllKnownActions(): Array<{ code: string; label: string; emoji: string }> {
  return Object.entries(ACTION_MAP).map(([code, meta]) => ({
    code, label: meta.label, emoji: meta.emoji,
  }));
}
