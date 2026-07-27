import type {
  ClauseResult,
  MissingClauseResult,
  MissingStandardClauseData,
  ResultCode,
  ReviewClauseResultData,
} from '../types'

const CLAUSE_RESULT_CODES: ResultCode[] = ['NONE', 'EXTRA', 'NO_MATCH']

export function mapClauseResult(item: ReviewClauseResultData): ClauseResult {
  const code = item.deviation.code as ResultCode
  if (!CLAUSE_RESULT_CODES.includes(code)) {
    throw new Error(`지원하지 않는 검토 결과 코드입니다: ${item.deviation.code}`)
  }
  const status = code
  const standard = item.match.standard

  return {
    id: item.user_clause_id,
    article: item.user_clause.split(' ')[0] || '조항',
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
