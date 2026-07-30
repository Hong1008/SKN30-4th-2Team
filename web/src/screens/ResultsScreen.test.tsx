import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ResultsScreen from './ResultsScreen'
import { api } from '../api/api'

vi.mock('../api/api', () => ({ api: { getResults: vi.fn(), deleteReview: vi.fn() } }))
vi.mock('../contexts/MetadataContext', () => ({ useMetadata: () => ({ metadata: { categories: [], result_code_details: [], features: {} } }) }))

describe('결과 화면 상태 이동', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('검토 미완료 응답은 진행 화면 복귀를 요청한다', async () => {
    vi.mocked(api.getResults).mockRejectedValue({ status: 409 })
    const onReviewInProgress = vi.fn()
    render(<ResultsScreen reviewId="review-1" onClauseClick={vi.fn()} onChatbot={vi.fn()} onReviewInProgress={onReviewInProgress} />)
    await waitFor(() => expect(onReviewInProgress).toHaveBeenCalledTimes(1))
  })

  it('누락 조항 표시명이 없으면 내부 정보 대신 표준계약서로 표시한다', async () => {
    vi.mocked(api.getResults).mockResolvedValue({
      data: {
        review: {
          review_id: 'review-1',
          review_state: 'COMPLETED',
          mcp_review_status: 'OK',
          contract_type: 'UNKNOWN',
          started_at: null,
          completed_at: null,
          expires_at: '',
          disclaimer: '',
        },
        summary: {
          clause_results: { total: 0, NONE: 0, EXTRA: 0, NO_MATCH: 0 },
          missing_standard_clauses: 1,
          toxic_pattern_candidates: 0,
        },
        clause_results: [],
        missing_standard_clauses: [{
          result_type: { code: 'MISSING', label: '누락' },
          standard: {
            standard_contract_label: '',
            category: { code: 'PAYMENT', label: '대금 지급' },
            title: '대금 지급 조항',
            text: '표준 조항 본문',
          },
          explanation: '필수 조항이 없습니다.',
        }],
      },
    } as never)

    render(<ResultsScreen reviewId="review-1" onClauseClick={vi.fn()} onChatbot={vi.fn()} />)

    await userEvent.click(await screen.findByRole('button', { name: /추가 확인 항목/ }))
    expect(await screen.findByText('표준계약서')).toBeInTheDocument()
    expect(screen.queryByText(/si_subcontract-2025-art13/)).not.toBeInTheDocument()
    expect(screen.queryByText(/\.md/)).not.toBeInTheDocument()
    expect(screen.queryByText(/버전: 2025/)).not.toBeInTheDocument()
  })
})
