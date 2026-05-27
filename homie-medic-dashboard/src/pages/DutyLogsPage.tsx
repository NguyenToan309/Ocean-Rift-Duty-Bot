import { useState, useMemo, useEffect } from 'react';
import {
  Download, Search, ChevronDown, ChevronUp, Trash2, FileText, ClipboardList, Clock,
} from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useLogs } from '../hooks/useApi';
import { api, formatError, type DutyLog } from '../lib/api';
import { promptNote } from '../lib/promptNote';
import { useAvatars } from '../contexts/AvatarContext';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { NativeSelect } from '../components/ui/select';
import { Avatar } from '../components/ui/avatar';
import { Skeleton, EmptyState } from '../components/shared/misc';
import { formatDateTime, minutesToHHMM, avatarText } from '../lib/format';
import { cn } from '../lib/cn';
import type { Period } from '../components/layout/Topbar';

const PERIOD_LABELS: Record<string, string> = {
  day: 'Hôm nay',
  week: 'Tuần này',
  month: 'Tháng này',
  quarter: 'Quý này',
  all: 'Tất cả',
};

interface UserGroup {
  user_id: string;
  username: string;
  logs: DutyLog[];
  totalMinutes: number;
  sessionCount: number;
  firstAt: string;
  lastAt: string;
}

