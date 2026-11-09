import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './app/App.tsx'
import { migrateBrandStorage } from './lib/migrate-brand-storage.ts'

for (const name of ['localStorage', 'sessionStorage'] as const) {
  try { migrateBrandStorage(window[name]); } catch { /* Restricted/full storage must not prevent startup. */ }
}

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Application root element not found')
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
