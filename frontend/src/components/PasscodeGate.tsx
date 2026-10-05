// Shows a passcode screen only when the API answers 401; otherwise renders the app untouched.
// Locally (APP_PASSCODE unset) the API never returns 401, so this screen never appears.
import { useQueryClient } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { ApiError, api, getPasscode, onUnauthorized, setPasscode } from '../api'
import { Button } from './ui'

type State = 'checking' | 'locked' | 'open'

export function PasscodeGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>('checking')
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const queryClient = useQueryClient()

  useEffect(() => {
    api('/api/rules')
      .then(() => setState('open'))
      .catch((e) => setState(e instanceof ApiError && e.status === 401 ? 'locked' : 'open'))
    return onUnauthorized(() => setState('locked'))
  }, [])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setPasscode(value.trim())
    try {
      await api('/api/rules')
      setError(null)
      setState('open')
      queryClient.invalidateQueries()
    } catch {
      setPasscode(null)
      setError('That passcode is not correct.')
    }
  }

  if (state === 'checking') return null
  if (state === 'open') return <>{children}</>

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-sm ring-1 ring-slate-200">
        <div className="mb-6 flex size-11 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
          <KeyRound className="size-5" />
        </div>
        <h1 className="text-lg font-semibold text-slate-900">Vendor Onboarding</h1>
        <p className="mt-1 text-sm text-slate-500">Enter the access passcode to continue.</p>
        <input
          type="password" autoFocus value={value} onChange={(e) => { setValue(e.target.value); setError(null) }}
          placeholder="Passcode" aria-label="Passcode"
          className="mt-6 w-full rounded-lg border-0 px-3 py-2.5 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-brand-600 focus:outline-none"
        />
        {error && <p className="mt-2 text-sm text-rose-700">{error}</p>}
        <Button type="submit" className="mt-4 w-full" disabled={!value.trim()}>Continue</Button>
        {getPasscode() === null && (
          <p className="mt-4 text-xs text-slate-400">The passcode is kept only for this browser session.</p>
        )}
      </form>
    </div>
  )
}
