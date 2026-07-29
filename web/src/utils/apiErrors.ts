export type ApiNextAction =
  | 'REUPLOAD'
  | 'SELECT_CONTRACT_TYPE'
  | 'CONFIRM_OUT_OF_SCOPE'
  | 'RETRY_REVIEW'
  | 'START_NEW_REVIEW'
  | 'CONTACT_SUPPORT'
  | 'RELOAD_GROUNDING'

interface ApiErrorLike {
  userMessage?: string
  nextAction?: string
  next_action?: string
}

export function getNextAction(error: unknown): ApiNextAction | undefined {
  if (!error || typeof error !== 'object') return undefined
  const candidate = error as ApiErrorLike
  return (candidate.nextAction || candidate.next_action) as ApiNextAction | undefined
}

export function getErrorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== 'object') return fallback
  return (error as ApiErrorLike).userMessage || fallback
}

/** API의 사용자 안내 문구만 표시하고, 영문·내부 원문은 화면에 노출하지 않는다. */
export function getSafeKoreanMessage(message: unknown): string | undefined {
  if (typeof message !== 'string') return undefined
  const normalized = message.trim()
  return /[가-힣]/.test(normalized) ? normalized : undefined
}
