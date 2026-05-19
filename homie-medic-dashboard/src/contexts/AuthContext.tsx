import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, type Me, type Guild } from '../lib/api';
import { detectAuth, logout as authLogout } from '../lib/auth';

type AuthState = 'loading' | 'anon' | 'need_2fa' | 'authed';

interface AuthContextType {
  state: AuthState;
  me: Me | null;
  guilds: Guild[];
  currentGuildId: string | null;
  currentGuild: Guild | null;
  setCurrentGuildId: (id: string) => void;
  refreshGuilds: () => Promise<void>;
  setAuthState: (s: AuthState) => void;
  setMe: (m: Me | null) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>('loading');
  const [me, setMe] = useState<Me | null>(null);
  const [guilds, setGuilds] = useState<Guild[]>([]);
  const [currentGuildId, _setGuildId] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem('hm-guild-id');
  });

  const setCurrentGuildId = (id: string) => {
    _setGuildId(id);
    localStorage.setItem('hm-guild-id', id);
  };

  const refreshGuilds = async () => {
    try {
      const gs = await api.myGuilds();
      setGuilds(gs);
      // Auto-select first guild if no current
      if (!currentGuildId && gs.length > 0) {
        setCurrentGuildId(gs[0].id);
      } else if (currentGuildId && !gs.find(g => g.id === currentGuildId) && gs.length > 0) {
        // Current guild no longer accessible -> pick first
        setCurrentGuildId(gs[0].id);
      }
    } catch (err) {
      console.warn('Load guilds failed:', err);
    }
  };

  useEffect(() => {
    let cancelled = false;
    detectAuth().then(async (res) => {
      if (cancelled) return;
      if (res.state === 'authed') {
        setMe(res.me);
        setState('authed');
        await refreshGuilds();
      } else if (res.state === 'need_2fa') {
        setState('need_2fa');
      } else {
        setState('anon');
      }
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const logout = async () => {
    await authLogout();
    setMe(null);
    setGuilds([]);
    setState('anon');
    localStorage.removeItem('hm-guild-id');
  };

  const currentGuild = guilds.find(g => g.id === currentGuildId) || null;

  return (
    <AuthContext.Provider
      value={{
        state,
        me,
        guilds,
        currentGuildId,
        currentGuild,
        setCurrentGuildId,
        refreshGuilds,
        setAuthState: setState,
        setMe,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}
