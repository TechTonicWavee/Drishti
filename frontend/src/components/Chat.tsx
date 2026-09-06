import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Minimal streaming chat box.
 *
 * Uses the browser's native EventSource, which can only issue GET requests —
 * so it connects to GET /api/chat/stream rather than POST /chat. Both routes
 * run the same server-side generator; see backend/app/routers/chat.py.
 *
 * The model is chosen by the backend router. The selector below is an escape
 * hatch, not the normal path: leaving it on "Auto" sends no model at all.
 */

const AUTO = 'auto'
const OVERRIDE_MODELS = ['qwen2.5:7b', 'qwen2.5-coder:7b'] as const

type Routing = {
  task: string
  agent: string
  model: string | null
  reason: string
  implemented: boolean
}

type Source = {
  source: string
  distance: number
}

type Message = {
  role: 'user' | 'assistant'
  content: string
  routing?: Routing
  sources?: Source[]
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [override, setOverride] = useState<string>(AUTO)
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const sourceRef = useRef<EventSource | null>(null)

  const closeStream = useCallback(() => {
    sourceRef.current?.close()
    sourceRef.current = null
    setStreaming(false)
  }, [])

  // Don't leave a socket open if the component goes away mid-answer.
  useEffect(() => closeStream, [closeStream])

  // Both handlers below patch the last message, which is always the assistant
  // turn currently being filled in.
  const patchLast = useCallback((patch: (m: Message) => Message) => {
    setMessages((prev) => {
      const next = [...prev]
      next[next.length - 1] = patch(next[next.length - 1])
      return next
    })
  }, [])

  const send = useCallback(
    (event: React.FormEvent) => {
      event.preventDefault()
      const prompt = input.trim()
      if (!prompt || streaming) return

      setError(null)
      setInput('')
      // The empty assistant message is the buffer that deltas append to.
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: prompt },
        { role: 'assistant', content: '' },
      ])
      setStreaming(true)

      // No model parameter on "Auto" — the router decides.
      const params = new URLSearchParams({ message: prompt })
      if (override !== AUTO) params.set('model', override)

      const source = new EventSource(`/api/chat/stream?${params}`)
      sourceRef.current = source

      // Always arrives before the first token, so the label is in place by the
      // time any text shows up.
      source.addEventListener('routing', (e) => {
        try {
          const routing = JSON.parse((e as MessageEvent<string>).data) as Routing
          patchLast((m) => ({ ...m, routing }))
        } catch {
          // A missing label is not worth discarding the answer for.
        }
      })

      // Reasoning turns only, and only for chunks that cleared the relevance
      // threshold — an empty list here means nothing was close enough, which
      // is why an unrelated question shows no sources at all.
      source.addEventListener('sources', (e) => {
        try {
          const { sources } = JSON.parse((e as MessageEvent<string>).data) as {
            sources?: Source[]
          }
          if (sources?.length) patchLast((m) => ({ ...m, sources }))
        } catch {
          // Losing the citation list should not cost us the answer.
        }
      })

      source.onmessage = (e: MessageEvent<string>) => {
        try {
          const { delta } = JSON.parse(e.data) as { delta?: string }
          if (delta) patchLast((m) => ({ ...m, content: m.content + delta }))
        } catch {
          // A single unparseable frame is not worth killing the stream over.
        }
      }

      // The model failed. Distinct from EventSource's own 'error' event, which
      // fires for transport problems.
      source.addEventListener('stream-error', (e) => {
        try {
          const { message } = JSON.parse((e as MessageEvent<string>).data) as {
            message?: string
          }
          setError(message ?? 'The model server reported an error.')
        } catch {
          setError('The model server reported an error.')
        }
      })

      // EventSource reconnects on its own when a stream ends, which would
      // re-run the prompt. The server's explicit 'done' event is the signal
      // to close instead.
      source.addEventListener('done', closeStream)

      source.onerror = () => {
        // Fires on a dropped connection; also fires after close() in some
        // browsers, so only surface it while a stream is genuinely live.
        if (sourceRef.current !== source) return
        setError('Lost connection to the backend while streaming.')
        closeStream()
      }
    },
    [closeStream, input, override, patchLast, streaming],
  )

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="font-heading text-xl">Chat</h2>
        <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
          Model
          <select
            value={override}
            onChange={(e) => setOverride(e.target.value)}
            disabled={streaming}
            className="rounded-md border border-border bg-card px-2 py-1 text-[13px] text-foreground"
          >
            <option value={AUTO}>Auto (router decides)</option>
            {OVERRIDE_MODELS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex flex-col gap-3">
        {messages.length === 0 && (
          <p className="text-[13px] text-muted-foreground">
            No messages yet. Everything below runs on this machine.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className="flex flex-col gap-1">
            <span
              className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
              title={m.routing?.reason}
            >
              {m.role === 'user' ? 'You' : formatRouting(m.routing)}
            </span>
            <p className="whitespace-pre-wrap text-[15px] leading-relaxed">
              {m.content}
              {streaming && i === messages.length - 1 && (
                <span className="ml-0.5 inline-block animate-pulse">▍</span>
              )}
            </p>
            {m.sources && m.sources.length > 0 && (
              <p className="text-[12px] text-muted-foreground">
                Sources:{' '}
                {m.sources.map((s) => s.source).join(', ')}
              </p>
            )}
          </div>
        ))}
      </div>

      {error && (
        <p className="text-[13px] text-destructive" role="alert">
          {error}
        </p>
      )}

      <form onSubmit={send} className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask something…"
          disabled={streaming}
          className="flex-1 rounded-lg border border-border bg-card px-3 py-2 text-[15px] outline-none focus-visible:border-ring"
        />
        <button
          type="submit"
          disabled={streaming || !input.trim()}
          className="rounded-lg bg-primary px-4 py-2 text-[14px] font-medium text-primary-foreground disabled:opacity-40"
        >
          {streaming ? 'Streaming…' : 'Send'}
        </button>
      </form>
    </section>
  )
}

function formatRouting(routing: Routing | undefined): string {
  if (!routing) return 'Routing…'
  // model is null when the route was recognised but nothing was invoked.
  const suffix = routing.model ? ` (${routing.model})` : ' — not yet implemented'
  return `Routed to: ${routing.agent}${suffix}`
}
