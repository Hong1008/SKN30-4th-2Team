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
  SuggestionResponse,
  SelectionSource,
} from '../types'

const idempotencyHeaders = (idempotencyKey: string): HeadersInit => ({
  'Idempotency-Key': idempotencyKey,
})

export const api = {
  getMetadata: (): Promise<ApiResponse<MetadataData>> => client('/metadata'),

  uploadContract(file: File, signal?: AbortSignal): Promise<ApiResponse<ReviewSessionData>> {
    const formData = new FormData()
    formData.append('file', file)
    return client('/review-sessions', { method: 'POST', body: formData, signal })
  },

  getSession: (sessionId: string, signal?: AbortSignal): Promise<ApiResponse<ReviewSessionData>> =>
    client(`/review-sessions/${encodeURIComponent(sessionId)}`, { signal }),

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
        history: history.slice(-10),
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
