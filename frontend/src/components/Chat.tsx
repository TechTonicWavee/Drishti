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

type ToolCall = {
  tool: string
  summary: string
  ok: boolean
}

type ExecutionResult = {
  code: string
  stdout: string
  stderr: string
  exit_code: number
  timed_out: boolean
}

type Message = {
  role: 'user' | 'assistant'
  content: string
  routing?: Routing
  sources?: Source[]
  tools?: ToolCall[]
  executions?: ExecutionResult[]
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

  // One handler for both transports. Text turns arrive over EventSource;
  // uploads arrive over a fetch stream, because EventSource cannot issue the
  // multipart POST an upload needs. Sharing this keeps the two from drifting.
  const applyEvent = useCallback(
    (name: string, data: string) => {
      try {
        const payload = JSON.parse(data)
        switch (name) {
          case 'routing':
            patchLast((m) => ({ ...m, routing: payload as Routing }))
            break
          case 'sources':
            if (payload.sources?.length) {
              patchLast((m) => ({ ...m, sources: payload.sources as Source[] }))
            }
            break
          case 'tool':
            patchLast((m) => ({ ...m, tools: [...(m.tools ?? []), payload as ToolCall] }))
            break
          case 'execution':
            patchLast((m) => ({
              ...m,
              executions: [...(m.executions ?? []), payload as ExecutionResult],
            }))
            break
          case 'message':
            if (payload.delta) {
              patchLast((m) => ({ ...m, content: m.content + payload.delta }))
            }
            break
          case 'stream-error':
            setError(payload.message ?? 'The model server reported an error.')
            break
        }
      } catch {
        // A single unparseable frame is not worth killing the stream over.
      }
    },
    [patchLast],
  )

  const startTurn = useCallback((userText: string) => {
    setError(null)
    // The empty assistant message is the buffer that deltas append to.
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: userText },
      { role: 'assistant', content: '' },
    ])
    setStreaming(true)
  }, [])

  const send = useCallback(
    (event: React.FormEvent) => {
      event.preventDefault()
      const prompt = input.trim()
      if (!prompt || streaming) return

      setInput('')
      startTurn(prompt)

      // No model parameter on "Auto" — the router decides.
      const params = new URLSearchParams({ message: prompt })
      if (override !== AUTO) params.set('model', override)

      const source = new EventSource(`/api/chat/stream?${params}`)
      sourceRef.current = source

      for (const name of ['routing', 'sources', 'tool', 'execution', 'stream-error']) {
        source.addEventListener(name, (e) =>
          applyEvent(name, (e as MessageEvent<string>).data),
        )
      }
      source.onmessage = (e: MessageEvent<string>) => applyEvent('message', e.data)

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
    [applyEvent, closeStream, input, override, startTurn, streaming],
  )

  const upload = useCallback(
    async (file: File) => {
      if (streaming) return
      const note = input.trim()
      setInput('')
      startTurn(note ? `📎 ${file.name}\n\n${note}` : `📎 ${file.name}`)

      try {
        const form = new FormData()
        form.append('file', file)
        if (note) form.append('message', note)

        const response = await fetch('/api/chat/upload', {
          method: 'POST',
          body: form,
        })
        if (!response.ok || !response.body) {
          const body = await response.json().catch(() => null)
          throw new Error(body?.detail ?? `Upload failed (HTTP ${response.status})`)
        }

        // Hand-parse the SSE stream. The frames are identical to the ones
        // EventSource would deliver; only the transport differs.
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          let boundary = buffer.indexOf('\n\n')
          while (boundary !== -1) {
            const frame = buffer.slice(0, boundary)
            buffer = buffer.slice(boundary + 2)
            let name = 'message'
            let data = ''
            for (const line of frame.split('\n')) {
              if (line.startsWith('event:')) name = line.slice(6).trim()
              else if (line.startsWith('data:')) data += line.slice(5).trim()
            }
            if (data) applyEvent(name, data)
            boundary = buffer.indexOf('\n\n')
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Upload failed.')
      } finally {
        setStreaming(false)
      }
    },
    [applyEvent, input, startTurn, streaming],
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
            {m.tools && m.tools.length > 0 && (
              <p className="text-[11px] text-muted-foreground">
                {m.tools.map((t, j) => (
                  <span key={j} title={t.summary}>
                    {j > 0 && ' · '}
                    {t.ok ? '🔧' : '⚠️'} {t.tool}
                  </span>
                ))}
              </p>
            )}
            <p className="whitespace-pre-wrap text-[15px] leading-relaxed">
              {m.content}
              {streaming && i === messages.length - 1 && (
                <span className="ml-0.5 inline-block animate-pulse">▍</span>
              )}
            </p>
            {m.executions?.map((run, k) => (
              <ExecutionBlock key={k} run={run} index={k} total={m.executions!.length} />
            ))}
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

      <UploadZone onFile={upload} disabled={streaming} />

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

function UploadZone({
  onFile,
  disabled,
}: {
  onFile: (file: File) => void
  disabled: boolean
}) {
  const [over, setOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const take = (file: File | undefined) => {
    if (file && !disabled) onFile(file)
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        take(e.dataTransfer.files?.[0])
      }}
      onClick={() => !disabled && inputRef.current?.click()}
      role="button"
      tabIndex={disabled ? -1 : 0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
      }}
      aria-label="Upload a scanned report or photograph"
      className={[
        'flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-5 text-center text-[13px] transition-colors',
        disabled
          ? 'cursor-not-allowed border-border/60 text-muted-foreground/50'
          : over
            ? 'border-primary bg-primary/5 text-foreground'
            : 'border-border text-muted-foreground hover:border-primary/60 hover:bg-card',
      ].join(' ')}
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/tiff,image/bmp,image/webp,application/pdf"
        className="hidden"
        onChange={(e) => {
          take(e.target.files?.[0])
          // Reset so selecting the same file twice fires onChange again.
          e.target.value = ''
        }}
      />
      <span>
        {over
          ? 'Drop to read it'
          : 'Drop a scanned report or photo here, or click to browse — PNG, JPG, TIFF or PDF'}
      </span>
    </div>
  )
}

function ExecutionBlock({
  run,
  index,
  total,
}: {
  run: ExecutionResult
  index: number
  total: number
}) {
  const failed = run.timed_out || run.exit_code !== 0
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <div className="flex items-center justify-between gap-2 border-b border-border bg-muted/50 px-3 py-1.5">
        <span className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          {total > 1 ? `Run ${index + 1} of ${total}` : 'Sandboxed run'}
        </span>
        <span
          className={[
            'text-[11px] font-medium',
            failed ? 'text-destructive' : 'text-muted-foreground',
          ].join(' ')}
        >
          {run.timed_out ? 'timed out' : `exit ${run.exit_code}`}
        </span>
      </div>

      {/* Plain monospace rather than a syntax highlighter: every highlighter
          worth using ships as a CDN script or a sizeable bundle, and this app
          may not load anything over the network. */}
      <pre className="overflow-x-auto px-3 py-2 font-mono text-[12px] leading-relaxed">
        {run.code}
      </pre>

      <div className="border-t border-border bg-muted/25">
        <div className="px-3 pt-1.5 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          Execution output
        </div>
        {run.stdout.trim() && (
          <pre className="overflow-x-auto px-3 py-1.5 font-mono text-[12px] leading-relaxed">
            {run.stdout.trimEnd()}
          </pre>
        )}
        {run.stderr.trim() && (
          <pre className="overflow-x-auto px-3 py-1.5 font-mono text-[12px] leading-relaxed text-destructive">
            {run.stderr.trimEnd()}
          </pre>
        )}
        {!run.stdout.trim() && !run.stderr.trim() && (
          <p className="px-3 py-1.5 text-[12px] text-muted-foreground">
            {run.timed_out ? 'Killed on timeout before producing output.' : 'No output.'}
          </p>
        )}
      </div>
    </div>
  )
}

function formatRouting(routing: Routing | undefined): string {
  if (!routing) return 'Routing…'
  // model is null when the route was recognised but nothing was invoked.
  const suffix = routing.model ? ` (${routing.model})` : ' — not yet implemented'
  return `Routed to: ${routing.agent}${suffix}`
}
