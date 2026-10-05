import { useQuery } from '@tanstack/react-query'
import { ClipboardCheck, LayoutDashboard, Plus } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import { getMetrics } from '../api'
import { cx } from '../lib/style'

function NavItem({ to, icon, label, badge }: { to: string; icon: React.ReactNode; label: string; badge?: number }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) => cx(
        'inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
        isActive ? 'bg-white/15 text-white' : 'text-brand-100 hover:bg-white/10 hover:text-white',
      )}
    >
      {icon}
      <span className="hidden sm:inline">{label}</span>
      {!!badge && <span className="rounded-full bg-white px-1.5 text-[11px] font-semibold text-brand-900">{badge}</span>}
    </NavLink>
  )
}

export function Layout() {
  const { data: metrics } = useQuery({ queryKey: ['metrics'], queryFn: getMetrics, refetchInterval: 5000 })
  const inReview = metrics?.by_status.INTERNAL_REVIEW

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-brand-900">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <NavLink to="/" className="flex items-center gap-2.5 text-white">
            <span className="flex size-8 items-center justify-center rounded-lg bg-white/15">
              <ClipboardCheck className="size-4.5" />
            </span>
            <span className="whitespace-nowrap text-[15px] font-semibold tracking-tight">Vendor Onboarding</span>
          </NavLink>
          <nav className="flex items-center gap-1">
            <NavItem to="/" icon={<LayoutDashboard className="size-4" />} label="Dashboard" />
            <NavItem to="/review" icon={<ClipboardCheck className="size-4" />} label="Review queue" badge={inReview} />
            <NavItem to="/new" icon={<Plus className="size-4" />} label="New vendor" />
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-7xl px-4 pb-8 text-xs text-slate-400 sm:px-6">
        Demo build · Indian vendors · GST registry and bank verification are simulated providers · all entities are fictitious
      </footer>
    </div>
  )
}
