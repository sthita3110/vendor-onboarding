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
  /** The response's `detail` as sent by the API (string, or a structured object such as duplicate_case). */
  detail: unknown
  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.status = status
    this.detail = detail
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
    let detail: unknown
    try {
      detail = (await res.json()).detail
      message = typeof detail === 'string' ? detail
        : detail && typeof detail === 'object' && 'message' in detail ? String((detail as { message: unknown }).message)
        : JSON.stringify(detail)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message, detail)
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

// ---------- submission ----------

export type Slot = 'gst_certificate' | 'pan_card' | 'bank_proof'
export type EntityType = 'company' | 'llp' | 'partnership' | 'proprietorship'

export interface SubmissionForm {
  legal_name: string
  trade_name: string
  entity_type: EntityType | ''
  address: { line1: string; city: string; state: string; pin_code: string }
  contact_name: string
  contact_email: string
  gstin: string
  pan: string
  bank: { account_holder_name: string; account_number: string; ifsc: string; bank_name: string }
}

export interface SampleSummary {
  id: string
  title: string
  description: string
}

export interface SampleDetail extends SampleSummary {
  submission: Partial<SubmissionForm> & Record<string, unknown>
  files: { slot: Slot; filename: string; url: string }[]
}

export const listSamples = () => api<SampleSummary[]>('/api/samples')
export const getSample = (id: string) => api<SampleDetail>(`/api/samples/${id}`)
export const getStates = () => api<string[]>('/api/reference/states')

/** Download a sample PDF as a File, so a loaded sample uploads exactly like a user-picked file. */
export async function fetchSampleFile(url: string, filename: string): Promise<File> {
  const headers = new Headers()
  const passcode = getPasscode()
  if (passcode) headers.set('X-App-Passcode', passcode)
  const res = await fetch(url, { headers })
  if (!res.ok) throw new ApiError(res.status, `Couldn't load ${filename}`)
  return new File([await res.blob()], filename, { type: 'application/pdf' })
}

/** Blank strings become null so the backend sees "missing" (COMP-01), not an empty value. */
function toPayload(form: SubmissionForm): Record<string, unknown> {
  const clean = (v: string) => (v.trim() === '' ? null : v.trim())
  return {
    legal_name: clean(form.legal_name), trade_name: clean(form.trade_name),
    entity_type: form.entity_type || null,
    address: Object.fromEntries(Object.entries(form.address).map(([k, v]) => [k, clean(v)])),
    contact_name: clean(form.contact_name), contact_email: clean(form.contact_email),
    gstin: clean(form.gstin), pan: clean(form.pan),
    bank: Object.fromEntries(Object.entries(form.bank).map(([k, v]) => [k, clean(v)])),
  }
}

export interface Created {
  case_id: number
  reference: string
  run_id: number
}

export function createCase(form: SubmissionForm, files: Partial<Record<Slot, File>>, sampleId?: string) {
  const body = new FormData()
  body.set('submission', JSON.stringify(toPayload(form)))
  if (sampleId) body.set('sample_id', sampleId)
  for (const [slot, file] of Object.entries(files)) if (file) body.set(slot, file)
  return api<Created>('/api/cases', { method: 'POST', body })
}

export const replayCase = (caseId: number) =>
  api<{ case_id: number; run_id: number }>(`/api/cases/${caseId}/replay`, { method: 'POST' })

// ---------- case detail ----------

export interface CheckResultView {
  status: 'pass' | 'fail' | 'blocked' | 'error'
  subject: string | null
  title: string
  detail: string | null
  vendor_text: string | null
  outcome_class: string | null
  evidence: Record<string, unknown>
  blocked_by: string | null
  blocked_by_issue: string | null
}

export interface RuleView {
  rule_id: string
  name: string
  issue: string
  required: boolean
  outcome_if_failed: 'VENDOR_ACTION' | 'REVIEW' | 'REJECT' | 'INFO'
  status: 'pass' | 'fail' | 'blocked' | 'error'
  results: CheckResultView[]
}

export interface ExtractedFieldView {
  value: string | null
  quote: string | null
  page: number | null
  grounded: 'text' | 'image' | 'unverified' | null
}

export interface ExtractionView {
  slot: Slot
  document_id: number | null
  filename: string | null
  classified_type: string | null
  readable: boolean | null
  file_problem: string | null
  extraction_error: string | null
  fields: Record<string, ExtractedFieldView>
  meta: Record<string, unknown>
}

export interface DocumentView {
  id: number
  slot: Slot
  filename: string
  size: number
  carried_over: boolean
  url: string
}

export interface CaseDetail extends CaseRow {
  pan: string | null
  can_resubmit: boolean
  can_replay: boolean
  selected_version: number
  versions_detail: {
    version: number
    submitted_at: string
    submitted_by: string
    run: { id: number; status: string; decision: Decision | null } | null
  }[]
  runs_detail: {
    id: number
    version: number
    trigger: Run['trigger']
    trigger_label: string
    status: string
    created_at: string
    decision: Decision | null
  }[]
  submission: Record<string, unknown>
  documents: DocumentView[]
  run: Run | null
  checks: { group: string; rules: RuleView[] }[]
  extractions: Partial<Record<Slot, ExtractionView>>
}

export interface AuditEvent {
  id: number
  at: string
  actor: string
  event: string
  run_id: number | null
  data: Record<string, unknown>
}

export const getCase = (id: number, version?: number) =>
  api<CaseDetail>(`/api/cases/${id}${version ? `?version=${version}` : ''}`)
export const getAudit = (id: number) => api<AuditEvent[]>(`/api/cases/${id}/audit`)
export const getReviewQueue = () => api<CaseRow[]>('/api/review-queue')

export function resubmitCase(caseId: number, form: SubmissionForm, files: Partial<Record<Slot, File>>) {
  const body = new FormData()
  body.set('submission', JSON.stringify(toPayload(form)))
  for (const [slot, file] of Object.entries(files)) if (file) body.set(slot, file)
  return api<{ case_id: number; run_id: number; version: number }>(`/api/cases/${caseId}/resubmit`, { method: 'POST', body })
}

/** Open an uploaded document in a new tab. Fetched with the passcode header (never put in the URL),
 *  then shown from a local blob URL. The tab is opened first so popup blockers allow it. */
export async function openDocument(url: string): Promise<void> {
  const tab = window.open('', '_blank')
  const headers = new Headers()
  const passcode = getPasscode()
  if (passcode) headers.set('X-App-Passcode', passcode)
  const res = await fetch(url, { headers })
  if (!res.ok) {
    tab?.close()
    throw new ApiError(res.status, "Couldn't open the document")
  }
  const blobUrl = URL.createObjectURL(await res.blob())
  if (tab) tab.location.href = blobUrl
  else window.location.href = blobUrl
}

// ---------- duplicate-case check ----------

export interface DuplicateMatch extends CaseRow {
  can_resubmit: boolean
  can_replay: boolean
  selected_version: number
}

export interface DuplicateCase {
  code: 'duplicate_case'
  message: string
  matches: DuplicateMatch[]
}

export function asDuplicate(error: unknown): DuplicateCase | null {
  if (error instanceof ApiError && error.status === 409 && error.detail && typeof error.detail === 'object'
    && (error.detail as { code?: string }).code === 'duplicate_case') return error.detail as DuplicateCase
  return null
}
