// Small UI kit: the handful of primitives the app needs, styled with Tailwind.
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { DisplayStatus, Reason } from '../api'
import { STATUS, cx } from '../lib/style'

type Variant = 'primary' | 'secondary' | 'ghost'

const BUTTON: Record<Variant, string> = {
  primary: 'bg-brand-700 text-white hover:bg-brand-800 shadow-sm',
  secondary: 'bg-white text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50',
  ghost: 'text-slate-600 hover:bg-slate-100',
}

export function Button({ variant = 'primary', className, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={cx('inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium',
        'transition-colors disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2',
        'focus-visible:outline-offset-2 focus-visible:outline-brand-600', BUTTON[variant], className)}
      {...props}
    />
  )
}

export function ButtonLink({ to, variant = 'primary', children }: { to: string; variant?: Variant; children: ReactNode }) {
  return (
    <Link to={to} className={cx('inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors',
      BUTTON[variant])}>
      {children}
    </Link>
  )
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx('rounded-xl bg-white ring-1 ring-slate-200 shadow-sm', className)}>{children}</div>
}

export function StatusBadge({ status }: { status: DisplayStatus }) {
  const s = STATUS[status]
  return (
    <span className={cx('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset', s.badge)}>
      <span className={cx('size-1.5 rounded-full', s.dot)} />
      {s.label}
    </span>
  )
}

export function ReasonChips({ reasons, max = 2 }: { reasons: Reason[]; max?: number }) {
  if (!reasons.length) return <span className="text-slate-400">—</span>
  const shown = reasons.slice(0, max)
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map((r) => (
        <span key={r.rule_id} title={r.rule_id}
          className="whitespace-nowrap rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
          {r.issue}
        </span>
      ))}
      {reasons.length > max && <span className="px-1 text-xs text-slate-500">+{reasons.length - max}</span>}
    </div>
  )
}

export function Tag({ children, tone = 'slate' }: { children: ReactNode; tone?: 'slate' | 'teal' }) {
  return (
    <span className={cx('inline-flex items-center whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-medium',
      tone === 'teal' ? 'bg-brand-50 text-brand-800' : 'bg-slate-100 text-slate-600')}>
      {children}
    </span>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <span className={cx('inline-block size-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand-700', className)} />
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  return (
    <div className="rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-800 ring-1 ring-rose-200">
      Something went wrong: {error instanceof Error ? error.message : String(error)}
    </div>
  )
}
