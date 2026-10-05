// Every message sent to vendors. Delivery is simulated: this is exactly what the vendor would receive.
import { useQuery } from '@tanstack/react-query'
import { getOutbox } from '../api'
import { MessageCard } from '../components/MessageCard'
import { Card, ErrorNote, PageHeader, Spinner } from '../components/ui'

export function Outbox() {
  const outbox = useQuery({ queryKey: ['outbox'], queryFn: getOutbox, refetchInterval: 5000 })
  return (
    <>
      <PageHeader title="Outbox"
        subtitle="Messages sent to vendors, newest first. Delivery is simulated — this is exactly what the vendor would receive. Wording may be AI-drafted; the list of requested items always comes from the rules or a reviewer, and internal reasons are never included." />
      {outbox.isLoading && <div className="flex justify-center p-10"><Spinner /></div>}
      {outbox.error && <ErrorNote error={outbox.error} />}
      {outbox.data && outbox.data.length === 0 && <Card className="p-10 text-center text-sm text-slate-500">No messages yet.</Card>}
      <div className="space-y-4">{outbox.data?.map((m) => <MessageCard key={m.id} m={m} showCase />)}</div>
    </>
  )
}
