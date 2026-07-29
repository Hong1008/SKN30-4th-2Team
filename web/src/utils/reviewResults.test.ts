import { describe, expect, it } from 'vitest'
import { extractClauseArticle } from './reviewResults'

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
