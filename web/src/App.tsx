import { createClientId } from './utils/clientId'
import { useState, useEffect, useRef } from 'react'
import { BrowserRouter, Routes, Route, useNavigate, useLocation, useParams, Navigate } from 'react-router-dom'
import type { Screen, ClauseResult } from './types'
import { SESSION_ID_KEY, REVIEW_ID_KEY } from './config'
import Header from './components/Header'
import HorizontalStepper from './components/HorizontalStepper'
import UploadAndTypeScreen from './screens/UploadAndTypeScreen'
import OutOfScopeScreen from './screens/OutOfScopeScreen'
import ProcessingScreen from './screens/ProcessingScreen'
import ResultsScreen from './screens/ResultsScreen'
import ClauseDetailScreen from './screens/ClauseDetailScreen'
import ChatbotScreen from './screens/ChatbotScreen'
import { MetadataProvider, useMetadata } from './contexts/MetadataContext'
import { api } from './api/api'
import { mapClauseResult } from './utils/reviewResults'
import { useToast } from './contexts/ToastContext'
import { getErrorMessage } from './utils/apiErrors'
import { getReviewIdFromPath } from './utils/reviewRoute'

function ProcessingRoute({ fallbackReviewId, onDone, onRetry, onStartNewReview }: {
  fallbackReviewId: string | null
  onDone: (id: string) => void
  onRetry: (id: string) => void
  onStartNewReview: (id: string) => void
}) {
  const { id } = useParams()
  const reviewId = (id && id !== 'new' ? id : null) ?? fallbackReviewId
  return reviewId
    ? <ProcessingScreen reviewId={reviewId} onDone={() => onDone(reviewId)} onRetry={onRetry} onStartNewReview={() => onStartNewReview(reviewId)} />
    : <Navigate to="/review" replace />
}

function ResultsRoute({ fallbackReviewId, onClauseClick, onChatbot, onReviewInProgress }: {
  fallbackReviewId: string | null
  onClauseClick: (clause: ClauseResult, reviewId: string) => void
  onChatbot: (reviewId: string) => void
  onReviewInProgress: (reviewId: string) => void
}) {
  const { id } = useParams()
  const reviewId = id ?? fallbackReviewId
  return reviewId ? <ResultsScreen reviewId={reviewId} onClauseClick={(clause) => onClauseClick(clause, reviewId)} onChatbot={() => onChatbot(reviewId)} onReviewInProgress={() => onReviewInProgress(reviewId)} /> : <Navigate to="/review" replace />
}

function ClauseRoute({ fallbackReviewId, selectedClause, onBack, onChatbot }: {
  fallbackReviewId: string | null
  selectedClause: ClauseResult | null
  onBack: (reviewId: string) => void
  onChatbot: (reviewId: string, clause: ClauseResult) => void
}) {
  const { id, clauseId } = useParams()
  const reviewId = id ?? fallbackReviewId
  const [clause, setClause] = useState<ClauseResult | null>(selectedClause?.id === clauseId ? selectedClause : null)
  const [isLoading, setIsLoading] = useState(selectedClause?.id !== clauseId)

  useEffect(() => {
    if (!reviewId || clause) return
    const controller = new AbortController()
    api.getResults(reviewId, controller.signal)
      .then((response) => {
        const rawClause = response.data.clause_results.find((item) => item.user_clause_id === clauseId)
        if (!rawClause) {
          setClause(null)
          return
        }
        setClause(mapClauseResult(rawClause))
      })
      .catch(() => setClause(null))
      .finally(() => setIsLoading(false))
    return () => controller.abort()
  }, [reviewId, clauseId, clause])

  if (!reviewId) return <Navigate to="/review" replace />
  if (isLoading) return <p className="text-sm text-slate-500">조항 정보를 불러오고 있습니다.</p>
  if (!clause) return <Navigate to={`/review/${reviewId}/results`} replace />
  return <ClauseDetailScreen clause={clause} reviewId={reviewId} onBack={() => onBack(reviewId)} onChatbot={() => onChatbot(reviewId, clause)} />
}

