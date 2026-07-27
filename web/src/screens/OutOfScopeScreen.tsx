import { useState } from 'react'
import { AlertCircle, ArrowLeft, ChevronRight, FileQuestion } from 'lucide-react'
import { api } from '../api/api'
import { REVIEW_ID_KEY } from '../config'

interface Props {
  sessionId: string | null
  onBack: () => void
  onContinue: (reviewId: string) => void
}

export default function OutOfScopeScreen({ sessionId, onBack, onContinue }: Props) {
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')

  const continueReview = async () => {
    if (!sessionId) {
      setError('검토 세션을 찾을 수 없습니다. 계약서를 다시 업로드해 주세요.')
      return
    }

    setIsSubmitting(true)
    setError('')
    try {
      const confirmation = await api.confirmOutOfScope(sessionId, true)
      if (!confirmation.data.can_start_review && !confirmation.data.allowed_actions?.includes('START_REVIEW')) {
        setError('현재 상태에서는 검토를 시작할 수 없습니다.')
        return
      }
      const review = await api.startReview(sessionId, crypto.randomUUID())
      localStorage.setItem(REVIEW_ID_KEY, review.data.review_id)
      onContinue(review.data.review_id)
    } catch (err: any) {
      const existingReviewId = err?.details?.review_id
      if (err?.status === 409 && existingReviewId) {
        localStorage.setItem(REVIEW_ID_KEY, existingReviewId)
        onContinue(existingReviewId)
      } else {
        setError(err?.message || '검토 시작 요청에 실패했습니다. 다시 시도해 주세요.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-[760px] space-y-8 animate-fade-up">
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
          선택한 계약 유형의 표준계약서와 업로드한 문서 사이의 공통 조항이 충분하지 않아
          비교 결과의 범위가 제한될 수 있습니다.
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
            <p className="text-sm font-semibold text-slate-900">프리랜서 계약서</p>
            <p className="text-xs text-slate-600">자유직업인 계약서</p>
          </div>
        </div>
      </div>

      {/* Limitation reason */}
      <div className="bg-slate-50 border border-slate-200 rounded-xl p-5 space-y-4">
        <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">제한 사유</p>
        <ul className="space-y-2.5">
          {[
            '문서에서 독립 계약자 관계를 명확히 나타내는 표현이 충분히 확인되지 않았습니다.',
            '근로 시간, 임금 등 근로 관계에 가까운 표현이 더 많이 나타납니다.',
            '선택한 유형의 표준계약서와 공통으로 비교할 조항이 3개 미만입니다.',
          ].map((item, i) => (
            <li key={i} className="flex items-start gap-2.5">
              <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-slate-500 shrink-0" aria-hidden="true" />
              <span className="text-sm text-slate-600 leading-relaxed">{item}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* Proceed caution */}
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-5">
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
          disabled={isSubmitting}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white shadow-[0_1px_2px_rgba(37,99,235,0.2),0_6px_16px_rgba(37,99,235,0.16)] transition-[background-color,box-shadow,transform] duration-150 hover:-translate-y-px hover:bg-blue-700 hover:shadow-md active:translate-y-0 active:bg-blue-800 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/20"
        >
          {isSubmitting ? '검토를 시작하는 중...' : '계속 검토하기'}
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}
