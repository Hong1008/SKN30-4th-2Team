import { describe, expect, it } from 'vitest'
import { getStandardContractLabel } from './standardContractLabel'

describe('표준계약서 사용자 표시명', () => {
  it('백엔드 표시명을 그대로 사용한다', () => {
    expect(getStandardContractLabel('SI 하도급 표준계약서')).toBe('SI 하도급 표준계약서')
  })

  it.each([undefined, null, '', '   '])('표시명이 %s이면 안전한 기본 문구를 사용한다', value => {
    expect(getStandardContractLabel(value)).toBe('표준계약서')
  })
})
