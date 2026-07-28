import { useEffect, useRef, useState } from 'react'
import { AlertCircle, ArrowLeft, ChevronRight, FileQuestion } from 'lucide-react'
import { api } from '../api/api'
import { getErrorMessage } from '../utils/apiErrors'
import { REVIEW_ID_KEY } from '../config'
import { useMetadata } from '../contexts/MetadataContext'
import { getMetadataLabel } from '../utils/metadata'
import type { ReviewSessionData } from '../types'

interface Props {
  sessionId: string | null
  onBack: () => void
  onContinue: (reviewId: string) => void
  setSessionExpiresAt: (expiresAt: string | null) => void
}

export default function OutOfScopeScreen({ sessionId, onBack, onContinue, setSessionExpiresAt }: Props) {
  const { metadata } = useMetadata()
  const [session, setSession] = useState<ReviewSessionData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')
  const startRequestKey = useRef<string | null>(null)

  useEffect(() => {
    if (!sessionId) {
      setError('검토 세션을 찾을 수 없습니다. 계약서를 다시 업로드해 주세요.')
      setIsLoading(false)
      return
    }
    const controller = new AbortController()
    setError('')
    api.getSession(sessionId, controller.signal)
      .then(({ data }) => {
        setSession(data)
        setSessionExpiresAt(data.expires_at)
        if (data.review_state !== 'OUT_OF_SCOPE_CONFIRMATION_REQUIRED') {
          setError('현재 세션은 제공 범위 확인이 필요한 상태가 아닙니다.')
        }
      })
      .catch((requestError) => {
        if (requestError?.name !== 'AbortError') {
          setError(getErrorMessage(requestError, '검토 범위 정보를 불러오지 못했습니다.'))
        }
      })
      .finally(() => setIsLoading(false))
    return () => controller.abort()
  }, [sessionId, setSessionExpiresAt])

  const contractTypeCode = session?.selected_contract_type || session?.suggested_contract_type
  const contractTypeLabel = getMetadataLabel(
    metadata?.contract_types,
    contractTypeCode,
    contractTypeCode || '선택 정보 없음',
  )

  const continueReview = async () => {
    if (!sessionId) {
      setError('검토 세션을 찾을 수 없습니다. 계약서를 다시 업로드해 주세요.')
      return
    }

    setIsSubmitting(true)
    setError('')
    try {
      const confirmation = await api.confirmOutOfScope(sessionId, true)
      setSessionExpiresAt(confirmation.data.expires_at)
      if (!confirmation.data.can_start_review && !confirmation.data.allowed_actions?.includes('START_REVIEW')) {
        setError('현재 상태에서는 검토를 시작할 수 없습니다.')
        return
      }
      const idempotencyKey = startRequestKey.current ?? crypto.randomUUID()
      startRequestKey.current = idempotencyKey
      const review = await api.startReview(sessionId, idempotencyKey)
      startRequestKey.current = null
      localStorage.setItem(REVIEW_ID_KEY, review.data.review_id)
      onContinue(review.data.review_id)
    } catch (err: any) {
      const existingReviewId = err?.details?.review_id
      if (err?.status === 409 && existingReviewId) {
        startRequestKey.current = null
        localStorage.setItem(REVIEW_ID_KEY, existingReviewId)
        onContinue(existingReviewId)
      } else {
        setError(getErrorMessage(err, '검토 시작 요청에 실패했습니다. 다시 시도해 주세요.'))
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-[760px] space-y-5 animate-fade-up">
      {/* Title */}
      <div>
        <div className="inline-flex items-center gap-2 text-xs font-medium text-slate-600 bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-full mb-4">
          <AlertCircle className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
          검토 범위 안내
        </div>
        <h1 className="text-[22px] font-semibold text-slate-900 tracking-tight mb-3 leading-snug">
          현재 표준계약서와의<br />공통 근거가 제한적입니다
        </h1>
        <p className="text-sm text-slate-600 leading-relaxed">
          {session?.scope_message || '선택한 계약 유형과 문서의 공통 근거가 제한되어 비교 결과의 범위가 좁을 수 있습니다.'}
        </p>
      </div>

      {/* Selected type card */}
      <div className="bg-white border border-slate-200 rounded-xl p-5">
        <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-3">선택한 계약 유형</p>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center shrink-0">
            <FileQuestion className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-900">{contractTypeLabel}</p>
            <p className="text-xs text-slate-600">선택 코드: {contractTypeCode || '없음'}</p>
          </div>
        </div>
      </div>

      {/* Limitation reason */}
      <div className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
        <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">제한 사유</p>
        <ul className="space-y-2.5">
          {[
            ...(session?.scope_message ? [session.scope_message] : []),
            `비교 후보로 확인된 조항: ${session?.matched_clause_count ?? 0}개`,
            ...(session?.exclusion_markers.length
              ? [`제외 판단 표식: ${session.exclusion_markers.join(', ')}`]
              : []),
          ].map((item, i) => (
            <li key={i} className="flex items-start gap-2.5">
              <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-slate-500 shrink-0" aria-hidden="true" />
              <span className="text-sm text-slate-600 leading-relaxed">{item}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* Proceed caution */}
      <div className="rounded-2xl border border-amber-200 bg-amber-50/60 p-5">
        <p className="text-xs font-semibold text-amber-700 mb-2">계속 진행 시 유의사항</p>
        <ul className="space-y-1.5">
          {[
            '비교 대상 조항이 적어 검토 결과가 일부에 그칠 수 있습니다.',
            '비교 결과는 해당 계약 유형의 표준조항을 기준으로 하며, 실제 계약 관계와 다를 수 있습니다.',
            '이 서비스는 법률 자문을 제공하지 않습니다.',
          ].map((item, i) => (
            <li key={i} className="flex items-start gap-2">
              <span className="mt-1.5 w-1 h-1 rounded-full bg-amber-400 shrink-0" aria-hidden="true" />
              <span className="text-xs text-amber-700 leading-relaxed">{item}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* Actions */}
      {isLoading && <p className="text-sm text-slate-500">검토 범위 정보를 확인하고 있습니다.</p>}
      {error && <p className="text-sm text-rose-600" role="alert">{error}</p>}
      <div className="flex items-center gap-3 pt-2">
        <button
          onClick={onBack}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 transition-colors hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15"
        >
          <ArrowLeft className="w-4 h-4" />
          유형 다시 선택
        </button>
        <button
          onClick={continueReview}
          disabled={isSubmitting || isLoading || !session || session.review_state !== 'OUT_OF_SCOPE_CONFIRMATION_REQUIRED'}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white shadow-[0_1px_2px_rgba(37,99,235,0.2),0_6px_16px_rgba(37,99,235,0.16)] transition-[background-color,box-shadow,transform] duration-150 hover:-translate-y-px hover:bg-blue-700 hover:shadow-md active:translate-y-0 active:bg-blue-800 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/20"
        >
          {isSubmitting ? '검토를 시작하는 중...' : '계속 검토하기'}
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}
