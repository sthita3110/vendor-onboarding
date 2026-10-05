// The vendor submission form, shared by "New vendor" and "Resubmit".
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, FlaskConical, Info, RotateCcw } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import {
  fetchSampleFile, getSample, getStates, listSamples,
  type DocumentView, type EntityType, type Slot, type SubmissionForm,
} from '../api'
import { EMPTY_FORM, formFromSubmission } from '../lib/form'
import { cx } from '../lib/style'
import { FileSlot } from './FileSlot'
import { Button, Card, ErrorNote, Spinner } from './ui'


const ENTITY_TYPES: { value: EntityType; label: string }[] = [
  { value: 'company', label: 'Private / public limited company' },
  { value: 'llp', label: 'Limited liability partnership (LLP)' },
  { value: 'partnership', label: 'Partnership firm' },
  { value: 'proprietorship', label: 'Sole proprietorship' },
]

const SLOTS: { slot: Slot; label: string; hint: string }[] = [
  { slot: 'gst_certificate', label: 'GST registration certificate', hint: 'Form GST REG-06 · PDF, PNG or JPG' },
  { slot: 'pan_card', label: 'PAN card', hint: 'PDF, PNG or JPG' },
  { slot: 'bank_proof', label: 'Cancelled cheque or bank letter', hint: 'PDF, PNG or JPG' },
]

// Presentation hint only: the server decides what is missing (COMP-01) and the vendor is asked for it.
const REQUIRED: [string, (f: SubmissionForm) => string][] = [
  ['Legal name', (f) => f.legal_name], ['Business type', (f) => f.entity_type], ['Address', (f) => f.address.line1],
  ['City', (f) => f.address.city], ['State', (f) => f.address.state], ['PIN code', (f) => f.address.pin_code],
  ['Contact name', (f) => f.contact_name], ['Contact email', (f) => f.contact_email], ['GSTIN', (f) => f.gstin],
  ['PAN', (f) => f.pan], ['Account holder', (f) => f.bank.account_holder_name],
  ['Account number', (f) => f.bank.account_number], ['IFSC', (f) => f.bank.ifsc], ['Bank name', (f) => f.bank.bank_name],
]


const INPUT = 'w-full rounded-lg border-0 px-3 py-2 text-sm text-slate-900 ring-1 ring-slate-300 placeholder:text-slate-400 focus:ring-2 focus:ring-brand-600 focus:outline-none'

function Field({ label, required, hint, className, children }: {
  label: string; required?: boolean; hint?: string; className?: string; children: ReactNode
}) {
  return (
    <label className={cx('block', className)}>
      <span className="mb-1.5 block text-sm font-medium text-slate-700">
        {label}{required && <span className="text-slate-400"> *</span>}
      </span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  )
}

function Section({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <Card className="p-5 sm:p-6">
      <div className="grid gap-6 md:grid-cols-[220px_1fr]">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          <p className="mt-1 text-sm text-slate-500">{description}</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">{children}</div>
      </div>
    </Card>
  )
}

export interface VendorFormProps {
  initialForm?: SubmissionForm
  /** Resubmission: documents of the current version, carried over unless replaced. */
  existingDocs?: DocumentView[]
  existingVersion?: number
  submitLabel: string
  submitting: boolean
  error: unknown
  onSubmit: (form: SubmissionForm, files: Partial<Record<Slot, File>>, sampleId?: string) => void
}

