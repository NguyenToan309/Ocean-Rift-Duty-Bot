import { useState, useEffect, useRef } from 'react';
import { Cross, Shield, ArrowRight, LogIn } from 'lucide-react';
import { startDiscordLogin, verify2FA, read2FAFlagFromURL, clearURLParams } from '../lib/auth';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Spinner } from '../components/shared/misc';
import { cn } from '../lib/cn';
import { formatError } from '../lib/api';

export function LoginPage() {
  const { state, setAuthState } = useAuth();
  const navigate = useNavigate();
  const [show2FA, setShow2FA] = useState(false);

  useEffect(() => {
    if (read2FAFlagFromURL()) {
      setShow2FA(true);
      clearURLParams();
    }
    if (state === 'need_2fa') setShow2FA(true);
  }, [state]);

  useEffect(() => {
    if (state === 'authed') navigate('/');
  }, [state, navigate]);

  return (
    <div className="min-h-screen bg-[var(--background)] flex items-center justify-center p-4 relative overflow-hidden">
      {/* Subtle background gradient */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_rgba(15,118,110,0.08),_transparent_50%)] pointer-events-none" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom,_rgba(20,184,166,0.05),_transparent_50%)] pointer-events-none" />

      <div className="relative w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-[var(--primary)] text-white mb-4 shadow-lg">
            <Cross className="h-7 w-7" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Homie Medic</h1>
          <p className="text-sm text-[var(--muted-foreground)] mt-1">
            Hệ thống quản lý ca trực y tế
          </p>
        </div>

        <Card className="shadow-xl">
          <CardContent className="p-6">
            {show2FA ? <TwoFactorForm onSuccess={() => setAuthState('authed')} /> : <DiscordLoginCard />}
          </CardContent>
        </Card>

        <p className="text-xs text-center text-[var(--muted-foreground)] mt-6">
          Bot chấm công nội bộ · Yêu cầu role được cấp quyền
          <br />
          <span className="opacity-60">© 2026 Homie Medic — Discord Bot Dashboard</span>
        </p>
      </div>
    </div>
  );
}

function DiscordLoginCard() {
  return (
    <div className="space-y-6">
      <div className="text-center">
        <h2 className="text-lg font-semibold">Đăng nhập</h2>
        <p className="text-sm text-[var(--muted-foreground)] mt-1">
          Sử dụng tài khoản Discord của bạn
        </p>
      </div>

      <Button
        onClick={startDiscordLogin}
        size="lg"
        className="w-full bg-[#5865F2] hover:bg-[#4752C4] text-white"
      >
        <DiscordIcon />
        Đăng nhập với Discord
        <ArrowRight className="h-4 w-4" />
      </Button>

      <div className="flex items-start gap-2 p-3 rounded-lg bg-[var(--muted)] text-xs text-[var(--muted-foreground)]">
        <Shield className="h-4 w-4 mt-0.5 shrink-0 text-[var(--info)]" />
        <p>
          Sau khi đăng nhập Discord, nếu tài khoản bạn đã bật 2FA, hệ thống sẽ yêu cầu nhập mã 6 số từ Google Authenticator.
        </p>
      </div>
    </div>
  );
}

