import { createBrowserRouter, Navigate } from 'react-router-dom';
import { RootLayout } from './components/layout/RootLayout';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { StaffPage } from './pages/StaffPage';
import { DutyLogsPage } from './pages/DutyLogsPage';
import { SchedulePage } from './pages/SchedulePage';
import { LeaveRequestsPage } from './pages/LeaveRequestsPage';
import { ResignRequestsPage } from './pages/ResignRequestsPage';
import { RankingsPage } from './pages/RankingsPage';
import { AuditLogPage } from './pages/AuditLogPage';
import { SettingsPage } from './pages/SettingsPage';
import { NotFoundPage, ForbiddenPage, ServerErrorPage } from './pages/ErrorPages';
import { useAuth } from './contexts/AuthContext';
import type { ReactNode } from 'react';

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  if (state === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-sm text-[var(--muted-foreground)]">Đang tải...</div>
      </div>
    );
  }
  if (state === 'anon' || state === 'need_2fa') {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export const router = createBrowserRouter([
  { path: '/login', Component: LoginPage },
  { path: '/403', Component: ForbiddenPage },
  { path: '/500', Component: ServerErrorPage },
  {
    path: '/',
    element: <ProtectedRoute><RootLayout /></ProtectedRoute>,
    errorElement: <ServerErrorPage />,
    children: [
      { index: true, Component: DashboardPage },
      { path: 'staff', Component: StaffPage },
      { path: 'duty-logs', Component: DutyLogsPage },
      { path: 'schedule', Component: SchedulePage },
      { path: 'leave-requests', Component: LeaveRequestsPage },
      { path: 'resign-requests', Component: ResignRequestsPage },
      { path: 'rankings', Component: RankingsPage },
      { path: 'audit-log', Component: AuditLogPage },
      { path: 'settings', Component: SettingsPage },
    ],
  },
  { path: '*', Component: NotFoundPage },
]);
