import { useState, useEffect } from 'react'
import type { Screen } from './types'
import { SESSION_ID_KEY, REVIEW_ID_KEY } from './config'
import Header from './components/Header'
import Sidebar from './components/Sidebar'
import UploadAndTypeScreen from './screens/UploadAndTypeScreen'
import OutOfScopeScreen from './screens/OutOfScopeScreen'
import ProcessingScreen from './screens/ProcessingScreen'
import ResultsScreen from './screens/ResultsScreen'
import ClauseDetailScreen from './screens/ClauseDetailScreen'
import ChatbotScreen from './screens/ChatbotScreen'

const DEMO_NAV: { id: Screen; label: string; step: string }[] = [
  { id: 'upload-and-type', label: '1. 업로드 및 유형선택', step: '1~2단계' },
  { id: 'out-of-scope',    label: '3. 범위 외 안내', step: '2단계' },
  { id: 'processing',      label: '4. 검토 진행',    step: '3단계' },
  { id: 'results',         label: '5. 검토 결과',    step: '4단계' },
  { id: 'clause-detail',   label: '6. 조항 상세',    step: '4단계' },
  { id: 'chatbot',         label: '7. 챗봇/문구',    step: '4단계' },
]

export default function App() {
  const [screen, setScreen] = useState<Screen>('upload-and-type')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [reviewId, setReviewId] = useState<string | null>(null)

  // Recovery logic for session and review IDs
  useEffect(() => {
    const savedSession = localStorage.getItem(SESSION_ID_KEY)
    const savedReview = localStorage.getItem(REVIEW_ID_KEY)
    
    if (savedSession) setSessionId(savedSession)
    if (savedReview) setReviewId(savedReview)

    if (savedReview) {
      // 복구 라우팅
      import('./api/mockApi').then(({ mockApi }) => {
        mockApi.getResults(savedReview).then(res => {
          if (res.data.review.review_state === 'COMPLETED') {
            setScreen('results')
          } else {
            setScreen('processing')
          }
        }).catch(() => {
          // 404 or other errors mean session lost
          setScreen('upload-and-type')
        })
      })
    } else if (savedSession) {
      setScreen('upload-and-type')
    }
  }, [])

  const nav = (s: Screen) => setScreen(s)

  return (
    <div className="min-h-screen bg-[#F8FAFC] flex flex-col">

      {/* ── Demo switcher ── */}
      <div className="bg-[#1E293B] border-b border-white/10">
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

      {/* ── Body ── */}
      <div className="flex flex-1 max-w-[1440px] mx-auto w-full">
        <Sidebar currentScreen={screen} onNavigate={nav} />

        <main className="flex-1 min-w-0 px-5 py-7 lg:px-8 lg:py-10">
          <div key={screen} className="max-w-[900px] mx-auto animate-fade-up">
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
                onClauseClick={() => nav('clause-detail')}
                onChatbot={() => nav('chatbot')}
              />
            )}
            {screen === 'clause-detail' && (
              <ClauseDetailScreen
                onBack={() => nav('results')}
                onChatbot={() => nav('chatbot')}
              />
            )}
            {screen === 'chatbot' && (
              <ChatbotScreen onBack={() => nav('results')} />
            )}
          </div>
        </main>
      </div>
    </div>
  )
}
