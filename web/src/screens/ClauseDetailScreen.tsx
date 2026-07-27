import { useState, useEffect } from 'react'
import { ArrowLeft, Scale, Copy, ChevronRight, MessageSquare, Check, BookOpen, Loader2 } from 'lucide-react'
import Badge from '../components/Badge'
import type { ClauseResult } from '../types'
import { api } from '../api/api'

interface Props {
  clause: ClauseResult
  reviewId: string | null
  onBack: () => void
  onChatbot: () => void
}

export default function ClauseDetailScreen({ clause, reviewId, onBack, onChatbot }: Props) {
  const [copied, setCopied] = useState<'user' | 'standard' | null>(null)
  const [legalBasis, setLegalBasis] = useState<any[]>([])
  const [loadingGrounding, setLoadingGrounding] = useState(false)

  useEffect(() => {
    if (reviewId && clause.categoryCode) {
      setLoadingGrounding(true)
      api.getGrounding(reviewId, clause.categoryCode).then(res => {
        if (res.data?.items) {
          setLegalBasis(res.data.items)
        }
        setLoadingGrounding(false)
      }).catch(() => {
        setLoadingGrounding(false)
      })
    }
  }, [reviewId, clause.categoryCode])

  const copy = (which: 'user' | 'standard', text: string) => {
    if (!text) return
    navigator.clipboard.writeText(text).catch(() => {})
    setCopied(which)
    setTimeout(() => setCopied(null), 1800)
  }

  return (
    <div className="space-y-6 animate-fade-up">
      {/* Back + breadcrumb */}
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          검토 결과로
        </button>
        <span className="text-slate-200">/</span>
        <span className="text-sm text-slate-900 font-medium">{clause.article}</span>
      </div>

      {/* Status + review point */}
      <div className="bg-white border border-slate-200 rounded-2xl p-6 space-y-4">
        <div className="flex items-center gap-3 flex-wrap">
          <Badge code={clause.status} label={clause.status === 'NONE' ? '정상' : clause.status === 'EXTRA' ? '변형 확인' : clause.status === 'NO_MATCH' ? '주의 필요' : '누락 확인'} />
          <span className="text-xs text-slate-500 bg-slate-50 border border-slate-200 px-2.5 py-1 rounded-full">
            {clause.category}
          </span>
        </div>
        <div>
          <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-2">검토 포인트</p>
          <p className="text-sm text-slate-900 leading-relaxed">{clause.summary}</p>
        </div>
      </div>

      {/* Comparison */}
      <div className="grid md:grid-cols-2 gap-4">
        {/* User clause */}
        <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-200 bg-slate-50">
            <p className="text-xs font-semibold text-slate-900">업로드한 계약서</p>
            <button
              onClick={() => copy('user', clause.excerpt)}
              className="flex items-center gap-1 text-[11px] text-slate-600 hover:text-slate-900 transition-colors"
              aria-label="원문 복사"
            >
              {copied === 'user' ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
              {copied === 'user' ? '복사됨' : '복사'}
            </button>
          </div>
          <pre className="px-5 py-5 text-xs text-slate-900 leading-loose font-mono whitespace-pre-wrap break-words">
            {clause.excerpt}
          </pre>
        </div>

        {/* Standard clause */}
        <div className="bg-blue-50/40 border border-blue-200 rounded-2xl overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-blue-200 bg-blue-50/60">
            <p className="text-xs font-semibold text-blue-600">대응 표준조항 {clause.standardTitle && `(${clause.standardTitle})`}</p>
            <button
              onClick={() => copy('standard', clause.standardText || '')}
              className="flex items-center gap-1 text-[11px] text-blue-600 hover:text-slate-900 transition-colors"
              aria-label="표준조항 복사"
            >
              {copied === 'standard' ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
              {copied === 'standard' ? '복사됨' : '복사'}
            </button>
          </div>
          <pre className="px-5 py-5 text-xs text-slate-900 leading-loose font-mono whitespace-pre-wrap break-words">
            {clause.standardText || '매칭된 표준 조항이 없습니다.'}
          </pre>
        </div>
      </div>

      {/* Legal basis */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <Scale className="w-4 h-4 text-slate-600" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-slate-900">법령 근거</h2>
        </div>
        
        {loadingGrounding ? (
          <div className="bg-white border border-slate-200 rounded-xl p-8 flex flex-col items-center justify-center text-slate-500">
            <Loader2 className="w-5 h-5 animate-spin mb-2" />
            <p className="text-xs">관련 법령을 불러오고 있습니다...</p>
          </div>
        ) : legalBasis.length > 0 ? (
          <div className="space-y-3">
            {legalBasis.map((basis, i) => (
              <div key={i} className="bg-white border border-slate-200 rounded-xl p-5">
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 bg-blue-50 rounded-lg flex items-center justify-center shrink-0 mt-0.5">
                    <BookOpen className="w-4 h-4 text-blue-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-2">
                      <span className="text-xs font-semibold text-blue-600 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded">{basis.law_name} {basis.article}</span>
                    </div>
                    <p className="text-xs text-slate-600 leading-relaxed mb-2">{basis.text}</p>
                    <p className="text-[10px] text-slate-500">출처: {basis.source}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
           <div className="bg-white border border-slate-200 rounded-xl p-8 text-center text-slate-500">
             <p className="text-xs">해당 카테고리에 매핑된 법령 근거가 없습니다.</p>
           </div>
        )}
      </div>

      {/* CTAs */}
      <div className="flex items-center gap-3 flex-wrap pt-2">
        <button
          onClick={onChatbot}
          className="flex items-center gap-2 px-5 py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition-colors"
        >
          협의 문구 제안 보기
          <ChevronRight className="w-4 h-4" />
        </button>
        <button
          onClick={onChatbot}
          className="flex items-center gap-2 px-5 py-3 bg-white border border-slate-200 text-slate-900 rounded-xl text-sm font-medium hover:bg-slate-50 transition-colors"
        >
          <MessageSquare className="w-4 h-4" />
          이 조항에 대해 질문하기
        </button>
      </div>
    </div>
  )
}
