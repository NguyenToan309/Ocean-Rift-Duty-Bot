import { useState, useMemo } from 'react';
import {
  ScrollText, Search, Filter, X, ChevronDown, ChevronUp, Download, Code,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useAuditLogs } from '../hooks/useApi';
import { getActionMeta, formatAuditDetail, categoryBadgeClass, categoryIconBgClass } from '../lib/audit';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Avatar } from '../components/ui/avatar';
import { Skeleton, EmptyState, DiscordIdChip } from '../components/shared/misc';
import { avatarText, formatDateTime, timeAgo } from '../lib/format';
import { cn } from '../lib/cn';

// Group actions theo category business
const ACTION_GROUPS: Array<{ label: string; icon: string; color: string; actions: string[] }> = [
  {
    label: 'Lịch trực', icon: '📅', color: 'var(--info)',
    actions: ['SCHEDULE_CREATED', 'SCHEDULE_UPDATED', 'SCHEDULE_DELETED'],
  },
  {
    label: 'Đơn nghỉ', icon: '🏖️', color: 'var(--success)',
    actions: ['LEAVE_REQUESTED', 'LEAVE_APPROVED', 'LEAVE_REJECTED'],
  },
  {
    label: 'Đơn xin out', icon: '🚪', color: 'var(--warning)',
    actions: ['RESIGN_REQUESTED', 'RESIGN_APPROVED', 'RESIGN_REJECTED'],
  },
  {
    label: 'Chấm công', icon: '📋', color: 'var(--info)',
    actions: ['LOG_UPLOADED', 'LOG_DELETED', 'LOG_REJECTED'],
  },
  {
    label: 'Nhân sự', icon: '👥', color: 'var(--primary)',
    actions: ['STAFF_ADDED', 'STAFF_UPDATED', 'STAFF_REMOVED', 'STAFF_ROLE_SYNCED'],
  },
  {
    label: 'Hệ thống', icon: '🔐', color: 'var(--muted-foreground)',
    actions: [
      'LOGIN_SUCCESS', 'LOGIN_FAILED', 'LOGIN_2FA_FAILED', 'LOGOUT',
      'ENABLE_2FA', 'ACCOUNT_LOCKED', 'ACCOUNT_UNLOCKED',
      'EXPORT_CSV', 'EXPORT_EXCEL',
      'CHANGE_ROLE_CONFIG', 'CHANGE_CHANNEL_CONFIG', 'SETUP_GUILD',
      'POSITION_ROLE_MAP_CHANGED', 'REMIND_SENT', 'ONBOARDING_REMINDED',
    ],
  },
  {
    label: 'Kỷ luật', icon: '⚖️', color: 'var(--destructive)',
    actions: ['DISCIPLINE', 'DISMISSED'],
  },
];

