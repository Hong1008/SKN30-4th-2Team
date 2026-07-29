import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import UploadAndTypeScreen from "./UploadAndTypeScreen"
import { api } from "../api/api"

vi.mock("../api/api", () => ({
  api: {
    uploadContract: vi.fn(),
    getSession: vi.fn(),
    selectContractType: vi.fn(),
    startReview: vi.fn(),
  },
}))
vi.mock("../contexts/MetadataContext", () => ({
  useMetadata: () => ({
    metadata: {
      file_policy: {
        extensions: ["pdf"],
        max_size_bytes: 10,
        allowed_mime_types: [],
        encrypted_file_allowed: false,
      },
      contract_types: [{ code: "SW_FREELANCER", label: "SW 프리랜서", description: "설명", enabled_for_mvp: true }],
    },
  }),
}))
vi.mock("../contexts/ToastContext", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

const props = {
  sessionId: null,
  setSessionId: vi.fn(),
  setReviewId: vi.fn(),
  onNext: vi.fn(),
  onOutOfScope: vi.fn(),
  setSessionExpiresAt: vi.fn(),
}
const input = (container: HTMLElement) =>
  container.querySelector('input[type="file"]') as HTMLInputElement
const file = (size: number) =>
  new File([new Uint8Array(size)], "contract.pdf", { type: "application/pdf" })

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.uploadContract).mockReset()
})

describe("계약서 업로드", () => {
  it("정확히 최대 허용 크기인 파일은 서버로 전송한다", async () => {
    vi.mocked(api.uploadContract).mockResolvedValue({
      data: { can_start_review: false, allowed_actions: ["REUPLOAD"] },
    } as never)
    const { container } = render(<UploadAndTypeScreen {...props} />)
    fireEvent.change(input(container), { target: { files: [file(10)] } })
    await waitFor(() => expect(api.uploadContract).toHaveBeenCalledTimes(1))
  })

  it("최대 허용 크기를 초과한 파일은 서버로 전송하지 않는다", () => {
    const { container } = render(<UploadAndTypeScreen {...props} />)
    fireEvent.change(input(container), { target: { files: [file(11)] } })
    expect(api.uploadContract).not.toHaveBeenCalled()
    expect(screen.getByText(/파일 크기가 제한/)).toBeInTheDocument()
  })

  it("빠른 연속 입력에도 업로드 요청은 하나만 전송한다", async () => {
    vi.mocked(api.uploadContract).mockReturnValue(new Promise(() => {}))
    const { container } = render(<UploadAndTypeScreen {...props} />)
    const picker = input(container)
    fireEvent.change(picker, { target: { files: [file(5)] } })
    fireEvent.change(picker, { target: { files: [file(5)] } })
    await waitFor(() => expect(api.uploadContract).toHaveBeenCalledTimes(1))
  })

  it("429 후 보존한 파일로 사용자가 직접 재시도한다", async () => {
    vi.mocked(api.uploadContract)
      .mockRejectedValueOnce({
        status: 429,
        code: "UPLOAD_CAPACITY_EXCEEDED",
        nextAction: "RETRY_LATER",
        retryAfterSeconds: 5,
        userMessage: "현재 업로드 요청이 많습니다.",
      })
      .mockResolvedValueOnce({
        data: { can_start_review: false, allowed_actions: ["REUPLOAD"] },
      } as never)
    const { container } = render(<UploadAndTypeScreen {...props} />)
    fireEvent.change(input(container), { target: { files: [file(5)] } })
    expect(await screen.findByText(/5초 후/)).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole("button", { name: "같은 파일 다시 시도" }),
    )
    await waitFor(() => expect(api.uploadContract).toHaveBeenCalledTimes(2))
  })
  it("범위 외 세션에서 유형 다시 선택 화면으로 복귀하면 자동 재이동하지 않는다", async () => {
    vi.mocked(api.getSession).mockResolvedValue({
      data: {
        upload: { file_name: "out-of-scope.pdf", size_bytes: 5 },
        selected_contract_type: "SW_FREELANCER",
        suggested_contract_type: "SW_FREELANCER",
        candidates: [{ contract_type: "SW_FREELANCER" }],
        expires_at: "2099-01-01T00:00:00Z",
        review_state: "OUT_OF_SCOPE_CONFIRMATION_REQUIRED",
      },
    } as never)

    render(<UploadAndTypeScreen {...props} sessionId="session-1" />)

    expect(await screen.findByText("out-of-scope.pdf")).toBeInTheDocument()
    expect(props.onOutOfScope).not.toHaveBeenCalled()
  })
  it("업로드 취소 시 요청을 abort하고 파일 입력을 복구한다", async () => {
    let uploadSignal: AbortSignal | undefined
    vi.mocked(api.uploadContract).mockImplementation((_file, signal) => {
      uploadSignal = signal
      return new Promise(() => {})
    })
    const { container } = render(<UploadAndTypeScreen {...props} />)
    fireEvent.change(input(container), { target: { files: [file(5)] } })

    await userEvent.click(await screen.findByRole("button", { name: "업로드 취소" }))

    expect(uploadSignal?.aborted).toBe(true)
    expect(input(container)).toBeInTheDocument()
  })
  it("metadata 확장자를 파일 accept에 반영한다", () => {
    const { container } = render(<UploadAndTypeScreen {...props} />)
    expect(input(container)).toHaveAttribute("accept", ".pdf")
  })

  it.each([
    [{ status: 503 }, "현재 서버를 사용할 수 없습니다"],
    [{ status: 504 }, "응답 시간이 초과"],
    [{}, "네트워크 연결"],
  ])("일시 오류 %j 후 파일과 계약 유형을 유지해 재시도한다", async (error, expectedMessage) => {
    vi.mocked(api.uploadContract)
      .mockRejectedValueOnce(error)
      .mockResolvedValueOnce({ data: { can_start_review: false, allowed_actions: ["REUPLOAD"] } } as never)
    const { container } = render(<UploadAndTypeScreen {...props} />)
    const typeButton = screen.getByRole("button", { name: /SW 프리랜서/ })
    await userEvent.click(typeButton)
    fireEvent.change(input(container), { target: { files: [file(5)] } })

    expect(await screen.findByText(new RegExp(expectedMessage))).toBeInTheDocument()
    expect(typeButton).toHaveAttribute("aria-pressed", "true")
    await userEvent.click(screen.getByRole("button", { name: "같은 파일 다시 시도" }))
    await waitFor(() => expect(api.uploadContract).toHaveBeenCalledTimes(2))
  })

  it("애플리케이션 413을 metadata 기반 파일 크기 제한으로 안내한다", async () => {
    vi.mocked(api.uploadContract).mockRejectedValue({ status: 413 })
    const { container } = render(<UploadAndTypeScreen {...props} />)
    fireEvent.change(input(container), { target: { files: [file(5)] } })

    expect(await screen.findByText(/서버 허용 제한\(0\.0MB\)/)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "같은 파일 다시 시도" })).not.toBeInTheDocument()
  })
})
