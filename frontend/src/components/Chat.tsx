import { useCallback, useEffect, useRef, useState } from 'react'

import AgentTrace, { type TraceStep } from '@/components/AgentTrace'
import Markdown from '@/components/Markdown'
import {
  ensureSession,
  touchSession,
  watchPageExit,
} from '@/lib/session'

/**
 * The chat surface.
 *
 * Two transports feed one event handler. Text turns arrive over EventSource;
 * uploads arrive over a fetch stream, because EventSource cannot issue the
 * multipart POST an upload needs. Sharing `applyEvent` keeps the frames from
 * being handled differently by accident — the transport differs, the protocol
 * does not.
 */

const AUTO = 'auto'
const OVERRIDE_MODELS = ['qwen2.5:7b', 'qwen2.5-coder:7b'] as const

// One card treatment, used by every block on the page so the interface reads
// as a single product rather than a pile of separately-styled features.
// Prior turns replayed so follow-ups resolve. Kept deliberately small: this
// rides in the query string, because EventSource can only issue a GET, and an
// over-long URL is refused by the server rather than merely being slow.
const HISTORY_TURNS = 6
const HISTORY_CHARS = 500

const CARD = 'rounded-2xl border border-border bg-card shadow-[0_1px_2px_rgba(43,39,37,0.05)]'
const LABEL = 'text-[11px] uppercase tracking-[0.14em] text-muted-foreground'

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
  chunk_index?: number
  excerpt?: string
}

type ToolCall = { tool: string; summary: string; ok: boolean }

type ExecutionResult = {
  code: string
  stdout: string
  stderr: string
  exit_code: number
  timed_out: boolean
}

type ArtifactFile = {
  filename: string
  kind: string
  url: string
  size_bytes: number
}

