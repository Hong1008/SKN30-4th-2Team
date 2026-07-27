import { useState, useEffect, useRef } from 'react'
import { BrowserRouter, Routes, Route, useNavigate, useLocation, useParams, useSearchParams, Navigate } from 'react-router-dom'
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

function ProcessingRoute({ fallbackReviewId, onDone, onRetry, onStartNewReview }: {
  fallbackReviewId: string | null
  onDone: (id: string) => void
  onRetry: (id: string) => void
  onStartNewReview: () => void
}) {
  const { id } = useParams()
  const reviewId = (id && id !== 'new' ? id : null) ?? fallbackReviewId
  return reviewId
    ? <ProcessingScreen reviewId={reviewId} onDone={() => onDone(reviewId)} onRetry={onRetry} onStartNewReview={onStartNewReview} />
    : <Navigate to="/review" replace />
}

function ResultsRoute({ fallbackReviewId, onClauseClick, onChatbot }: {
  fallbackReviewId: string | null
  onClauseClick: (clause: ClauseResult, reviewId: string) => void
  onChatbot: (reviewId: string) => void
}) {
  const { id } = useParams()
  const reviewId = id ?? fallbackReviewId
  return reviewId ? <ResultsScreen reviewId={reviewId} onClauseClick={(clause) => onClauseClick(clause, reviewId)} onChatbot={() => onChatbot(reviewId)} /> : <Navigate to="/review" replace />
}

function ClauseRoute({ fallbackReviewId, selectedClause, onBack, onChatbot }: {
  fallbackReviewId: string | null
  selectedClause: ClauseResult | null
  onBack: (reviewId: string) => void
  onChatbot: (reviewId: string, clauseId: string) => void
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
  return <ClauseDetailScreen clause={clause} reviewId={reviewId} onBack={() => onBack(reviewId)} onChatbot={() => onChatbot(reviewId, clause.id)} />
}

function ChatRoute({ fallbackReviewId, onBack, onStartNewReview }: {
  fallbackReviewId: string | null
  onBack: (reviewId: string) => void
  onStartNewReview: () => void
}) {
  const { metadata } = useMetadata()
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const reviewId = id ?? fallbackReviewId
  if (!reviewId) return <Navigate to="/review" replace />
  if (!metadata?.features.chat) return <Navigate to={`/review/${reviewId}/results`} replace />
  return (
    <ChatbotScreen
      onBack={() => onBack(reviewId)}
      reviewId={reviewId}
      focusClauseId={searchParams.get('focusClauseId') || undefined}
      onStartNewReview={onStartNewReview}
    />
  )
}

function MainApp() {
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
  const discardRequestKey = useRef<string | null>(null)

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
          localStorage.removeItem(SESSION_ID_KEY)
          localStorage.removeItem(REVIEW_ID_KEY)
          setSessionId(null)
          setReviewId(null)
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

  const startNewReview = async () => {
    setShowNewReviewConfirm(false)
    setIsStartingNewReview(true)
    try {
      if (reviewId && metadata?.features.server_side_cancel) {
        const key = discardRequestKey.current ?? crypto.randomUUID()
        discardRequestKey.current = key
        await api.deleteReview(reviewId, key)
      }
      discardRequestKey.current = null
      setSessionId(null)
      setReviewId(null)
      setSelectedClause(null)
      setSessionExpiresAt(null)
      localStorage.removeItem(SESSION_ID_KEY)
      localStorage.removeItem(REVIEW_ID_KEY)
      navigate('/review', { replace: true })
    } catch (error: any) {
      if (error?.status === 404 || error?.status === 410) {
        discardRequestKey.current = null
        setSessionId(null)
        setReviewId(null)
        setSelectedClause(null)
        setSessionExpiresAt(null)
        localStorage.removeItem(SESSION_ID_KEY)
        localStorage.removeItem(REVIEW_ID_KEY)
        navigate('/review', { replace: true })
      } else {
        showToast(error?.message || '기존 검토를 정리하지 못했습니다. 다시 시도해 주세요.', 'error')
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
      <div className="min-h-screen bg-slate-50 flex flex-col">
        {/* ── App header ── */}
        <Header
          currentScreen={screen}
          onNavigate={nav}
          expiresAt={sessionExpiresAt}
          canStartNewReview={Boolean(sessionId || reviewId) && (
            !reviewId || metadata?.features.server_side_cancel === true
          )}
          onStartNewReview={() => setShowNewReviewConfirm(true)}
          isStartingNewReview={isStartingNewReview}
        />

        {/* ── Stepper ── */}
        <HorizontalStepper currentScreen={screen} onNavigate={nav} />

        {/* ── Body ── */}
        <main className="px-4 py-8 sm:px-6 lg:px-8 lg:py-10 flex-1">
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
                  onStartNewReview={() => setShowNewReviewConfirm(true)}
                />
              } />
              <Route path="/review/:id/results" element={
                <ResultsRoute fallbackReviewId={reviewId} onClauseClick={(clause, id) => {
                    setSelectedClause(clause)
                    navigate(`/review/${id}/results/clause/${clause.id}`)
                  }} onChatbot={(id) => navigate(`/review/${id}/chatbot`)} />
              } />
              <Route path="/review/:id/results/clause/:clauseId" element={<ClauseRoute fallbackReviewId={reviewId} selectedClause={selectedClause} onBack={(id) => navigate(`/review/${id}/results`)} onChatbot={(id, clauseId) => navigate(`/review/${id}/chatbot?focusClauseId=${encodeURIComponent(clauseId)}`)} />} />
              <Route path="/review/:id/chatbot" element={
                <ChatRoute fallbackReviewId={reviewId} onBack={(id) => navigate(`/review/${id}/results`)} onStartNewReview={() => setShowNewReviewConfirm(true)} />
              } />
            </Routes>
          </div>
        </main>
        {showNewReviewConfirm && (
          <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4" role="dialog" aria-modal="true" aria-labelledby="new-review-title">
            <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl">
              <h2 id="new-review-title" className="text-lg font-bold text-slate-950">새 검토를 시작할까요?</h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                현재 검토 결과와 서버에 임시 저장된 파일을 폐기한 뒤 새 계약서를 업로드합니다.
              </p>
              <div className="mt-6 flex justify-end gap-2">
                <button type="button" onClick={() => setShowNewReviewConfirm(false)} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700">
                  계속 보기
                </button>
                <button type="button" onClick={startNewReview} className="rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white">
                  폐기하고 새 검토
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