export function MainApp() {
  const { metadata } = useMetadata()
  const { showToast } = useToast()
  const navigate = useNavigate()
  const location = useLocation()

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [reviewId, setReviewId] = useState<string | null>(null)
  const [selectedClause, setSelectedClause] = useState<ClauseResult | null>(null)
  const [sessionExpiresAt, setSessionExpiresAt] = useState<string | null>(null)
  const [isStartingNewReview, setIsStartingNewReview] = useState(false)
  const [showNewReviewConfirm, setShowNewReviewConfirm] = useState(false)
  const [reviewIdToDiscard, setReviewIdToDiscard] = useState<string | null>(null)
  const [chatTarget, setChatTarget] = useState<{ reviewId: string; clause?: ClauseResult } | null>(null)
  const [isChatOpen, setIsChatOpen] = useState(false)
  const discardRequestKey = useRef<string | null>(null)
  const chatTriggerRef = useRef<HTMLElement | null>(null)

  const openChat = (id: string, clause?: ClauseResult) => {
    chatTriggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setChatTarget({ reviewId: id, clause })
    setIsChatOpen(true)
  }
  const closeChat = () => {
    setIsChatOpen(false)
    requestAnimationFrame(() => chatTriggerRef.current?.focus())
  }
  const clearChat = () => {
    setIsChatOpen(false)
    setChatTarget(null)
    chatTriggerRef.current = null
  }
  const clearLocalReview = () => {
    clearChat()
    setSessionId(null)
    setReviewId(null)
    setSelectedClause(null)
    setSessionExpiresAt(null)
    localStorage.removeItem(SESSION_ID_KEY)
    localStorage.removeItem(REVIEW_ID_KEY)
  }

  useEffect(() => {
    if (!sessionExpiresAt) return
    const expiresAt = new Date(sessionExpiresAt).getTime()
    if (!Number.isFinite(expiresAt)) return
    const timeout = window.setTimeout(() => {
      clearLocalReview()
      showToast('세션 보관 기간이 만료되었습니다. 새 검토를 시작해 주세요.', 'error')
      navigate('/review', { replace: true })
    }, Math.max(0, expiresAt - Date.now()))
    return () => window.clearTimeout(timeout)
  }, [sessionExpiresAt])

  // Recovery logic for session and review IDs
  useEffect(() => {
    const savedSession = localStorage.getItem(SESSION_ID_KEY)
    const savedReview = localStorage.getItem(REVIEW_ID_KEY)
    
    if (savedSession) setSessionId(savedSession)
    if (savedReview) setReviewId(savedReview)

    // Only run routing on initial mount if not already deep linked
    const isRoot = location.pathname === '/' || location.pathname === '' || location.pathname === '/review'

    if (savedReview) {
      api.pollReviewStatus(savedReview).then(res => {
        setSessionExpiresAt(res.data.expires_at)
        if (res.data.review_state === 'COMPLETED') {
          if (isRoot) navigate(`/review/${savedReview}/results`, { replace: true })
        } else {
          if (isRoot) navigate(`/review/${savedReview}/progress`, { replace: true })
        }
      }).catch((err) => {
        if (err.status === 404 || err.status === 410) {
          clearLocalReview()
        }
        if (isRoot) navigate('/review', { replace: true })
      })
    } else if (savedSession) {
      api.getSession(savedSession).then((response) => {
        setSessionExpiresAt(response.data.expires_at)
        if (isRoot) navigate('/review', { replace: true })
      }).catch((err) => {
        if (err.status === 404 || err.status === 410) {
          localStorage.removeItem(SESSION_ID_KEY)
          setSessionId(null)
        }
        if (isRoot) navigate('/review', { replace: true })
      })
    } else {
      if (isRoot) navigate('/review', { replace: true })
    }
  }, []) // Run once on mount

  const routeReviewId = getReviewIdFromPath(location.pathname)
  const activeReviewId = routeReviewId ?? reviewId

  const requestStartNewReview = (targetReviewId: string | null = activeReviewId) => {
    if (targetReviewId && metadata?.features.server_side_cancel !== true) {
      showToast('진행 중인 검토를 안전하게 중단할 수 없어 새 검토를 시작할 수 없습니다.', 'error')
      return
    }
    setReviewIdToDiscard(targetReviewId)
    setShowNewReviewConfirm(true)
  }

  const startNewReview = async () => {
    setIsStartingNewReview(true)
    try {
      if (reviewIdToDiscard) {
        const key = discardRequestKey.current ?? createClientId()
        discardRequestKey.current = key
        await api.deleteReview(reviewIdToDiscard, key)
      }
      discardRequestKey.current = null
      setReviewIdToDiscard(null)
      setShowNewReviewConfirm(false)
      clearLocalReview()
      navigate('/review', { replace: true })
    } catch (error: any) {
      if (error?.status === 404 || error?.status === 410) {
        discardRequestKey.current = null
        setReviewIdToDiscard(null)
        setShowNewReviewConfirm(false)
        clearLocalReview()
        navigate('/review', { replace: true })
      } else {
        showToast(getErrorMessage(error, '기존 검토를 정리하지 못했습니다. 다시 시도해 주세요.'), 'error')
      }
    } finally {
      setIsStartingNewReview(false)
    }
  }

  // Determine current "screen" for Header and Stepper based on location.pathname
  let screen: Screen = 'upload-and-type'
  const path = location.pathname
  if (path.includes('/progress')) screen = 'processing'
  else if (path.includes('/results/clause')) screen = 'clause-detail'
  else if (path.includes('/chatbot')) screen = 'chatbot'
  else if (path.includes('/results')) screen = 'results'
  else if (path.includes('/out-of-scope')) screen = 'out-of-scope'
  const navigationLocked = screen === 'processing'

  const nav = (s: Screen) => {
    switch (s) {
      case 'upload-and-type': return navigate('/review')
      case 'out-of-scope': return navigate('/out-of-scope')
      case 'processing': return navigate(reviewId ? `/review/${reviewId}/progress` : '/review')
      case 'results': return navigate(reviewId ? `/review/${reviewId}/results` : '/review')
      case 'clause-detail': return navigate(reviewId ? `/review/${reviewId}/results/clause` : '/review')
      case 'chatbot': return navigate(reviewId ? `/review/${reviewId}/chatbot` : '/review')
    }
  }

  return (
      <div className="flex min-h-screen flex-col bg-[#F6F8FA]">
        {/* ── App header ── */}
        <Header
          currentScreen={screen}
          onNavigate={nav}
          expiresAt={sessionExpiresAt}
          canStartNewReview={Boolean(sessionId || activeReviewId) && (
            !activeReviewId || metadata?.features.server_side_cancel === true
          )}
          onStartNewReview={() => requestStartNewReview()}
          isStartingNewReview={isStartingNewReview}
          navigationLocked={navigationLocked}
        />

        {/* ── Stepper ── */}
        <HorizontalStepper currentScreen={screen} onNavigate={nav} navigationLocked={navigationLocked} />

        {/* ── Body ── */}
        <main className="flex-1 px-4 py-7 sm:px-6 lg:px-8 lg:py-9">
          <div key={screen} className="mx-auto w-full max-w-[1080px] animate-page-enter">
            <Routes>
              <Route path="/" element={<Navigate to="/review" replace />} />
              <Route path="/review" element={
                <UploadAndTypeScreen
                  sessionId={sessionId}
                  setSessionId={setSessionId}
                  setReviewId={setReviewId}
                  onNext={(id) => navigate(`/review/${id}/progress`)}
                  onOutOfScope={() => nav('out-of-scope')}
                  setSessionExpiresAt={setSessionExpiresAt}
                />
              } />
              <Route path="/out-of-scope" element={
                <OutOfScopeScreen
                  sessionId={sessionId}
                  onBack={() => nav('upload-and-type')}
                  onContinue={(id) => {
                    setReviewId(id)
                    navigate(`/review/${id}/progress`)
                  }}
                  setSessionExpiresAt={setSessionExpiresAt}
                />
              } />
              <Route path="/review/:id/progress" element={
                <ProcessingRoute
                  fallbackReviewId={reviewId}
                  onDone={(id) => navigate(`/review/${id}/results`)}
                  onRetry={(id) => {
                    setReviewId(id)
                    localStorage.setItem(REVIEW_ID_KEY, id)
                    navigate(`/review/${id}/progress`, { replace: true })
                  }}
                  onStartNewReview={(id) => requestStartNewReview(id)}
                />
              } />
              <Route path="/review/:id/results" element={
                <ResultsRoute fallbackReviewId={reviewId} onClauseClick={(clause, id) => {
                    setSelectedClause(clause)
                    navigate(`/review/${id}/results/clause/${clause.id}`)
                  }} onChatbot={(id) => openChat(id)} onReviewInProgress={(id) => navigate(`/review/${id}/progress`, { replace: true })} />
              } />
              <Route path="/review/:id/results/clause/:clauseId" element={<ClauseRoute fallbackReviewId={reviewId} selectedClause={selectedClause} onBack={(id) => navigate(`/review/${id}/results`)} onChatbot={openChat} />} />
              <Route path="/review/:id/chatbot" element={<Navigate to="../results" replace />} />
            </Routes>
          </div>
          {chatTarget && <ChatbotScreen key={chatTarget.reviewId} reviewId={chatTarget.reviewId} focusClauseId={chatTarget.clause?.id} focusClauseName={chatTarget.clause?.article} focusClauseTitle={chatTarget.clause?.standardTitle} focusClauseStatus={chatTarget.clause?.status} focusClauseCategory={chatTarget.clause?.category} isOpen={isChatOpen} onClose={closeChat} onClearFocus={() => setChatTarget(target => target ? { reviewId: target.reviewId } : null)} onReviewUnavailable={() => {
            clearLocalReview()
            showToast('검토가 종료되었거나 보관 기간이 만료되었습니다. 새 검토를 시작해 주세요.', 'error')
            navigate('/review', { replace: true })
          }} />}
        </main>
        {showNewReviewConfirm && (
          <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4" role="dialog" aria-modal="true" aria-labelledby="new-review-title">
            <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-xl">
              <h2 id="new-review-title" className="text-lg font-bold text-slate-950">
                {screen === 'processing' ? '검토를 중단하고 새로 시작할까요?' : '새 검토를 시작할까요?'}
              </h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                {screen === 'processing'
                  ? '중단하면 계약서와 분석 내용이 삭제됩니다.'
                  : '현재 계약서와 검토 결과가 삭제됩니다.'}
              </p>
              <div className="mt-6 flex justify-end gap-2">
                <button type="button" onClick={() => { setShowNewReviewConfirm(false); setReviewIdToDiscard(null) }} disabled={isStartingNewReview} className="min-w-20 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50">
                  아니요
                </button>
                <button type="button" onClick={startNewReview} disabled={isStartingNewReview} className="min-w-20 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-700 transition-colors hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50">
                  {isStartingNewReview ? '처리 중' : '예'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <MetadataProvider>
        <MainApp />
      </MetadataProvider>
    </BrowserRouter>
  )
}
