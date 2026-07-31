import { afterEach, describe, expect, it, vi } from "vitest"

const clientMock = vi.hoisted(() => vi.fn())
vi.mock("./client", () => ({ client: clientMock }))
import { api } from "./api"

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  clientMock.mockReset()
})

describe("업로드 요청 시간 제한", () => {
  it.each([
    ["upload", 60_000, () => api.uploadContract(new File(["pdf"], "contract.pdf"))],
    ["delete", 15_000, () => api.deleteSession("session-timeout")],
  ])("%s 요청이 제한 시간을 넘으면 504 오류로 종료한다", async (_name, timeout, request) => {
    vi.useFakeTimers()
    clientMock.mockImplementation((_endpoint, options: RequestInit) =>
      new Promise((_resolve, reject) => {
        options.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        )
      }),
    )
    const assertion = expect(request()).rejects.toMatchObject({ status: 504 })
    await vi.advanceTimersByTimeAsync(timeout as number)
    await assertion
  })
})

describe("챗봇 SSE", () => {
  it("progress·delta·segment_complete·completed 이벤트를 순서대로 소비한다", async () => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode([
          "event: progress\ndata: {\"sequence\":0,\"stage\":\"PREPARING_EVIDENCE\",\"message\":\"근거를 준비하고 있습니다.\",\"context_used\":true}\n\n",
          "event: delta\ndata: {\"sequence\":1,\"text\":\"답변 조각\"}\n\n",
          "event: segment_complete\ndata: {\"sequence\":2,\"segment\":{\"index\":1,\"total\":2},\"sources\":[]}\n\n",
          "event: completed\ndata: {\"sequence\":3,\"response\":{\"outcome\":\"ANSWERED\",\"answer\":\"완성 답변\",\"sources\":[],\"refused\":false,\"limitations\":[],\"tool_status\":\"OK\",\"disclaimer\":\"\"},\"continuation\":{\"next_segment_offset\":1,\"remaining_segments\":1}}\n\n",
        ].join("")))
        controller.close()
      },
    })
    const fetchMock = vi.fn().mockResolvedValue(new Response(stream, {
      headers: { "content-type": "text/event-stream" },
    }))
    vi.stubGlobal("fetch", fetchMock)
    const onProgress = vi.fn()
    const onDelta = vi.fn()
    const onSegmentComplete = vi.fn()
    const onCompleted = vi.fn()

    await expect(api.chatStream("review-1", "질문", "chat-key", { onProgress, onDelta, onSegmentComplete, onCompleted }))
      .resolves.toMatchObject({ answer: "완성 답변" })

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/reviews/review-1/chat/messages/stream"),
      expect.objectContaining({ method: "POST", credentials: "include" }),
    )
    expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ stage: "PREPARING_EVIDENCE" }))
    expect(onDelta).toHaveBeenCalledWith(expect.objectContaining({ text: "답변 조각" }))
    expect(onSegmentComplete).toHaveBeenCalledWith(expect.objectContaining({ segment: { index: 1, total: 2 } }))
    expect(onCompleted).toHaveBeenCalledWith(expect.objectContaining({ continuation: { next_segment_offset: 1, remaining_segments: 1 } }))
  })

  it("헤더를 받기 전 SSE 연결이 실패하면 기존 JSON 요청으로 대체한다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network unavailable")))
    clientMock.mockResolvedValue({
      data: {
        outcome: "ANSWERED", answer: "JSON 답변", sources: [], refused: false,
        limitations: [], tool_status: "OK", disclaimer: "",
      },
    })

    await expect(api.chatStream("review-1", "질문", "chat-key", {}))
      .resolves.toMatchObject({ answer: "JSON 답변" })

    expect(clientMock).toHaveBeenCalledWith(
      "/reviews/review-1/chat/messages",
      expect.objectContaining({ method: "POST" }),
    )
  })
})
