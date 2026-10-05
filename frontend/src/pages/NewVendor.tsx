import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, PlayCircle, Upload, Users } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { asDuplicate, createCase, replayCase, type DuplicateCase, type Slot, type SubmissionForm } from '../api'
import { Button, PageHeader, StatusBadge } from '../components/ui'
import { VendorForm } from '../components/VendorForm'

type Entered = { form: SubmissionForm; files: Partial<Record<Slot, File>>; sampleId?: string }

/** The entity already has a case: offer only the actions that keep one case per entity. */
function DuplicatePanel({ dup, entered }: { dup: DuplicateCase; entered: Entered }) {
  const navigate = useNavigate()
  const panel = useRef<HTMLDivElement>(null)
  const replay = useMutation({ mutationFn: (caseId: number) => replayCase(caseId), onSuccess: (r) => navigate(`/runs/${r.run_id}`) })
  useEffect(() => {
    // Braces matter: newer browsers return a Promise from scrollIntoView, which React would treat as a cleanup.
    panel.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [dup])

  return (
    <div ref={panel} className="rounded-xl bg-sky-50 p-5 ring-1 ring-sky-200">
      <div className="flex items-start gap-3">
        <Users className="mt-0.5 size-5 shrink-0 text-sky-700" />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-sky-950">This vendor already has an onboarding case</h2>
          <p className="mt-1 text-sm text-sky-900">
            Nothing was created. To avoid duplicate onboarding work, continue on the existing case:
            <strong className="font-semibold"> resubmit</strong> to correct it with what you entered here, or
            <strong className="font-semibold"> replay</strong> to reprocess its current documents.
          </p>
          <ul className="mt-4 space-y-3">
            {dup.matches.map((c) => (
              <li key={c.id} className="rounded-lg bg-white p-4 ring-1 ring-sky-100">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-slate-900">{c.vendor_name}</span>
                  <span className="text-sm text-slate-500">{c.reference} · version {c.selected_version}</span>
                  <StatusBadge status={c.display_status} />
                </div>
                <div className="mt-0.5 font-mono text-xs text-slate-500">{c.gstin}</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Link to={`/cases/${c.id}`}
                    className="inline-flex items-center gap-2 rounded-lg bg-white px-3.5 py-2 text-sm font-medium text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50">
                    <ExternalLink className="size-4" /> Open existing case
                  </Link>
                  {c.can_resubmit && (
                    <Button onClick={() => navigate(`/cases/${c.id}/resubmit`, { state: entered })}>
                      <Upload className="size-4" /> Resubmit with these details
                    </Button>
                  )}
                  {c.can_replay && (
                    <Button variant="secondary" onClick={() => replay.mutate(c.id)} disabled={replay.isPending}>
                      <PlayCircle className="size-4" /> {replay.isPending ? 'Starting…' : 'Replay existing case'}
                    </Button>
                  )}
                </div>
                {!c.can_resubmit && (c.display_status === 'APPROVED' || c.display_status === 'REJECTED') && (
                  <p className="mt-2 text-xs text-slate-500">
                    This case is {c.display_status === 'APPROVED' ? 'approved' : 'rejected'} and final, so it can't be resubmitted.
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}

export function NewVendor() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const submit = useMutation({
    mutationFn: (v: Entered) => createCase(v.form, v.files, v.sampleId),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['cases'] })
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      navigate(`/runs/${created.run_id}`)
    },
  })
  const dup = asDuplicate(submit.error)

  return (
    <>
      <PageHeader title="New vendor" subtitle="Vendor details and documents. Checks run automatically after you submit." />
      <VendorForm
        submitLabel="Submit for checks" submitting={submit.isPending}
        error={dup ? null : submit.error}
        notice={dup && submit.variables ? <DuplicatePanel dup={dup} entered={submit.variables} /> : null}
        onSubmit={(form, files, sampleId) => submit.mutate({ form, files, sampleId })}
      />
    </>
  )
}
