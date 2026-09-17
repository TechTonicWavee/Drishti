import { useEffect, useMemo, useState } from 'react'

export type GraphNode = {
  id: string
  type: 'equipment' | 'procedure' | 'revision' | 'standard'
  label: string
  title: string
  subtitle: string
  badge: string
  color: string
  is_overdue?: boolean
  details: Record<string, any>
}

export type GraphEdge = {
  source: string
  target: string
  label: string
  animated?: boolean
  style?: string
}

export type PlantGraphData = {
  nodes: GraphNode[]
  edges: GraphEdge[]
  evaluation_date: string
}

interface PlantGraphViewProps {
  onInvestigate?: (prompt: string) => void
  highlightedNodeId?: string | null
}

export default function PlantGraphView({
  onInvestigate,
  highlightedNodeId: initialHighlight,
}: PlantGraphViewProps) {
  const [data, setData] = useState<PlantGraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(initialHighlight ?? 'eq:V-204')
  const [filterType, setFilterType] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [highlightChain, setHighlightChain] = useState<Set<string>>(new Set())

  // Fetch graph elements
  useEffect(() => {
    let active = true
    fetch('/api/plant-graph/elements')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((payload: PlantGraphData) => {
        if (active) {
          setData(payload)
          setLoading(false)
        }
      })
      .catch((err) => {
        if (active) {
          setError(err.message || 'Failed to load plant knowledge graph')
          setLoading(false)
        }
      })
    return () => {
      active = false
    }
  }, [])

  // Auto-calculate connected chain when a node is selected
  useEffect(() => {
    if (!data || !selectedNodeId) {
      setHighlightChain(new Set())
      return
    }

    const chain = new Set<string>([selectedNodeId])
    // Forward links
    data.edges.forEach((e) => {
      if (e.source === selectedNodeId) chain.add(e.target)
      if (e.target === selectedNodeId) chain.add(e.source)
    })
    // 2nd hop (e.g. equipment -> procedure -> standard / revisions)
    data.edges.forEach((e) => {
      if (chain.has(e.source)) chain.add(e.target)
      if (chain.has(e.target)) chain.add(e.source)
    })
    setHighlightChain(chain)
  }, [data, selectedNodeId])

  const selectedNode = useMemo(() => {
    return data?.nodes.find((n) => n.id === selectedNodeId) ?? null
  }, [data, selectedNodeId])

  // Compute clean layout coordinates for SVG visualization
  const positionedNodes = useMemo(() => {
    if (!data) return []

    // Group into 4 visual vertical columns
    const columns: Record<string, GraphNode[]> = {
      equipment: [],
      procedure: [],
      revision: [],
      standard: [],
    }

    data.nodes.forEach((n) => {
      if (columns[n.type]) columns[n.type].push(n)
    })

    const colX: Record<string, number> = {
      equipment: 100,
      procedure: 380,
      revision: 660,
      standard: 940,
    }

    const result: Array<GraphNode & { x: number; y: number }> = []

    Object.entries(columns).forEach(([type, list]) => {
      const x = colX[type] ?? 100
      const spacingY = Math.max(90, Math.min(130, 680 / (list.length + 1)))
      const startY = 80 + Math.max(0, (680 - (list.length - 1) * spacingY) / 2)

      list.forEach((node, idx) => {
        result.push({
          ...node,
          x,
          y: startY + idx * spacingY,
        })
      })
    })

    return result
  }, [data])

  const nodeMap = useMemo(() => {
    const map = new Map<string, GraphNode & { x: number; y: number }>()
    positionedNodes.forEach((n) => map.set(n.id, n))
    return map
  }, [positionedNodes])

  // Filter nodes matching search and category
  const filteredNodeIds = useMemo(() => {
    if (!data) return new Set<string>()
    const q = searchQuery.toLowerCase().trim()
    const set = new Set<string>()

    data.nodes.forEach((n) => {
      const matchesType =
        filterType === 'all' ||
        (filterType === 'overdue' ? n.is_overdue : n.type === filterType)
      const matchesQuery =
        !q ||
        n.label.toLowerCase().includes(q) ||
        n.title.toLowerCase().includes(q) ||
        n.subtitle.toLowerCase().includes(q)

      if (matchesType && matchesQuery) {
        set.add(n.id)
      }
    })
    return set
  }, [data, filterType, searchQuery])

  if (loading) {
    return (
      <div className="flex h-[550px] items-center justify-center rounded-3xl border border-border bg-card/50">
        <div className="flex items-center gap-3 text-muted-foreground text-sm">
          <span className="size-3 animate-ping rounded-full bg-brand" />
          Constructing plant equipment & revision graph…
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex h-[400px] flex-col items-center justify-center rounded-3xl border border-destructive/20 bg-destructive/5 p-6 text-center">
        <p className="text-destructive font-semibold mb-2">Knowledge Graph Error</p>
        <p className="text-muted-foreground text-sm">{error}</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Top Controls & Category Filter */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-border/70 bg-card/60 p-3.5 backdrop-blur-sm">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mr-1">
            Layer:
          </span>
          {[
            { id: 'all', label: 'All Elements' },
            { id: 'equipment', label: 'Equipment Assets', color: 'text-cyan-400' },
            { id: 'procedure', label: 'Governing SOPs', color: 'text-amber-400' },
            { id: 'revision', label: 'Revision Chains', color: 'text-purple-400' },
            { id: 'standard', label: 'API / ASME Standards', color: 'text-emerald-400' },
            { id: 'overdue', label: '⚠️ Review Overdue', color: 'text-rose-400' },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setFilterType(tab.id)}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                filterType === tab.id
                  ? 'bg-primary text-primary-foreground shadow-sm'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              } ${tab.color ?? ''}`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <div className="relative">
            <input
              type="text"
              placeholder="Search tag (V-204, API 510)…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-8 w-56 rounded-lg border border-border bg-background/80 px-3 text-xs placeholder:text-muted-foreground/60 focus:border-brand focus:outline-none"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-2 text-muted-foreground text-xs hover:text-foreground"
              >
                ✕
              </button>
            )}
          </div>
          <button
            type="button"
            onClick={() => {
              setSelectedNodeId(null)
              setHighlightChain(new Set())
              setSearchQuery('')
              setFilterType('all')
            }}
            className="h-8 rounded-lg border border-border bg-muted/40 px-2.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            Reset
          </button>
        </div>
      </div>

      {/* Main Visual Canvas + Inspector Panel */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Visual Graph Viewport (SVG) */}
        <div className="relative overflow-hidden rounded-3xl border border-border bg-card/80 p-2 shadow-inner lg:col-span-8 h-[620px]">
          {/* Column labels */}
          <div className="absolute top-3 inset-x-0 grid grid-cols-4 px-6 text-center pointer-events-none z-10">
            <span className="text-[10px] font-mono font-bold uppercase tracking-widest text-cyan-400/80">
              1. Assets
            </span>
            <span className="text-[10px] font-mono font-bold uppercase tracking-widest text-amber-400/80">
              2. Governing SOP
            </span>
            <span className="text-[10px] font-mono font-bold uppercase tracking-widest text-purple-400/80">
              3. Revision Chain
            </span>
            <span className="text-[10px] font-mono font-bold uppercase tracking-widest text-emerald-400/80">
              4. Industry Standard
            </span>
          </div>

          <svg
            className="size-full select-none"
            viewBox="0 0 1050 640"
            preserveAspectRatio="xMidYMid meet"
          >
            <defs>
              <linearGradient id="edge-cyan-amber" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.6" />
                <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.6" />
              </linearGradient>
              <linearGradient id="edge-amber-emerald" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.6" />
                <stop offset="100%" stopColor="#10b981" stopOpacity="0.6" />
              </linearGradient>
              <linearGradient id="edge-purple-amber" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#8b5cf6" stopOpacity="0.5" />
                <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.5" />
              </linearGradient>
            </defs>

            {/* Render Edges */}
            <g className="edges">
              {data.edges.map((edge, idx) => {
                const src = nodeMap.get(edge.source)
                const tgt = nodeMap.get(edge.target)
                if (!src || !tgt) return null

                const isInChain =
                  highlightChain.has(edge.source) && highlightChain.has(edge.target)
                const isFiltered =
                  filteredNodeIds.has(edge.source) && filteredNodeIds.has(edge.target)

                // Smooth bezier curve between columns
                const dx = Math.abs(tgt.x - src.x) * 0.5
                const path = `M ${src.x} ${src.y} C ${src.x + dx} ${src.y}, ${tgt.x - dx} ${tgt.y}, ${tgt.x} ${tgt.y}`

                return (
                  <path
                    key={`edge-${idx}`}
                    d={path}
                    fill="none"
                    stroke={
                      isInChain
                        ? '#38bdf8'
                        : isFiltered
                        ? 'rgba(148, 163, 184, 0.25)'
                        : 'rgba(100, 116, 139, 0.1)'
                    }
                    strokeWidth={isInChain ? 3 : 1.5}
                    strokeDasharray={edge.style === 'dashed' ? '4,4' : undefined}
                    className={isInChain ? 'transition-all duration-300' : ''}
                  />
                )
              })}
            </g>

            {/* Render Nodes */}
            <g className="nodes">
              {positionedNodes.map((node) => {
                const isSelected = selectedNodeId === node.id
                const isInChain = highlightChain.has(node.id)
                const isMatch = filteredNodeIds.has(node.id)
                const opacity = isMatch ? (isInChain || !selectedNodeId ? 1 : 0.45) : 0.15

                return (
                  <g
                    key={node.id}
                    transform={`translate(${node.x}, ${node.y})`}
                    onClick={() => setSelectedNodeId(node.id)}
                    className="cursor-pointer transition-all duration-200"
                    opacity={opacity}
                  >
                    {/* Glowing highlight ring */}
                    {isSelected && (
                      <circle
                        r="28"
                        fill="none"
                        stroke={node.color}
                        strokeWidth="2.5"
                        strokeDasharray="4,3"
                        className="animate-spin"
                        style={{ animationDuration: '8s' }}
                      />
                    )}

                    {/* Node Core */}
                    <circle
                      r="18"
                      fill="#0f172a"
                      stroke={node.color}
                      strokeWidth={isSelected ? 3 : 2}
                      className={node.is_overdue ? 'animate-pulse' : ''}
                    />

                    {/* Inner Type Indicator */}
                    <circle
                      r="6"
                      fill={node.color}
                      className={isInChain ? 'animate-ping' : ''}
                      style={{ animationDuration: '3s' }}
                    />

                    {/* Node Label Card */}
                    <text
                      y="-24"
                      textAnchor="middle"
                      className="fill-foreground text-[11px] font-bold font-mono tracking-tight"
                    >
                      {node.label}
                    </text>

                    <text
                      y="32"
                      textAnchor="middle"
                      className="fill-muted-foreground text-[9px] font-sans"
                    >
                      {node.badge}
                    </text>

                    {node.is_overdue && (
                      <text
                        y="-38"
                        textAnchor="middle"
                        className="fill-rose-400 text-[10px] font-bold animate-bounce"
                      >
                        ⚠️ Overdue
                      </text>
                    )}
                  </g>
                )
              })}
            </g>
          </svg>

          {/* Canvas Overlay Legend */}
          <div className="absolute bottom-3 left-4 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground bg-background/80 px-3 py-1.5 rounded-xl border border-border/60">
            <span className="flex items-center gap-1.5">
              <span className="size-2 rounded-full bg-cyan-400" /> Equipment
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2 rounded-full bg-amber-400" /> Procedure
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2 rounded-full bg-purple-400" /> Revision
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2 rounded-full bg-emerald-400" /> Standard
            </span>
          </div>
        </div>

        {/* Node Inspector Drawer */}
        <div className="flex flex-col rounded-3xl border border-border bg-card/70 p-5 shadow-sm lg:col-span-4 h-[620px] overflow-y-auto">
          {selectedNode ? (
            <div className="flex flex-col gap-4">
              {/* Header */}
              <div className="flex items-start justify-between gap-2 border-b border-border/60 pb-3">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className="size-2.5 rounded-full"
                      style={{ backgroundColor: selectedNode.color }}
                    />
                    <span className="font-mono text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      {selectedNode.type}
                    </span>
                    <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-foreground">
                      {selectedNode.badge}
                    </span>
                  </div>
                  <h3 className="font-heading text-lg leading-snug">{selectedNode.title}</h3>
                  <p className="text-xs text-muted-foreground">{selectedNode.subtitle}</p>
                </div>
              </div>

              {/* Statutory Overdue Warning Alert */}
              {selectedNode.is_overdue && (
                <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-3.5 text-xs text-rose-300">
                  <div className="flex items-center gap-2 font-semibold text-rose-400 mb-1">
                    <span>⚠️</span>
                    Statutory Review Exceeded
                  </div>
                  <p className="leading-relaxed">
                    Mandatory 3-year statutory review deadline expired under API 510 Section 6.4. Draft
                    Rev 4 exists in pending state requiring technical review & approval note.
                  </p>
                </div>
              )}

              {/* Node Properties */}
              <div className="flex flex-col gap-2.5">
                <h4 className="text-[11px] font-mono font-bold uppercase tracking-wider text-muted-foreground">
                  Node Specifications
                </h4>
                <div className="divide-y divide-border/40 rounded-xl border border-border/70 bg-muted/20 text-xs">
                  {Object.entries(selectedNode.details).map(([key, val]) => {
                    if (key === 'Revisions' || key === 'Operating Limits') return null
                    return (
                      <div key={key} className="flex justify-between p-2.5 gap-2">
                        <span className="text-muted-foreground">{key}</span>
                        <span className="font-mono font-medium text-right text-foreground">
                          {String(val)}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Revision Chain Details if Procedure */}
              {selectedNode.details.Revisions && (
                <div className="flex flex-col gap-2">
                  <h4 className="text-[11px] font-mono font-bold uppercase tracking-wider text-muted-foreground">
                    Revision History Chain
                  </h4>
                  <div className="flex flex-col gap-1.5">
                    {(selectedNode.details.Revisions as any[]).map((rev) => (
                      <div
                        key={rev.rev}
                        className={`rounded-xl border p-2.5 text-xs ${
                          rev.status.includes('Overdue')
                            ? 'border-rose-500/30 bg-rose-500/10'
                            : rev.status.includes('Pending')
                            ? 'border-purple-500/30 bg-purple-500/10'
                            : 'border-border/60 bg-muted/30'
                        }`}
                      >
                        <div className="flex items-center justify-between font-mono font-medium mb-1">
                          <span className="font-bold">{rev.rev}</span>
                          <span className="text-[11px] text-muted-foreground">{rev.date}</span>
                        </div>
                        <p className="text-[11px] text-foreground/90 font-medium mb-0.5">
                          {rev.status}
                        </p>
                        <p className="text-[10px] text-muted-foreground">{rev.notes}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Operating Limits if Equipment */}
              {selectedNode.details['Operating Limits'] && (
                <div className="flex flex-col gap-2">
                  <h4 className="text-[11px] font-mono font-bold uppercase tracking-wider text-muted-foreground">
                    Operating & Safety Boundaries
                  </h4>
                  <div className="rounded-xl border border-border/70 bg-muted/20 p-2.5 text-xs font-mono divide-y divide-border/30">
                    {Object.entries(selectedNode.details['Operating Limits']).map(([k, v]) => (
                      <div key={k} className="flex justify-between py-1.5">
                        <span className="text-muted-foreground">{k}</span>
                        <span className="text-cyan-400 font-semibold">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Action Buttons */}
              <div className="mt-auto pt-4 flex flex-col gap-2">
                <button
                  type="button"
                  onClick={() => {
                    const prompt =
                      selectedNode.type === 'equipment'
                        ? `Investigate compliance status for asset ${selectedNode.label}, check governing SOP and API 510 review date, and generate a management escalation approval note.`
                        : `Review statutory revision history for procedure ${selectedNode.label} and draft technical approval note.`
                    onInvestigate?.(prompt)
                  }}
                  className="w-full rounded-xl bg-brand px-4 py-2.5 text-xs font-semibold text-brand-foreground shadow-sm transition-all hover:bg-brand/90 flex items-center justify-center gap-2"
                >
                  <span>⚡</span>
                  Investigate in Workbench
                </button>
              </div>
            </div>
          ) : (
            <div className="flex h-full flex-col items-center justify-center text-center text-muted-foreground p-6">
              <span className="text-2xl mb-2">🔍</span>
              <p className="text-xs">Click any equipment asset, procedure, or standard node to inspect its governing chain.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
