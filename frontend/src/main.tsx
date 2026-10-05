import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { PasscodeGate } from './components/PasscodeGate'
import './index.css'
import { Dashboard } from './pages/Dashboard'
import { NewVendor } from './pages/NewVendor'
import { Placeholder } from './pages/Placeholder'
import { RunView } from './pages/RunView'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <PasscodeGate>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Dashboard />} />
              <Route path="new" element={<NewVendor />} />
              <Route path="runs/:id" element={<RunView />} />
              <Route path="cases/:id" element={<Placeholder title="Case" step="4c" />} />
              <Route path="review" element={<Placeholder title="Review queue" step="4c" />} />
              <Route path="*" element={<Placeholder title="Page not found" step="—" />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </PasscodeGate>
    </QueryClientProvider>
  </StrictMode>,
)
