import { describe, expect, it } from 'vitest'
import { getSuggestionFieldLabel } from './suggestionFields'

describe('협의 문구 확인 필드 표시명', () => {
  it('알려진 내부 필드를 사용자용 명칭으로 변환한다', () => {
    expect(getSuggestionFieldLabel('law_grounding')).toBe('법령 근거 확인')
    expect(getSuggestionFieldLabel('liability_limit')).toBe('책임 한도')
  })

  it('알 수 없는 내부 필드를 화면에 노출하지 않는다', () => {
    expect(getSuggestionFieldLabel('private_internal_key')).toBe('추가 확인 정보')
  })
})
