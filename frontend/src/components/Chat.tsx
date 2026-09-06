import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Minimal streaming chat box.
 *
 * Uses the browser's native EventSource, which can only issue GET requests —
 * so it connects to GET /api/chat/stream rather than POST /chat. Both routes
 * run the same server-side generator; see backend/app/routers/chat.py.
 */

const MODELS = ['qwen2.5:7b', 'qwen2.5-coder:7b'] as const

type Message = {
  role: 'user' | 'assistant'
  content: string
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [model, setModel] = useState<string>(MODELS[0])
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

      const params = new URLSearchParams({ message: prompt, model })
      const source = new EventSource(`/api/chat/stream?${params}`)
      sourceRef.current = source

      const appendDelta = (delta: string) =>
        setMessages((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          next[next.length - 1] = { ...last, content: last.content + delta }
          return next
        })

      source.onmessage = (e: MessageEvent<string>) => {
        try {
          const { delta } = JSON.parse(e.data) as { delta?: string }
          if (delta) appendDelta(delta)
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
    [closeStream, input, model, streaming],
  )

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="font-heading text-xl">Chat</h2>
        <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
          Model
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={streaming}
            className="rounded-md border border-border bg-card px-2 py-1 text-[13px] text-foreground"
          >
            {MODELS.map((m) => (
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
            <span className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
              {m.role === 'user' ? 'You' : model}
            </span>
            <p className="whitespace-pre-wrap text-[15px] leading-relaxed">
              {m.content}
              {streaming && i === messages.length - 1 && (
                <span className="ml-0.5 inline-block animate-pulse">▍</span>
              )}
            </p>
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
