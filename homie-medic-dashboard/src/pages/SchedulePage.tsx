import { useState, useMemo, useEffect } from 'react';
import {
  Plus, ChevronLeft, ChevronRight, Calendar as CalendarIcon, Clock, Users,
  Trash2, AlertCircle,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useScheduleCalendar, useScheduleGrid, useStaffList } from '../hooks/useApi';
import { api, formatError } from '../lib/api';
import { promptNote } from '../lib/promptNote';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Avatar } from '../components/ui/avatar';
import { Input, Textarea, Label } from '../components/ui/input';
import { NativeSelect } from '../components/ui/select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '../components/ui/dialog';
import { Skeleton, EmptyState } from '../components/shared/misc';
import { WEEKDAYS_SHORT_VI, avatarText } from '../lib/format';
import { useAvatars } from '../contexts/AvatarContext';
import { cn } from '../lib/cn';

const MONTHS_VI = [
  'Tháng 1', 'Tháng 2', 'Tháng 3', 'Tháng 4', 'Tháng 5', 'Tháng 6',
  'Tháng 7', 'Tháng 8', 'Tháng 9', 'Tháng 10', 'Tháng 11', 'Tháng 12',
];

const WEEKDAY_LABELS_FULL = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ nhật'];

interface EditingSlot {
  mode: 'create' | 'edit';
  id?: number;
  user_id: string;
  username?: string;
  weekday: number;
  start_time: string;
  end_time: string;
}

