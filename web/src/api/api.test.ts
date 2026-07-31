import { afterEach, describe, expect, it, vi } from "vitest"

const clientMock = vi.hoisted(() => vi.fn())
vi.mock("./client", () => ({ client: clientMock }))
import { api } from "./api"

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
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