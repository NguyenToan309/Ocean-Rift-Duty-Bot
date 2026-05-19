/**
 * format.ts — Pure formatting helpers.
 */

/** 142 phút → "2h 22m" hoặc "142 phút" tùy mode */
export function minutesToHHMM(min: number, short = true): string {
  if (!Number.isFinite(min)) return '—';
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h === 0) return short ? `${m}m` : `${m} phút`;
  if (m === 0) return short ? `${h}h` : `${h} giờ`;
  return short ? `${h}h ${m}m` : `${h} giờ ${m} phút`;
}

/** 142 → "142h" — dùng cho tổng giờ */
export function minutesToHours(min: number): string {
  return `${(min / 60).toFixed(1)}h`;
}

/** Avatar fallback từ tên */
export function avatarText(name?: string | null): string {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** "11/05/2026 07:02:15" — Vietnamese order */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** "11/05" — short */
export function formatDateShort(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Relative: "5 phút trước", "2 giờ trước", "Hôm qua" */
export function timeAgo(iso: string): string {
  const d = new Date(iso).getTime();
  if (!d) return iso;
  const diff = Math.floor((Date.now() - d) / 1000);
  if (diff < 60) return 'Vừa xong';
  if (diff < 3600) return `${Math.floor(diff / 60)} phút trước`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} giờ trước`;
  if (diff < 172800) return 'Hôm qua';
  if (diff < 604800) return `${Math.floor(diff / 86400)} ngày trước`;
  return formatDateShort(iso);
}

/** "Thứ 2", "Thứ 3"... — ISO weekday: 0=Mon */
export const WEEKDAYS_VI = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'Chủ nhật'];
export const WEEKDAYS_SHORT_VI = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'];

/** ISO weekday hôm nay: 0=Mon, 6=Sun (JS getDay 0=Sun → cần shift) */
export function todayIsoWeekday(): number {
  const d = new Date().getDay();
  return d === 0 ? 6 : d - 1;
}

/** Period label */
export const PERIOD_LABELS: Record<string, string> = {
  day: 'Hôm nay',
  week: 'Tuần',
  month: 'Tháng',
  quarter: 'Quý',
};

/** Greeting theo giờ */
export function greetingByHour(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Chào buổi sáng';
  if (h < 18) return 'Chào buổi chiều';
  return 'Chào buổi tối';
}

/** Compliance color class */
export function complianceColor(rate: number): {
  text: string;
  bg: string;
  dot: string;
} {
  if (rate >= 90) return { text: 'text-green-500', bg: 'bg-green-500', dot: 'bg-green-500' };
  if (rate >= 70) return { text: 'text-amber-500', bg: 'bg-amber-500', dot: 'bg-amber-500' };
  return { text: 'text-red-500', bg: 'bg-red-500', dot: 'bg-red-500' };
}
