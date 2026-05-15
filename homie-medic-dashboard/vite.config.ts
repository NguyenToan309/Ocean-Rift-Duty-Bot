import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig, loadEnv } from 'vite';

/**
 * Vite config — Homie Medic dashboard
 *
 * Dev: proxy /api, /auth, /ws → FastAPI tại http://localhost:8000
 * Build: output `dist/` rồi FastAPI mount serve static cho production.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  const apiTarget = env.VITE_API_URL || 'http://localhost:8000';

  return {
    plugins: [react(), tailwindcss()],
    define: {
      'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY),
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    build: {
      outDir: 'dist',
      assetsDir: 'assets',
      sourcemap: false,
      chunkSizeWarningLimit: 1024,
    },
    server: {
      port: 3000,
      host: '0.0.0.0',
      hmr: process.env.DISABLE_HMR !== 'true',
      proxy: {
        // REST API
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          secure: false,
        },
        // OAuth2 + 2FA + logout
        '/auth': {
          target: apiTarget,
          changeOrigin: true,
          secure: false,
        },
        // WebSocket realtime
        '/ws': {
          target: apiTarget.replace(/^http/, 'ws'),
          ws: true,
          changeOrigin: true,
        },
        // Health check
        '/health': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
