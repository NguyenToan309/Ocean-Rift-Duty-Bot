# Homie Medic — React Dashboard

SPA tiền tuyến (frontend) cho Discord bot Homie Medic. Cấp tin sống động cho
staff/lãnh đạo y khoa: theo dõi chấm công, lịch trực, đơn nghỉ, audit.

Build bằng **React 19 + TypeScript + Vite + Tailwind 4 + Recharts + motion**.
Kết nối backend FastAPI (`web/main.py`) qua REST API + WebSocket.

---

## 📦 Cấu trúc

```
homie-medic-dashboard/
├── src/
│   ├── main.tsx                # Entry point
│   ├── index.css               # Tailwind import + design tokens
│   ├── App.tsx                 # Toàn bộ UI (auth + 7 sections)
│   └── lib/
│       ├── api.ts              # Typed fetch client + endpoints
│       ├── auth.ts             # OAuth2 / 2FA helpers
│       ├── format.ts           # Pure formatting (datetime, avatar, period…)
│       └── hooks.ts            # useAsync, useOverview, useRealtime, useMutation
├── vite.config.ts              # Dev proxy: /api /auth /ws → FastAPI :8000
├── package.json
└── tsconfig.json
```

## 🚀 Chạy

### Cách nhanh (1 lệnh)
```powershell
cd ..   # ra root duty-logger
.\scripts\run_dashboard.ps1
```
Script tự: start Docker postgres → migration → install deps → chạy
FastAPI :8000 + Vite :3000.

### Cách thủ công
```powershell
# Terminal 1: backend
cd E:\Discord\Bot\Duty-bot
.venv\Scripts\python -m uvicorn web.main:app --reload --port 8000

# Terminal 2: frontend
cd homie-medic-dashboard
npm install        # lần đầu
npm run dev        # http://localhost:3000
```

### Production
```powershell
cd homie-medic-dashboard
npm run build      # tạo dist/
```
Sau đó chỉ chạy FastAPI — nó sẽ tự serve `dist/index.html` cho `/` và `/dashboard`.

## 🔌 Wiring frontend ↔ backend

| Frontend | Backend |
|---|---|
| `api.me()` | `GET /api/dashboard/me` |
| `api.myGuilds()` | `GET /api/dashboard/me/guilds` |
| `api.overview()` | `GET /api/dashboard/overview` |
| `api.chart()` | `GET /api/dashboard/chart` |
| `api.ranking()` | `GET /api/dashboard/ranking` |
| `api.attendance()` | `GET /api/dashboard/attendance` |
| `api.logs()` | `GET /api/dashboard/logs` |
| `api.deleteLog()` | `DELETE /api/dashboard/logs/{id}` |
| `api.scheduleGrid()` | `GET /api/schedule/grid` |
| `api.scheduleCalendar()` | `GET /api/schedule/calendar` |
| `api.scheduleCompliance()` | `GET /api/schedule/compliance` |
| `api.scheduleUpdate()` | `PUT /api/schedule/{id}` |
| `api.leaveList()` | `GET /api/leave/list?status=…` |
| `api.leaveDecision()` | `POST /api/leave/{id}/decision` |
| `api.leaveRevert()` | `POST /api/leave/{id}/revert` |
| `api.auditLogs()` | `GET /api/audit/logs` |
| WebSocket `useRealtime` | `WS /ws` (proxy qua Vite) |
| Login button | `GET /auth/login` (redirect Discord) |
| 2FA OTP | `POST /auth/verify-2fa` |
| Logout | `POST /auth/logout` |

Cookies HttpOnly tự gửi qua `credentials: 'include'`. Vite dev proxy đảm bảo
cùng origin → cookie hoạt động bình thường trong dev.

## 🎨 Design tokens

Định nghĩa trong `src/index.css` qua `@theme` của Tailwind 4 + CSS variables:

```css
--color-brand:       #3b82f6   /* blue 500 */
--color-accent:      #8b5cf6   /* violet 500 */
--color-success:     #10b981
--color-warning:     #f59e0b
--color-danger:      #ef4444
--color-bg-base, --color-bg-surface, --color-border, --color-text-*
```

Dark mode toggle bằng class `.dark` trên `<html>` (managed bởi React state).

## 🔐 Auth flow

1. User → `http://localhost:3000` → React mount → `detectAuth()` call `/api/dashboard/me`
2. Nếu 401 → hiển thị Login screen → click → `window.location = '/auth/login'`
3. FastAPI → Discord OAuth → callback → set cookie `access_token` (hoặc `2fa_pending`)
4. Redirect về `/` (hoặc `/?require_2fa=1`)
5. React mount lại → nếu có flag 2FA → show OTP modal → `POST /auth/verify-2fa`
6. Reload → `/api/dashboard/me` thành công → vào dashboard

## ⚡ Realtime (WebSocket)

```ts
useRealtime(isAuth, (event) => {
  if (event.type === 'duty_log_created') overviewQ.refetch();
});
```
Tự reconnect với exponential backoff. Ping mỗi 25s để giữ kết nối qua proxy.

## 📝 Lưu ý developer

- **Stack mới** so với phần trước: thay vì Jinja2 + vanilla JS, dashboard giờ là SPA độc lập.
  Templates cũ (`web/templates/dashboard.html`) vẫn được giữ làm **fallback** nếu chưa
  build dist/.
- **Tailwind 4** dùng `@theme {}` thay cho `tailwind.config.js` legacy.
- **Mọi `fetch()` đã được thay** bằng `api.*` typed wrappers — không gọi
  fetch trực tiếp trong components, dùng hooks.
- **State quản lý qua useState/useMemo**, không có Redux/Zustand —
  đủ cho scope hiện tại.
- **Auth state singleton** trong App.tsx — nếu mở rộng nên chuyển sang Context.
