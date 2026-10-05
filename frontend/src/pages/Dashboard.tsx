import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Info, Plus, RotateCcw, Search } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getMetrics, listCases, resetDemo, type DisplayStatus, type Metrics } from '../api'
import { Button, ButtonLink, Card, ErrorNote, PageHeader, ReasonChips, Spinner, StatusBadge, Tag } from '../components/ui'
import { STATUS, cx } from '../lib/style'
import { percent, relativeTime, seconds } from '../lib/format'

const TABS: { key: DisplayStatus | 'ALL'; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'INTERNAL_REVIEW', label: 'In review' },
  { key: 'AWAITING_VENDOR', label: 'Awaiting vendor' },
  { key: 'APPROVED', label: 'Approved' },
  { key: 'REJECTED', label: 'Rejected' },
  { key: 'IN_PROGRESS', label: 'In progress' },
]

function Kpi({ label, value, hint, accent }: { label: string; value: string; hint?: string; accent?: string }) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
        {accent && <span className={cx('size-2 rounded-full', accent)} />}
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight text-slate-900 tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </Card>
  )
}

// Where cases are right now.
function StatusTiles({ m }: { m: Metrics }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
      <Kpi label="Total cases" value={String(m.total)} />
      <Kpi label="Approved" value={String(m.by_status.APPROVED)} accent={STATUS.APPROVED.dot} />
      <Kpi label="In review" value={String(m.by_status.INTERNAL_REVIEW)} accent={STATUS.INTERNAL_REVIEW.dot} />
      <Kpi label="Awaiting vendor" value={String(m.by_status.AWAITING_VENDOR)} accent={STATUS.AWAITING_VENDOR.dot} />
      <Kpi label="Rejected" value={String(m.by_status.REJECTED)} accent={STATUS.REJECTED.dot} />
    </div>
  )
}

// How well the process is working.
function Efficiency({ m }: { m: Metrics }) {
  return (
    <Card className="divide-y divide-slate-100">
      <div className="p-4">
        <div className="text-xs font-medium text-slate-500">Straight-through rate</div>
        <div className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{percent(m.straight_through_rate)}</div>
        <div className="mt-0.5 text-xs text-slate-500">Approved on the first run with no human touch</div>
      </div>
      <div className="p-4">
        <div className="text-xs font-medium text-slate-500">Median time to decision</div>
        <div className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{seconds(m.median_seconds_to_decision)}</div>
        <div className="mt-0.5 text-xs text-slate-500">
          {m.median_seconds_to_decision == null ? 'No executed runs yet — seeded samples have no real duration' : 'Submission to decision, executed runs'}
        </div>
      </div>
    </Card>
  )
}

