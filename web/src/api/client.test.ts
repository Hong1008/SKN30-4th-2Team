import { afterEach, describe, expect, it, vi } from "vitest"
import { ApiError, client } from "./client"

afterEach(() => vi.unstubAllGlobals())

describe("API 오류 응답", () => {
  it("숫자 Retry-After를 초 단위로 보존한다", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({
              error: {
                code: "UPLOAD_CAPACITY_EXCEEDED",
                message: "현재 업로드 요청이 많습니다.",
                retryable: true,
                next_action: "RETRY_LATER",
              },
            }),
            {
              status: 429,
              headers: {
                "content-type": "application/json",
                "Retry-After": "5",
              },
            },
          ),
        ),
    )
    const error = (await client("/review-sessions").catch(
      (value) => value,
    )) as ApiError
    expect(error.status).toBe(429)
    expect(error.code).toBe("UPLOAD_CAPACITY_EXCEEDED")
    expect(error.nextAction).toBe("RETRY_LATER")
    expect(error.retryAfterSeconds).toBe(5)
  })

  it("HTTP 날짜 Retry-After를 남은 초로 변환한다", async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-07-29T12:00:00Z"))
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("", {
            status: 429,
            headers: { "Retry-After": "Wed, 29 Jul 2026 12:00:05 GMT" },
          }),
        ),
    )
    const error = (await client("/review-sessions").catch(
      (value) => value,
    )) as ApiError
    expect(error.retryAfterSeconds).toBe(5)
    vi.useRealTimers()
  })

  it.each(["-1", "invalid"])(
    "잘못된 Retry-After %s는 무시한다",
    async (value) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            new Response("", {
              status: 429,
              headers: { "Retry-After": value },
            }),
          ),
      )
      const error = (await client("/review-sessions").catch(
        (reason) => reason,
      )) as ApiError
      expect(error.retryAfterSeconds).toBeUndefined()
    },
  )

  it("비 JSON 413 서버 원문을 사용자 메시지로 노출하지 않는다", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("<html>nginx internal error</html>", {
            status: 413,
            headers: { "content-type": "text/html" },
          }),
        ),
    )
    const error = (await client("/review-sessions").catch(
      (value) => value,
    )) as ApiError
    expect(error.status).toBe(413)
    expect(error.userMessage).toBeUndefined()
    expect(error.message).not.toContain("nginx")
  })
})
