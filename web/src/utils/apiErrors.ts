export type ApiNextAction = "REUPLOAD" | "SELECT_CONTRACT_TYPE" | "CONFIRM_OUT_OF_SCOPE" | "RETRY_REVIEW" | "START_NEW_REVIEW" | "CONTACT_SUPPORT" | "RELOAD_GROUNDING" | "RETRY_LATER"

interface ApiErrorLike {
  userMessage?: string

  nextAction?: string

  next_action?: string
}

export function getNextAction(error: unknown): ApiNextAction | undefined {
  if (!error || typeof error !== "object") return undefined

  const candidate = error as ApiErrorLike

  return (candidate.nextAction ||
    candidate.next_action) as ApiNextAction | undefined
}

export function getErrorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== "object") return fallback

  return (error as ApiErrorLike).userMessage || fallback
}

/** API의 사용자 안내 문구만 표시하고, 영문·내부 원문은 화면에 노출하지 않는다. */

export function getSafeKoreanMessage(message: unknown): string | undefined {
  if (typeof message !== "string") return undefined

  const normalized = message.trim()

  return /[가-힣]/.test(normalized) ? normalized : undefined
}
interface UploadErrorLike extends ApiErrorLike {
  code?: string
  status?: number
}

const uploadCodeMessages: Record<string, string> = {
  FILE_EXTENSION_MISSING: "파일명에 확장자가 없습니다. 확장자를 확인해 주세요.",
  UNSUPPORTED_FILE_TYPE: "지원하지 않는 파일 형식입니다.",
  FILE_TYPE_MISMATCH: "파일 확장자와 실제 파일 형식이 일치하지 않습니다.",
  ENCRYPTED_FILE: "암호화된 파일은 업로드할 수 없습니다. 암호를 해제해 주세요.",
  CORRUPTED_FILE: "파일이 손상되어 읽을 수 없습니다.",
}

export function getUploadErrorMessage(error: unknown, maxSizeMb: number): string {
  const candidate = error && typeof error === "object" ? error as UploadErrorLike : {}
  const codeMessage = candidate.code ? uploadCodeMessages[candidate.code] : undefined
  if (codeMessage) return codeMessage
  if (candidate.status === 413) return `파일 용량이 서버 허용 제한(${maxSizeMb.toFixed(1)}MB)을 초과했습니다.`
  if (candidate.status === 429 && candidate.code === "UPLOAD_CAPACITY_EXCEEDED") {
    return "동시 업로드 요청이 많아 현재 처리할 수 없습니다."
  }
  if (candidate.status === 429) return "서버가 혼잡합니다. 잠시 후 다시 시도해 주세요."
  if (candidate.status === 503) return "현재 서버를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
  if (candidate.status === 504) return "서버 응답 시간이 초과되었습니다. 다시 시도해 주세요."
  if (candidate.status == null) return "네트워크 연결을 확인한 후 다시 시도해 주세요."
  if (candidate.status === 415) return "지원하지 않는 파일 형식이거나 실제 파일 형식이 일치하지 않습니다."
  if (candidate.status === 422) return "파일이 암호화되었거나 손상되어 읽을 수 없습니다."
  return candidate.userMessage || "업로드에 실패했습니다. 다시 시도해 주세요."
}
