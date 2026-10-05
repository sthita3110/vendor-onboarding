// Cases the rules sent to a human, oldest first (the longest-waiting vendor is at the top).
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, ShieldCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { getReviewQueue } from '../api'
import { Card, ErrorNote, PageHeader, ReasonChips, Spinner, Tag } from '../components/ui'
import { relativeTime } from '../lib/format'

export function ReviewQueue() {
  const navigate = useNavigate()
  const queue = useQuery({ queryKey: ['review-queue'], queryFn: getReviewQueue, refetchInterval: 5000 })

  return (
    <>
      <PageHeader
        title="Review queue"
        subtitle="Cases that need a person's judgement — identity conflicts, bank mismatches, possible duplicates or debarment matches, and checks that couldn't complete. Oldest first."
      />
      {queue.isLoading && <div className="flex justify-center p-10"><Spinner /></div>}
      {queue.error && <ErrorNote error={queue.error} />}
      {queue.data && queue.data.length === 0 && (
        <Card className="flex flex-col items-center gap-2 p-12 text-center">
          <ShieldCheck className="size-8 text-emerald-600" />
          <p className="text-sm font-medium text-slate-900">Nothing waiting for review.</p>
          <p className="text-sm text-slate-500">Cases appear here when the rules need a human decision.</p>
        </Card>
      )}
      {queue.data && queue.data.length > 0 && (
        <Card>
          <ul className="divide-y divide-slate-100">
            {queue.data.map((c) => (
              <li key={c.id}>
                <button onClick={() => navigate(`/cases/${c.id}`)}
                  className="group flex w-full flex-col gap-2 px-4 py-4 text-left hover:bg-slate-50 sm:flex-row sm:items-center sm:gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-slate-900">{c.vendor_name}</span>
                      <span className="text-sm text-slate-500">{c.reference}</span>
                      {c.source === 'seed' && <Tag>Seeded sample</Tag>}
                    </div>
                    <div className="mt-1.5"><ReasonChips reasons={c.reasons} max={4} /></div>
                    {c.vendor_actions > 0 && (
                      <div className="mt-1 text-xs text-slate-500">Vendor also asked for {c.vendor_actions} item(s)</div>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-sm text-slate-500">
                    <span className="whitespace-nowrap">waiting {relativeTime(c.decided_at).replace(' ago', '')}</span>
                    <ArrowRight className="size-4 text-slate-300 group-hover:text-slate-500" />
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  )
}
