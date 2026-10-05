// Case page: the decision, the evidence behind it, what the AI read, and the full history.
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  AlertTriangle, ArrowLeft, CheckCircle2, ChevronDown, ExternalLink, FileText, MinusCircle, PlayCircle, Upload, XCircle,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  getAudit, getCase, openDocument, replayCase,
  type CaseDetail, type CheckResultView, type ExtractionView, type RuleView,
} from '../api'
import { AuditTimeline } from '../components/AuditTimeline'
import { Evidence } from '../components/Evidence'
import { Button, Card, ErrorNote, ReasonChips, Spinner, StatusBadge, Tag } from '../components/ui'
import { dateTime, relativeTime } from '../lib/format'
import { cx } from '../lib/style'

type TabKey = 'checks' | 'documents' | 'details' | 'audit'

const OUTCOME_LABEL: Record<string, { text: string; tone: string }> = {
  VENDOR_ACTION: { text: 'Vendor to fix', tone: 'bg-amber-50 text-amber-800 ring-amber-200' },
  REVIEW: { text: 'Needs review', tone: 'bg-violet-50 text-violet-800 ring-violet-200' },
  REJECT: { text: 'Reject', tone: 'bg-rose-50 text-rose-800 ring-rose-200' },
}

const FIELD_LABEL: Record<string, string> = {
  legal_name: 'Legal name', trade_name: 'Trade name', gstin: 'GSTIN', constitution_of_business: 'Constitution',
  principal_address: 'Principal address', state: 'State', name: 'Name', pan: 'PAN',
  account_holder_name: 'Account holder', account_number: 'Account number', ifsc: 'IFSC', bank_name: 'Bank',
  invoice_number: 'Invoice number', invoice_date: 'Invoice date', total_amount: 'Total amount',
}
const MONO = new Set(['gstin', 'pan', 'ifsc', 'account_number', 'invoice_number'])
const SLOT_LABEL: Record<string, string> = {
  gst_certificate: 'GST registration certificate', pan_card: 'PAN card', bank_proof: 'Cancelled cheque / bank letter',
}
const DOC_TYPE: Record<string, string> = {
  gst_certificate: 'GST certificate', pan_card: 'PAN card', bank_proof: 'Bank proof', invoice: 'Invoice', other: 'Other document',
}

function StatusIcon({ status, size = 'size-5' }: { status: RuleView['status']; size?: string }) {
  if (status === 'pass') return <CheckCircle2 className={cx(size, 'text-emerald-600')} />
  if (status === 'fail') return <AlertTriangle className={cx(size, 'text-amber-500')} />
  if (status === 'error') return <XCircle className={cx(size, 'text-rose-600')} />
  return <MinusCircle className={cx(size, 'text-slate-400')} />
}

function ResultItem({ r }: { r: CheckResultView }) {
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex gap-2">
        <span className="mt-0.5"><StatusIcon status={r.status} size="size-4" /></span>
        <div className="min-w-0 flex-1">
          <div className="text-sm text-slate-900">{r.title}</div>
          {r.status === 'blocked' && (
            <div className="text-sm text-slate-500">Not checked because of an earlier finding: {r.blocked_by_issue ?? r.blocked_by}</div>
          )}
          {r.detail && r.status !== 'blocked' && <div className="mt-0.5 text-sm text-slate-600">{r.detail}</div>}
          {r.vendor_text && (
            <div className="mt-1.5 rounded-md bg-amber-50 px-2.5 py-1.5 text-sm text-amber-900 ring-1 ring-amber-200">
              <span className="font-medium">Asked the vendor: </span>{r.vendor_text}
            </div>
          )}
          {r.status !== 'blocked' && <Evidence ev={r.evidence} />}
        </div>
      </div>
    </li>
  )
}

