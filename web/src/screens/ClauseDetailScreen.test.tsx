import { render, screen } from "@testing-library/react"
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
  standardClauseId: "std_liability_1",
  matchStatus: "CANDIDATE_SELECTED",
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe("협의문구 출처", () => {
  it("내부 ID 대신 표시용 출처와 법령 링크를 출력한다", async () => {
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

    expect(await screen.findByText("사용자 조항 · 제1조 손해배상"))
      .toBeInTheDocument()
    expect(screen.getByText("표준조항 · 제18조 손해배상"))
      .toBeInTheDocument()
    expect(screen.getByRole("link", { name: "법령 근거 · 민법 제390조" }))
      .toHaveAttribute(
        "href",
        "https://www.law.go.kr/법령/민법/제390조",
      )
    expect(screen.queryByText(/uc_rev_suggestion_1/)).not.toBeInTheDocument()
    expect(screen.queryByText(/std_liability_1/)).not.toBeInTheDocument()
    expect(screen.queryByText(/law_1/)).not.toBeInTheDocument()
  })
})
