export const SESSION_ID_KEY = 'draft_review_session_id';
export const REVIEW_ID_KEY = 'draft_review_id';
export const CHAT_HISTORY_STORAGE_KEY_PREFIX = 'draft_review_chat_history:';
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export const getChatHistoryStorageKey = (reviewId: string) =>
  `${CHAT_HISTORY_STORAGE_KEY_PREFIX}${reviewId}`;
