import { cn } from '../../lib/cn';
import { Inbox, Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('h-4 w-4 animate-spin', className)} />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('skeleton rounded-md', className)} />;
}

export function EmptyState({
  icon = <Inbox className="h-12 w-12" />,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="text-[var(--muted-foreground)] mb-3">{icon}</div>
      <p className="text-base font-semibold mb-1">{title}</p>
      {description && <p className="text-sm text-[var(--muted-foreground)] max-w-md">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/**
 * Hiển thị Discord User ID dạng mono nhỏ — giữ full string 19-digit BigInt.
 */
export function DiscordIdChip({ id }: { id: string }) {
  if (!id) return null;
  return (
    <span
      className="font-mono-id text-[10px] text-[var(--muted-foreground)] tracking-tight"
      title={id}
    >
      ID: {id}
    </span>
  );
}

/**
 * Realtime status indicator (bottom-right floating pill).
 */
export function RealtimeIndicator({ state }: { state: 'connected' | 'connecting' | 'offline' }) {
  const config = {
    connected: { color: 'bg-[var(--success)]', label: 'Realtime: Đã kết nối', pulse: true },
    connecting: { color: 'bg-[var(--warning)]', label: 'Realtime: Đang kết nối...', pulse: true },
    offline: { color: 'bg-[var(--destructive)]', label: 'Realtime: Mất kết nối', pulse: false },
  }[state];

  return (
    <div className="fixed bottom-4 right-4 z-40 flex items-center gap-2 rounded-full bg-[var(--card)] border border-[var(--border)] px-3 py-1.5 shadow-md text-xs">
      <span className={cn('h-2 w-2 rounded-full', config.color, config.pulse && 'animate-pulse')} />
      <span className="font-medium">{config.label}</span>
    </div>
  );
}
