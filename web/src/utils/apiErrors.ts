export type ApiNextAction =
  | 'REUPLOAD'
  | 'SELECT_CONTRACT_TYPE'
  | 'CONFIRM_OUT_OF_SCOPE'
  | 'RETRY_REVIEW'
  | 'START_NEW_REVIEW'
  | 'CONTACT_SUPPORT'
  | 'RELOAD_GROUNDING'

interface ApiErrorLike {
  message?: string
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
  return (error as ApiErrorLike).message || fallback
}
