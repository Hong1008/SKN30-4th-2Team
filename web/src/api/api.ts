import { client } from './client';
import { mockApi } from './mockApi';
import type { ApiResponse, MetadataData, ReviewSessionData, ReviewData, ResultsData } from '../types';

export const api = {
  // --- REAL API (Implemented by Backend) ---
  // 로컬 개발/미리보기 환경에서 실제 백엔드(8000)가 안 켜져있을 경우 UI 테스트를 위해 Mock으로 자동 폴백합니다.

  async getMetadata(): Promise<ApiResponse<MetadataData>> {
    return client<ApiResponse<MetadataData>>('/metadata');
  },

  async uploadContract(file: File): Promise<ApiResponse<ReviewSessionData>> {
    const formData = new FormData();
    formData.append('file', file);
    return client<ApiResponse<ReviewSessionData>>('/review-sessions', {
      method: 'POST',
      body: formData
    });
  },

  async getSession(sessionId: string): Promise<ApiResponse<ReviewSessionData>> {
    return client<ApiResponse<ReviewSessionData>>(`/review-sessions/${sessionId}`).catch(err => {
      // 404, 410은 기획된 에러이므로 그대로 throw (복구 로직 테스트용)
      if (err.status === 404 || err.status === 410) throw err;
      throw err; // getSession은 mockApi에 없으므로 그냥 에러 던짐
    });
  },

  async selectContractType(sessionId: string, type: string): Promise<ApiResponse<ReviewSessionData>> {
    return client<ApiResponse<ReviewSessionData>>(`/review-sessions/${sessionId}/contract-type`, {
      method: 'PATCH',
      body: JSON.stringify({ contract_type: type })
    });
  },

  // --- REVIEW DATA API (Real API with Fallback) ---

  async startReview(sessionId: string, idempotencyKey?: string): Promise<ApiResponse<ReviewData>> {
    const headers: any = { 'Content-Type': 'application/json' };
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;

    return client<ApiResponse<ReviewData>>('/reviews', {
      method: 'POST',
      headers,
      body: JSON.stringify({ session_id: sessionId })
    });
  },

  async pollReviewStatus(reviewId: string, currentPercent: number): Promise<ApiResponse<ReviewData>> {
    return client<ApiResponse<ReviewData>>(`/reviews/${reviewId}`);
  },

  async getResults(reviewId: string): Promise<ApiResponse<ResultsData>> {
    return client<ApiResponse<ResultsData>>(`/reviews/${reviewId}/results`);
  },

  async getGrounding(reviewId: string, category: string): Promise<ApiResponse<any>> {
    return client<ApiResponse<any>>(`/reviews/${reviewId}/grounding?category=${category}`);
  },

  // --- CHAT & SUGGESTIONS API (Mock for now until Chat API spec is final) ---

  async retryReview(reviewId: string, idempotencyKey?: string): Promise<ApiResponse<ReviewData>> {
    const headers: any = { 'Content-Type': 'application/json' };
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;

    return client<ApiResponse<ReviewData>>(`/reviews/${reviewId}/retry`, {
      method: 'POST',
      headers
    });
  },

  async chat(reviewId: string, message: string, idempotencyKey?: string): Promise<ApiResponse<any>> {
    return mockApi.chat(reviewId, message, idempotencyKey);
  },

  async suggestions(reviewId: string, clauseId: string, idempotencyKey?: string): Promise<ApiResponse<any>> {
    return mockApi.suggestions(reviewId, clauseId, idempotencyKey);
  }
};
