import React from 'react';
import ReactDOM from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { router } from './routes';
import { ThemeProvider } from './contexts/ThemeContext';
import { AuthProvider } from './contexts/AuthContext';
import { AvatarProvider } from './contexts/AvatarContext';
import { BrandingProvider } from './contexts/BrandingContext';
import './styles/theme.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <BrandingProvider>
        <AuthProvider>
          <AvatarProvider>
            <RouterProvider router={router} />
          </AvatarProvider>
        </AuthProvider>
      </BrandingProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
