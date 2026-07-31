import { act, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/api"
import type { ClauseResult } from "../types"
import ClauseDetailScreen from "./ClauseDetailScreen"

vi.mock("../api/api", () => ({
  api: {
    getGrounding: vi.fn(),
    suggestions: vi.fn(),
  },
}))
vi.mock("../contexts/MetadataContext", () => ({
  useMetadata: () => ({
    metadata: {
      features: { basic_suggestion: true, chat: true },
      result_code_details: [],
    },
  }),
}))

const clause: ClauseResult = {
  id: "uc_rev_suggestion_1",
  article: "제1조",
  excerpt: "손해배상 책임의 범위는 상호 협의한다.",
  status: "NONE",
  category: "책임·손해배상",
  summary: "표준 대응 후보가 확인됐습니다.",
  standardTitle: "손해배상",
  standardText: "귀책사유가 있는 당사자는 발생한 손해를 배상한다.",
  standardContractLabel: "SW 프리랜서 용역 표준계약서",
  matchStatus: "CANDIDATE_SELECTED",
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getGrounding).mockResolvedValue({
    data: { items: [], grounding_status: "NO_RESULT", retryable: false },
  } as never)
})

describe("협의문구 출처", () => {
  it('조항 전환 후 이전 법령 근거 응답을 표시하지 않는다', async () => {
    let resolveFirst: (value: unknown) => void
    let resolveSecond: (value: unknown) => void
    let firstSignal: AbortSignal | undefined
    const firstResponse = new Promise(resolve => { resolveFirst = resolve })
    const secondResponse = new Promise(resolve => { resolveSecond = resolve })
    vi.mocked(api.getGrounding)
      .mockImplementationOnce((_reviewId, _category, signal) => {
        firstSignal = signal
        return firstResponse as never
      })
      .mockImplementationOnce(() => secondResponse as never)
    const firstClause = { ...clause, categoryCode: 'LIABILITY' }
    const secondClause = { ...clause, id: 'uc_rev_suggestion_2', article: '제2조', categoryCode: 'PAYMENT' }
    const { rerender } = render(
      <ClauseDetailScreen clause={firstClause} reviewId="rev_suggestion" onBack={vi.fn()} onChatbot={vi.fn()} />,
    )

    rerender(
      <ClauseDetailScreen clause={secondClause} reviewId="rev_suggestion" onBack={vi.fn()} onChatbot={vi.fn()} />,
    )
    expect(firstSignal?.aborted).toBe(true)

    await act(async () => {
      resolveFirst({
        data: { items: [{ source_id: 'old', law_name: '이전 법령', article: '제1조', text: '이전 근거' }], grounding_status: 'OK', retryable: false },
      })
      resolveSecond({
        data: { items: [{ source_id: 'new', law_name: '새 법령', article: '제2조', text: '새 근거' }], grounding_status: 'OK', retryable: false },
      })
      await Promise.resolve()
    })

    expect(await screen.findByText('새 근거')).toBeInTheDocument()
    expect(screen.queryByText('이전 근거')).not.toBeInTheDocument()
  })

  it('카테고리가 없는 조항으로 전환하면 이전 법령 근거를 비운다', async () => {
    vi.mocked(api.getGrounding).mockResolvedValueOnce({
      data: {
        items: [{ source_id: 'old', law_name: '이전 법령', article: '제1조', text: '이전 근거' }],
        grounding_status: 'OK',
        retryable: false,
      },
    } as never)
    const { rerender } = render(
      <ClauseDetailScreen
        clause={{ ...clause, categoryCode: 'LIABILITY' }}
        reviewId="rev_suggestion"
        onBack={vi.fn()}
        onChatbot={vi.fn()}
      />,
    )
    expect(await screen.findByText('이전 근거')).toBeInTheDocument()

    rerender(
      <ClauseDetailScreen
        clause={{ ...clause, id: 'uc_rev_suggestion_2', article: '제2조', categoryCode: undefined }}
        reviewId="rev_suggestion"
        onBack={vi.fn()}
        onChatbot={vi.fn()}
      />,
    )

    expect(screen.queryByText('이전 근거')).not.toBeInTheDocument()
    expect(api.getGrounding).toHaveBeenCalledTimes(1)
  })

  it('계약서와 표준조항 본문을 동일한 제한 높이의 스크롤 영역으로 표시한다', () => {
    render(<ClauseDetailScreen clause={clause} reviewId="rev_suggestion" onBack={vi.fn()} onChatbot={vi.fn()} />)

    expect(screen.getByTestId('user-clause-scroll')).toHaveClass('overflow-y-auto')
    expect(screen.getByTestId('standard-clause-scroll')).toHaveClass('overflow-y-auto')
    expect(screen.getByTestId('user-clause-scroll').parentElement).toHaveClass('h-[380px]', 'sm:h-[420px]')
    expect(screen.getByTestId('standard-clause-scroll').parentElement).toHaveClass('h-[380px]', 'sm:h-[420px]')
  })

  it('미확정 후보 기반 안내를 표시하고 후보 미확정 조항도 생성을 요청한다', async () => {
    vi.mocked(api.suggestions).mockResolvedValue({
      data: {
        outcome: 'GENERATED',
        text: '계약 원문을 확인해 협의해 주세요.',
        evidence_level: 'CANDIDATE_STANDARD',
        message: '표준조항 후보를 참고한 초안입니다. 원문과 계약 맥락을 확인해 주세요.',
        purpose: '책임 범위 명확화',
        key_changes: [], used_source_keys: [], user_clause_ids: [], standard_clause_ids: [], grounding_source_ids: [],
        sources: [], required_confirmations: [], missing_inputs: [], disclaimer: '법률 자문이 아닙니다.',
      },
    } as never)
    render(<ClauseDetailScreen clause={{ ...clause, matchStatus: 'NO_CANDIDATE', standardText: undefined }} reviewId="rev_suggestion" onBack={vi.fn()} onChatbot={vi.fn()} />)

    await userEvent.click(screen.getByRole('button', { name: /협의 문구 제안 보기/ }))

    expect(api.suggestions).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('표준조항 후보 기반')).toBeInTheDocument()
    expect(screen.getByText(/원문과 계약 맥락을 확인해 주세요/)).toBeInTheDocument()
  })

  it('확인 사항과 누락 입력의 내부 필드명을 사용자용 문구로 바꾼다', async () => {
    vi.mocked(api.suggestions).mockResolvedValue({
      data: {
        outcome: 'REQUIRED_VALUE_MISSING', text: null, evidence_level: null,
        message: '협의 문구 생성에 필요한 입력값을 확인해 주세요.',
        reason_code: 'REQUIRED_VALUE_MISSING', purpose: '책임 범위 명확화',
        key_changes: [], used_source_keys: [], user_clause_ids: [], standard_clause_ids: [], grounding_source_ids: [], sources: [],
        required_confirmations: [{ field: 'law_grounding', placeholder: '관련 법령 원문을 별도로 확인해 주세요.' }],
        missing_inputs: ['liability_limit', 'private_internal_key'], disclaimer: '법률 자문이 아닙니다.',
      },
    } as never)
    render(<ClauseDetailScreen clause={clause} reviewId="rev_suggestion" onBack={vi.fn()} onChatbot={vi.fn()} />)

    await userEvent.click(screen.getByRole('button', { name: /협의 문구 제안 보기/ }))

    expect(await screen.findByText('법령 근거 확인')).toBeInTheDocument()
    expect(screen.getByText('책임 한도')).toBeInTheDocument()
    expect(screen.getByText('추가 확인 정보')).toBeInTheDocument()
    expect(screen.queryByText('law_grounding')).not.toBeInTheDocument()
    expect(screen.queryByText('liability_limit')).not.toBeInTheDocument()
    expect(screen.queryByText('private_internal_key')).not.toBeInTheDocument()
    expect(screen.queryByText('REQUIRED_VALUE_MISSING')).not.toBeInTheDocument()
  })

  it("내부 ID와 URL 링크 없이 표시용 출처를 출력한다", async () => {
    vi.mocked(api.suggestions).mockResolvedValue({
      data: {
        outcome: "GENERATED",
        text: "귀책사유 기준으로 책임 범위를 정해 주시기 바랍니다.",
        purpose: "책임 범위 명확화",
        key_changes: [],
        used_source_keys: ["SRC_USER", "SRC_STANDARD", "SRC_GROUNDING"],
        user_clause_ids: ["uc_rev_suggestion_1"],
        standard_clause_ids: ["std_liability_1"],
        grounding_source_ids: ["law_1"],
        sources: [
          {
            type: "USER_CLAUSE",
            id: "uc_rev_suggestion_1",
            display_label: "제1조 손해배상",
          },
          {
            type: "STANDARD_CLAUSE",
            id: "std_liability_1",
            display_label: "제18조 손해배상",
            standard_contract_label: "SW 프리랜서 용역 표준계약서",
          },
          {
            type: "LAW",
            id: "law_1",
            display_label: "민법 제390조",
            law_name: "민법",
            article: "제390조",
            source_url: "https://www.law.go.kr/법령/민법/제390조",
          },
        ],
        required_confirmations: [],
        missing_inputs: [],
        disclaimer: "법률 자문이 아닙니다.",
      },
    } as never)

    render(
      <ClauseDetailScreen
        clause={clause}
        reviewId="rev_suggestion"
        onBack={vi.fn()}
        onChatbot={vi.fn()}
      />,
    )
    await userEvent.click(
      screen.getByRole("button", { name: /협의 문구 제안 보기/ }),
    )

    expect(await screen.findByText("제1조 손해배상"))
      .toBeInTheDocument()
    expect(
      screen.getByText(
        "SW 프리랜서 용역 표준계약서 · 제18조 손해배상",
      ),
    )
      .toBeInTheDocument()
    expect(screen.getByText("민법 제390조")).toBeInTheDocument()
    expect(screen.queryByRole("link")).not.toBeInTheDocument()
    expect(screen.queryByText(/uc_rev_suggestion_1/)).not.toBeInTheDocument()
    expect(screen.queryByText(/std_liability_1/)).not.toBeInTheDocument()
    expect(screen.queryByText(/law_1/)).not.toBeInTheDocument()
    expect(screen.getByText('출처: SW 프리랜서 용역 표준계약서')).toBeInTheDocument()
    expect(screen.queryByText(/\.md/)).not.toBeInTheDocument()
    expect(screen.queryByText(/버전: 2025/)).not.toBeInTheDocument()
    expect(screen.queryByText(/si_subcontract-2025-art13/)).not.toBeInTheDocument()
  })

  it('표준계약서 표시명이 없으면 내부 정보 대신 기본 출처를 표시한다', async () => {
    render(
      <ClauseDetailScreen
        clause={{ ...clause, standardContractLabel: undefined }}
        reviewId="rev_suggestion"
        onBack={vi.fn()}
        onChatbot={vi.fn()}
      />,
    )

    expect(screen.getByText('출처: 표준계약서')).toBeInTheDocument()
    expect(screen.queryByText(/\.md/)).not.toBeInTheDocument()
    expect(screen.queryByText(/버전:/)).not.toBeInTheDocument()
    expect(screen.queryByText(/si_subcontract-2025-art13/)).not.toBeInTheDocument()
  })
})
