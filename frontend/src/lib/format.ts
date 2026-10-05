// Display helpers. API timestamps are ISO 8601 UTC ("...Z").

export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—'
  const seconds = Math.round((now - new Date(iso).getTime()) / 1000)
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.round(hours / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

export function percent(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value * 100)}%`
}

export function seconds(value: number | null | undefined): string {
  if (value == null) return '—'
  return value < 60 ? `${value.toFixed(1)} s` : `${Math.round(value / 60)} min`
}
