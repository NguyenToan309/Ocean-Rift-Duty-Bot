/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useState, useEffect, useMemo } from 'react';
import { detectAuth, startDiscordLogin, verify2FA, logout } from './lib/auth';
import {
  useGuilds,
  useOverview,
  useChart,
  useRanking,
  useAttendance,
  useLogs,
  useScheduleGrid,
  useScheduleCalendar,
  useScheduleCompliance,
  useLeaveList,
  useAuditLogs,
  useRealtime,
  useMutation,
} from './lib/hooks';
import { api, formatError } from './lib/api';
import {
  minutesToHours,
  minutesToHHMM,
  avatarText,
  formatDateTime,
  greetingByHour,
  complianceColor,
  WEEKDAYS_VI,
  todayIsoWeekday,
} from './lib/format';
import { 
  BarChart3, 
  Calendar, 
  ClipboardList, 
  FileText, 
  History, 
  LayoutDashboard, 
  LogOut, 
  Moon, 
  Search, 
  Settings, 
  ShieldAlert, 
  Sun, 
  Trophy, 
  Users,
  Bell,
  ChevronDown,
  Download,
  Filter,
  CheckCircle2,
  Clock,
  AlertCircle
} from 'lucide-react';
import { 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer 
} from 'recharts';
import { motion, AnimatePresence } from 'motion/react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// CHART_DATA + TOP_STAFF giờ đến từ hooks bên trong component (useChart + useRanking).

/** Quick action cards trong Overview — đếm pending leaves + staff đang đi muộn. */
function OverviewQuickActions({
  guildId,
  onGoLeave,
  onGoSchedule,
  scheduleComplianceData,
}: {
  guildId: string | null;
  onGoLeave: () => void;
  onGoSchedule: () => void;
  scheduleComplianceData: any[] | null;
}) {
  // Pending leaves
  const pendingLeavesQ = useLeaveList(guildId, 'PENDING');
  const pendingCount = pendingLeavesQ.data?.length ?? 0;

  // Late/missed staff today — đếm từ compliance data nếu có
  const lateCount = (scheduleComplianceData || []).filter((r: any) => (r?.late ?? 0) > 0 || (r?.missed ?? 0) > 0).length;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
      <button
        onClick={onGoSchedule}
        className="rounded-xl border border-dashed border-[var(--color-border)] p-6 flex items-center justify-between group cursor-pointer hover:border-[var(--color-brand)] transition-all text-left"
      >
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-500 group-hover:bg-[var(--color-brand-muted)] group-hover:text-[var(--color-brand)] transition-all">
            <AlertCircle size={24} />
          </div>
          <div>
            <h4 className="font-bold">Nhân sự đi muộn / vắng</h4>
            <p className="text-sm text-[var(--color-text-secondary)]">
              {scheduleComplianceData === null
                ? 'Mở "Lịch trực → Tuân thủ" để xem chi tiết.'
                : lateCount === 0
                ? 'Không có ai trễ/vắng trong kỳ này.'
                : `${lateCount} nhân sự có ca trễ hoặc bỏ ca`}
            </p>
          </div>
        </div>
        <span className="px-3 py-1.5 rounded-lg text-xs font-bold bg-amber-500/10 text-amber-500 border border-amber-500/20 group-hover:bg-amber-500 group-hover:text-white transition-all">
          Kiểm tra ngay
        </span>
      </button>

      <button
        onClick={onGoLeave}
        className="rounded-xl border border-dashed border-[var(--color-border)] p-6 flex items-center justify-between group cursor-pointer hover:border-[var(--color-brand)] transition-all text-left"
      >
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-500 group-hover:bg-[var(--color-brand-muted)] group-hover:text-[var(--color-brand)] transition-all">
            <FileText size={24} />
          </div>
          <div>
            <h4 className="font-bold">Đơn nghỉ phép mới</h4>
            <p className="text-sm text-[var(--color-text-secondary)]">
              {pendingLeavesQ.loading
                ? 'Đang đếm…'
                : pendingCount === 0
                ? 'Không có đơn nào đang chờ.'
                : `${pendingCount} đơn đang chờ phê duyệt`}
            </p>
          </div>
        </div>
        <span className="px-3 py-1.5 rounded-lg text-xs font-bold bg-blue-500/10 text-blue-500 border border-blue-500/20 group-hover:bg-blue-500 group-hover:text-white transition-all">
          Duyệt ngay
        </span>
      </button>
    </div>
  );
}

type AuthState = 'loading' | 'anon' | 'need_2fa' | 'authed';
type Period = 'day' | 'week' | 'month' | 'quarter';

