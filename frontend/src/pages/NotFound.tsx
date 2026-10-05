import { ButtonLink, Card, PageHeader } from '../components/ui'

export function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" />
      <Card className="flex flex-col items-center gap-4 p-10 text-center text-sm text-slate-500">
        That page doesn't exist.
        <ButtonLink to="/" variant="secondary">Back to the dashboard</ButtonLink>
      </Card>
    </>
  )
}
