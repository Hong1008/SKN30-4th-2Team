import { afterEach, describe, expect, it, vi } from "vitest"
import { createClientId } from "./clientId"

afterEach(() => vi.unstubAllGlobals())

describe("클라이언트 요청 ID", () => {
  it("HTTP LAN 환경처럼 randomUUID가 없어도 UUID를 생성한다", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.forEach((_, index) => { bytes[index] = index + 1 })
        return bytes
      },
    })

    expect(createClientId()).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    )
  })
})