export function AuditLogPage() {
  const { currentGuildId } = useAuth();
  const [page, setPage] = useState(1);
  const [selectedActions, setSelectedActions] = useState<Set<string>>(new Set());
  const [userSearch, setUserSearch] = useState('');
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  // Pass first selected action to API (backend filters one at a time)
  const apiActionFilter = selectedActions.size === 1 ? Array.from(selectedActions)[0] : undefined;
  const logsQ = useAuditLogs(currentGuildId, page, apiActionFilter);

  const items = useMemo(() => {
    let list = logsQ.data?.items || [];
    if (selectedActions.size > 1) {
      list = list.filter(l => selectedActions.has(l.action));
    }
    if (userSearch.trim()) {
      const s = userSearch.toLowerCase().trim();
      list = list.filter(l => l.username.toLowerCase().includes(s));
    }
    return list;
  }, [logsQ.data, selectedActions, userSearch]);

  const resolved = logsQ.data?.resolved || {};

  const toggleAction = (act: string) => {
    const next = new Set(selectedActions);
    if (next.has(act)) next.delete(act);
    else next.add(act);
    setSelectedActions(next);
    setPage(1);
  };

  const toggleGroup = (label: string) => {
    const next = new Set(collapsedGroups);
    if (next.has(label)) next.delete(label);
    else next.add(label);
    setCollapsedGroups(next);
  };

  const toggleExpanded = (id: number) => {
    const next = new Set(expandedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpandedIds(next);
  };

  const clearFilters = () => {
    setSelectedActions(new Set());
    setUserSearch('');
    setPage(1);
  };

  return (
    <div className="space-y-6 max-w-[1400px] mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <ScrollText className="h-6 w-6 text-[var(--primary)]" />
            Audit Log — Truy vết hệ thống
          </h1>
          <p className="text-sm text-[var(--muted-foreground)] mt-1">
            Mọi thay đổi quan trọng được ghi lại với lý do và đối tượng cụ thể
          </p>
        </div>
        <Button variant="outline">
          <Download className="h-4 w-4" /> Xuất CSV
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6">
        {/* Filter sidebar */}
        <aside className="space-y-4">
          <Card className="p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold flex items-center gap-2">
                <Filter className="h-4 w-4 text-[var(--primary)]" />
                Bộ lọc
              </h3>
              {(selectedActions.size > 0 || userSearch) && (
                <Button variant="ghost" size="sm" onClick={clearFilters}>
                  <X className="h-3 w-3" /> Xóa
                </Button>
              )}
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs font-bold uppercase tracking-wider text-[var(--muted-foreground)] mb-1.5 block">
                  Người thực hiện
                </label>
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[var(--muted-foreground)]" />
                  <Input
                    placeholder="Tìm theo tên..."
                    value={userSearch}
                    onChange={e => setUserSearch(e.target.value)}
                    className="pl-8 h-8 text-sm"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-bold uppercase tracking-wider text-[var(--muted-foreground)] mb-1.5 block">
                  Loại hành động
                </label>
                <div className="space-y-1">
                  {ACTION_GROUPS.map(group => {
                    const collapsed = collapsedGroups.has(group.label);
                    const selectedInGroup = group.actions.filter(a => selectedActions.has(a)).length;
                    return (
                      <div key={group.label} className="border border-[var(--border)] rounded-lg overflow-hidden">
                        <button
                          onClick={() => toggleGroup(group.label)}
                          className="w-full px-2.5 py-1.5 flex items-center justify-between hover:bg-[var(--muted)] transition-colors"
                        >
                          <span className="text-xs font-semibold flex items-center gap-1.5" style={{ color: group.color }}>
                            <span>{group.icon}</span>
                            {group.label}
                            {selectedInGroup > 0 && (
                              <span className="ml-1 bg-[var(--primary)] text-white text-[9px] rounded-full px-1.5 py-px font-bold">
                                {selectedInGroup}
                              </span>
                            )}
                          </span>
                          {collapsed ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
                        </button>
                        {!collapsed && (
                          <div className="px-2 pb-2 space-y-0.5">
                            {group.actions.map(act => {
                              const meta = getActionMeta(act);
                              return (
                                <label
                                  key={act}
                                  className="flex items-center gap-2 px-1.5 py-1 rounded text-xs hover:bg-[var(--muted)] cursor-pointer"
                                >
                                  <input
                                    type="checkbox"
                                    checked={selectedActions.has(act)}
                                    onChange={() => toggleAction(act)}
                                    className="rounded accent-[var(--primary)]"
                                  />
                                  <span>{meta.emoji}</span>
                                  <span className="truncate flex-1">{meta.label}</span>
                                </label>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </Card>
        </aside>

        {/* Timeline feed */}
        <main className="space-y-3 min-w-0">
          {logsQ.loading && [...Array(5)].map((_, i) => <Skeleton key={i} className="h-32" />)}

          {!logsQ.loading && items.length === 0 && (
            <Card className="p-8">
              <EmptyState
                icon={<ScrollText className="h-12 w-12" />}
                title="Chưa có hoạt động"
                description="Khi có thay đổi trong hệ thống, sẽ xuất hiện tại đây"
              />
            </Card>
          )}

          {items.map((log: any, idx: number) => (
            <AuditEntry
              key={log.id}
              log={log}
              resolved={resolved}
              isLast={idx === items.length - 1}
              expanded={expandedIds.has(log.id)}
              onToggle={() => toggleExpanded(log.id)}
            />
          ))}

          {/* Pagination */}
          {items.length > 0 && (
            <div className="flex items-center justify-between py-3">
              <p className="text-xs text-[var(--muted-foreground)]">
                {logsQ.data ? `Tổng ${logsQ.data.total.toLocaleString('vi-VN')} bản ghi` : ''}
              </p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}>
                  Trang trước
                </Button>
                <span className="text-xs px-3 py-1.5 flex items-center font-medium">Trang {page}</span>
                <Button variant="outline" size="sm" onClick={() => setPage(p => p + 1)} disabled={items.length < 50}>
                  Trang sau
                </Button>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function AuditEntry({
  log, resolved, isLast, expanded, onToggle,
}: any) {
  const meta = getActionMeta(log.action);
  const detail = log.detail || {};
  const note = detail.note || detail.reason || '';

  // Build human-readable target description
  const targetDesc = buildTargetDescription(log, resolved);

  // Compute before/after if "changes" field exists
  const changes = detail.changes;
  const hasChanges = changes && typeof changes === 'object' && Object.keys(changes).length > 0;

  // Show JSON only on demand
  const [showJson, setShowJson] = useState(false);

  return (
    <Card className="overflow-hidden hover:shadow-sm transition-shadow">
      <div className="flex gap-3 p-4">
        {/* Timeline avatar */}
        <div className="relative flex-shrink-0">
          <div className={cn('w-10 h-10 rounded-full flex items-center justify-center text-lg', categoryIconBgClass(meta.category))}>
            {meta.emoji}
          </div>
          {!isLast && <div className="absolute top-12 left-1/2 -translate-x-1/2 w-px h-[calc(100%-32px)] bg-[var(--border)]" />}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
              <Avatar fallback={avatarText(log.username)} size={20} />
              <span className="text-sm font-semibold">{log.username}</span>
              <DiscordIdChip id={log.user_id} />
              <Badge className={cn('text-[10px] border-0', categoryBadgeClass(meta.category))}>
                {meta.label}
              </Badge>
            </div>
            <span
              className="text-[10px] text-[var(--muted-foreground)] cursor-help"
              title={formatDateTime(log.created_at)}
            >
              {timeAgo(log.created_at)}
            </span>
          </div>

          {/* Resolved target description (human-readable, NOT raw IDs) */}
          {targetDesc && (
            <p className="text-sm mt-1.5 text-[var(--foreground)]/90 leading-relaxed">
              {targetDesc}
            </p>
          )}

          {/* Note prominent */}
          {note && (
            <div className="mt-3 flex items-start gap-2 p-3 rounded-lg bg-[var(--muted)]/60 border-l-2 border-[var(--primary)]">
              <span className="text-base">💬</span>
              <p className="text-sm italic text-[var(--foreground)]/90 flex-1">
                "{note}"
              </p>
            </div>
          )}

          {/* Expand button */}
          {(hasChanges || Object.keys(detail).length > 0) && (
            <button
              onClick={onToggle}
              className="mt-3 text-xs text-[var(--primary)] hover:underline flex items-center gap-1 font-medium"
            >
              {expanded ? (
                <><ChevronUp className="h-3 w-3" /> Thu gọn</>
              ) : (
                <><ChevronDown className="h-3 w-3" /> Xem chi tiết</>
              )}
            </button>
          )}

          {/* Expanded section */}
          {expanded && (
            <div className="mt-3 space-y-2">
              {/* Before/After diff (human-readable) */}
              {hasChanges && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  <div className="p-3 rounded-lg bg-[var(--destructive)]/5 border border-[var(--destructive)]/20">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--destructive)] mb-1">Trước</p>
                    {Object.entries(changes).map(([field, val]: any) => (
                      <div key={field} className="text-xs">
                        <span className="text-[var(--muted-foreground)]">{fieldLabel(field)}: </span>
                        <span className="font-medium">{formatValue(val.before, resolved)}</span>
                      </div>
                    ))}
                  </div>
                  <div className="p-3 rounded-lg bg-[var(--success)]/5 border border-[var(--success)]/20">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--success)] mb-1">Sau</p>
                    {Object.entries(changes).map(([field, val]: any) => (
                      <div key={field} className="text-xs">
                        <span className="text-[var(--muted-foreground)]">{fieldLabel(field)}: </span>
                        <span className="font-medium">{formatValue(val.after, resolved)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Other detail chips */}
              {!hasChanges && (
                <DetailChips detail={detail} resolved={resolved} />
              )}

              {/* Raw JSON (collapsed by default) */}
              <button
                onClick={() => setShowJson(s => !s)}
                className="text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] flex items-center gap-1"
              >
                <Code className="h-3 w-3" />
                {showJson ? 'Ẩn JSON gốc' : 'Xem JSON gốc (cho dev)'}
              </button>
              {showJson && (
                <pre className="text-[10px] font-mono bg-[var(--muted)] p-2 rounded-lg overflow-x-auto">
                  {JSON.stringify(detail, null, 2)}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

function DetailChips({ detail, resolved }: { detail: any; resolved: any }) {
  // Use existing audit.ts formatter if useful
  let chips: any[] = [];
  try {
    chips = formatAuditDetail(detail, resolved) || [];
  } catch { chips = []; }
  if (chips.length === 0) {
    return null;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {chips.map((c: any, i: number) => (
        <Badge key={i} variant="outline" className="text-[10px]">
          <span className="text-[var(--muted-foreground)] mr-1">{c.label}:</span>
          <span className="font-medium">{String(c.value)}</span>
        </Badge>
      ))}
    </div>
  );
}

function buildTargetDescription(log: any, resolved: any): string {
  const d = log.detail || {};
  const action = log.action;
  const stafffName = (id: string) => resolved[id]?.name || id;

  // Custom narrative for common actions
  if (action === 'LEAVE_APPROVED' && d.for_user) {
    return `Đã duyệt đơn nghỉ #${d.request_id || '?'} của ${stafffName(d.for_user)}`;
  }
  if (action === 'LEAVE_REJECTED' && d.for_user) {
    return `Đã từ chối đơn nghỉ #${d.request_id || '?'} của ${stafffName(d.for_user)}`;
  }
  if (action === 'STAFF_ADDED' && d.staff_user_id) {
    return `Đã thêm ${d.staff_username || stafffName(d.staff_user_id)} vào danh sách (chức vụ: ${d.position || '—'})`;
  }
  if (action === 'STAFF_UPDATED' && d.staff_user_id) {
    return `Đã cập nhật thông tin của ${d.staff_username || stafffName(d.staff_user_id)}`;
  }
  if (action === 'STAFF_REMOVED' && d.staff_user_id) {
    return `Đã gỡ ${d.staff_username || stafffName(d.staff_user_id)} khỏi danh sách hoạt động`;
  }
  if (action === 'STAFF_ROLE_SYNCED') {
    const added = d.added_role_id ? `+ role ${resolved[d.added_role_id]?.name || d.added_role_id}` : '';
    const removed = d.removed_role_id ? `- role ${resolved[d.removed_role_id]?.name || d.removed_role_id}` : '';
    return `Đồng bộ Discord role: ${[added, removed].filter(Boolean).join(', ') || 'không có thay đổi'}`;
  }
  if (action === 'SCHEDULE_CREATED' || action === 'SCHEDULE_UPDATED' || action === 'SCHEDULE_DELETED') {
    return `Lịch trực ${d.weekday ? 'thứ ' + (d.weekday + 1) : ''} ${d.start || ''}${d.end ? '-' + d.end : ''}`;
  }
  if (action === 'LOG_DELETED' && d.log_id) {
    return `Đã xóa bản ghi chấm công #${d.log_id}`;
  }
  if (action === 'POSITION_ROLE_MAP_CHANGED') {
    return 'Đã cập nhật bảng map chức vụ → quyền hệ thống';
  }
  return '';
}

function fieldLabel(field: string): string {
  const map: Record<string, string> = {
    position: 'Chức vụ',
    department: 'Khoa',
    username: 'Tên',
    is_active: 'Trạng thái',
    start: 'Bắt đầu',
    end: 'Kết thúc',
    weekday: 'Thứ',
    user_id: 'Người',
    role_id: 'Role',
    channel_id: 'Kênh',
  };
  return map[field] || field;
}

function formatValue(v: any, _resolved: any): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'Có' : 'Không';
  return String(v);
}
