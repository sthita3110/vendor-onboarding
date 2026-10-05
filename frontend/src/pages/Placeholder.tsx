import { Card, PageHeader } from '../components/ui'

// Temporary screens until steps 4b/4c fill them in.
export function Placeholder({ title, step }: { title: string; step: string }) {
  return (
    <>
      <PageHeader title={title} />
      <Card className="p-10 text-center text-sm text-slate-500">This screen arrives in step {step}.</Card>
    </>
  )
}
