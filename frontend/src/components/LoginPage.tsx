import { useState, type FormEvent } from 'react'

import AirGapBadge from '@/components/AirGapBadge'
import { ApiError, loginDemo, loginUser, type AuthedUser } from '@/lib/api'

interface LoginPageProps {
  onSuccess: (user: AuthedUser) => void
  backendError?: string | null
  onRetryBackend?: () => void
}

export default function LoginPage({
  onSuccess,
  backendError,
  onRetryBackend,
}: LoginPageProps) {
  const [username, setUsername] = useState('operator')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [demoLoading, setDemoLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password.trim()) {
      setError('Please enter both username and password.')
      return
    }

    setLoading(true)
    setError(null)

    try {
      const user = await loginUser(username.trim(), password)
      onSuccess(user)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('An unexpected error occurred during sign in.')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleDemoAccess = async () => {
    setDemoLoading(true)
    setError(null)

    try {
      const user = await loginDemo()
      onSuccess(user)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('Failed to initiate judge demo session.')
      }
    } finally {
      setDemoLoading(false)
    }
  }

  return (
    <div className="relative flex min-h-dvh items-center justify-center bg-background px-6">
      <AirGapBadge />

      <div className="w-full max-w-md rounded-3xl border border-border/80 bg-gradient-to-b from-card/90 to-card/40 p-8 shadow-sm backdrop-blur-sm">
        <div className="flex flex-col gap-2 text-center">
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
            MRPL Mangalore · On-Premise Sovereign AI
          </p>
          <h1 className="font-heading text-3xl font-medium tracking-tight text-foreground">
            Sign in to Drishti
          </h1>
          <p className="text-[13px] text-muted-foreground">
            Local authentication. Credentials never leave this machine.
          </p>
        </div>

        {backendError && (
          <div className="mt-6 rounded-2xl border border-destructive/40 bg-destructive/10 p-4 text-center">
            <p className="text-[13px] font-medium text-destructive">{backendError}</p>
            {onRetryBackend && (
              <button
                type="button"
                onClick={onRetryBackend}
                className="mt-2 rounded-lg bg-destructive/20 px-3 py-1 text-xs font-semibold text-destructive hover:bg-destructive/30"
              >
                Retry Connection
              </button>
            )}
          </div>
        )}

        <form onSubmit={handleLogin} className="mt-6 flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="username"
              className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground"
            >
              Username
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={loading || demoLoading}
              placeholder="e.g. operator"
              required
              className="rounded-2xl border border-border bg-card px-4 py-3 text-[15px] shadow-[0_1px_2px_rgba(43,39,37,0.05)] outline-none focus-visible:border-ring disabled:opacity-60"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="password"
              className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading || demoLoading}
              placeholder="••••••••"
              required
              className="rounded-2xl border border-border bg-card px-4 py-3 text-[15px] shadow-[0_1px_2px_rgba(43,39,37,0.05)] outline-none focus-visible:border-ring disabled:opacity-60"
            />
          </div>

          {error && (
            <p className="text-center text-[13px] font-medium text-destructive">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading || demoLoading}
            className="mt-1 w-full rounded-xl bg-brand px-4 py-2.5 text-xs font-semibold text-brand-foreground shadow-sm transition-all hover:bg-brand/90 disabled:opacity-50"
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <div className="relative my-6 flex items-center justify-center">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-border" />
          </div>
          <span className="relative bg-card px-3 text-[11px] uppercase tracking-wider text-muted-foreground">
            or
          </span>
        </div>

        <div className="flex flex-col gap-2 text-center">
          <button
            type="button"
            onClick={handleDemoAccess}
            disabled={loading || demoLoading}
            className="w-full rounded-xl border border-border/80 bg-muted/30 px-4 py-2.5 text-xs font-medium text-foreground transition-colors hover:bg-muted/80 disabled:opacity-50"
          >
            {demoLoading ? 'Connecting…' : 'Continue as Judge / Demo Access'}
          </button>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            No credentials needed — signs in as a read-visibility demo account, logged like any other session.
          </p>
        </div>
      </div>
    </div>
  )
}
