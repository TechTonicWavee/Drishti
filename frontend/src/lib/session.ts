/**
 * Session lifecycle.
 *
 * The backend extracts durable facts when a session ends, so something has to
 * say when that is. Guessing server-side would either fire mid-conversation or
 * never fire, so the browser signals it: on inactivity, and when the page goes
 * away.
 */

export type Turn = { role: string; content: string }

// Long enough that a pause to read a long answer is not the end of a session,
// short enough that a walked-away-from tab is closed out the same shift.
const IDLE_MS = 3 * 60 * 1000

let sessionId: string | null = null
let idleTimer: ReturnType<typeof setTimeout> | null = null
// Guards against ending twice — the idle timer and the page-hide handler can
// otherwise both fire, and extraction would run on the same messages twice.
let ended = false

function newId(): string {
  // randomUUID needs a secure context; localhost qualifies, but a plain-http
  // LAN address does not, and the plant will be served over exactly that.
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `s-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

/** The current session, started if there is not one. */
export function ensureSession(): string {
  if (sessionId && !ended) return sessionId
  sessionId = newId()
  ended = false
  void fetch('/api/session/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  }).catch(() => {
    // Session tracking is best-effort; the chat works without it.
  })
  return sessionId
}

/** Close the session and hand its messages over for extraction. */
export function endSession(messages: Turn[], beacon = false): void {
  if (!sessionId || ended) return
  ended = true
  clearIdle()

  const body = JSON.stringify({ session_id: sessionId, messages })

  if (beacon && navigator.sendBeacon) {
    // The page is going away, so a normal fetch would be cancelled mid-flight.
    // sendBeacon is the only request the browser guarantees to finish.
    navigator.sendBeacon(
      '/api/session/end',
      new Blob([body], { type: 'application/json' }),
    )
    return
  }

  void fetch('/api/session/end', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    keepalive: true,
  }).catch(() => {})
}

function clearIdle(): void {
  if (idleTimer) clearTimeout(idleTimer)
  idleTimer = null
}

/** Restart the inactivity countdown. Call after each turn. */
export function touchSession(getMessages: () => Turn[]): void {
  clearIdle()
  idleTimer = setTimeout(() => endSession(getMessages()), IDLE_MS)
}

/** Wire page-hide to ending the session. Returns a cleanup function. */
export function watchPageExit(getMessages: () => Turn[]): () => void {
  const onHide = () => {
    // pagehide rather than beforeunload: it is the event that actually fires
    // on mobile and on tab discard, where beforeunload is unreliable.
    if (document.visibilityState === 'hidden') endSession(getMessages(), true)
  }
  document.addEventListener('visibilitychange', onHide)
  window.addEventListener('pagehide', () => endSession(getMessages(), true))
  return () => document.removeEventListener('visibilitychange', onHide)
}
