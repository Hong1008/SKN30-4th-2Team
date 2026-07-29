import { describe, expect, it } from 'vitest'
import { extractClauseArticle, mapClauseResult, mapMissingClause } from './reviewResults'

describe('조항 번호 표시', () => {
  it.each([
    ['제 1 조 목적', '제1조'],
    ['제12조 계약기간', '제12조'],
    ['제 5 조의 2 책임', '제5조의2'],
    ['제3조의2 비밀유지', '제3조의2'],
  ])('%s에서 조항 번호를 추출한다', (text, expected) => {
    expect(extractClauseArticle(text)).toBe(expected)
  })
})

const standard = {
  standard_contract_label: 'SI 하도급 표준계약서',
  category: { code: 'PAYMENT', label: '대금 지급' },
  title: '대금 지급',
  text: '검수 완료 후 대금을 지급한다.',
}

describe('표준조항 사용자 표시 변환', () => {
  it('내부 표준조항 메타데이터 대신 표시명을 사용한다', () => {
    const result = mapClauseResult({
      user_clause_id: 'uc_review_1',
      user_clause: '제2조 대금 지급',
      deviation: { code: 'NONE', label: '표준 대응 후보 있음' },
      match: { status: 'CANDIDATE_SELECTED', standard },
      explanation: '표준 대응 후보가 확인됐습니다.',
      toxic_patterns: [],
    })
    expect(result.standardContractLabel).toBe('SI 하도급 표준계약서')
    expect(result).not.toHaveProperty('standardClauseId')
    expect(result).not.toHaveProperty('standardSource')
    expect(result).not.toHaveProperty('standardVersion')
  })

  it('누락 조항도 원본 파일명 없이 표시명을 사용한다', () => {
    const result = mapMissingClause({
      result_type: { code: 'MISSING', label: '표준조항 누락 가능성' },
      standard,
      explanation: '포함 여부를 확인해 주세요.',
    })
    expect(result.standardContractLabel).toBe('SI 하도급 표준계약서')
    expect(JSON.stringify(result)).not.toContain('.md')
  })
})
