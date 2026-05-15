/**
 * auth.ts — Helpers cho OAuth2 flow + 2FA.
 *
 * Flow:
 *  1. User click "Login" → redirect tới /auth/login (FastAPI)
 *  2. FastAPI redirect Discord → callback → set HttpOnly cookie
 *     - Nếu user có 2FA: set `2fa_pending` cookie, redirect ?require_2fa=1
 *     - Nếu không: set `access_token` cookie, redirect /dashboard
 *  3. SPA mount → check ?require_2fa=1 hoặc gọi /api/dashboard/me
 *  4. Nếu pending → show OTP modal → POST /auth/verify-2fa → reload
 */
import { api, APIError } from './api';

export function startDiscordLogin(): void {
  // Đẩy thẳng tới backend; backend sẽ redirect tới Discord OAuth.
  window.location.href = '/auth/login';
}

export function read2FAFlagFromURL(): boolean {
  const params = new URLSearchParams(window.location.search);
  return params.get('require_2fa') === '1';
}

export function clearURLParams(): void {
  window.history.replaceState({}, '', window.location.pathname);
}

export async function logout(): Promise<void> {
  try {
    await api.logout();
  } catch {
    /* ignore — vẫn xóa state phía client */
  }
  window.location.href = '/';
}

export async function detectAuth(): Promise<
  | { state: 'authed'; me: Awaited<ReturnType<typeof api.me>> }
  | { state: 'need_2fa' }
  | { state: 'anon' }
> {
  if (read2FAFlagFromURL()) {
    clearURLParams();
    return { state: 'need_2fa' };
  }
  try {
    const me = await api.me();
    return { state: 'authed', me };
  } catch (err) {
    if (err instanceof APIError && err.status === 401) {
      return { state: 'anon' };
    }
    // Lỗi mạng / 500 — coi như anon để hiển thị login
    return { state: 'anon' };
  }
}

export async function verify2FA(otp: string): Promise<void> {
  await api.verify2FA(otp);
  // Reload để FastAPI set cookie access_token rồi me() trả về ok
  window.location.href = '/';
}
