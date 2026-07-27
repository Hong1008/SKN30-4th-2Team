import { useState, useEffect } from 'react'
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
import { MetadataProvider } from './contexts/MetadataContext'
import { api } from './api/api'

function ProcessingRoute({ fallbackReviewId, onDone }: { fallbackReviewId: string | null; onDone: (id: string) => void }) {
  const { id } = useParams()
  const reviewId = (id && id !== 'new' ? id : null) ?? fallbackReviewId
  return reviewId
    ? <ProcessingScreen reviewId={reviewId} onDone={() => onDone(reviewId)} />
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
  onChatbot: (reviewId: string) => void
}) {
  const { id, clauseId } = useParams()
  const reviewId = id ?? fallbackReviewId
  const [clause, setClause] = useState<ClauseResult | null>(selectedClause?.id === clauseId ? selectedClause : null)

  useEffect(() => {
    if (!reviewId || clause) return
    const controller = new AbortController()
    api.getResults(reviewId, controller.signal)
      .then((response) => {
        const rawClause = response.data.clause_results.find((item) => {
          const raw = item as unknown as { id?: string; user_clause_id?: string }
          return raw.id === clauseId || raw.user_clause_id === clauseId
        }) as unknown as {
          user_clause_id?: string
          user_clause?: string
          deviation?: { code?: ClauseResult['status'] }
          match?: { standard?: { category?: { code?: string; label?: string }; title?: string; text?: string; source?: string } }
          explanation?: string
          toxic_patterns?: ClauseResult['toxic_patterns']
        } | undefined
        if (!rawClause?.user_clause_id) return setClause(null)
        setClause({
          id: rawClause.user_clause_id,
          article: rawClause.user_clause?.split(' ')[0] || '조항',
          excerpt: rawClause.user_clause || '',
          status: rawClause.deviation?.code || 'NO_MATCH',
          category: rawClause.match?.standard?.category?.label || '기타',
          categoryCode: rawClause.match?.standard?.category?.code,
          summary: rawClause.explanation || '',
          toxic_patterns: rawClause.toxic_patterns,
          standardTitle: rawClause.match?.standard?.title,
          standardText: rawClause.match?.standard?.text,
          standardSource: rawClause.match?.standard?.source,
        })
      })
      .catch(() => setClause(null))
    return () => controller.abort()
  }, [reviewId, clauseId, clause])

  if (!reviewId) return <Navigate to="/review" replace />
  if (!clause) return <Navigate to={`/review/${reviewId}/results`} replace />
  return <ClauseDetailScreen clause={clause} reviewId={reviewId} onBack={() => onBack(reviewId)} onChatbot={() => onChatbot(reviewId)} />
}

function ChatRoute({ fallbackReviewId, onBack }: { fallbackReviewId: string | null; onBack: (reviewId: string) => void }) {
  const { id } = useParams()
  const reviewId = id ?? fallbackReviewId
  return reviewId ? <ChatbotScreen onBack={() => onBack(reviewId)} reviewId={reviewId} /> : <Navigate to="/review" replace />
}

function MainApp() {
  const navigate = useNavigate()
  const location = useLocation()

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [reviewId, setReviewId] = useState<string | null>(null)
  const [selectedClause, setSelectedClause] = useState<ClauseResult | null>(null)

  // Recovery logic for session and review IDs
  useEffect(() => {
    const savedSession = localStorage.getItem(SESSION_ID_KEY)
    const savedReview = localStorage.getItem(REVIEW_ID_KEY)
    
    if (savedSession) setSessionId(savedSession)
    if (savedReview) setReviewId(savedReview)

    // Only run routing on initial mount if not already deep linked
    const isRoot = location.pathname === '/' || location.pathname === ''

    if (savedReview) {
      api.pollReviewStatus(savedReview).then(res => {
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
      api.getSession(savedSession).then(() => {
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
    <MetadataProvider>
      <div className="min-h-screen bg-slate-50 flex flex-col">
        {/* ── App header ── */}
        <Header currentScreen={screen} onNavigate={nav} />

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
                />
              } />
              <Route path="/review/:id/progress" element={
                <ProcessingRoute fallbackReviewId={reviewId} onDone={(id) => navigate(`/review/${id}/results`)} />
              } />
              <Route path="/review/:id/results" element={
                <ResultsRoute fallbackReviewId={reviewId} onClauseClick={(clause, id) => {
                    setSelectedClause(clause)
                    navigate(`/review/${id}/results/clause/${clause.id}`)
                  }} onChatbot={(id) => navigate(`/review/${id}/chatbot`)} />
              } />
              <Route path="/review/:id/results/clause/:clauseId" element={<ClauseRoute fallbackReviewId={reviewId} selectedClause={selectedClause} onBack={(id) => navigate(`/review/${id}/results`)} onChatbot={(id) => navigate(`/review/${id}/chatbot`)} />} />
              <Route path="/review/:id/chatbot" element={
                <ChatRoute fallbackReviewId={reviewId} onBack={(id) => navigate(`/review/${id}/results`)} />
              } />
            </Routes>
          </div>
        </main>
      </div>
    </MetadataProvider>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <MainApp />
    </BrowserRouter>
  )
}
