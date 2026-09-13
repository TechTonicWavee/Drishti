import { useState } from 'react'

export type StepType =
  | 'inspect'
  | 'retrieve'
  | 'compute'
  | 'verify'
  | 'delegate'
  | 'deliverable'
  | 'synthesize'

export type StepStatus = 'pending' | 'running' | 'completed' | 'failed'

export type PlanStep = {
  id: string
  title: string
  step_type: StepType
  description: string
  status: StepStatus
  agent: string
  summary?: string | null
}

export type TaskPlan = {
  plan_id: string
  goal: string
  total_steps: number
  steps: PlanStep[]
}

const STEP_ICONS: Record<StepType, string> = {
  inspect: '🔍',
  retrieve: '📚',
  compute: '⚡',
  verify: '🛡️',
  delegate: '🤝',
  deliverable: '📄',
  synthesize: '🧠',
}

const STEP_COLORS: Record<StepType, string> = {
  inspect: 'border-cyan-500/30 text-cyan-400 bg-cyan-500/10',
  retrieve: 'border-amber-500/30 text-amber-400 bg-amber-500/10',
  compute: 'border-blue-500/30 text-blue-400 bg-blue-500/10',
  verify: 'border-emerald-500/30 text-emerald-400 bg-emerald-500/10',
  delegate: 'border-purple-500/30 text-purple-400 bg-purple-500/10',
  deliverable: 'border-rose-500/30 text-rose-400 bg-rose-500/10',
  synthesize: 'border-indigo-500/30 text-indigo-400 bg-indigo-500/10',
}

export default function TaskGraphView({ plan }: { plan: TaskPlan }) {
  const [expanded, setExpanded] = useState(true)

  const completedCount = plan.steps.filter((s) => s.status === 'completed').length
  const isFinished = completedCount === plan.total_steps

  return (
    <div className="mb-4 overflow-hidden rounded-2xl border border-border/80 bg-card/70 shadow-sm backdrop-blur-sm transition-all">
      {/* Plan Header */}
      <div className="flex items-center justify-between gap-3 border-b border-border/60 bg-muted/40 px-4 py-3 text-xs">
        <div className="flex items-center gap-2.5">
          <span className="flex size-5 items-center justify-center rounded-md bg-brand/15 text-[11px] font-bold text-brand">
            ⌘
          </span>
          <span className="font-semibold text-foreground tracking-wide">
            {plan.goal}
          </span>
          <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
            {completedCount}/{plan.total_steps} steps
          </span>
        </div>

        <div className="flex items-center gap-2">
          {isFinished ? (
            <span className="flex items-center gap-1 font-medium text-emerald-400 text-[11px]">
              <svg className="size-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path
                  fillRule="evenodd"
                  d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                  clipRule="evenodd"
                />
              </svg>
              Plan verified
            </span>
          ) : (
            <span className="flex items-center gap-1.5 font-medium text-brand text-[11px]">
              <span className="size-2 animate-ping rounded-full bg-brand" />
              Executing plan…
            </span>
          )}

          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            title={expanded ? 'Collapse plan view' : 'Expand plan view'}
          >
            <svg
              className={`size-3.5 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>
      </div>

      {/* Steps List */}
      {expanded && (
        <div className="divide-y divide-border/40 p-1.5">
          {plan.steps.map((step, idx) => {
            const isRunning = step.status === 'running'
            const isDone = step.status === 'completed'
            const isPending = step.status === 'pending'
            const isFailed = step.status === 'failed'

            return (
              <div
                key={step.id}
                className={`flex items-start gap-3 rounded-xl p-2.5 transition-colors ${
                  isRunning
                    ? 'bg-brand/5 border border-brand/20'
                    : 'hover:bg-muted/30'
                }`}
              >
                {/* Step Status Indicator */}
                <div className="flex size-6 shrink-0 items-center justify-center rounded-full mt-0.5">
                  {isDone && (
                    <span className="flex size-5 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-400">
                      <svg className="size-3" viewBox="0 0 20 20" fill="currentColor">
                        <path
                          fillRule="evenodd"
                          d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                          clipRule="evenodd"
                        />
                      </svg>
                    </span>
                  )}
                  {isRunning && (
                    <span className="relative flex size-4">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand opacity-75" />
                      <span className="relative inline-flex size-4 rounded-full bg-brand" />
                    </span>
                  )}
                  {isPending && (
                    <span className="flex size-5 items-center justify-center rounded-full border border-border text-[10px] font-mono text-muted-foreground">
                      {idx + 1}
                    </span>
                  )}
                  {isFailed && (
                    <span className="flex size-5 items-center justify-center rounded-full bg-destructive/20 text-destructive text-xs font-bold">
                      ✕
                    </span>
                  )}
                </div>

                {/* Step Body */}
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-0.5">
                    <span
                      className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${
                        STEP_COLORS[step.step_type]
                      }`}
                    >
                      <span>{STEP_ICONS[step.step_type]}</span>
                      {step.step_type}
                    </span>
                    <span
                      className={`text-[13px] font-medium leading-tight ${
                        isDone
                          ? 'text-foreground'
                          : isRunning
                          ? 'text-foreground font-semibold'
                          : 'text-muted-foreground'
                      }`}
                    >
                      {step.title}
                    </span>
                    <span className="text-[11px] font-mono text-muted-foreground/70">
                      [{step.agent}]
                    </span>
                  </div>

                  <p className="text-[12px] leading-relaxed text-muted-foreground">
                    {step.description}
                  </p>

                  {step.summary && (
                    <div className="mt-1.5 flex items-center gap-1.5 rounded-lg bg-muted/60 px-2.5 py-1 text-[11px] text-foreground font-mono">
                      <span className="text-muted-foreground">↳</span>
                      <span className="truncate">{step.summary}</span>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
