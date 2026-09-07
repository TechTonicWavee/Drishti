import { useCallback, useEffect, useImperativeHandle, useState } from 'react'
import type { Ref } from 'react'

/**
 * Past conversations, newest first.
 *
 * Threads are transcripts — the conversation as it happened, for reopening and
 * reading. Not to be confused with the user memory feature, which stores a few
 * extracted facts for prompt injection. See backend/app/services/thread_service.py.
 */

export type ThreadSummary = {
  thread_id: string
  title: string
  created_at: string
  updated_at: string
  preview: string
  message_count: number
}

export type ThreadSidebarHandle = { refresh: () => void }

type Props = {
  activeThreadId: string | null
  onSelect: (threadId: string) => void
  onNewChat: () => void
  ref?: Ref<ThreadSidebarHandle>
}

export default function ThreadSidebar({
  activeThreadId,
  onSelect,
  onNewChat,
  ref,
}: Props) {
  const [threads, setThreads] = useState<ThreadSummary[]>([])
  const [open, setOpen] = useState(true)

  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/threads?user_id=demo_user')
      if (!response.ok) return
      setThreads((await response.json()) as ThreadSummary[])
    } catch {
      // The sidebar is navigation, not the work. A failed refresh should not
      // interrupt a conversation in progress.
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // The chat panel refreshes this once a turn finishes, so a new thread and
  // its generated title appear without a poll.
  useImperativeHandle(ref, () => ({ refresh: load }), [load])

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Show conversations"
        className="fixed left-4 top-4 z-40 rounded-xl border border-border bg-card px-3 py-2 text-[12px] text-muted-foreground shadow-[0_1px_2px_rgba(43,39,37,0.05)] transition-colors hover:text-foreground"
      >
        ☰ Chats
      </button>
    )
  }

  return (
    <aside className="flex h-dvh w-64 shrink-0 flex-col gap-3 border-r border-border bg-card/40 px-3 py-4">
      <div className="flex items-center justify-between gap-2 px-1">
        <span className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          Conversations
        </span>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Hide conversations"
          className="rounded-md px-1.5 py-0.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
        >
          ⟨
        </button>
      </div>

      <button
        type="button"
        onClick={onNewChat}
        className="flex items-center justify-center gap-1.5 rounded-xl bg-primary px-3 py-2.5 text-[13px] font-medium text-primary-foreground shadow-[0_1px_2px_rgba(43,39,37,0.08)] transition-colors hover:bg-primary/90"
      >
        <span aria-hidden>+</span> New chat
      </button>

      <nav className="-mx-1 flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto px-1">
        {threads.length === 0 && (
          <p className="px-2 py-3 text-[12px] leading-relaxed text-muted-foreground">
            No conversations yet. They are saved as you go.
          </p>
        )}
        {threads.map((thread) => {
          const active = thread.thread_id === activeThreadId
          return (
            <button
              key={thread.thread_id}
              type="button"
              onClick={() => onSelect(thread.thread_id)}
              aria-current={active ? 'true' : undefined}
              title={thread.preview || thread.title}
              className={[
                'flex flex-col gap-0.5 rounded-lg px-2.5 py-2 text-left transition-colors',
                active
                  ? 'bg-secondary text-foreground'
                  : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground',
              ].join(' ')}
            >
              <span className="truncate text-[13px] font-medium">
                {thread.title}
              </span>
              <span className="truncate text-[11px] text-muted-foreground">
                {relativeTime(thread.updated_at)}
              </span>
            </button>
          )
        })}
      </nav>
    </aside>
  )
}

/** "2 hours ago", from an ISO timestamp. */
export function relativeTime(iso: string): string {
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return ''
  const seconds = Math.max(0, (Date.now() - then) / 1000)

  if (seconds < 45) return 'just now'
  const units: [number, string][] = [
    [60, 'minute'],
    [3600, 'hour'],
    [86400, 'day'],
    [604800, 'week'],
  ]
  // Walk up until the next unit would round to less than one.
  let value = seconds / 60
  let name = 'minute'
  for (const [size, unit] of units) {
    if (seconds < size * 60 || unit === 'week') {
      value = seconds / size
      name = unit
      break
    }
  }
  const rounded = Math.floor(value)
  if (rounded < 1) return 'just now'
  return `${rounded} ${name}${rounded === 1 ? '' : 's'} ago`
}
