// Renders a check result's evidence for a procurement reader: form vs document, the quote it came from,
// how names were compared, what the (simulated) provider said. Raw JSON only under "Technical details".
import type { ReactNode } from 'react'
import { cx } from '../lib/style'
import { Tag } from './ui'

type Ev = Record<string, unknown>

const str = (v: unknown) => (v == null || v === '' ? null : String(v))
const DOC = { gst_certificate: 'GST certificate', pan_card: 'PAN card', bank_proof: 'Bank proof', form: 'Form' } as Record<string, string>
const TIER: Record<string, string> = {
  EXACT: 'Exact match', NORMALIZED: 'Match after standardising (e.g. "Private Limited" = "Pvt Ltd")',
  TRADE_NAME: 'Match via the trade name registered on the GST certificate', MISMATCH: 'Different names',
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[130px_1fr] gap-3 py-1 text-sm">
      <div className="text-slate-500">{label}</div>
      <div className="min-w-0 break-words text-slate-800">{children}</div>
    </div>
  )
}

function Quote({ quote, page }: { quote: unknown; page: unknown }) {
  if (!str(quote)) return null
  return (
    <Row label="Read from">
      <span className="rounded bg-amber-50 px-1.5 py-0.5 font-mono text-xs text-amber-900">“{String(quote).replace(/\n/g, ' ')}”</span>
      {page != null && <span className="ml-1 text-xs text-slate-400">page {String(page)}</span>}
    </Row>
  )
}

function Compare({ ev }: { ev: Ev }) {
  const form = str(ev.form_value), doc = str(ev.doc_value)
  const same = form === doc
  return (
    <>
      <Row label="On the form"><span className="font-mono">{form ?? '—'}</span></Row>
      <Row label={`On the ${DOC[String(ev.source_doc)] ?? 'document'}`}>
        <span className={cx('font-mono', !same && 'rounded bg-rose-50 px-1 text-rose-800')}>{doc ?? '—'}</span>
      </Row>
      <Quote quote={ev.quote} page={ev.page} />
    </>
  )
}

function Names({ ev }: { ev: Ev }) {
  const onlyC = (ev.only_in_candidate as string[] | undefined) ?? []
  const onlyA = (ev.only_in_anchor as string[] | undefined) ?? []
  return (
    <>
      <Row label="Compared">{str(ev.candidate)}</Row>
      <Row label="Against">{str(ev.anchor)} <span className="text-xs text-slate-400">(legal name on the GST certificate)</span></Row>
      <Row label="Result">{TIER[String(ev.match_tier)] ?? String(ev.match_tier)}</Row>
      {(onlyC.length > 0 || onlyA.length > 0) && (
        <Row label="Differences">
          <span className="flex flex-wrap gap-1">
            {onlyC.map((t) => <span key={`c${t}`} className="rounded bg-rose-50 px-1.5 text-xs text-rose-800">+ {t}</span>)}
            {onlyA.map((t) => <span key={`a${t}`} className="rounded bg-sky-50 px-1.5 text-xs text-sky-800">− {t}</span>)}
          </span>
        </Row>
      )}
      <Quote quote={ev.quote} page={ev.page} />
    </>
  )
}

function Provider({ resp }: { resp: Ev }) {
  return (
    <div className="mt-1 rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <Tag>Simulated provider</Tag>
        <span className="font-mono">{str(resp.provider)}</span>
        {resp.fixture === false && <Tag>Sandbox default response</Tag>}
      </div>
      <Row label="Status">{str(resp.status)}</Row>
      {str(resp.holder_name) && <Row label="Account holder">{str(resp.holder_name)}</Row>}
      {str(resp.legal_name) && <Row label="Registered name">{str(resp.legal_name)}</Row>}
      {str(resp.gstin) && <Row label="GSTIN"><span className="font-mono">{str(resp.gstin)}</span></Row>}
      {str(resp.account_number) && <Row label="Account"><span className="font-mono">{str(resp.account_number)} · {str(resp.ifsc)}</span></Row>}
    </div>
  )
}

function Matches({ items }: { items: Ev[] }) {
  return (
    <Row label="Matched record">
      <ul className="space-y-1">
        {items.map((m, i) => (
          <li key={i} className="rounded bg-slate-50 px-2 py-1 text-xs ring-1 ring-slate-200">
            {str(m.vendor_id) ? <>Vendor <strong>{str(m.vendor_id)}</strong> · {str(m.legal_name)} · PAN {str(m.pan)} · bank {str(m.bank_account_number)} / {str(m.ifsc)}</>
              : <><strong>{str(m.entity_name)}</strong> · PAN {str(m.pan)} · {str(m.list_source)} · {str(m.reason)}</>}
          </li>
        ))}
      </ul>
    </Row>
  )
}

export function Evidence({ ev }: { ev: Ev }) {
  const keys = Object.keys(ev)
  if (keys.length === 0) return null
  const parts: ReactNode[] = []
  if ('form_value' in ev && 'doc_value' in ev) parts.push(<Compare key="cmp" ev={ev} />)
  if ('match_tier' in ev) parts.push(<Names key="names" ev={ev} />)
  if (ev.adapter_response && typeof ev.adapter_response === 'object') parts.push(<Provider key="prov" resp={ev.adapter_response as Ev} />)
  if (Array.isArray(ev.problems) && ev.problems.length) {
    parts.push(<Row key="prob" label="Problems"><ul className="list-disc pl-4">{(ev.problems as string[]).map((p) => <li key={p}>{p}</li>)}</ul></Row>)
  }
  if (Array.isArray(ev.matches) && ev.matches.length) parts.push(<Matches key="m" items={ev.matches as Ev[]} />)
  if ('gstin_state' in ev) {
    parts.push(<Row key="st" label="States">GSTIN registered in <strong>{str(ev.gstin_state)}</strong> (code {str(ev.gstin_state_code)}) · address in <strong>{str(ev.address_state)}</strong></Row>)
  }
  if ('pan_in_gstin' in ev) {
    parts.push(<Row key="pan" label="PAN check">GSTIN <span className="font-mono">{str(ev.gstin)}</span> contains PAN <span className="font-mono">{str(ev.pan_in_gstin)}</span>; compared with <span className="font-mono">{str(ev.pan)}</span></Row>)
  }
  if ('pan_holder_type' in ev) {
    parts.push(<Row key="ph" label="PAN type">4th character “{str(ev.pan_holder_char)}” = {str(ev.pan_holder_type)} · business type: {str(ev.entity_type)}</Row>)
  }
  if (Array.isArray(ev.missing_fields)) parts.push(<Row key="mf" label="Not found">{(ev.missing_fields as string[]).join(', ')}</Row>)
  if ('classified_type' in ev && 'slot' in ev) {
    parts.push(<Row key="ct" label="Identified as">{str(ev.classified_type)} <span className="text-xs text-slate-400">(file {str(ev.filename)})</span></Row>)
  }

  return (
    <div className="mt-2">
      {parts}
      <details className="mt-1 text-xs text-slate-400">
        <summary className="cursor-pointer select-none hover:text-slate-600">Technical details</summary>
        <pre className="mt-1 max-h-64 overflow-auto rounded bg-slate-900 p-3 text-[11px] leading-relaxed text-slate-100">{JSON.stringify(ev, null, 2)}</pre>
      </details>
    </div>
  )
}
