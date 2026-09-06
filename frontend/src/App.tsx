import { useCallback, useEffect, useState } from 'react'

import Chat from '@/components/Chat'
import { ApiError, fetchHealth, type Health } from '@/lib/api'

type Status =
  | { kind: 'checking' }
  | { kind: 'connected'; health: Health }
  | { kind: 'failed'; message: string }

export default function App() {
  const [status, setStatus] = useState<Status>({ kind: 'checking' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setStatus({ kind: 'checking' })

    fetchHealth(controller.signal)
      .then((health) => setStatus({ kind: 'connected', health }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setStatus({
          kind: 'failed',
          message:
            error instanceof ApiError
              ? error.message
              : 'An unexpected error occurred while contacting the backend.',
        })
      })

    return () => controller.abort()
  }, [attempt])

  const recheck = useCallback(() => setAttempt((n) => n + 1), [])

  return (
    <main className="min-h-dvh px-6 py-20 sm:py-28">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-10">
        <header className="flex flex-col gap-3">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
            MRPL · On-premise
          </p>
          <h1 className="font-heading text-4xl leading-tight sm:text-5xl">
            Drishti Workbench
          </h1>
          <p className="max-w-prose text-[15px] leading-relaxed text-muted-foreground">
            A self-hosted agentic AI workbench that runs entirely within the
            plant network. No cloud services, no telemetry, no data leaving the
            premises.
          </p>
        </header>

        <section
          aria-live="polite"
          className="rounded-2xl border border-border bg-card p-7 shadow-[0_1px_2px_rgba(43,39,37,0.04)]"
        >
          <StatusPanel status={status} onRetry={recheck} />
        </section>

        <div className="border-t border-border pt-10">
          <Chat />
        </div>

        <footer className="text-[13px] leading-relaxed text-muted-foreground">
          Inference runs on a local Ollama instance. See{' '}
          <code className="rounded-md bg-muted px-1.5 py-0.5 text-[12px]">
            .env.example
          </code>{' '}
          — no API keys are required, by design.
        </footer>
      </div>
    </main>
  )
}

function StatusPanel({
  status,
  onRetry,
}: {
  status: Status
  onRetry: () => void
}) {
  if (status.kind === 'checking') {
    return (
      <div className="flex items-center gap-3">
        <Dot className="animate-pulse bg-muted-foreground/50" />
        <p className="text-[15px] text-muted-foreground">
          Checking backend…
        </p>
      </div>
    )
  }

  if (status.kind === 'connected') {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-3">
          <Dot className="bg-brand" />
          <p className="text-[15px] font-medium">
            Backend connected — fully offline
          </p>
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 border-t border-border pt-4 text-[13px]">
          <dt className="text-muted-foreground">Status</dt>
          <dd className="font-mono">{status.health.status}</dd>
          <dt className="text-muted-foreground">Offline</dt>
          <dd className="font-mono">{String(status.health.offline)}</dd>
        </dl>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-3">
        <Dot className="mt-[7px] bg-destructive" />
        <div className="flex flex-col gap-1.5">
          <p className="text-[15px] font-medium text-destructive">
            Backend unreachable
          </p>
          <p className="max-w-prose text-[13px] leading-relaxed text-muted-foreground">
            {status.message}
          </p>
        </div>
      </div>
      <div className="border-t border-border pt-4">
        <button
          type="button"
          onClick={onRetry}
          className="rounded-lg bg-primary px-3.5 py-2 text-[13px] font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          Try again
        </button>
      </div>
    </div>
  )
}

function Dot({ className = '' }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={`size-2 shrink-0 rounded-full ${className}`}
    />
  )
}
