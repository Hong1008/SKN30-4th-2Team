import type {
  ClauseResult,
  MissingClauseResult,
  MissingStandardClauseData,
  ResultCode,
  ReviewClauseResultData,
} from '../types'

const CLAUSE_RESULT_CODES: ResultCode[] = ['NONE', 'EXTRA', 'NO_MATCH']

const CATEGORY_DISPLAY_LABELS: Record<string, string> = {
  PAYMENT: '대금지급 / 임금',
  IP_OWNERSHIP: '저작권/지식재산권 귀속',
  SCOPE_SOW: '과업범위 / 담당업무',
  CONTRACT_PERIOD: '계약기간 / 근로계약기간',
  TERMINATION: '계약해지 및 해제',
  CONFIDENTIALITY: '비밀유지 / 비밀준수',
  LIABILITY: '손해배상 및 책임',
  DISPUTE: '분쟁해결 및 관할법원',
  SOCIAL_INSURANCE: '사회보험 가입',
  WORKING_HOURS: '근로 및 휴게시간',
  HOLIDAY_LEAVE: '휴일 및 연차유급휴가',
  DELIVERY_INSPECTION: '납품 및 검수',
  WARRANTY: '하자담보',
  SUBCONTRACTING: '재하도급 금지',
  INDUSTRIAL_SAFETY: '산업안전보건',
  INFO_SECURITY: '정보보안',
  GENERAL: '일반 조항',
}

function displayCategoryLabel(label: string | undefined): string {
  if (!label) return '기타'
  return CATEGORY_DISPLAY_LABELS[label] || label
}

export function extractClauseArticle(text: string): string {
  const normalized = text.trim()
  const match = normalized.match(/^제\s*(\d+(?:-\d+)?)\s*조(?:\s*의\s*(\d+))?/)
  if (!match) return normalized.split(/\s+/)[0] || '조항'
  return `제${match[1]}조${match[2] ? `의${match[2]}` : ''}`
}

export function mapClauseResult(item: ReviewClauseResultData): ClauseResult {
  const code = item.deviation.code as ResultCode
  if (!CLAUSE_RESULT_CODES.includes(code)) {
    throw new Error(`지원하지 않는 검토 결과 코드입니다: ${item.deviation.code}`)
  }
  const status = code
  const standard = item.match.standard

  return {
    id: item.user_clause_id,
    article: extractClauseArticle(item.user_clause),
    excerpt: item.user_clause,
    status,
    category: displayCategoryLabel(standard?.category.label),
    categoryCode: standard?.category.code,
    summary: item.explanation,
    toxic_patterns: item.toxic_patterns,
    standardTitle: standard?.title,
    standardText: standard?.text,
    standardContractLabel: standard?.standard_contract_label,
    matchStatus: item.match.status,
  }
}

export function mapMissingClause(item: MissingStandardClauseData): MissingClauseResult {
  return {
    id: `${item.standard.category.code}:${item.standard.title}`,
    category: displayCategoryLabel(item.standard.category.label),
    standardContractLabel: item.standard.standard_contract_label,
    title: item.standard.title,
    text: item.standard.text,
    explanation: item.explanation,
  }
}
