import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MainApp } from './App'
import { api } from './api/api'
import { SESSION_ID_KEY, getChatHistoryStorageKey } from './config'

const showToast = vi.fn()

vi.mock('./api/api', () => ({ api: { deleteReview: vi.fn(), getSession: vi.fn(), extendSession: vi.fn(), pollReviewStatus: vi.fn() } }))
vi.mock('./contexts/MetadataContext', () => ({
  useMetadata: () => ({ metadata: { features: { server_side_cancel: true } } }),
  MetadataProvider: ({ children }: { children: React.ReactNode }) => children,
}))
vi.mock('./contexts/ToastContext', () => ({ useToast: () => ({ showToast }) }))
vi.mock('./components/Header', () => ({ default: ({ onStartNewReview, isStartingNewReview, canExtendSession, onExtendSession, isExtendingSession, expiresAt }: any) => <div><button onClick={onStartNewReview} disabled={isStartingNewReview}>{isStartingNewReview ? '처리 중' : '새 검토'}</button>{canExtendSession && <button onClick={onExtendSession} disabled={isExtendingSession}>{isExtendingSession ? '연장 중' : '연장'}</button>}<span>{expiresAt}</span></div> }))
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
    sessionStorage.setItem(getChatHistoryStorageKey('rev_from_url'), '[]')
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
    expect(sessionStorage.getItem(getChatHistoryStorageKey('rev_from_url'))).toBeNull()
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

describe('세션 연장', () => {
  it('연장 성공 전 중복 요청을 막고 새 expires_at을 반영한다', async () => {
    const originalExpiry = new Date(Date.now() + 10 * 60_000).toISOString()
    const extendedExpiry = new Date(Date.now() + 30 * 60_000).toISOString()
    localStorage.setItem(SESSION_ID_KEY, 'ses_extend')
    vi.mocked(api.getSession).mockResolvedValue({ data: { session_id: 'ses_extend', expires_at: originalExpiry } } as never)
    let finishExtend: ((value: unknown) => void) | undefined
    vi.mocked(api.extendSession).mockReturnValue(new Promise(resolve => { finishExtend = resolve }) as never)
    render(<MemoryRouter initialEntries={['/review']}><MainApp /></MemoryRouter>)

    const extendButton = await screen.findByRole('button', { name: '연장' })
    await userEvent.click(extendButton)

    expect(api.extendSession).toHaveBeenCalledTimes(1)
    expect(api.extendSession).toHaveBeenCalledWith('ses_extend')
    expect(screen.getByRole('button', { name: '연장 중' })).toBeDisabled()
    finishExtend?.({ data: { session_id: 'ses_extend', expires_at: extendedExpiry } })
    expect(await screen.findByText(extendedExpiry)).toBeInTheDocument()
  })

  it('연장 실패 시 기존 expires_at을 유지한다', async () => {
    const originalExpiry = new Date(Date.now() + 10 * 60_000).toISOString()
    localStorage.setItem(SESSION_ID_KEY, 'ses_failed')
    vi.mocked(api.getSession).mockResolvedValue({ data: { session_id: 'ses_failed', expires_at: originalExpiry } } as never)
    vi.mocked(api.extendSession).mockRejectedValue({ status: 500 })
    render(<MemoryRouter initialEntries={['/review']}><MainApp /></MemoryRouter>)

    await userEvent.click(await screen.findByRole('button', { name: '연장' }))

    expect(await screen.findByText(originalExpiry)).toBeInTheDocument()
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('세션 시간'), 'error')
  })

  it('연장 요청이 410이면 만료된 로컬 세션을 정리한다', async () => {
    const expiry = new Date(Date.now() + 10 * 60_000).toISOString()
    localStorage.setItem(SESSION_ID_KEY, 'ses_expired')
    vi.mocked(api.getSession).mockResolvedValue({ data: { session_id: 'ses_expired', expires_at: expiry } } as never)
    vi.mocked(api.extendSession).mockRejectedValue({ status: 410 })
    render(<MemoryRouter initialEntries={['/review']}><MainApp /></MemoryRouter>)

    await userEvent.click(await screen.findByRole('button', { name: '연장' }))

    expect(localStorage.getItem(SESSION_ID_KEY)).toBeNull()
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('세션이 만료'), 'error')
  })
})
