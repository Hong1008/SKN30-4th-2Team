import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, useNavigate, useLocation, Navigate } from 'react-router-dom'
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
      api.getResults(savedReview).then(res => {
        if (res.data.review.review_state === 'COMPLETED') {
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
      case 'processing': return navigate(`/review/${reviewId || 'new'}/progress`)
      case 'results': return navigate(`/review/${reviewId || 'new'}/results`)
      case 'clause-detail': return navigate(`/review/${reviewId || 'new'}/results/clause`)
      case 'chatbot': return navigate(`/review/${reviewId || 'new'}/chatbot`)
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
                  onNext={() => nav('processing')}
                  onOutOfScope={() => nav('out-of-scope')}
                />
              } />
              <Route path="/out-of-scope" element={
                <OutOfScopeScreen
                  onBack={() => nav('upload-and-type')}
                  onContinue={() => nav('processing')}
                />
              } />
              <Route path="/review/:id/progress" element={
                <ProcessingScreen
                  reviewId={reviewId}
                  onDone={() => nav('results')} 
                />
              } />
              <Route path="/review/:id/results" element={
                <ResultsScreen
                  reviewId={reviewId}
                  onClauseClick={(clause) => {
                    setSelectedClause(clause)
                    nav('clause-detail')
                  }}
                  onChatbot={() => nav('chatbot')}
                />
              } />
              <Route path="/review/:id/results/clause" element={
                selectedClause ? (
                  <ClauseDetailScreen
                    clause={selectedClause}
                    reviewId={reviewId}
                    onBack={() => nav('results')}
                    onChatbot={() => nav('chatbot')}
                  />
                ) : (
                  <Navigate to={`/review/${reviewId || 'new'}/results`} replace />
                )
              } />
              <Route path="/review/:id/chatbot" element={
                <ChatbotScreen onBack={() => nav('results')} reviewId={reviewId!} />
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
