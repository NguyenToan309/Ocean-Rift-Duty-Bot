/**
 * hooks.ts — Custom React hooks bao quanh API client.
 * Mỗi hook trả về { data, loading, error, refetch }.
 *
 * Sử dụng AbortController để cancel khi component unmount hoặc dep đổi.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, APIError, type Me, type Guild } from './api';

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: APIError | null;
  refetch: () => void;
}

function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [nonce, setNonce] = useState(0);

  // Lưu fn vào ref để tránh re-fetch khi closure đổi mà deps không đổi
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);

    fnRef
      .current(ctrl.signal)
      .then((res) => {
        if (!ctrl.signal.aborted) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof APIError) setError(err);
        else setError(new APIError(0, String(err)));
        setLoading(false);
      });

    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const refetch = useCallback(() => setNonce((n) => n + 1), []);
  return { data, loading, error, refetch };
}

// ============================================================
// CONCRETE HOOKS
// ============================================================

export function useMe() {
  return useAsync<Me>((signal) => api.me().then((r) => (signal.aborted ? Promise.reject(new Error('abort')) : r)), []);
}

export function useGuilds() {
  return useAsync<Guild[]>(() => api.myGuilds(), []);
}

export function useOverview(guildId: string | null, period: string, start?: string, end?: string) {
  return useAsync(
    () => (guildId ? api.overview(guildId, period, start, end) : Promise.resolve(null as any)),
    [guildId, period, start, end],
  );
}

export function useChart(guildId: string | null, period: string) {
  return useAsync(
    () => (guildId ? api.chart(guildId, period) : Promise.resolve([] as any)),
    [guildId, period],
  );
}

export function useRanking(
  guildId: string | null,
  period: string,
  mode: 'top' | 'bottom' = 'top',
  limit = 20,
) {
  return useAsync(
    () => (guildId ? api.ranking(guildId, period, mode, limit) : Promise.resolve([] as any)),
    [guildId, period, mode, limit],
  );
}

export function useAttendance(guildId: string | null, period: string) {
  return useAsync(
    () => (guildId ? api.attendance(guildId, period) : Promise.resolve([] as any)),
    [guildId, period],
  );
}

export function useLogs(guildId: string | null, page: number, search?: string) {
  return useAsync(
    () =>
      guildId
        ? api.logs(guildId, page, 20, undefined, search)
        : Promise.resolve({ items: [], total: 0, page, page_size: 20 } as any),
    [guildId, page, search],
  );
}

export function useScheduleGrid(guildId: string | null, period: string = 'week') {
  return useAsync(
    () =>
      guildId
        ? api.scheduleGrid(guildId, period)
        : Promise.resolve({ week_start: '', days: [] } as any),
    [guildId, period],
  );
}

export function useScheduleCalendar(guildId: string | null, year: number, month: number) {
  return useAsync(
    () =>
      guildId
        ? api.scheduleCalendar(guildId, year, month)
        : Promise.resolve({ days: [] } as any),
    [guildId, year, month],
  );
}

export function useScheduleCompliance(guildId: string | null, period: string) {
  return useAsync(
    () => (guildId ? api.scheduleCompliance(guildId, period) : Promise.resolve([] as any)),
    [guildId, period],
  );
}

export function useLeaveList(guildId: string | null, status?: string) {
  return useAsync(
    () => (guildId ? api.leaveList(guildId, status) : Promise.resolve([] as any)),
    [guildId, status],
  );
}

export function useAuditLogs(guildId: string | null, page: number, action?: string) {
  return useAsync(
    () =>
      guildId
        ? api.auditLogs(guildId, page, 50, action)
        : Promise.resolve({ items: [], total: 0 } as any),
    [guildId, page, action],
  );
}

// ----- STAFF HOOKS -----

export function useStaffPositions(enabled: boolean) {
  return useAsync(
    () =>
      enabled
        ? api.staffPositions()
        : Promise.resolve({ positions: [], groups: [] } as any),
    [enabled],
  );
}

export function useStaffList(
  guildId: string | null,
  opts: { group?: string; position?: string; is_active?: boolean; search?: string } = {},
) {
  return useAsync(
    () =>
      guildId
        ? api.staffList(guildId, opts as any)
        : Promise.resolve({
            items: [],
            total: 0,
            counts_by_group: { LANH_DAO: 0, Y_TE: 0, DAO_TAO: 0 },
          } as any),
    [guildId, opts.group, opts.position, opts.is_active, opts.search],
  );
}

export function useStaffPositionRoleMap(guildId: string | null) {
  return useAsync(
    () =>
      guildId
        ? api.staffGetPositionRoleMap(guildId)
        : Promise.resolve({ position_role_map: {}, valid_system_roles: [] } as any),
    [guildId],
  );
}

// ============================================================
// WEBSOCKET HOOK — single connection per app lifetime
// ============================================================

export interface RealtimeEvent {
  type: string;
  payload?: any;
  ts?: number;
}

export function useRealtime(
  enabled: boolean,
  onEvent: (event: RealtimeEvent) => void,
  guildId: string | null = null,
): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    // Backend /ws bắt buộc guild_id query param. Không có guildId → không connect.
    if (!enabled || !guildId) return;

    let retry = 0;
    let ws: WebSocket | null = null;
    let pingTimer: ReturnType<typeof setInterval> | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;
    // Giới hạn retry để tránh reconnect vô hạn khi 403/4401 (auth fail)
    let permanentlyClosed = false;

    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = `${proto}//${window.location.host}/ws?guild_id=${encodeURIComponent(guildId)}`;
      ws = new WebSocket(url);

      ws.onopen = () => {
        setConnected(true);
        retry = 0;
        // Ping 25s — backend mong "ping" plain text, không phải JSON
        pingTimer = setInterval(() => {
          if (ws?.readyState === WebSocket.OPEN) ws.send('ping');
        }, 25000);
      };

      ws.onmessage = (e) => {
        if (e.data === 'pong') return;
        try {
          const event = JSON.parse(e.data) as RealtimeEvent;
          onEventRef.current(event);
        } catch {
          /* ignore non-JSON */
        }
      };

      ws.onclose = (e) => {
        setConnected(false);
        if (pingTimer) clearInterval(pingTimer);
        if (cancelled) return;
        // Code 4401 = auth fail, 4403 = not member, 4503 = Discord down.
        // Mọi 4xxx code → KHÔNG retry để tránh DOS server.
        if (e.code >= 4400 && e.code < 5000) {
          console.warn(`[WS] permanently closed (${e.code}): ${e.reason}`);
          permanentlyClosed = true;
          return;
        }
        if (permanentlyClosed) return;
        // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
        const delay = Math.min(1000 * 2 ** retry, 30000);
        retry++;
        reconnectTimer = setTimeout(connect, delay);
      };

      ws.onerror = () => ws?.close();
    };

    connect();

    return () => {
      cancelled = true;
      if (pingTimer) clearInterval(pingTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [enabled, guildId]);

  return { connected };
}

// ============================================================
// MUTATION HELPER
// ============================================================

export function useMutation<TArgs extends any[], TResult>(
  fn: (...args: TArgs) => Promise<TResult>,
): {
  mutate: (...args: TArgs) => Promise<TResult>;
  loading: boolean;
  error: APIError | null;
} {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<APIError | null>(null);

  const mutate = useCallback(
    async (...args: TArgs) => {
      setLoading(true);
      setError(null);
      try {
        return await fn(...args);
      } catch (err) {
        const apiErr =
          err instanceof APIError ? err : new APIError(0, String(err));
        setError(apiErr);
        throw apiErr;
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  return { mutate, loading, error };
}
