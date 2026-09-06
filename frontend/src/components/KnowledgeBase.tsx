import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Knowledge base management.
 *
 * Deliberately separate from the chat's upload zone, because the two do
 * different things and conflating them is confusing: dropping a scan on the
 * chat reads it once and moves on, while adding a document here indexes it so
 * every future question can be answered from it.
 */

const ACCEPTED = '.txt,.md,.pdf'

type Document = {
  source: string
  chunks: number
  on_disk: boolean
}

export default function KnowledgeBase() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [over, setOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/documents')
      if (!response.ok) return
      setDocuments((await response.json()) as Document[])
    } catch {
      // The panel is secondary; a failed refresh should not raise an alarm.
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const add = useCallback(
    async (file: File | undefined) => {
      if (!file || busy) return
      setError(null)
      setBusy(`Indexing ${file.name}…`)
      try {
        const form = new FormData()
        form.append('file', file)
        const response = await fetch('/api/documents', { method: 'POST', body: form })
        const body = await response.json().catch(() => null)
        if (!response.ok) {
          throw new Error(body?.detail ?? `Upload failed (HTTP ${response.status})`)
        }
        await load()
        setBusy(null)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not add the document.')
        setBusy(null)
      }
    },
    [busy, load],
  )

  const remove = useCallback(
    async (source: string) => {
      if (busy) return
      setError(null)
      setBusy(`Removing ${source}…`)
      try {
        const response = await fetch(`/api/documents/${encodeURIComponent(source)}`, {
          method: 'DELETE',
        })
        if (!response.ok) {
          const body = await response.json().catch(() => null)
          throw new Error(body?.detail ?? `Delete failed (HTTP ${response.status})`)
        }
        setDocuments((await response.json()) as Document[])
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not remove the document.')
      } finally {
        setBusy(null)
      }
    },
    [busy],
  )

  const totalChunks = documents.reduce((sum, d) => sum + d.chunks, 0)

  return (
    <details className="group rounded-2xl border border-border bg-card px-5 py-4 shadow-[0_1px_2px_rgba(43,39,37,0.05)]">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-[13px] marker:content-none">
        <span className="text-muted-foreground group-open:text-brand">▸</span>
        <span className="font-medium">Knowledge base</span>
        <span className="text-muted-foreground">
          {documents.length} document{documents.length === 1 ? '' : 's'} ·{' '}
          {totalChunks} searchable chunk{totalChunks === 1 ? '' : 's'}
        </span>
      </summary>

      <p className="mt-3 text-[12px] leading-relaxed text-muted-foreground">
        Documents added here are indexed and used to answer questions, with
        citations. Stored in{' '}
        <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
          backend/data/sample_docs/
        </code>
        , searchable index in{' '}
        <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
          backend/data/chroma/
        </code>
        . This is not the same as dropping a scan into the chat, which reads a
        page once without indexing it.
      </p>

      <ul className="mt-4 flex flex-col gap-1.5">
        {documents.length === 0 && (
          <li className="text-[13px] text-muted-foreground">
            Nothing indexed yet.
          </li>
        )}
        {documents.map((d) => (
          <li
            key={d.source}
            className="flex items-center gap-3 rounded-lg px-2 py-1.5 text-[13px] hover:bg-muted/40"
          >
            <span className="truncate" title={d.source}>
              {d.source}
            </span>
            <span className="shrink-0 text-[11px] text-muted-foreground">
              {d.chunks} chunk{d.chunks === 1 ? '' : 's'}
              {!d.on_disk && ' · source file missing'}
            </span>
            <button
              type="button"
              onClick={() => remove(d.source)}
              disabled={busy !== null}
              className="ml-auto shrink-0 rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-40"
              aria-label={`Remove ${d.source}`}
            >
              Remove
            </button>
          </li>
        ))}
      </ul>

      <div
        onDragOver={(e) => {
          e.preventDefault()
          if (!busy) setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setOver(false)
          void add(e.dataTransfer.files?.[0])
        }}
        onClick={() => !busy && inputRef.current?.click()}
        role="button"
        tabIndex={busy ? -1 : 0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
        }}
        aria-label="Add a document to the knowledge base"
        className={[
          'mt-4 flex cursor-pointer items-center justify-center rounded-xl border border-dashed px-4 py-4 text-center text-[12px] transition-colors',
          busy
            ? 'cursor-wait border-border/60 text-muted-foreground'
            : over
              ? 'border-brand bg-brand/5 text-foreground'
              : 'border-border text-muted-foreground hover:border-brand/60 hover:bg-muted/30',
        ].join(' ')}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          className="hidden"
          onChange={(e) => {
            void add(e.target.files?.[0])
            e.target.value = ''
          }}
        />
        <span>
          {busy ?? 'Add a document to the knowledge base — TXT, Markdown or PDF'}
        </span>
      </div>

      {error && (
        <p className="mt-3 text-[12px] text-destructive" role="alert">
          {error}
        </p>
      )}
    </details>
  )
}
