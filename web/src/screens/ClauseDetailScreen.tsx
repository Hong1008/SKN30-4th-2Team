import { createClientId } from '../utils/clientId'
import { useState, useEffect, useRef, useCallback } from 'react'
import { ArrowLeft, Scale, Copy, ChevronRight, MessageSquare, Check, BookOpen, Loader2, RefreshCw } from 'lucide-react'
import Badge from '../components/Badge'
import type { ClauseResult, GroundingItem, SuggestionResponse } from '../types'
import { api } from '../api/api'
import { useMetadata } from '../contexts/MetadataContext'
import { getMetadataLabel, getStatusPresentation } from '../utils/metadata'
import { getErrorMessage, getSafeKoreanMessage } from '../utils/apiErrors'
import SourceReferences, { type SourceReference } from '../components/SourceReferences'

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
  const [groundingRetryable, setGroundingRetryable] = useState(false)
  const [suggestion, setSuggestion] = useState<SuggestionResponse | null>(null)
  const [loadingSuggestion, setLoadingSuggestion] = useState(false)
  const [suggestionError, setSuggestionError] = useState('')
  const [suggestionPurpose, setSuggestionPurpose] = useState('책임과 의무 범위를 명확히 하는 협의 문구')
  const [suggestionInputs, setSuggestionInputs] = useState<Record<string, string>>({})
  const suggestionRequestKey = useRef<string | null>(null)

  const loadGrounding = useCallback(() => {
    if (!reviewId || !clause.categoryCode) return
    setLoadingGrounding(true)
    setGroundingMessage('')
    setGroundingRetryable(false)
    api.getGrounding(reviewId, clause.categoryCode).then(res => {
        setLegalBasis(res.data.items)
        setGroundingStatus(res.data.grounding_status)
        setGroundingMessage(getSafeKoreanMessage(res.data.message) || '')
        setGroundingRetryable(res.data.retryable === true)
        setLoadingGrounding(false)
      }).catch((error) => {
        setLegalBasis([])
        setGroundingStatus(error?.code || 'REQUEST_FAILED')
        setGroundingMessage(getErrorMessage(error, '관련 법령 근거를 불러오지 못했습니다.'))
        setGroundingRetryable(error?.retryable === true)
        setLoadingGrounding(false)
      })
  }, [reviewId, clause.categoryCode])

  useEffect(() => {
    loadGrounding()
  }, [loadGrounding])

  const groundingPresentation = getStatusPresentation(metadata?.grounding_status_details, groundingStatus)
  const canReloadGrounding = groundingRetryable || groundingPresentation?.retryable === true

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
    setSuggestion(null)
    try {
      const idempotencyKey = suggestionRequestKey.current ?? createClientId()
      suggestionRequestKey.current = idempotencyKey
      const response = await api.suggestions(
        reviewId,
        clause.id,
        suggestionPurpose.trim(),
        idempotencyKey,
        suggestionInputs,
      )
      setSuggestion(response.data)
      suggestionRequestKey.current = null
    } catch (error: any) {
      setSuggestionError(getErrorMessage(error, '협의 문구를 생성하지 못했습니다.'))
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
  const suggestionInputFields = suggestion
    ? Array.from(new Map<string, string>([
        ...suggestion.required_confirmations.map(item => [item.field, item.placeholder] as [string, string]),
        ...suggestion.missing_inputs.map(field => [field, field] as [string, string]),
      ]).entries())
    : []
  const suggestionSources: SourceReference[] = suggestion ? [
    ...(suggestion.user_clause_ids.length > 0 ? [{
      type: 'USER_CLAUSE' as const,
      clause_number: clause.article,
      category: clause.category,
    }] : []),
    ...(suggestion.standard_clause_ids.length > 0 ? [{
      type: 'STANDARD_CLAUSE' as const,
      title: clause.standardTitle,
      category: clause.category,
    }] : []),
    ...suggestion.grounding_source_ids.map(sourceId => {
      const basis = legalBasis.find(item => item.source_id === sourceId)
      return {
        type: 'LAW' as const,
        law_name: basis?.law_name,
        article: basis?.article,
        source_url: basis?.source_url,
      }
    }),
  ] : []

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
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">검토 포인트</p>
          <p className="text-sm text-slate-900 leading-relaxed">{clause.summary}</p>
        </div>
      </div>

      {/* Comparison */}
      <div className="grid gap-5 md:grid-cols-2">
        {/* User clause */}
        <div className="flex min-h-[320px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white">
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-200 bg-slate-50">
            <p className="text-xs font-semibold text-slate-900">업로드한 계약서</p>
            <button
              onClick={() => copy('user', clause.excerpt)}
              className="flex items-center gap-1 text-xs text-slate-600 transition-colors hover:text-slate-900"
              aria-label="원문 복사"
            >
              {copied === 'user' ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
              {copied === 'user' ? '복사됨' : '복사'}
            </button>
          </div>
          <pre className="flex-1 whitespace-pre-wrap break-words px-5 py-5 font-sans text-sm leading-7 text-slate-800">
            {clause.excerpt}
          </pre>
        </div>

        {/* Standard clause */}
        <div className="flex min-h-[320px] flex-col overflow-hidden rounded-2xl border border-blue-200 bg-blue-50/25">
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-blue-200 bg-blue-50/60">
            <p className="text-xs font-semibold text-blue-600">대응 표준조항 {clause.standardTitle && `(${clause.standardTitle})`}</p>
            <button
              onClick={() => copy('standard', clause.standardText || '')}
              className="flex items-center gap-1 text-xs text-blue-600 transition-colors hover:text-slate-900"
              aria-label="표준조항 복사"
            >
              {copied === 'standard' ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
              {copied === 'standard' ? '복사됨' : '복사'}
            </button>
          </div>
          <pre className="flex-1 whitespace-pre-wrap break-words px-5 py-5 font-sans text-sm leading-7 text-slate-800">
            {clause.standardText || '매칭된 표준 조항이 없습니다.'}
          </pre>
          {clause.standardClauseId && (
            <div className="border-t border-blue-100 px-5 py-3 text-xs leading-5 text-slate-500">
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
        ) : groundingStatus === 'OK' && legalBasis.length > 0 ? (
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
                    <p className="text-xs text-slate-500">출처: {basis.source}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
           <div className="bg-white border border-slate-200 rounded-xl p-8 text-center text-slate-500">
             <p className="text-xs">{groundingPresentation?.message || groundingMessage || '법령 근거 정보를 확인하지 못했습니다.'}</p>
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
      {metadata?.features.basic_suggestion && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <label htmlFor="suggestion-purpose" className="mb-2 block text-xs font-semibold text-slate-700">
            협의 목적
          </label>
          <input
            id="suggestion-purpose"
            value={suggestionPurpose}
            maxLength={500}
            onChange={(event) => {
              setSuggestionPurpose(event.target.value)
              suggestionRequestKey.current = null
            }}
            placeholder="예: 책임 범위와 지급 조건을 명확히 하고 싶어요"
            className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10"
          />
        </div>
      )}
      <div className="flex items-center gap-3 flex-wrap pt-2">
        {metadata?.features.basic_suggestion && (
          <button
            onClick={createSuggestion}
            disabled={loadingSuggestion || !reviewId || !canCreateSuggestion || !suggestionPurpose.trim()}
            title={!canCreateSuggestion ? '대응 표준조항이 확인된 조항에서만 생성할 수 있습니다.' : undefined}
            className="flex min-h-11 items-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/20 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loadingSuggestion ? '협의 문구 생성 중' : '협의 문구 제안 보기'}
            {loadingSuggestion ? <Loader2 className="w-4 h-4 animate-spin" /> : <ChevronRight className="w-4 h-4" />}
          </button>
        )}
        {metadata?.features.chat && <button
          onClick={onChatbot}
          className="flex min-h-11 items-center gap-2 rounded-xl border border-slate-200 bg-white px-5 py-3 text-sm font-medium text-slate-900 transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15"
        >
          <MessageSquare className="w-4 h-4" />
          이 조항에 대해 질문하기
        </button>}
      </div>

      {suggestionError && <p className="text-sm text-rose-600" role="alert">{suggestionError}</p>}
      {suggestion && (
        <section className="space-y-3 rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
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
          <p className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${
            suggestion.outcome === 'GENERATED'
              ? 'bg-emerald-50 text-emerald-700'
              : suggestion.outcome === 'INSUFFICIENT_GROUNDING'
                ? 'bg-amber-50 text-amber-700'
                : 'bg-rose-50 text-rose-700'
          }`}>
            {{
              GENERATED: '제안 생성 완료',
              INSUFFICIENT_GROUNDING: '근거 부족',
              REQUIRED_VALUE_MISSING: '필수값 확인 필요',
              GENERATED_FACT_NOT_GROUNDED: '근거 검증 실패',
              LLM_OUTPUT_INVALID: '생성 결과 검증 실패',
            }[suggestion.outcome] || suggestion.outcome}
          </p>
          {suggestion.outcome !== 'GENERATED' && <p className="text-sm text-amber-700">{getStatusPresentation(metadata?.draft_outcome_details, suggestion.outcome)?.message || '협의 문구 생성 조건을 확인해 주세요.'}</p>}
          {suggestion.text
            ? <p className="whitespace-pre-wrap text-sm leading-7 text-slate-800">{suggestion.text}</p>
            : <p className="text-sm text-slate-600">제안 생성에 필요한 정보가 부족합니다.</p>}
          {suggestion.purpose && <p className="text-xs text-slate-600">생성 목적: {suggestion.purpose}</p>}
          {suggestion.key_changes.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-xs text-slate-600">
              {suggestion.key_changes.map(change => <li key={change}>{change}</li>)}
            </ul>
          )}
          {suggestionInputFields.length > 0 && (
            <div className="space-y-2 text-xs text-amber-700">
              <p className="font-semibold">확인이 필요한 항목</p>
              {suggestionInputFields.map(([field, placeholder]) => (
                <label key={field} className="block space-y-1">
                  <span>{field}</span>
                  <input
                    value={suggestionInputs[field] || ''}
                    onChange={(event) => setSuggestionInputs(previous => ({ ...previous, [field]: event.target.value }))}
                    placeholder={placeholder}
                    className="w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10"
                  />
                </label>
              ))}
              <button type="button" onClick={createSuggestion} disabled={loadingSuggestion} className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-semibold text-amber-800 disabled:opacity-50">
                입력값으로 다시 생성
              </button>
            </div>
          )}
          <SourceReferences sources={suggestionSources} title="협의 문구 출처" />
          {suggestion.outcome === 'GENERATED' && suggestion.grounding_source_ids.length === 0 && (
            <p className="text-xs text-amber-700">법령 근거 없이 표준조항을 기준으로 작성된 초안입니다.</p>
          )}
          <p className="text-xs leading-5 text-slate-500">{suggestion.disclaimer}</p>
        </section>
      )}
    </div>
  )
}
