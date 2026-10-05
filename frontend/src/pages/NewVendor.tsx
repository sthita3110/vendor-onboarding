import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { createCase, type Slot, type SubmissionForm } from '../api'
import { PageHeader } from '../components/ui'
import { VendorForm } from '../components/VendorForm'

export function NewVendor() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const submit = useMutation({
    mutationFn: (v: { form: SubmissionForm; files: Partial<Record<Slot, File>>; sampleId?: string }) =>
      createCase(v.form, v.files, v.sampleId),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['cases'] })
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      navigate(`/runs/${created.run_id}`)
    },
  })
  return (
    <>
      <PageHeader title="New vendor" subtitle="Vendor details and documents. Checks run automatically after you submit." />
      <VendorForm submitLabel="Submit for checks" submitting={submit.isPending} error={submit.error}
        onSubmit={(form, files, sampleId) => submit.mutate({ form, files, sampleId })} />
    </>
  )
}
