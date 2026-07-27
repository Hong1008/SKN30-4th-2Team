import { API_BASE_URL } from '../config'

export interface ErrorPayload {
  code?: string
  message?: string
  retryable?: boolean
  next_action?: string
  field?: string | null
  details?: unknown
}

export class ApiError extends Error {
  public readonly code: string
  public readonly status: number
  public readonly retryable: boolean
  public readonly nextAction?: string
  public readonly field?: string | null
  public readonly details?: unknown
  public readonly requestId?: string

  constructor(status: number, payload: unknown) {
    const envelope = payload as { error?: ErrorPayload; meta?: { request_id?: string } }
    const error = envelope?.error ?? (payload as ErrorPayload)
    super(error?.message || `API Error: ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = error?.code || 'UNKNOWN_ERROR'
    this.retryable = error?.retryable === true
    this.nextAction = error?.next_action
    this.field = error?.field
    this.details = error?.details
    this.requestId = envelope?.meta?.request_id
  }
}

export const client = async <T>(endpoint: string, options: RequestInit = {}): Promise<T> => {
  const headers = new Headers(options.headers)
  const isJsonBody = typeof options.body === 'string'
  if (isJsonBody && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
    credentials: 'include',
  })

  const contentType = response.headers.get('content-type') ?? ''
  const data: unknown = contentType.includes('application/json')
    ? await response.json().catch(() => ({}))
    : await response.text().catch(() => '')

  if (!response.ok) throw new ApiError(response.status, data)
  return data as T
}