function RuleCard({ rule }: { rule: RuleView }) {
  const [open, setOpen] = useState(rule.status !== 'pass')
  const label = rule.status === 'fail' ? OUTCOME_LABEL[rule.outcome_if_failed]
    : rule.status === 'blocked' ? { text: 'Not fully checked', tone: 'bg-slate-100 text-slate-600 ring-slate-200' }
    : rule.status === 'error' ? { text: "Couldn't check", tone: 'bg-rose-50 text-rose-800 ring-rose-200' } : null
  return (
    <div className="border-t border-slate-100 first:border-t-0">
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50">
        <StatusIcon status={rule.status} />
        <span className="flex-1 text-sm font-medium text-slate-900">{rule.name}</span>
        {label && <span className={cx('rounded-full px-2 py-0.5 text-xs font-medium ring-1', label.tone)}>{label.text}</span>}
        <span className="hidden font-mono text-[11px] text-slate-400 sm:inline">{rule.rule_id}</span>
        <ChevronDown className={cx('size-4 text-slate-400 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <ul className="divide-y divide-slate-100 px-4 pb-4 pl-12">
          {rule.results.map((r, i) => <ResultItem key={i} r={r} />)}
        </ul>
      )}
    </div>
  )
}

function ChecksTab({ c }: { c: CaseDetail }) {
  if (!c.checks.length) {
    return <Card className="p-8 text-center text-sm text-slate-500">Checks for this version haven't finished yet.</Card>
  }
  return (
    <div className="space-y-4">
      {c.checks.map((g) => {
        const bad = g.rules.filter((r) => r.status !== 'pass').length
        return (
          <Card key={g.group}>
            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
              <h3 className="text-sm font-semibold text-slate-900">{g.group}</h3>
              <span className="text-xs text-slate-500">{bad ? `${bad} of ${g.rules.length} need attention` : `All ${g.rules.length} passed`}</span>
            </div>
            {g.rules.map((r) => <RuleCard key={r.rule_id} rule={r} />)}
          </Card>
        )
      })}
    </div>
  )
}

function Grounding({ g }: { g: string | null }) {
  if (g === 'text') return <span className="text-xs font-medium text-emerald-700">Found in document text</span>
  if (g === 'image') return <span className="text-xs font-medium text-slate-500">Scan · format-checked</span>
  if (g === 'unverified') return <span className="text-xs font-medium text-amber-700">Not found in document text</span>
  return <span className="text-xs text-slate-400">—</span>
}

