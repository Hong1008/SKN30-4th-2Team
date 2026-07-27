import { useState, useEffect } from 'react'
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

const DEMO_NAV: { id: Screen; label: string; step: string }[] = [
  { id: 'upload-and-type', label: '1. 업로드 및 유형선택', step: '1단계' },
  { id: 'out-of-scope',    label: '2. 범위 외 안내', step: '1단계' },
  { id: 'processing',      label: '3. 검토 진행',    step: '2단계' },
  { id: 'results',         label: '4. 검토 결과',    step: '3단계' },
  { id: 'clause-detail',   label: '5. 조항 상세',    step: '3단계' },
  { id: 'chatbot',         label: '6. 챗봇/문구',    step: '3단계' },
]

export default function App() {
  const [screen, setScreen] = useState<Screen>('upload-and-type')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [reviewId, setReviewId] = useState<string | null>(null)
  const [selectedClause, setSelectedClause] = useState<ClauseResult | null>(null)

  // Recovery logic for session and review IDs
  useEffect(() => {
    const savedSession = localStorage.getItem(SESSION_ID_KEY)
    const savedReview = localStorage.getItem(REVIEW_ID_KEY)
    
    if (savedSession) setSessionId(savedSession)
    if (savedReview) setReviewId(savedReview)

    if (savedReview) {
      // 복구 라우팅
      api.getResults(savedReview).then(res => {
        if (res.data.review.review_state === 'COMPLETED') {
          setScreen('results')
        } else {
          setScreen('processing')
        }
      }).catch((err) => {
        // 404 (Not Found) or 410 (Gone) or other errors mean session lost
        if (err.status === 404 || err.status === 410) {
          localStorage.removeItem(SESSION_ID_KEY)
          localStorage.removeItem(REVIEW_ID_KEY)
          setSessionId(null)
          setReviewId(null)
        }
        setScreen('upload-and-type')
      })
    } else if (savedSession) {
      api.getSession(savedSession).then(() => {
        setScreen('upload-and-type')
      }).catch((err) => {
        if (err.status === 404 || err.status === 410) {
          localStorage.removeItem(SESSION_ID_KEY)
          setSessionId(null)
        }
        setScreen('upload-and-type')
      })
    }
  }, [])

  const nav = (s: Screen) => setScreen(s)

  return (
    <MetadataProvider>
      <div className="min-h-screen bg-slate-50 flex flex-col">

        {/* ── Demo switcher ── */}
        <div className="bg-[#1E293B] border-b border-white/10 hidden">
          <div className="max-w-[1440px] mx-auto px-4 h-10 flex items-center gap-1 overflow-x-auto">
            <span className="text-[10px] text-white/40 font-medium pr-2 shrink-0 hidden sm:block">화면 전환</span>
            {DEMO_NAV.map(s => (
              <button
                key={s.id}
                onClick={() => nav(s.id)}
                className={`px-3 py-1 rounded text-[11px] font-medium whitespace-nowrap transition-colors shrink-0 ${
                  screen === s.id
                    ? 'bg-white/20 text-white'
                    : 'text-white/50 hover:text-white/80 hover:bg-white/10'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {/* ── App header ── */}
        <Header currentScreen={screen} onNavigate={nav} />

        {/* ── Stepper ── */}
        <HorizontalStepper currentScreen={screen} onNavigate={nav} />

        {/* ── Body ── */}
        <main className="px-4 py-8 sm:px-6 lg:px-8 lg:py-10 flex-1">
          <div key={screen} className="mx-auto w-full max-w-[1080px] animate-page-enter">
              {screen === 'upload-and-type' && (
                <UploadAndTypeScreen
                  sessionId={sessionId}
                  setSessionId={setSessionId}
                  setReviewId={setReviewId}
                  onNext={() => nav('processing')}
                  onOutOfScope={() => nav('out-of-scope')}
                />
              )}
              {screen === 'out-of-scope' && (
                <OutOfScopeScreen
                  onBack={() => nav('upload-and-type')}
                  onContinue={() => nav('processing')}
                />
              )}
              {screen === 'processing' && (
                <ProcessingScreen
                  reviewId={reviewId}
                  onDone={() => nav('results')} 
                />
              )}
              {screen === 'results' && (
                <ResultsScreen
                  reviewId={reviewId}
                  onClauseClick={(clause) => {
                    setSelectedClause(clause)
                    nav('clause-detail')
                  }}
                  onChatbot={() => nav('chatbot')}
                />
              )}
              {screen === 'clause-detail' && (
                <ClauseDetailScreen
                  clause={selectedClause!}
                  reviewId={reviewId}
                  onBack={() => nav('results')}
                  onChatbot={() => nav('chatbot')}
                />
              )}
              {screen === 'chatbot' && <ChatbotScreen onBack={() => nav('results')} reviewId={reviewId!} />}
            </div>
          </main>
      </div>
    </MetadataProvider>
  )
}
