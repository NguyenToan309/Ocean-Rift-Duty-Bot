import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import { ErrorBoundary } from './ErrorBoundary.tsx';
import './index.css';

// Surface unhandled promise rejections trong console với context rõ.
window.addEventListener('unhandledrejection', (event) => {
  console.error('[Homie Medic] Unhandled promise rejection:', event.reason);
});
window.addEventListener('error', (event) => {
  console.error('[Homie Medic] Window error:', event.error || event.message);
});

const rootEl = document.getElementById('root');
if (!rootEl) {
  throw new Error('Không tìm thấy <div id="root"> trong index.html');
}

createRoot(rootEl).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
