/**
 * AvatarContext — Cache user_id → avatar_url + username toàn app.
 *
 * Pattern:
 * 1. Khi guild đổi: fetch staff list 1 lần → seed cache với avatar_url.
 * 2. Mọi page gọi useAvatar(user_id):
 *    - Nếu cache hit → trả ngay
 *    - Nếu miss → add vào queue, debounce 150ms → batch POST /resolve-users
 *    - Trả default avatar trong khi chờ; cache update → React re-render
 * 3. Backend `resolve_user_info` cache 10p, nên batch lặp lại không tốn API.
 *
 * KHÔNG dùng setInterval — chỉ on-demand khi component render gọi getAvatar.
 */
import {
  createContext, useContext, useEffect, useState, useCallback,
  useRef, type ReactNode,
} from 'react';
import { api } from '../lib/api';
import { defaultDiscordAvatar } from '../lib/discord';
import { useAuth } from './AuthContext';

interface UserInfo {
  avatar_url: string;
  username?: string;
}

interface AvatarContextType {
  /** Lookup avatar URL — fallback default + trigger background fetch nếu miss. */
  getAvatar: (user_id: string | null | undefined) => string;
  /** Lookup username — trả '' nếu chưa biết. */
  getUsername: (user_id: string | null | undefined) => string;
  /** Bổ sung avatar khi page fetch được (vd staff list, leave list). */
  learnAvatar: (user_id: string, url: string | null | undefined, username?: string) => void;
  /** Force refresh staff cache. */
  refresh: () => void;
}

const AvatarContext = createContext<AvatarContextType | undefined>(undefined);

const FETCH_DEBOUNCE_MS = 150;
const NEGATIVE_TTL_MS = 60_000;   // user_id đã thử fetch fail trong 60s thì không retry

export function AvatarProvider({ children }: { children: ReactNode }) {
  const { currentGuildId, state } = useAuth();
  const [cache, setCache] = useState<Map<string, UserInfo>>(new Map());
  const [nonce, setNonce] = useState(0);

  // Pending IDs chờ fetch (chưa flush)
  const pendingRef = useRef<Set<string>>(new Set());
  // ID đã request và đang chờ response (tránh duplicate)
  const inFlightRef = useRef<Set<string>>(new Set());
  // Negative cache: id → timestamp đã fail → skip retry 60s
  const failedAtRef = useRef<Map<string, number>>(new Map());
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Flush queue: gom pending IDs → 1 request batch
  const flush = useCallback(async () => {
    flushTimerRef.current = null;
    const ids = Array.from(pendingRef.current);
    pendingRef.current.clear();
    if (ids.length === 0) return;

    // Đánh dấu in-flight
    for (const id of ids) inFlightRef.current.add(id);

    try {
      const r = await api.resolveUsers(ids);
      const results = r.results || {};
      setCache(prev => {
        const next = new Map(prev);
        for (const id of ids) {
          const info = results[id];
          if (info && info.avatar_url) {
            next.set(id, {
              avatar_url: info.avatar_url,
              username: info.global_name || info.username,
            });
          } else {
            // Backend không resolve được → đánh dấu fail để không retry ngay
            failedAtRef.current.set(id, Date.now());
          }
        }
        return next;
      });
    } catch (err) {
      console.warn('[AvatarContext] Batch resolve failed:', err);
      // Đánh dấu tất cả ids đã fail (sẽ retry sau 60s)
      const now = Date.now();
      for (const id of ids) failedAtRef.current.set(id, now);
    } finally {
      for (const id of ids) inFlightRef.current.delete(id);
    }
  }, []);

  const scheduleFlush = useCallback(() => {
    if (flushTimerRef.current != null) return;
    flushTimerRef.current = setTimeout(() => {
      flush();
    }, FETCH_DEBOUNCE_MS);
  }, [flush]);

  const enqueue = useCallback((user_id: string) => {
    if (!user_id) return;
    if (cache.has(user_id)) return;
    if (inFlightRef.current.has(user_id)) return;
    if (pendingRef.current.has(user_id)) return;

    // Negative cache check
    const failedAt = failedAtRef.current.get(user_id);
    if (failedAt && Date.now() - failedAt < NEGATIVE_TTL_MS) return;

    pendingRef.current.add(user_id);
    scheduleFlush();
  }, [cache, scheduleFlush]);

  // Khi guild đổi: clear cache + seed từ staff list
  useEffect(() => {
    if (state !== 'authed' || !currentGuildId) return;
    let cancelled = false;
    // Reset pending state khi đổi guild
    pendingRef.current.clear();
    inFlightRef.current.clear();
    failedAtRef.current.clear();
    if (flushTimerRef.current) {
      clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }

    api.staffList(currentGuildId, { is_active: undefined })
      .then(r => {
        if (cancelled) return;
        setCache(() => {
          const next = new Map<string, UserInfo>();
          for (const m of r.items || []) {
            if (m.avatar_url) {
              next.set(m.user_id, {
                avatar_url: m.avatar_url,
                username: m.username,
              });
            }
          }
          return next;
        });
      })
      .catch(err => console.warn('[AvatarContext] Load staff avatars failed:', err));

    return () => {
      cancelled = true;
      if (flushTimerRef.current) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
    };
  }, [currentGuildId, state, nonce]);

  const getAvatar = useCallback((user_id: string | null | undefined): string => {
    if (!user_id) return defaultDiscordAvatar(user_id);
    const hit = cache.get(user_id);
    if (hit) return hit.avatar_url;
    enqueue(user_id);
    return defaultDiscordAvatar(user_id);
  }, [cache, enqueue]);

  const getUsername = useCallback((user_id: string | null | undefined): string => {
    if (!user_id) return '';
    return cache.get(user_id)?.username || '';
  }, [cache]);

  const learnAvatar = useCallback((user_id: string, url: string | null | undefined, username?: string) => {
    if (!user_id || !url) return;
    setCache(prev => {
      const existing = prev.get(user_id);
      if (existing?.avatar_url === url && (!username || existing.username === username)) return prev;
      const next = new Map(prev);
      next.set(user_id, {
        avatar_url: url,
        username: username || existing?.username,
      });
      return next;
    });
  }, []);

  const refresh = useCallback(() => {
    failedAtRef.current.clear();
    setNonce(n => n + 1);
  }, []);

  return (
    <AvatarContext.Provider value={{ getAvatar, getUsername, learnAvatar, refresh }}>
      {children}
    </AvatarContext.Provider>
  );
}

export function useAvatars() {
  const ctx = useContext(AvatarContext);
  if (!ctx) throw new Error('useAvatars must be inside AvatarProvider');
  return ctx;
}

/** Hook ngắn: lấy avatar URL cho 1 user_id. */
export function useAvatar(user_id: string | null | undefined): string {
  return useAvatars().getAvatar(user_id);
}
