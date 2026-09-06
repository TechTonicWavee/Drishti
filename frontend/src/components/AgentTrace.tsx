/**
 * The path a request actually took.
 *
 * Collapsed by default: it is evidence, not the answer. The steps come from
 * GET /system/trace, which reads them back out of the audit log files rather
 * than from a separate in-memory record — so what is shown here and what is
 * on disk cannot disagree.
 */

export type TraceStep = {
  at: string
  log: string
  kind: string
  label: string
  detail: string
  fields: Record<string, string>
}

const KIND_MARKS: Record<string, string> = {
  route: '⇥',
  delegate: '→',
  tool: '🔧',
  vision: '👁',
  sandbox: '▶',
  artifact: '📄',
}

export default function AgentTrace({ steps }: { steps: TraceStep[] }) {
  // Timestamps have second resolution; showing only the clock time keeps the
  // column narrow without losing the ordering that matters.
  const clock = (at: string) => at.slice(11)

  return (
    <details className="group rounded-2xl border border-border bg-card/60 px-4 py-3 shadow-[0_1px_2px_rgba(43,39,37,0.05)]">
      <summary className="cursor-pointer list-none text-[11px] uppercase tracking-[0.14em] text-muted-foreground marker:content-none">
        <span className="text-muted-foreground group-open:text-brand">▸ </span>
        Agent trace · {steps.length} step{steps.length === 1 ? '' : 's'}
      </summary>

      <ol className="mt-3 flex flex-col gap-2">
        {steps.map((step, i) => (
          <li key={i} className="flex gap-3 text-[12px] leading-relaxed">
            <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
              {clock(step.at)}
            </span>
            <span aria-hidden className="shrink-0 text-muted-foreground">
              {KIND_MARKS[step.kind] ?? '·'}
            </span>
            <span className="min-w-0">
              <span className="text-foreground">{step.label}</span>
              {step.detail && (
                <span className="text-muted-foreground"> — {step.detail}</span>
              )}
              <span
                className="ml-1.5 text-[10px] text-muted-foreground/70"
                title={`recorded in ${step.log}`}
              >
                {step.log}
              </span>
            </span>
          </li>
        ))}
      </ol>

      <p className="mt-3 border-t border-border pt-2 text-[10px] leading-relaxed text-muted-foreground">
        Read back from the audit logs in backend/logs/, not kept separately.
      </p>
    </details>
  )
}