export function DutyLogsPage() {
  const { period: topbarPeriod } = useOutletContext<{ period: Period }>();
  const { currentGuildId, currentGuild } = useAuth();
  const isAdmin = currentGuild?.is_admin || false;

  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  // Period local — mặc định theo topbar nhưng có thể override
  const [period, setPeriod] = useState<string>(topbarPeriod || 'all');
  const [expandedUsers, setExpandedUsers] = useState<Set<string>>(new Set());

  const logsQ = useLogs(currentGuildId, page, search, period);
  const { learnAvatar } = useAvatars();

  // Seed avatar cache từ logs
  useEffect(() => {
    (logsQ.data?.items || []).forEach((log: any) => {
      if (log.user_id && log.avatar_url) learnAvatar(String(log.user_id), log.avatar_url, log.username);
    });
  }, [logsQ.data, learnAvatar]);

  // Group logs by user_id
  const groups: UserGroup[] = useMemo(() => {
    const filtered = (logsQ.data?.items || []).filter(l =>
      !sourceFilter || (l.source || '').toUpperCase() === sourceFilter.toUpperCase()
    );
    const map = new Map<string, UserGroup>();
    for (const log of filtered) {
      const key = log.user_id || `_${log.username}`;
      const g = map.get(key);
      if (!g) {
        map.set(key, {
          user_id: log.user_id,
          username: log.username,
          logs: [log],
          totalMinutes: log.duration_minutes || 0,
          sessionCount: 1,
          firstAt: log.started_at,
          lastAt: log.started_at,
        });
      } else {
        g.logs.push(log);
        g.totalMinutes += log.duration_minutes || 0;
        g.sessionCount += 1;
        if (log.started_at < g.firstAt) g.firstAt = log.started_at;
        if (log.started_at > g.lastAt) g.lastAt = log.started_at;
      }
    }
    // Sort: most recent activity first
    return Array.from(map.values()).sort((a, b) => b.lastAt.localeCompare(a.lastAt));
  }, [logsQ.data, sourceFilter]);

  const toggle = (uid: string) => {
    const next = new Set(expandedUsers);
    if (next.has(uid)) next.delete(uid);
    else next.add(uid);
    setExpandedUsers(next);
  };

  const expandAll = () => {
    setExpandedUsers(new Set(groups.map(g => g.user_id || `_${g.username}`)));
  };
  const collapseAll = () => setExpandedUsers(new Set());

  const onExport = async () => {
    if (!currentGuildId) return;
    try {
      const r = await api.exportPrepare(currentGuildId, 'excel', 'month', { mode: 'logs' });
      window.open(r.download_url, '_blank');
    } catch (err) {
      alert('Lỗi: ' + formatError(err));
    }
  };

  const onDelete = async (logId: number, username: string) => {
    if (!currentGuildId) return;
    const note = await promptNote({
      title: `Xoá log của ${username}?`,
      description: 'Log sẽ bị xoá vĩnh viễn. Audit log sẽ ghi snapshot trước khi xoá để phục hồi nếu cần.',
      placeholder: 'VD: log sai giờ, đã có log khác chính xác hơn...',
      minLength: 3,
      destructive: true,
      confirmLabel: 'Xoá log',
    });
    if (note === null) return;
    try {
      await api.deleteLog(currentGuildId, logId, note);
      logsQ.refetch();
    } catch (err) {
      alert('Lỗi: ' + formatError(err));
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <ClipboardList className="h-6 w-6 text-[var(--primary)]" />
            Nhật ký chấm công
          </h1>
          <p className="text-sm text-[var(--muted-foreground)] mt-1">
            Group theo từng nhân viên — click để xem các ca trực chi tiết
          </p>
        </div>
        <Button onClick={onExport}>
          <Download className="h-4 w-4" /> Xuất Excel
        </Button>
      </div>

      {/* Filter */}
      <Card className="p-4 space-y-3">
        {/* Period switcher */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-[var(--muted-foreground)]">
            Khoảng thời gian:
          </span>
          <div className="flex items-center gap-0.5 bg-[var(--muted)] rounded-lg p-0.5">
            {(['day', 'week', 'month', 'quarter', 'all'] as const).map(p => (
              <button
                key={p}
                onClick={() => { setPeriod(p); setPage(1); }}
                className={cn(
                  'px-3 py-1 rounded-md text-xs font-medium transition-all',
                  period === p
                    ? 'bg-[var(--card)] text-[var(--foreground)] shadow-sm'
                    : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]',
                )}
              >
                {PERIOD_LABELS[p]}
              </button>
            ))}
          </div>
          <Badge variant="info" className="text-[10px]">
            Đang xem: {PERIOD_LABELS[period] || 'Tất cả'}
          </Badge>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--muted-foreground)]" />
            <Input
              placeholder="Tìm theo tên nhân viên..."
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1); }}
              className="pl-9"
            />
          </div>
          <NativeSelect value={sourceFilter} onChange={e => setSourceFilter(e.target.value)}>
            <option value="">— Tất cả nguồn —</option>
            <option value="OCR">OCR (Nhận diện ảnh)</option>
            <option value="FORWARD">Forward (Chuyển tiếp)</option>
            <option value="MESSAGE">Message (Text)</option>
            <option value="MANUAL">Thủ công</option>
          </NativeSelect>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={expandAll} className="flex-1">
              <ChevronDown className="h-3.5 w-3.5" /> Mở tất cả
            </Button>
            <Button variant="outline" size="sm" onClick={collapseAll} className="flex-1">
              <ChevronUp className="h-3.5 w-3.5" /> Đóng tất cả
            </Button>
          </div>
        </div>
      </Card>

      {/* Stats summary */}
      {!logsQ.loading && groups.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Card className="p-4">
            <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]">Tổng nhân viên</p>
            <p className="text-2xl font-bold mt-1">{groups.length}</p>
          </Card>
          <Card className="p-4">
            <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]">Tổng ca trực</p>
            <p className="text-2xl font-bold mt-1">{groups.reduce((s, g) => s + g.sessionCount, 0)}</p>
          </Card>
          <Card className="p-4">
            <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]">Tổng giờ</p>
            <p className="text-2xl font-bold mt-1">
              {minutesToHHMM(groups.reduce((s, g) => s + g.totalMinutes, 0))}
            </p>
          </Card>
        </div>
      )}

      {/* User groups */}
      <div className="space-y-3">
        {logsQ.loading && [...Array(3)].map((_, i) => <Skeleton key={i} className="h-24" />)}

        {!logsQ.loading && groups.length === 0 && (
          <Card className="p-8">
            <EmptyState
              icon={<FileText className="h-12 w-12" />}
              title={
                period !== 'all'
                  ? `Không có log nào trong ${PERIOD_LABELS[period] || 'kỳ này'}`
                  : 'Chưa có dữ liệu chấm công'
              }
              description={
                period !== 'all'
                  ? 'Thử mở rộng khoảng thời gian phía trên (VD: "Tất cả") để xem các log cũ.'
                  : 'Nhân viên forward tin nhắn LOG DUTY hoặc upload ảnh vào channel chấm công.'
              }
              action={
                period !== 'all' ? (
                  <Button
                    variant="outline"
                    onClick={() => { setPeriod('all'); setPage(1); }}
                  >
                    Xem tất cả log
                  </Button>
                ) : undefined
              }
            />
          </Card>
        )}

        {groups.map(group => {
          const key = group.user_id || `_${group.username}`;
          const expanded = expandedUsers.has(key);
          return (
            <UserGroupCard
              key={key}
              group={group}
              expanded={expanded}
              onToggle={() => toggle(key)}
              canDelete={isAdmin}
              onDelete={onDelete}
            />
          );
        })}
      </div>

      {/* Pagination */}
      {groups.length > 0 && (
        <div className="flex items-center justify-between py-3">
          <p className="text-xs text-[var(--muted-foreground)]">
            {logsQ.data ? `Trang ${page} · ${groups.length} nhân viên · ${logsQ.data.total.toLocaleString('vi-VN')} bản ghi tổng` : '...'}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}>
              Trước
            </Button>
            <Button variant="outline" size="sm" onClick={() => setPage(p => p + 1)} disabled={(logsQ.data?.items.length || 0) < (logsQ.data?.page_size || 20)}>
              Sau
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function UserGroupCard({
  group, expanded, onToggle, canDelete, onDelete,
}: {
  group: UserGroup;
  expanded: boolean;
  onToggle: () => void;
  canDelete: boolean;
  onDelete: (logId: number, username: string) => void;
}) {
  const { getAvatar } = useAvatars();
  const avatarUrl = getAvatar(group.user_id);
  return (
    <Card className="overflow-hidden">
      {/* User header — clickable */}
      <button
        onClick={onToggle}
        className="w-full p-4 flex items-center gap-4 hover:bg-[var(--muted)]/40 transition-colors text-left"
      >
        <Avatar src={avatarUrl} fallback={avatarText(group.username)} size={36} />
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-base truncate">{group.username}</p>
          <div className="flex items-center gap-2 mt-0.5">
            <span
              className="text-[11px] font-mono-id text-[var(--muted-foreground)] truncate"
              title={group.user_id}
            >
              ID: {group.user_id || '—'}
            </span>
          </div>
        </div>

        {/* Stats inline */}
        <div className="hidden sm:flex items-center gap-5 mr-2">
          <div className="text-center">
            <p className="text-[9px] uppercase tracking-wider text-[var(--muted-foreground)]">Ca</p>
            <p className="text-sm font-bold">{group.sessionCount}</p>
          </div>
          <div className="text-center">
            <p className="text-[9px] uppercase tracking-wider text-[var(--muted-foreground)]">Tổng giờ</p>
            <p className="text-sm font-bold text-[var(--primary)]">{minutesToHHMM(group.totalMinutes)}</p>
          </div>
          <div className="text-center">
            <p className="text-[9px] uppercase tracking-wider text-[var(--muted-foreground)]">Gần nhất</p>
            <p className="text-xs font-mono-id">{formatDateTime(group.lastAt).slice(0, 16)}</p>
          </div>
        </div>

        <div className="shrink-0 text-[var(--muted-foreground)]">
          {expanded ? <ChevronUp className="h-5 w-5" /> : <ChevronDown className="h-5 w-5" />}
        </div>
      </button>

      {/* Mobile stats row */}
      <div className="sm:hidden flex items-center justify-around px-4 pb-3 -mt-1 text-xs">
        <span>📋 {group.sessionCount} ca</span>
        <span className="text-[var(--primary)] font-bold">⏱ {minutesToHHMM(group.totalMinutes)}</span>
      </div>

      {/* Expanded — log list */}
      {expanded && (
        <div className="border-t border-[var(--border)] bg-[var(--muted)]/20">
          <div className="px-4 py-2 grid grid-cols-[1fr_1fr_auto_auto_auto] gap-3 text-[10px] font-bold uppercase tracking-wider text-[var(--muted-foreground)] border-b border-[var(--border)]">
            <span>Bắt đầu</span>
            <span>Kết thúc</span>
            <span>Thời lượng</span>
            <span>Nguồn</span>
            <span className="text-right">Thao tác</span>
          </div>
          <div className="divide-y divide-[var(--border)]/50">
            {group.logs.map(log => (
              <div
                key={log.id}
                className="px-4 py-2.5 grid grid-cols-[1fr_1fr_auto_auto_auto] gap-3 items-center text-sm hover:bg-[var(--muted)]/40"
              >
                <span className="font-mono-id text-xs flex items-center gap-1">
                  <Clock className="h-3 w-3 text-[var(--muted-foreground)]" />
                  {formatDateTime(log.started_at)}
                </span>
                <span className="font-mono-id text-xs flex items-center gap-1">
                  {log.ended_at ? (
                    <>
                      <Clock className="h-3 w-3 text-[var(--muted-foreground)]" />
                      {formatDateTime(log.ended_at)}
                    </>
                  ) : (
                    <Badge variant="success" className="text-[10px]">● Đang trực</Badge>
                  )}
                </span>
                <Badge variant="default" className="text-[10px] justify-self-start">
                  {minutesToHHMM(log.duration_minutes)}
                </Badge>
                <Badge variant={log.source === 'OCR' ? 'info' : 'secondary'} className="text-[10px] justify-self-start">
                  {log.source || 'manual'}
                </Badge>
                <div className="flex items-center gap-1 justify-end">
                  {log.image_url && (
                    <a
                      href={log.image_url}
                      target="_blank"
                      rel="noreferrer"
                      title="Xem ảnh gốc"
                      className="p-1.5 hover:bg-[var(--muted)] rounded text-[var(--info)]"
                    >
                      🖼
                    </a>
                  )}
                  {canDelete && (
                    <button
                      onClick={() => onDelete(log.id, group.username)}
                      title="Xóa log"
                      className="p-1.5 hover:bg-[var(--destructive)]/10 hover:text-[var(--destructive)] rounded text-[var(--muted-foreground)] transition-colors"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}
