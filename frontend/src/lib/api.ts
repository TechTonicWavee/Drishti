/**
 * Backend client.
 *
 * Requests go to a relative /api path, which the Vite dev server proxies to
 * FastAPI (see vite.config.ts). Keeping the URL relative means no backend
 * hostname is compiled into the bundle and the browser never has an absolute
 * origin it could be pointed at — which is exactly what an air-gapped
 * deployment wants.
 */

export type Health = {
  status: string
  offline: boolean
}

export class ApiError extends Error {}

const UNREACHABLE =
  'Could not reach the backend. Is it running on port 8000?'

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  let response: Response
  try {
    response = await fetch('/api/health', {
      signal,
      headers: { Accept: 'application/json' },
    })
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw new ApiError(UNREACHABLE)
  }

  // The dev-server proxy answers with a gateway error rather than failing the
  // fetch when the backend is down, so those codes mean "unreachable" here.
  if (response.status === 502 || response.status === 503 || response.status === 504) {
    throw new ApiError(UNREACHABLE)
  }

  if (!response.ok) {
    throw new ApiError(`Backend responded with HTTP ${response.status}.`)
  }

  const body: unknown = await response.json().catch(() => {
    throw new ApiError('Backend returned a response that was not valid JSON.')
  })

  if (
    typeof body !== 'object' ||
    body === null ||
    typeof (body as Health).status !== 'string' ||
    typeof (body as Health).offline !== 'boolean'
  ) {
    throw new ApiError('Backend returned an unexpected payload shape.')
  }

  return body as Health
}
