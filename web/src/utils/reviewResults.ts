import type {
  ClauseResult,
  MissingClauseResult,
  MissingStandardClauseData,
  ResultCode,
  ReviewClauseResultData,
} from '../types'

const CLAUSE_RESULT_CODES: ResultCode[] = ['NONE', 'EXTRA', 'NO_MATCH']

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
    category: standard?.category.label || '기타',
    categoryCode: standard?.category.code,
    summary: item.explanation,
    toxic_patterns: item.toxic_patterns,
    standardTitle: standard?.title,
    standardText: standard?.text,
    standardSource: standard?.source,
    standardClauseId: standard?.clause_id,
    standardVersion: standard?.version,
    matchStatus: item.match.status,
  }
}

export function mapMissingClause(item: MissingStandardClauseData): MissingClauseResult {
  return {
    id: item.standard.clause_id,
    category: item.standard.category.label,
    title: item.standard.title,
    text: item.standard.text,
    explanation: item.explanation,
  }
}