export function SchedulePage() {
  const { currentGuildId, currentGuild } = useAuth();
  const isAdmin = currentGuild?.is_admin || false;
  const isMod = currentGuild?.is_mod || isAdmin;

  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [editing, setEditing] = useState<EditingSlot | null>(null);

  const calQ = useScheduleCalendar(currentGuildId, year, month);
  const gridQ = useScheduleGrid(currentGuildId, 'week');

  const goPrev = () => {
    if (month === 1) { setMonth(12); setYear(y => y - 1); }
    else setMonth(m => m - 1);
  };
  const goNext = () => {
    if (month === 12) { setMonth(1); setYear(y => y + 1); }
    else setMonth(m => m + 1);
  };
  const goToday = () => {
    setYear(now.getFullYear());
    setMonth(now.getMonth() + 1);
  };

  const cells = useMemo(() => {
    const firstDay = new Date(year, month - 1, 1);
    const firstWeekday = (firstDay.getDay() + 6) % 7;
    const daysInMonth = new Date(year, month, 0).getDate();
    const daysInPrevMonth = new Date(year, month - 1, 0).getDate();
    const result: Array<{ day: number; isCurrentMonth: boolean; isToday: boolean; date: string; weekday: number }> = [];

    for (let i = firstWeekday - 1; i >= 0; i--) {
      const day = daysInPrevMonth - i;
      const m = month - 1 || 12;
      const y = month - 1 < 1 ? year - 1 : year;
      result.push({
        day, isCurrentMonth: false, isToday: false,
        date: `${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`,
        weekday: 0,
      });
    }

    for (let d = 1; d <= daysInMonth; d++) {
      const isToday = year === now.getFullYear() && month === now.getMonth() + 1 && d === now.getDate();
      const dt = new Date(year, month - 1, d);
      const wd = (dt.getDay() + 6) % 7;
      result.push({
        day: d, isCurrentMonth: true, isToday,
        date: `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`,
        weekday: wd,
      });
    }

    let nextDay = 1;
    while (result.length < 42) {
      const m = month + 1 > 12 ? 1 : month + 1;
      const y = month + 1 > 12 ? year + 1 : year;
      result.push({
        day: nextDay++, isCurrentMonth: false, isToday: false,
        date: `${y}-${String(m).padStart(2, '0')}-${String(nextDay - 1).padStart(2, '0')}`,
        weekday: 0,
      });
    }

    return result;
  }, [year, month]);

  const shiftsByDate: Record<string, any[]> = {};
  (calQ.data?.days || []).forEach((d: any) => {
    shiftsByDate[d.date] = d.slots || d.shifts || [];
  });

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <CalendarIcon className="h-6 w-6 text-[var(--primary)]" />
            Lịch trực
          </h1>
          <p className="text-sm text-[var(--muted-foreground)] mt-1">
            {isAdmin
              ? 'Click vào ca trực để sửa, hoặc tạo ca mới'
              : 'Xem lịch trực — chỉ Admin mới sửa được'}
          </p>
        </div>
        {isAdmin && (
          <Button
            size="lg"
            onClick={() => setEditing({
              mode: 'create',
              user_id: '',
              weekday: now.getDay() === 0 ? 6 : now.getDay() - 1,
              start_time: '08:00',
              end_time: '12:00',
            })}
          >
            <Plus className="h-4 w-4" /> Tạo ca trực
          </Button>
        )}
      </div>

      <Tabs defaultValue="month">
        <TabsList>
          <TabsTrigger value="month">Lịch tháng</TabsTrigger>
          <TabsTrigger value="week">Lưới tuần</TabsTrigger>
          <TabsTrigger value="compliance">Tuân thủ</TabsTrigger>
        </TabsList>

        <TabsContent value="month">
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
            <Card className="lg:col-span-3 overflow-hidden">
              <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
                <div className="flex items-center gap-2">
                  <Button variant="ghost" size="icon" onClick={goPrev}>
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <h2 className="font-bold text-base min-w-[140px] text-center">
                    {MONTHS_VI[month - 1]}, {year}
                  </h2>
                  <Button variant="ghost" size="icon" onClick={goNext}>
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
                <Button variant="outline" size="sm" onClick={goToday}>Hôm nay</Button>
              </div>

              <div className="grid grid-cols-7 border-b border-[var(--border)] bg-[var(--muted)]/30">
                {WEEKDAYS_SHORT_VI.map((d, i) => (
                  <div
                    key={d}
                    className={cn(
                      'p-2 text-center text-xs font-bold uppercase tracking-wider',
                      i === 5 && 'text-[var(--primary)]',
                      i === 6 && 'text-[var(--destructive)]',
                    )}
                  >
                    {d}
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-7">
                {cells.map((cell, i) => {
                  const shifts = shiftsByDate[cell.date] || [];
                  return (
                    <div
                      key={i}
                      className={cn(
                        'min-h-[100px] p-1.5 border-r border-b border-[var(--border)] last:border-r-0',
                        !cell.isCurrentMonth && 'bg-[var(--muted)]/30 opacity-50',
                      )}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span
                          className={cn(
                            'text-xs font-semibold inline-flex items-center justify-center',
                            cell.isToday && 'bg-[var(--primary)] text-white w-6 h-6 rounded-full',
                          )}
                        >
                          {cell.day}
                        </span>
                        {isAdmin && cell.isCurrentMonth && (
                          <button
                            onClick={() => setEditing({
                              mode: 'create',
                              user_id: '',
                              weekday: cell.weekday,
                              start_time: '08:00',
                              end_time: '12:00',
                            })}
                            title="Thêm ca trực ngày này"
                            className="opacity-0 hover:opacity-100 transition-opacity text-[var(--primary)] hover:bg-[var(--primary)]/10 rounded p-0.5"
                          >
                            <Plus className="h-3 w-3" />
                          </button>
                        )}
                      </div>
                      <div className="space-y-0.5">
                        {shifts.slice(0, 3).map((s: any, idx: number) => (
                          <button
                            key={idx}
                            onClick={() => {
                              if (!isAdmin) return;
                              setEditing({
                                mode: 'edit',
                                id: s.id,
                                user_id: String(s.user_id || ''),
                                username: s.username,
                                weekday: cell.weekday,
                                start_time: s.start_time,
                                end_time: s.end_time,
                              });
                            }}
                            className={cn(
                              'w-full text-left text-[10px] px-1.5 py-0.5 rounded bg-[var(--primary)]/10 text-[var(--primary)] truncate transition-colors',
                              isAdmin && 'hover:bg-[var(--primary)]/20 cursor-pointer',
                            )}
                            title={`${s.start_time}-${s.end_time} · ${s.username}${isAdmin ? ' (click để sửa)' : ''}`}
                          >
                            {s.start_time} {s.username}
                          </button>
                        ))}
                        {shifts.length > 3 && (
                          <p className="text-[10px] text-[var(--muted-foreground)] pl-1">
                            +{shifts.length - 3} khác
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>

            <TodaySidebar gridData={gridQ.data} loading={gridQ.loading} />
          </div>
        </TabsContent>

        <TabsContent value="week">
          <Card className="p-6">
            <EmptyState
              icon={<CalendarIcon className="h-10 w-10" />}
              title="Lưới tuần"
              description="View dạng grid theo người × ngày. Sắp phát triển."
            />
          </Card>
        </TabsContent>

        <TabsContent value="compliance">
          <Card className="p-6">
            <EmptyState
              icon={<CalendarIcon className="h-10 w-10" />}
              title="Báo cáo tuân thủ"
              description="So sánh lịch đăng ký với chấm công thực tế. Sắp phát triển."
            />
          </Card>
        </TabsContent>
      </Tabs>

      {!isAdmin && (
        <Card className="p-4 border-l-4 border-l-[var(--info)] bg-[var(--info)]/5">
          <div className="flex gap-2 items-start">
            <AlertCircle className="h-4 w-4 text-[var(--info)] shrink-0 mt-0.5" />
            <p className="text-xs text-[var(--info)]">
              Bạn không có quyền sửa lịch trực. Chỉ tài khoản Admin (Viện Trưởng) mới chỉnh sửa được.
            </p>
          </div>
        </Card>
      )}

      {/* Edit/Create modal */}
      {editing && (
        <ScheduleEditModal
          slot={editing}
          guildId={currentGuildId}
          onClose={() => setEditing(null)}
          onSaved={() => { calQ.refetch(); gridQ.refetch(); setEditing(null); }}
        />
      )}
    </div>
  );
}

function TodaySidebar({ gridData, loading }: { gridData: any; loading: boolean }) {
  const { getAvatar, learnAvatar } = useAvatars();
  const todayWeekday = ((new Date().getDay() + 6) % 7);
  const todayShifts = gridData?.days?.[todayWeekday]?.slots || [];

  useEffect(() => {
    todayShifts.forEach((s: any) => {
      if (s.user_id && s.avatar_url) learnAvatar(String(s.user_id), s.avatar_url, s.username);
    });
  }, [todayShifts, learnAvatar]);

  return (
    <Card className="p-5 h-fit lg:sticky lg:top-20">
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-semibold flex items-center gap-2">
          <Clock className="h-4 w-4 text-[var(--primary)]" />
          Ca hôm nay
        </h4>
        <Badge variant="default">{todayShifts.length}</Badge>
      </div>
      {loading && <Skeleton className="h-24" />}
      {!loading && todayShifts.length === 0 && (
        <p className="text-xs text-[var(--muted-foreground)] italic py-3 text-center">
          Không có ca nào hôm nay
        </p>
      )}
      <div className="space-y-2">
        {todayShifts.map((s: any, i: number) => (
          <div key={i} className="p-2.5 rounded-lg border border-[var(--border)] hover:bg-[var(--muted)]">
            <div className="flex items-center gap-2">
              <Avatar
                src={getAvatar(String(s.user_id || ''))}
                fallback={avatarText(s.username)}
                size={28}
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{s.username}</p>
                <p className="text-xs text-[var(--muted-foreground)] font-mono-id">
                  {s.start_time} - {s.end_time}
                </p>
              </div>
              <Users className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function ScheduleEditModal({
  slot, guildId, onClose, onSaved,
}: {
  slot: EditingSlot;
  guildId: string | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  // Multi-day mode mặc định BẬT khi tạo mới → REPLACE semantics
  const [multiMode, setMultiMode] = useState(slot.mode === 'create');
  const [form, setForm] = useState({
    user_id: slot.user_id,
    weekday: slot.weekday,
    weekdays: [slot.weekday],  // dùng khi multiMode = true
    start_time: slot.start_time,
    end_time: slot.end_time,
    note: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resultMsg, setResultMsg] = useState<string | null>(null);
  const { getAvatar } = useAvatars();

  // Load staff list for user picker (chỉ khi tạo mới)
  const staffQ = useStaffList(slot.mode === 'create' ? guildId : null, { is_active: true });

  const toggleWeekday = (wd: number) => {
    setForm(f => {
      const set = new Set(f.weekdays);
      if (set.has(wd)) set.delete(wd);
      else set.add(wd);
      return { ...f, weekdays: Array.from(set).sort() };
    });
  };

  const submit = async () => {
    if (!guildId) return;
    if (form.note.trim().length < 3) {
      setError('Bắt buộc lý do (≥3 ký tự).');
      return;
    }
    setSaving(true);
    setError(null);
    setResultMsg(null);
    try {
      if (slot.mode === 'create' && multiMode) {
        if (!form.user_id) {
          setError('Chưa chọn nhân viên.');
          setSaving(false);
          return;
        }
        if (form.weekdays.length === 0) {
          setError('Chọn ít nhất 1 thứ trong tuần.');
          setSaving(false);
          return;
        }
        const r = await api.scheduleBulkReplace(guildId, {
          user_id: form.user_id,
          weekdays: form.weekdays,
          start_time: form.start_time,
          end_time: form.end_time,
          note: form.note.trim(),
        });
        const parts: string[] = [];
        if (r.created.length) parts.push(`Tạo mới: ${r.created.length}`);
        if (r.updated.length) parts.push(`Cập nhật: ${r.updated.length}`);
        if (r.removed.length) parts.push(`Gỡ ngày cũ: ${r.removed.length}`);
        setResultMsg(parts.join(' · ') || 'OK');
        setTimeout(() => onSaved(), 800);
      } else if (slot.mode === 'create') {
        // Single mode (legacy)
        if (!form.user_id) {
          setError('Chưa chọn nhân viên.');
          setSaving(false);
          return;
        }
        await api.scheduleCreate(guildId, {
          user_id: form.user_id,
          weekday: form.weekday,
          start_time: form.start_time,
          end_time: form.end_time,
          note: form.note.trim(),
        });
        onSaved();
      } else if (slot.id) {
        await api.scheduleUpdate(guildId, slot.id, {
          weekday: form.weekday,
          start_time: form.start_time,
          end_time: form.end_time,
          note: form.note.trim(),
        });
        onSaved();
      }
    } catch (err) {
      setError(formatError(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!guildId || !slot.id) return;
    const note = await promptNote({
      title: `Xoá ca trực ${slot.start_time} – ${slot.end_time}?`,
      description: 'Ca trực sẽ bị xoá khỏi lịch. Audit log ghi snapshot để xem lại.',
      placeholder: 'VD: nhân viên xin đổi ca, lịch trùng...',
      minLength: 3,
      destructive: true,
      confirmLabel: 'Xoá ca',
    });
    if (note === null) return;
    setSaving(true);
    try {
      await api.scheduleDelete(guildId, slot.id, note);
      onSaved();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={open => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {slot.mode === 'create' ? 'Tạo ca trực mới' : `Sửa ca trực · ${slot.username}`}
          </DialogTitle>
          <DialogDescription>
            {slot.mode === 'create' && multiMode
              ? `Đặt lịch ${form.weekdays.length} thứ với khung giờ ${form.start_time}-${form.end_time}`
              : `Lịch trực lặp theo tuần (mỗi ${WEEKDAY_LABELS_FULL[form.weekday]} hằng tuần)`}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {slot.mode === 'create' && (
            <div>
              <Label required>Nhân viên</Label>
              <NativeSelect
                value={form.user_id}
                onChange={e => setForm({ ...form, user_id: e.target.value })}
                className="mt-1"
              >
                <option value="">— Chọn nhân viên —</option>
                {(staffQ.data?.items || []).map(s => (
                  <option key={s.user_id} value={s.user_id}>
                    {s.position_icon} {s.username} ({s.position_label})
                  </option>
                ))}
              </NativeSelect>
              {(staffQ.data?.items || []).length === 0 && !staffQ.loading && (
                <p className="text-[10px] text-[var(--warning)] mt-1">
                  ⚠ Chưa có nhân viên nào — hãy thêm trong tab "Nhân sự" trước.
                </p>
              )}
            </div>
          )}

          {slot.mode === 'edit' && slot.username && (
            <div className="p-3 rounded-lg bg-[var(--muted)] flex items-center gap-3">
              <Avatar
                src={getAvatar(slot.user_id)}
                fallback={avatarText(slot.username)}
                size={32}
              />
              <div>
                <p className="font-medium text-sm">{slot.username}</p>
                <p className="text-[10px] font-mono-id text-[var(--muted-foreground)]">{slot.user_id}</p>
              </div>
            </div>
          )}

          {slot.mode === 'create' && (
            <div className="flex items-center justify-between p-2 rounded-lg bg-[var(--info)]/5 border border-[var(--info)]/20">
              <div>
                <p className="text-xs font-semibold">🔄 Chế độ thay thế (REPLACE)</p>
                <p className="text-[10px] text-[var(--muted-foreground)]">
                  Bật: chọn nhiều thứ, các ngày cũ KHÔNG chọn sẽ bị gỡ
                </p>
              </div>
              <input
                type="checkbox"
                checked={multiMode}
                onChange={e => setMultiMode(e.target.checked)}
                className="w-5 h-5 accent-[var(--primary)]"
              />
            </div>
          )}

          <div>
            <Label required>{slot.mode === 'create' && multiMode ? 'Các thứ trong tuần' : 'Thứ trong tuần'}</Label>
            {slot.mode === 'create' && multiMode ? (
              <div className="grid grid-cols-7 gap-1 mt-1">
                {WEEKDAY_LABELS_FULL.map((label, i) => {
                  const active = form.weekdays.includes(i);
                  return (
                    <button
                      key={i}
                      type="button"
                      onClick={() => toggleWeekday(i)}
                      className={cn(
                        'py-2 rounded-md text-xs font-bold transition-colors',
                        active
                          ? 'bg-[var(--primary)] text-white'
                          : 'bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--secondary)]',
                      )}
                      title={label}
                    >
                      {label.replace('Thứ ', 'T').replace('Chủ nhật', 'CN')}
                    </button>
                  );
                })}
              </div>
            ) : (
              <NativeSelect
                value={form.weekday}
                onChange={e => setForm({ ...form, weekday: Number(e.target.value) })}
                className="mt-1"
              >
                {WEEKDAY_LABELS_FULL.map((label, i) => (
                  <option key={i} value={i}>{label}</option>
                ))}
              </NativeSelect>
            )}
            {slot.mode === 'create' && multiMode && (
              <p className="text-[10px] text-[var(--muted-foreground)] mt-1">
                Đã chọn {form.weekdays.length} thứ. Các thứ KHÔNG chọn sẽ bị gỡ khỏi lịch (nếu đã có với cùng khung giờ).
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label required>Giờ bắt đầu</Label>
              <Input
                type="time"
                value={form.start_time}
                onChange={e => setForm({ ...form, start_time: e.target.value })}
                className="mt-1"
              />
            </div>
            <div>
              <Label required>Giờ kết thúc</Label>
              <Input
                type="time"
                value={form.end_time}
                onChange={e => setForm({ ...form, end_time: e.target.value })}
                className="mt-1"
              />
              {form.start_time >= form.end_time && (
                <p className="text-[10px] text-[var(--info)] mt-1">
                  ⚠ Ca qua đêm (kết thúc rạng sáng hôm sau)
                </p>
              )}
            </div>
          </div>

          <div>
            <Label required>Lý do</Label>
            <Textarea
              rows={2}
              placeholder={slot.mode === 'create' ? 'VD: Thêm ca trực cố định...' : 'VD: Đổi giờ theo yêu cầu...'}
              value={form.note}
              onChange={e => setForm({ ...form, note: e.target.value })}
              className="mt-1"
            />
            <p className="text-[10px] text-[var(--muted-foreground)] mt-1">
              Bắt buộc lý do (≥3 ký tự) — sẽ ghi vào audit log
            </p>
          </div>

          {error && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-[var(--destructive)]/10 text-[var(--destructive)] text-sm">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {resultMsg && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-[var(--success)]/10 text-[var(--success)] text-sm">
              <span>✅ {resultMsg}</span>
            </div>
          )}
        </div>

        <DialogFooter className="justify-between sm:justify-between">
          {slot.mode === 'edit' && (
            <Button variant="destructive" onClick={remove} disabled={saving}>
              <Trash2 className="h-4 w-4" /> Xóa ca
            </Button>
          )}
          <div className="flex gap-2 ml-auto">
            <Button variant="outline" onClick={onClose} disabled={saving}>Hủy</Button>
            <Button onClick={submit} disabled={saving}>
              {saving
                ? 'Đang lưu...'
                : slot.mode === 'create' && multiMode
                ? `Lưu lịch (${form.weekdays.length} thứ)`
                : slot.mode === 'create'
                ? 'Tạo ca'
                : 'Lưu thay đổi'}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