type Message = {
  role: 'user' | 'assistant'
  content: string
  routing?: Routing
  sources?: Source[]
  tools?: ToolCall[]
  executions?: ExecutionResult[]
  artifacts?: ArtifactFile[]
  trace?: TraceStep[]
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [override, setOverride] = useState<string>(AUTO)
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const sourceRef = useRef<EventSource | null>(null)
  // When the current turn began, in unix seconds — the window the trace asks
  // the backend for.
  const turnStartRef = useRef<number>(0)

  // Read through a ref so the send/upload callbacks do not have to be rebuilt
  // on every streamed token.
  const messagesRef = useRef<Message[]>([])
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  const history = useCallback(
    () =>
      messagesRef.current
        .filter((m) => m.content.trim())
        .slice(-HISTORY_TURNS)
        .map((m) => ({
          role: m.role,
          content:
            m.content.length > HISTORY_CHARS
              ? m.content.slice(0, HISTORY_CHARS) + '…'
              : m.content,
        })),
    [],
  )

  const patchLast = useCallback((patch: (m: Message) => Message) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev
      const next = [...prev]
      next[next.length - 1] = patch(next[next.length - 1])
      return next
    })
  }, [])

  // Pulled once the turn ends, from the same log files the audit trail uses.
  const loadTrace = useCallback(async () => {
    try {
      const response = await fetch(
        `/api/system/trace?since_epoch=${turnStartRef.current}`,
      )
      if (!response.ok) return
      const body = (await response.json()) as { steps: TraceStep[] }
      if (body.steps?.length) patchLast((m) => ({ ...m, trace: body.steps }))
    } catch {
      // The trace is supporting evidence; losing it must not disturb the answer.
    }
  }, [patchLast])

  const closeStream = useCallback(() => {
    sourceRef.current?.close()
    sourceRef.current = null
    setStreaming(false)
    void loadTrace()
  }, [loadTrace])

  // Don't leave a socket open if the component goes away mid-answer.
  useEffect(() => () => sourceRef.current?.close(), [])

  // A session bracket, so the backend knows when to extract durable facts.
  // Only the user's own turns are handed over; the server filters again.
  useEffect(() => {
    ensureSession()
    return watchPageExit(() =>
      messagesRef.current.map((m) => ({ role: m.role, content: m.content })),
    )
  }, [])

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
          case 'artifact':
            patchLast((m) => ({
              ...m,
              artifacts: [...(m.artifacts ?? []), payload as ArtifactFile],
            }))
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
    ensureSession()
    touchSession(() =>
      messagesRef.current.map((m) => ({ role: m.role, content: m.content })),
    )
    // A second's grace: log timestamps have second resolution, so a step
    // written in the same second the turn began would otherwise be missed.
    turnStartRef.current = Date.now() / 1000 - 1
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
      // Captured before startTurn appends this turn, so the history is the
      // conversation as it stood when the question was asked.
      const prior = history()
      startTurn(prompt)

      // No model parameter on "Auto" — the router decides.
      const params = new URLSearchParams({ message: prompt })
      if (override !== AUTO) params.set('model', override)
      if (prior.length) params.set('history', JSON.stringify(prior))

      const source = new EventSource(`/api/chat/stream?${params}`)
      sourceRef.current = source

      for (const name of [
        'routing', 'sources', 'tool', 'execution', 'artifact', 'stream-error',
      ]) {
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
        // Also fires after close() in some browsers, so only surface it while
        // a stream is genuinely live.
        if (sourceRef.current !== source) return
        setError('Lost connection to the backend while streaming.')
        closeStream()
      }
    },
    [applyEvent, closeStream, history, input, override, startTurn, streaming],
  )

  const upload = useCallback(
    async (file: File) => {
      if (streaming) return
      const note = input.trim()
      setInput('')
      const prior = history()
      startTurn(note ? `${file.name}\n\n${note}` : file.name)

      try {
        const form = new FormData()
        form.append('file', file)
        if (note) form.append('message', note)
        if (prior.length) form.append('history', JSON.stringify(prior))

        const response = await fetch('/api/chat/upload', { method: 'POST', body: form })
        if (!response.ok || !response.body) {
          const body = await response.json().catch(() => null)
          throw new Error(body?.detail ?? `Upload failed (HTTP ${response.status})`)
        }

        // Hand-parse the SSE stream: the frames are identical to the ones
        // EventSource delivers, only the transport differs.
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
        void loadTrace()
      }
    },
    [applyEvent, history, input, loadTrace, startTurn, streaming],
  )

  return (
    <section className="flex flex-col gap-6">
      <header className="flex items-baseline justify-between gap-4">
        <h2 className="font-heading text-2xl">Workbench</h2>
        <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
          Model
          <select
            value={override}
            onChange={(e) => setOverride(e.target.value)}
            disabled={streaming}
            className="rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12px] text-foreground shadow-[0_1px_2px_rgba(43,39,37,0.04)] outline-none focus-visible:border-ring"
          >
            <option value={AUTO}>Auto (router decides)</option>
            {OVERRIDE_MODELS.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </label>
      </header>

      <div className="flex flex-col gap-7">
        {messages.length === 0 && (
          <p className="text-[14px] leading-relaxed text-muted-foreground">
            Ask about a procedure, request a script, or drop a scanned report
            below. Everything runs on this machine.
          </p>
        )}

        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="flex justify-end">
              <p className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-secondary px-4 py-3 text-[15px] leading-relaxed">
                {m.content}
              </p>
            </div>
          ) : (
            <article key={i} className="flex flex-col gap-3">
              <span className={LABEL} title={m.routing?.reason}>
                {formatRouting(m.routing)}
              </span>

              {m.tools && m.tools.length > 0 && (
                <p className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                  {m.tools.map((t, j) => (
                    <span key={j} title={t.summary}>
                      {t.ok ? '🔧' : '⚠️'} {t.tool}
                    </span>
                  ))}
                </p>
              )}

              {m.content && (
                <div>
                  <Markdown>{m.content}</Markdown>
                  {streaming && i === messages.length - 1 && (
                    <span className="ml-0.5 inline-block animate-pulse">▍</span>
                  )}
                </div>
              )}

              {m.artifacts?.map((file, k) => (
                <DeliverableCard key={k} file={file} />
              ))}

              {m.executions?.map((run, k) => (
                <ExecutionBlock
                  key={k}
                  run={run}
                  index={k}
                  total={m.executions!.length}
                />
              ))}

              {m.sources && m.sources.length > 0 && <Citations sources={m.sources} />}

              {m.trace && m.trace.length > 0 && <AgentTrace steps={m.trace} />}
            </article>
          ),
        )}
      </div>

      {error && (
        <p className="text-[13px] text-destructive" role="alert">
          {error}
        </p>
      )}

      <div className="flex flex-col gap-3">
        <UploadZone onFile={upload} disabled={streaming} />

        <form onSubmit={send} className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask something…"
            disabled={streaming}
            className={`flex-1 ${CARD} px-4 py-3 text-[15px] outline-none focus-visible:border-ring`}
          />
          <button
            type="submit"
            disabled={streaming || !input.trim()}
            className="rounded-2xl bg-primary px-5 py-3 text-[14px] font-medium text-primary-foreground shadow-[0_1px_2px_rgba(43,39,37,0.08)] transition-colors hover:bg-primary/90 disabled:opacity-40"
          >
            {streaming ? 'Working…' : 'Send'}
          </button>
        </form>
      </div>
    </section>
  )
}

