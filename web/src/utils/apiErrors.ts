export type ApiNextAction =
  | 'REUPLOAD'
  | 'SELECT_CONTRACT_TYPE'
  | 'CONFIRM_OUT_OF_SCOPE'
  | 'RETRY_REVIEW'
  | 'START_NEW_REVIEW'
  | 'CONTACT_SUPPORT'
  | 'RELOAD_GROUNDING'

interface ApiErrorLike {
  code?: string
  message?: string
  nextAction?: string
  next_action?: string
}

const ERROR_MESSAGES: Record<string, string> = {
  FILE_EXTENSION_MISSING: '파일 확장자를 확인할 수 없습니다. 지원하는 파일을 다시 업로드해 주세요.',
  UNSUPPORTED_FILE_TYPE: '지원하지 않는 파일 형식입니다. 지원하는 파일을 다시 업로드해 주세요.',
  FILE_TYPE_MISMATCH: '파일 확장자와 실제 파일 형식이 일치하지 않습니다. 파일을 확인해 주세요.',
  FILE_TOO_LARGE: '파일 크기가 제한을 초과했습니다. 더 작은 파일을 업로드해 주세요.',
  ENCRYPTED_FILE: '암호화된 파일은 검토할 수 없습니다. 암호를 해제한 파일을 업로드해 주세요.',
  CORRUPTED_FILE: '파일을 읽을 수 없습니다. 파일 상태를 확인한 후 다시 업로드해 주세요.',
  EMPTY_DOCUMENT: '검토할 조항을 찾지 못했습니다. 내용을 확인한 후 다시 업로드해 주세요.',
  SESSION_EXPIRED: '검토 세션이 만료되었습니다. 새 계약서를 업로드해 주세요.',
  RESOURCE_NOT_FOUND: '요청한 검토 정보를 찾을 수 없습니다. 새로 시작해 주세요.',
  REVIEW_ALREADY_RUNNING: '같은 검토가 이미 진행 중입니다. 잠시 후 상태를 확인해 주세요.',
  REVIEW_NOT_COMPLETED: '검토가 아직 완료되지 않았습니다. 진행 상태를 확인해 주세요.',
  RATE_LIMITED: '요청이 많습니다. 잠시 후 다시 시도해 주세요.',
  MCP_TIMEOUT: '검토 서비스의 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.',
  CORPUS_UNAVAILABLE: '검토 기준 정보를 현재 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
  INVALID_CONFIG: '서비스 설정을 확인할 수 없습니다. 관리자에게 문의해 주세요.',
  PIPELINE_ERROR: '검토 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.',
  MCP_RESPONSE_INVALID: '검토 서비스 응답을 확인하지 못했습니다. 관리자에게 문의해 주세요.',
  GROUNDING_TIMEOUT: '법령 조회 시간이 초과되었습니다. 다시 시도해 주세요.',
  GROUNDING_UPSTREAM_ERROR: '법령 서비스를 현재 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.',
  CHAT_CONTEXT_INVALID: '현재 검토 결과로 답변할 수 없는 질문입니다. 질문 대상을 확인해 주세요.',
  LLM_OUTPUT_INVALID: '답변 결과를 안전하게 검증하지 못했습니다. 다시 시도해 주세요.',
  LLM_CITATION_INVALID: '답변의 출처를 검증하지 못했습니다. 다시 시도해 주세요.',
  INSUFFICIENT_GROUNDING: '답변 또는 문구 생성에 필요한 근거가 부족합니다.',
  REQUIRED_VALUE_MISSING: '필요한 입력값을 확인해 주세요.',
  GENERATED_FACT_NOT_GROUNDED: '생성 내용의 근거 검증에 실패했습니다. 다시 시도해 주세요.',
  INTERNAL_ERROR: '요청 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.',
  INTERNAL_SERVER_ERROR: '요청 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.',
}

export function getNextAction(error: unknown): ApiNextAction | undefined {
  if (!error || typeof error !== 'object') return undefined
  const candidate = error as ApiErrorLike
  return (candidate.nextAction || candidate.next_action) as ApiNextAction | undefined
}

export function getErrorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== 'object') return fallback
  const { code } = error as ApiErrorLike
  return (code && ERROR_MESSAGES[code]) || fallback
}
