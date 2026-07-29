import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import SourceReferences from './SourceReferences'

describe('공통 출처 UI', () => {
  it('표시 정보가 없을 때 내부 ID 대신 안전한 문구를 사용한다', () => {
    render(<SourceReferences sources={[
      { type: 'USER_CLAUSE' },
      { type: 'STANDARD_CLAUSE' },
      { type: 'LAW' },
    ]} />)
    expect(screen.getByText('현재 검토 조항')).toBeInTheDocument()
    expect(screen.getByText('대응 표준조항')).toBeInTheDocument()
    expect(screen.getByText('법령 근거')).toBeInTheDocument()
    expect(screen.queryByText(/usr_|std_|law_/)).not.toBeInTheDocument()
  })

  it('표시용 정보와 법령 이름·조항을 렌더링한다', () => {
    render(<SourceReferences sources={[
      { type: 'USER_CLAUSE', display_label: '제3조 · 책임 범위' },
      { type: 'STANDARD_CLAUSE', display_label: '제5조 · 대금 지급', standard_contract_label: 'SW 프리랜서 표준계약서' },
      { type: 'LAW', law_name: '민법', article: '제390조' },
    ]} />)
    expect(screen.getByText('제3조 · 책임 범위')).toBeInTheDocument()
    expect(screen.getByText('SW 프리랜서 표준계약서 · 제5조 · 대금 지급')).toBeInTheDocument()
    expect(screen.getByText('민법 제390조')).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })
})
