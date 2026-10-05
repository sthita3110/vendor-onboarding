// One message as the vendor receives it (delivery is simulated), with how it was produced.
import { Mail } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { VendorMessage } from '../api'
import { dateTime } from '../lib/format'
import { cx } from '../lib/style'
import { Card, Tag } from './ui'

const KIND: Record<VendorMessage['kind'], { label: string; tone: string }> = {
  approved: { label: 'Approved', tone: 'bg-emerald-50 text-emerald-800 ring-emerald-200' },
  action_needed: { label: 'Action needed', tone: 'bg-amber-50 text-amber-800 ring-amber-200' },
  under_review: { label: 'Under review', tone: 'bg-violet-50 text-violet-800 ring-violet-200' },
  rejected: { label: 'Not proceeding', tone: 'bg-rose-50 text-rose-800 ring-rose-200' },
}

export function MessageCard({ m, showCase = false }: { m: VendorMessage; showCase?: boolean }) {
  const k = KIND[m.kind]
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
        <Mail className="size-4 text-slate-400" />
        <span className={cx('rounded-full px-2 py-0.5 text-xs font-medium ring-1', k.tone)}>{k.label}</span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-900">{m.subject}</span>
        <span className="text-xs text-slate-400">{dateTime(m.created_at)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 pt-3 text-xs text-slate-500">
        <span>To: {m.recipient ?? 'no contact email on file'}</span>
        {showCase && m.reference && (
          <Link to={`/cases/${m.case_id}`} className="font-medium text-brand-700 hover:underline">
            {m.reference} · {m.vendor_name}
          </Link>
        )}
        <span>{m.source === 'review' ? 'After a reviewer decision' : 'After the automated decision'}</span>
        <Tag>{m.status}</Tag>
        <Tag tone={m.ai_drafted ? 'teal' : 'slate'}>
          {m.ai_drafted ? 'AI-drafted wording · checklist from the rules' : m.generated_by}
        </Tag>
      </div>
      <pre className="mx-4 my-3 whitespace-pre-wrap rounded-lg bg-slate-50 p-4 font-sans text-sm leading-relaxed text-slate-800 ring-1 ring-slate-100">{m.body}</pre>
    </Card>
  )
}
