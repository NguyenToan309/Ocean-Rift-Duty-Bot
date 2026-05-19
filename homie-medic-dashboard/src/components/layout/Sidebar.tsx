import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Stethoscope,
  ClipboardList,
  Calendar,
  FileText,
  DoorOpen,
  Trophy,
  ScrollText,
  Settings as SettingsIcon,
  Cross,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { cn } from '../../lib/cn';
import { Badge } from '../ui/badge';
import { useAuth } from '../../contexts/AuthContext';

const NAV_ITEMS = [
  { path: '/', icon: LayoutDashboard, label: 'Tổng quan', exact: true },
  { path: '/staff', icon: Stethoscope, label: 'Nhân sự', isNew: true },
  { path: '/duty-logs', icon: ClipboardList, label: 'Chấm công' },
  { path: '/schedule', icon: Calendar, label: 'Lịch trực' },
  { path: '/leave-requests', icon: FileText, label: 'Đơn nghỉ', badgeKey: 'pendingLeaves' as const },
  { path: '/resign-requests', icon: DoorOpen, label: 'Đơn xin out' },
  { path: '/rankings', icon: Trophy, label: 'Xếp hạng' },
  { path: '/audit-log', icon: ScrollText, label: 'Audit Log' },
];

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  pendingLeaves?: number;
}

export function Sidebar({ collapsed, onToggleCollapse, pendingLeaves = 0 }: SidebarProps) {
  const { currentGuild } = useAuth();
  const isAdmin = currentGuild?.is_admin || false;

  return (
    <aside
      className={cn(
        'sticky top-0 h-screen flex-shrink-0 bg-[var(--sidebar)] border-r border-[var(--sidebar-border)]',
        'transition-[width] duration-200 flex flex-col z-30',
        collapsed ? 'w-16' : 'w-[260px]',
      )}
    >
      {/* Logo */}
      <div className="h-16 flex items-center px-4 border-b border-[var(--sidebar-border)] gap-3 shrink-0">
        <div className="w-9 h-9 rounded-lg bg-[var(--primary)] text-white flex items-center justify-center shrink-0">
          <Cross className="h-5 w-5" />
        </div>
        {!collapsed && (
          <div className="overflow-hidden">
            <p className="text-sm font-bold tracking-tight truncate">Homie Medic</p>
            <p className="text-[10px] italic text-[var(--muted-foreground)] truncate">Discord Bot Dashboard</p>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const badgeValue = item.badgeKey === 'pendingLeaves' ? pendingLeaves : 0;
          return (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.exact}
              className={({ isActive }) =>
                cn(
                  'group relative flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-[var(--primary)]/10 text-[var(--primary)]'
                    : 'text-[var(--sidebar-foreground)]/70 hover:bg-[var(--sidebar-accent)] hover:text-[var(--sidebar-accent-foreground)]',
                )
              }
              title={collapsed ? item.label : undefined}
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-0.5 bg-[var(--primary)] rounded-r" />
                  )}
                  <Icon className={cn('h-[18px] w-[18px] shrink-0', isActive && 'stroke-[2.5]')} />
                  {!collapsed && (
                    <>
                      <span className="flex-1 truncate">{item.label}</span>
                      {item.isNew && (
                        <Badge variant="success" className="text-[9px] px-1.5 py-0">
                          NEW
                        </Badge>
                      )}
                      {!!badgeValue && badgeValue > 0 && (
                        <Badge variant="destructive" className="text-[10px] px-1.5 py-0 min-w-[20px] justify-center">
                          {badgeValue}
                        </Badge>
                      )}
                    </>
                  )}
                  {collapsed && !!badgeValue && badgeValue > 0 && (
                    <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-[var(--destructive)]" />
                  )}
                </>
              )}
            </NavLink>
          );
        })}

        {/* Admin section */}
        {isAdmin && (
          <>
            <div className="my-3 border-t border-[var(--sidebar-border)]" />
            <NavLink
              to="/settings"
              className={({ isActive }) =>
                cn(
                  'group flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-[var(--primary)]/10 text-[var(--primary)]'
                    : 'text-[var(--sidebar-foreground)]/70 hover:bg-[var(--sidebar-accent)]',
                )
              }
              title={collapsed ? 'Cài đặt' : undefined}
            >
              <SettingsIcon className="h-[18px] w-[18px] shrink-0" />
              {!collapsed && <span className="flex-1 truncate">Cài đặt</span>}
              {!collapsed && (
                <Badge variant="outline" className="text-[9px] px-1.5 py-0">
                  ADMIN
                </Badge>
              )}
            </NavLink>
          </>
        )}
      </nav>

      {/* Collapse button */}
      <button
        onClick={onToggleCollapse}
        className="h-10 flex items-center justify-center gap-2 border-t border-[var(--sidebar-border)] text-[var(--muted-foreground)] hover:bg-[var(--sidebar-accent)] transition-colors text-xs"
      >
        {collapsed ? (
          <ChevronRight className="h-4 w-4" />
        ) : (
          <>
            <ChevronLeft className="h-4 w-4" /> <span>Thu gọn</span>
          </>
        )}
      </button>
    </aside>
  );
}
