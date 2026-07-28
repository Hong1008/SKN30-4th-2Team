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
  /** 공통 API 오류 envelope에서만 받은 사용자 안내 문구 */
  public readonly userMessage?: string

  constructor(status: number, payload: unknown) {
    const envelope = payload as { error?: ErrorPayload; meta?: { request_id?: string } }
    const error = envelope?.error ?? (payload as ErrorPayload)
    // 화면은 code·retryable·next_action으로 안내한다. 서버 원문은 보관하거나 노출하지 않는다.
    super('요청을 처리하지 못했습니다.')
    this.name = 'ApiError'
    this.status = status
    this.code = error?.code || 'UNKNOWN_ERROR'
    this.retryable = error?.retryable === true
    this.nextAction = error?.next_action
    this.field = error?.field
    this.details = error?.details
    this.requestId = envelope?.meta?.request_id
    const message = typeof error?.message === 'string' ? error.message.trim() : ''
    this.userMessage = /[가-힣]/.test(message)
      ? message
      : undefined
  }
}

/**
 * 성공 HTTP 응답도 공통 API envelope를 지켜야 한다. 화면에서 응답 내부 필드를
 * 바로 읽다가 JavaScript 오류를 노출하지 않도록 API 경계에서 차단한다.
 */
export class ApiResponseFormatError extends Error {
  constructor() {
    super('서버 응답 형식이 올바르지 않습니다. 잠시 후 다시 시도해 주세요.')
    this.name = 'ApiResponseFormatError'
  }
}

function hasResponseData(value: unknown): value is { data: unknown } {
  return typeof value === 'object' && value !== null && 'data' in value
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
  if (!hasResponseData(data)) throw new ApiResponseFormatError()
  return data as T
}
