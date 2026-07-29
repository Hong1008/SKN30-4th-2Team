import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChatbotScreen from './ChatbotScreen'
import { api } from '../api/api'

vi.mock('../api/api', () => ({ api: { chat: vi.fn() } }))
vi.mock('../contexts/MetadataContext', () => ({ useMetadata: () => ({ metadata: {} }) }))

const props = {
  reviewId: 'review-1',
  onClose: vi.fn(),
  isOpen: true,
}

beforeEach(() => vi.clearAllMocks())

describe('챗봇 요청 상태', () => {
  it('답변 대기 중 입력 표시와 중복 전송 차단을 적용한다', async () => {
    vi.mocked(api.chat).mockReturnValue(new Promise(() => {}))
    render(<ChatbotScreen {...props} />)
    const input = screen.getByPlaceholderText('검토 결과에 대해 질문해 주세요')
    await userEvent.type(input, '이 조항을 설명해줘')
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))
    expect(screen.getByRole('status')).toHaveTextContent('답변을 작성하고 있습니다')
    expect(input).toBeDisabled()
    expect(api.chat).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))
    expect(api.chat).toHaveBeenCalledTimes(1)
  })

  it('출처의 내부 ID를 표시하지 않고 안전한 라벨을 사용한다', async () => {
    vi.mocked(api.chat).mockResolvedValue({
      data: {
        answer: '답변입니다.',
        refused: false,
        disclaimer: '',
        limitations: [],
        outcome: 'ANSWERED',
        tool_status: 'OK',
        retryable: false,
        sources: [
          { type: 'USER_CLAUSE', id: 'usr_internal_123' },
          { type: 'STANDARD_CLAUSE', id: 'std_internal_456', display_label: '제5조 · 대금 지급' },
          { type: 'LAW', id: 'law_internal_789', law_name: '민법', article: '제390조' },
        ],
      },
    } as never)
    render(<ChatbotScreen {...props} />)
    await userEvent.type(screen.getByPlaceholderText('검토 결과에 대해 질문해 주세요'), '근거를 알려줘')
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))
    expect(await screen.findByText('현재 검토 조항')).toBeInTheDocument()
    expect(screen.getByText('제5조 · 대금 지급')).toBeInTheDocument()
    expect(screen.getByText('민법 제390조')).toBeInTheDocument()
    expect(screen.queryByText(/internal_/)).not.toBeInTheDocument()
  })
})