export function VendorForm({ initialForm, existingDocs, existingVersion, submitLabel, submitting, error, onSubmit }: VendorFormProps) {
  const start = initialForm ?? EMPTY_FORM
  const [form, setForm] = useState<SubmissionForm>(start)
  const [files, setFiles] = useState<Partial<Record<Slot, File>>>({})
  const [sampleId, setSampleId] = useState<string | undefined>()
  const [loadingSample, setLoadingSample] = useState(false)
  const [sampleError, setSampleError] = useState<unknown>(null)

  const samples = useQuery({ queryKey: ['samples'], queryFn: listSamples })
  const states = useQuery({ queryKey: ['states'], queryFn: getStates, staleTime: Infinity })
  const existingBySlot: Partial<Record<Slot, DocumentView>> = Object.fromEntries((existingDocs ?? []).map((d) => [d.slot, d]))

  const set = (patch: Partial<SubmissionForm>) => setForm((f) => ({ ...f, ...patch }))
  const setAddress = (patch: Partial<SubmissionForm['address']>) => setForm((f) => ({ ...f, address: { ...f.address, ...patch } }))
  const setBank = (patch: Partial<SubmissionForm['bank']>) => setForm((f) => ({ ...f, bank: { ...f.bank, ...patch } }))

  async function loadSample(id: string) {
    if (!id) return
    setLoadingSample(true)
    setSampleError(null)
    try {
      const s = await getSample(id)
      const loaded = await Promise.all(s.files.map(async (f) => [f.slot, await fetchSampleFile(f.url, f.filename)] as const))
      // Resubmission: a sample file identical to the current version's (same name and size) is left to carry
      // over, as a vendor would only re-upload what changed.
      const changed = loaded.filter(([slot, file]) => {
        const prev = existingBySlot[slot]
        return !(prev && prev.filename === file.name && prev.size === file.size)
      })
      setForm(formFromSubmission(s.submission))
      setFiles(Object.fromEntries(changed))
      setSampleId(id)
    } catch (e) {
      setSampleError(e)
    } finally {
      setLoadingSample(false)
    }
  }

  function reset() {
    setForm(start)
    setFiles({})
    setSampleId(undefined)
  }

  const missingFields = REQUIRED.filter(([, get]) => !get(form).trim()).map(([label]) => label)
  const missingDocs = SLOTS.filter((s) => !files[s.slot] && !existingBySlot[s.slot]).map((s) => s.label)
  const loadedSample = samples.data?.find((s) => s.id === sampleId)

  return (
    <>
      <Card className="mb-6 flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
          <FlaskConical className="size-4 text-brand-700" /> Demo samples
        </div>
        <select value={sampleId ?? ''} onChange={(e) => loadSample(e.target.value)} disabled={loadingSample}
          className={cx(INPUT, 'sm:max-w-md')} aria-label="Load a demo sample">
          <option value="">Load a sample vendor…</option>
          {samples.data?.map((s) => <option key={s.id} value={s.id}>{s.id} — {s.title}</option>)}
        </select>
        {loadingSample && <Spinner />}
        {(sampleId || form !== start || Object.keys(files).length > 0) && (
          <Button variant="ghost" onClick={reset} className="sm:ml-auto">
            <RotateCcw className="size-4" /> {initialForm ? 'Undo changes' : 'Clear form'}
          </Button>
        )}
      </Card>
      {sampleError != null && <div className="mb-6"><ErrorNote error={sampleError} /></div>}
      {loadedSample && (
        <div className="mb-6 flex items-start gap-3 rounded-xl bg-brand-50 px-4 py-3 text-sm text-brand-900 ring-1 ring-brand-100">
          <Info className="mt-0.5 size-4 shrink-0" />
          <p><strong className="font-semibold">Loaded sample {loadedSample.id}: {loadedSample.title}.</strong>{' '}
            {loadedSample.description} You can edit anything before submitting; it runs through the live pipeline.</p>
        </div>
      )}

      <form className="space-y-6" onSubmit={(e) => { e.preventDefault(); onSubmit(form, files, sampleId) }}>
        <Section title="Company" description="As registered with GST.">
          <Field label="Legal name" required className="sm:col-span-2">
            <input className={INPUT} value={form.legal_name} onChange={(e) => set({ legal_name: e.target.value })} />
          </Field>
          <Field label="Trade name" hint="If different from the legal name">
            <input className={INPUT} value={form.trade_name} onChange={(e) => set({ trade_name: e.target.value })} />
          </Field>
          <Field label="Business type" required>
            <select className={INPUT} value={form.entity_type} onChange={(e) => set({ entity_type: e.target.value as EntityType })}>
              <option value="">Select…</option>
              {ENTITY_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </Field>
          <Field label="Registered address" required className="sm:col-span-2">
            <input className={INPUT} value={form.address.line1} onChange={(e) => setAddress({ line1: e.target.value })} />
          </Field>
          <Field label="City" required>
            <input className={INPUT} value={form.address.city} onChange={(e) => setAddress({ city: e.target.value })} />
          </Field>
          <div className="grid grid-cols-[1fr_120px] gap-4">
            <Field label="State" required>
              <select className={INPUT} value={form.address.state} onChange={(e) => setAddress({ state: e.target.value })}>
                <option value="">Select…</option>
                {states.data?.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </Field>
            <Field label="PIN code" required>
              <input className={INPUT} inputMode="numeric" value={form.address.pin_code} onChange={(e) => setAddress({ pin_code: e.target.value })} />
            </Field>
          </div>
        </Section>

        <Section title="Tax" description="GSTIN for the state of the address above, and the business PAN.">
          <Field label="GSTIN" required hint="15 characters, e.g. 29AAACL4821K1ZD">
            <input className={cx(INPUT, 'font-mono uppercase')} value={form.gstin} onChange={(e) => set({ gstin: e.target.value })} />
          </Field>
          <Field label="PAN" required hint="10 characters, e.g. AAACL4821K">
            <input className={cx(INPUT, 'font-mono uppercase')} value={form.pan} onChange={(e) => set({ pan: e.target.value })} />
          </Field>
        </Section>

        <Section title="Bank account" description="Where payments will be sent. Verified with the bank before approval.">
          <Field label="Account holder name" required className="sm:col-span-2">
            <input className={INPUT} value={form.bank.account_holder_name} onChange={(e) => setBank({ account_holder_name: e.target.value })} />
          </Field>
          <Field label="Account number" required>
            <input className={cx(INPUT, 'font-mono')} inputMode="numeric" value={form.bank.account_number} onChange={(e) => setBank({ account_number: e.target.value })} />
          </Field>
          <Field label="IFSC" required hint="11 characters, e.g. HDFC0000075">
            <input className={cx(INPUT, 'font-mono uppercase')} value={form.bank.ifsc} onChange={(e) => setBank({ ifsc: e.target.value })} />
          </Field>
          <Field label="Bank name" required className="sm:col-span-2">
            <input className={INPUT} value={form.bank.bank_name} onChange={(e) => setBank({ bank_name: e.target.value })} />
          </Field>
        </Section>

        <Section title="Contact" description="Who we contact about this onboarding.">
          <Field label="Contact name" required>
            <input className={INPUT} value={form.contact_name} onChange={(e) => set({ contact_name: e.target.value })} />
          </Field>
          <Field label="Contact email" required>
            <input className={INPUT} type="email" value={form.contact_email} onChange={(e) => set({ contact_email: e.target.value })} />
          </Field>
        </Section>

        <Section title="Documents" description="We read each document and check it against the details above.">
          {SLOTS.map((s) => (
            <div key={s.slot} className={s.slot === 'bank_proof' ? 'sm:col-span-2' : ''}>
              <FileSlot label={s.label} hint={s.hint} file={files[s.slot]}
                onChange={(file) => setFiles((f) => ({ ...f, [s.slot]: file }))}
                existing={existingBySlot[s.slot] && {
                  filename: existingBySlot[s.slot]!.filename,
                  note: `Kept from version ${existingVersion} unless you replace it`,
                }} />
            </div>
          ))}
        </Section>

        {error != null && <ErrorNote error={error} />}

        <Card className="sticky bottom-4 flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-slate-500">
            {missingFields.length + missingDocs.length === 0
              ? 'Everything is filled in.'
              : `${missingFields.length + missingDocs.length} required item(s) are empty — you can still submit; the vendor will be asked for them.`}
          </p>
          <Button type="submit" disabled={submitting}>
            {submitting ? <><Spinner className="border-white/40 border-t-white" /> Submitting…</> : <>{submitLabel} <ArrowRight className="size-4" /></>}
          </Button>
        </Card>
      </form>
    </>
  )
}
