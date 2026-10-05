// Live run view: the 10 pipeline stages filling in as the backend executes them (polled every second).
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  AlertTriangle, ArrowLeft, CheckCircle2, Circle, ExternalLink, MinusCircle, PlayCircle, ShieldCheck, XCircle,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, getRun, replayCase, type Decision, type DisplayStatus, type Run, type Stage } from '../api'
import { Button, Card, ErrorNote, PageHeader, Spinner, Tag } from '../components/ui'
import { cx } from '../lib/style'

const RUNNING_TEXT: Record<string, string> = {
  intake: 'Storing the submission…',
  completeness: 'Checking every required detail and document is present…',
  read_documents: 'Reading each document with AI — type, fields and the exact text they came from…',
  doc_checks: 'Checking each file opened, is the right document, and was read reliably…',
  validation: 'Checking GSTIN, PAN, IFSC and account number formats…',
  cross_check: 'Comparing names, tax IDs and bank details across the form and documents…',
  external_verify: 'Asking the GST registry and the bank…',
  risk: 'Screening the debarred list and existing vendors…',
  decision: 'Applying the decision rules…',
  notify: 'Preparing follow-up…',
}

const DOC_TYPE: Record<string, string> = {
  gst_certificate: 'GST certificate', pan_card: 'PAN card', bank_proof: 'Bank proof', invoice: 'Invoice',
  other: 'Other document', unknown: 'Unrecognised',
}

const SLOT_LABEL: Record<string, string> = {
  gst_certificate: 'GST certificate', pan_card: 'PAN card', bank_proof: 'Cancelled cheque / bank letter',
}

const BANNER: Record<DisplayStatus, { title: string; tone: string; icon: React.ReactNode }> = {
  APPROVED: { title: 'Vendor approved', tone: 'bg-emerald-50 ring-emerald-200 text-emerald-900', icon: <CheckCircle2 className="size-6 text-emerald-600" /> },
  AWAITING_VENDOR: { title: 'Waiting on the vendor', tone: 'bg-amber-50 ring-amber-200 text-amber-900', icon: <AlertTriangle className="size-6 text-amber-600" /> },
  INTERNAL_REVIEW: { title: 'Sent to internal review', tone: 'bg-violet-50 ring-violet-200 text-violet-900', icon: <ShieldCheck className="size-6 text-violet-600" /> },
  REJECTED: { title: 'Vendor rejected', tone: 'bg-rose-50 ring-rose-200 text-rose-900', icon: <XCircle className="size-6 text-rose-600" /> },
  IN_PROGRESS: { title: 'In progress', tone: 'bg-sky-50 ring-sky-200 text-sky-900', icon: <Spinner /> },
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(t)
  }, [active])
  return now
}

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return ''
  if (ms < 100) return '<0.1 s'
  return `${(ms / 1000).toFixed(1)} s`
}

function StageIcon({ stage, decision }: { stage: Stage; decision: Decision | null }) {
  if (stage.status === 'pending') return <Circle className="size-6 text-slate-300" />
  if (stage.status === 'running') return <Spinner className="size-6 border-[3px]" />
  if (stage.status === 'failed' || stage.outcome === 'error') return <XCircle className="size-6 text-rose-600" />
  if (stage.key === 'decision' && decision?.display_status === 'REJECTED') return <XCircle className="size-6 text-rose-600" />
  if (stage.outcome === 'issues') return <AlertTriangle className="size-6 text-amber-500" />
  if (stage.outcome === 'blocked') return <MinusCircle className="size-6 text-slate-400" />
  return <CheckCircle2 className="size-6 text-emerald-600" />
}

interface DocDetail {
  filename: string | null
  type: string | null
  scanned?: boolean
  cached?: boolean | null
  latency_ms?: number | null
  error?: string | null
  file_problem?: string | null
}

