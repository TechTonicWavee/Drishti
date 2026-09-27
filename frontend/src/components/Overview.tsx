import { useEffect, useState } from 'react'

export type ComplianceFinding = {
  id: string
  severity: 'CRITICAL' | 'WARNING' | 'INFO'
  equipment_tag: string
  procedure_id: string
  standard_code: string
  title: string
  description: string
  remediation: string
  created_at: string
}

export type AuditEvent = {
  row_id: number
  event_type: string
  actor: string
  summary: string
  timestamp: string
  row_hash: string
}

interface OverviewProps {
  onNavigate: (view: 'overview' | 'workbench' | 'graph' | 'audit') => void
  onLaunchInvestigation: (prompt: string) => void
}

export default function Overview({ onNavigate, onLaunchInvestigation }: OverviewProps) {
  const [findings, setFindings] = useState<ComplianceFinding[]>([])
  const [sweeping, setSweeping] = useState(false)
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([])

  // Load findings and recent audit events
  useEffect(() => {
    fetch('/api/compliance/findings')
      .then((res) => (res.ok ? res.json() : []))
      .then((data: ComplianceFinding[]) => setFindings(data))
      .catch(() => {})

    fetch('/api/audit/events?limit=4')
      .then((res) => (res.ok ? res.json() : []))
      .then((data: AuditEvent[]) => setAuditEvents(data))
      .catch(() => {})
  }, [])

  const runSweep = async () => {
    setSweeping(true)
    try {
      const res = await fetch('/api/compliance/sweep', { method: 'POST' })
      if (res.ok) {
        const payload = await res.json()
        setFindings(payload.findings || [])
        // Refresh audit ticker
        const auditRes = await fetch('/api/audit/events?limit=4')
        if (auditRes.ok) {
          setAuditEvents(await auditRes.json())
        }
      }
    } catch {
      // Ignored for demo stability
    } finally {
      setSweeping(false)
    }
  }

  const criticalFindings = findings.filter((f) => f.severity === 'CRITICAL')

  return (
    <div className="flex flex-col gap-10">
      {/* 1. Hero Infrastructure Banner */}
      <section className="relative overflow-hidden rounded-3xl border border-border/80 bg-gradient-to-b from-card/90 to-card/40 p-7 shadow-sm backdrop-blur-sm">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-col gap-1.5 max-w-xl">
            <div className="flex items-center gap-2">
              <span className="flex size-2 rounded-full bg-brand animate-pulse" />
              <span className="text-[11px] font-mono font-semibold uppercase tracking-[0.2em] text-brand">
                Industrial Air-Gapped Workbench
              </span>
              <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
                0 External Egress
              </span>
            </div>
            <h2 className="font-heading text-2xl sm:text-3xl font-medium tracking-tight">
              MRPL Refinery Multi-Agent Infrastructure
            </h2>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Autonomous, tamper-evident AI system for refinery process intelligence. Four local specialist
              models operating over private ChromaDB, deterministic equipment graphs, and locked-down Docker sandboxes.
            </p>
          </div>

          <div className="flex flex-wrap gap-2.5 sm:flex-col sm:items-end">
            <button
              type="button"
              onClick={() => onNavigate('workbench')}
              className="rounded-xl bg-brand px-4 py-2.5 text-xs font-semibold text-brand-foreground shadow-sm transition-all hover:bg-brand/90 flex items-center gap-2"
            >
              <span>💬</span>
              Open Task Workbench
            </button>
            <button
              type="button"
              onClick={() => onNavigate('graph')}
              className="rounded-xl border border-border/80 bg-muted/30 px-4 py-2 text-xs font-medium text-foreground hover:bg-muted/80 transition-colors flex items-center gap-2"
            >
              <span>🕸️</span>
              Explore Plant Graph
            </button>
          </div>
        </div>

        {/* 4 Metric Badges */}
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4 border-t border-border/60 pt-5">
          <div className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground">Monitored Assets</span>
            <span className="font-mono text-xl font-bold text-cyan-400">6 Units</span>
            <span className="text-[10px] text-muted-foreground/80">FCC, CDU, Flare & HSE</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground">Governed SOPs</span>
            <span className="font-mono text-xl font-bold text-amber-400">5 Documents</span>
            <span className="text-[10px] text-muted-foreground/80">16 Private Vector Chunks</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground">Industry Standards</span>
            <span className="font-mono text-xl font-bold text-emerald-400">5 Codes</span>
            <span className="text-[10px] text-muted-foreground/80">API 510, ASME VIII, OSHA</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground">Audit Verification</span>
            <span className="font-mono text-xl font-bold text-purple-400">100% Intact</span>
            <span className="text-[10px] text-muted-foreground/80">Cryptographic Hash Chain</span>
          </div>
        </div>
      </section>

      {/* 2. Four Local Models Grid */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-muted-foreground">
            On-Premise Specialist Models
          </h3>
          <span className="text-[11px] font-mono text-muted-foreground">
            Inference: Local Hardware · Engine: Ollama / vLLM
          </span>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            {
              role: 'Reasoning Specialist',
              model: 'qwen2.5:7b',
              badge: 'Coordinator',
              spec: '32k Context · RAG Grounding',
              desc: 'Orchestrates multi-agent routing, plant SOP queries, and technical reasoning.',
              color: 'border-cyan-500/30 bg-cyan-500/5',
              dot: 'bg-cyan-400',
            },
            {
              role: 'Code Sandbox Agent',
              model: 'qwen2.5-coder:7b',
              badge: 'Docker Isolated',
              spec: 'network=none · Read-Only',
              desc: 'Generates calculation scripts, executed and verified in an isolated container.',
              color: 'border-blue-500/30 bg-blue-500/5',
              dot: 'bg-blue-400',
            },
            {
              role: 'Vision Specialist',
              model: 'qwen2.5vl:7b',
              badge: 'Multimodal',
              spec: 'OpenCV Deskew · P&ID Scans',
              desc: 'Extracts equipment inspection data and charts from scanned plant documents.',
              color: 'border-purple-500/30 bg-purple-500/5',
              dot: 'bg-purple-400',
            },
            {
              role: 'Vector Embeddings',
              model: 'nomic-embed-text',
              badge: 'ChromaDB Local',
              spec: 'HNSW Cosine Index',
              desc: 'Indexes confidential refinery manuals with zero cloud API dependencies.',
              color: 'border-emerald-500/30 bg-emerald-500/5',
              dot: 'bg-emerald-400',
            },
          ].map((m) => (
            <div
              key={m.role}
              className={`flex flex-col justify-between rounded-2xl border p-4 transition-all hover:bg-muted/40 ${m.color}`}
            >
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="flex items-center gap-1.5 text-xs font-bold text-foreground">
                    <span className={`size-2 rounded-full ${m.dot}`} />
                    {m.role}
                  </span>
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[9px] font-mono font-medium text-muted-foreground">
                    {m.badge}
                  </span>
                </div>
                <p className="font-mono text-[11px] text-foreground/90 font-medium mb-1">
                  {m.model}
                </p>
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  {m.desc}
                </p>
              </div>
              <div className="mt-3 border-t border-border/40 pt-2 text-[10px] font-mono text-muted-foreground">
                {m.spec}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 3. Proactive Compliance Section & Section 3 Demo Story */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-muted-foreground">
              Proactive Compliance Sweep (Advancement 2.4)
            </h3>
            <span className="rounded-full bg-rose-500/10 border border-rose-500/30 px-2 py-0.5 text-[10px] font-semibold text-rose-400">
              {criticalFindings.length} Critical Alert
            </span>
          </div>
          <button
            type="button"
            onClick={runSweep}
            disabled={sweeping}
            className="rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted transition-colors flex items-center gap-1.5"
          >
            <span className={sweeping ? 'animate-spin' : ''}>↻</span>
            {sweeping ? 'Sweeping Plant Model…' : 'Run Full Compliance Sweep'}
          </button>
        </div>

        {/* Prominent Findings Card */}
        <div className="rounded-3xl border border-rose-500/30 bg-rose-500/5 p-5 shadow-sm">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3 max-w-2xl">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-2xl bg-rose-500/20 text-rose-400 text-lg">
                ⚠️
              </span>
              <div className="flex flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-bold text-rose-300 text-sm">
                    Statutory Review Exceeded: Pressure Vessel Inspection SOP
                  </span>
                  <span className="rounded bg-rose-500/20 px-1.5 py-0.5 font-mono text-[10px] font-bold text-rose-400">
                    Asset V-204 · API 510
                  </span>
                </div>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Governing procedure <code className="text-foreground">SAMPLE-SOP-INSP-004 (Rev 3)</code> reached its mandatory 3-year statutory cycle on <strong>2026-08-10</strong> (34 days overdue under API 510 Section 6.4). Affects Overhead Flash Drum V-204 and Exchanger Train E-102.
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={() => {
                const prompt =
                  'Investigate compliance alert for Flash Drum V-204: check governing procedure SAMPLE-SOP-INSP-004 review date under API 510, verify ultrasonic thickness thresholds, and generate an official management escalation approval note (.docx).'
                onLaunchInvestigation(prompt)
              }}
              className="shrink-0 rounded-2xl bg-rose-500 px-4 py-2.5 text-xs font-bold text-white shadow-md transition-all hover:bg-rose-600 flex items-center justify-center gap-2"
            >
              <span>⚡</span>
              Launch Compliance Investigation (Demo Flow)
            </button>
          </div>
        </div>
      </section>

      {/* 4. Cryptographic Audit Ticker */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-muted-foreground">
            Tamper-Evident Hash Chain Activity
          </h3>
          <button
            type="button"
            onClick={() => onNavigate('audit')}
            className="text-xs text-brand hover:underline font-medium"
          >
            View Full Audit Trail →
          </button>
        </div>

        <div className="divide-y divide-border/40 rounded-2xl border border-border/80 bg-card/60 overflow-hidden text-xs">
          {auditEvents.length ? (
            auditEvents.map((evt) => (
              <div key={evt.row_id} className="flex items-center justify-between p-3 gap-3">
                <div className="flex items-center gap-2.5 min-w-0">
                  <span className="font-mono text-[10px] text-muted-foreground">#{evt.row_id}</span>
                  <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] font-semibold text-foreground">
                    {evt.event_type}
                  </span>
                  <span className="truncate text-muted-foreground text-[12px]">{evt.summary}</span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="font-mono text-[10px] text-muted-foreground/70 truncate w-24">
                    hash:{evt.row_hash?.slice(0, 10)}…
                  </span>
                  <span className="text-[10px] text-muted-foreground">{evt.timestamp?.slice(11, 19)}</span>
                </div>
              </div>
            ))
          ) : (
            <div className="p-4 text-center text-muted-foreground text-xs">
              Cryptographic chain ready and verifying…
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
