// Typed client for the backend API. Types mirror backend/app/api/serializers.py.

export type DisplayStatus = 'APPROVED' | 'AWAITING_VENDOR' | 'INTERNAL_REVIEW' | 'REJECTED' | 'IN_PROGRESS'

export interface Reason {
  rule_id: string
  issue: string
}

export interface CaseRow {
  id: number
  reference: string
  vendor_name: string | null
  gstin: string | null
  status: string
  sub_state: string | null
  display_status: DisplayStatus
  reasons: Reason[]
  versions: number
  vendor_actions: number
  source: 'form' | 'seed'
  source_label: string
  sample_id: string | null
  created_at: string
  decided_at: string | null
  updated_at: string
  latest_run: { id: number; status: string } | null
}

export interface Metrics {
  total: number
  by_status: Record<DisplayStatus, number>
  straight_through_rate: number | null
  median_seconds_to_decision: number | null
  top_reasons: { rule_id: string; issue: string; count: number }[]
  seeded_cases: number
}

export interface Stage {
  key: string
  label: string
  status: 'pending' | 'running' | 'done' | 'failed'
  outcome: 'pass' | 'issues' | 'blocked' | 'error' | null
  summary: string | null
  details: Record<string, unknown>
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
}

export interface Decision {
  status: string
  sub_state: string | null
  display_status: DisplayStatus
  summary: string
  reasons: Reason[]
  vendor_actions: string[]
  rule_catalog_version: string
  decided_at: string | null
}

export interface Run {
  id: number
  case_id: number
  reference: string
  vendor_name: string | null
  version: number
  trigger: 'submission' | 'resubmission' | 'replay' | 'seed'
  trigger_label: string
  executed: boolean
  status: 'queued' | 'running' | 'completed' | 'failed' | 'interrupted'
  active: boolean
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  stages: Stage[]
  decision: Decision | null
}

const PASSCODE_KEY = 'vo-passcode'

export function getPasscode(): string | null {
  try {
    return sessionStorage.getItem(PASSCODE_KEY)
  } catch {
    return null
  }
}

export function setPasscode(value: string | null): void {
  try {
    if (value) sessionStorage.setItem(PASSCODE_KEY, value)
    else sessionStorage.removeItem(PASSCODE_KEY)
  } catch {
    /* storage unavailable (private mode): passcode lives only in memory for this page */
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// Notified on 401 so the passcode screen can appear from anywhere in the app.
type UnauthorizedListener = () => void
const unauthorizedListeners = new Set<UnauthorizedListener>()
export function onUnauthorized(fn: UnauthorizedListener): () => void {
  unauthorizedListeners.add(fn)
  return () => unauthorizedListeners.delete(fn)
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const passcode = getPasscode()
  if (passcode) headers.set('X-App-Passcode', passcode)
  const res = await fetch(path, { ...init, headers })
  if (res.status === 401) {
    unauthorizedListeners.forEach((fn) => fn())
    throw new ApiError(401, 'Passcode required')
  }
  if (!res.ok) {
    let message = res.statusText
    try {
      const body = await res.json()
      message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message)
  }
  return res.json() as Promise<T>
}

export const listCases = (params: { status?: string; q?: string } = {}) => {
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  if (params.q) qs.set('q', params.q)
  const query = qs.toString()
  return api<CaseRow[]>(`/api/cases${query ? `?${query}` : ''}`)
}

export const getMetrics = () => api<Metrics>('/api/metrics')
export const getRun = (id: number) => api<Run>(`/api/runs/${id}`)
