import { API_BASE_URL } from '../config'
import { client } from './client'
import type {
  ApiResponse,
  ChatHistoryMessage,
  ChatResponse,
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
  ): Promise<ApiResponse<ChatResponse>> {
    return client(`/reviews/${encodeURIComponent(reviewId)}/chat/messages`, {
      method: 'POST',
      headers: idempotencyHeaders(idempotencyKey),
      body: JSON.stringify({
        message,
        focus_clause_id: focusClauseId ?? null,
        history: history.slice(-2),
      }),
    })
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
