import { useState, useEffect, useRef, useMemo } from 'react';
import { Bell, Sun, Moon, ChevronDown, Menu, LogOut, User as UserIcon, Settings, Calendar } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext';
import { useAuth } from '../../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import { cn } from '../../lib/cn';
import { Avatar } from '../ui/avatar';

export type Period = 'day' | 'week' | 'month' | 'quarter' | 'custom';

export interface CustomRange {
  from: string;  // ISO YYYY-MM-DD
  to: string;    // ISO YYYY-MM-DD
}

export interface PeriodState {
  period: Period;
  customRange: CustomRange | null;
}

interface TopbarProps {
  onToggleSidebar: () => void;
  period: Period;
  onPeriodChange: (p: Period) => void;
  customRange: CustomRange | null;
  onCustomRangeChange: (r: CustomRange | null) => void;
  pendingCount?: number;
  onOpenNotifications: () => void;
}

const PERIODS: { key: Exclude<Period, 'custom'>; label: string }[] = [
  { key: 'day', label: 'Hôm nay' },
  { key: 'week', label: 'Tuần' },
  { key: 'month', label: 'Tháng' },
  { key: 'quarter', label: 'Quý' },
];

function formatVnDate(iso: string): string {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  if (!y || !m || !d) return '';
  return `${d}/${m}`;
}

