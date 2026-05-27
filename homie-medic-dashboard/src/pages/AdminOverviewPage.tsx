/**
 * AdminOverviewPage.tsx — Trang bot owner xem installations + authorizations.
 *
 * Truy cập:
 *  - Backend dependency require_bot_owner đã enforce (settings.BOT_OWNER_IDS).
 *  - Frontend ẩn link nếu me.is_bot_owner === false (xem layout).
 *
 * 3 phần:
 *  1. Summary cards (8 metric)
 *  2. Installations table: bot đang ở guild nào, owner ai, setup status, duty stats
 *  3. Authorizations table: ai đã OAuth2 vào web, 2FA, last login, IP masked
 */
import { useEffect, useMemo, useState } from 'react';
import { api, type AdminOverview, type AdminInstallation, type AdminAuthorization, formatError } from '../lib/api';

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('vi-VN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function relativeTime(iso: string | null): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return iso;
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s trước`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} phút trước`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} giờ trước`;
  const d = Math.floor(h / 24);
  return `${d} ngày trước`;
}

export function AdminOverviewPage() {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [installSearch, setInstallSearch] = useState('');
  const [authSearch, setAuthSearch] = useState('');

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.adminOverview();
      setData(r);
    } catch (e) {
      setError(formatError(e));
    } finally {
      setLoading(false);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      await api.adminRefresh();
      const r = await api.adminOverview();
      setData(r);
    } catch (e) {
      setError(formatError(e));
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const filteredInstalls = useMemo<AdminInstallation[]>(() => {
    if (!data) return [];
    if (!installSearch.trim()) return data.installations;
    const q = installSearch.toLowerCase();
    return data.installations.filter(
      (i) =>
        i.guild_name.toLowerCase().includes(q) ||
        i.guild_id.includes(q) ||
        (i.owner?.username || '').toLowerCase().includes(q),
    );
  }, [data, installSearch]);

  const filteredAuths = useMemo<AdminAuthorization[]>(() => {
    if (!data) return [];
    if (!authSearch.trim()) return data.authorizations;
    const q = authSearch.toLowerCase();
    return data.authorizations.filter(
      (a) => a.username.toLowerCase().includes(q) || a.discord_id.includes(q),
    );
  }, [data, authSearch]);

  if (loading && !data) {
    return (
      <div className="p-6">
        <div className="text-sm text-[var(--muted-foreground)]">Đang tải dữ liệu admin overview...</div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="p-6">
        <div className="rounded-md border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
          <strong>Lỗi:</strong> {error}
        </div>
        <button
          onClick={load}
          className="mt-4 rounded-md border border-[var(--border)] px-3 py-1 text-sm hover:bg-[var(--card)]"
        >
          Thử lại
        </button>
      </div>
    );
  }

  if (!data) return null;

  const cards: Array<{ label: string; value: number | string; hint?: string }> = [
    { label: 'Tổng server', value: data.totals.total_installs },
    { label: 'Đã setup', value: data.totals.configured, hint: `${data.totals.pending} chưa` },
    { label: 'Chưa setup', value: data.totals.pending },
    { label: 'Tổng user OAuth2', value: data.totals.total_authorizations },
    { label: 'Có 2FA', value: data.totals.with_2fa },
    { label: 'Active 7 ngày', value: data.totals.active_last_7d },
    { label: 'Tổng duty log', value: data.totals.total_duty_logs.toLocaleString('vi-VN') },
    { label: 'Unique users (toàn hệ thống)', value: data.totals.unique_users_global },
  ];

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Admin Overview</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Cập nhật {relativeTime(data.fetched_at)}
            {data.cache_hit && (
              <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-blue-500/20 px-2 py-0.5 text-xs text-blue-300">
                cached
              </span>
            )}
          </p>
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--card)] disabled:opacity-50"
        >
          {refreshing ? 'Đang refresh...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-yellow-500/40 bg-yellow-500/10 p-3 text-sm text-yellow-300">
          {error}
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {cards.map((c) => (
          <div
            key={c.label}
            className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3"
          >
            <div className="text-xs text-[var(--muted-foreground)]">{c.label}</div>
            <div className="mt-1 text-2xl font-semibold">{c.value}</div>
            {c.hint && <div className="text-xs text-[var(--muted-foreground)]">{c.hint}</div>}
          </div>
        ))}
      </div>

      {/* Installations table */}
      <div className="rounded-lg border border-[var(--border)]">
        <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
          <h2 className="text-lg font-semibold">Servers cài bot ({data.installations.length})</h2>
          <input
            type="text"
            value={installSearch}
            onChange={(e) => setInstallSearch(e.target.value)}
            placeholder="Tìm theo tên / ID / owner..."
            className="rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-sm"
          />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--card)] text-left">
                <th className="px-3 py-2 font-medium">Server</th>
                <th className="px-3 py-2 font-medium">ID</th>
                <th className="px-3 py-2 font-medium">Members</th>
                <th className="px-3 py-2 font-medium">Owner</th>
                <th className="px-3 py-2 font-medium">Inviter</th>
                <th className="px-3 py-2 font-medium">Setup</th>
                <th className="px-3 py-2 font-medium">Duty logs</th>
                <th className="px-3 py-2 font-medium">Bot joined</th>
              </tr>
            </thead>
            <tbody>
              {filteredInstalls.map((i) => (
                <tr key={i.guild_id} className="border-b border-[var(--border)]">
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      {i.icon_url ? (
                        <img src={i.icon_url} alt="" className="h-6 w-6 rounded-full" />
                      ) : (
                        <div className="h-6 w-6 rounded-full bg-[var(--muted)]" />
                      )}
                      <span>{i.guild_name}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{i.guild_id}</td>
                  <td className="px-3 py-2">{i.member_count?.toLocaleString('vi-VN') ?? '—'}</td>
                  <td className="px-3 py-2">
                    {i.owner ? (
                      <span className="flex items-center gap-1">
                        {i.owner.avatar_url && (
                          <img src={i.owner.avatar_url} alt="" className="h-4 w-4 rounded-full" />
                        )}
                        {i.owner.username}
                      </span>
                    ) : (
                      <span className="text-[var(--muted-foreground)]">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {i.inviter ? (
                      i.inviter.username
                    ) : (
                      <span className="text-xs text-[var(--muted-foreground)]">(không xác định)</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {i.setup_status === 'configured' ? (
                      <span className="inline-flex items-center rounded-full bg-green-500/20 px-2 py-0.5 text-xs text-green-300">
                        ✓ configured
                      </span>
                    ) : (
                      <span className="inline-flex items-center rounded-full bg-gray-500/20 px-2 py-0.5 text-xs text-gray-400">
                        pending
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {i.duty_log_count.toLocaleString('vi-VN')}
                    {i.last_duty_log_at && (
                      <span className="ml-1 text-xs text-[var(--muted-foreground)]">
                        ({relativeTime(i.last_duty_log_at)})
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs">{formatDate(i.bot_joined_at)}</td>
                </tr>
              ))}
              {filteredInstalls.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-6 text-center text-sm text-[var(--muted-foreground)]">
                    Không có server nào khớp.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Authorizations table */}
      <div className="rounded-lg border border-[var(--border)]">
        <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
          <h2 className="text-lg font-semibold">User đã OAuth2 ({data.authorizations.length})</h2>
          <input
            type="text"
            value={authSearch}
            onChange={(e) => setAuthSearch(e.target.value)}
            placeholder="Tìm theo username / ID..."
            className="rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-sm"
          />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--card)] text-left">
                <th className="px-3 py-2 font-medium">User</th>
                <th className="px-3 py-2 font-medium">ID</th>
                <th className="px-3 py-2 font-medium">2FA</th>
                <th className="px-3 py-2 font-medium">Last login</th>
                <th className="px-3 py-2 font-medium">IP</th>
                <th className="px-3 py-2 font-medium">Failed</th>
                <th className="px-3 py-2 font-medium">Total logins</th>
                <th className="px-3 py-2 font-medium">First seen</th>
              </tr>
            </thead>
            <tbody>
              {filteredAuths.map((a) => {
                const locked = a.locked_until && new Date(a.locked_until) > new Date();
                return (
                  <tr
                    key={a.discord_id}
                    className={`border-b border-[var(--border)] ${locked ? 'bg-red-500/10' : ''}`}
                  >
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        {a.avatar_url ? (
                          <img src={a.avatar_url} alt="" className="h-6 w-6 rounded-full" />
                        ) : (
                          <div className="h-6 w-6 rounded-full bg-[var(--muted)]" />
                        )}
                        <span>{a.username}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{a.discord_id}</td>
                    <td className="px-3 py-2">
                      {a.is_2fa_enabled ? (
                        <span className="text-green-400">✓</span>
                      ) : (
                        <span className="text-gray-500">✗</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">{formatDate(a.last_login_at)}</td>
                    <td className="px-3 py-2 font-mono text-xs">{a.last_login_ip || '—'}</td>
                    <td className="px-3 py-2">
                      {a.failed_login_attempts > 0 ? (
                        <span className="text-yellow-400">{a.failed_login_attempts}</span>
                      ) : (
                        '0'
                      )}
                    </td>
                    <td className="px-3 py-2">{a.total_logins}</td>
                    <td className="px-3 py-2 text-xs">{formatDate(a.first_login_at)}</td>
                  </tr>
                );
              })}
              {filteredAuths.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-6 text-center text-sm text-[var(--muted-foreground)]">
                    Không có user nào khớp.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
