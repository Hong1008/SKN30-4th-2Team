import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import HorizontalStepper from './HorizontalStepper'

describe('검토 진행 중 단계 이동', () => {
  it('모든 단계 이동 버튼을 잠근다', async () => {
    const onNavigate = vi.fn()
    render(<HorizontalStepper currentScreen="processing" onNavigate={onNavigate} navigationLocked />)
    const buttons = screen.getAllByRole('button')
    expect(buttons.every(button => button.hasAttribute('disabled'))).toBe(true)
    await userEvent.click(buttons[0])
    expect(onNavigate).not.toHaveBeenCalled()
  })
})
