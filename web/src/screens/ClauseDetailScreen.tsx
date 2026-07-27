import { useState, useEffect, useRef, useCallback } from 'react'
import { ArrowLeft, Scale, Copy, ChevronRight, MessageSquare, Check, BookOpen, Loader2, RefreshCw } from 'lucide-react'
import Badge from '../components/Badge'
import type { ClauseResult, GroundingItem, SuggestionResponse } from '../types'
import { api } from '../api/api'
import { useMetadata } from '../contexts/MetadataContext'
import { getMetadataLabel } from '../utils/metadata'
import { getNextAction } from '../utils/apiErrors'

interface Props {
  clause: ClauseResult
  reviewId: string | null
  onBack: () => void
  onChatbot: () => void
}

export default function ClauseDetailScreen({ clause, reviewId, onBack, onChatbot }: Props) {
  const { metadata } = useMetadata()
  const [copied, setCopied] = useState<'user' | 'standard' | 'suggestion' | null>(null)
  const [legalBasis, setLegalBasis] = useState<GroundingItem[]>([])
  const [loadingGrounding, setLoadingGrounding] = useState(false)
  const [groundingMessage, setGroundingMessage] = useState('')
  const [groundingStatus, setGroundingStatus] = useState('')
  const [suggestion, setSuggestion] = useState<SuggestionResponse | null>(null)
  const [loadingSuggestion, setLoadingSuggestion] = useState(false)
  const [suggestionError, setSuggestionError] = useState('')
  const suggestionRequestKey = useRef<string | null>(null)

  const loadGrounding = useCallback(() => {
    if (!reviewId || !clause.categoryCode) return
    setLoadingGrounding(true)
    setGroundingMessage('')
    api.getGrounding(reviewId, clause.categoryCode).then(res => {
        setLegalBasis(res.data.items)
        setGroundingStatus(res.data.grounding_status)
        setGroundingMessage(res.data.message || '')
        setLoadingGrounding(false)
      }).catch((error) => {
        setLegalBasis([])
        setGroundingStatus(getNextAction(error) || error?.code || 'REQUEST_FAILED')
        setGroundingMessage(error?.message || '관련 법령 근거를 불러오지 못했습니다.')
        setLoadingGrounding(false)
      })
  }, [reviewId, clause.categoryCode])

  useEffect(() => {
    loadGrounding()
  }, [loadGrounding])

  const canReloadGrounding = [
    'UPSTREAM_ERROR',
    'TIMEOUT',
    'GROUNDING_TIMEOUT',
    'GROUNDING_UPSTREAM_ERROR',
    'RELOAD_GROUNDING',
    'REQUEST_FAILED',
  ].includes(groundingStatus)

  const copy = (which: 'user' | 'standard' | 'suggestion', text: string) => {
    if (!text) return
    navigator.clipboard.writeText(text).catch(() => {})
    setCopied(which)
    setTimeout(() => setCopied(null), 1800)
  }

  const createSuggestion = async () => {
    if (!reviewId || clause.matchStatus !== 'CANDIDATE_SELECTED' || !clause.standardClauseId) return
    setLoadingSuggestion(true)
    setSuggestionError('')
    try {
      const idempotencyKey = suggestionRequestKey.current ?? crypto.randomUUID()
      suggestionRequestKey.current = idempotencyKey
      const response = await api.suggestions(
        reviewId,
        clause.id,
        '표준계약서 기준의 중립적인 협의 문구 제안',
        idempotencyKey,
      )
      setSuggestion(response.data)
      suggestionRequestKey.current = null
    } catch (error: any) {
      setSuggestionError(error?.message || '협의 문구를 생성하지 못했습니다.')
    } finally {
      setLoadingSuggestion(false)
    }
  }

  const statusLabel = getMetadataLabel(
    metadata?.result_code_details,
    clause.status,
    clause.status,
  )
  const canCreateSuggestion = clause.matchStatus === 'CANDIDATE_SELECTED'
    && Boolean(clause.standardClauseId && clause.standardText)

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
          <Badge code={clause.status} label={statusLabel} />
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
          {clause.standardClauseId && (
            <div className="border-t border-blue-100 px-5 py-3 text-[11px] leading-5 text-slate-500">
              <p>표준조항 ID: {clause.standardClauseId}</p>
              {clause.standardVersion && <p>버전: {clause.standardVersion}</p>}
              {clause.standardSource && <p>출처: {clause.standardSource}</p>}
            </div>
          )}
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
             <p className="text-xs">{groundingMessage || '해당 카테고리에 매핑된 법령 근거가 없습니다.'}</p>
             {canReloadGrounding && (
               <button
                 type="button"
                 onClick={loadGrounding}
                 className="mx-auto mt-3 inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
               >
                 <RefreshCw className="size-3.5" />
                 법령 근거 다시 불러오기
               </button>
             )}
           </div>
        )}
      </div>

      {/* CTAs */}
      <div className="flex items-center gap-3 flex-wrap pt-2">
        {metadata?.features.basic_suggestion && (
          <button
            onClick={createSuggestion}
            disabled={loadingSuggestion || !reviewId || !canCreateSuggestion}
            title={!canCreateSuggestion ? '대응 표준조항이 확인된 조항에서만 생성할 수 있습니다.' : undefined}
            className="flex items-center gap-2 px-5 py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition-colors disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loadingSuggestion ? '협의 문구 생성 중' : '협의 문구 제안 보기'}
            {loadingSuggestion ? <Loader2 className="w-4 h-4 animate-spin" /> : <ChevronRight className="w-4 h-4" />}
          </button>
        )}
        {metadata?.features.chat && <button
          onClick={onChatbot}
          className="flex items-center gap-2 px-5 py-3 bg-white border border-slate-200 text-slate-900 rounded-xl text-sm font-medium hover:bg-slate-50 transition-colors"
        >
          <MessageSquare className="w-4 h-4" />
          이 조항에 대해 질문하기
        </button>}
      </div>

      {suggestionError && <p className="text-sm text-rose-600" role="alert">{suggestionError}</p>}
      {suggestion && (
        <section className="rounded-2xl border border-blue-200 bg-blue-50/40 p-5 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-slate-900">협의 문구 제안</h2>
            {suggestion.text && (
              <button
                type="button"
                onClick={() => copy('suggestion', suggestion.text || '')}
                className="inline-flex items-center gap-1 text-xs font-semibold text-blue-700"
              >
                {copied === 'suggestion' ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                {copied === 'suggestion' ? '복사됨' : '제안 복사'}
              </button>
            )}
          </div>
          {suggestion.text
            ? <p className="whitespace-pre-wrap text-sm leading-7 text-slate-800">{suggestion.text}</p>
            : <p className="text-sm text-slate-600">제안 생성에 필요한 정보가 부족합니다.</p>}
          {suggestion.purpose && <p className="text-xs text-slate-600">생성 목적: {suggestion.purpose}</p>}
          {suggestion.key_changes.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-xs text-slate-600">
              {suggestion.key_changes.map(change => <li key={change}>{change}</li>)}
            </ul>
          )}
          {suggestion.missing_inputs.length > 0 && (
            <p className="text-xs text-amber-700">추가 정보: {suggestion.missing_inputs.join(', ')}</p>
          )}
          {suggestion.required_confirmations.length > 0 && (
            <div className="space-y-1 text-xs text-amber-700">
              <p className="font-semibold">확인이 필요한 항목</p>
              {suggestion.required_confirmations.map(item => (
                <p key={item.field}>{item.field}: {item.placeholder}</p>
              ))}
            </div>
          )}
          {(suggestion.standard_clause_ids.length > 0 || suggestion.grounding_source_ids.length > 0) && (
            <div className="text-[11px] leading-5 text-slate-500">
              {suggestion.standard_clause_ids.length > 0 && (
                <p>참고 표준조항: {suggestion.standard_clause_ids.join(', ')}</p>
              )}
              {suggestion.grounding_source_ids.length > 0 && (
                <p>참고 법령 근거: {suggestion.grounding_source_ids.join(', ')}</p>
              )}
            </div>
          )}
          <p className="text-[11px] text-slate-500">{suggestion.disclaimer}</p>
        </section>
      )}
    </div>
  )
}