function TwoFactorForm({ onSuccess }: { onSuccess: () => void }) {
  const [digits, setDigits] = useState<string[]>(['', '', '', '', '', '']);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const code = digits.join('');

  const handleChange = (i: number, v: string) => {
    const digit = v.replace(/\D/g, '').slice(-1);
    const next = [...digits];
    next[i] = digit;
    setDigits(next);
    if (digit && i < 5) refs.current[i + 1]?.focus();
  };

  const handleKey = (i: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && !digits[i] && i > 0) {
      refs.current[i - 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const txt = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
    if (!txt) return;
    const next = ['', '', '', '', '', ''];
    txt.split('').forEach((c, i) => { next[i] = c; });
    setDigits(next);
    refs.current[Math.min(txt.length, 5)]?.focus();
  };

  const submit = async () => {
    setError(null);
    if (code.length !== 6) {
      setError('Vui lòng nhập đủ 6 chữ số');
      return;
    }
    setSubmitting(true);
    try {
      await verify2FA(code);
      onSuccess();
    } catch (err) {
      setError(formatError(err));
      setDigits(['', '', '', '', '', '']);
      refs.current[0]?.focus();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="text-center">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-[var(--primary)]/10 text-[var(--primary)] mb-3">
          <Shield className="h-6 w-6" />
        </div>
        <h2 className="text-lg font-semibold">Xác thực 2 bước</h2>
        <p className="text-sm text-[var(--muted-foreground)] mt-1">
          Nhập mã 6 chữ số từ <strong>Google Authenticator</strong>
        </p>
      </div>

      <div className="flex justify-center gap-2" onPaste={handlePaste}>
        {digits.map((d, i) => (
          <input
            key={i}
            ref={el => { refs.current[i] = el; }}
            type="text"
            inputMode="numeric"
            maxLength={1}
            value={d}
            onChange={e => handleChange(i, e.target.value)}
            onKeyDown={e => handleKey(i, e)}
            className={cn(
              'w-11 h-12 text-center text-lg font-mono font-bold',
              'border border-[var(--border)] rounded-lg bg-[var(--input-background)]',
              'focus:outline-none focus:ring-2 focus:ring-[var(--ring)] focus:border-[var(--ring)]',
              error && 'border-[var(--destructive)]',
            )}
          />
        ))}
      </div>

      {error && (
        <p className="text-xs text-[var(--destructive)] text-center bg-[var(--destructive)]/10 px-3 py-2 rounded-lg">
          {error}
        </p>
      )}

      <Button
        onClick={submit}
        disabled={submitting || code.length !== 6}
        size="lg"
        className="w-full"
      >
        {submitting ? <><Spinner /> Đang xác thực...</> : <><LogIn className="h-4 w-4" /> Xác thực</>}
      </Button>
    </div>
  );
}

function DiscordIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 71 55" fill="currentColor">
      <path d="M60.105 4.898A58.55 58.55 0 0 0 45.653.415a.22.22 0 0 0-.232.11 40.78 40.78 0 0 0-1.8 3.697c-5.456-.817-10.886-.817-16.23 0-.485-1.164-1.201-2.587-1.828-3.697a.228.228 0 0 0-.233-.11 58.39 58.39 0 0 0-14.451 4.483.207.207 0 0 0-.095.082C1.578 18.73-.944 32.144.293 45.39a.244.244 0 0 0 .093.167c6.073 4.46 11.955 7.167 17.729 8.962a.23.23 0 0 0 .249-.082 42.08 42.08 0 0 0 3.627-5.9.225.225 0 0 0-.123-.312 38.772 38.772 0 0 1-5.539-2.64.228.228 0 0 1-.022-.378c.372-.279.744-.569 1.1-.862a.22.22 0 0 1 .229-.031c11.62 5.305 24.198 5.305 35.681 0a.219.219 0 0 1 .232.028c.356.293.728.586 1.103.865.165.123.156.366-.021.378a36.384 36.384 0 0 1-5.54 2.637.227.227 0 0 0-.121.315 47.252 47.252 0 0 0 3.624 5.897.225.225 0 0 0 .249.084c5.801-1.795 11.683-4.503 17.756-8.962a.228.228 0 0 0 .092-.164c1.48-15.314-2.479-28.618-10.495-40.412a.18.18 0 0 0-.093-.084Zm-36.38 32.427c-3.497 0-6.38-3.211-6.38-7.156 0-3.944 2.827-7.156 6.38-7.156 3.583 0 6.438 3.24 6.382 7.156 0 3.945-2.827 7.156-6.382 7.156Zm23.593 0c-3.498 0-6.38-3.211-6.38-7.156 0-3.944 2.826-7.156 6.38-7.156 3.582 0 6.437 3.24 6.38 7.156 0 3.945-2.798 7.156-6.38 7.156Z" />
    </svg>
  );
}