function DocumentsTab({ c }: { c: CaseDetail }) {
  const [openError, setOpenError] = useState<unknown>(null)
  const docs = c.documents
  return (
    <div className="space-y-4">
      {openError != null && <ErrorNote error={openError} />}
      {docs.map((d) => {
        const x = c.extractions[d.slot] as ExtractionView | undefined
        const seeded = x?.meta.source === 'seed'
        const mismatch = x?.classified_type && x.classified_type !== d.slot
        return (
          <Card key={d.id}>
            <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-4 py-3">
              <FileText className="size-5 text-brand-700" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-slate-900">{SLOT_LABEL[d.slot]}</div>
                <div className="truncate text-xs text-slate-500">{d.filename}{d.carried_over && ' · carried over from the previous version'}</div>
              </div>
              <Button variant="secondary" onClick={() => openDocument(d.url).catch(setOpenError)}>
                <ExternalLink className="size-4" /> Open
              </Button>
            </div>
            <div className="px-4 py-3">
              {!x ? <p className="text-sm text-slate-500">Not read yet.</p>
                : x.file_problem ? <p className="text-sm text-amber-800">This file couldn't be opened: {x.file_problem}.</p>
                : x.extraction_error ? <p className="text-sm text-rose-700">Reading failed: {x.extraction_error}</p>
                : (
                  <>
                    <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
                      <span className="text-slate-500">Identified as</span>
                      <span className={cx('font-medium', mismatch ? 'text-amber-700' : 'text-slate-900')}>
                        {DOC_TYPE[x.classified_type ?? ''] ?? x.classified_type}{mismatch && ' — not what this slot needs'}
                      </span>
                      {seeded ? <Tag>Seeded sample data · not read by the model</Tag>
                        : <Tag>Read by {String(x.meta.model)}{x.meta.cached ? ' · from cache' : ''}</Tag>}
                    </div>
                    <table className="w-full text-sm">
                      <tbody className="divide-y divide-slate-100">
                        {Object.entries(x.fields).map(([k, f]) => (
                          <tr key={k}>
                            <td className="w-36 py-2 pr-3 align-top text-slate-500">{FIELD_LABEL[k] ?? k}</td>
                            <td className="py-2 pr-3 align-top">
                              <div className={cx('text-slate-900', MONO.has(k) && 'font-mono')}>{f.value}</div>
                              {f.quote && <div className="mt-0.5 text-xs text-slate-400">“{f.quote.replace(/\n/g, ' ')}”</div>}
                            </td>
                            <td className="py-2 text-right align-top"><Grounding g={f.grounded} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                )}
            </div>
          </Card>
        )
      })}
    </div>
  )
}

function DetailsTab({ c }: { c: CaseDetail }) {
  const s = c.submission as Record<string, any>
  const rows: [string, string | null | undefined, boolean?][] = [
    ['Legal name', s.legal_name], ['Trade name', s.trade_name], ['Business type', s.entity_type],
    ['Address', [s.address?.line1, s.address?.city, s.address?.state, s.address?.pin_code].filter(Boolean).join(', ')],
    ['GSTIN', s.gstin, true], ['PAN', s.pan, true],
    ['Account holder', s.bank?.account_holder_name], ['Account number', s.bank?.account_number, true],
    ['IFSC', s.bank?.ifsc, true], ['Bank', s.bank?.bank_name],
    ['Contact', [s.contact_name, s.contact_email].filter(Boolean).join(' · ')],
  ]
  return (
    <Card className="p-4">
      <dl className="divide-y divide-slate-100">
        {rows.map(([k, v, mono]) => (
          <div key={k} className="grid grid-cols-[160px_1fr] gap-3 py-2 text-sm">
            <dt className="text-slate-500">{k}</dt>
            <dd className={cx(v ? 'text-slate-900' : 'text-slate-400', mono && 'font-mono')}>{v || 'Not provided'}</dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}

export function CaseView() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const [version, setVersion] = useState<number | undefined>()
  const [tab, setTab] = useState<TabKey>('checks')
  const kase = useQuery({
    queryKey: ['case', id, version],
    queryFn: () => getCase(id, version),
    refetchInterval: (q) => (q.state.data?.latest_run?.status === 'running' || q.state.data?.latest_run?.status === 'queued' ? 2000 : false),
  })
  const audit = useQuery({ queryKey: ['audit', id], queryFn: () => getAudit(id), enabled: tab === 'audit' })
  const replay = useMutation({ mutationFn: () => replayCase(id), onSuccess: (r) => navigate(`/runs/${r.run_id}`) })

  if (kase.isLoading) return <div className="flex justify-center p-16"><Spinner /></div>
  if (kase.error || !kase.data) return <ErrorNote error={kase.error ?? 'Case not found'} />
  const c = kase.data
  const decision = c.run?.decision
  const latestVersion = c.versions_detail[c.versions_detail.length - 1]?.version
  const viewingOld = c.selected_version !== latestVersion

  const TABS: { key: TabKey; label: string }[] = [
    { key: 'checks', label: 'What we checked' }, { key: 'documents', label: 'Documents' },
    { key: 'details', label: 'Submitted details' }, { key: 'audit', label: 'Audit trail' },
  ]

  return (
    <>
      <Link to="/" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="size-4" /> Dashboard
      </Link>

      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{c.vendor_name ?? c.reference}</h1>
            <StatusBadge status={c.display_status} />
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-slate-500">
            <span>{c.reference}</span>
            {c.gstin && <span className="font-mono">{c.gstin}</span>}
            <Tag tone={c.source === 'seed' ? 'slate' : 'teal'}>{c.source_label}</Tag>
            <span>· created {relativeTime(c.created_at)}</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {c.versions_detail.length > 1 && (
            <select value={c.selected_version} onChange={(e) => setVersion(Number(e.target.value))} aria-label="Version"
              className="rounded-lg border-0 py-2 pl-3 pr-8 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-brand-600">
              {c.versions_detail.map((v) => <option key={v.version} value={v.version}>Version {v.version}{v.version === latestVersion ? ' (current)' : ''}</option>)}
            </select>
          )}
          <Button variant="secondary" onClick={() => replay.mutate()} disabled={!c.can_replay || replay.isPending}
            title="Execute the full pipeline again on the current version">
            <PlayCircle className="size-4" /> {replay.isPending ? 'Starting…' : 'Replay'}
          </Button>
          {c.can_resubmit && (
            <Button onClick={() => navigate(`/cases/${c.id}/resubmit`)}>
              <Upload className="size-4" /> Resubmit for vendor
            </Button>
          )}
        </div>
      </div>
      {replay.error && <div className="mb-4"><ErrorNote error={replay.error} /></div>}
      {viewingOld && (
        <div className="mb-4 rounded-lg bg-sky-50 px-4 py-2.5 text-sm text-sky-900 ring-1 ring-sky-200">
          Viewing version {c.selected_version}. The current version is {latestVersion}.
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="min-w-0">
          <div className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200">
            {TABS.map((t) => (
              <button key={t.key} onClick={() => setTab(t.key)}
                className={cx('-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium',
                  tab === t.key ? 'border-brand-700 text-brand-800' : 'border-transparent text-slate-500 hover:text-slate-800')}>
                {t.label}
              </button>
            ))}
          </div>
          {tab === 'checks' && <ChecksTab c={c} />}
          {tab === 'documents' && <DocumentsTab c={c} />}
          {tab === 'details' && <DetailsTab c={c} />}
          {tab === 'audit' && (
            <Card className="p-5">
              {audit.isLoading ? <Spinner /> : audit.error ? <ErrorNote error={audit.error} /> : <AuditTimeline events={audit.data ?? []} />}
            </Card>
          )}
        </div>

        <aside className="space-y-4">
          <Card className="p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Decision · version {c.selected_version}</div>
            {decision ? (
              <>
                <div className="mt-2"><StatusBadge status={decision.display_status} /></div>
                <p className="mt-2 text-sm text-slate-700">{decision.summary}</p>
                {decision.reasons.length > 0 && <div className="mt-3"><ReasonChips reasons={decision.reasons} max={6} /></div>}
                {decision.vendor_actions.length > 0 && (
                  <div className="mt-4">
                    <div className="text-xs font-semibold text-slate-500">Asked of the vendor</div>
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
                      {decision.vendor_actions.map((a) => <li key={a}>{a}</li>)}
                    </ul>
                  </div>
                )}
                {decision.display_status === 'INTERNAL_REVIEW' && (
                  <p className="mt-3 text-xs text-slate-500">The vendor is told only that the application is under review.</p>
                )}
                <div className="mt-3 text-xs text-slate-400">Rules {decision.rule_catalog_version} · {dateTime(decision.decided_at)}</div>
              </>
            ) : <p className="mt-2 text-sm text-slate-500">Checks in progress…</p>}
          </Card>

          <Card className="p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">History</div>
            <ul className="mt-3 space-y-3">
              {[...c.runs_detail].reverse().map((r) => (
                <li key={r.id}>
                  <Link to={`/runs/${r.id}`} className="group block rounded-lg p-2 -m-2 hover:bg-slate-50">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-slate-900 group-hover:text-brand-800">
                        {r.trigger_label} · v{r.version}
                      </span>
                      {r.decision ? <StatusBadge status={r.decision.display_status} />
                        : <span className="text-xs text-slate-500">{r.status}</span>}
                    </div>
                    <div className="mt-0.5 text-xs text-slate-500">Run #{r.id} · {dateTime(r.created_at)} · view run →</div>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </aside>
      </div>
    </>
  )
}
