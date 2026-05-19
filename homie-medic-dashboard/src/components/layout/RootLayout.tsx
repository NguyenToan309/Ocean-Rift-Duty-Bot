import { useState, useCallback } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Topbar, type Period } from './Topbar';
import { NotificationCenter } from './NotificationCenter';
import { RealtimeIndicator } from '../shared/misc';
import { useAuth } from '../../contexts/AuthContext';
import { useLeavePending } from '../../hooks/useApi';

export function RootLayout() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  // Default 'month' để user thấy data ngay khi vào (tránh edge case đầu tuần)
  const [period, setPeriod] = useState<Period>('month');
  const [notifOpen, setNotifOpen] = useState(false);
  const { currentGuildId } = useAuth();

  const pendingLeavesQ = useLeavePending(currentGuildId);
  const pendingCount = pendingLeavesQ.data?.length || 0;

  const onToggleSidebar = useCallback(() => setSidebarCollapsed(s => !s), []);

  return (
    <div className="flex min-h-screen bg-[var(--background)] text-[var(--foreground)]">
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggleCollapse={onToggleSidebar}
        pendingLeaves={pendingCount}
      />

      <div className="flex-1 flex flex-col min-w-0">
        <Topbar
          onToggleSidebar={onToggleSidebar}
          period={period}
          onPeriodChange={setPeriod}
          pendingCount={pendingCount}
          onOpenNotifications={() => setNotifOpen(true)}
        />

        <main className="flex-1 p-6 lg:p-8 overflow-x-hidden">
          <Outlet context={{ period }} />
        </main>
      </div>

      <NotificationCenter
        open={notifOpen}
        onClose={() => setNotifOpen(false)}
        pendingCount={pendingCount}
      />

      <RealtimeIndicator state="connected" />
    </div>
  );
}
