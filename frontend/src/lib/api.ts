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

export type AuthedUser = {
  user_id: string
  username: string
  display_name: string
  role: string
}

export async function fetchMe(signal?: AbortSignal): Promise<AuthedUser | null> {
  let response: Response
  try {
    response = await fetch('/api/auth/me', {
      signal,
      headers: { Accept: 'application/json' },
    })
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw new ApiError(UNREACHABLE)
  }

  if (response.status === 401) {
    return null
  }

  if (response.status === 502 || response.status === 503 || response.status === 504) {
    throw new ApiError(UNREACHABLE)
  }

  if (!response.ok) {
    throw new ApiError(`Backend responded with HTTP ${response.status}.`)
  }

  const body = (await response.json()) as AuthedUser
  return body
}

export async function loginUser(
  username: string,
  password: string,
): Promise<AuthedUser> {
  let response: Response
  try {
    response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({ username, password }),
    })
  } catch {
    throw new ApiError(UNREACHABLE)
  }

  if (response.status === 502 || response.status === 503 || response.status === 504) {
    throw new ApiError(UNREACHABLE)
  }

  if (!response.ok) {
    const errBody = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new ApiError(errBody?.detail || 'Invalid username or password.')
  }

  return (await response.json()) as AuthedUser
}

export async function loginDemo(): Promise<AuthedUser> {
  let response: Response
  try {
    response = await fetch('/api/auth/demo', {
      method: 'POST',
      headers: { Accept: 'application/json' },
    })
  } catch {
    throw new ApiError(UNREACHABLE)
  }

  if (response.status === 502 || response.status === 503 || response.status === 504) {
    throw new ApiError(UNREACHABLE)
  }

  if (!response.ok) {
    const errBody = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new ApiError(errBody?.detail || 'Could not log in as judge demo.')
  }

  return (await response.json()) as AuthedUser
}

export async function logoutUser(): Promise<void> {
  try {
    await fetch('/api/auth/logout', {
      method: 'POST',
      headers: { Accept: 'application/json' },
    })
  } catch {
    // Best-effort logout
  }
}
