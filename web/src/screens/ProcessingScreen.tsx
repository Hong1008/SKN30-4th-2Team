import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Check, ChevronRight, RefreshCw } from 'lucide-react'
import { api } from '../api/api'
import type { ReviewData, ReviewProgress, ReviewSseEvent } from '../types'
import { useToast } from '../contexts/ToastContext'
import { useMetadata } from '../contexts/MetadataContext'
import { getMetadataLabel } from '../utils/metadata'
import { isTerminalReviewState, toReviewProgress } from '../utils/reviewProgress'
import { getNextAction } from '../utils/apiErrors'

interface Props {
  reviewId: string | null
  onDone: () => void
  onRetry: (reviewId: string) => void
  onStartNewReview: () => void
}

type Mode = 'running' | 'error' | 'done'

export default function ProcessingScreen({ reviewId, onDone, onRetry, onStartNewReview }: Props) {
  const { metadata } = useMetadata()
  const { showToast } = useToast()
  const stages = useMemo(
    () => (metadata?.progress_stages ?? []).map((code) => ({
      code,
      label: getMetadataLabel(metadata?.progress_stage_details, code, '진행 단계'),
    })),
    [metadata?.progress_stage_details, metadata?.progress_stages],
  )
  const [activeStep, setActiveStep] = useState(0)
  const [progress, setProgress] = useState<ReviewProgress | null>(null)
  const [mode, setMode] = useState<Mode>('running')
  const [errorMessage, setErrorMessage] = useState('')
  const [retryable, setRetryable] = useState(false)
  const [reviewState, setReviewState] = useState<'QUEUED' | 'REVIEWING'>('QUEUED')
  const retryRequestKey = useRef<string | null>(null)

  useEffect(() => {
    if (mode !== 'running' || !reviewId) return

    let subscribed = true
    let source: EventSource | null = null
    let pollingTimer: ReturnType<typeof setTimeout> | null = null
    let watchdogTimer: ReturnType<typeof setTimeout> | null = null
    let pollingStarted = false
    let lastSequence = -1

    const update = (reviewState: string, nextProgress?: ReviewProgress | null, reviewError?: ReviewData['error']) => {
      if (reviewState === 'QUEUED' || reviewState === 'REVIEWING') {
        setReviewState(reviewState)
      }
      if (nextProgress) {
        if (nextProgress.sequence >= lastSequence) {
          lastSequence = nextProgress.sequence
          setProgress(nextProgress)
          const index = stages.findIndex((stage) => stage.code === nextProgress.stage)
          if (index >= 0) setActiveStep(index)
        }
      }
      if (reviewState === 'COMPLETED') {
        if (watchdogTimer) {
          clearTimeout(watchdogTimer)
          watchdogTimer = null
        }
        stopPolling()
        setActiveStep(Math.max(stages.length - 1, 0))
        setMode('done')
      }
      if (['FAILED', 'CANCELLED', 'EXPIRED'].includes(reviewState)) {
        if (watchdogTimer) {
          clearTimeout(watchdogTimer)
          watchdogTimer = null
        }
        stopPolling()
        setMode('error')
        const fallbackByCode: Record<string, string> = {
          CORPUS_UNAVAILABLE: '표준 비교 기준 자료를 현재 사용할 수 없습니다.',
          INVALID_CONFIG: '검토 서비스 설정을 확인할 수 없습니다. 관리자에게 문의해 주세요.',
          PIPELINE_ERROR: '검토 처리 시간이 초과되었거나 처리 중 오류가 발생했습니다.',
          MCP_TIMEOUT: '검토 서비스 응답이 지연되어 작업이 중단되었습니다.',
          SESSION_EXPIRED: '검토 세션이 만료되었습니다. 새 검토를 시작해 주세요.',
        }
        setErrorMessage(
          reviewError?.message
          || fallbackByCode[reviewError?.code || '']
          || '검토가 중단되었거나 만료되었습니다.',
        )
        setRetryable(
          reviewError?.retryable === true
          || getNextAction(reviewError) === 'RETRY_REVIEW'
        )
      }
    }

    const stopPolling = () => {
      pollingStarted = false
      if (pollingTimer) {
        clearTimeout(pollingTimer)
        pollingTimer = null
      }
    }

    const startPolling = () => {
      if (!subscribed || pollingStarted) return
      pollingStarted = true
      const poll = async () => {
        try {
          const response = await api.pollReviewStatus(reviewId)
          if (!subscribed) return
          update(response.data.review_state, response.data.progress, response.data.error)
          if (!isTerminalReviewState(response.data.review_state)) {
            pollingTimer = setTimeout(poll, 2000)
          } else {
            stopPolling()
          }
        } catch (error: any) {
          if (!subscribed) return
          if (error?.status === 404 || error?.status === 410) {
            showToast('검토 정보를 찾을 수 없거나 만료되었습니다. 처음부터 다시 시작해 주세요.', 'error')
            setMode('error')
            setErrorMessage('검토 정보를 찾을 수 없거나 만료되었습니다.')
            setRetryable(false)
            return
          }
          setMode('error')
          setErrorMessage(error?.message || '검토 상태를 불러오지 못했습니다.')
          setRetryable(
            error?.retryable === true
            || getNextAction(error) === 'RETRY_REVIEW'
          )
        }
      }
      void poll()
    }

    const scheduleWatchdog = () => {
      if (watchdogTimer) clearTimeout(watchdogTimer)
      watchdogTimer = setTimeout(startPolling, 5000)
    }

    const syncCurrentStatus = async () => {
      try {
        const response = await api.pollReviewStatus(reviewId)
        if (!subscribed) return
        update(response.data.review_state, response.data.progress, response.data.error)
      } catch {
        // SSE 연결이 실패하면 onerror에서 polling으로 복구한다.
      }
    }

    void syncCurrentStatus()

    try {
      source = new EventSource(api.reviewEventsUrl(reviewId), { withCredentials: true })
      const onEvent = (event: MessageEvent<string>) => {
        try {
          const data = JSON.parse(event.data) as ReviewSseEvent
          const sequence = Number.isFinite(data.sequence)
            ? data.sequence
            : Number(event.lastEventId)
          if (!Number.isFinite(sequence) || sequence < lastSequence) return

          stopPolling()
          update(
            data.review_state,
            toReviewProgress({ ...data, sequence }),
            data.error,
          )
          if (!isTerminalReviewState(data.review_state)) scheduleWatchdog()
        } catch {
          source?.close()
          startPolling()
        }
      }
      source.addEventListener('progress', onEvent)
      source.addEventListener('completed', onEvent)
      source.addEventListener('failed', onEvent)
      source.onopen = () => {
        stopPolling()
        scheduleWatchdog()
      }
      scheduleWatchdog()
      source.onerror = () => {
        // EventSource가 Last-Event-ID를 유지한 채 자동 재연결하도록 연결은 닫지 않는다.
        // 재연결 전까지는 polling으로 현재 상태를 동기화한다.
        startPolling()
      }
    } catch {
      startPolling()
    }

    return () => {
      subscribed = false
      source?.close()
      if (pollingTimer) clearTimeout(pollingTimer)
      if (watchdogTimer) clearTimeout(watchdogTimer)
    }
  }, [mode, reviewId, showToast, stages])

  const retry = async () => {
    if (!reviewId) return
    try {
      const idempotencyKey = retryRequestKey.current ?? crypto.randomUUID()
      retryRequestKey.current = idempotencyKey
      const response = await api.retryReview(reviewId, idempotencyKey)
      retryRequestKey.current = null
      setActiveStep(0)
      setProgress(null)
      onRetry(response.data.review_id)
    } catch (error: any) {
      setErrorMessage(error?.message || '재시도 요청에 실패했습니다.')
      setRetryable(
        error?.retryable === true
        || getNextAction(error) === 'RETRY_REVIEW'
      )
    }
  }

  if (!reviewId) return <p className="text-sm text-rose-600">검토 ID를 찾을 수 없습니다.</p>

  return (
    <div className="mx-auto w-full max-w-[760px] space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-950">
          {reviewState === 'QUEUED' ? '검토 요청이 접수되었습니다' : '계약서를 검토하고 있습니다'}
        </h1>
        <p className="mt-2 text-sm text-slate-500">
          {reviewState === 'QUEUED'
            ? '검토를 시작할 준비를 하고 있습니다.'
            : '진행 상태는 실시간으로 갱신됩니다.'}
        </p>
      </div>
      {mode !== 'error' && <div className="rounded-2xl border border-slate-200 bg-white p-5">
        <div className="mb-3 flex justify-between text-sm"><span>검토 진행 상태</span><span className="text-blue-600">{progress?.percent ?? 0}%</span></div>
        <div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-blue-600 transition-all" style={{ width: `${progress?.percent ?? 0}%` }} /></div>
        {progress?.message && <p className="mt-3 text-xs text-slate-600">{progress.message}</p>}
      </div>}
      <section className="divide-y rounded-2xl border border-slate-200 bg-white">
        {stages.map((stage, index) => <div key={stage.code} className="flex items-center gap-3 px-5 py-4">
          {mode === 'done' || index < activeStep ? <Check className="size-5 text-blue-600" /> : index === activeStep && mode === 'running' ? <RefreshCw className="size-5 animate-spin text-blue-600" /> : <span className="size-5 rounded-full border border-slate-300" />}
          <span className="text-sm text-slate-700">{stage.label}</span>
        </div>)}
      </section>
      {mode === 'error' && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700"><AlertCircle className="mr-2 inline size-4" />{errorMessage}</div>}
      {mode === 'error' && retryable && <button onClick={retry} className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white"><RefreshCw className="size-4" />다시 시도</button>}
      {mode === 'error' && !retryable && (
        <button onClick={onStartNewReview} className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white">
          새 검토 시작
        </button>
      )}
      {mode === 'done' && <button onClick={onDone} className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white">검토 결과 확인 <ChevronRight className="size-4" /></button>}
    </div>
  )
}