export function Topbar({
  onToggleSidebar,
  period,
  onPeriodChange,
  customRange,
  onCustomRangeChange,
  pendingCount = 0,
  onOpenNotifications,
}: TopbarProps) {
  const { theme, toggleTheme } = useTheme();
  const { me, guilds, currentGuildId, setCurrentGuildId, currentGuild, logout } = useAuth();
  const navigate = useNavigate();
  const [guildMenuOpen, setGuildMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const guildMenuRef = useRef<HTMLDivElement>(null);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const customRef = useRef<HTMLDivElement>(null);

  // Popover form state — chỉ commit khi user click "Áp dụng"
  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const yesterday = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return d.toISOString().slice(0, 10);
  }, []);
  const [draftFrom, setDraftFrom] = useState<string>(customRange?.from || yesterday);
  const [draftTo, setDraftTo] = useState<string>(customRange?.to || today);

  // Sync draft khi customRange thay đổi từ ngoài (localStorage restore)
  useEffect(() => {
    if (customRange) {
      setDraftFrom(customRange.from);
      setDraftTo(customRange.to);
    }
  }, [customRange]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (guildMenuRef.current && !guildMenuRef.current.contains(e.target as Node)) {
        setGuildMenuOpen(false);
      }
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
      if (customRef.current && !customRef.current.contains(e.target as Node)) {
        setCustomOpen(false);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const draftError = useMemo(() => {
    if (!draftFrom || !draftTo) return 'Cần nhập cả 2 ngày';
    if (draftFrom > draftTo) return 'Từ ngày phải ≤ đến ngày';
    if (draftTo > today) return 'Đến ngày không được vượt hôm nay';
    return null;
  }, [draftFrom, draftTo, today]);

  const applyCustom = () => {
    if (draftError) return;
    onCustomRangeChange({ from: draftFrom, to: draftTo });
    onPeriodChange('custom');
    setCustomOpen(false);
  };

  const cancelCustom = () => {
    setDraftFrom(customRange?.from || yesterday);
    setDraftTo(customRange?.to || today);
    setCustomOpen(false);
  };

  const customChipLabel = period === 'custom' && customRange
    ? `${formatVnDate(customRange.from)} → ${formatVnDate(customRange.to)}`
    : 'Tùy chỉnh';

  return (
    <header className="sticky top-0 z-20 h-16 bg-[var(--card)] border-b border-[var(--border)] flex items-center px-6 gap-4">
      <button
        onClick={onToggleSidebar}
        className="md:hidden p-2 hover:bg-[var(--muted)] rounded-md"
        aria-label="Mở menu"
      >
        <Menu className="h-5 w-5" />
      </button>

      {/* Guild Selector */}
      <div ref={guildMenuRef} className="relative">
        <button
          onClick={() => setGuildMenuOpen(o => !o)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-[var(--border)] hover:bg-[var(--muted)] transition-colors min-w-[200px]"
        >
          <span className="text-base">🏥</span>
          <span className="text-sm font-medium truncate flex-1 text-left">
            {currentGuild ? currentGuild.name : 'Chọn server...'}
          </span>
          <ChevronDown className="h-4 w-4 text-[var(--muted-foreground)]" />
        </button>
        {guildMenuOpen && (
          <div className="absolute top-full left-0 mt-1 w-[280px] bg-[var(--card)] border border-[var(--border)] rounded-lg shadow-lg p-1 z-50">
            <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-foreground)] px-3 py-1.5">
              Discord Server
            </p>
            {guilds.length === 0 && (
              <p className="text-xs text-[var(--muted-foreground)] px-3 py-2">Không có server nào</p>
            )}
            {guilds.map((g) => (
              <button
                key={g.id}
                onClick={() => {
                  setCurrentGuildId(g.id);
                  setGuildMenuOpen(false);
                }}
                className={cn(
                  'w-full text-left px-3 py-2 rounded-md text-sm hover:bg-[var(--muted)] flex items-center gap-2',
                  currentGuildId === g.id && 'bg-[var(--primary)]/10 text-[var(--primary)]',
                )}
              >
                <span>🏥</span>
                <span className="truncate flex-1">{g.name}</span>
                <span className="text-[9px] uppercase tracking-wider text-[var(--muted-foreground)]">
                  {g.role}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="h-5 w-px bg-[var(--border)] hidden lg:block" />

      {/* Period switcher */}
      <div className="hidden lg:flex items-center gap-0.5 bg-[var(--muted)] rounded-lg p-0.5">
        {PERIODS.map((p) => (
          <button
            key={p.key}
            onClick={() => {
              onPeriodChange(p.key);
              onCustomRangeChange(null);
            }}
            className={cn(
              'px-3 py-1 rounded-md text-xs font-medium transition-all',
              period === p.key
                ? 'bg-[var(--card)] text-[var(--foreground)] shadow-sm'
                : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]',
            )}
          >
            {p.label}
          </button>
        ))}

        {/* Custom date chip */}
        <div ref={customRef} className="relative">
          <button
            onClick={() => setCustomOpen(o => !o)}
            className={cn(
              'px-3 py-1 rounded-md text-xs font-medium transition-all flex items-center gap-1',
              period === 'custom'
                ? 'bg-[var(--card)] text-[var(--foreground)] shadow-sm'
                : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]',
            )}
            title={period === 'custom' && customRange
              ? `Từ ${customRange.from} đến ${customRange.to}`
              : 'Chọn khoảng ngày tùy ý'}
          >
            <Calendar className="h-3.5 w-3.5" />
            {customChipLabel}
          </button>
          {customOpen && (
            <div className="absolute top-full right-0 mt-1 w-[280px] bg-[var(--card)] border border-[var(--border)] rounded-lg shadow-lg p-3 z-50">
              <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-foreground)] mb-2">
                Khoảng ngày tùy chỉnh
              </p>
              <div className="space-y-2">
                <div>
                  <label className="text-[10px] text-[var(--muted-foreground)] block mb-1">Từ ngày</label>
                  <input
                    type="date"
                    value={draftFrom}
                    onChange={(e) => setDraftFrom(e.target.value)}
                    max={draftTo || today}
                    className="w-full px-2 py-1.5 text-xs rounded border border-[var(--border)] bg-[var(--background)] text-[var(--foreground)]"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-[var(--muted-foreground)] block mb-1">Đến ngày</label>
                  <input
                    type="date"
                    value={draftTo}
                    onChange={(e) => setDraftTo(e.target.value)}
                    min={draftFrom || undefined}
                    max={today}
                    className="w-full px-2 py-1.5 text-xs rounded border border-[var(--border)] bg-[var(--background)] text-[var(--foreground)]"
                  />
                </div>
              </div>
              {draftError && (
                <p className="text-[10px] text-[var(--destructive)] mt-2">⚠️ {draftError}</p>
              )}
              <div className="flex gap-2 mt-3">
                <button
                  onClick={cancelCustom}
                  className="flex-1 px-3 py-1.5 text-xs rounded border border-[var(--border)] hover:bg-[var(--muted)]"
                >
                  Hủy
                </button>
                <button
                  onClick={applyCustom}
                  disabled={!!draftError}
                  className={cn(
                    'flex-1 px-3 py-1.5 text-xs rounded font-medium',
                    draftError
                      ? 'bg-[var(--muted)] text-[var(--muted-foreground)] cursor-not-allowed'
                      : 'bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90',
                  )}
                >
                  Áp dụng
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="flex-1" />

      {/* Right side */}
      <div className="flex items-center gap-1.5">
        <button
          onClick={onOpenNotifications}
          className="relative p-2 hover:bg-[var(--muted)] rounded-lg transition-colors"
          aria-label="Thông báo"
        >
          <Bell className="h-5 w-5" />
          {pendingCount > 0 && (
            <span className="absolute top-1 right-1 min-w-[16px] h-[16px] px-1 bg-[var(--destructive)] text-white text-[9px] font-bold rounded-full flex items-center justify-center">
              {pendingCount > 99 ? '99+' : pendingCount}
            </span>
          )}
        </button>

        <button
          onClick={toggleTheme}
          className="p-2 hover:bg-[var(--muted)] rounded-lg transition-colors"
          aria-label="Đổi chế độ"
        >
          {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
        </button>

        <div className="h-5 w-px bg-[var(--border)] mx-1" />

        {/* User menu */}
        <div ref={userMenuRef} className="relative">
          <button
            onClick={() => setUserMenuOpen(o => !o)}
            className="flex items-center gap-2 p-1 pl-2 rounded-lg hover:bg-[var(--muted)] transition-colors"
          >
            <span className="text-sm font-medium hidden sm:block">
              {me?.global_name || me?.username || 'User'}
            </span>
            <Avatar
              src={me?.avatar_url}
              fallback={me?.username?.[0] || 'U'}
              size={32}
            />
          </button>
          {userMenuOpen && (
            <div className="absolute top-full right-0 mt-1 w-56 bg-[var(--card)] border border-[var(--border)] rounded-lg shadow-lg p-1 z-50">
              <div className="px-3 py-2 border-b border-[var(--border)] mb-1">
                <p className="text-sm font-medium truncate">{me?.global_name || me?.username}</p>
                <p className="text-[10px] font-mono-id text-[var(--muted-foreground)] truncate" title={me?.discord_id}>
                  ID: {me?.discord_id}
                </p>
              </div>
              <button
                onClick={() => { navigate('/settings'); setUserMenuOpen(false); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md hover:bg-[var(--muted)]"
              >
                <Settings className="h-4 w-4" />
                Cài đặt
              </button>
              <button
                onClick={() => { setUserMenuOpen(false); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md hover:bg-[var(--muted)]"
              >
                <UserIcon className="h-4 w-4" />
                Hồ sơ
              </button>
              <div className="my-1 border-t border-[var(--border)]" />
              <button
                onClick={() => { logout(); setUserMenuOpen(false); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md hover:bg-[var(--destructive)]/10 text-[var(--destructive)]"
              >
                <LogOut className="h-4 w-4" />
                Đăng xuất
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
