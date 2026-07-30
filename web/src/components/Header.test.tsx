import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Header from './Header'

describe('검토 진행 중 헤더', () => {
  it('새 검토 처리 중에는 버튼을 비활성화하고 처리 중으로 표시한다', () => {
    render(<Header currentScreen="processing" onNavigate={vi.fn()} expiresAt={null} canStartNewReview onStartNewReview={vi.fn()} isStartingNewReview navigationLocked />)
    expect(screen.getByRole('button', { name: '처리 중' })).toBeDisabled()
  })

  it('세션 연장 버튼을 표시하고 요청 중에는 중복 클릭을 막는다', () => {
    const onExtendSession = vi.fn()
    const { rerender } = render(<Header currentScreen="results" onNavigate={vi.fn()} expiresAt="2099-01-01T00:00:00Z" canStartNewReview={false} onStartNewReview={vi.fn()} isStartingNewReview={false} canExtendSession onExtendSession={onExtendSession} />)
    expect(screen.getByRole('button', { name: '연장' })).toBeEnabled()
    rerender(<Header currentScreen="results" onNavigate={vi.fn()} expiresAt="2099-01-01T00:00:00Z" canStartNewReview={false} onStartNewReview={vi.fn()} isStartingNewReview={false} canExtendSession onExtendSession={onExtendSession} isExtendingSession />)
    expect(screen.getByRole('button', { name: '연장 중' })).toBeDisabled()
  })

  it('만료된 세션은 연장할 수 없고 검토 진행 중이면 만료 대신 진행 상태를 표시한다', () => {
    const { rerender } = render(<Header currentScreen="results" onNavigate={vi.fn()} expiresAt="2000-01-01T00:00:00Z" canStartNewReview={false} onStartNewReview={vi.fn()} isStartingNewReview={false} canExtendSession onExtendSession={vi.fn()} />)
    expect(screen.getByRole('button', { name: '연장' })).toBeDisabled()
    expect(screen.getByText(/세션 만료/)).toBeInTheDocument()
    rerender(<Header currentScreen="processing" onNavigate={vi.fn()} expiresAt="2000-01-01T00:00:00Z" canStartNewReview={false} onStartNewReview={vi.fn()} isStartingNewReview={false} canExtendSession={false} onExtendSession={vi.fn()} />)
    expect(screen.getByText('검토 진행 중')).toBeInTheDocument()
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