export default function App() {
  // ----- AUTH -----
  const [authState, setAuthState] = useState<AuthState>('loading');
  const [me, setMe] = useState<Awaited<ReturnType<typeof api.me>> | null>(null);
  const [showOTP, setShowOTP] = useState(false);
  const [otpDigits, setOtpDigits] = useState<string[]>(['', '', '', '', '', '']);
  const [otpError, setOtpError] = useState<string | null>(null);
  const verifyMut = useMutation((code: string) => verify2FA(code));

  // ----- NAVIGATION -----
  const [activeTab, setActiveTab] = useState<
    'overview' | 'ranking' | 'attendance' | 'schedule' | 'leave' | 'logs' | 'audit'
  >('overview');
  const [scheduleTab, setScheduleTab] = useState<'grid' | 'calendar' | 'compliance'>('grid');
  const [leaveTab, setLeaveTab] = useState<'pending' | 'approved' | 'rejected' | 'resign'>('pending');

  // ----- UI STATE -----
  const [isDarkMode, setIsDarkMode] = useState(true);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [editingShift, setEditingShift] = useState<any>(null);
  const [shiftForm, setShiftForm] = useState({
    start_time: '',
    end_time: '',
    role_name: '',
    weekday: 0,
    note: '',
  });
  const [shiftSaving, setShiftSaving] = useState(false);
  // user_id giữ STRING — Discord ID là 64-bit BigInt, JS Number sẽ mất precision.
  const [attendanceDetail, setAttendanceDetail] = useState<{
    user_id: string;
    username: string;
  } | null>(null);
  const [exporting, setExporting] = useState(false);
  // Calendar month/year state (default = hôm nay)
  const _now = new Date();
  const [calMonth, setCalMonth] = useState(_now.getMonth() + 1);
  const [calYear, setCalYear] = useState(_now.getFullYear());

  // ----- GLOBAL FILTERS -----
  const [guildId, setGuildId] = useState<string | null>(null);
  const [period, setPeriod] = useState<Period>('month');
  const [logsPage, setLogsPage] = useState(1);
  const [logsSearch, setLogsSearch] = useState('');
  const [auditPage, setAuditPage] = useState(1);
  const [rankingSearch, setRankingSearch] = useState('');
  // Attendance view mode: 'hours' = giờ trực thông thường | 'compliance' = tuân thủ ca theo lịch
  const [attendanceViewMode, setAttendanceViewMode] = useState<'hours' | 'compliance' | 'auto'>('auto');

  // ----- AUTH DETECTION ON MOUNT -----
  useEffect(() => {
    let cancelled = false;
    detectAuth().then((res) => {
      if (cancelled) return;
      if (res.state === 'authed') {
        setAuthState('authed');
        setMe(res.me);
      } else if (res.state === 'need_2fa') {
        setAuthState('need_2fa');
        setShowOTP(true);
      } else {
        setAuthState('anon');
      }
    });
    return () => { cancelled = true; };
  }, []);

  // ----- DATA HOOKS — chỉ gọi khi đã authed -----
  const guildsQ = useGuilds();
  useEffect(() => {
    if (!guildId && guildsQ.data && guildsQ.data.length > 0) {
      setGuildId(guildsQ.data[0].id);
    }
  }, [guildsQ.data, guildId]);

  const overviewQ = useOverview(authState === 'authed' ? guildId : null, period);
  const chartQ = useChart(authState === 'authed' ? guildId : null, period);
  const topRankQ = useRanking(authState === 'authed' ? guildId : null, period, 'top', 3);
  const fullRankQ = useRanking(authState === 'authed' && activeTab === 'ranking' ? guildId : null, period, 'top', 20);
  const attendanceQ = useAttendance(authState === 'authed' && activeTab === 'attendance' ? guildId : null, period);
  const scheduleGridQ = useScheduleGrid(authState === 'authed' && activeTab === 'schedule' && scheduleTab === 'grid' ? guildId : null);
  const scheduleCalendarQ = useScheduleCalendar(
    authState === 'authed' && activeTab === 'schedule' && scheduleTab === 'calendar' ? guildId : null,
    calYear,
    calMonth,
  );
  const scheduleComplianceQ = useScheduleCompliance(authState === 'authed' && activeTab === 'schedule' && scheduleTab === 'compliance' ? guildId : null, period);
  const leaveQ = useLeaveList(
    authState === 'authed' && activeTab === 'leave' ? guildId : null,
    leaveTab.toUpperCase(),
  );
  const logsQ = useLogs(authState === 'authed' && activeTab === 'logs' ? guildId : null, logsPage, logsSearch);
  const auditQ = useAuditLogs(authState === 'authed' && activeTab === 'audit' ? guildId : null, auditPage);

  // Pending leave count cho topbar bell badge — luôn fetch khi đã auth
  const pendingLeavesQ = useLeaveList(authState === 'authed' ? guildId : null, 'PENDING');
  const pendingLeavesCount = pendingLeavesQ.data?.length ?? 0;

  // ----- REALTIME -----
  // Backend /ws bắt buộc guild_id; chỉ connect khi đã chọn guild.
  useRealtime(
    authState === 'authed',
    (evt) => {
      if (evt.type === 'duty_log_created' || evt.type === 'duty_log_deleted') {
        overviewQ.refetch();
        chartQ.refetch();
        if (activeTab === 'logs') logsQ.refetch();
      }
      if ((evt.type === 'leave_decided' || evt.type === 'leave_decision') && activeTab === 'leave') {
        leaveQ.refetch();
        pendingLeavesQ.refetch();
      }
      if (evt.type === 'schedule_updated' && activeTab === 'schedule') {
        scheduleGridQ.refetch();
      }
    },
    guildId,
  );

  // ----- DERIVED -----
  const currentGuild = useMemo(
    () => guildsQ.data?.find((g) => g.id === guildId) || null,
    [guildsQ.data, guildId],
  );
  const TODAY_INDEX = todayIsoWeekday();
  const DAYS = WEEKDAYS_VI;

  // CHART_DATA shape: backend trả { date, value } → recharts cần { name, value }
  // Backend trả `value` là tổng PHÚT trong ngày. Convert sang giờ (1 chữ số thập phân)
  // cho dễ đọc. Tooltip vẫn hiển thị cả phút.
  const CHART_DATA = useMemo(
    () => (chartQ.data || []).map((p) => ({
      name: p.date,
      hours: +(p.value / 60).toFixed(1),
      minutes: p.value,
    })),
    [chartQ.data],
  );

  // TOP_STAFF cho overview sidebar
  const TOP_STAFF = useMemo(
    () =>
      (topRankQ.data || []).map((r) => ({
        name: r.username,
        hours: Math.round(r.total_minutes / 60),
        sessions: r.session_count,
        rank: r.rank,
        avatar: avatarText(r.username),
      })),
    [topRankQ.data],
  );

  // WEEKLY_SHIFTS flatten cho schedule grid
  const WEEKLY_SHIFTS = useMemo(() => {
    if (!scheduleGridQ.data) return [];
    const out: Array<{ id: number; name: string; role: string; time: string; dept: string; status: string; day: number }> = [];
    for (const day of scheduleGridQ.data.days) {
      for (const slot of day.slots) {
        // status đơn giản: nếu weekday < today = completed, == today = active, > today = upcoming
        const status = day.weekday < TODAY_INDEX ? 'completed' : day.weekday === TODAY_INDEX ? 'active' : 'upcoming';
        out.push({
          id: slot.id,
          name: slot.username,
          role: slot.role_name || 'Trực',
          time: `${slot.start_time} - ${slot.end_time}`,
          dept: slot.department || '—',
          status,
          day: day.weekday,
        });
      }
    }
    return out;
  }, [scheduleGridQ.data, TODAY_INDEX]);

  // COMPLIANCE_DATA reuse cho attendance cards + compliance tab
  const COMPLIANCE_DATA = useMemo(() => {
    const src = activeTab === 'attendance' ? attendanceQ.data : scheduleComplianceQ.data;
    if (!src) return [];
    return src.map((row: any) => ({
      name: row.username,
      total: row.total_scheduled ?? row.total ?? 0,
      onTime: row.on_time ?? 0,
      late: row.late ?? 0,
      missed: row.missed ?? 0,
      rate: row.compliance_rate ?? row.rate ?? 0,
    }));
  }, [activeTab, attendanceQ.data, scheduleComplianceQ.data]);

  // ----- DARK MODE SYNC -----
  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDarkMode]);

  // ----- SYNC SHIFT FORM WHEN MODAL OPENS -----
  useEffect(() => {
    if (!editingShift) return;
    // Parse "07:00 - 19:00" → start/end
    const time = String(editingShift.time || '');
    const [start = '07:00', end = '19:00'] = time.split('-').map((s) => s.trim());
    setShiftForm({
      start_time: start,
      end_time: end,
      role_name: editingShift.role || '',
      weekday: typeof editingShift.day === 'number' ? editingShift.day : 0,
      note: '',
    });
  }, [editingShift]);

  // ----- ATTENDANCE DAILY DETAIL -----
  // Lấy 30 ngày gần nhất. Backend get_custom_range CHỈ chấp nhận format
  // DD/MM/YYYY (Việt Nam) — KHÔNG phải ISO YYYY-MM-DD. Format đúng để tránh
  // ValueError → HTTP 400 → modal trống.
  const attendanceDailyRange = useMemo(() => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - 30);
    const fmt = (d: Date) => {
      const dd = String(d.getDate()).padStart(2, '0');
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      return `${dd}/${mm}/${d.getFullYear()}`;
    };
    return { start: fmt(start), end: fmt(end) };
  }, [attendanceDetail]);

  type AttendanceDailyDay = {
    date: string;
    weekday_label: string;
    weekday_short: string;
    is_today: boolean;
    is_future: boolean;
    status: string;
    minutes: number;
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
  };

  const [attendanceDailyData, setAttendanceDailyData] = useState<{
    summary: any | null;
    days: AttendanceDailyDay[];
  } | null>(null);
  const [attendanceDailyLoading, setAttendanceDailyLoading] = useState(false);
  const [attendanceFilter, setAttendanceFilter] = useState<'all' | 'with_activity' | 'with_schedule' | 'missed'>('with_activity');
  // Date range tự custom — defaults 30 ngày qua
  const [attendanceCustomRange, setAttendanceCustomRange] = useState<{ from: string; to: string } | null>(null);

  useEffect(() => {
    if (!attendanceDetail || !guildId) {
      setAttendanceDailyData(null);
      return;
    }
    setAttendanceDailyLoading(true);
    const ctrl = new AbortController();
    const from = attendanceCustomRange?.from || attendanceDailyRange.start;
    const to = attendanceCustomRange?.to || attendanceDailyRange.end;
    api
      .attendanceDaily(guildId, attendanceDetail.user_id, from, to)
      .then((data) => {
        if (!ctrl.signal.aborted) setAttendanceDailyData(data);
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) {
          console.error('attendance daily fetch failed', err);
          setAttendanceDailyData({ summary: null, days: [] });
        }
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setAttendanceDailyLoading(false);
      });
    return () => ctrl.abort();
  }, [attendanceDetail, guildId, attendanceDailyRange.start, attendanceDailyRange.end, attendanceCustomRange]);

  // Reset custom range khi đóng modal
  useEffect(() => {
    if (!attendanceDetail) {
      setAttendanceCustomRange(null);
      setAttendanceFilter('with_activity');
    }
  }, [attendanceDetail]);

  // ----- EXPORT HANDLER -----
  // mode='logs' (default): raw từng duty log
  // mode='ranking': aggregate 1 row/người (sort theo tổng phút giảm dần)
  const handleExport = async (format: 'csv' | 'excel', mode: 'logs' | 'ranking' = 'logs') => {
    if (!guildId) {
      alert('Vui lòng chọn server trước khi xuất.');
      return;
    }
    setExporting(true);
    try {
      const res = await api.exportPrepare(guildId, format, period, { mode });
      window.open(res.download_url, '_blank');
    } catch (err: any) {
      alert('Lỗi xuất báo cáo: ' + formatError(err));
    } finally {
      setExporting(false);
    }
  };

  // ----- AUTH HANDLERS -----
  const handleLogin = () => startDiscordLogin();
  const handleVerify = async () => {
    const code = otpDigits.join('');
    if (code.length !== 6) {
      setOtpError('Vui lòng nhập đủ 6 chữ số');
      return;
    }
    setOtpError(null);
    try {
      await verifyMut.mutate(code);
    } catch (err: any) {
      setOtpError(err?.detail || 'Mã không hợp lệ');
    }
  };
  const handleLogout = () => logout();

  // OTP keyboard handlers
  const setOtpDigit = (i: number, v: string) => {
    const clean = v.replace(/\D/g, '').slice(0, 1);
    const next = [...otpDigits];
    next[i] = clean;
    setOtpDigits(next);
    // Auto-focus next
    if (clean && i < 5) {
      const el = document.getElementById(`otp-${i + 1}`) as HTMLInputElement | null;
      el?.focus();
    }
  };

  const isAuthenticated = authState === 'authed';

  // Splash khi đang detect auth — tránh flash login page
  if (authState === 'loading') {
    return (
      <div className={cn("min-h-screen flex items-center justify-center", isDarkMode ? "bg-slate-950 text-white" : "bg-slate-50 text-slate-900")}>
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
          <p className="text-sm text-slate-500 font-medium">Đang xác thực…</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className={cn("min-h-screen flex flex-col items-center justify-center p-4 transition-colors duration-300", isDarkMode ? "bg-slate-950 text-white" : "bg-slate-50 text-slate-900")}>
        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="w-full max-w-md bg-[var(--color-bg-surface)] border border-[var(--color-border)] rounded-2xl shadow-2xl overflow-hidden p-8 space-y-8"
        >
          <div className="text-center space-y-2">
            <div className="w-16 h-16 bg-[var(--color-brand)] rounded-2xl flex items-center justify-center text-white mx-auto shadow-lg shadow-blue-500/20 mb-4">
              <ShieldAlert size={32} />
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Homie Medic</h1>
            <p className="text-sm text-[var(--color-text-secondary)]">Hệ thống quản lý chấm công & nhân sự y khoa</p>
          </div>

          <AnimatePresence mode="wait">
            {!showOTP ? (
              <motion.div 
                key="login"
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 10 }}
                className="space-y-4"
              >
                <div className="p-4 bg-slate-100 dark:bg-slate-800 rounded-xl border border-[var(--color-border)] text-sm text-[var(--color-text-secondary)] text-center">
                  Chào mừng trở lại. Vui lòng đăng nhập bằng tài khoản Discord nội bộ.
                </div>
                <button 
                  onClick={handleLogin}
                  className="w-full flex items-center justify-center gap-3 bg-[#5865F2] hover:bg-[#4752C4] text-white py-3 rounded-xl font-bold transition-all shadow-lg shadow-indigo-500/20 active:scale-[0.98]"
                >
                  <svg className="w-5 h-5 fill-current" viewBox="0 0 24 24"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.06.06 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.419-2.157 2.419zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.419-2.157 2.419z"/></svg>
                  Đăng nhập bằng Discord
                </button>
              </motion.div>
            ) : (
              <motion.div 
                key="otp"
                initial={{ opacity: 0, x: 10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                className="space-y-6"
              >
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-wider text-[var(--color-text-secondary)]">Mã 2FA (TOTP)</label>
                  <div className="grid grid-cols-6 gap-2">
                    {[0, 1, 2, 3, 4, 5].map((i) => (
                      <input
                        key={i}
                        id={`otp-${i}`}
                        type="text"
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        maxLength={1}
                        value={otpDigits[i]}
                        onChange={(e) => setOtpDigit(i, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleVerify();
                          if (e.key === 'Backspace' && !otpDigits[i] && i > 0) {
                            const prev = document.getElementById(`otp-${i - 1}`) as HTMLInputElement | null;
                            prev?.focus();
                          }
                        }}
                        className="w-full aspect-square bg-slate-100 dark:bg-slate-800 border border-[var(--color-border)] rounded-lg text-center font-bold text-lg focus:ring-2 focus:ring-[var(--color-brand)] focus:outline-none"
                      />
                    ))}
                  </div>
                  {otpError && (
                    <p className="text-xs font-semibold text-red-500" role="alert">{otpError}</p>
                  )}
                </div>
                <button
                  onClick={handleVerify}
                  disabled={verifyMut.loading}
                  className="w-full bg-[var(--color-brand)] text-white py-3 rounded-xl font-bold transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {verifyMut.loading ? 'Đang xác thực…' : 'Xác nhận'}
                </button>
                <button 
                  onClick={() => setShowOTP(false)}
                  className="w-full text-sm font-semibold text-[var(--color-text-secondary)] hover:text-[var(--color-text-main)]"
                >
                  Quay lại
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
        
        <p className="mt-8 text-xs text-slate-500">© 2026 Medic System • ISO 27001 Certified</p>
      </div>
    );
  }

  const navItems = [
    { id: 'overview', label: 'Tổng quan', icon: LayoutDashboard },
    { id: 'ranking', label: 'Bảng xếp hạng', icon: Trophy },
    { id: 'attendance', label: 'Chấm công', icon: ClipboardList },
    { id: 'schedule', label: 'Lịch trực', icon: Calendar },
    { id: 'leave', label: 'Đơn nghỉ phép', icon: FileText },
    { id: 'logs', label: 'Lịch sử log', icon: History },
    { id: 'audit', label: 'Truy vết (Audit)', icon: ShieldAlert },
  ];

  return (
    <div className="min-h-screen flex text-[var(--color-text-main)] transition-colors duration-300">
      {/* Sidebar */}
      <aside 
        className={cn(
          "h-screen sticky top-0 bg-[var(--color-bg-surface)] border-r border-[var(--color-border)] flex flex-col transition-all duration-300 z-50",
          isSidebarCollapsed ? "w-20" : "w-64"
        )}
      >
        <div className="p-6 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-[var(--color-brand)] flex items-center justify-center text-white shrink-0">
            <ShieldAlert size={20} />
          </div>
          {!isSidebarCollapsed && (
            <span className="font-bold text-lg tracking-tight">HOMIE MEDIC</span>
          )}
        </div>

        <nav className="flex-1 px-4 py-2 space-y-1">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id as typeof activeTab)}
              className={cn(
                "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all group relative",
                activeTab === item.id 
                  ? "bg-[var(--color-brand-muted)] text-[var(--color-brand)]" 
                  : "text-[var(--color-text-secondary)] hover:bg-slate-100 dark:hover:bg-slate-800/50 hover:text-[var(--color-text-main)]"
              )}
            >
              <item.icon size={20} className={cn(
                "shrink-0",
                activeTab === item.id ? "text-[var(--color-brand)]" : "text-slate-400 group-hover:text-slate-200"
              )} />
              {!isSidebarCollapsed && <span>{item.label}</span>}
              {activeTab === item.id && (
                <motion.div 
                  layoutId="activeRail"
                  className="absolute left-0 w-1 h-6 bg-[var(--color-brand)] rounded-r-full"
                />
              )}
            </button>
          ))}
        </nav>

        <div className="p-4 border-t border-[var(--color-border)] space-y-4">
          <button 
            onClick={() => setIsDarkMode(!isDarkMode)}
            className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-[var(--color-text-secondary)] hover:bg-slate-100 dark:hover:bg-slate-800/50 transition-all"
          >
            {isDarkMode ? <Sun size={18} /> : <Moon size={18} />}
            {!isSidebarCollapsed && <span>{isDarkMode ? 'Chế độ sáng' : 'Chế độ tối'}</span>}
          </button>
          
          {!isSidebarCollapsed ? (
            <div className="flex items-center gap-3 px-3 py-2">
              {me?.avatar_url ? (
                <img src={me.avatar_url} alt="" className="w-8 h-8 rounded-full ring-2 ring-[var(--color-border)] object-cover" />
              ) : (
                <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center text-xs font-bold ring-2 ring-[var(--color-border)]">
                  {avatarText(me?.global_name || me?.username)}
                </div>
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold truncate">{me?.global_name || me?.username || 'User'}</p>
                <p className="text-xs text-[var(--color-text-secondary)] truncate">
                  {currentGuild ? `${currentGuild.role === 'ADMIN' ? 'Quản trị viên' : currentGuild.role === 'MOD' ? 'Điều hành' : 'Thành viên'}` : 'Đang tải…'}
                </p>
              </div>
              <button onClick={handleLogout} aria-label="Đăng xuất" className="text-slate-500 hover:text-red-400 transition-colors">
                <LogOut size={16} />
              </button>
            </div>
          ) : (
            <button onClick={handleLogout} aria-label="Đăng xuất" className="flex justify-center py-2 w-full">
              {me?.avatar_url ? (
                <img src={me.avatar_url} alt="" className="w-8 h-8 rounded-full ring-2 ring-[var(--color-border)] object-cover" />
              ) : (
                <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center text-xs font-bold ring-2 ring-[var(--color-border)]">
                  {avatarText(me?.global_name || me?.username)}
                </div>
              )}
            </button>
          )}
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col min-w-0 bg-[var(--color-bg-base)]">
        {/* Topbar */}
        <header className="h-[60px] bg-[var(--color-bg-surface)] border-b border-[var(--color-border)] px-8 flex items-center justify-between sticky top-0 z-40">
          <div className="flex items-center gap-6">
            {guildsQ.data && guildsQ.data.length > 0 ? (
              <label className="relative flex items-center gap-2 px-3 py-1.5 bg-slate-100 dark:bg-slate-800 rounded-md border border-[var(--color-border)] hover:border-slate-600 transition-all cursor-pointer">
                <span className="text-xs font-bold text-[var(--color-brand)]">SERVER</span>
                <select
                  value={guildId || ''}
                  onChange={(e) => setGuildId(e.target.value)}
                  className="bg-transparent text-sm font-medium focus:outline-none pr-5 appearance-none cursor-pointer"
                >
                  {guildsQ.data.map((g) => (
                    <option key={g.id} value={g.id}>{g.name}</option>
                  ))}
                </select>
                <ChevronDown size={14} className="text-slate-500 absolute right-3 pointer-events-none" />
              </label>
            ) : (
              <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-100 dark:bg-slate-800 rounded-md border border-[var(--color-border)]">
                <span className="text-xs font-bold text-[var(--color-text-secondary)]">SERVER</span>
                <span className="text-sm font-medium text-slate-500">{guildsQ.loading ? 'Đang tải…' : 'Không có'}</span>
              </div>
            )}

            <div className="h-4 w-px bg-[var(--color-border)] hidden md:block" />

            <div className="hidden lg:flex items-center gap-1 text-sm bg-slate-100 dark:bg-slate-800 p-1 rounded-lg border border-[var(--color-border)]">
              {([
                { key: 'day', label: 'Hôm nay' },
                { key: 'week', label: 'Tuần' },
                { key: 'month', label: 'Tháng' },
                { key: 'quarter', label: 'Quý' },
              ] as const).map((p) => (
                <button
                  key={p.key}
                  onClick={() => setPeriod(p.key)}
                  className={cn(
                    "px-3 py-1 rounded-md transition-all",
                    period === p.key ? "bg-[var(--color-bg-surface)] shadow-sm text-[var(--color-brand)] font-semibold" : "text-[var(--color-text-secondary)] hover:text-[var(--color-text-main)]"
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="relative hidden sm:block">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="text"
                placeholder="Tìm theo tên (bảng xếp hạng)"
                value={rankingSearch}
                onChange={(e) => {
                  setRankingSearch(e.target.value);
                  // Auto-switch sang tab ranking khi gõ search nếu chưa ở đó
                  if (e.target.value && activeTab !== 'ranking' && activeTab !== 'logs') {
                    setActiveTab('ranking');
                  }
                }}
                className="pl-10 pr-4 py-1.5 bg-slate-100 dark:bg-slate-800 border border-[var(--color-border)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-brand)] w-64 transition-all"
              />
            </div>
            <button
              onClick={() => { setActiveTab('leave'); setLeaveTab('pending'); }}
              aria-label="Thông báo: đơn nghỉ phép đang chờ"
              className="p-2 text-slate-500 hover:text-[var(--color-brand)] transition-colors relative"
            >
              <Bell size={20} />
              {pendingLeavesCount > 0 && (
                <span className="absolute top-1 right-1 min-w-[16px] h-4 px-1 bg-red-500 text-white text-[9px] font-bold rounded-full flex items-center justify-center border-2 border-[var(--color-bg-surface)]">
                  {pendingLeavesCount > 9 ? '9+' : pendingLeavesCount}
                </span>
              )}
            </button>
          </div>
        </header>

        {/* Content Section */}
        <div className="p-8 max-w-7xl mx-auto w-full space-y-8">
          <AnimatePresence mode="wait">
            {activeTab === 'overview' && (
              <motion.div 
                key="overview"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-8"
              >
                {/* Hero Panel */}
                <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-blue-600 to-indigo-700 p-8 text-white shadow-xl">
                  <div className="relative z-10 flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                        <span className="text-xs font-bold uppercase tracking-widest opacity-80">Hệ thống đang trực tuyến</span>
                      </div>
                      <h1 className="text-3xl font-bold mb-2">{greetingByHour()}, {me?.global_name || me?.username || 'Admin'}</h1>
                      <p className="text-blue-100/80 max-w-md">
                        {overviewQ.loading ? 'Đang tải dữ liệu…' : overviewQ.data ? (
                          <>
                            Hiện có <span className="font-bold text-white">{overviewQ.data.active_members} nhân sự</span> đang active / {overviewQ.data.total_members} tổng.
                            Tổng <span className="font-bold text-white">{overviewQ.data.total_sessions} ca</span>
                            <span className="font-bold text-white"> · {minutesToHHMM(overviewQ.data.total_minutes, false)}</span> trong kỳ.
                          </>
                        ) : 'Chưa có dữ liệu cho server này.'}
                      </p>
                    </div>
                    <div className="flex gap-3">
                      <button
                        onClick={() => handleExport('excel')}
                        disabled={exporting}
                        className="px-4 py-2 bg-white/10 backdrop-blur-md border border-white/20 rounded-lg font-semibold hover:bg-white/20 transition-all flex items-center gap-2 text-sm disabled:opacity-50"
                      >
                        <Download size={16} /> {exporting ? 'Đang xuất…' : 'Xuất báo cáo'}
                      </button>
                      <button
                        onClick={() => setActiveTab('schedule')}
                        className="px-4 py-2 bg-white text-blue-700 rounded-lg font-bold hover:shadow-lg transition-all text-sm"
                      >
                        Quản lý lịch trực
                      </button>
                    </div>
                  </div>
                  {/* Decorative Pattern */}
                  <div className="absolute top-0 right-0 w-64 h-64 bg-white/5 rounded-full -translate-y-1/2 translate-x-1/2 blur-3xl pointer-events-none" />
                  <div className="absolute bottom-0 left-0 w-32 h-32 bg-indigo-400/10 rounded-full translate-y-1/2 -translate-x-1/2 blur-2xl pointer-events-none" />
                </div>

                {/* Stat Cards */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
                  {([
                    {
                      label: 'Tổng giờ trực',
                      value: overviewQ.data ? minutesToHHMM(overviewQ.data.total_minutes) : '—',
                      info: overviewQ.data ? `${overviewQ.data.total_sessions} ca` : undefined,
                      icon: BarChart3,
                      color: 'var(--color-brand)',
                    },
                    {
                      label: 'Nhân sự Active',
                      value: overviewQ.data ? String(overviewQ.data.active_members) : '—',
                      info: overviewQ.data ? `/${overviewQ.data.total_members} tổng` : undefined,
                      icon: Users,
                      color: 'var(--color-accent)',
                    },
                    {
                      label: 'Thời gian TB',
                      value: overviewQ.data ? minutesToHHMM(overviewQ.data.avg_minutes_per_session) : '—',
                      icon: Clock,
                      color: 'var(--color-warning)',
                    },
                    {
                      label: 'Độ tuân thủ',
                      value:
                        overviewQ.data && overviewQ.data.compliance_rate !== null
                          ? `${overviewQ.data.compliance_rate.toFixed(1)}%`
                          : '—',
                      status:
                        overviewQ.data && overviewQ.data.compliance_rate !== null
                          ? overviewQ.data.compliance_rate >= 90 ? 'Tốt' : overviewQ.data.compliance_rate >= 70 ? 'Trung bình' : 'Kém'
                          : undefined,
                      icon: CheckCircle2,
                      color: 'var(--color-success)',
                    },
                  ] as Array<{ label: string; value: string; trend?: string; info?: string; status?: string; icon: any; color: string }>).map((stat, i) => (
                    <motion.div 
                      key={stat.label}
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ delay: i * 0.1 }}
                      className="stat-card group"
                    >
                      <div className="flex justify-between items-start mb-4">
                        <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800 text-[var(--color-text-secondary)] transition-colors group-hover:bg-[var(--color-brand-muted)] group-hover:text-[var(--color-brand)]">
                          <stat.icon size={20} />
                        </div>
                        {stat.trend && (
                          <span className={cn(
                            "text-xs font-bold px-1.5 py-0.5 rounded",
                            stat.trend.startsWith('+') ? "text-green-500 bg-green-500/10" : "text-red-500 bg-red-500/10"
                          )}>
                            {stat.trend}
                          </span>
                        )}
                        {stat.status && (
                          <span className="text-xs font-bold text-green-500 flex items-center gap-1">
                            <div className="w-1.5 h-1.5 rounded-full bg-green-500" /> {stat.status}
                          </span>
                        )}
                      </div>
                      <div>
                        <p className="text-xs font-bold text-[var(--color-text-secondary)] uppercase tracking-wider mb-1">{stat.label}</p>
                        <div className="flex items-baseline gap-2">
                          <span className="text-2xl font-bold font-mono tracking-tight">{stat.value}</span>
                          {stat.info && <span className="text-xs text-slate-500">{stat.info}</span>}
                        </div>
                      </div>
                    </motion.div>
                  ))}
                </div>

                {/* Main Section Grid */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                  {/* Activity Chart */}
                  <div className="lg:col-span-2 rounded-xl bg-[var(--color-bg-surface)] border border-[var(--color-border)] p-6 shadow-sm">
                    <div className="flex justify-between items-center mb-8">
                      <div>
                        <h3 className="font-bold text-lg">Hoạt động trực (30 ngày)</h3>
                        <p className="text-sm text-[var(--color-text-secondary)]">Xu hướng tổng số giờ trực của toàn bộ staff</p>
                      </div>
                      <div className="px-3 py-2 border border-[var(--color-border)] rounded-lg flex items-center gap-2 text-xs font-bold uppercase text-[var(--color-text-secondary)]">
                        <Filter size={14} />
                        <span className="tabular-nums">
                          {period === 'day' ? 'Hôm nay' : period === 'week' ? 'Tuần này' : period === 'month' ? `Tháng ${new Date().getMonth() + 1}/${new Date().getFullYear()}` : `Q${Math.ceil((new Date().getMonth() + 1) / 3)}/${new Date().getFullYear()}`}
                        </span>
                      </div>
                    </div>
                    <div className="h-[300px] w-full">
                      {chartQ.loading && (
                        <div className="h-full flex items-center justify-center text-sm text-slate-500">Đang tải biểu đồ…</div>
                      )}
                      {!chartQ.loading && CHART_DATA.length === 0 && (
                        <div className="h-full flex items-center justify-center text-sm text-slate-500">Chưa có hoạt động trực trong kỳ.</div>
                      )}
                      {!chartQ.loading && CHART_DATA.length > 0 && (
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={CHART_DATA} margin={{ top: 5, right: 5, left: -10, bottom: 5 }}>
                          <defs>
                            <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="var(--color-brand)" stopOpacity={0.3}/>
                              <stop offset="95%" stopColor="var(--color-brand)" stopOpacity={0}/>
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
                          <XAxis
                            dataKey="name"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fill: 'var(--color-text-secondary)', fontSize: 12 }}
                            dy={10}
                          />
                          <YAxis
                            axisLine={false}
                            tickLine={false}
                            tick={{ fill: 'var(--color-text-secondary)', fontSize: 12 }}
                            tickFormatter={(v: number) => `${v}h`}
                            width={40}
                          />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: 'var(--color-bg-surface)',
                              borderColor: 'var(--color-border)',
                              borderRadius: '8px',
                              fontSize: '12px',
                            }}
                            labelStyle={{ color: 'var(--color-text-secondary)', marginBottom: 4 }}
                            formatter={(value: number, _name: string, item: any) => {
                              const mins = item?.payload?.minutes ?? Math.round(value * 60);
                              return [`${value}h (${minutesToHHMM(mins)})`, 'Thời gian trực'];
                            }}
                          />
                          <Area
                            type="monotone"
                            dataKey="hours"
                            stroke="var(--color-brand)"
                            strokeWidth={3}
                            fillOpacity={1}
                            fill="url(#colorValue)"
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                      )}
                    </div>
                  </div>

                  {/* Top Ranking Sidebar */}
                  <div className="rounded-xl bg-[var(--color-bg-surface)] border border-[var(--color-border)] p-6 shadow-sm h-full">
                    <h3 className="font-bold text-lg mb-6">Top trực tháng này</h3>
                    <div className="space-y-4">
                      {TOP_STAFF.map((staff, i) => (
                        <div key={staff.name} className="flex items-center gap-4 p-3 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-all border border-transparent hover:border-[var(--color-border)]">
                          <div className={cn(
                            "w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold relative",
                            staff.rank === 1 ? "bg-yellow-500/20 text-yellow-500 ring-2 ring-yellow-500/20" :
                            staff.rank === 2 ? "bg-slate-400/20 text-slate-400" : "bg-orange-400/20 text-orange-400"
                          )}>
                            {staff.avatar}
                            {i === 0 && <div className="absolute -top-1 -right-1 w-4 h-4 bg-yellow-500 rounded-full flex items-center justify-center border-2 border-[var(--color-bg-surface)]"><Trophy size={8} className="text-white" /></div>}
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-bold truncate">{staff.name}</p>
                            <p className="text-xs text-[var(--color-text-secondary)]">{staff.sessions} ca trực</p>
                          </div>
                          <div className="text-right">
                            <p className="text-sm font-mono font-bold text-[var(--color-brand)]">{staff.hours}h</p>
                            <div className="w-16 h-1 bg-slate-200 dark:bg-slate-700 rounded-full mt-1 overflow-hidden">
                              <div 
                                className="h-full bg-[var(--color-brand)]" 
                                style={{ width: `${(staff.hours / 150) * 100}%` }}
                              />
                            </div>
                          </div>
                        </div>
                      ))}
                      <button className="w-full mt-4 py-2 text-sm font-bold text-slate-500 hover:text-[var(--color-brand)] transition-colors">
                        Xem tất cả bảng xếp hạng →
                      </button>
                    </div>
                  </div>
                </div>

                {/* Quick Actions / Recent Alerts — đếm từ data thật */}
                <OverviewQuickActions
                  guildId={guildId}
                  onGoLeave={() => { setActiveTab('leave'); setLeaveTab('pending'); }}
                  onGoSchedule={() => { setActiveTab('schedule'); setScheduleTab('compliance'); }}
                  scheduleComplianceData={scheduleComplianceQ.data}
                />
              </motion.div>
            )}

            {activeTab === 'ranking' && (
              <motion.div 
                key="ranking"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-8"
              >
                {(() => {
                  const allRows = fullRankQ.data || [];
                  const top3 = allRows.slice(0, 3);
                  // High intensity = top 3 cao nhất (proxy cho burnout). Có thể đổi
                  // tiêu chí khi backend bổ sung warning chuyên dụng.
                  const intense = allRows.slice(0, 3);
                  const maxHours = allRows.length > 0 ? Math.max(...allRows.map((r: any) => r.total_minutes / 60)) : 1;
                  const filtered = rankingSearch
                    ? allRows.filter((r: any) => r.username.toLowerCase().includes(rankingSearch.toLowerCase()))
                    : allRows;
                  const periodLabel = period === 'day' ? 'Hôm nay' : period === 'week' ? 'Tuần này' : period === 'month' ? `Tháng ${new Date().getMonth() + 1}/${new Date().getFullYear()}` : `Quý ${Math.ceil((new Date().getMonth() + 1) / 3)}/${new Date().getFullYear()}`;
                  return (<>
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div>
                    <h2 className="text-2xl font-bold tracking-tight">Bảng xếp hạng trực</h2>
                    <p className="text-sm text-[var(--color-text-secondary)]">Thống kê hiệu suất và nỗ lực của đội ngũ y tế</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button className="px-4 py-2 bg-slate-100 dark:bg-slate-800 rounded-lg text-sm font-bold border border-[var(--color-border)] flex items-center gap-2 cursor-default">
                      <Calendar size={16} /> {periodLabel}
                    </button>
                    <button
                      onClick={() => handleExport('excel', 'ranking')}
                      disabled={exporting}
                      className="p-2 border border-[var(--color-border)] rounded-lg hover:bg-slate-800 transition-all disabled:opacity-50 flex items-center gap-2 text-xs font-bold"
                      aria-label="Xuất bảng xếp hạng Excel"
                      title="Xuất Excel bảng xếp hạng (1 row/nhân sự)"
                    >
                      <Download size={16} /> Xuất xếp hạng
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                  {/* Top Performers Card */}
                  <div className="bg-[var(--color-bg-surface)] p-6 rounded-2xl border border-[var(--color-border)] shadow-sm">
                    <div className="flex items-center gap-2 mb-6">
                      <div className="p-2 bg-yellow-500/10 text-yellow-500 rounded-lg"><Trophy size={20} /></div>
                      <h3 className="font-bold text-lg">Top nỗ lực cao nhất</h3>
                    </div>
                    <div className="space-y-6">
                      {fullRankQ.loading && (
                        <p className="text-center text-sm text-slate-500 py-6">Đang tính toán bảng xếp hạng…</p>
                      )}
                      {!fullRankQ.loading && top3.length === 0 && (
                        <p className="text-center text-sm text-slate-500 py-6">Chưa có ca trực nào trong kỳ.</p>
                      )}
                      {top3.map((row: any, i: number) => {
                        const hours = Math.round(row.total_minutes / 60);
                        return (
                        <div key={row.user_id} className="flex items-center gap-4">
                          <span className={cn(
                            "w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm shrink-0",
                            i === 0 ? "bg-yellow-500 text-white" : i === 1 ? "bg-slate-300 text-slate-700" : "bg-orange-400 text-white"
                          )}>
                            {i + 1}
                          </span>
                          <div className="flex-1 min-w-0">
                            <p className="font-bold text-sm truncate">{row.username}</p>
                            <div className="w-full h-1.5 bg-slate-100 dark:bg-slate-800 rounded-full mt-2 overflow-hidden">
                              <motion.div
                                initial={{ width: 0 }}
                                animate={{ width: `${maxHours > 0 ? (hours / maxHours) * 100 : 0}%` }}
                                transition={{ duration: 0.6, ease: 'easeOut' }}
                                className="h-full bg-[var(--color-brand)]"
                              />
                            </div>
                          </div>
                          <div className="text-right shrink-0">
                            <p className="text-sm font-bold font-mono text-[var(--color-brand)]">{hours}h</p>
                            <p className="text-[10px] text-slate-500 font-bold uppercase tabular-nums">{row.session_count} ca</p>
                          </div>
                        </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* High Intensity / Burnout Alert Card */}
                  <div className="bg-[var(--color-bg-surface)] p-6 rounded-2xl border border-[var(--color-border)] shadow-sm">
                    <div className="flex items-center gap-2 mb-6">
                      <div className="p-2 bg-red-500/10 text-red-500 rounded-lg"><AlertCircle size={20} /></div>
                      <h3 className="font-bold text-lg">Cảnh báo cường độ cao</h3>
                      <span className="ml-auto text-xs font-bold text-red-500 bg-red-500/10 px-2 py-0.5 rounded">Check burnout</span>
                    </div>
                    <div className="space-y-6">
                      {fullRankQ.loading && (
                        <p className="text-center text-sm text-slate-500 py-6">Đang tải…</p>
                      )}
                      {!fullRankQ.loading && intense.length === 0 && (
                        <p className="text-center text-sm text-slate-500 py-6">Không có cảnh báo trong kỳ này.</p>
                      )}
                      {intense.map((row: any) => {
                        const hours = Math.round(row.total_minutes / 60);
                        // Ngưỡng burnout: >220h/month, >55h/week, >9h/day
                        const threshold = period === 'day' ? 9 : period === 'week' ? 55 : period === 'quarter' ? 660 : 220;
                        const isBurnout = hours >= threshold;
                        const note = isBurnout
                          ? `Vượt ngưỡng ${threshold}h/${period === 'day' ? 'ngày' : period === 'week' ? 'tuần' : period === 'month' ? 'tháng' : 'quý'}`
                          : `Cường độ cao (${row.session_count} ca liên tiếp)`;
                        return (
                          <div key={row.user_id} className="flex items-center gap-4">
                            <div className="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center text-red-500 font-bold shrink-0">
                              {avatarText(row.username)}
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="font-bold text-sm truncate">{row.username}</p>
                              <p className="text-xs text-red-500 font-medium">{note}</p>
                            </div>
                            <div className="text-right shrink-0">
                              <p className="text-sm font-bold font-mono text-red-500">{hours}h</p>
                              <p className="text-[10px] text-slate-500 font-bold uppercase tabular-nums">{row.session_count} ca</p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>

                {/* Main Ranking Table */}
                <div className="bg-[var(--color-bg-surface)] rounded-2xl border border-[var(--color-border)] overflow-hidden shadow-sm">
                  <div className="px-6 py-4 border-b border-[var(--color-border)] flex flex-col md:flex-row md:justify-between md:items-center gap-3">
                    <div className="flex items-center gap-4">
                      <h3 className="font-bold text-lg">Danh sách chi tiết</h3>
                      <span className="text-xs text-slate-500 font-mono tabular-nums">{filtered.length}/{allRows.length} nhân sự</span>
                    </div>
                    <div className="flex items-center gap-2 relative">
                      <Search size={14} className="absolute left-3 text-slate-500" />
                      <input
                        type="text"
                        value={rankingSearch}
                        onChange={(e) => setRankingSearch(e.target.value)}
                        placeholder="Tìm tên..."
                        className="pl-9 pr-4 py-1.5 bg-slate-50 dark:bg-slate-900 border border-[var(--color-border)] rounded-lg text-xs focus:ring-2 focus:ring-[var(--color-brand)] outline-none"
                      />
                    </div>
                  </div>

                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="bg-slate-50 dark:bg-slate-900 border-b border-[var(--color-border)]">
                        <th className="px-6 py-4 font-bold text-[10px] uppercase tracking-wider text-slate-500">Thứ hạng</th>
                        <th className="px-6 py-4 font-bold text-[10px] uppercase tracking-wider text-slate-500">Nhân viên</th>
                        <th className="px-6 py-4 font-bold text-[10px] uppercase tracking-wider text-slate-500">Tổng giờ</th>
                        <th className="px-6 py-4 font-bold text-[10px] uppercase tracking-wider text-slate-500">Số ca</th>
                        <th className="px-6 py-4 font-bold text-[10px] uppercase tracking-wider text-slate-500">TB/Ca</th>
                        <th className="px-6 py-4 font-bold text-[10px] uppercase tracking-wider text-slate-500 text-right">Tỷ trọng</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--color-border)]">
                      {fullRankQ.loading && (
                        <tr><td colSpan={6} className="px-6 py-12 text-center text-sm text-slate-500">Đang tải bảng xếp hạng…</td></tr>
                      )}
                      {!fullRankQ.loading && filtered.length === 0 && allRows.length === 0 && (
                        <tr><td colSpan={6} className="px-6 py-12 text-center text-sm text-slate-500">Chưa có dữ liệu chấm công trong kỳ này.</td></tr>
                      )}
                      {!fullRankQ.loading && filtered.length === 0 && allRows.length > 0 && (
                        <tr><td colSpan={6} className="px-6 py-12 text-center text-sm text-slate-500">Không tìm thấy "{rankingSearch}".</td></tr>
                      )}
                      {filtered.map((row: any) => {
                        const hours = row.total_minutes / 60;
                        const avg = row.session_count > 0 ? hours / row.session_count : 0;
                        const ratio = maxHours > 0 ? (hours / maxHours) * 100 : 0;
                        return (
                          <tr key={row.user_id} className="hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-all group">
                            <td className="px-6 py-4 font-mono font-bold text-slate-400 tabular-nums">#{row.rank}</td>
                            <td className="px-6 py-4 font-bold group-hover:text-[var(--color-brand)] transition-colors">{row.username}</td>
                            <td className="px-6 py-4 font-mono font-bold tabular-nums">{hours.toFixed(1)}h</td>
                            <td className="px-6 py-4 font-mono tabular-nums">{row.session_count}</td>
                            <td className="px-6 py-4 font-medium text-slate-500 tabular-nums">{avg.toFixed(1)}h</td>
                            <td className="px-6 py-4 text-right">
                              <div className="inline-flex items-center gap-2 justify-end">
                                <div className="w-24 h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                                  <div className="h-full bg-[var(--color-brand)]" style={{ width: `${ratio}%` }} />
                                </div>
                                <span className="text-xs font-bold font-mono text-slate-400 tabular-nums w-12 text-right">{ratio.toFixed(0)}%</span>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                  </>);
                })()}
              </motion.div>
            )}

            {activeTab === 'schedule' && (
              <motion.div 
                key="schedule"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-6"
              >
                {/* Schedule Header & Toolbar */}
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div>
                    <h2 className="text-2xl font-bold tracking-tight">Lịch trực đơn vị</h2>
                    <p className="text-sm text-[var(--color-text-secondary)]">
                      Quản lý và điều phối ca trực toàn hệ thống ·
                      <span className="ml-1 font-mono tabular-nums">
                        {(() => {
                          // Hiển thị range hiện tại theo period
                          const now = new Date();
                          if (period === 'day') {
                            return now.toLocaleDateString('vi-VN');
                          }
                          if (period === 'week') {
                            const dow = (now.getDay() + 6) % 7;
                            const mon = new Date(now); mon.setDate(now.getDate() - dow);
                            const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
                            return `${mon.toLocaleDateString('vi-VN')} – ${sun.toLocaleDateString('vi-VN')}`;
                          }
                          if (period === 'month') {
                            return `Tháng ${now.getMonth() + 1}/${now.getFullYear()}`;
                          }
                          if (period === 'quarter') {
                            return `Quý ${Math.ceil((now.getMonth() + 1) / 3)}/${now.getFullYear()}`;
                          }
                          return '';
                        })()}
                      </span>
                    </p>
                  </div>
                  
                  <div className="flex items-center gap-3">
                    <div className="flex bg-slate-100 dark:bg-slate-800 p-1 rounded-xl border border-[var(--color-border)]">
                      <button 
                        onClick={() => setScheduleTab('grid')}
                        className={cn(
                          "px-4 py-1.5 rounded-lg text-sm font-bold transition-all",
                          scheduleTab === 'grid' ? "bg-[var(--color-bg-surface)] text-[var(--color-brand)] shadow-sm" : "text-slate-500 hover:text-slate-300"
                        )}
                      >
                        Tuần
                      </button>
                      <button 
                        onClick={() => setScheduleTab('calendar')}
                        className={cn(
                          "px-4 py-1.5 rounded-lg text-sm font-bold transition-all",
                          scheduleTab === 'calendar' ? "bg-[var(--color-bg-surface)] text-[var(--color-brand)] shadow-sm" : "text-slate-500 hover:text-slate-300"
                        )}
                      >
                        Tháng
                      </button>
                      <button 
                        onClick={() => setScheduleTab('compliance')}
                        className={cn(
                          "px-4 py-1.5 rounded-lg text-sm font-bold transition-all",
                          scheduleTab === 'compliance' ? "bg-[var(--color-bg-surface)] text-[var(--color-brand)] shadow-sm" : "text-slate-500 hover:text-slate-300"
                        )}
                      >
                        Tuân thủ
                      </button>
                    </div>
                    <button className="p-2 border border-[var(--color-border)] rounded-lg hover:bg-slate-800 transition-all">
                      <Filter size={18} />
                    </button>
                  </div>
                </div>

                {/* Tab Content */}
                <AnimatePresence mode="wait">
                  {scheduleTab === 'grid' && (
                    <motion.div 
                      key="grid"
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: 10 }}
                      className="overflow-x-auto pb-4"
                    >
                      <div className="grid grid-cols-7 min-w-[1000px] gap-4">
                        {DAYS.map((day, idx) => (
                          <div key={day} className={cn(
                            "flex flex-col gap-4",
                            idx === TODAY_INDEX && "relative border-x border-[var(--color-brand)]/20 px-2 bg-[var(--color-brand)]/5 rounded-xl pt-2"
                          )}>
                            <div className="flex flex-col items-center mb-2">
                              <span className={cn(
                                "text-xs font-bold uppercase tracking-widest",
                                idx === TODAY_INDEX ? "text-[var(--color-brand)]" : "text-slate-500"
                              )}>
                                {day}
                              </span>
                              <span className={cn(
                                "text-lg font-bold",
                                idx === TODAY_INDEX && "w-8 h-8 rounded-full bg-[var(--color-brand)] flex items-center justify-center text-white mt-1"
                              )}>
                                {12 + idx}
                              </span>
                            </div>

                            <div className="space-y-3">
                              {WEEKLY_SHIFTS.filter(s => s.day === idx).map(shift => (
                                <motion.div 
                                  key={shift.id}
                                  whileHover={{ y: -2 }}
                                  onClick={() => setEditingShift(shift)}
                                  className={cn(
                                    "p-3 rounded-xl border transition-all cursor-pointer group",
                                    shift.status === 'active' ? "bg-[var(--color-bg-surface)] border-[var(--color-brand)] shadow-md shadow-blue-500/10 ring-1 ring-blue-500/20" :
                                    shift.status === 'completed' ? "bg-slate-50 dark:bg-slate-900 border-[var(--color-border)] opacity-60 grayscale-[0.5]" :
                                    "bg-[var(--color-bg-surface)] border-[var(--color-border)] hover:border-slate-500"
                                  )}
                                >
                                  <div className="flex items-center gap-2 mb-2">
                                    <div className="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center text-[10px] font-bold">
                                      {shift.name.split(' ').pop()?.substring(0, 2).toUpperCase()}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                      <p className="text-[11px] font-bold truncate group-hover:text-[var(--color-brand)] transition-colors">{shift.name}</p>
                                      <p className="text-[9px] text-slate-500 font-medium truncate">{shift.role}</p>
                                    </div>
                                    {shift.status === 'active' && <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />}
                                  </div>
                                  <div className="flex items-center justify-between text-[10px] font-mono font-medium text-[var(--color-text-secondary)]">
                                    <span>{shift.time}</span>
                                    <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-[9px] font-sans uppercase font-bold">{shift.dept}</span>
                                  </div>
                                </motion.div>
                              ))}
                              {WEEKLY_SHIFTS.filter(s => s.day === idx).length === 0 && (
                                <div className="h-20 rounded-xl border border-dashed border-[var(--color-border)] flex items-center justify-center text-[10px] text-slate-500 font-medium italic">
                                  Trống
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </motion.div>
                  )}

                  {scheduleTab === 'calendar' && (
                    <motion.div 
                      key="calendar"
                      initial={{ opacity: 0, scale: 0.98 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.98 }}
                      className="bg-[var(--color-bg-surface)] rounded-2xl border border-[var(--color-border)] overflow-hidden shadow-sm pt-4"
                    >
                      <div className="px-6 flex items-center justify-between mb-6">
                        <div className="flex items-center gap-4">
                          <button
                            onClick={() => {
                              if (calMonth === 1) { setCalMonth(12); setCalYear(calYear - 1); }
                              else setCalMonth(calMonth - 1);
                            }}
                            className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-all"
                            aria-label="Tháng trước"
                          ><Sun size={20} className="rotate-90" /></button>
                          <h3 className="text-lg font-bold tabular-nums">Tháng {calMonth}, {calYear}</h3>
                          <button
                            onClick={() => {
                              if (calMonth === 12) { setCalMonth(1); setCalYear(calYear + 1); }
                              else setCalMonth(calMonth + 1);
                            }}
                            className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-all"
                            aria-label="Tháng sau"
                          ><Sun size={20} className="-rotate-90" /></button>
                        </div>
                        <button
                          onClick={() => {
                            const n = new Date();
                            setCalMonth(n.getMonth() + 1);
                            setCalYear(n.getFullYear());
                          }}
                          className="px-3 py-1.5 text-xs font-bold bg-[var(--color-brand-muted)] text-[var(--color-brand)] rounded-lg hover:brightness-110 transition-all"
                        >Hôm nay</button>
                      </div>

                      {(() => {
                        // Build calendar matrix: lưới 7×6 cells
                        const firstDay = new Date(calYear, calMonth - 1, 1);
                        const firstWeekday = (firstDay.getDay() + 6) % 7; // 0 = Mon
                        const daysInMonth = new Date(calYear, calMonth, 0).getDate();
                        const today = new Date();
                        const isCurrentMonth = today.getFullYear() === calYear && today.getMonth() + 1 === calMonth;
                        const slotsByDate: Record<string, any[]> = {};
                        for (const day of (scheduleCalendarQ.data?.days || [])) {
                          slotsByDate[day.date] = day.slots;
                        }
                        const cells: Array<{ day: number; date: string; inMonth: boolean }> = [];
                        // Padding trước
                        for (let i = 0; i < firstWeekday; i++) cells.push({ day: 0, date: '', inMonth: false });
                        for (let d = 1; d <= daysInMonth; d++) {
                          const date = `${calYear}-${String(calMonth).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
                          cells.push({ day: d, date, inMonth: true });
                        }
                        while (cells.length < 42) cells.push({ day: 0, date: '', inMonth: false });

                        return (
                          <div className="grid grid-cols-7 border-t border-[var(--color-border)]">
                            {DAYS.map(d => (
                              <div key={d} className="py-3 text-center text-xs font-bold uppercase tracking-widest text-slate-500 border-b border-[var(--color-border)]">{d}</div>
                            ))}
                            {scheduleCalendarQ.loading && (
                              <div className="col-span-7 py-16 text-center text-sm text-slate-500">Đang tải lịch…</div>
                            )}
                            {!scheduleCalendarQ.loading && cells.map((c, i) => {
                              const slots = c.date ? (slotsByDate[c.date] || []) : [];
                              const count = slots.length;
                              const isToday = c.inMonth && isCurrentMonth && c.day === today.getDate();
                              return (
                                <div key={i} className={cn(
                                  "h-32 border-r border-b border-[var(--color-border)] p-2 group hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-all",
                                  !c.inMonth && "opacity-40",
                                  isToday && "bg-blue-500/5 ring-1 ring-inset ring-blue-500/20"
                                )}>
                                  {c.inMonth && (
                                    <>
                                      <div className="flex justify-between items-start mb-2">
                                        <span className={cn(
                                          "text-sm font-bold",
                                          isToday ? "w-6 h-6 rounded-full bg-[var(--color-brand)] text-white flex items-center justify-center" : "text-slate-400"
                                        )}>{c.day}</span>
                                        {count > 0 && (
                                          <div className="flex gap-0.5">
                                            {[...Array(Math.min(count, 4))].map((_, j) => (
                                              <div key={j} className="w-1 h-1 rounded-full bg-blue-500" />
                                            ))}
                                          </div>
                                        )}
                                      </div>
                                      {count > 0 && (
                                        <div className="space-y-1 overflow-hidden">
                                          {slots.slice(0, 2).map((s) => (
                                            <div key={s.id} className="px-1 py-0.5 rounded text-[9px] bg-blue-500/10 text-blue-500 font-bold truncate">
                                              {(s as any).username || '—'} · {(s as any).start_time}
                                            </div>
                                          ))}
                                          {count > 2 && (
                                            <div className="px-1 text-[9px] text-slate-500 font-bold">+{count - 2} ca</div>
                                          )}
                                        </div>
                                      )}
                                    </>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        );
                      })()}
                    </motion.div>
                  )}

                  {scheduleTab === 'compliance' && (
                    <motion.div 
                      key="compliance"
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -10 }}
                      className="space-y-8"
                    >
                      {/* Sub-Stat Cards — tổng từ scheduleComplianceQ */}
                      {(() => {
                        const rows = scheduleComplianceQ.data || [];
                        const totals = rows.reduce(
                          (acc: any, r: any) => ({
                            total: acc.total + (r.total || 0),
                            on_time: acc.on_time + (r.on_time || 0),
                            late: acc.late + (r.late || 0),
                            missed: acc.missed + (r.missed || 0),
                          }),
                          { total: 0, on_time: 0, late: 0, missed: 0 },
                        );
                        const denom = totals.on_time + totals.late + totals.missed;
                        const onTimeRate = denom > 0 ? ((totals.on_time / denom) * 100).toFixed(1) + '%' : '—';
                        const subStats = [
                          { label: 'Tỷ lệ On-time', value: onTimeRate, icon: CheckCircle2, status: 'positive' },
                          { label: 'Ca vắng mặt (Missed)', value: `${totals.missed} ca`, icon: AlertCircle, status: 'negative' },
                          { label: 'Ca đi muộn (Late)', value: `${totals.late} ca`, icon: Clock, status: 'warning' },
                        ];
                        return (
                          <>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                        {subStats.map((stat) => (
                          <div key={stat.label} className="bg-[var(--color-bg-surface)] p-6 rounded-2xl border border-[var(--color-border)] shadow-sm">
                            <div className="flex items-center gap-4 mb-4">
                              <div className={cn(
                                "p-3 rounded-xl",
                                stat.status === 'positive' ? "bg-green-500/10 text-green-500" :
                                stat.status === 'negative' ? "bg-red-500/10 text-red-500" : "bg-amber-500/10 text-amber-500"
                              )}>
                                <stat.icon size={24} />
                              </div>
                              <span className="text-sm font-bold text-slate-500 uppercase tracking-widest">{stat.label}</span>
                            </div>
                            <p className="text-3xl font-bold font-mono">{stat.value}</p>
                          </div>
                        ))}
                      </div>

                      {/* Compliance Table */}
                      <div className="bg-[var(--color-bg-surface)] rounded-2xl border border-[var(--color-border)] overflow-hidden shadow-sm">
                        <div className="px-6 py-4 border-b border-[var(--color-border)] flex justify-between items-center">
                          <h3 className="font-bold">Chi tiết nhân sự</h3>
                          <button
                            onClick={() => handleExport('csv')}
                            disabled={exporting}
                            className="flex items-center gap-2 text-xs font-bold text-[var(--color-brand)] hover:underline disabled:opacity-50"
                          >
                            <Download size={14} /> {exporting ? 'Đang tải…' : 'Tải bảng CSV'}
                          </button>
                        </div>
                        <table className="w-full text-left text-sm border-collapse">
                          <thead>
                            <tr className="bg-slate-50 dark:bg-slate-900 border-b border-[var(--color-border)] text-slate-500">
                              <th className="px-6 py-4 font-bold uppercase tracking-wider text-[10px]">Nhân viên</th>
                              <th className="px-6 py-4 font-bold uppercase tracking-wider text-[10px]">Tổng ca</th>
                              <th className="px-6 py-4 font-bold uppercase tracking-wider text-[10px]">On-time</th>
                              <th className="px-6 py-4 font-bold uppercase tracking-wider text-[10px]">Late</th>
                              <th className="px-6 py-4 font-bold uppercase tracking-wider text-[10px]">Missed</th>
                              <th className="px-4 py-4 font-bold uppercase tracking-wider text-[10px]">Tỷ lệ</th>
                              <th className="px-6 py-4 font-bold uppercase tracking-wider text-[10px] text-right">Hành động</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-[var(--color-border)]">
                            {scheduleComplianceQ.loading && (
                              <tr><td colSpan={7} className="px-6 py-12 text-center text-sm text-slate-500">Đang tính toán độ tuân thủ…</td></tr>
                            )}
                            {!scheduleComplianceQ.loading && COMPLIANCE_DATA.length === 0 && (
                              <tr><td colSpan={7} className="px-6 py-12 text-center text-sm text-slate-500">Chưa có dữ liệu trong kỳ này.</td></tr>
                            )}
                            {COMPLIANCE_DATA.map((row, idx) => (
                              <tr key={`${row.name}-${idx}`} className="hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-all group">
                                <td className="px-6 py-4 font-bold group-hover:text-[var(--color-brand)]">{row.name}</td>
                                <td className="px-6 py-4 font-mono">{row.total}</td>
                                <td className="px-6 py-4 text-green-500 font-bold">{row.onTime}</td>
                                <td className="px-6 py-4 text-amber-500 font-medium">{row.late}</td>
                                <td className="px-6 py-4 text-red-500 font-medium">{row.missed}</td>
                                <td className="px-4 py-4">
                                  <div className="flex items-center gap-2">
                                    <div className={cn(
                                       "px-2 py-0.5 rounded text-[10px] font-bold tabular-nums",
                                       row.total === 0 ? "bg-slate-500/10 text-slate-500" :
                                       row.rate > 90 ? "bg-green-500/10 text-green-500" :
                                       row.rate > 75 ? "bg-amber-500/10 text-amber-500" : "bg-red-500/10 text-red-500"
                                    )}>
                                      {row.total === 0 ? 'N/A' : `${row.rate.toFixed(1)}%`}
                                    </div>
                                    <div className="w-16 h-1 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                                      <div
                                        className={cn(
                                          "h-full",
                                          row.rate > 90 ? "bg-green-500" : row.rate > 75 ? "bg-amber-500" : "bg-red-500"
                                        )}
                                        style={{ width: `${row.rate}%` }}
                                      />
                                    </div>
                                  </div>
                                </td>
                                <td className="px-6 py-4 text-right">
                                  <button
                                    onClick={() => {
                                      // tìm user_id trong scheduleComplianceQ.data
                                      const found = (scheduleComplianceQ.data || []).find((r: any) => r.username === row.name);
                                      if (found) setAttendanceDetail({ user_id: (found as any).user_id, username: row.name });
                                    }}
                                    className="text-xs font-bold text-slate-400 hover:text-[var(--color-brand)] transition-colors underline underline-offset-4"
                                  >Tra cứu log</button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                          </>
                        );
                      })()}
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* Edit Shift Modal Backdrop */}
                <AnimatePresence>
                  {editingShift && (
                    <motion.div 
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="fixed inset-0 bg-slate-950/60 backdrop-blur-sm z-[100] flex items-center justify-center p-4"
                      onClick={() => setEditingShift(null)}
                    >
                      <motion.div 
                        initial={{ scale: 0.95, opacity: 0, y: 20 }}
                        animate={{ scale: 1, opacity: 1, y: 0 }}
                        exit={{ scale: 0.95, opacity: 0, y: 20 }}
                        onClick={(e) => e.stopPropagation()}
                        className="bg-[var(--color-bg-surface)] border border-[var(--color-border)] w-full max-w-lg rounded-2xl shadow-2xl p-8 space-y-6"
                      >
                        <div className="flex justify-between items-start">
                          <div>
                            <h3 className="text-xl font-bold">Chỉnh sửa ca trực</h3>
                            <p className="text-sm text-slate-500">Mã ca: #SH-{editingShift.id}</p>
                          </div>
                          <button onClick={() => setEditingShift(null)} className="p-2 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-full transition-all">
                            <ShieldAlert size={20} className="rotate-45" />
                          </button>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                          <div className="space-y-1.5">
                            <label className="text-xs font-bold uppercase text-slate-500 tracking-wider">Nhân viên</label>
                            <input
                              type="text"
                              value={editingShift.name}
                              readOnly
                              className="w-full px-4 py-2 rounded-xl bg-slate-100 dark:bg-slate-900 border border-[var(--color-border)] text-sm opacity-70 cursor-not-allowed"
                            />
                          </div>
                          <div className="space-y-1.5">
                            <label className="text-xs font-bold uppercase text-slate-500 tracking-wider">Vai trò</label>
                            <input
                              type="text"
                              value={shiftForm.role_name}
                              onChange={(e) => setShiftForm({ ...shiftForm, role_name: e.target.value })}
                              className="w-full px-4 py-2 rounded-xl bg-slate-100 dark:bg-slate-900 border border-[var(--color-border)] text-sm focus:ring-2 focus:ring-[var(--color-brand)] outline-none"
                              placeholder="Bác sĩ trực chính"
                            />
                          </div>
                          <div className="space-y-1.5">
                            <label className="text-xs font-bold uppercase text-slate-500 tracking-wider">Thứ trong tuần</label>
                            <select
                              value={shiftForm.weekday}
                              onChange={(e) => setShiftForm({ ...shiftForm, weekday: Number(e.target.value) })}
                              className="w-full px-4 py-2 rounded-xl bg-slate-100 dark:bg-slate-900 border border-[var(--color-border)] text-sm outline-none focus:ring-2 focus:ring-[var(--color-brand)]"
                            >
                              {DAYS.map((d, i) => <option key={i} value={i}>{d}</option>)}
                            </select>
                          </div>
                          <div className="space-y-1.5">
                            <label className="text-xs font-bold uppercase text-slate-500 tracking-wider">Khoa / phòng</label>
                            <input
                              type="text"
                              value={editingShift.dept}
                              readOnly
                              className="w-full px-4 py-2 rounded-xl bg-slate-100 dark:bg-slate-900 border border-[var(--color-border)] text-sm opacity-70 cursor-not-allowed"
                            />
                          </div>
                          <div className="space-y-1.5">
                            <label className="text-xs font-bold uppercase text-slate-500 tracking-wider">Bắt đầu</label>
                            <input
                              type="time"
                              value={shiftForm.start_time}
                              onChange={(e) => setShiftForm({ ...shiftForm, start_time: e.target.value })}
                              className="w-full px-4 py-2 rounded-xl bg-slate-100 dark:bg-slate-900 border border-[var(--color-border)] text-sm focus:ring-2 focus:ring-[var(--color-brand)] outline-none font-mono"
                            />
                          </div>
                          <div className="space-y-1.5">
                            <label className="text-xs font-bold uppercase text-slate-500 tracking-wider">Kết thúc</label>
                            <input
                              type="time"
                              value={shiftForm.end_time}
                              onChange={(e) => setShiftForm({ ...shiftForm, end_time: e.target.value })}
                              className="w-full px-4 py-2 rounded-xl bg-slate-100 dark:bg-slate-900 border border-[var(--color-border)] text-sm focus:ring-2 focus:ring-[var(--color-brand)] outline-none font-mono"
                            />
                          </div>
                        </div>

                        <div className="space-y-1.5">
                          <label className="text-xs font-bold uppercase text-slate-500 tracking-wider">Ghi chú audit</label>
                          <textarea
                            value={shiftForm.note}
                            onChange={(e) => setShiftForm({ ...shiftForm, note: e.target.value })}
                            className="w-full px-4 py-2 rounded-xl bg-slate-100 dark:bg-slate-900 border border-[var(--color-border)] text-sm outline-none h-20 resize-none focus:ring-2 focus:ring-[var(--color-brand)]"
                            placeholder="Lý do thay đổi ca trực..."
                          />
                        </div>

                        <div className="flex gap-3 pt-4">
                          <button
                            onClick={async () => {
                              if (!guildId || !editingShift?.id) { setEditingShift(null); return; }
                              if (!window.confirm(`Xoá ca trực #${editingShift.id} của ${editingShift.name}?`)) return;
                              setShiftSaving(true);
                              try {
                                await api.scheduleDelete(guildId, editingShift.id);
                                scheduleGridQ.refetch();
                                setEditingShift(null);
                              } catch (err: any) {
                                alert('Lỗi xoá: ' + (err?.detail || 'không xác định'));
                              } finally {
                                setShiftSaving(false);
                              }
                            }}
                            disabled={shiftSaving}
                            className="px-4 py-3 rounded-xl bg-red-500/10 text-red-500 font-bold text-sm hover:bg-red-500 hover:text-white transition-all border border-red-500/20 disabled:opacity-50"
                          >Xoá ca</button>
                          <button
                            onClick={() => setEditingShift(null)}
                            disabled={shiftSaving}
                            className="flex-1 py-3 rounded-xl bg-slate-100 dark:bg-slate-800 font-bold text-sm hover:brightness-110 transition-all disabled:opacity-50"
                          >Hủy</button>
                          <button
                            onClick={async () => {
                              if (!guildId || !editingShift?.id) { setEditingShift(null); return; }
                              if (!shiftForm.start_time || !shiftForm.end_time) {
                                alert('Vui lòng nhập đủ giờ bắt đầu và kết thúc.');
                                return;
                              }
                              if (shiftForm.start_time === shiftForm.end_time) {
                                alert('Giờ bắt đầu và kết thúc không được trùng.');
                                return;
                              }
                              setShiftSaving(true);
                              try {
                                await api.scheduleUpdate(guildId, editingShift.id, {
                                  weekday: shiftForm.weekday,
                                  start_time: shiftForm.start_time,
                                  end_time: shiftForm.end_time,
                                  role_name: shiftForm.role_name || undefined,
                                });
                                scheduleGridQ.refetch();
                                setEditingShift(null);
                              } catch (err: any) {
                                alert('Lỗi lưu: ' + (err?.detail || 'không xác định'));
                              } finally {
                                setShiftSaving(false);
                              }
                            }}
                            disabled={shiftSaving}
                            className="flex-1 py-3 rounded-xl bg-[var(--color-brand)] text-white font-bold text-sm hover:shadow-lg hover:shadow-blue-500/20 transition-all disabled:opacity-50"
                          >{shiftSaving ? 'Đang lưu…' : 'Lưu thay đổi'}</button>
                        </div>
                      </motion.div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            )}

            {activeTab === 'leave' && (
              <motion.div 
                key="leave"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-6"
              >
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div>
                    <h2 className="text-2xl font-bold tracking-tight">Quản lý đơn nghỉ phép</h2>
                    <p className="text-sm text-[var(--color-text-secondary)]">Xử lý các yêu cầu nghỉ phép và vắng mặt</p>
                  </div>
                  <div className="flex bg-slate-100 dark:bg-slate-800 p-1 rounded-xl border border-[var(--color-border)]">
                    {['pending', 'approved', 'rejected', 'resign'].map((tab) => (
                      <button 
                        key={tab}
                        onClick={() => setLeaveTab(tab as any)}
                        className={cn(
                          "px-4 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider transition-all",
                          leaveTab === tab ? "bg-[var(--color-bg-surface)] text-[var(--color-brand)] shadow-sm" : "text-slate-500 hover:text-slate-300"
                        )}
                      >
                        {tab === 'pending' ? 'Chờ duyệt' : tab === 'approved' ? 'Đã duyệt' : tab === 'rejected' ? 'Từ chối' : 'Thôi việc'}
                      </button>
                    ))}
                  </div>
                </div>

                {leaveQ.loading && (
                  <div className="text-center py-12 text-sm text-slate-500">Đang tải đơn nghỉ phép…</div>
                )}
                {!leaveQ.loading && leaveQ.data && leaveQ.data.length === 0 && (
                  <div className="text-center py-12 text-sm text-slate-500">
                    Không có đơn nào trong mục "{leaveTab === 'pending' ? 'Chờ duyệt' : leaveTab === 'approved' ? 'Đã duyệt' : leaveTab === 'rejected' ? 'Từ chối' : 'Thôi việc'}".
                  </div>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  {(leaveQ.data || []).map((lv) => ({
                    id: lv.id,
                    name: lv.username,
                    type: lv.type_label,
                    time: `${lv.start_date.slice(5)} - ${lv.end_date.slice(5)}`,
                    reason: lv.reason,
                    status: lv.status.toLowerCase(),
                    _raw: lv,
                  })).map((leave) => (
                    <motion.div 
                      key={leave.id}
                      whileHover={{ y: -4 }}
                      className="bg-[var(--color-bg-surface)] rounded-2xl border border-[var(--color-border)] p-5 shadow-sm hover:shadow-md transition-all space-y-4"
                    >
                      <div className="flex justify-between items-start">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center font-bold text-slate-400">
                             {leave.name.split(' ').pop()?.substring(0, 1)}
                          </div>
                          <div>
                            <p className="text-sm font-bold">{leave.name}</p>
                            <p className="text-[10px] font-bold text-amber-500 uppercase tracking-tighter bg-amber-500/10 px-1.5 py-0.5 rounded w-fit">{leave.type}</p>
                          </div>
                        </div>
                        <span className={cn(
                          "px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider",
                          leave.status === 'pending' ? "bg-amber-500/10 text-amber-500" :
                          leave.status === 'approved' ? "bg-green-500/10 text-green-500" :
                          "bg-red-500/10 text-red-500"
                        )}>
                          {leave.status === 'pending' ? 'Chờ duyệt' : leave.status === 'approved' ? 'Đã duyệt' : 'Từ chối'}
                        </span>
                      </div>

                      <div className="space-y-2 py-2">
                        <div className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
                          <Calendar size={14} />
                          <span className="font-medium">{leave.time}</span>
                        </div>
                        <p className="text-sm text-[var(--color-text-secondary)] line-clamp-2">“{leave.reason}”</p>
                      </div>

                      <div className="flex gap-2 pt-2">
                        {leave.status === 'pending' ? (
                          <>
                            <button
                              onClick={async () => {
                                if (!guildId) return;
                                const note = window.prompt('Lý do từ chối (tuỳ chọn):') || '';
                                try {
                                  await api.leaveDecision(guildId, leave.id, 'REJECTED', note);
                                  leaveQ.refetch();
                                } catch (err: any) {
                                  alert('Lỗi: ' + formatError(err));
                                }
                              }}
                              className="flex-1 py-2 rounded-lg bg-red-500/10 text-red-500 text-xs font-bold hover:bg-red-500 hover:text-white transition-all border border-red-500/20"
                            >Từ chối</button>
                            <button
                              onClick={async () => {
                                if (!guildId) return;
                                if (!window.confirm(`Duyệt đơn của ${leave.name}?`)) return;
                                try {
                                  await api.leaveDecision(guildId, leave.id, 'APPROVED');
                                  leaveQ.refetch();
                                } catch (err: any) {
                                  alert('Lỗi: ' + formatError(err));
                                }
                              }}
                              className="flex-1 py-2 rounded-lg bg-green-500/10 text-green-500 text-xs font-bold hover:bg-green-500 hover:text-white transition-all border border-green-500/20"
                            >Duyệt</button>
                          </>
                        ) : (
                          <button
                            onClick={async () => {
                              if (!guildId) return;
                              const reason = window.prompt('Lý do hoàn tác quyết định:');
                              if (!reason) return;
                              try {
                                await api.leaveRevert(guildId, leave.id, reason);
                                leaveQ.refetch();
                              } catch (err: any) {
                                alert('Lỗi: ' + formatError(err));
                              }
                            }}
                            className="flex-1 py-2 rounded-lg bg-slate-100 dark:bg-slate-800 text-xs font-bold hover:bg-slate-200 dark:hover:bg-slate-700 transition-all"
                          >Hoàn tác quyết định</button>
                        )}
                      </div>
                    </motion.div>
                  ))}
                </div>
              </motion.div>
            )}

            {activeTab === 'attendance' && (
              <motion.div 
                key="attendance"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-6"
              >
                <div className="flex justify-between items-center">
                  <div>
                    <h2 className="text-2xl font-bold tracking-tight">Thống kê chấm công</h2>
                    <p className="text-sm text-[var(--color-text-secondary)]">Theo dõi chuyên cần và sự tuân thủ ca trực</p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleExport('csv')}
                      disabled={exporting}
                      className="px-4 py-2 bg-slate-100 dark:bg-slate-800 rounded-lg text-sm font-bold border border-[var(--color-border)] hover:brightness-110 transition-all disabled:opacity-50"
                    >Xuất CSV</button>
                    <button
                      onClick={() => handleExport('excel')}
                      disabled={exporting}
                      className="px-4 py-2 bg-[var(--color-brand)] text-white rounded-lg text-sm font-bold hover:brightness-110 transition-all disabled:opacity-50"
                    >{exporting ? 'Đang xuất…' : 'Xuất Excel'}</button>
                  </div>
                </div>

                {/* View mode toggle */}
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-500">Hiển thị:</span>
                  <div className="flex bg-slate-100 dark:bg-slate-800 p-1 rounded-lg border border-[var(--color-border)]">
                    {([
                      { k: 'auto',       l: 'Tự động',     tip: 'User có lịch → Tuân thủ; còn lại → Giờ trực' },
                      { k: 'hours',      l: 'Giờ trực',    tip: 'Tổng giờ + số ca + TB/ca + lần cuối log' },
                      { k: 'compliance', l: 'Tuân thủ ca', tip: 'Tỷ lệ đúng giờ / trễ / vắng theo lịch' },
                    ] as const).map((opt) => (
                      <button
                        key={opt.k}
                        onClick={() => setAttendanceViewMode(opt.k)}
                        title={opt.tip}
                        className={cn(
                          "px-3 py-1.5 rounded-md text-xs font-bold transition-all",
                          attendanceViewMode === opt.k
                            ? "bg-[var(--color-bg-surface)] text-[var(--color-brand)] shadow-sm"
                            : "text-slate-500 hover:text-slate-300"
                        )}
                      >{opt.l}</button>
                    ))}
                  </div>
                  <span className="text-xs text-slate-500">
                    {attendanceViewMode === 'auto' && '(User có lịch trực sẽ hiện tuân thủ, còn lại hiện giờ thường)'}
                    {attendanceViewMode === 'hours' && '(Tất cả user hiện theo giờ trực thực tế)'}
                    {attendanceViewMode === 'compliance' && '(Tất cả user hiện theo tuân thủ ca, kể cả chưa setup lịch)'}
                  </span>
                </div>

                {attendanceQ.loading && (
                  <div className="text-center py-12 text-sm text-slate-500">Đang tải dữ liệu chấm công…</div>
                )}
                {!attendanceQ.loading && attendanceQ.data && attendanceQ.data.length === 0 && (
                  <div className="text-center py-12 text-sm text-slate-500">Chưa có dữ liệu chấm công trong kỳ này.</div>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                  {(attendanceQ.data || []).map((staff) => {
                    // Quyết định mode hiển thị cho card này
                    // auto: user có schedule → compliance; không có → hours
                    const showCompliance =
                      attendanceViewMode === 'compliance' ||
                      (attendanceViewMode === 'auto' && staff.has_schedule);
                    const rate = staff.compliance_rate;
                    const rateColor = rate !== null ? complianceColor(rate) : { text: 'text-slate-500', bg: 'bg-slate-500', dot: 'bg-slate-500' };
                    return (
                      <motion.div
                        key={staff.user_id}
                        whileHover={{ scale: 1.02 }}
                        className="bg-[var(--color-bg-surface)] p-5 rounded-2xl border border-[var(--color-border)] shadow-sm space-y-4"
                      >
                        <div className="flex items-center gap-3">
                          {staff.avatar_url ? (
                            <img src={staff.avatar_url} alt="" className="w-10 h-10 rounded-full object-cover" />
                          ) : (
                            <div className="w-10 h-10 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center font-bold text-slate-500">
                              {avatarText(staff.username)}
                            </div>
                          )}
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-bold truncate">{staff.username}</p>
                            <p className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">
                              {staff.has_schedule ? '✓ Đã đăng ký lịch' : 'Chưa có lịch trực'}
                            </p>
                          </div>
                        </div>

                        {showCompliance ? (
                          /* ─────────── COMPLIANCE VIEW ─────────── */
                          staff.has_schedule || attendanceViewMode === 'compliance' ? (
                            <div className="space-y-3">
                              <div className="flex justify-between items-end">
                                <span className="text-xs text-slate-500 font-medium">Độ tuân thủ</span>
                                <span className={cn("text-sm font-bold font-mono", rateColor.text)}>
                                  {rate !== null ? `${rate.toFixed(1)}%` : 'N/A'}
                                </span>
                              </div>
                              <div className="w-full h-1.5 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                                <div className={cn("h-full", rateColor.bg)} style={{ width: `${rate ?? 0}%` }} />
                              </div>
                              <div className="grid grid-cols-3 gap-2 py-1">
                                <div className="text-center">
                                  <p className="text-[10px] text-slate-500 uppercase font-bold">Đúng giờ</p>
                                  <p className="text-sm font-bold font-mono text-green-500 tabular-nums">{staff.on_time}</p>
                                </div>
                                <div className="text-center border-x border-[var(--color-border)]">
                                  <p className="text-[10px] text-slate-500 uppercase font-bold">Trễ</p>
                                  <p className="text-sm font-bold font-mono text-amber-500 tabular-nums">{staff.late}</p>
                                </div>
                                <div className="text-center">
                                  <p className="text-[10px] text-slate-500 uppercase font-bold">Vắng</p>
                                  <p className="text-sm font-bold font-mono text-red-500 tabular-nums">{staff.missed}</p>
                                </div>
                              </div>
                              <div className="text-center pt-1 border-t border-[var(--color-border)]">
                                <p className="text-[10px] text-slate-500 uppercase font-bold tracking-wider">
                                  Tổng <span className="text-slate-300 font-mono tabular-nums">{staff.total_scheduled}</span> ca theo lịch
                                </p>
                              </div>
                            </div>
                          ) : null
                        ) : (
                          /* ─────────── HOURS VIEW (mặc định cho user không có schedule) ─────────── */
                          <div className="space-y-3">
                            <div className="text-center py-2 bg-slate-50 dark:bg-slate-900/40 rounded-lg">
                              <p className="text-[10px] text-slate-500 uppercase font-bold tracking-wider">Tổng giờ trực</p>
                              <p className="text-2xl font-bold font-mono tabular-nums text-[var(--color-brand)] mt-1">
                                {staff.total_minutes > 0 ? minutesToHHMM(staff.total_minutes) : '0 phút'}
                              </p>
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                              <div className="text-center py-2 rounded-lg bg-slate-50 dark:bg-slate-900/40">
                                <p className="text-[10px] text-slate-500 uppercase font-bold">Số ca</p>
                                <p className="text-sm font-bold font-mono tabular-nums mt-0.5">{staff.session_count}</p>
                              </div>
                              <div className="text-center py-2 rounded-lg bg-slate-50 dark:bg-slate-900/40">
                                <p className="text-[10px] text-slate-500 uppercase font-bold">TB/ca</p>
                                <p className="text-sm font-bold font-mono tabular-nums mt-0.5">
                                  {staff.session_count > 0 ? minutesToHHMM(staff.avg_minutes) : '—'}
                                </p>
                              </div>
                            </div>
                            <div className="text-center pt-1 border-t border-[var(--color-border)]">
                              <p className="text-[10px] text-slate-500 uppercase font-bold tracking-wider">
                                {staff.last_log_at ? (
                                  <>Lần cuối: <span className="text-slate-300 font-mono tabular-nums">
                                    {staff.last_log_age_days === 0 ? 'Hôm nay'
                                      : staff.last_log_age_days === 1 ? 'Hôm qua'
                                      : staff.last_log_age_days !== null ? `${staff.last_log_age_days} ngày trước`
                                      : '—'}
                                  </span></>
                                ) : (
                                  <span className="text-slate-500">Chưa từng chấm công</span>
                                )}
                              </p>
                            </div>
                          </div>
                        )}

                        <button
                          onClick={() => setAttendanceDetail({ user_id: staff.user_id, username: staff.username })}
                          className="w-full py-2 rounded-xl bg-slate-100 dark:bg-slate-800 text-xs font-bold hover:bg-[var(--color-brand-muted)] hover:text-[var(--color-brand)] transition-all"
                        >Chi tiết cá nhân</button>
                      </motion.div>
                    );
                  })}
                </div>
              </motion.div>
            )}

            {activeTab === 'logs' && (
              <motion.div 
                key="logs"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-6"
              >
                <div className="flex justify-between items-center">
                  <div>
                    <h2 className="text-2xl font-bold tracking-tight">Nhật ký chấm công (OCR)</h2>
                    <p className="text-sm text-[var(--color-text-secondary)]">Dữ liệu thô từ hệ thống nhận diện hình ảnh</p>
                  </div>
                  <div className="flex gap-3">
                    <div className="relative">
                      <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                      <input
                        type="text"
                        placeholder="Tìm theo ID, Tên..."
                        value={logsSearch}
                        onChange={(e) => { setLogsSearch(e.target.value); setLogsPage(1); }}
                        className="pl-10 pr-4 py-2 bg-[var(--color-bg-surface)] border border-[var(--color-border)] rounded-lg text-sm"
                      />
                    </div>
                  </div>
                </div>

                <div className="bg-[var(--color-bg-surface)] rounded-2xl border border-[var(--color-border)] overflow-hidden shadow-sm">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="bg-slate-50 dark:bg-slate-900 border-b border-[var(--color-border)]">
                        <th className="px-6 py-4 font-bold text-[10px] uppercase tracking-wider text-slate-500">ID Log</th>
                        <th className="px-6 py-4 font-bold text-[10px] uppercase tracking-wider text-slate-500">Người thực hiện</th>
                        <th className="px-6 py-4 font-bold text-[10px] uppercase tracking-wider text-slate-500">Thời gian ghi nhận</th>
                        <th className="px-6 py-4 font-bold text-[10px] uppercase tracking-wider text-slate-500">Loại Check</th>
                        <th className="px-6 py-4 font-bold text-[10px] uppercase tracking-wider text-slate-500">Ảnh OCR</th>
                        <th className="px-6 py-4 font-bold text-[10px] uppercase tracking-wider text-slate-500">Trạng thái</th>
                        <th className="px-6 py-4 font-bold text-[10px] uppercase tracking-wider text-slate-500 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--color-border)]">
                      {logsQ.loading && (
                        <tr><td colSpan={7} className="px-6 py-12 text-center text-sm text-slate-500">Đang tải log…</td></tr>
                      )}
                      {!logsQ.loading && logsQ.data && logsQ.data.items.length === 0 && (
                        <tr><td colSpan={7} className="px-6 py-12 text-center text-sm text-slate-500">Chưa có bản ghi nào.</td></tr>
                      )}
                      {(logsQ.data?.items || []).map((log) => (
                        <tr key={log.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-all">
                          <td className="px-6 py-4 font-mono text-slate-400">#LOG-{String(log.id).padStart(4, '0')}</td>
                          <td className="px-6 py-4 font-bold">{log.username}</td>
                          <td className="px-6 py-4 text-slate-500 font-mono text-xs">{formatDateTime(log.started_at)}</td>
                          <td className="px-6 py-4"><span className="px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-500 text-[10px] font-bold">{log.source}</span></td>
                          <td className="px-6 py-4">
                            {log.image_url ? (
                              <a href={log.image_url} target="_blank" rel="noreferrer" className="w-8 h-8 rounded bg-slate-200 dark:bg-slate-800 flex items-center justify-center text-slate-400 hover:text-[var(--color-brand)] transition-colors">
                                <FileText size={14} />
                              </a>
                            ) : (
                              <span className="text-slate-600 text-xs">—</span>
                            )}
                          </td>
                          <td className="px-6 py-4">
                            <div className={cn("flex items-center gap-1.5 font-bold text-[10px]", log.is_valid ? "text-green-500" : "text-red-500")}>
                              <CheckCircle2 size={12} /> {log.is_valid ? 'Hợp lệ' : 'Không hợp lệ'}
                            </div>
                          </td>
                          <td className="px-6 py-4 text-right">
                            <button
                              onClick={async () => {
                                if (!guildId) return;
                                if (!window.confirm(`Xoá log #${log.id}?`)) return;
                                try {
                                  await api.deleteLog(guildId, log.id);
                                  logsQ.refetch();
                                } catch (err: any) {
                                  alert('Lỗi: ' + formatError(err));
                                }
                              }}
                              className="p-1.5 hover:bg-red-500/10 hover:text-red-500 rounded-lg transition-all"
                              aria-label="Xoá log"
                            >
                              <LogOut size={16} className="rotate-180" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="px-6 py-4 bg-slate-50 dark:bg-slate-900 flex justify-between items-center text-xs text-slate-500 font-bold uppercase">
                    <span>
                      Hiển thị {logsQ.data?.items.length || 0} / {logsQ.data?.total.toLocaleString('vi-VN') || 0} bản ghi
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setLogsPage((p) => Math.max(1, p - 1))}
                        disabled={logsPage <= 1}
                        className="px-3 py-1 border border-[var(--color-border)] rounded hover:bg-white dark:hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed"
                      >Trước</button>
                      <span className="px-3 py-1">{logsPage}</span>
                      <button
                        onClick={() => setLogsPage((p) => p + 1)}
                        disabled={!logsQ.data || logsQ.data.items.length < logsQ.data.page_size}
                        className="px-3 py-1 border border-[var(--color-border)] rounded hover:bg-white dark:hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed"
                      >Tiếp</button>
                    </div>
                  </div>
                </div>
              </motion.div>
            )}

            {activeTab === 'audit' && (
              <motion.div 
                key="audit"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-6"
              >
                <div className="flex justify-between items-center">
                  <div>
                    <h2 className="text-2xl font-bold tracking-tight">Nhật ký hệ thống (Audit)</h2>
                    <p className="text-sm text-[var(--color-text-secondary)]">Truy vết mọi hành động quản trị và thay đổi dữ liệu</p>
                  </div>
                </div>

                <div className="bg-[var(--color-bg-surface)] rounded-2xl border border-[var(--color-border)] shadow-sm overflow-hidden">
                  <div className="p-4 border-b border-[var(--color-border)] bg-slate-50 dark:bg-slate-900 flex gap-4">
                     <select className="px-3 py-1.5 rounded-lg bg-white dark:bg-slate-800 border border-[var(--color-border)] text-xs font-bold focus:ring-2 focus:ring-[var(--color-brand)] outline-none">
                       <option>Tất cả hành động</option>
                       <option>Sửa lịch trực</option>
                       <option>Phê duyệt nghỉ phép</option>
                       <option>Thay đổi quyền</option>
                     </select>
                     <input type="date" className="px-3 py-1.5 rounded-lg bg-white dark:bg-slate-800 border border-[var(--color-border)] text-xs font-bold outline-none" />
                  </div>
                  
                  <div className="divide-y divide-[var(--color-border)]">
                    {auditQ.loading && (
                      <div className="p-12 text-center text-sm text-slate-500">Đang tải audit log…</div>
                    )}
                    {!auditQ.loading && auditQ.data && auditQ.data.items.length === 0 && (
                      <div className="p-12 text-center text-sm text-slate-500">Chưa có hành động nào được ghi lại.</div>
                    )}
                    {(auditQ.data?.items || []).map((row) => {
                      // Phân loại type theo prefix action
                      const type =
                        row.action.startsWith('DELETE') || row.action.startsWith('REJECT') || row.action.includes('FAILURE')
                          ? 'danger'
                          : row.action.startsWith('APPROVE') || row.action.startsWith('CREATE')
                          ? 'success'
                          : row.action.startsWith('UPDATE') || row.action.startsWith('CHANGE')
                          ? 'warning'
                          : 'info';
                      const detailStr = typeof row.detail === 'object' && row.detail !== null
                        ? Object.entries(row.detail)
                            .filter(([_, v]) => v !== null && v !== undefined)
                            .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
                            .join(' • ')
                        : String(row.detail || '');
                      return (
                        <div key={row.id} className="p-4 flex items-start gap-4 hover:bg-slate-50 dark:hover:bg-slate-800/10 transition-all group">
                          <div className={cn(
                            "w-10 h-10 rounded-xl flex items-center justify-center shrink-0",
                            type === 'warning' ? "bg-amber-500/10 text-amber-500" :
                            type === 'success' ? "bg-green-500/10 text-green-500" :
                            type === 'danger' ? "bg-red-500/10 text-red-500" : "bg-blue-500/10 text-blue-500"
                          )}>
                            <ShieldAlert size={20} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1 flex-wrap">
                              <span className="text-xs font-bold px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono">{row.action}</span>
                              <span className="text-[10px] text-slate-500 font-bold uppercase font-mono">{formatDateTime(row.created_at)}</span>
                            </div>
                            <p className="text-sm font-medium">
                              <span className="font-bold text-[var(--color-brand)]">{row.username}</span>
                              {detailStr && <> — <span className="italic text-[var(--color-text-secondary)]">{detailStr}</span></>}
                            </p>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="p-6 bg-slate-50 dark:bg-slate-900 border-t border-[var(--color-border)] flex justify-between items-center text-xs">
                    <span className="text-slate-500">
                      Hiển thị {auditQ.data?.items.length || 0} / {auditQ.data?.total.toLocaleString('vi-VN') || 0}
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setAuditPage((p) => Math.max(1, p - 1))}
                        disabled={auditPage <= 1}
                        className="px-3 py-1 border border-[var(--color-border)] rounded font-bold hover:bg-white dark:hover:bg-slate-800 disabled:opacity-30"
                      >Trước</button>
                      <span className="px-3 py-1 font-bold">{auditPage}</span>
                      <button
                        onClick={() => setAuditPage((p) => p + 1)}
                        disabled={!auditQ.data || auditQ.data.items.length < 50}
                        className="px-3 py-1 border border-[var(--color-border)] rounded font-bold hover:bg-white dark:hover:bg-slate-800 disabled:opacity-30"
                      >Tiếp</button>
                    </div>
                  </div>
                </div>
              </motion.div>
            )}

            {activeTab !== 'overview' && activeTab !== 'schedule' && activeTab !== 'ranking' && activeTab !== 'leave' && activeTab !== 'attendance' && activeTab !== 'logs' && activeTab !== 'audit' && (
              <motion.div 
                key="coming-soon"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="h-[60vh] flex flex-col items-center justify-center text-center space-y-4"
              >
                <div className="w-16 h-16 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-400 mb-4">
                  <Settings size={32} />
                </div>
                <h2 className="text-2xl font-bold">Màn hình {navItems.find(i => i.id === activeTab)?.label} đang được hoàn thiện</h2>
                <p className="text-slate-500 max-w-sm">Chúng tôi đang thiết kế dữ liệu mẫu thực tế cho phần này để tránh các placeholder sáo rỗng.</p>
                <button 
                  onClick={() => setActiveTab('overview')}
                  className="px-6 py-2 bg-[var(--color-brand)] text-white rounded-lg font-bold hover:brightness-110 transition-all"
                >
                  Quay lại Tổng quan
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>

      {/* Attendance Detail Modal */}
      <AnimatePresence>
        {attendanceDetail && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-slate-950/60 backdrop-blur-sm z-[100] flex items-center justify-center p-4"
            onClick={() => setAttendanceDetail(null)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.95, opacity: 0, y: 20 }}
              onClick={(e) => e.stopPropagation()}
              role="dialog"
              aria-modal="true"
              aria-labelledby="att-detail-title"
              className="bg-[var(--color-bg-surface)] border border-[var(--color-border)] w-full max-w-3xl rounded-2xl shadow-2xl flex flex-col max-h-[92vh]"
            >
              {/* HEADER */}
              <div className="px-6 py-5 border-b border-[var(--color-border)] flex justify-between items-start">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center font-bold text-slate-500 text-base shrink-0">
                    {avatarText(attendanceDetail.username)}
                  </div>
                  <div className="min-w-0">
                    <h3 id="att-detail-title" className="text-xl font-bold truncate">{attendanceDetail.username}</h3>
                    <p className="text-xs text-slate-500 font-mono uppercase tracking-wider">Chi tiết chấm công theo ngày</p>
                  </div>
                </div>
                <button
                  onClick={() => setAttendanceDetail(null)}
                  aria-label="Đóng"
                  className="p-2 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-full transition-all shrink-0"
                >
                  <ShieldAlert size={20} className="rotate-45" />
                </button>
              </div>

              {/* TOOLBAR: date pickers + filter + summary */}
              <div className="px-6 py-3 border-b border-[var(--color-border)] bg-slate-50 dark:bg-slate-900/40 flex flex-wrap gap-3 items-center">
                <div className="flex items-center gap-2 text-xs">
                  <Calendar size={14} className="text-slate-500" />
                  <span className="font-bold uppercase text-slate-500">Từ</span>
                  <input
                    type="date"
                    value={(() => {
                      const v = attendanceCustomRange?.from || attendanceDailyRange.start;
                      // DD/MM/YYYY → YYYY-MM-DD cho input[type=date]
                      const [d, m, y] = v.split('/');
                      return y && m && d ? `${y}-${m}-${d}` : '';
                    })()}
                    onChange={(e) => {
                      if (!e.target.value) return;
                      const [y, m, d] = e.target.value.split('-');
                      const newFrom = `${d}/${m}/${y}`;
                      const currentTo = attendanceCustomRange?.to || attendanceDailyRange.end;
                      setAttendanceCustomRange({ from: newFrom, to: currentTo });
                    }}
                    className="px-2 py-1 rounded bg-[var(--color-bg-surface)] border border-[var(--color-border)] text-xs font-mono focus:outline-none focus:ring-2 focus:ring-[var(--color-brand)]"
                  />
                  <span className="font-bold uppercase text-slate-500">đến</span>
                  <input
                    type="date"
                    value={(() => {
                      const v = attendanceCustomRange?.to || attendanceDailyRange.end;
                      const [d, m, y] = v.split('/');
                      return y && m && d ? `${y}-${m}-${d}` : '';
                    })()}
                    onChange={(e) => {
                      if (!e.target.value) return;
                      const [y, m, d] = e.target.value.split('-');
                      const newTo = `${d}/${m}/${y}`;
                      const currentFrom = attendanceCustomRange?.from || attendanceDailyRange.start;
                      setAttendanceCustomRange({ from: currentFrom, to: newTo });
                    }}
                    className="px-2 py-1 rounded bg-[var(--color-bg-surface)] border border-[var(--color-border)] text-xs font-mono focus:outline-none focus:ring-2 focus:ring-[var(--color-brand)]"
                  />
                  <button
                    onClick={() => setAttendanceCustomRange(null)}
                    className="ml-1 px-2 py-1 text-xs font-bold text-[var(--color-brand)] hover:underline"
                    title="Reset về 30 ngày qua"
                  >Reset</button>
                </div>

                <div className="flex bg-[var(--color-bg-surface)] border border-[var(--color-border)] p-0.5 rounded-lg ml-auto">
                  {([
                    { k: 'all', l: 'Tất cả' },
                    { k: 'with_activity', l: 'Có log' },
                    { k: 'with_schedule', l: 'Có lịch' },
                    { k: 'missed', l: 'Bỏ ca' },
                  ] as const).map((opt) => (
                    <button
                      key={opt.k}
                      onClick={() => setAttendanceFilter(opt.k)}
                      className={cn(
                        "px-2 py-1 rounded text-[10px] font-bold uppercase tracking-wider transition-all",
                        attendanceFilter === opt.k ? "bg-[var(--color-brand-muted)] text-[var(--color-brand)]" : "text-slate-500 hover:text-slate-300"
                      )}
                    >{opt.l}</button>
                  ))}
                </div>
              </div>

              {/* SUMMARY ROW */}
              {attendanceDailyData?.summary && (
                <div className="px-6 py-3 border-b border-[var(--color-border)] grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                  <div>
                    <p className="text-slate-500 font-bold uppercase tracking-wider text-[10px] mb-1">Đã trực</p>
                    <p className="font-mono font-bold text-green-500">{attendanceDailyData.summary.total_worked_hhmm || '—'}</p>
                  </div>
                  <div>
                    <p className="text-slate-500 font-bold uppercase tracking-wider text-[10px] mb-1">Theo lịch</p>
                    <p className="font-mono font-bold text-blue-400">{attendanceDailyData.summary.total_scheduled_hhmm || '—'}</p>
                  </div>
                  <div>
                    <p className="text-slate-500 font-bold uppercase tracking-wider text-[10px] mb-1">Đúng giờ</p>
                    <p className="font-mono font-bold text-green-500 tabular-nums">{attendanceDailyData.summary.counters?.on_time || 0} <span className="font-normal text-slate-500">/ {(attendanceDailyData.summary.counters?.on_time || 0) + (attendanceDailyData.summary.counters?.late || 0) + (attendanceDailyData.summary.counters?.missed || 0)} ca</span></p>
                  </div>
                  <div>
                    <p className="text-slate-500 font-bold uppercase tracking-wider text-[10px] mb-1">Tỷ lệ</p>
                    <p className={cn("font-mono font-bold tabular-nums",
                      attendanceDailyData.summary.overall_compliance_pct === null ? "text-slate-500" :
                      attendanceDailyData.summary.overall_compliance_pct >= 90 ? "text-green-500" :
                      attendanceDailyData.summary.overall_compliance_pct >= 70 ? "text-amber-500" : "text-red-500"
                    )}>
                      {attendanceDailyData.summary.overall_compliance_pct === null ? '—' : `${attendanceDailyData.summary.overall_compliance_pct}%`}
                    </p>
                  </div>
                </div>
              )}

              {/* BODY: timeline cards */}
              <div className="overflow-y-auto p-4 space-y-2 flex-1">
                {attendanceDailyLoading && (
                  <div className="text-center py-12 text-sm text-slate-500">Đang tải timeline…</div>
                )}
                {!attendanceDailyLoading && attendanceDailyData && (() => {
                  // Apply filter
                  let days = attendanceDailyData.days;
                  if (attendanceFilter === 'with_activity') days = days.filter((d) => d.logs.length > 0);
                  else if (attendanceFilter === 'with_schedule') days = days.filter((d) => d.schedules.length > 0);
                  else if (attendanceFilter === 'missed') days = days.filter((d) => d.status === 'missed');
                  // Hide future days
                  days = days.filter((d) => !d.is_future);
                  // Reverse: ngày mới nhất lên đầu
                  days = [...days].reverse();
                  if (days.length === 0) {
                    return (
                      <div className="text-center py-12 text-sm text-slate-500">
                        {attendanceFilter === 'with_activity' ? 'Không có ngày nào có log chấm công trong khoảng này.' :
                         attendanceFilter === 'missed' ? 'Tuyệt vời! Không có ngày nào bỏ ca.' :
                         attendanceFilter === 'with_schedule' ? 'Người này chưa có lịch trực thiết lập.' :
                         'Không có dữ liệu trong khoảng này.'}
                      </div>
                    );
                  }

                  const statusMeta: Record<string, { label: string; dotCls: string; bgCls: string; textCls: string }> = {
                    on_time: { label: 'Đúng giờ', dotCls: 'bg-green-500', bgCls: 'bg-green-500/10', textCls: 'text-green-500' },
                    late: { label: 'Đi muộn', dotCls: 'bg-amber-500', bgCls: 'bg-amber-500/10', textCls: 'text-amber-500' },
                    missed: { label: 'Bỏ ca', dotCls: 'bg-red-500', bgCls: 'bg-red-500/10', textCls: 'text-red-500' },
                    on_leave: { label: 'Nghỉ phép', dotCls: 'bg-blue-500', bgCls: 'bg-blue-500/10', textCls: 'text-blue-500' },
                    off_schedule: { label: 'Ngoài lịch', dotCls: 'bg-violet-500', bgCls: 'bg-violet-500/10', textCls: 'text-violet-500' },
                    no_schedule: { label: 'Không có lịch', dotCls: 'bg-slate-500', bgCls: 'bg-slate-500/10', textCls: 'text-slate-500' },
                  };

                  return days.map((d) => {
                    const meta = statusMeta[d.status] || statusMeta.no_schedule;
                    const [yy, mm, dd] = d.date.split('-');
                    return (
                      <div key={d.date} className={cn(
                        "rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-surface)] overflow-hidden",
                        d.is_today && "ring-2 ring-[var(--color-brand)] ring-offset-2 ring-offset-[var(--color-bg-base)]"
                      )}>
                        {/* Day header */}
                        <div className="px-4 py-3 flex items-center gap-3 border-b border-[var(--color-border)]">
                          <div className="text-center w-12 shrink-0">
                            <p className="text-[9px] font-bold uppercase tracking-widest text-slate-500">{d.weekday_short}</p>
                            <p className="text-lg font-bold tabular-nums leading-tight">{dd}</p>
                            <p className="text-[9px] text-slate-500 tabular-nums">{mm}/{yy}</p>
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className={cn("inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider", meta.bgCls, meta.textCls)}>
                                <span className={cn("w-1.5 h-1.5 rounded-full", meta.dotCls)} />
                                {meta.label}
                              </span>
                              {d.is_today && <span className="text-[10px] font-bold text-[var(--color-brand)] uppercase">Hôm nay</span>}
                            </div>
                            <p className="text-xs text-slate-500 mt-0.5">{d.weekday_label}</p>
                          </div>
                          <div className="text-right shrink-0">
                            <p className="text-xs text-slate-500 uppercase font-bold tracking-wider">Đã trực</p>
                            <p className={cn("font-mono font-bold text-sm tabular-nums", d.minutes > 0 ? meta.textCls : 'text-slate-500')}>
                              {d.minutes > 0 ? minutesToHHMM(d.minutes) : '—'}
                            </p>
                            {d.scheduled_minutes > 0 && (
                              <p className="text-[10px] text-slate-500 font-mono tabular-nums">
                                / {minutesToHHMM(d.scheduled_minutes)} lịch
                              </p>
                            )}
                          </div>
                        </div>

                        {/* Schedules row */}
                        {d.schedules.length > 0 && (
                          <div className="px-4 py-2 bg-slate-50 dark:bg-slate-900/30 border-b border-[var(--color-border)]">
                            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">Ca trực theo lịch</p>
                            <div className="flex flex-wrap gap-2">
                              {d.schedules.map((s) => (
                                <span key={s.id} className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 text-[11px] font-mono font-bold tabular-nums">
                                  <Clock size={10} /> {s.start_time} – {s.end_time}{s.crosses_midnight && ' (+1)'}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Logs row */}
                        {d.logs.length > 0 && (
                          <div className="px-4 py-2">
                            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">Log chấm công ({d.logs.length})</p>
                            <div className="space-y-1">
                              {d.logs.map((log) => {
                                const s = new Date(log.started_at);
                                const e = new Date(log.ended_at);
                                const pad = (n: number) => String(n).padStart(2, '0');
                                const sLabel = `${pad(s.getHours())}:${pad(s.getMinutes())}`;
                                const eLabel = `${pad(e.getHours())}:${pad(e.getMinutes())}`;
                                return (
                                  <div key={log.id} className="flex items-center gap-2 py-1 text-xs">
                                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono tabular-nums">
                                      {sLabel} → {eLabel}
                                    </span>
                                    <span className="font-mono font-bold tabular-nums text-[var(--color-brand)]">{minutesToHHMM(log.duration_minutes)}</span>
                                    {log.source && <span className="text-[9px] font-bold uppercase text-slate-500 ml-auto">[{log.source}]</span>}
                                    {log.schedule_id && <span className="text-[9px] font-bold uppercase text-green-500">✓ KHỚP LỊCH</span>}
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {/* Leave row */}
                        {d.leave && (
                          <div className="px-4 py-2 bg-blue-500/5 border-t border-[var(--color-border)] text-xs">
                            <span className="font-bold text-blue-400">📋 {d.leave.type}</span>
                            {d.leave.reason && <span className="text-slate-500"> — "{d.leave.reason}"</span>}
                          </div>
                        )}
                      </div>
                    );
                  });
                })()}
              </div>

              <div className="px-6 py-3 border-t border-[var(--color-border)] flex justify-end gap-2">
                <button
                  onClick={() => setAttendanceDetail(null)}
                  className="px-4 py-2 rounded-lg bg-slate-100 dark:bg-slate-800 font-bold text-sm hover:brightness-110 transition-all"
                >Đóng</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Toast Notification Simulation */}
      <div className="fixed bottom-8 right-8 z-[100]">
        <motion.div 
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          className="bg-[var(--color-bg-surface)] border border-[var(--color-border)] rounded-xl p-4 shadow-2xl flex items-center gap-4 max-w-sm"
        >
          <div className="w-10 h-10 rounded-full bg-green-500/20 text-green-500 flex items-center justify-center shrink-0">
            <CheckCircle2 size={24} />
          </div>
          <div>
            <p className="text-sm font-bold">Kết nối thành công</p>
            <p className="text-xs text-[var(--color-text-secondary)]">Đã đồng bộ dữ liệu với Discord Bot Homie Medic.</p>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
