import { API_BASE_URL } from '../config'
import { ApiError, ApiResponseFormatError, client } from './client'
import type {
  ApiResponse,
  ChatHistoryMessage,
  ChatResponse,
  ChatStreamCompletedEvent,
  ChatStreamDeltaEvent,
  ChatStreamFailedEvent,
  ChatStreamHandlers,
  ChatStreamProgressEvent,
  ChatStreamSegmentCompleteEvent,
  GroundingData,
  MetadataData,
  ResultsData,
  ReviewCreateData,
  ReviewCancelData,
  ReviewData,
  ReviewSessionData,
  ReviewSessionDeleteData,
  SuggestionResponse,
  SelectionSource,
} from '../types'

const idempotencyHeaders = (idempotencyKey: string): HeadersInit => ({
  'Idempotency-Key': idempotencyKey,
})

const UPLOAD_TIMEOUT_MS = 60_000
const SESSION_DELETE_TIMEOUT_MS = 15_000

class ChatStreamError extends Error {
  readonly retryable: boolean
  readonly nextAction?: string | null
  readonly userMessage?: string
  readonly continuation?: ChatStreamFailedEvent['continuation']
  readonly conversationToken?: string | null

  constructor(event: ChatStreamFailedEvent) {
    super('답변 스트림이 중단되었습니다.')
    this.name = 'ChatStreamError'
    this.retryable = event.error.retryable === true
    this.nextAction = event.error.next_action
    const message = event.error.message?.trim()
    this.userMessage = message && /[가-힣]/.test(message) ? message : undefined
    this.continuation = event.continuation
    this.conversationToken = event.conversation_token
  }
}

function readSseEvent(eventName: string, data: string, handlers: ChatStreamHandlers): ChatResponse | undefined {
  let payload: unknown
  try {
    payload = JSON.parse(data)
  } catch {
    throw new ApiResponseFormatError()
  }
  if (!payload || typeof payload !== 'object') throw new ApiResponseFormatError()

  switch (eventName) {
    case 'progress':
      handlers.onProgress?.(payload as ChatStreamProgressEvent)
      return undefined
    case 'delta':
      handlers.onDelta?.(payload as ChatStreamDeltaEvent)
      return undefined
    case 'segment_complete':
      handlers.onSegmentComplete?.(payload as ChatStreamSegmentCompleteEvent)
      return undefined
    case 'completed': {
      const completed = payload as ChatStreamCompletedEvent
      const response = completed.response
      if (!response || typeof response !== 'object') throw new ApiResponseFormatError()
      handlers.onCompleted?.(completed)
      return response
    }
    case 'failed':
      handlers.onFailed?.(payload as ChatStreamFailedEvent)
      throw new ChatStreamError(payload as ChatStreamFailedEvent)
    default:
      return undefined
  }
}

async function readStreamError(response: Response): Promise<ApiError> {
  const contentType = response.headers.get('content-type') ?? ''
  const payload: unknown = contentType.includes('application/json')
    ? await response.json().catch(() => ({}))
    : await response.text().catch(() => '')
  return new ApiError(response.status, payload, response.headers)
}

async function clientWithTimeout<T>(
  endpoint: string,
  options: RequestInit,
  timeoutMs: number,
  externalSignal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController()
  let timedOut = false
  const abortFromExternal = () => controller.abort(externalSignal?.reason)
  if (externalSignal?.aborted) abortFromExternal()
  else externalSignal?.addEventListener('abort', abortFromExternal, { once: true })
  const timeoutId = globalThis.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  try {
    return await client<T>(endpoint, { ...options, signal: controller.signal })
  } catch (error) {
    if (!timedOut) throw error
    throw {
      name: 'RequestTimeoutError',
      status: 504,
      userMessage: '서버 응답 시간이 초과되었습니다. 다시 시도해 주세요.',
    }
  } finally {
    globalThis.clearTimeout(timeoutId)
    externalSignal?.removeEventListener('abort', abortFromExternal)
  }
}

