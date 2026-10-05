import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { PasscodeGate } from './components/PasscodeGate'
import './index.css'
import { CaseView } from './pages/CaseView'
import { Dashboard } from './pages/Dashboard'
import { NewVendor } from './pages/NewVendor'
import { NotFound } from './pages/NotFound'
import { Outbox } from './pages/Outbox'
import { Reapply } from './pages/Reapply'
import { Resubmit } from './pages/Resubmit'
import { ReviewQueue } from './pages/ReviewQueue'
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
              <Route path="cases/:id" element={<CaseView />} />
              <Route path="cases/:id/resubmit" element={<Resubmit />} />
              <Route path="cases/:id/reapply" element={<Reapply />} />
              <Route path="review" element={<ReviewQueue />} />
              <Route path="outbox" element={<Outbox />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </PasscodeGate>
    </QueryClientProvider>
  </StrictMode>,
)