function TopReasons({ m }: { m: Metrics }) {
  const max = Math.max(1, ...m.top_reasons.map((r) => r.count))
  return (
    <Card className="p-4">
      <h2 className="text-sm font-semibold text-slate-900">Why cases aren't approved</h2>
      <p className="text-xs text-slate-500">Most common open issues</p>
      {m.top_reasons.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500">No open issues.</p>
      ) : (
        <ul className="mt-4 space-y-3">
          {m.top_reasons.map((r) => (
            <li key={r.rule_id}>
              <div className="flex justify-between text-sm">
                <span className="text-slate-700">{r.issue}</span>
                <span className="tabular-nums text-slate-500">{r.count}</span>
              </div>
              <div className="mt-1 h-1.5 rounded-full bg-slate-100">
                <div className="h-1.5 rounded-full bg-brand-600" style={{ width: `${(r.count / max) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/** Demo-only reset, behind an explicit confirmation that says exactly what is deleted. */
function ResetDemo() {
  const [confirming, setConfirming] = useState(false)
  const queryClient = useQueryClient()
  const reset = useMutation({
    mutationFn: resetDemo,
    onSuccess: () => { setConfirming(false); queryClient.invalidateQueries() },
  })
  if (!confirming) {
    return (
      <Button variant="ghost" onClick={() => setConfirming(true)} title="Restore the six seeded demo cases">
        <RotateCcw className="size-4" /> Reset demo
      </Button>
    )
  }
  return (
    <div className="flex flex-col gap-2 rounded-xl bg-rose-50 p-3 text-sm text-rose-900 ring-1 ring-rose-200 sm:max-w-md">
      <p><strong className="font-semibold">Reset demo data?</strong> This deletes every case, run, review decision,
        message, uploaded file and audit entry, then restores the six seeded samples. It can't be undone.</p>
      {reset.error && <ErrorNote error={reset.error} />}
      <div className="flex gap-2">
        <button onClick={() => reset.mutate()} disabled={reset.isPending}
          className="rounded-lg bg-rose-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-800 disabled:opacity-50">
          {reset.isPending ? 'Resetting…' : 'Yes, reset everything'}
        </button>
        <Button variant="secondary" onClick={() => { setConfirming(false); reset.reset() }}>Cancel</Button>
      </div>
    </div>
  )
}

export function Dashboard() {
  const [tab, setTab] = useState<DisplayStatus | 'ALL'>('ALL')
  const [query, setQuery] = useState('')
  const navigate = useNavigate()

  const metrics = useQuery({ queryKey: ['metrics'], queryFn: getMetrics, refetchInterval: 5000 })
  const cases = useQuery({
    queryKey: ['cases', tab, query],
    queryFn: () => listCases({ status: tab === 'ALL' ? undefined : tab, q: query.trim() || undefined }),
    refetchInterval: 5000,
  })

  return (
    <>
      <PageHeader
        title="Vendor onboarding"
        subtitle="Every submission, its status, and why — across all runs."
        actions={<div className="flex flex-wrap items-start gap-2"><ResetDemo />
          <ButtonLink to="/new"><Plus className="size-4" /> New vendor</ButtonLink></div>}
      />

      {metrics.data && metrics.data.seeded_cases > 0 && (
        <div className="mb-6 flex items-start gap-3 rounded-xl bg-brand-50 px-4 py-3 text-sm text-brand-900 ring-1 ring-brand-100">
          <Info className="mt-0.5 size-4 shrink-0" />
          <p>
            <strong className="font-semibold">{metrics.data.seeded_cases} cases are seeded samples</strong> — pre-loaded
            demo history, not live runs. Open one and choose <strong className="font-semibold">Replay</strong> to run the
            full pipeline live, or submit a new vendor.
          </p>
        </div>
      )}

      {metrics.error && <ErrorNote error={metrics.error} />}
      {metrics.data && (
        <div className="grid gap-6 lg:grid-cols-[1fr_260px]">
          <div className="min-w-0 space-y-6">
            <StatusTiles m={metrics.data} />

            <Card>
              <div className="flex flex-col gap-3 border-b border-slate-200 p-4 md:flex-row md:items-center md:justify-between">
                <div className="-mx-1 flex gap-1 overflow-x-auto px-1">
                  {TABS.map((t) => {
                    const count = t.key === 'ALL' ? metrics.data.total : metrics.data.by_status[t.key]
                    return (
                      <button key={t.key} onClick={() => setTab(t.key)}
                        className={cx('whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                          tab === t.key ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100')}>
                        {t.label} <span className={cx('ml-1 tabular-nums', tab === t.key ? 'text-slate-300' : 'text-slate-400')}>{count}</span>
                      </button>
                    )
                  })}
                </div>
                <label className="relative block md:w-64">
                  <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
                  <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Vendor, GSTIN or VO-…"
                    className="w-full rounded-lg border-0 py-2 pl-9 pr-3 text-sm ring-1 ring-slate-300 placeholder:text-slate-400 focus:ring-2 focus:ring-brand-600 focus:outline-none" />
                </label>
              </div>

              {cases.isLoading && <div className="flex justify-center p-10"><Spinner /></div>}
              {cases.error && <div className="p-4"><ErrorNote error={cases.error} /></div>}
              {cases.data && cases.data.length === 0 && (
                <div className="p-10 text-center text-sm text-slate-500">
                  No cases here yet. <Link to="/new" className="font-medium text-brand-700 hover:underline">Submit a vendor</Link>.
                </div>
              )}
              {cases.data && cases.data.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-50 text-xs font-medium uppercase tracking-wide text-slate-500">
                      <tr>
                        <th className="px-4 py-2.5">Case</th>
                        <th className="px-4 py-2.5">Vendor</th>
                        <th className="px-4 py-2.5">Status</th>
                        <th className="px-4 py-2.5">Open issues</th>
                        <th className="px-4 py-2.5 text-right">Updated</th>
                        <th className="w-8" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {cases.data.map((c) => (
                        <tr key={c.id} onClick={() => navigate(`/cases/${c.id}`)}
                          className="group cursor-pointer hover:bg-slate-50">
                          <td className="px-4 py-3 align-top">
                            <div className="whitespace-nowrap font-medium text-slate-900">{c.reference}</div>
                            <div className="mt-1 flex flex-wrap gap-1">
                              <Tag tone={c.source === 'seed' ? 'slate' : 'teal'}>{c.source_label}</Tag>
                              {c.versions > 1 && <Tag>v{c.versions}</Tag>}
                              {c.previous_case_id && <Tag>Reapplication</Tag>}
                            </div>
                          </td>
                          <td className="min-w-48 px-4 py-3 align-top">
                            <div className="text-slate-900">{c.vendor_name ?? '—'}</div>
                            <div className="font-mono text-xs text-slate-500">{c.gstin ?? ''}</div>
                          </td>
                          <td className="px-4 py-3 align-top">
                            <StatusBadge status={c.display_status} />
                            {c.display_status === 'INTERNAL_REVIEW' && c.vendor_actions > 0 && (
                              <div className="mt-1 text-xs text-slate-500">also waiting on vendor: {c.vendor_actions}</div>
                            )}
                          </td>
                          <td className="px-4 py-3 align-top"><ReasonChips reasons={c.reasons} /></td>
                          <td className="whitespace-nowrap px-4 py-3 text-right align-top text-slate-500">{relativeTime(c.updated_at)}</td>
                          <td className="px-2 py-3 align-top text-slate-300 group-hover:text-slate-500">
                            <ArrowRight className="size-4" />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>
          <div className="space-y-6">
            <Efficiency m={metrics.data} />
            <TopReasons m={metrics.data} />
          </div>
        </div>
      )}
    </>
  )
}
