import type { ReviewProgress, ReviewSseEvent } from '../types'

export function toReviewProgress(event: ReviewSseEvent): ReviewProgress | null {
  if (!event.stage || event.current === null || event.percent === null) {
    return null
  }

  return {
    sequence: event.sequence,
    stage: event.stage,
    current: event.current,
    total: event.total,
    percent: event.percent,
    message: event.message,
  }
}

export function isTerminalReviewState(reviewState: string): boolean {
  return ['COMPLETED', 'FAILED', 'CANCELLED', 'EXPIRED'].includes(reviewState)
}
