import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MainApp } from './App'
import { api } from './api/api'

const showToast = vi.fn()

vi.mock('./api/api', () => ({ api: { deleteReview: vi.fn() } }))
vi.mock('./contexts/MetadataContext', () => ({
  useMetadata: () => ({ metadata: { features: { server_side_cancel: true } } }),
  MetadataProvider: ({ children }: { children: React.ReactNode }) => children,
}))
vi.mock('./contexts/ToastContext', () => ({ useToast: () => ({ showToast }) }))
vi.mock('./components/Header', () => ({ default: ({ onStartNewReview, isStartingNewReview }: any) => <button onClick={onStartNewReview} disabled={isStartingNewReview}>{isStartingNewReview ? '처리 중' : '새 검토'}</button> }))
vi.mock('./components/HorizontalStepper', () => ({ default: () => null }))
vi.mock('./screens/ProcessingScreen', () => ({ default: () => <p>진행 화면</p> }))
vi.mock('./screens/UploadAndTypeScreen', () => ({ default: () => <p>업로드 화면</p> }))
vi.mock('./screens/OutOfScopeScreen', () => ({ default: () => null }))
vi.mock('./screens/ResultsScreen', () => ({ default: () => null }))
vi.mock('./screens/ClauseDetailScreen', () => ({ default: () => null }))
vi.mock('./screens/ChatbotScreen', () => ({ default: () => null }))

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

describe('진행 중 새 검토 시작', () => {
  it('URL의 review ID를 취소하고 완료 전에는 화면 이동과 중복 요청을 막는다', async () => {
    let finishDelete: ((value: unknown) => void) | undefined
    vi.mocked(api.deleteReview).mockReturnValue(new Promise(resolve => { finishDelete = resolve }) as never)
    render(<MemoryRouter initialEntries={['/review/rev_from_url/progress']}><MainApp /></MemoryRouter>)

    await userEvent.click(screen.getByRole('button', { name: '새 검토' }))
    await userEvent.click(screen.getByRole('button', { name: '예' }))

    expect(api.deleteReview).toHaveBeenCalledTimes(1)
    expect(api.deleteReview).toHaveBeenCalledWith('rev_from_url', expect.any(String))
    screen.getAllByRole('button', { name: '처리 중' }).forEach(button => expect(button).toBeDisabled())
    expect(screen.getByText('진행 화면')).toBeInTheDocument()

    finishDelete?.({ data: { review_id: 'rev_from_url', review_state: 'CANCELLED', deleted: true } })
    expect(await screen.findByText('업로드 화면')).toBeInTheDocument()
  })

  it('취소 실패 시 진행 화면과 확인창을 유지한다', async () => {
    vi.mocked(api.deleteReview).mockRejectedValue({ status: 500 })
    render(<MemoryRouter initialEntries={['/review/rev_failed/progress']}><MainApp /></MemoryRouter>)

    await userEvent.click(screen.getByRole('button', { name: '새 검토' }))
    await userEvent.click(screen.getByRole('button', { name: '예' }))

    expect(await screen.findByText('진행 화면')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(showToast).toHaveBeenCalledTimes(1)
  })
})
