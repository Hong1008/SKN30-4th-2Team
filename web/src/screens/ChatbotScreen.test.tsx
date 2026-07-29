import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/api"
import ChatbotScreen from "./ChatbotScreen"

vi.mock("../api/api", () => ({
  api: { chat: vi.fn() },
}))
vi.mock("../contexts/MetadataContext", () => ({
  useMetadata: () => ({ metadata: null }),
}))

beforeEach(() => {
  vi.clearAllMocks()
  Element.prototype.scrollIntoView = vi.fn()
})

describe("챗봇 답변 출처", () => {
  it("내부 조항 ID 대신 사용자용 조항명을 표시한다", async () => {
    vi.mocked(api.chat).mockResolvedValue({
      data: {
        outcome: "ANSWERED",
        answer: "업무 범위에는 API 명세서 작성이 포함됩니다.",
        refused: false,
        sources: [{
          type: "USER_CLAUSE",
          id: "uc_rev_chat_1",
          display_label: "제1조 목적 및 업무 범위",
        }, {
          type: "STANDARD_CLAUSE",
          id: "std_scope_1",
          display_label: "제1조 업무 범위",
          standard_contract_label: "SW 프리랜서 용역 표준계약서",
        }],
        limitations: [],
        tool_status: "NOT_REQUESTED",
        disclaimer: "법률 자문이 아닙니다.",
      },
    } as never)

    render(
      <ChatbotScreen
        reviewId="rev_chat"
        isOpen
        onClose={vi.fn()}
      />,
    )
    await userEvent.type(
      screen.getByPlaceholderText("검토 결과에 대해 질문해 주세요"),
      "을의 업무 범위에는 무엇이 포함되나요?",
    )
    await userEvent.click(screen.getByRole("button", { name: "질문 전송" }))

    expect(
      await screen.findByText("사용자 조항 · 제1조 목적 및 업무 범위"),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        "SW 프리랜서 용역 표준계약서 · 제1조 업무 범위",
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/uc_rev_chat_1/)).not.toBeInTheDocument()
    expect(screen.queryByText(/std_scope_1/)).not.toBeInTheDocument()
  })

  it("검증된 법령 출처 URL을 새 창 링크로 표시한다", async () => {
    vi.mocked(api.chat).mockResolvedValue({
      data: {
        outcome: "ANSWERED",
        answer: "관련 법령 참고 원문을 확인했습니다.",
        refused: false,
        sources: [{
          type: "LAW",
          id: "law_1",
          display_label: "민법 제390조",
          law_name: "민법",
          article: "제390조",
          source_url: "https://www.law.go.kr/법령/민법/제390조",
        }],
        limitations: [],
        tool_status: "OK",
        disclaimer: "법률 자문이 아닙니다.",
      },
    } as never)

    render(
      <ChatbotScreen
        reviewId="rev_chat"
        isOpen
        onClose={vi.fn()}
      />,
    )
    await userEvent.type(
      screen.getByPlaceholderText("검토 결과에 대해 질문해 주세요"),
      "관련 법령을 알려줘.",
    )
    await userEvent.click(screen.getByRole("button", { name: "질문 전송" }))

    expect(await screen.findByRole("link", { name: /민법 제390조/ }))
      .toHaveAttribute(
        "href",
        "https://www.law.go.kr/법령/민법/제390조",
      )
    expect(screen.queryByText(/law_1/)).not.toBeInTheDocument()
  })
})
