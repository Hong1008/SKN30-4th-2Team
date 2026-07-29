import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/api"
import { MetadataProvider } from "./MetadataContext"

vi.mock("../api/api", () => ({ api: { getMetadata: vi.fn() } }))

beforeEach(() => vi.clearAllMocks())

describe("metadata 안전 처리", () => {
  it("metadata 조회 실패 시 업로드 화면을 열지 않고 안전한 오류를 표시한다", async () => {
    vi.mocked(api.getMetadata).mockRejectedValue(new Error("internal metadata error"))
    render(<MetadataProvider><div>업로드 화면</div></MetadataProvider>)

    expect(await screen.findByText("설정 정보를 불러오지 못했습니다.")).toBeInTheDocument()
    expect(screen.queryByText("업로드 화면")).not.toBeInTheDocument()
    expect(screen.queryByText("internal metadata error")).not.toBeInTheDocument()
  })
})