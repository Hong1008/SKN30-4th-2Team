import { render, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ResultsScreen from './ResultsScreen'
import { api } from '../api/api'

vi.mock('../api/api', () => ({ api: { getResults: vi.fn(), deleteReview: vi.fn() } }))
vi.mock('../contexts/MetadataContext', () => ({ useMetadata: () => ({ metadata: { categories: [], result_code_details: [], features: {} } }) }))

describe('결과 화면 상태 이동', () => {
  it('검토 미완료 응답은 진행 화면 복귀를 요청한다', async () => {
    vi.mocked(api.getResults).mockRejectedValue({ status: 409 })
    const onReviewInProgress = vi.fn()
    render(<ResultsScreen reviewId="review-1" onClauseClick={vi.fn()} onChatbot={vi.fn()} onReviewInProgress={onReviewInProgress} />)
    await waitFor(() => expect(onReviewInProgress).toHaveBeenCalledTimes(1))
  })
})