export const api = {
  getMetadata: (): Promise<ApiResponse<MetadataData>> => client('/metadata'),

  uploadContract(file: File, signal?: AbortSignal): Promise<ApiResponse<ReviewSessionData>> {
    const formData = new FormData()
    formData.append('file', file)
    return clientWithTimeout(
      '/review-sessions',
      { method: 'POST', body: formData },
      UPLOAD_TIMEOUT_MS,
      signal,
    )
  },

  getSession: (sessionId: string, signal?: AbortSignal): Promise<ApiResponse<ReviewSessionData>> =>
    client(`/review-sessions/${encodeURIComponent(sessionId)}`, { signal }),

  deleteSession: (sessionId: string, signal?: AbortSignal): Promise<ApiResponse<ReviewSessionDeleteData>> =>
    clientWithTimeout(
      `/review-sessions/${encodeURIComponent(sessionId)}`,
      { method: 'DELETE' },
      SESSION_DELETE_TIMEOUT_MS,
      signal,
    ),

  extendSession: (sessionId: string): Promise<ApiResponse<ReviewSessionData>> =>
    client(`/review-sessions/${encodeURIComponent(sessionId)}/extend`, { method: 'POST' }),

  selectContractType(
    sessionId: string,
    selectedContractType: string,
    selectionSource: SelectionSource,
  ): Promise<ApiResponse<ReviewSessionData>> {
    return client(`/review-sessions/${encodeURIComponent(sessionId)}/contract-type`, {
      method: 'PATCH',
      body: JSON.stringify({
        selected_contract_type: selectedContractType,
        selection_source: selectionSource,
      }),
    })
  },

  confirmOutOfScope(sessionId: string, confirmed: boolean): Promise<ApiResponse<ReviewSessionData>> {
    return client(`/review-sessions/${encodeURIComponent(sessionId)}/out-of-scope-confirmation`, {
      method: 'POST',
      body: JSON.stringify({ confirmed }),
    })
  },

  startReview(sessionId: string, idempotencyKey: string): Promise<ApiResponse<ReviewCreateData>> {
    return client('/reviews', {
      method: 'POST',
      headers: idempotencyHeaders(idempotencyKey),
      body: JSON.stringify({ session_id: sessionId }),
    })
  },

  pollReviewStatus: (reviewId: string, signal?: AbortSignal): Promise<ApiResponse<ReviewData>> =>
    client(`/reviews/${encodeURIComponent(reviewId)}`, { signal }),

  getResults: (reviewId: string, signal?: AbortSignal): Promise<ApiResponse<ResultsData>> =>
    client(`/reviews/${encodeURIComponent(reviewId)}/results`, { signal }),

  deleteReview(reviewId: string, idempotencyKey: string): Promise<ApiResponse<ReviewCancelData>> {
    return client(`/reviews/${encodeURIComponent(reviewId)}`, {
      method: 'DELETE',
      headers: idempotencyHeaders(idempotencyKey),
    })
  },

  retryReview(reviewId: string, idempotencyKey: string): Promise<ApiResponse<ReviewCreateData>> {
    return client(`/reviews/${encodeURIComponent(reviewId)}/retry`, {
      method: 'POST',
      headers: idempotencyHeaders(idempotencyKey),
    })
  },

  getGrounding(reviewId: string, category: string, signal?: AbortSignal): Promise<ApiResponse<GroundingData>> {
    const query = new URLSearchParams({ category })
    return client(`/reviews/${encodeURIComponent(reviewId)}/grounding?${query}`, { signal })
  },

  chat(
    reviewId: string,
    message: string,
    idempotencyKey: string,
    focusClauseId?: string,
    history: ChatHistoryMessage[] = [],
    conversationToken?: string,
  ): Promise<ApiResponse<ChatResponse>> {
    return client(`/reviews/${encodeURIComponent(reviewId)}/chat/messages`, {
      method: 'POST',
      headers: idempotencyHeaders(idempotencyKey),
      body: JSON.stringify({
        message,
        focus_clause_id: focusClauseId ?? null,
        history: history.slice(-2),
        conversation_token: conversationToken ?? null,
      }),
    })
  },

  async chatStream(
    reviewId: string,
    message: string,
    idempotencyKey: string,
    handlers: ChatStreamHandlers,
    focusClauseId?: string,
    history: ChatHistoryMessage[] = [],
    conversationToken?: string,
  ): Promise<ChatResponse> {
    const body = JSON.stringify({
      message,
      focus_clause_id: focusClauseId ?? null,
      history: history.slice(-2),
      conversation_token: conversationToken ?? null,
    })
    let response: Response
    try {
      response = await fetch(`${API_BASE_URL}/reviews/${encodeURIComponent(reviewId)}/chat/messages/stream`, {
        method: 'POST',
        headers: {
          ...idempotencyHeaders(idempotencyKey),
          'Content-Type': 'application/json',
        },
        body,
        credentials: 'include',
      })
    } catch {
      // SSE 연결 자체가 시작되지 않은 경우에만 기존 JSON 경로로 안전하게 대체한다.
      const fallback = await api.chat(reviewId, message, idempotencyKey, focusClauseId, history, conversationToken)
      return fallback.data
    }

    if (!response.ok) throw await readStreamError(response)
    if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body) {
      throw new ApiResponseFormatError()
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let completedResponse: ChatResponse | undefined

    const consumeFrame = (frame: string) => {
      const lines = frame.split('\n')
      const eventName = lines.find(line => line.startsWith('event:'))?.slice('event:'.length).trim()
      const data = lines
        .filter(line => line.startsWith('data:'))
        .map(line => line.slice('data:'.length).trimStart())
        .join('\n')
      if (!eventName || !data) return
      const responseFromEvent = readSseEvent(eventName, data, handlers)
      if (responseFromEvent) completedResponse = responseFromEvent
    }

    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n?/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        consumeFrame(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
      }
      if (done) break
    }
    if (buffer.trim()) consumeFrame(buffer)
    if (!completedResponse) throw new ApiResponseFormatError()
    return completedResponse
  },

  suggestions(
    reviewId: string,
    userClauseId: string,
    purpose: string,
    idempotencyKey: string,
    inputs?: Record<string, unknown>,
  ): Promise<ApiResponse<SuggestionResponse>> {
    return client(`/reviews/${encodeURIComponent(reviewId)}/suggestions`, {
      method: 'POST',
      headers: idempotencyHeaders(idempotencyKey),
      body: JSON.stringify({ user_clause_id: userClauseId, purpose, inputs }),
    })
  },

  reviewEventsUrl(reviewId: string): string {
    return `${API_BASE_URL}/reviews/${encodeURIComponent(reviewId)}/events`
  },
}
