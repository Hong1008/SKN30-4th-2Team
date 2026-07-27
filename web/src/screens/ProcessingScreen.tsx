import { useEffect, useState } from 'react'
import { AlertCircle, Check, ChevronRight, RefreshCw } from 'lucide-react'
import { api } from '../api/api'
import type { ReviewData, ReviewProgress } from '../types'
import { useToast } from '../contexts/ToastContext'
import { useMetadata } from '../contexts/MetadataContext'

interface Props {
  reviewId: string | null
  onDone: () => void
}

type Mode = 'running' | 'error' | 'done'

export default function ProcessingScreen({ reviewId, onDone }: Props) {
  const { metadata } = useMetadata()
  const { showToast } = useToast()
  const stages = (metadata?.progress_stages ?? []).map((code) => ({ code, label: code }))
  const [activeStep, setActiveStep] = useState(0)
  const [progress, setProgress] = useState<ReviewProgress | null>(null)
  const [mode, setMode] = useState<Mode>('running')
  const [errorMessage, setErrorMessage] = useState('')
  const [retryable, setRetryable] = useState(false)

  useEffect(() => {
    if (mode !== 'running' || !reviewId) return

    let subscribed = true
    let source: EventSource | null = null
    let pollingTimer: ReturnType<typeof setTimeout> | null = null
    let pollingStarted = false
    let lastSequence = -1

    const update = (reviewState: string, nextProgress?: ReviewProgress | null, reviewError?: ReviewData['error']) => {
      if (nextProgress) {
        setProgress(nextProgress)
        const index = stages.findIndex((stage) => stage.code === nextProgress.stage)
        if (index >= 0) setActiveStep(index)
      }
      if (reviewState === 'COMPLETED') {
        setActiveStep(Math.max(stages.length - 1, 0))
        setMode('done')
      }
      if (reviewState === 'FAILED') {
        setMode('error')
        setErrorMessage(reviewError?.message || '검토 중 오류가 발생했습니다.')
        setRetryable(reviewError?.retryable === true)
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
          if (!['COMPLETED', 'FAILED', 'CANCELLED', 'EXPIRED'].includes(response.data.review_state)) {
            pollingTimer = setTimeout(poll, 1500)
          }
        } catch (error: any) {
          if (!subscribed) return
          if (error?.status === 404 || error?.status === 410) {
            showToast('검토 정보를 찾을 수 없거나 만료되었습니다. 처음부터 다시 시작해 주세요.', 'error')
            return
          }
          setMode('error')
          setErrorMessage(error?.message || '검토 상태를 불러오지 못했습니다.')
          setRetryable(error?.retryable === true)
        }
      }
      void poll()
    }

    try {
      source = new EventSource(api.reviewEventsUrl(reviewId), { withCredentials: true })
      const onEvent = (event: MessageEvent<string>) => {
        const data = JSON.parse(event.data) as ReviewData & { sequence?: number }
        const sequence = data.sequence ?? Number(event.lastEventId)
        if (Number.isFinite(sequence) && sequence <= lastSequence) return
        if (Number.isFinite(sequence)) lastSequence = sequence
        update(data.review_state, data.progress, data.error)
      }
      source.addEventListener('progress', onEvent)
      source.addEventListener('completed', onEvent)
      source.addEventListener('failed', onEvent)
      source.onerror = () => {
        source?.close()
        startPolling()
      }
    } catch {
      startPolling()
    }

    return () => {
      subscribed = false
      source?.close()
      if (pollingTimer) clearTimeout(pollingTimer)
    }
  }, [mode, reviewId, showToast, stages])

  const retry = async () => {
    if (!reviewId) return
    try {
      await api.retryReview(reviewId, crypto.randomUUID())
      setActiveStep(0)
      setProgress(null)
      setMode('running')
    } catch (error: any) {
      setErrorMessage(error?.message || '재시도 요청에 실패했습니다.')
      setRetryable(error?.retryable === true)
    }
  }

  if (!reviewId) return <p className="text-sm text-rose-600">검토 ID를 찾을 수 없습니다.</p>

  return (
    <div className="mx-auto w-full max-w-[760px] space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-950">계약서를 검토하고 있습니다</h1>
        <p className="mt-2 text-sm text-slate-500">진행 상태는 실시간으로 갱신됩니다.</p>
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
      {mode === 'done' && <button onClick={onDone} className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white">검토 결과 확인 <ChevronRight className="size-4" /></button>}
    </div>
  )
}
