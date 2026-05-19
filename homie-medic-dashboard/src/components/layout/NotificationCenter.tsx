import { useEffect } from 'react';
import { X, Bell, Calendar, AlertTriangle, FileText, CheckCircle2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useLeavePending } from '../../hooks/useApi';
import { cn } from '../../lib/cn';
import { Button } from '../ui/button';
import { EmptyState } from '../shared/misc';

interface NotificationCenterProps {
  open: boolean;
  onClose: () => void;
  pendingCount: number;
}

export function NotificationCenter({ open, onClose, pendingCount }: NotificationCenterProps) {
  const navigate = useNavigate();
  const { currentGuildId } = useAuth();
  const pendingQ = useLeavePending(open ? currentGuildId : null);

  useEffect(() => {
    if (!open) return;
    const onEsc = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onEsc);
    return () => document.removeEventListener('keydown', onEsc);
  }, [open, onClose]);

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        className={cn(
          'fixed inset-0 bg-black/30 z-40 transition-opacity',
          open ? 'opacity-100' : 'opacity-0 pointer-events-none',
        )}
      />

      {/* Drawer */}
      <aside
        className={cn(
          'fixed right-0 top-0 h-full w-full max-w-md bg-[var(--card)] border-l border-[var(--border)] shadow-2xl z-50',
          'transition-transform duration-200 flex flex-col',
          open ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        <header className="h-16 flex items-center justify-between px-6 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <Bell className="h-5 w-5 text-[var(--primary)]" />
            <h3 className="font-bold">Trung tâm thông báo</h3>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-[var(--muted)] rounded-md">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {/* Pending approvals */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-bold uppercase tracking-wider text-[var(--muted-foreground)]">
                📥 Đơn chờ duyệt
              </p>
              {pendingCount > 0 && (
                <span className="text-xs bg-[var(--destructive)]/10 text-[var(--destructive)] px-2 py-0.5 rounded-full font-semibold">
                  {pendingCount}
                </span>
              )}
            </div>
            {pendingQ.loading && <p className="text-xs text-[var(--muted-foreground)]">Đang tải...</p>}
            {!pendingQ.loading && pendingQ.data && pendingQ.data.length === 0 && (
              <p className="text-xs text-[var(--muted-foreground)] italic">Không có đơn nào chờ duyệt</p>
            )}
            <div className="space-y-1">
              {(pendingQ.data || []).slice(0, 5).map((req) => (
                <button
                  key={req.id}
                  onClick={() => { navigate('/leave-requests'); onClose(); }}
                  className="w-full text-left p-3 rounded-lg border border-[var(--border)] hover:bg-[var(--muted)] transition-colors"
                >
                  <div className="flex items-start gap-2">
                    <FileText className="h-4 w-4 text-[var(--info)] shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{req.username}</p>
                      <p className="text-xs text-[var(--muted-foreground)] truncate">
                        {req.type_label} • {req.start_date} → {req.end_date}
                      </p>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </section>

          {/* Burnout alerts (placeholder) */}
          <section>
            <p className="text-xs font-bold uppercase tracking-wider text-[var(--muted-foreground)] mb-2">
              🚨 Cảnh báo burnout
            </p>
            <div className="text-xs text-[var(--muted-foreground)] italic p-3 rounded-lg bg-[var(--muted)]">
              Chưa có cảnh báo. Sẽ tự hiện khi có nhân sự vượt ngưỡng giờ.
            </div>
          </section>

          {/* System notifications */}
          <section>
            <p className="text-xs font-bold uppercase tracking-wider text-[var(--muted-foreground)] mb-2">
              🔔 Hệ thống
            </p>
            <div className="space-y-1">
              <div className="flex items-start gap-2 p-3 rounded-lg border border-[var(--border)]">
                <CheckCircle2 className="h-4 w-4 text-[var(--success)] shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="text-xs">Realtime đã kết nối</p>
                  <p className="text-[10px] text-[var(--muted-foreground)]">Vừa xong</p>
                </div>
              </div>
            </div>
          </section>

          {(pendingQ.data?.length || 0) === 0 && (
            <EmptyState
              icon={<Bell className="h-10 w-10" />}
              title="Tất cả đã được xem"
              description="Khi có hoạt động mới, sẽ hiện ở đây."
            />
          )}
        </div>

        <footer className="border-t border-[var(--border)] p-4 flex justify-between items-center">
          <Button variant="ghost" size="sm" disabled>
            Đánh dấu đã đọc
          </Button>
          <Button size="sm" onClick={() => { navigate('/audit-log'); onClose(); }}>
            Xem tất cả
          </Button>
        </footer>
      </aside>
    </>
  );
}
