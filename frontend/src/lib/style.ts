// Shared styling helpers (kept out of component files so fast refresh works).
import type { DisplayStatus } from '../api'

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ')
}

// One place that decides how each status looks and reads.
export const STATUS: Record<DisplayStatus, { label: string; badge: string; dot: string }> = {
  APPROVED: { label: 'Approved', badge: 'bg-emerald-50 text-emerald-800 ring-emerald-600/20', dot: 'bg-emerald-500' },
  AWAITING_VENDOR: { label: 'Awaiting vendor', badge: 'bg-amber-50 text-amber-800 ring-amber-600/20', dot: 'bg-amber-500' },
  INTERNAL_REVIEW: { label: 'In review', badge: 'bg-violet-50 text-violet-800 ring-violet-600/20', dot: 'bg-violet-500' },
  REJECTED: { label: 'Rejected', badge: 'bg-rose-50 text-rose-800 ring-rose-600/20', dot: 'bg-rose-500' },
  IN_PROGRESS: { label: 'In progress', badge: 'bg-sky-50 text-sky-800 ring-sky-600/20', dot: 'bg-sky-500 animate-pulse' },
}
