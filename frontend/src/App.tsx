import { useCallback, useEffect, useRef, useState } from 'react'

import AirGapBadge from '@/components/AirGapBadge'
import AuditView from '@/components/AuditView'
import Chat from '@/components/Chat'
import KnowledgeBase from '@/components/KnowledgeBase'
import ThreadSidebar, { type ThreadSidebarHandle } from '@/components/ThreadSidebar'
import { ApiError, fetchHealth, type Health } from '@/lib/api'

// Often enough that a dead backend is obvious within a demo beat, rarely
// enough to be invisible in the network log.
const HEALTH_POLL_MS = 10_000

type Status =
  | { kind: 'checking' }
  | { kind: 'connected'; health: Health }
  | { kind: 'failed'; message: string }

export default function App() {
  const [status, setStatus] = useState<Status>({ kind: 'checking' })
  const [attempt, setAttempt] = useState(0)

  // Polled, not checked once. A one-shot check goes on displaying "Backend
  // connected" long after the backend has died — which is exactly when the
  // indicator matters, and is how a dead server looked healthy while every
  // request beneath it failed.
  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    setStatus((current) =>
      current.kind === 'checking' ? current : { kind: 'checking' },
    )

    const poll = () => {
      fetchHealth(controller.signal)
        .then((health) => {
          if (!cancelled) setStatus({ kind: 'connected', health })
        })
        .catch((error: unknown) => {
          if (cancelled) return
          if (error instanceof DOMException && error.name === 'AbortError') return
          setStatus({
            kind: 'failed',
            message:
              error instanceof ApiError
                ? error.message
                : 'An unexpected error occurred while contacting the backend.',
          })
        })
    }

    poll()
    const timer = setInterval(poll, HEALTH_POLL_MS)
    return () => {
      cancelled = true
      controller.abort()
      clearInterval(timer)
    }
  }, [attempt])

  const recheck = useCallback(() => setAttempt((n) => n + 1), [])

  // The conversation currently open. null is a fresh, unsaved one.
  const [threadId, setThreadId] = useState<string | null>(null)
  const sidebarRef = useRef<ThreadSidebarHandle>(null)

  // Refresh the list after each turn, so a new thread and the title the model
  // generated for it appear without polling.
  const onTurnEnd = useCallback(() => sidebarRef.current?.refresh(), [])
  const newChat = useCallback(() => setThreadId(null), [])

  // A tab, not a route: the audit trail is an admin/compliance view bolted
  // onto the same page rather than a separate page, so it needs no router.
  const [view, setView] = useState<'workbench' | 'audit'>('workbench')

  return (
    <div className="flex min-h-dvh">
      <AirGapBadge />

      {/* Sticky so the conversation list stays put while the transcript
          scrolls — the list is navigation, not part of the document. */}
      <div className="sticky top-0 hidden h-dvh md:block">
        <ThreadSidebar
          ref={sidebarRef}
          activeThreadId={threadId}
          onSelect={setThreadId}
          onNewChat={newChat}
        />
      </div>

      <main className="min-w-0 flex-1 px-6 py-16 sm:py-24">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-12">
        <header className="flex flex-col gap-3">
          <div className="flex items-baseline justify-between gap-4">
            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
              MRPL · On-premise
            </p>
            <nav className="flex gap-1 rounded-full border border-border bg-card p-0.5 text-[12px]">
              {(['workbench', 'audit'] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setView(tab)}
                  aria-current={view === tab ? 'true' : undefined}
                  className={[
                    'rounded-full px-3 py-1.5 font-medium capitalize transition-colors',
                    view === tab
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:text-foreground',
                  ].join(' ')}
                >
                  {tab === 'audit' ? 'Audit log' : 'Workbench'}
                </button>
              ))}
            </nav>
          </div>
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

        {view === 'audit' ? (
          <AuditView />
        ) : (
          <>
            <KnowledgeBase />

            <div className="border-t border-border pt-10">
              <Chat
                threadId={threadId}
                onThreadId={setThreadId}
                onTurnEnd={onTurnEnd}
              />
            </div>
          </>
        )}

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
    </div>
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
