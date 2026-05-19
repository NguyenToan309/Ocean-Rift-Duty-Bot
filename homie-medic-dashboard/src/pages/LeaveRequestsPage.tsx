import { useState, useEffect } from 'react';
import { Check, X, Clock, FileText, AlertCircle, RotateCcw } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useLeaveList } from '../hooks/useApi';
import { api, type LeaveRequest, formatError } from '../lib/api';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Avatar } from '../components/ui/avatar';
import { Textarea, Label } from '../components/ui/input';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '../components/ui/dialog';
import { Skeleton, EmptyState, DiscordIdChip } from '../components/shared/misc';
import { avatarText, formatDateShort, timeAgo } from '../lib/format';
import { useAvatars } from '../contexts/AvatarContext';
import { cn } from '../lib/cn';

type TabKey = 'pending' | 'approved' | 'rejected';

const TYPE_VARIANT: Record<string, 'success' | 'warning' | 'info' | 'default'> = {
  'Nghỉ phép': 'success',
  'Nghỉ ốm': 'warning',
  'Việc riêng': 'info',
  'Thôi việc': 'default',
};

export function LeaveRequestsPage() {
  const { currentGuildId, currentGuild } = useAuth();
  const isAdmin = currentGuild?.is_admin || false;
  const [tab, setTab] = useState<TabKey>('pending');
  const [selected, setSelected] = useState<LeaveRequest | null>(null);
  const { learnAvatar } = useAvatars();

  const status = tab.toUpperCase();
  const reqQ = useLeaveList(currentGuildId, status);

  // Seed avatar cache
  useEffect(() => {
    (reqQ.data || []).forEach((r: any) => {
      if (r.user_id && r.avatar_url) learnAvatar(String(r.user_id), r.avatar_url, r.username);
    });
  }, [reqQ.data, learnAvatar]);

  const tabs: { key: TabKey; label: string; variant: 'destructive' | 'success' | 'default' }[] = [
    { key: 'pending', label: 'Chờ duyệt', variant: 'destructive' },
    { key: 'approved', label: 'Đã duyệt', variant: 'success' },
    { key: 'rejected', label: 'Từ chối', variant: 'default' },
  ];

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <FileText className="h-6 w-6 text-[var(--primary)]" />
            Quản lý Đơn nghỉ
          </h1>
          <p className="text-sm text-[var(--muted-foreground)] mt-1">
            Phê duyệt hoặc từ chối đơn xin nghỉ phép/ốm
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-[var(--border)]">
        <div className="flex gap-1">
          {tabs.map(t => {
            const count = t.key === tab ? (reqQ.data?.length || 0) : null;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cn(
                  'px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px flex items-center gap-2',
                  tab === t.key
                    ? 'border-[var(--primary)] text-[var(--primary)]'
                    : 'border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)]',
                )}
              >
                {t.label}
                {count !== null && count > 0 && (
                  <Badge variant={t.variant === 'destructive' ? 'destructive' : t.variant === 'success' ? 'success' : 'default'} className="text-[10px]">
                    {count}
                  </Badge>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Cards */}
      {reqQ.loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-48" />)}
        </div>
      )}

      {!reqQ.loading && (reqQ.data || []).length === 0 && (
        <Card className="p-8">
          <EmptyState
            icon={<FileText className="h-12 w-12" />}
            title={`Không có đơn ${tab === 'pending' ? 'chờ duyệt' : tab === 'approved' ? 'đã duyệt' : 'bị từ chối'}`}
            description="Đơn nghỉ tạo từ Discord bằng lệnh /xinnghi"
          />
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {(reqQ.data || []).map(req => (
          <LeaveCard
            key={req.id}
            req={req}
            canDecide={isAdmin && req.status === 'PENDING'}
            canRevert={isAdmin && req.status !== 'PENDING'}
            onClick={() => setSelected(req)}
            onRevert={async (e) => {
              e.stopPropagation();
              if (!currentGuildId) return;
              const reason = window.prompt(
                `Hoàn tác đơn của ${req.username}?\n` +
                `Trạng thái hiện tại: ${req.status === 'APPROVED' ? 'Đã duyệt' : 'Từ chối'}\n\n` +
                `LƯU Ý: Nếu là đơn xin out đã duyệt, role Discord ĐÃ GỠ sẽ KHÔNG tự cấp lại.\n\n` +
                `Lý do hoàn tác (≥3 ký tự):`,
              );
              if (!reason || reason.trim().length < 3) {
                if (reason !== null) alert('Cần ghi lý do ≥3 ký tự.');
                return;
              }
              try {
                await api.leaveRevert(currentGuildId, req.id, reason.trim());
                reqQ.refetch();
              } catch (err) {
                alert('Lỗi: ' + formatError(err));
              }
            }}
          />
        ))}
      </div>

      {selected && (
        <LeaveDetailDrawer
          req={selected}
          guildId={currentGuildId}
          canDecide={isAdmin && selected.status === 'PENDING'}
          canRevert={isAdmin && selected.status !== 'PENDING'}
          onClose={() => setSelected(null)}
          onDecided={() => { reqQ.refetch(); setSelected(null); }}
        />
      )}
    </div>
  );
}

function LeaveCard({
  req, canDecide, canRevert, onClick, onRevert,
}: {
  req: LeaveRequest;
  canDecide: boolean;
  canRevert: boolean;
  onClick: () => void;
  onRevert?: (e: React.MouseEvent) => void;
}) {
  const { getAvatar } = useAvatars();
  return (
    <Card
      onClick={onClick}
      className="p-4 cursor-pointer hover:shadow-md hover:-translate-y-0.5 transition-all relative"
    >
      <div className="flex items-start gap-3 mb-3">
        <Avatar src={getAvatar(req.user_id)} fallback={avatarText(req.username)} size={40} />
        <div className="flex-1 min-w-0">
          <p className="font-semibold truncate">{req.username}</p>
          <DiscordIdChip id={req.user_id} />
        </div>
        <Badge variant={TYPE_VARIANT[req.type_label] || 'default'} className="shrink-0">
          {req.type_label}
        </Badge>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
          <Clock className="h-3.5 w-3.5" />
          {formatDateShort(req.start_date)} → {formatDateShort(req.end_date)} · {req.duration_days} ngày
        </div>
        <p className="text-xs line-clamp-2 italic text-[var(--foreground)]/80">
          "{req.reason}"
        </p>
        <div className="flex items-center justify-between mt-2">
          <p className="text-[10px] text-[var(--muted-foreground)]">
            {timeAgo(req.created_at)}
          </p>
          {canRevert && onRevert && (
            <button
              onClick={onRevert}
              className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-md bg-[var(--warning)]/10 text-[var(--warning)] hover:bg-[var(--warning)]/20 transition-colors"
              title="Hoàn tác về Chờ duyệt"
            >
              <RotateCcw className="h-3 w-3" />
              Hoàn tác
            </button>
          )}
        </div>
      </div>
    </Card>
  );
}

function LeaveDetailDrawer({
  req, guildId, canDecide, canRevert, onClose, onDecided,
}: {
  req: LeaveRequest;
  guildId: string | null;
  canDecide: boolean;
  canRevert: boolean;
  onClose: () => void;
  onDecided: () => void;
}) {
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { getAvatar } = useAvatars();

  const decide = async (approved: boolean) => {
    if (!guildId) return;
    if (note.trim().length < 3) {
      setError('Bắt buộc ghi lý do quyết định (≥3 ký tự).');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.leaveDecision(guildId, req.id, approved ? 'APPROVED' : 'REJECTED', note.trim());
      onDecided();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open onOpenChange={open => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Chi tiết đơn #{req.id}</DialogTitle>
          <DialogDescription>
            <Badge variant={req.status === 'PENDING' ? 'warning' : req.status === 'APPROVED' ? 'success' : 'destructive'}>
              {req.status === 'PENDING' ? 'Chờ duyệt' : req.status === 'APPROVED' ? 'Đã duyệt' : 'Từ chối'}
            </Badge>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
          <div className="flex items-center gap-3">
            <Avatar src={getAvatar(req.user_id)} fallback={avatarText(req.username)} size={48} />
            <div>
              <p className="font-semibold">{req.username}</p>
              <DiscordIdChip id={req.user_id} />
            </div>
          </div>

          <div>
            <Label>Loại đơn</Label>
            <p className="mt-1"><Badge variant={TYPE_VARIANT[req.type_label] || 'default'}>{req.type_label}</Badge></p>
          </div>

          <div>
            <Label>Thời gian</Label>
            <p className="text-sm mt-1 font-medium">
              {formatDateShort(req.start_date)} → {formatDateShort(req.end_date)}
            </p>
            <p className="text-xs text-[var(--muted-foreground)]">Tổng: {req.duration_days} ngày</p>
          </div>

          <div>
            <Label>Lý do xin nghỉ</Label>
            <div className="mt-1 p-3 rounded-lg bg-[var(--muted)] text-sm italic">
              "{req.reason}"
            </div>
          </div>

          {canDecide && (
            <div className="pt-3 border-t border-[var(--border)]">
              <Label required>Ghi chú quyết định</Label>
              <Textarea
                rows={3}
                placeholder="VD: Đã xác nhận với khoa trưởng, đồng ý duyệt"
                value={note}
                onChange={e => setNote(e.target.value)}
                className="mt-1"
              />
              <p className="text-[10px] text-[var(--muted-foreground)] mt-1">
                Bắt buộc ghi lý do (audit policy ≥3 ký tự)
              </p>
            </div>
          )}

          {error && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-[var(--destructive)]/10 text-[var(--destructive)] text-sm">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}
        </div>

        <DialogFooter className="justify-between sm:justify-between">
          {canRevert && (
            <Button
              variant="outline"
              onClick={async () => {
                if (!guildId) return;
                const reason = window.prompt(
                  `Hoàn tác đơn ${req.username}?\n` +
                  `Trạng thái: ${req.status === 'APPROVED' ? 'Đã duyệt' : 'Từ chối'} → Chờ duyệt\n\n` +
                  `LƯU Ý: Nếu là đơn xin out đã duyệt, role Discord ĐÃ GỠ sẽ KHÔNG tự cấp lại.\n\n` +
                  `Lý do hoàn tác (≥3 ký tự):`,
                );
                if (!reason || reason.trim().length < 3) {
                  if (reason !== null) alert('Cần ghi lý do ≥3 ký tự.');
                  return;
                }
                setSubmitting(true);
                try {
                  await api.leaveRevert(guildId, req.id, reason.trim());
                  onDecided();
                } catch (err) {
                  setError(formatError(err));
                } finally {
                  setSubmitting(false);
                }
              }}
              disabled={submitting}
              className="text-[var(--warning)] border-[var(--warning)]/40 hover:bg-[var(--warning)]/10"
            >
              <RotateCcw className="h-4 w-4" /> Hoàn tác
            </Button>
          )}
          <div className="flex gap-2 ml-auto">
            {canDecide ? (
              <>
                <Button variant="destructive" onClick={() => decide(false)} disabled={submitting}>
                  <X className="h-4 w-4" /> Từ chối
                </Button>
                <Button variant="success" onClick={() => decide(true)} disabled={submitting}>
                  <Check className="h-4 w-4" /> Duyệt
                </Button>
              </>
            ) : (
              <Button variant="outline" onClick={onClose}>Đóng</Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
