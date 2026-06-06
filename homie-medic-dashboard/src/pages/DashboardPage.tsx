import { useEffect } from 'react';
import { useOutletContext, Link } from 'react-router-dom';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import {
  Activity, Clock, Bell, Target, TrendingUp, Users, Trophy, Calendar, ArrowRight,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useOverview, useChart, useRanking, useAttendance, useLeavePending } from '../hooks/useApi';
import { Card } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Avatar } from '../components/ui/avatar';
import { Skeleton, EmptyState, DiscordIdChip } from '../components/shared/misc';
import { greetingByHour, minutesToHHMM, avatarText } from '../lib/format';
import { useAvatars } from '../contexts/AvatarContext';
import type { PeriodState } from '../components/layout/Topbar';
import { cn } from '../lib/cn';

/** YYYY-MM-DD → DD/MM/YYYY (backend get_custom_range format). */
function isoToVnDate(iso: string): string {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  if (!y || !m || !d) return '';
  return `${d}/${m}/${y}`;
}

export function DashboardPage() {
  const { period, customRange } = useOutletContext<PeriodState>();
  const { me, currentGuildId, currentGuild } = useAuth();
  const { getAvatar, learnAvatar } = useAvatars();

  const useCustom = period === 'custom' && !!customRange;
  const startParam = useCustom && customRange ? isoToVnDate(customRange.from) : undefined;
  const endParam = useCustom && customRange ? isoToVnDate(customRange.to) : undefined;

  const overviewQ = useOverview(currentGuildId, period, startParam, endParam);
  const chartQ = useChart(currentGuildId, period, startParam, endParam);
  const topQ = useRanking(currentGuildId, period, 'top', 5, startParam, endParam);
  const attQ = useAttendance(currentGuildId, period, startParam, endParam);
  const pendingQ = useLeavePending(currentGuildId);

  const onDuty = (attQ.data || []).filter((u: any) => u?.total_minutes > 0).slice(0, 5);
  const pendingCount = pendingQ.data?.length || 0;

  // Seed avatar cache từ data fetched (backend đã include avatar_url)
  useEffect(() => {
    (overviewQ.data?.top_users || []).forEach((u: any) => {
      if (u.user_id && u.avatar_url) learnAvatar(String(u.user_id), u.avatar_url, u.username);
    });
    (topQ.data || []).forEach((u: any) => {
      if (u.user_id && u.avatar_url) learnAvatar(String(u.user_id), u.avatar_url, u.username);
    });
    (attQ.data || []).forEach((u: any) => {
      if (u.user_id && u.avatar_url) learnAvatar(String(u.user_id), u.avatar_url, u.username);
    });
    (pendingQ.data || []).forEach((r: any) => {
      if (r.user_id && r.avatar_url) learnAvatar(String(r.user_id), r.avatar_url, r.username);
    });
  }, [overviewQ.data, topQ.data, attQ.data, pendingQ.data, learnAvatar]);

  const stats = [
    {
      label: 'Đang trực',
      value: `${onDuty.length}`,
      suffix: ' người',
      icon: Activity,
      color: 'text-[var(--success)]',
      pulse: true,
      bg: 'bg-[var(--success)]/10',
    },
    {
      label: 'Tổng giờ',
      value: minutesToHHMM(overviewQ.data?.total_minutes || 0, true),
      icon: Clock,
      color: 'text-[var(--info)]',
      bg: 'bg-[var(--info)]/10',
      trend: '+12%',
    },
    {
      label: 'Đơn chờ duyệt',
      value: `${pendingCount}`,
      icon: Bell,
      color: 'text-[var(--warning)]',
      bg: 'bg-[var(--warning)]/10',
      accent: true,
    },
    {
      label: 'Tỷ lệ chuyên cần',
      value: overviewQ.data?.compliance_rate != null ? `${Math.round(overviewQ.data.compliance_rate)}%` : '—',
      icon: Target,
      color: 'text-[var(--primary)]',
      bg: 'bg-[var(--primary)]/10',
    },
  ];

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Welcome banner */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            Chào {greetingByHour()}, {me?.global_name || me?.username || 'bạn'} 👨‍⚕️
          </h1>
          <p className="text-sm text-[var(--muted-foreground)] mt-1">
            {new Date().toLocaleDateString('vi-VN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
            {currentGuild && <> · 🏥 {currentGuild.name}</>}
          </p>
        </div>
        <Badge variant="outline" className="gap-2">
          <span className="h-2 w-2 rounded-full bg-[var(--success)] animate-pulse" />
          Hệ thống đang hoạt động
        </Badge>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((s, i) => {
          const Icon = s.icon;
          return (
            <Card key={i} className={cn('p-5 hover:-translate-y-px transition-transform', s.accent && 'border-l-4 border-l-[var(--warning)]')}>
              <div className="flex items-start justify-between mb-3">
                <div className={cn('p-2 rounded-lg', s.bg)}>
                  <Icon className={cn('h-5 w-5', s.color)} />
                </div>
                {s.trend && (
                  <span className="text-xs font-semibold text-[var(--success)] flex items-center gap-0.5">
                    <TrendingUp className="h-3 w-3" /> {s.trend}
                  </span>
                )}
                {s.pulse && (
                  <span className="h-2 w-2 rounded-full bg-[var(--success)] animate-pulse mt-2" />
                )}
              </div>
              <p className="text-xs font-medium text-[var(--muted-foreground)] uppercase tracking-wider mb-1">
                {s.label}
              </p>
              <p className="text-2xl font-bold tracking-tight">
                {overviewQ.loading ? <Skeleton className="h-7 w-16" /> : (
                  <>{s.value}<span className="text-sm font-normal text-[var(--muted-foreground)]">{s.suffix}</span></>
                )}
              </p>
            </Card>
          );
        })}
      </div>

      {/* Chart + Right column */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Chart */}
        <Card className="lg:col-span-2 p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-semibold">Giờ trực theo ngày</h3>
              <p className="text-xs text-[var(--muted-foreground)] mt-0.5">Tổng giờ chấm công trong {period === 'week' ? 'tuần' : period === 'month' ? 'tháng' : 'kỳ'} này</p>
            </div>
          </div>
          <div className="h-72">
            {chartQ.loading ? (
              <Skeleton className="w-full h-full" />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartQ.data || []}>
                  <defs>
                    <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                  <XAxis
                    dataKey="date"
                    stroke="var(--muted-foreground)"
                    style={{ fontSize: 12 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    stroke="var(--muted-foreground)"
                    style={{ fontSize: 12 }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v: number) => `${Math.round(v / 60)}h`}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--card)',
                      border: '1px solid var(--border)',
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    formatter={(v: any) => [minutesToHHMM(v), 'Tổng giờ']}
                    labelFormatter={(l) => `Ngày ${l}`}
                  />
                  <Area
                    type="monotone"
                    dataKey="value"
                    name="Tổng giờ"
                    stroke="var(--chart-1)"
                    strokeWidth={2}
                    fill="url(#chartGradient)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>

        {/* Right column */}
        <div className="space-y-4">
          <Card className="p-5">
            <div className="flex items-center justify-between mb-3">
              <h4 className="font-semibold flex items-center gap-2">
                <Users className="h-4 w-4 text-[var(--primary)]" />
                Đang trực
              </h4>
              <Badge variant="success" className="text-[10px]">{onDuty.length} người</Badge>
            </div>
            <div className="space-y-2">
              {onDuty.length === 0 && (
                <p className="text-xs text-[var(--muted-foreground)] italic py-3">Hiện chưa có ai đang trực</p>
              )}
              {onDuty.map((u: any, i: number) => (
                <div key={u.user_id || i} className="flex items-center gap-2.5">
                  <Avatar src={getAvatar(String(u.user_id || ''))} fallback={avatarText(u.username)} size={32} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{u.username}</p>
                    <DiscordIdChip id={String(u.user_id || '')} />
                  </div>
                  <span className="h-2 w-2 rounded-full bg-[var(--success)] animate-pulse" />
                </div>
              ))}
            </div>
          </Card>

          <Card className="p-5">
            <h4 className="font-semibold mb-3 flex items-center gap-2">
              <Calendar className="h-4 w-4 text-[var(--info)]" />
              Sự kiện sắp tới
            </h4>
            <div className="space-y-2">
              {(pendingQ.data || []).slice(0, 3).map((req: any) => (
                <div key={req.id} className="flex gap-3 p-2 rounded-lg hover:bg-[var(--muted)]">
                  <div className="w-0.5 bg-[var(--info)] rounded-full" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium truncate">{req.username}</p>
                    <p className="text-xs text-[var(--muted-foreground)]">{req.type_label} · {req.start_date}</p>
                  </div>
                </div>
              ))}
              {(!pendingQ.data || pendingQ.data.length === 0) && (
                <p className="text-xs text-[var(--muted-foreground)] italic">Không có sự kiện</p>
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* Top 5 leaderboard */}
      <Card className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold flex items-center gap-2">
            <Trophy className="h-5 w-5 text-[var(--warning)]" />
            Top 5 nhân viên xuất sắc
          </h3>
          <Link to="/rankings" className="text-xs text-[var(--primary)] hover:underline flex items-center gap-1">
            Xem tất cả <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
        {topQ.loading ? (
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
          </div>
        ) : (topQ.data || []).length === 0 ? (
          <EmptyState
            icon={<Trophy className="h-10 w-10" />}
            title="Chưa có dữ liệu"
            description="Bảng xếp hạng sẽ hiển thị khi có nhân viên chấm công"
          />
        ) : (
          <div className="space-y-2">
            {(topQ.data || []).slice(0, 5).map((u: any, i: number) => (
              <div key={u.user_id || i} className="flex items-center gap-3 p-2 rounded-lg hover:bg-[var(--muted)] transition-colors">
                <span className="w-8 text-center text-lg">
                  {i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : <span className="text-sm text-[var(--muted-foreground)]">{i + 1}</span>}
                </span>
                <Avatar src={getAvatar(String(u.user_id || ''))} fallback={avatarText(u.username)} size={32} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{u.username}</p>
                  <div className="w-full h-1.5 bg-[var(--muted)] rounded-full mt-1 overflow-hidden">
                    <div
                      className="h-full bg-[var(--primary)] rounded-full transition-all"
                      style={{ width: `${Math.min(100, (u.total_minutes / (topQ.data?.[0]?.total_minutes || 1)) * 100)}%` }}
                    />
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-sm font-bold">{minutesToHHMM(u.total_minutes)}</p>
                  <p className="text-[10px] text-[var(--muted-foreground)]">{u.session_count} ca</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
