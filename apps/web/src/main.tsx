import { QueryClientProvider } from '@tanstack/react-query';
import { lazy, StrictMode, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import App from './App';
import { createQueryClient } from './api/queries';
import { EmptyState } from './components/EmptyState';
import NotFound from './routes/NotFound';
import './theme/tokens.css';
import './theme/global.css';

const LandscapePage = lazy(() => import('./routes/LandscapePage'));

const queryClient = createQueryClient();
const loading = <EmptyState title="Loading…" />;

const container = document.getElementById('root');
if (!container) throw new Error('Missing #root element');

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<App />}>
            <Route index element={<Navigate to="/landscape" replace />} />
            <Route
              path="landscape"
              element={
                <Suspense fallback={loading}>
                  <LandscapePage />
                </Suspense>
              }
            />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
