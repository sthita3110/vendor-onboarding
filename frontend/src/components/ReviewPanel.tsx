// A reviewer's decision on an internal-review case. Every action needs a name and a reason; Approve is disabled
// (with the reason shown) when checks didn't run or the vendor still owes items.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, MessageSquare, XCircle } from 'lucide-react'
import { useState } from 'react'
import { reviewCase, type CaseDetail, type ReviewActionView } from '../api'
import { cx } from '../lib/style'
import { Button, Card, ErrorNote, ReasonChips } from './ui'

type Action = ReviewActionView['action']

const REVIEWER_KEY = 'vo-reviewer'
const readReviewer = () => { try { return localStorage.getItem(REVIEWER_KEY) ?? '' } catch { return '' } }
const saveReviewer = (v: string) => { try { localStorage.setItem(REVIEWER_KEY, v) } catch { /* storage unavailable */ } }

const CHOICES: { action: Action; label: string; icon: React.ReactNode; tone: string; hint: string }[] = [
  { action: 'approve', label: 'Approve', icon: <CheckCircle2 className="size-4" />, tone: 'emerald',
    hint: 'Accept the findings above and approve the vendor. They are recorded as overridden, with your reason.' },
  { action: 'request_info', label: 'Request info', icon: <MessageSquare className="size-4" />, tone: 'amber',
    hint: 'Ask the vendor for something specific. The case waits for their resubmission.' },
  { action: 'reject', label: 'Reject', icon: <XCircle className="size-4" />, tone: 'rose',
    hint: 'Reject the application. The vendor receives a generic notice; they may reapply later.' },
]

const INPUT = 'w-full rounded-lg border-0 px-3 py-2 text-sm ring-1 ring-slate-300 placeholder:text-slate-400 focus:ring-2 focus:ring-brand-600 focus:outline-none'

export function ReviewPanel({ c }: { c: CaseDetail }) {
  const queryClient = useQueryClient()
  const [action, setAction] = useState<Action | null>(null)
  const [reviewer, setReviewer] = useState(readReviewer)
  const [reason, setReason] = useState('')
  const [message, setMessage] = useState('')
  const submit = useMutation({
    mutationFn: () => reviewCase(c.id, { action: action!, reviewer, reason, message: message || undefined }),
    onSuccess: () => {
      saveReviewer(reviewer.trim())
      queryClient.invalidateQueries({ queryKey: ['case', c.id] })
      queryClient.invalidateQueries({ queryKey: ['audit', c.id] })
      queryClient.invalidateQueries({ queryKey: ['cases'] })
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      queryClient.invalidateQueries({ queryKey: ['review-queue'] })
    },
  })
  const choice = CHOICES.find((x) => x.action === action)
  const ready = action && reviewer.trim() && reason.trim() && (action !== 'request_info' || message.trim())

  return (
    <Card className="p-4 ring-violet-200">
      <div className="text-xs font-semibold uppercase tracking-wide text-violet-700">Your decision</div>
      <p className="mt-1 text-sm text-slate-600">The rules couldn't decide this case on their own.</p>
      {c.reasons.length > 0 && <div className="mt-2"><ReasonChips reasons={c.reasons} max={6} /></div>}

      <div className="mt-4 grid grid-cols-3 gap-1.5">
        {CHOICES.map((x) => {
          const disabled = x.action === 'approve' && !c.can_approve
          return (
            <button key={x.action} type="button" disabled={disabled} onClick={() => setAction(x.action)}
              title={disabled ? c.approve_blocked_reason ?? '' : x.hint}
              className={cx('flex flex-col items-center gap-1 rounded-lg px-2 py-2 text-xs font-medium ring-1 transition-colors',
                'disabled:cursor-not-allowed disabled:opacity-40',
                action === x.action
                  ? x.tone === 'emerald' ? 'bg-emerald-50 text-emerald-800 ring-emerald-400'
                    : x.tone === 'amber' ? 'bg-amber-50 text-amber-800 ring-amber-400' : 'bg-rose-50 text-rose-800 ring-rose-400'
                  : 'bg-white text-slate-700 ring-slate-200 hover:bg-slate-50')}>
              {x.icon}{x.label}
            </button>
          )
        })}
      </div>
      {!c.can_approve && c.approve_blocked_reason && (
        <p className="mt-2 text-xs text-slate-500">Approve unavailable: {c.approve_blocked_reason}</p>
      )}

      {choice && (
        <form className="mt-4 space-y-3" onSubmit={(e) => { e.preventDefault(); submit.mutate() }}>
          <p className="text-xs text-slate-500">{choice.hint}</p>
          {action === 'request_info' && (
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-700">Message to the vendor *</span>
              <textarea className={INPUT} rows={3} value={message} onChange={(e) => setMessage(e.target.value)}
                placeholder="e.g. Please send a letter on bank letterhead confirming the account holder." />
            </label>
          )}
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-700">
              Reason{action === 'request_info' ? ' (internal)' : ''} *
            </span>
            <textarea className={INPUT} rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder={action === 'approve' ? 'e.g. Account is the proprietor\'s; confirmed against the GST certificate'
                : action === 'reject' ? 'e.g. GSTIN belongs to a different legal entity' : 'Why you need this'} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-700">Your name *</span>
            <input className={INPUT} value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Reviewer" />
          </label>
          {submit.error && <ErrorNote error={submit.error} />}
          <Button type="submit" className="w-full" disabled={!ready || submit.isPending}>
            {submit.isPending ? 'Saving…' : `Confirm: ${choice.label}`}
          </Button>
          <p className="text-[11px] text-slate-400">Recorded in the audit trail with your name and reason.</p>
        </form>
      )}
    </Card>
  )
}