function DocumentsRead({ details }: { details: Record<string, unknown> }) {
  const perDoc = details.per_document as Record<string, DocDetail> | undefined
  if (!perDoc) return null
  return (
    <ul className="mt-3 space-y-1.5">
      {Object.entries(perDoc).map(([slot, d]) => {
        const mismatch = d.type && d.type !== slot
        return (
          <li key={slot} className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg bg-slate-50 px-3 py-2 text-sm">
            <span className="text-slate-500">{SLOT_LABEL[slot] ?? slot}:</span>
            <span className="truncate font-medium text-slate-800">{d.filename}</span>
            {d.file_problem ? <span className="text-amber-700">· can't be opened</span>
              : d.error ? <span className="text-rose-700">· couldn't be read</span>
              : d.type && (
                <span className={cx(mismatch ? 'font-medium text-amber-700' : 'text-slate-600')}>
                  · identified as {DOC_TYPE[d.type] ?? d.type}{mismatch ? ' — not what this slot needs' : ''}
                </span>
              )}
            {d.scanned && <Tag>Scanned image</Tag>}
            {d.cached && <Tag>From cache</Tag>}
            {d.latency_ms != null && !d.cached && <span className="ml-auto text-xs tabular-nums text-slate-400">{fmtMs(d.latency_ms)}</span>}
          </li>
        )
      })}
    </ul>
  )
}

function StageRow({ stage, last, decision, issues, executed }: {
  stage: Stage; last: boolean; decision: Decision | null; issues: Record<string, string>; executed: boolean
}) {
  const failing = (stage.details.failing_rules as string[] | undefined) ?? []
  const showFailing = stage.key !== 'decision' && failing.length > 0
  return (
    <li className="relative flex gap-4 pb-6">
      {!last && <span className={cx('absolute left-3 top-8 -bottom-1 w-px', stage.status === 'done' ? 'bg-slate-300' : 'bg-slate-200')} />}
      <div className="relative z-10 bg-white"><StageIcon stage={stage} decision={decision} /></div>
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex items-baseline justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className={cx('text-sm font-semibold', stage.status === 'pending' ? 'text-slate-400' : 'text-slate-900')}>{stage.label}</h3>
            {stage.key === 'external_verify' && stage.status !== 'pending' && <Tag>Simulated provider</Tag>}
          </div>
          {/* Seeded runs were never executed, so they have no real stage durations to show. */}
          {stage.status === 'done' && executed && <span className="shrink-0 text-xs tabular-nums text-slate-400">{fmtMs(stage.duration_ms)}</span>}
        </div>
        {stage.status === 'running' && <p className="mt-0.5 text-sm text-brand-700">{RUNNING_TEXT[stage.key] ?? 'Working…'}</p>}
        {stage.status !== 'running' && stage.summary && (
          <p className={cx('mt-0.5 text-sm', stage.outcome === 'issues' ? 'text-slate-800' : 'text-slate-600',
            stage.outcome === 'error' && 'text-rose-700')}>{stage.summary}</p>
        )}
        {showFailing && (
          <div className="mt-2 flex flex-wrap gap-1">
            {failing.map((r) => (
              <span key={r} title={r} className="rounded-md bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-amber-200">
                {issues[r] ?? r}
              </span>
            ))}
          </div>
        )}
        {stage.key === 'read_documents' && stage.status === 'done' && <DocumentsRead details={stage.details} />}
      </div>
    </li>
  )
}