function Citations({ sources }: { sources: Source[] }) {
  return (
    <div className={`${CARD} px-4 py-3`}>
      <p className={`${LABEL} mb-2`}>Sources</p>
      <div className="flex flex-col gap-2">
        {sources.map((s, i) => (
          <details key={i} className="group">
            <summary className="cursor-pointer list-none text-[13px] text-foreground marker:content-none">
              <span className="text-muted-foreground group-open:text-brand">▸ </span>
              {s.source}
              {typeof s.chunk_index === 'number' && s.chunk_index >= 0 && (
                <span className="text-muted-foreground"> · part {s.chunk_index + 1}</span>
              )}
            </summary>
            {s.excerpt && (
              <blockquote className="mt-2 border-l-2 border-brand/50 pl-3 text-[13px] leading-relaxed text-muted-foreground">
                {s.excerpt}
              </blockquote>
            )}
          </details>
        ))}
      </div>
    </div>
  )
}

const FILE_ICONS: Record<string, string> = {
  '.docx': '📄',
  '.pptx': '📊',
  '.xlsx': '🧮',
}

const KIND_LABELS: Record<string, string> = {
  approval_note: 'Word approval note',
  summary_deck: 'PowerPoint deck',
  calculation_sheet: 'Excel calculation sheet',
}

function DeliverableCard({ file }: { file: ArtifactFile }) {
  const extension = file.filename.slice(file.filename.lastIndexOf('.')).toLowerCase()
  const label = KIND_LABELS[file.kind] ?? 'Document'
  const kb = Math.max(1, Math.round(file.size_bytes / 1024))

  return (
    <div className={`${CARD} flex items-center gap-4 px-4 py-3.5`}>
      <span aria-hidden className="text-[24px] leading-none">
        {FILE_ICONS[extension] ?? '📎'}
      </span>
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-[13px] font-medium" title={file.filename}>
          {file.filename}
        </span>
        <span className="text-[11px] text-muted-foreground">
          {label} · {kb} KB
        </span>
      </div>
      {/* A plain link: the endpoint sets Content-Disposition: attachment, so
          the browser saves it rather than trying to render Office XML. */}
      <a
        href={file.url}
        download={file.filename}
        className="ml-auto shrink-0 rounded-xl bg-primary px-3.5 py-2 text-[13px] font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        Download
      </a>
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
    <div className={`${CARD} overflow-hidden`}>
      <div className="flex items-center justify-between gap-2 border-b border-border bg-muted/40 px-4 py-2">
        <span className={LABEL}>
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
      <pre className="overflow-x-auto px-4 py-3 font-mono text-[12px] leading-relaxed">
        {run.code}
      </pre>

      <div className="border-t border-border bg-muted/20">
        <div className={`${LABEL} px-4 pt-2`}>Execution output</div>
        {run.stdout.trim() && (
          <pre className="overflow-x-auto px-4 py-2 font-mono text-[12px] leading-relaxed">
            {run.stdout.trimEnd()}
          </pre>
        )}
        {run.stderr.trim() && (
          <pre className="overflow-x-auto px-4 py-2 font-mono text-[12px] leading-relaxed text-destructive">
            {run.stderr.trimEnd()}
          </pre>
        )}
        {!run.stdout.trim() && !run.stderr.trim() && (
          <p className="px-4 py-2 text-[12px] text-muted-foreground">
            {run.timed_out ? 'Killed on timeout before producing output.' : 'No output.'}
          </p>
        )}
      </div>
    </div>
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
        'flex cursor-pointer items-center justify-center gap-2 rounded-2xl border border-dashed px-4 py-6 text-center text-[13px] transition-colors',
        disabled
          ? 'cursor-not-allowed border-border/60 text-muted-foreground/50'
          : over
            ? 'border-brand bg-brand/5 text-foreground'
            : 'border-border text-muted-foreground hover:border-brand/60 hover:bg-card',
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
          : 'Read a scanned report or photo — drop it here or click to browse. Not indexed; use Knowledge base above to add searchable documents.'}
      </span>
    </div>
  )
}

function formatRouting(routing: Routing | undefined): string {
  if (!routing) return 'Routing…'
  // model is null when the route was recognised but nothing was invoked.
  const suffix = routing.model ? ` (${routing.model})` : ' — not yet implemented'
  return `Routed to: ${routing.agent}${suffix}`
}
