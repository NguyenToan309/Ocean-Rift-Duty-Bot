import { useState, useCallback, useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Topbar, type Period, type CustomRange, type PeriodState } from './Topbar';
import { NotificationCenter } from './NotificationCenter';
import { RealtimeIndicator } from '../shared/misc';
import { PromptNoteHost } from '../shared/PromptNoteHost';
import { useAuth } from '../../contexts/AuthContext';
import { useLeavePending } from '../../hooks/useApi';

const LS_KEY = 'duty:period_state_v2';

interface StoredState {
  period: Period;
  customRange: CustomRange | null;
}

function loadStored(): StoredState {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return { period: 'month', customRange: null };
    const parsed = JSON.parse(raw);
    const validPeriods: Period[] = ['day', 'week', 'month', 'quarter', 'custom'];
    if (!validPeriods.includes(parsed.period)) return { period: 'month', customRange: null };
    if (parsed.period === 'custom' && (!parsed.customRange?.from || !parsed.customRange?.to)) {
      return { period: 'month', customRange: null };
    }
    return {
      period: parsed.period,
      customRange: parsed.customRange || null,
    };
  } catch {
    return { period: 'month', customRange: null };
  }
}

export function RootLayout() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const initial = loadStored();
  const [period, setPeriod] = useState<Period>(initial.period);
  const [customRange, setCustomRange] = useState<CustomRange | null>(initial.customRange);
  const [notifOpen, setNotifOpen] = useState(false);
  const { currentGuildId } = useAuth();

  // Persist
  useEffect(() => {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({ period, customRange }));
    } catch {
      // ignore quota errors
    }
  }, [period, customRange]);

  const pendingLeavesQ = useLeavePending(currentGuildId);
  const pendingCount = pendingLeavesQ.data?.length || 0;

  const onToggleSidebar = useCallback(() => setSidebarCollapsed(s => !s), []);

  const outletState: PeriodState = { period, customRange };

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
          customRange={customRange}
          onCustomRangeChange={setCustomRange}
          pendingCount={pendingCount}
          onOpenNotifications={() => setNotifOpen(true)}
        />

        <main className="flex-1 p-6 lg:p-8 overflow-x-hidden">
          <Outlet context={outletState} />
        </main>
      </div>

      <NotificationCenter
        open={notifOpen}
        onClose={() => setNotifOpen(false)}
        pendingCount={pendingCount}
      />

      <RealtimeIndicator state="connected" />

      <PromptNoteHost />
    </div>
  );
}
