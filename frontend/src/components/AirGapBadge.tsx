import { useEffect, useState } from 'react'

/**
 * Always-visible sovereignty indicator.
 *
 * Polls /system/network-status and shows the live count of outbound calls the
 * backend has attempted to anything beyond loopback and the private network.
 *
 * The secondary line reports local calls on purpose. A badge that only ever
 * reads "0 external" looks identical whether the counter is working or stuck,
 * so a visibly rising local count is what shows the instrument is live.
 */

const POLL_MS = 3000

type NetworkStatus = {
  external_call_attempts: number
  internal_call_count: number
  last_external_attempt: { url: string | null; at: string | null } | null
  uptime_seconds: number
}

export default function AirGapBadge() {
  const [status, setStatus] = useState<NetworkStatus | null>(null)
  const [reachable, setReachable] = useState(true)

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    const poll = async () => {
      try {
        const response = await fetch('/api/system/network-status', {
          signal: controller.signal,
        })
        if (!response.ok) throw new Error(String(response.status))
        const body = (await response.json()) as NetworkStatus
        if (!cancelled) {
          setStatus(body)
          setReachable(true)
        }
      } catch {
        if (!cancelled) setReachable(false)
      }
    }

    void poll()
    const timer = setInterval(poll, POLL_MS)
    return () => {
      cancelled = true
      controller.abort()
      clearInterval(timer)
    }
  }, [])

  const breached = (status?.external_call_attempts ?? 0) > 0

  return (
    <div
      className="fixed right-4 top-4 z-50 select-none"
      role="status"
      aria-live="polite"
      title={
        status
          ? `${status.internal_call_count} local call(s), ` +
            `${status.external_call_attempts} external. ` +
            `Uptime ${formatUptime(status.uptime_seconds)}.`
          : 'Waiting for the backend…'
      }
    >
      <div
        className={[
          'flex flex-col gap-0.5 rounded-xl border px-3 py-2 shadow-sm backdrop-blur',
          breached
            ? 'border-destructive/40 bg-destructive/10'
            : 'border-border bg-card/90',
        ].join(' ')}
      >
        <span
          className={[
            'flex items-center gap-1.5 text-[12px] font-medium leading-none',
            breached ? 'text-destructive' : 'text-foreground',
          ].join(' ')}
        >
          {!reachable ? (
            <>⚠️ Backend unreachable</>
          ) : breached ? (
            <>
              ⚠️ {status?.external_call_attempts} external call
              {status?.external_call_attempts === 1 ? '' : 's'}
            </>
          ) : (
            <>
              🔒 Air-gapped — {status?.external_call_attempts ?? 0} external
              call{status?.external_call_attempts === 1 ? '' : 's'}
            </>
          )}
        </span>
        {reachable && status && (
          <span className="text-[10px] leading-none text-muted-foreground">
            {status.internal_call_count} local · {formatUptime(status.uptime_seconds)} up
          </span>
        )}
      </div>
    </div>
  )
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}
