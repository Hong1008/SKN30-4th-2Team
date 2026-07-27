import { useState, useEffect } from 'react'
import { Check, AlertCircle, RefreshCw, ChevronRight } from 'lucide-react'
import { mockApi } from '../api/mockApi'
import { ReviewProgress } from '../types'

interface Props {
  reviewId: string | null;
  onDone: () => void
}

const STEPS = [
  { id: 0, label: '검토 준비 중', stage: 'PREPARE' },
  { id: 1, label: '조항 탐색 및 분류', stage: 'BATCH_SEARCH' },
  { id: 2, label: '검토 진행 중', stage: 'CLAUSE_REVIEW' },
  { id: 3, label: '누락 조항 검출', stage: 'MISSING_DETECTION' },
  { id: 4, label: '결과 정리 중', stage: 'RESULT_ASSEMBLY' },
]

type Mode = 'running' | 'error' | 'done'

const USE_REAL_API = false // TODO: 실제 API 연동 시 true로 변경

export default function ProcessingScreen({ reviewId, onDone }: Props) {
  const [activeStep, setActiveStep] = useState(0)
  const [progress, setProgress] = useState<ReviewProgress | null>(null)
  const [mode, setMode] = useState<Mode>('running')
  const [errorMsg, setErrorMsg] = useState('')
  const [isRetryable, setIsRetryable] = useState(false)

  useEffect(() => {
    if (mode !== 'running' || !reviewId) return

    let isSubscribed = true
    let eventSource: EventSource | null = null
    let lastEventId: string | null = null
    let currentPercent = progress?.percent || 0 // Mock용

    const handleUpdate = (review_state: string, newProgress: ReviewProgress) => {
      setProgress(newProgress)
      currentPercent = newProgress.percent

      const stepIndex = STEPS.findIndex(s => s.stage === newProgress.stage)
      if (stepIndex !== -1) setActiveStep(stepIndex)

      if (review_state === 'COMPLETED') {
        setActiveStep(STEPS.length - 1)
        setMode('done')
      } else if (review_state === 'FAILED') {
        setMode('error')
        setErrorMsg('서버에서 검토 중 오류가 발생했습니다.')
        setIsRetryable(newProgress.error?.retryable === true || (newProgress as any).retryable === true)
      }
    }

    const connectSSE = () => {
      if (!isSubscribed) return

      if (USE_REAL_API) {
        // [Real API] SSE 연결 및 Fallback 처리
        const url = new URL(`http://localhost:8000/api/v1/reviews/${reviewId}/events`) // TODO: config의 API_BASE_URL 사용
        if (lastEventId) {
          url.searchParams.append('last_event_id', lastEventId)
        }

        eventSource = new EventSource(url.toString(), { withCredentials: true })

        eventSource.onmessage = (event) => {
          if (!isSubscribed) return
          const data = JSON.parse(event.data)
          // SSE 응답 최상위에 있는 sequence나 event.lastEventId 갱신
          lastEventId = event.lastEventId || data.sequence?.toString() || lastEventId
          handleUpdate(data.review_state, data) // data 자체가 progress 정보를 담고 있다고 가정
        }

        eventSource.onerror = async () => {
          if (!isSubscribed) return
          eventSource?.close()
          console.warn('[SSE] Connection lost. Attempting state sync & reconnect...')

          try {
            // 1. 상태 동기화 (Polling Fallback)
            const syncRes = await fetch(`http://localhost:8000/api/v1/reviews/${reviewId}`, { credentials: 'include' })
            if (!syncRes.ok) throw new Error('Sync failed')
            const syncData = await syncRes.json()
            
            // 2. 동기화된 상태 반영
            handleUpdate(syncData.review_state, syncData.progress || syncData)
            
            // 3. 아직 진행 중이라면 다시 SSE 연결 (재귀)
            if (syncData.review_state !== 'COMPLETED' && syncData.review_state !== 'FAILED') {
              setTimeout(connectSSE, 2000)
            }
          } catch (e: any) {
            const status = e?.response?.status || e?.status
            if (status === 404 || status === 410) {
              alert('유효하지 않거나 만료된 세션입니다. 처음부터 다시 시작합니다.')
              localStorage.clear()
              window.location.reload()
            } else {
              setMode('error')
              setErrorMsg('서버 연결이 끊어졌으며 복구에 실패했습니다.')
              setIsRetryable(true)
            }
          }
        }
      } else {
        // [Mock API] 기존의 Polling 시뮬레이션
        const mockPoll = async () => {
          try {
            const res = await mockApi.pollReviewStatus(reviewId, currentPercent)
            if (!isSubscribed) return
            handleUpdate(res.data.review_state, res.data.progress)
            if (res.data.review_state !== 'COMPLETED' && res.data.review_state !== 'FAILED') {
              setTimeout(mockPoll, 1500)
            }
          } catch (err: any) {
            if (!isSubscribed) return
            const status = err?.response?.status || err?.status
            if (status === 404 || status === 410) {
              alert('유효하지 않거나 만료된 세션입니다. 처음부터 다시 시작합니다.')
              localStorage.clear()
              window.location.reload()
              return
            }
            setMode('error')
            setErrorMsg('통신 중 오류가 발생했습니다.')
            setIsRetryable(true) // Mock에서는 기본적으로 재시도 허용
          }
        }
        mockPoll()
      }
    }

    connectSSE()

    return () => {
      isSubscribed = false
      eventSource?.close()
    }
  }, [mode, reviewId])

  const triggerError = () => {
    setMode('error')
    setErrorMsg('오류 상태 미리보기용 테스트 오류입니다.')
    setIsRetryable(true)
  }

  const handleRetry = async () => {
    if (!reviewId) return
    
    // 멱등성 키 생성 (Idempotency-Key)
    const idempotencyKey = crypto.randomUUID()
    console.log(`[Processing] Retrying review with Idempotency-Key: ${idempotencyKey}`)
    
    try {
      await mockApi.retryReview(reviewId, idempotencyKey)
      setActiveStep(0)
      setProgress(null)
      setMode('running')
      setIsRetryable(false)
    } catch (err: any) {
      const status = err?.response?.status || err?.status
      if (status === 409) {
        // [4] 409 IDEMPOTENCY_KEY_REUSED
        console.warn('이미 재시도 요청이 진행 중입니다.')
        setActiveStep(0)
        setProgress(null)
        setMode('running')
        setIsRetryable(false)
      } else if (status === 404 || status === 410) {
        alert('유효하지 않거나 만료된 세션입니다. 처음부터 다시 시작합니다.')
        localStorage.clear()
        window.location.reload()
      } else {
        setErrorMsg('재시도 요청에 실패했습니다.')
      }
    }
  }

  return (
    <div className="space-y-8 animate-fade-up max-w-2xl">
      {/* Title */}
      <div>
        <h1 className="text-[22px] font-semibold text-[#1E293B] tracking-tight mb-2">
          {mode === 'error' ? '검토 중 오류가 발생했습니다' : '계약서를 검토하고 있습니다'}
        </h1>
        <p className="text-sm text-[#475569]">
          {mode === 'error'
            ? '진행하던 단계에서 처리가 중단되었습니다. 다시 시도해 주세요.'
            : '표준계약서와 조항을 비교하고 있습니다. 잠시 기다려 주세요.'}
        </p>
      </div>

      {/* Progress bar */}
      {mode !== 'error' && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold text-[#1E293B]">검토 진행 상태</p>
            <p className="text-xs font-medium text-[#6366F1]">
              {mode === 'done' ? '완료됨' : '처리 중'}
            </p>
          </div>
          <div className="h-2 bg-[#E2E8F0] rounded-full overflow-hidden">
            <div
              className="h-full bg-[#6366F1] rounded-full transition-all duration-700"
              style={{ width: `${progress?.percent || 0}%` }}
            />
          </div>
          {mode === 'running' && progress && (
            <p className="text-xs text-[#475569] mt-3">
              현재 처리 중:{' '}
              <span className="font-medium text-[#1E293B]">{progress.message}</span>
            </p>
          )}
        </div>
      )}

      {/* Step list */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl divide-y divide-[#F1F5F9]">
        {STEPS.map((step, i) => {
          const done = i < activeStep || mode === 'done'
          const current = i === activeStep && mode === 'running'
          const error = mode === 'error' && i === activeStep
          const ahead = i > activeStep && mode !== 'done'

          return (
            <div key={step.id} className={`flex items-center gap-4 px-5 py-4 ${current ? 'bg-[#EEF2FF]/40' : ''}`}>
              {/* Status icon */}
              <div className="w-7 h-7 shrink-0 flex items-center justify-center">
                {done && !error && (
                  <div className="w-7 h-7 rounded-full bg-[#6366F1] flex items-center justify-center">
                    <Check className="w-3.5 h-3.5 text-white" strokeWidth={2.5} />
                  </div>
                )}
                {current && (
                  <div className="w-7 h-7 rounded-full border-2 border-[#6366F1] border-t-transparent animate-spin-slow" />
                )}
                {error && (
                  <div className="w-7 h-7 rounded-full bg-rose-100 flex items-center justify-center">
                    <AlertCircle className="w-4 h-4 text-rose-500" />
                  </div>
                )}
                {ahead && (
                  <div className="w-7 h-7 rounded-full border-2 border-[#E2E8F0]" />
                )}
              </div>

              <div className="flex-1 min-w-0">
                <p className={`text-sm font-medium ${done ? 'text-[#1E293B]' : current ? 'text-[#1E293B]' : error ? 'text-rose-600' : 'text-[#64748B]'
                  }`}>
                  {step.label}
                </p>
                {error && (
                  <p className="text-xs text-rose-500 mt-0.5">조항 비교 중 서버 응답을 받지 못했습니다</p>
                )}
              </div>

              {done && (
                <span className="text-[11px] text-[#475569] shrink-0">완료</span>
              )}
              {current && (
                <span className="text-[11px] text-[#6366F1] font-medium shrink-0 animate-pulse-dot">진행 중</span>
              )}
            </div>
          )
        })}
      </div>

      {/* Error detail */}
      {mode === 'error' && (
        <div className="bg-rose-50 border border-rose-200 rounded-xl p-5">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-4 h-4 text-rose-500 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-rose-700 mb-1">진행 중 오류 발생</p>
              <p className="text-xs text-rose-600 leading-relaxed">
                {errorMsg}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-3 pt-2">
        {mode === 'error' && isRetryable && (
          <button
            onClick={handleRetry}
            className="flex items-center gap-2 px-5 py-3 bg-[#6366F1] text-white rounded-xl text-sm font-medium hover:bg-[#4F46E5] transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            다시 시도
          </button>
        )}
        {mode === 'done' && (
          <button
            onClick={onDone}
            className="flex items-center gap-2 px-6 py-3 bg-[#6366F1] text-white rounded-xl text-sm font-medium hover:bg-[#4F46E5] transition-colors"
          >
            검토 결과 확인하기
            <ChevronRight className="w-4 h-4" />
          </button>
        )}
        {mode === 'running' && (
          <button
            onClick={triggerError}
            className="text-xs text-[#64748B] hover:text-[#475569] transition-colors"
          >
            오류 상태 미리보기 →
          </button>
        )}
      </div>
    </div>
  )
}
