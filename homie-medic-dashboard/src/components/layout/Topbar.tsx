import { useState, useEffect, useRef } from 'react';
import { Bell, Sun, Moon, ChevronDown, Menu, LogOut, User as UserIcon, Settings } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext';
import { useAuth } from '../../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import { cn } from '../../lib/cn';
import { Avatar } from '../ui/avatar';

export type Period = 'day' | 'week' | 'month' | 'quarter';

interface TopbarProps {
  onToggleSidebar: () => void;
  period: Period;
  onPeriodChange: (p: Period) => void;
  pendingCount?: number;
  onOpenNotifications: () => void;
}

const PERIODS: { key: Period; label: string }[] = [
  { key: 'day', label: 'Hôm nay' },
  { key: 'week', label: 'Tuần' },
  { key: 'month', label: 'Tháng' },
  { key: 'quarter', label: 'Quý' },
];

export function Topbar({ onToggleSidebar, period, onPeriodChange, pendingCount = 0, onOpenNotifications }: TopbarProps) {
  const { theme, toggleTheme } = useTheme();
  const { me, guilds, currentGuildId, setCurrentGuildId, currentGuild, logout } = useAuth();
  const navigate = useNavigate();
  const [guildMenuOpen, setGuildMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const guildMenuRef = useRef<HTMLDivElement>(null);
  const userMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (guildMenuRef.current && !guildMenuRef.current.contains(e.target as Node)) {
        setGuildMenuOpen(false);
      }
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

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
            onClick={() => onPeriodChange(p.key)}
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
