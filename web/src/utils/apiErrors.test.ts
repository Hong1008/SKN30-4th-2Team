import { describe, expect, it } from "vitest"
import { getUploadErrorMessage } from "./apiErrors"

describe("업로드 오류 안내", () => {
  it.each([
    ["FILE_EXTENSION_MISSING", "확장자"],
    ["UNSUPPORTED_FILE_TYPE", "지원하지 않는 파일 형식"],
    ["FILE_TYPE_MISMATCH", "실제 파일 형식"],
    ["ENCRYPTED_FILE", "암호화"],
    ["CORRUPTED_FILE", "손상"],
  ])("%s 코드를 구분해 안내한다", (code, expected) => {
    expect(getUploadErrorMessage({ code }, 10)).toContain(expected)
  })

  it("UPLOAD_CAPACITY_EXCEEDED는 파일 크기가 아닌 혼잡 안내를 반환한다", () => {
    const message = getUploadErrorMessage({ status: 429, code: "UPLOAD_CAPACITY_EXCEEDED" }, 10)
    expect(message).toContain("동시 업로드")
    expect(message).not.toContain("파일 용량")
  })
})