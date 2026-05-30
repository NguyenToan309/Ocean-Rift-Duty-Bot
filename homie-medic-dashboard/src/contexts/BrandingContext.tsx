/**
 * BrandingContext.tsx — Load system_name từ /api/branding 1 lần, expose
 * toàn app qua hook useBranding(). Sidebar logo + LoginPage title +
 * document.title đều đọc từ đây để bot owner đổi tên là cả app đổi theo.
 *
 * Fallback "Homie Medic" nếu API fail (vd: backend chưa migrate / down).
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api } from '../lib/api';

const DEFAULT_NAME = 'Homie Medic';

interface BrandingState {
  systemName: string;
  refresh: () => Promise<void>;
}

const BrandingContext = createContext<BrandingState>({
  systemName: DEFAULT_NAME,
  refresh: async () => {},
});

export function BrandingProvider({ children }: { children: ReactNode }) {
  const [systemName, setSystemName] = useState<string>(DEFAULT_NAME);

  const load = async () => {
    try {
      const r = await api.branding();
      if (r.system_name) {
        setSystemName(r.system_name);
        // Sync document.title cho browser tab
        if (typeof document !== 'undefined') {
          document.title = r.system_name;
        }
      }
    } catch (err) {
      // Branding fail là non-critical — giữ default, không log noise
      console.debug('Branding load failed, dùng default:', err);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <BrandingContext.Provider value={{ systemName, refresh: load }}>
      {children}
    </BrandingContext.Provider>
  );
}

export function useBranding(): BrandingState {
  return useContext(BrandingContext);
}
