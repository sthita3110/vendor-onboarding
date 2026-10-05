// Resubmit on the vendor's behalf: same form, pre-filled; unchanged documents carry over.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Info } from 'lucide-react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { getCase, resubmitCase, type Slot, type SubmissionForm } from '../api'
import { Card, ErrorNote, PageHeader, Spinner } from '../components/ui'
import { VendorForm } from '../components/VendorForm'
import { formFromSubmission } from '../lib/form'

type Carried = { form: SubmissionForm; files: Partial<Record<Slot, File>> } | null

export function Resubmit() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // Arriving from "New vendor" after the duplicate-case check: carry over what was entered there.
  const carried = useLocation().state as Carried
  const kase = useQuery({ queryKey: ['case', id, undefined], queryFn: () => getCase(id) })
  const submit = useMutation({
    mutationFn: (v: { form: SubmissionForm; files: Partial<Record<Slot, File>> }) => resubmitCase(id, v.form, v.files),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['case', id] })
      queryClient.invalidateQueries({ queryKey: ['cases'] })
      navigate(`/runs/${r.run_id}`)
    },
  })

  if (kase.isLoading) return <div className="flex justify-center p-16"><Spinner /></div>
  if (kase.error || !kase.data) return <ErrorNote error={kase.error ?? 'Case not found'} />
  const c = kase.data

  // A carried file identical to the current version's (same name and size) is left to carry over.
  const carriedFiles: Partial<Record<Slot, File>> | undefined = carried
    ? Object.fromEntries(Object.entries(carried.files).filter(([slot, f]) => {
      const prev = c.documents.find((d) => d.slot === slot)
      return f && !(prev && prev.filename === f.name && prev.size === f.size)
    }))
    : undefined

  return (
    <>
      <Link to={`/cases/${id}`} className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="size-4" /> {c.reference}
      </Link>
      <PageHeader title={`Resubmit · ${c.vendor_name ?? c.reference}`}
        subtitle={`Creates version ${c.selected_version + 1} and runs every check again. Replace only the documents that changed.`} />
      {!c.can_resubmit ? (
        <Card className="p-8 text-sm text-slate-600">
          This case can't be resubmitted right now — only pending cases with no run in progress can be.
        </Card>
      ) : (
        <>
          {carried && (
            <div className="mb-6 flex items-start gap-3 rounded-xl bg-sky-50 px-4 py-3 text-sm text-sky-900 ring-1 ring-sky-200">
              <Info className="mt-0.5 size-4 shrink-0" />
              <p>Carried over what you entered on <strong className="font-semibold">New vendor</strong>. Documents identical
                to the current version are kept as they are. Review, then submit as version {c.selected_version + 1}.</p>
            </div>
          )}
          {c.run?.decision && c.run.decision.vendor_actions.length > 0 && (
            <Card className="mb-6 p-4">
              <div className="text-sm font-semibold text-slate-900">What the vendor was asked for</div>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
                {c.run.decision.vendor_actions.map((a) => <li key={a}>{a}</li>)}
              </ul>
            </Card>
          )}
          <VendorForm
            initialForm={carried?.form ?? formFromSubmission(c.submission)} initialFiles={carriedFiles}
            existingDocs={c.documents} existingVersion={c.selected_version}
            submitLabel={`Submit version ${c.selected_version + 1}`} submitting={submit.isPending} error={submit.error}
            onSubmit={(form, files) => submit.mutate({ form, files })}
          />
        </>
      )}
    </>
  )
}