function DecisionBanner({ run, onReplay, replaying }: { run: Run; onReplay: () => void; replaying: boolean }) {
  const d = run.decision!
  const b = BANNER[d.display_status]
  return (
    <div className={cx('rounded-xl p-5 ring-1', b.tone)}>
      <div className="flex items-start gap-3">
        {b.icon}
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold">{b.title}</h2>
          <p className="mt-1 text-sm opacity-90">{d.summary}</p>
          {d.vendor_actions.length > 0 && (
            <div className="mt-4">
              <div className="text-xs font-semibold uppercase tracking-wide opacity-70">We'll ask the vendor for</div>
              <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm">
                {d.vendor_actions.map((a) => <li key={a}>{a}</li>)}
              </ul>
            </div>
          )}
          {d.display_status === 'INTERNAL_REVIEW' && (
            <p className="mt-3 text-sm opacity-80">The vendor is told only that their application is under review — not why.</p>
          )}
          {d.display_status === 'REJECTED' && (
            <p className="mt-3 text-sm opacity-80">The vendor receives a generic notice; the reason is not disclosed.</p>
          )}
          <div className="mt-5 flex flex-wrap gap-2">
            <Link to={`/cases/${run.case_id}`}
              className="inline-flex items-center gap-2 rounded-lg bg-white px-3.5 py-2 text-sm font-medium text-slate-800 shadow-sm ring-1 ring-black/10 hover:bg-slate-50">
              <ExternalLink className="size-4" /> Open case — evidence and history
            </Link>
            <Button variant="secondary" onClick={onReplay} disabled={replaying}>
              <PlayCircle className="size-4" /> {replaying ? 'Starting…' : 'Replay'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export function RunView() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const run = useQuery({
    queryKey: ['run', id],
    queryFn: () => getRun(id),
    refetchInterval: (q) => (q.state.data && !q.state.data.active ? false : 1000),
  })
  const rules = useQuery({
    queryKey: ['rules'],
    queryFn: () => api<{ id: string; issue: string }[]>('/api/rules'),
    staleTime: Infinity,
  })
  const replay = useMutation({
    mutationFn: () => replayCase(run.data!.case_id),
    onSuccess: (r) => navigate(`/runs/${r.run_id}`),
  })
  const active = run.data?.active ?? false
  const now = useNow(active)

  if (run.isLoading) return <div className="flex justify-center p-16"><Spinner /></div>
  if (run.error || !run.data) return <ErrorNote error={run.error ?? 'Run not found'} />
  const r = run.data
  const issues = Object.fromEntries((rules.data ?? []).map((x) => [x.id, x.issue]))
  const elapsed = r.started_at
    ? (r.finished_at ? new Date(r.finished_at).getTime() : now) - new Date(r.started_at).getTime()
    : 0
  const done = r.stages.filter((s) => s.status === 'done').length

  return (
    <>
      <Link to="/" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="size-4" /> Dashboard
      </Link>
      <PageHeader
        title={r.vendor_name ?? r.reference}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <span>{r.reference} · version {r.version}</span>
            <Tag tone={r.executed ? 'teal' : 'slate'}>{r.trigger_label}</Tag>
          </span>
        }
        actions={
          <div className="text-right">
            <div className="text-2xl font-semibold tabular-nums text-slate-900">
              {!r.executed ? '—' : r.started_at ? fmtMs(Math.max(elapsed, 0)) : 'Starting…'}
            </div>
            <div className="text-xs text-slate-500">{active ? `Running · ${done} of ${r.stages.length} stages` : r.executed ? 'Total time' : 'Not executed'}</div>
          </div>
        }
      />

      {!r.executed && (
        <div className="mb-6 flex flex-col gap-3 rounded-xl bg-slate-100 px-4 py-3 text-sm text-slate-700 sm:flex-row sm:items-center sm:justify-between">
          <p><strong className="font-semibold">Seeded sample.</strong> These results were pre-populated from the sample's known
            data — the pipeline was not executed. Replay to watch it run live.</p>
          <Button onClick={() => replay.mutate()} disabled={replay.isPending} className="shrink-0">
            <PlayCircle className="size-4" /> {replay.isPending ? 'Starting…' : 'Replay live'}
          </Button>
        </div>
      )}
      {(r.status === 'failed' || r.status === 'interrupted') && (
        <div className="mb-6 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-900 ring-1 ring-rose-200">
          <strong className="font-semibold">This run did not finish.</strong> {r.error} The case was sent to internal review
          (fail-safe: an incomplete check never approves a vendor).
        </div>
      )}
      {replay.error && <div className="mb-6"><ErrorNote error={replay.error} /></div>}

      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <Card className="p-5 sm:p-6">
          <ol>
            {r.stages.map((s, i) => (
              <StageRow key={s.key} stage={s} last={i === r.stages.length - 1} decision={r.decision} issues={issues}
                executed={r.executed} />
            ))}
          </ol>
        </Card>
        <div className="lg:sticky lg:top-6 lg:self-start">
          {r.decision ? (
            <DecisionBanner run={r} onReplay={() => replay.mutate()} replaying={replay.isPending} />
          ) : (
            <Card className="p-5 text-sm text-slate-500">
              <div className="flex items-center gap-2 font-medium text-slate-700"><Spinner /> Checks in progress</div>
              <p className="mt-2">The decision appears here when all checks finish. Every decision comes from fixed
                rules; the AI only reads the documents.</p>
            </Card>
          )}
        </div>
      </div>
    </>
  )
}
