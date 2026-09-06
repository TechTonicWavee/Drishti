import { useCallback, useEffect, useState } from 'react'

import AirGapBadge from '@/components/AirGapBadge'
import Chat from '@/components/Chat'
import KnowledgeBase from '@/components/KnowledgeBase'
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
    <main className="min-h-dvh px-6 py-16 sm:py-24">
      <AirGapBadge />

      <div className="mx-auto flex w-full max-w-3xl flex-col gap-12">
        <header className="flex flex-col gap-3">
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
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

        {/* Compact when healthy: a green light does not deserve the same space
            as the work. It expands only when something is wrong. */}
        <section aria-live="polite">
          <StatusLine status={status} onRetry={recheck} />
        </section>

        <KnowledgeBase />

        <div className="border-t border-border pt-10">
          <Chat />
        </div>

        <footer className="border-t border-border pt-6 text-[12px] leading-relaxed text-muted-foreground">
          Inference, retrieval, code execution and document generation all run
          on this machine. See{' '}
          <code className="rounded-md bg-muted px-1.5 py-0.5 text-[11px]">
            docs/air_gap_proof.md
          </code>{' '}
          to verify it.
        </footer>
      </div>
    </main>
  )
}

function StatusLine({
  status,
  onRetry,
}: {
  status: Status
  onRetry: () => void
}) {
  if (status.kind === 'checking') {
    return (
      <p className="flex items-center gap-2.5 text-[13px] text-muted-foreground">
        <span className="size-2 shrink-0 animate-pulse rounded-full bg-muted-foreground/50" />
        Checking backend…
      </p>
    )
  }

  if (status.kind === 'connected') {
    return (
      <p className="flex items-center gap-2.5 text-[13px]">
        <span className="size-2 shrink-0 rounded-full bg-brand" />
        <span className="font-medium">Backend connected — fully offline</span>
        <span className="font-mono text-[11px] text-muted-foreground">
          status={status.health.status} · offline={String(status.health.offline)}
        </span>
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3.5">
      <p className="flex items-center gap-2.5 text-[14px] font-medium text-destructive">
        <span className="size-2 shrink-0 rounded-full bg-destructive" />
        Backend unreachable
      </p>
      <p className="max-w-prose text-[13px] leading-relaxed text-muted-foreground">
        {status.message}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="self-start rounded-xl bg-primary px-3.5 py-2 text-[13px] font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        Try again
      </button>
    </div>
  )
}
