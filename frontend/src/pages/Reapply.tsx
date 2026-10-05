// Reapply after rejection: a genuinely new application, created as a new case linked to the rejected one.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ShieldAlert } from 'lucide-react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { getCase, reapplyCase, type Slot, type SubmissionForm } from '../api'
import { Card, ErrorNote, PageHeader, ReasonChips, Spinner } from '../components/ui'
import { VendorForm } from '../components/VendorForm'
import { dateTime } from '../lib/format'
import { formFromSubmission } from '../lib/form'

type Carried = { form: SubmissionForm; files: Partial<Record<Slot, File>> } | null

export function Reapply() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const carried = useLocation().state as Carried  // from the duplicate-case panel on New vendor
  const kase = useQuery({ queryKey: ['case', id, undefined], queryFn: () => getCase(id) })
  const submit = useMutation({
    mutationFn: (v: { form: SubmissionForm; files: Partial<Record<Slot, File>> }) => reapplyCase(id, v.form, v.files),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['cases'] })
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      navigate(`/runs/${r.run_id}`)
    },
  })

  if (kase.isLoading) return <div className="flex justify-center p-16"><Spinner /></div>
  if (kase.error || !kase.data) return <ErrorNote error={kase.error ?? 'Case not found'} />
  const c = kase.data

  return (
    <>
      <Link to={`/cases/${id}`} className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="size-4" /> {c.reference}
      </Link>
      <PageHeader title={`Reapply · ${c.vendor_name ?? c.reference}`}
        subtitle={`A new application, created as a new case linked to ${c.reference}. The rejected case stays as it is.`} />
      {!c.can_reapply ? (
        <Card className="p-8 text-sm text-slate-600">
          Reapplying is only possible for a rejected case when the vendor has no other open case.
        </Card>
      ) : (
        <>
          <div className="mb-6 flex items-start gap-3 rounded-xl bg-violet-50 px-4 py-3 text-sm text-violet-950 ring-1 ring-violet-200">
            <ShieldAlert className="mt-0.5 size-4 shrink-0 text-violet-700" />
            <div>
              <p><strong className="font-semibold">{c.reference} was rejected</strong>{c.decided_at && ` on ${dateTime(c.decided_at)}`}.
                Because of that, this new application will always be reviewed by a person before it can be approved,
                and every check, including the debarred list, runs again.</p>
              {c.reasons.length > 0 && <div className="mt-2"><ReasonChips reasons={c.reasons} max={6} /></div>}
            </div>
          </div>
          <VendorForm
            initialForm={carried?.form ?? formFromSubmission(c.submission)} initialFiles={carried?.files}
            submitLabel="Submit new application" submitting={submit.isPending} error={submit.error}
            onSubmit={(form, files) => submit.mutate({ form, files })}
          />
        </>
      )}
    </>
  )
}
