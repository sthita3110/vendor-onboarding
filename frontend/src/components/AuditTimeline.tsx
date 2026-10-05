// Audit trail in plain language: who did what, when. Raw event data stays one click away.
import type { AuditEvent } from '../api'
import { dateTime } from '../lib/format'
import { cx } from '../lib/style'

const STATUS_WORD: Record<string, string> = {
  APPROVED: 'Approved', REJECTED: 'Rejected', RECEIVED: 'In progress', AWAITING_VENDOR: 'Awaiting vendor',
  INTERNAL_REVIEW: 'In review',
}

function statusWord(s: unknown): string {
  const o = (s ?? {}) as { status?: string; sub_state?: string | null }
  return STATUS_WORD[o.sub_state ?? ''] ?? STATUS_WORD[o.status ?? ''] ?? String(o.status ?? '—')
}

function describe(e: AuditEvent): { text: string; tone?: 'bad' | 'good' | 'muted'; note?: string } {
  const d = e.data
  switch (e.event) {
    case 'case.created': return { text: d.source === 'seed' ? 'Case created as a seeded sample' : 'Case created' }
    case 'submission.received': {
      const docs = (d.documents as { carried_over?: boolean }[] | undefined) ?? []
      const carried = docs.filter((x) => x.carried_over).length
      return { text: `Version ${d.version} submitted · ${docs.length} document(s)${carried ? `, ${carried} carried over` : ''}` }
    }
    case 'seed.loaded': return { text: 'Loaded as pre-populated demo history', tone: 'muted', note: String(d.note ?? '') }
    case 'run.created': return { text: `Run #${e.run_id} queued (${d.trigger ?? 'submission'})`, tone: 'muted' }
    case 'run.replayed': return { text: `Replay requested for version ${d.submission_version}` }
    case 'run.started': return { text: `Run #${e.run_id} started`, tone: 'muted' }
    case 'run.completed': return { text: `Run #${e.run_id} completed`, tone: 'muted' }
    case 'run.failed': return { text: `Run #${e.run_id} failed in “${d.stage}”`, tone: 'bad', note: String(d.error ?? '') }
    case 'run.interrupted': return { text: `Run #${e.run_id} interrupted`, tone: 'bad', note: String(d.error ?? '') }
    case 'decision.made': {
      const word = statusWord(d)
      return { text: `Decision: ${word}`, tone: word === 'Approved' ? 'good' : word === 'Rejected' ? 'bad' : undefined,
        note: String(d.summary ?? '') }
    }
    case 'review.approve':
      return { text: 'Reviewer approved', tone: 'good', note: `“${d.reason}”` + (Array.isArray(d.overridden_rules) && d.overridden_rules.length ? ` · overrode ${(d.overridden_rules as string[]).join(', ')}` : '') }
    case 'review.reject': return { text: 'Reviewer rejected', tone: 'bad', note: `“${d.reason}”` }
    case 'review.request_info':
      return { text: 'Reviewer requested information', note: `To vendor: “${d.message}” · reason: “${d.reason}”` }
    case 'duplicate_submission.blocked': return { text: 'Duplicate submission blocked', tone: 'muted', note: 'Someone tried to start a new case for this vendor; they were sent here instead.' }
    case 'message.sent':
      return { text: `Message sent to the vendor: “${d.subject}”`, tone: 'muted',
        note: `${String(d.generated_by).startsWith('llm:') ? 'AI-drafted wording' : String(d.generated_by)} · to ${d.recipient ?? 'no email on file'} · delivery simulated` }
    case 'case.reapplied': return { text: `Reapplied as ${d.new_reference}`, note: 'A new application was created and linked to this rejected case.' }
    case 'status.changed':
      return { text: `Status: ${statusWord(d.before)} → ${statusWord(d.after)}`, tone: 'muted', note: d.reason ? String(d.reason) : undefined }
    default: return { text: e.event }
  }
}

export function AuditTimeline({ events }: { events: AuditEvent[] }) {
  return (
    <ol className="relative space-y-4 border-l border-slate-200 pl-6">
      {events.map((e) => {
        const { text, tone, note } = describe(e)
        return (
          <li key={e.id} className="relative">
            <span className={cx('absolute -left-[29px] top-1.5 size-2.5 rounded-full ring-4 ring-white',
              tone === 'bad' ? 'bg-rose-500' : tone === 'good' ? 'bg-emerald-500' : tone === 'muted' ? 'bg-slate-300' : 'bg-brand-600')} />
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className={cx('text-sm', tone === 'muted' ? 'text-slate-500' : 'font-medium text-slate-900')}>{text}</span>
              <span className="text-xs tabular-nums text-slate-400">{dateTime(e.at)}</span>
            </div>
            <div className="text-xs text-slate-500">by {e.actor}</div>
            {note && <p className="mt-1 text-sm text-slate-600">{note}</p>}
            <details className="mt-1 text-xs text-slate-400">
              <summary className="cursor-pointer select-none hover:text-slate-600">{e.event}</summary>
              <pre className="mt-1 max-h-48 overflow-auto rounded bg-slate-900 p-2 text-[11px] text-slate-100">{JSON.stringify(e.data, null, 2)}</pre>
            </details>
          </li>
        )
      })}
    </ol>
  )
}
