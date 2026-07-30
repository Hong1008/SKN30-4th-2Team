import { describe, expect, it } from 'vitest'
import { getReviewIdFromPath } from './reviewRoute'

describe('현재 검토 경로 ID', () => {
  it('진행 및 결과 URL에서 활성 review ID를 읽는다', () => {
    expect(getReviewIdFromPath('/review/rev_active/progress')).toBe('rev_active')
    expect(getReviewIdFromPath('/review/rev_result/results/clause/uc_1')).toBe('rev_result')
  })

  it('업로드 화면과 잘못된 ID는 활성 검토로 취급하지 않는다', () => {
    expect(getReviewIdFromPath('/review')).toBeNull()
    expect(getReviewIdFromPath('/review/new/progress')).toBeNull()
    expect(getReviewIdFromPath('/review/%E0%A4%A/progress')).toBeNull()
  })
})
