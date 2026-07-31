import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChatbotScreen from './ChatbotScreen'
import { api } from '../api/api'

vi.mock('../api/api', () => ({ api: { chat: vi.fn(), chatStream: vi.fn() } }))
vi.mock('../contexts/MetadataContext', () => ({ useMetadata: () => ({ metadata: {} }) }))

const props = {
  reviewId: 'review-1',
  onClose: vi.fn(),
  isOpen: true,
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
})

describe('챗봇 요청 상태', () => {
  it('답변 대기 중 입력 표시와 중복 전송 차단을 적용한다', async () => {
    vi.mocked(api.chatStream).mockReturnValue(new Promise(() => {}))
    render(<ChatbotScreen {...props} />)
    const input = screen.getByPlaceholderText('검토 결과에 대해 질문해 주세요')
    await userEvent.type(input, '이 조항을 설명해줘')
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))
    expect(screen.getByRole('status')).toHaveTextContent('답변 준비를 시작하고 있습니다')
    expect(screen.getByTestId('typing-dots')).toHaveTextContent('.')
    expect(screen.getByRole('button', { name: /답변 준비 상태 · 답변 준비를 시작/ })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('button', { name: '답변 복사' })).not.toBeInTheDocument()
    expect(input).toBeDisabled()
    expect(api.chatStream).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))
    expect(api.chatStream).toHaveBeenCalledTimes(1)
  })

  it('한글 조합 중 Enter는 전송하지 않고 입력값을 유지한다', async () => {
    render(<ChatbotScreen {...props} />)
    const input = screen.getByPlaceholderText('검토 결과에 대해 질문해 주세요')
    await userEvent.type(input, '계약을 설명해줘')

    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', isComposing: true })

    expect(api.chatStream).not.toHaveBeenCalled()
    expect(input).toHaveValue('계약을 설명해줘')
  })

  it('출처의 내부 ID를 표시하지 않고 안전한 라벨을 사용한다', async () => {
    vi.mocked(api.chatStream).mockResolvedValue({
        answer: '답변입니다.',
        refused: false,
        disclaimer: '',
        limitations: [],
        outcome: 'ANSWERED',
        tool_status: 'OK',
        retryable: false,
        sources: [
          { type: 'USER_CLAUSE', id: 'usr_internal_123' },
          { type: 'STANDARD_CLAUSE', id: 'std_internal_456', display_label: '제5조 · 대금 지급', standard_contract_label: 'SW 프리랜서 표준계약서' },
          { type: 'LAW', id: 'law_internal_789', law_name: '민법', article: '제390조' },
        ],
      } as never)
    render(<ChatbotScreen {...props} />)
    await userEvent.type(screen.getByPlaceholderText('검토 결과에 대해 질문해 주세요'), '근거를 알려줘')
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))
    expect(await screen.findByText('현재 검토 조항')).toBeInTheDocument()
    expect(screen.getByText('SW 프리랜서 표준계약서 · 제5조 · 대금 지급')).toBeInTheDocument()
    expect(screen.getByText('민법 제390조')).toBeInTheDocument()
    expect(screen.queryByText(/internal_/)).not.toBeInTheDocument()
  })

  it('거절 답변 본문이 있으면 중복 안내 문구를 표시하지 않는다', async () => {
    vi.mocked(api.chatStream).mockResolvedValue({
        answer: '제공된 문서에서 관련 정보를 찾을 수 없습니다.',
        refused: true,
        disclaimer: '',
        limitations: [],
        outcome: 'REFUSED',
        tool_status: 'NOT_REQUESTED',
        retryable: false,
        sources: [],
      } as never)
    render(<ChatbotScreen {...props} />)
    await userEvent.type(screen.getByPlaceholderText('검토 결과에 대해 질문해 주세요'), '오늘 점심 뭐 먹지')
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))

    expect(await screen.findByText('제공된 문서에서 관련 정보를 찾을 수 없습니다.')).toBeInTheDocument()
    expect(screen.queryByText('현재 검토 근거로는 답변이 제한됩니다. 질문 범위를 조정해 주세요.')).not.toBeInTheDocument()
  })

  it('같은 검토 세션에서는 새로고침 후에도 대화를 복원한다', async () => {
    vi.mocked(api.chatStream).mockResolvedValue({
        answer: '복원할 답변입니다.', refused: false, disclaimer: '', limitations: [],
        outcome: 'ANSWERED', tool_status: 'OK', retryable: false, sources: [],
      } as never)
    const view = render(<ChatbotScreen {...props} />)
    await userEvent.type(screen.getByPlaceholderText('검토 결과에 대해 질문해 주세요'), '복원할 질문')
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))
    await screen.findByText('복원할 답변입니다.')
    await waitFor(() => expect(sessionStorage.length).toBe(1))

    view.unmount()
    render(<ChatbotScreen {...props} />)

    expect(await screen.findByText('복원할 질문')).toBeInTheDocument()
    expect(screen.getByText('복원할 답변입니다.')).toBeInTheDocument()
  })

  it('완료된 assistant 답변의 하단에서만 답변을 복사한다', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    vi.mocked(api.chatStream).mockResolvedValue({
      answer: '복사할 **답변**입니다.', refused: false, disclaimer: '', limitations: [],
      outcome: 'ANSWERED', tool_status: 'OK', retryable: false, sources: [],
    } as never)
    render(<ChatbotScreen {...props} />)
    await userEvent.type(screen.getByPlaceholderText('검토 결과에 대해 질문해 주세요'), '복사해줘')
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))

    const copyButton = await screen.findByRole('button', { name: '답변 복사' })
    await userEvent.click(copyButton)

    expect(writeText).toHaveBeenCalledWith('복사할 **답변**입니다.')
    expect(screen.getByRole('button', { name: '답변 복사' })).toHaveTextContent('복사됨')
  })

  it('스트림 진행 상태를 사용자 질문 바로 아래에 보존하고 접거나 펼칠 수 있다', async () => {
    let completeStream: (() => void) | undefined
    vi.mocked(api.chatStream).mockImplementation((_reviewId, _message, _key, handlers) => {
      handlers.onProgress?.({
        sequence: 0,
        stage: 'PREPARING_EVIDENCE',
        message: '검토 근거를 준비하고 있습니다.',
        question_category: 'CLAUSE_EXPLANATION',
        context_used: true,
        segment: { index: 1, total: 2 },
      })
      handlers.onDelta?.({ sequence: 1, text: '생성 중인 답변입니다.' })
      return new Promise(resolve => {
        completeStream = () => resolve({
          answer: '스트림 답변입니다.', refused: false, disclaimer: '', limitations: [],
          outcome: 'ANSWERED', tool_status: 'OK', retryable: false, sources: [],
        })
      })
    })
    render(<ChatbotScreen {...props} />)
    await userEvent.type(screen.getByPlaceholderText('검토 결과에 대해 질문해 주세요'), '조항을 설명해줘')
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))

    const toggle = await screen.findByRole('button', { name: /답변 준비 상태 · 검토 근거를 준비/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(toggle)
    expect(screen.getByRole('button', { name: '답변 준비 상태 닫기' })).toBeInTheDocument()
    expect(screen.getByText('검토 근거를 준비하고 있습니다.')).toBeInTheDocument()
    expect(screen.getByText('질문 유형: CLAUSE_EXPLANATION')).toBeInTheDocument()
    expect(screen.getByText('생성 중인 답변입니다.')).toBeInTheDocument()
    expect(screen.queryByTestId('typing-dots')).not.toBeInTheDocument()
    completeStream?.()
    expect(await screen.findByText('스트림 답변입니다.')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('분할 답변의 출처를 누적하고 남은 묶음을 같은 대화 토큰으로 재개한다', async () => {
    vi.mocked(api.chatStream)
      .mockImplementationOnce((_reviewId, _message, _key, handlers) => {
        handlers.onDelta?.({ sequence: 0, text: '## 첫째\n\n첫 묶음' })
        handlers.onSegmentComplete?.({ sequence: 1, segment: { index: 1, total: 2 }, sources: [{ type: 'USER_CLAUSE', display_label: '제1조' }] })
        handlers.onCompleted?.({ sequence: 2, response: {} as never, continuation: { next_segment_offset: 1, remaining_segments: 1 } })
        return Promise.resolve({ answer: '## 첫째\n\n첫 묶음', refused: false, disclaimer: '', limitations: [], outcome: 'ANSWERED', tool_status: 'OK', retryable: false, sources: [], conversation_token: 'ctx_next' } as never)
      })
      .mockResolvedValueOnce({ answer: '## 둘째\n\n남은 묶음', refused: false, disclaimer: '', limitations: [], outcome: 'ANSWERED', tool_status: 'OK', retryable: false, sources: [], conversation_token: 'ctx_done' } as never)
    render(<ChatbotScreen {...props} />)
    await userEvent.type(screen.getByPlaceholderText('검토 결과에 대해 질문해 주세요'), '각 조항을 설명해줘')
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))

    const continueButton = await screen.findByRole('button', { name: '이어서 답변 (1개 묶음)' })
    expect(screen.getByText('제1조')).toBeInTheDocument()
    await userEvent.click(continueButton)

    await screen.findByText('남은 묶음')
    expect(api.chatStream).toHaveBeenLastCalledWith(
      'review-1', '이어서 답변해줘', expect.any(String), expect.any(Object), undefined, [], 'ctx_next',
    )
  })

  it('assistant Markdown을 렌더링하고 raw HTML과 안전하지 않은 링크는 실행하지 않는다', async () => {
    vi.mocked(api.chatStream).mockResolvedValue({
      answer: '## 제목\n\n**굵게**\n\n- 첫째\n- 둘째\n\n| 항목 | 값 |\n| --- | --- |\n| A | B |\n\n[안전 링크](https://example.com) <img src=x onerror=alert(1)> [위험 링크](javascript:alert(1))',
      refused: false, disclaimer: '', limitations: [], outcome: 'ANSWERED', tool_status: 'OK', retryable: false, sources: [],
    } as never)
    render(<ChatbotScreen {...props} />)
    await userEvent.type(screen.getByPlaceholderText('검토 결과에 대해 질문해 주세요'), '형식을 보여줘')
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))

    expect(await screen.findByRole('heading', { name: '제목' })).toBeInTheDocument()
    expect(screen.getByText('굵게').tagName).toBe('STRONG')
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '안전 링크' })).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '위험 링크' })).not.toBeInTheDocument()
  })

  it('상태 헤더를 숨기고 답변 아래에 질문 분류 근거를 표시한다', async () => {
    vi.mocked(api.chatStream).mockResolvedValue({
      answer: '[상태: 검토 결과 질문]\n\n## 별도 확인 필요\n\n11개 조항입니다.',
      refused: false, disclaimer: '', limitations: [], outcome: 'ANSWERED', tool_status: 'OK', retryable: false, sources: [],
      question_category: '검토 결과 질문',
    } as never)
    render(<ChatbotScreen {...props} />)
    await userEvent.type(screen.getByPlaceholderText('검토 결과에 대해 질문해 주세요'), '별도 확인 필요한 조항 11개 아니야?')
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))

    expect(await screen.findByRole('heading', { name: '별도 확인 필요' })).toBeInTheDocument()
    expect(screen.queryByText('[상태: 검토 결과 질문]')).not.toBeInTheDocument()
    expect(screen.getByText('생각한 근거: 검토 결과 질문')).toBeInTheDocument()
    const preparation = screen.getByLabelText('답변 준비 상태')
    expect(preparation).not.toHaveTextContent('11개 조항입니다.')
    expect(preparation.parentElement).toHaveTextContent('11개 조항입니다.')
  })

  it('범위 밖과 근거 부족 제한 사유를 응답 메타데이터로 표시한다', async () => {
    vi.mocked(api.chatStream).mockResolvedValue({
      answer: null, refused: true, refusal_reason: 'OUT_OF_SCOPE', disclaimer: '',
      limitations: ['서버 제한 문구'], outcome: 'REFUSED', tool_status: 'NOT_REQUESTED', retryable: false, sources: [],
      question_category: '선정 불가',
    } as never)
    render(<ChatbotScreen {...props} />)
    await userEvent.type(screen.getByPlaceholderText('검토 결과에 대해 질문해 주세요'), '오늘 점심 뭐 먹지')
    await userEvent.click(screen.getByRole('button', { name: '질문 전송' }))

    expect(await screen.findByText('답변 제한 사유: 검토 자료 범위 밖 질문')).toBeInTheDocument()
    expect(screen.getByText('현재 질문은 계약 검토 결과·표준조항·법령 참고자료 범위를 벗어났습니다.')).toBeInTheDocument()
    expect(screen.queryByText('서버 제한 문구')).not.toBeInTheDocument()
  })
})
