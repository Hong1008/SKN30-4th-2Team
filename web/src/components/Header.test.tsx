import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Header from './Header'

describe('검토 진행 중 헤더', () => {
  it('새 검토 처리 중에는 버튼을 비활성화하고 처리 중으로 표시한다', () => {
    render(<Header currentScreen="processing" onNavigate={vi.fn()} expiresAt={null} canStartNewReview onStartNewReview={vi.fn()} isStartingNewReview navigationLocked />)
    expect(screen.getByRole('button', { name: '처리 중' })).toBeDisabled()
  })

  it('일반 이동은 잠그고 새 검토 버튼은 유지한다', async () => {
    const onNavigate = vi.fn()
    const onStartNewReview = vi.fn()
    render(
      <Header
        currentScreen="processing"
        onNavigate={onNavigate}
        expiresAt={null}
        canStartNewReview
        onStartNewReview={onStartNewReview}
        isStartingNewReview={false}
        navigationLocked
      />,
    )
    const newReview = screen.getByRole('button', { name: '새 검토' })
    expect(newReview).toBeEnabled()
    expect(screen.getByRole('button', { name: '계약서 검토' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '검토 결과' })).toBeDisabled()
    await userEvent.click(newReview)
    expect(onStartNewReview).toHaveBeenCalledTimes(1)
  })
})
