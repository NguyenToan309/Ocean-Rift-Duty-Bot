import { useState, useEffect } from 'react';
import { Download, Trophy, TrendingDown, TrendingUp } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useRanking } from '../hooks/useApi';
import { api, formatError } from '../lib/api';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Avatar } from '../components/ui/avatar';
import { Skeleton, EmptyState, DiscordIdChip } from '../components/shared/misc';
import { minutesToHHMM, avatarText } from '../lib/format';
import { useAvatars } from '../contexts/AvatarContext';
import { cn } from '../lib/cn';
import type { Period } from '../components/layout/Topbar';

export function RankingsPage() {
  const { period } = useOutletContext<{ period: Period }>();
  const { currentGuildId } = useAuth();
  const { getAvatar, learnAvatar } = useAvatars();
  const [mode, setMode] = useState<'top' | 'bottom'>('top');

  const rankQ = useRanking(currentGuildId, period, mode, 20);
  const data = rankQ.data || [];

  // Seed avatar cache
  useEffect(() => {
    data.forEach((u: any) => {
      if (u.user_id && u.avatar_url) learnAvatar(String(u.user_id), u.avatar_url, u.username);
    });
  }, [data, learnAvatar]);

  const onExport = async () => {
    if (!currentGuildId) return;
    try {
      const r = await api.exportPrepare(currentGuildId, 'excel', period, { mode: 'ranking' });
      window.open(r.download_url, '_blank');
    } catch (err) {
      alert('Lỗi: ' + formatError(err));
    }
  };

  const maxMin = data[0]?.total_minutes || 1;
  const top3 = data.slice(0, 3);

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Trophy className="h-6 w-6 text-[var(--warning)]" />
            Bảng xếp hạng
          </h1>
          <p className="text-sm text-[var(--muted-foreground)] mt-1">
            Ghi nhận nỗ lực của đội ngũ y tế trong kỳ này
          </p>
        </div>
        <Button onClick={onExport}>
          <Download className="h-4 w-4" /> Tải Excel
        </Button>
      </div>

      <div className="flex gap-2">
        <Button
          variant={mode === 'top' ? 'default' : 'outline'}
          onClick={() => setMode('top')}
        >
          🏆 Top 10
        </Button>
        <Button
          variant={mode === 'bottom' ? 'default' : 'outline'}
          onClick={() => setMode('bottom')}
        >
          📉 Bottom 5
        </Button>
      </div>

      {/* Podium for Top */}
      {mode === 'top' && top3.length === 3 && (
        <Card className="p-8 bg-gradient-to-br from-[var(--primary)]/5 to-[var(--accent)]/5">
          <div className="flex items-end justify-center gap-4 max-w-2xl mx-auto">
            <PodiumStep place={2} medal="🥈" data={top3[1]} height={120} avatarSize={64} />
            <PodiumStep place={1} medal="🥇" data={top3[0]} height={160} avatarSize={80} highlight />
            <PodiumStep place={3} medal="🥉" data={top3[2]} height={100} avatarSize={64} />
          </div>
        </Card>
      )}

      {/* Table */}
      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[var(--muted)]/50 border-b border-[var(--border)]">
            <tr>
              <th className="text-center px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-[var(--muted-foreground)] w-16">Hạng</th>
              <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]">Nhân viên</th>
              <th className="text-right px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]">Tổng giờ</th>
              <th className="text-right px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]">Số ca</th>
              <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-[var(--muted-foreground)] w-1/3 min-w-[180px]">Tiến độ</th>
            </tr>
          </thead>
          <tbody>
            {rankQ.loading && [...Array(5)].map((_, i) => (
              <tr key={i} className="border-b border-[var(--border)]">
                <td colSpan={5} className="p-3"><Skeleton className="h-10 w-full" /></td>
              </tr>
            ))}
            {!rankQ.loading && data.length === 0 && (
              <tr>
                <td colSpan={5}>
                  <EmptyState
                    icon={<Trophy className="h-10 w-10" />}
                    title="Chưa có dữ liệu"
                    description="Bảng xếp hạng sẽ hiện khi có chấm công"
                  />
                </td>
              </tr>
            )}
            {data.map((u: any, i: number) => (
              <tr key={u.user_id || i} className="border-b border-[var(--border)] hover:bg-[var(--muted)]/30 group transition-colors">
                <td className="px-4 py-3 text-center">
                  <span
                    className={cn(
                      'inline-flex items-center justify-center w-9 h-9 rounded-full font-semibold text-sm',
                      mode === 'top' && i < 3
                        ? 'bg-[var(--primary)] text-[var(--primary-foreground)]'
                        : 'bg-[var(--muted)] text-[var(--muted-foreground)]',
                    )}
                  >
                    {i + 1}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    <Avatar src={getAvatar(String(u.user_id || ''))} fallback={avatarText(u.username)} size={36} />
                    <div>
                      <p className="font-medium group-hover:text-[var(--primary)] transition-colors">{u.username}</p>
                      <DiscordIdChip id={String(u.user_id || '')} />
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3 text-right font-bold text-lg">
                  {minutesToHHMM(u.total_minutes)}
                </td>
                <td className="px-4 py-3 text-right text-[var(--muted-foreground)]">
                  {u.session_count}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-[var(--muted)] rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${Math.min(100, (u.total_minutes / maxMin) * 100)}%`,
                          backgroundColor: mode === 'top' ? 'var(--primary)' : 'var(--warning)',
                        }}
                      />
                    </div>
                    <span className="text-xs text-[var(--muted-foreground)] w-10 text-right">
                      {Math.round((u.total_minutes / maxMin) * 100)}%
                    </span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function PodiumStep({ place, medal, data, height, avatarSize, highlight }: any) {
  const { getAvatar } = useAvatars();
  return (
    <div className="flex flex-col items-center flex-1 max-w-[160px]">
      <Card className={cn('p-3 mb-2 w-full text-center', highlight && 'border-2 border-[var(--primary)] shadow-lg')}>
        <div className="text-3xl mb-1">{medal}</div>
        <Avatar
          src={getAvatar(String(data?.user_id || ''))}
          fallback={avatarText(data?.username)}
          size={avatarSize}
          className="mx-auto"
        />
        <p className="font-semibold text-sm mt-2 truncate">{data?.username}</p>
        <p className={cn('text-lg font-bold mt-1', highlight ? 'text-[var(--primary)]' : 'text-[var(--foreground)]')}>
          {minutesToHHMM(data?.total_minutes || 0)}
        </p>
      </Card>
      <div
        className={cn(
          'w-full rounded-t-lg flex items-center justify-center font-bold text-2xl text-white',
          highlight ? 'bg-[var(--primary)]' : 'bg-[var(--muted)] text-[var(--muted-foreground)]',
        )}
        style={{ height }}
      >
        {place}
      </div>
    </div>
  );
}
