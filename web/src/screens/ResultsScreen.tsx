import { createClientId } from '../utils/clientId'
import { useState, useEffect, useRef } from 'react'
import { Search, SlidersHorizontal, MessageSquare, ChevronRight, RotateCcw, ChevronDown, ChevronUp, AlertTriangle, CheckSquare, Trash2, Loader2 } from 'lucide-react'
import Badge from '../components/Badge'
import type { ResultCode, ClauseResult, ResultsData } from '../types'
import { api } from '../api/api'
import { getErrorMessage } from '../utils/apiErrors'
import { useMetadata } from '../contexts/MetadataContext'
import { getMetadataLabel } from '../utils/metadata'
import { mapClauseResult } from '../utils/reviewResults'
import { REVIEW_ID_KEY, SESSION_ID_KEY, getChatHistoryStorageKey } from '../config'
import { getStandardContractLabel } from '../utils/standardContractLabel'

const CLAUSE_VISUALS: Record<ResultCode, {
  accent: string
  gradient: string
  hover: string
}> = {
  NONE: {
    accent: 'before:bg-emerald-500',
    gradient: 'from-emerald-50/55',
    hover: 'hover:border-emerald-200',
  },
  EXTRA: {
    accent: 'before:bg-amber-500',
    gradient: 'from-amber-50/55',
    hover: 'hover:border-amber-200',
  },
  NO_MATCH: {
    accent: 'before:bg-rose-500',
    gradient: 'from-rose-50/55',
    hover: 'hover:border-rose-200',
  },
  MISSING: {
    accent: 'before:bg-slate-500',
    gradient: 'from-slate-100/70',
    hover: 'hover:border-slate-300',
  },
}

interface Props {
  reviewId: string | null;
  onClauseClick: (clause: ClauseResult) => void
  onChatbot: () => void
  onReviewInProgress?: () => void
}

export default function ResultsScreen({ reviewId, onClauseClick, onChatbot, onReviewInProgress }: Props) {
  const { metadata } = useMetadata()
  const resultCodeDetails = metadata?.result_code_details ?? []
  const categories = ['전체', ...(metadata?.categories.map(c => c.label) || [])]
  const statuses: { id: ResultCode | 'all'; label: string }[] = [
    { id: 'all', label: '전체' },
    ...resultCodeDetails
      .filter(r => r.code !== 'MISSING')
      .map(r => ({ id: r.code as ResultCode, label: r.label }))
  ]
  const [filterStatus, setFilterStatus]     = useState<ResultCode | 'all'>('all')
  const [filterCategory, setFilterCategory] = useState('전체')
  const [search, setSearch]                 = useState('')
  const [expandedMissing, setExpandedMissing] = useState<string | null>(null)
  const [notesOpen, setNotesOpen]           = useState(false)

  const [isLoading, setIsLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState('')
  const [resultsData, setResultsData] = useState<ResultsData | null>(null)
  const [clauses, setClauses] = useState<ClauseResult[]>([])
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false)
  const [isDiscarding, setIsDiscarding] = useState(false)
  const [discardError, setDiscardError] = useState('')
  const discardRequestKey = useRef<string | null>(null)

  useEffect(() => {
    let isSubscribed = true
    const controller = new AbortController()
    setIsLoading(true)
    setErrorMessage('')

    if (!reviewId) {
      setIsLoading(false)
      return
    }

    api.getResults(reviewId, controller.signal).then(res => {
      if (!isSubscribed) return
      if (res.data.review.mcp_review_status !== 'OK') {
        throw new Error('검토가 정상 완료 상태가 아니어서 결과를 표시할 수 없습니다.')
      }
      setResultsData(res.data)
      
      // Map API response to UI ClauseResult format
      const mappedClauses = res.data.clause_results.map(mapClauseResult)
      
      setClauses(mappedClauses)
      setIsLoading(false)
    }).catch((error) => {
      if (!isSubscribed) return
      setIsLoading(false)
      if (error?.status === 404 || error?.status === 410) {
        localStorage.removeItem(SESSION_ID_KEY)
        localStorage.removeItem(REVIEW_ID_KEY)
        sessionStorage.removeItem(getChatHistoryStorageKey(reviewId))
        setErrorMessage('검토 결과를 찾을 수 없거나 보관 기간이 만료되었습니다.')
      } else if (error?.status === 409) {
        onReviewInProgress?.()
      } else {
        setErrorMessage(getErrorMessage(error, '검토 결과를 불러오지 못했습니다.'))
      }
    })

    return () => {
      isSubscribed = false
      controller.abort()
    }
  }, [reviewId])

  const filtered = clauses.filter(c => {
    const matchStatus = filterStatus === 'all' || c.status === filterStatus
    const matchCat    = filterCategory === '전체' || c.category === filterCategory
    const matchSearch = !search || c.article.includes(search) || c.excerpt.includes(search) || c.summary.includes(search)
    return matchStatus && matchCat && matchSearch
  })

  const resetFilters = () => { setFilterStatus('all'); setFilterCategory('전체'); setSearch('') }
  const hasFilter = filterStatus !== 'all' || filterCategory !== '전체' || search !== ''

  const discardReview = async () => {
    if (!reviewId || isDiscarding) return
    setIsDiscarding(true)
    setDiscardError('')
    try {
      const key = discardRequestKey.current ?? createClientId()
      discardRequestKey.current = key
      await api.deleteReview(reviewId, key)
      discardRequestKey.current = null
      localStorage.removeItem(SESSION_ID_KEY)
      localStorage.removeItem(REVIEW_ID_KEY)
      sessionStorage.removeItem(getChatHistoryStorageKey(reviewId))
      window.location.assign('/review')
    } catch (error: any) {
      if (error?.status === 404 || error?.status === 410) {
        localStorage.removeItem(SESSION_ID_KEY)
        localStorage.removeItem(REVIEW_ID_KEY)
        sessionStorage.removeItem(getChatHistoryStorageKey(reviewId))
        window.location.assign('/review')
        return
      }
      setDiscardError(getErrorMessage(error, '검토 결과를 폐기하지 못했습니다. 다시 시도해 주세요.'))
    } finally {
      setIsDiscarding(false)
    }
  }

  if (isLoading) {
    return (
      <div className="mx-auto w-full space-y-6 animate-pulse">
        {/* 실제 헤더와 같은 형태 */}
        <div className="flex items-center justify-between gap-4">
          <div className="space-y-2">
            <div className="h-8 w-56 rounded-lg bg-slate-200/70" />
            <div className="h-4 w-72 rounded-md bg-slate-100" />
          </div>
          <div className="h-10 w-40 rounded-full bg-slate-100" />
        </div>
      
        <div className="h-10 rounded-lg bg-slate-100" />
      
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="min-h-36 rounded-2xl border border-slate-100 bg-white p-5"
            >
              <div className="h-4 w-24 rounded bg-slate-100" />
              <div className="mt-6 h-9 w-12 rounded-md bg-slate-200/70" />
            </div>
          ))}
        </div>
      
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-48 rounded-2xl border border-slate-100 bg-white"
            />
          ))}
        </div>
      </div>
    )
  }

  if (!resultsData) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center shadow-sm">
        <p className="text-slate-600">{errorMessage || '검토 결과를 불러올 수 없습니다.'}</p>
        <button
          type="button"
          onClick={() => window.location.assign('/review')}
          className="mt-4 min-h-11 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/20"
        >
          새 검토 시작
        </button>
      </div>
    )
  }

  // Generate SUMMARY based on actual data
  const summaryCounts = resultsData.summary.clause_results
  const contractTypeLabel = getMetadataLabel(
    metadata?.contract_types,
    resultsData.review.contract_type,
    '계약 유형',
  )
  const uiSummary = [
    { status: 'NONE' as ResultCode,  count: summaryCounts.NONE || 0,  label: getMetadataLabel(resultCodeDetails, 'NONE', '대응 표준조항 있음'),   text: 'text-slate-700', dot: 'bg-emerald-500' },
    { status: 'EXTRA' as ResultCode, count: summaryCounts.EXTRA || 0,  label: getMetadataLabel(resultCodeDetails, 'EXTRA', '추가·변형 내용 확인'),  text: 'text-amber-700',   dot: 'bg-amber-500' },
    { status: 'NO_MATCH' as ResultCode,   count: summaryCounts.NO_MATCH || 0,  label: getMetadataLabel(resultCodeDetails, 'NO_MATCH', '대응 조항 확인 필요'),  text: 'text-slate-700',    dot: 'bg-rose-400' },
    { status: 'MISSING' as ResultCode,  count: resultsData.summary.missing_standard_clauses || 0,  label: getMetadataLabel(resultCodeDetails, 'MISSING', '포함 여부 확인 필요'),  text: 'text-slate-600',   dot: 'bg-slate-400' },
  ]
  const toxicCandidates = clauses.flatMap(clause =>
    (clause.toxic_patterns ?? []).map(pattern => ({ clause, pattern })),
  )

  return (
    <div className="space-y-6">
      {/* Title row */}
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-2xl font-bold leading-tight tracking-[-0.025em] text-slate-950 sm:text-3xl">
              계약서 검토 결과
            </h1>

            <span className="inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium tracking-wide text-slate-400">
              Workshield Analysis
            </span>
          </div>

          <p className="mt-2 text-sm font-normal text-slate-500">
            {contractTypeLabel} 기준
            <span className="mx-1.5 text-slate-300">·</span>
            {resultsData.review.completed_at
              ? new Date(resultsData.review.completed_at).toLocaleDateString()
              : '완료 시각 확인 중'}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {metadata?.features.chat && <button
            type="button"
            onClick={onChatbot}
            className="
              inline-flex h-10 shrink-0 items-center justify-center gap-2 self-start
              rounded-xl bg-blue-600 px-4
              text-sm font-semibold text-white shadow-sm
              transition-colors duration-150
              hover:bg-blue-700
              focus-visible:outline-none focus-visible:ring-4
              focus-visible:ring-blue-500/15
              sm:self-auto
            "
          >
            <MessageSquare className="size-4" aria-hidden="true" />
            결과 기반 질의응답
          </button>}
          {metadata?.features.server_side_cancel && (
            <button
              type="button"
              onClick={() => {
                setDiscardError('')
                setShowDiscardConfirm(true)
              }}
              className="inline-flex h-10 items-center gap-2 rounded-full border border-rose-200 px-4 text-sm font-medium text-rose-700 hover:bg-rose-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-rose-500/15"
            >
              <Trash2 className="size-4" />
              검토 결과 폐기
            </button>
          )}
        </div>
      </div>

      {/* Disclaimer */}
      <div
        role="note"
        className="inline-flex w-fit max-w-full items-start gap-2 px-1"
      >
        <AlertTriangle
          className="mt-0.5 size-3.5 shrink-0 text-amber-500"
          aria-hidden="true"
        />

        <p className="text-xs leading-5 text-slate-500">
          표준계약서 대비 검토 후보이며
          <span className="ml-1 font-semibold text-slate-600">
            법률 자문이 아닙니다.
          </span>
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {uiSummary.map(s => (
          <button
            key={s.status}
            onClick={() => {
              if (s.status === 'MISSING') {
                setNotesOpen(true)
                setFilterStatus('all')
              } else {
                setFilterStatus(s.status)
              }
            }}
            className={`group relative min-h-24 overflow-hidden rounded-xl border bg-white p-4 text-left shadow-[0_1px_2px_rgba(15,23,42,0.03)] transition-all duration-200 hover:border-blue-300 hover:shadow-sm focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15 ${
              filterStatus === s.status
                ? 'border-blue-400 bg-blue-50/20 ring-2 ring-blue-500/10 before:absolute before:inset-y-4 before:left-0 before:w-1 before:rounded-r-full before:bg-blue-600'
                : 'border-slate-200/80'
            }`}
          >
            <div className="flex items-center justify-between gap-3">
              <p className={`text-xs font-semibold leading-5 ${s.text}`}>
                {s.label}
              </p>

              <span
                className={`size-2 shrink-0 rounded-full ${s.dot} ring-4 ring-current/10`}
                aria-hidden="true"
              />
            </div>

            <div className="mt-3 flex items-end justify-between">
              <p className="tabular-nums text-2xl font-semibold leading-none tracking-[-0.04em] text-slate-950">
                {s.count}
              </p>

              <span className="mb-1 text-xs font-medium text-slate-500">
                조항
              </span>
            </div>
          </button>
        ))}
      </div>

      <section aria-label="조항별 검토 결과" className="space-y-4">
          {/* Filter bar */}
          <div className="space-y-3 border-y border-slate-200/80 py-4">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="text"
                placeholder="조항명, 키워드로 검색"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="h-11 w-full rounded-xl border border-slate-200 bg-slate-50 pl-10 pr-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-400 hover:border-slate-300 focus:border-blue-500 focus:bg-white focus:ring-4 focus:ring-blue-500/10"
              />
            </div>
            {/* Filters row */}
            <div className="flex items-center gap-3 flex-wrap">
              <SlidersHorizontal className="w-3.5 h-3.5 text-slate-600 shrink-0" />
              <div className="flex gap-1.5 flex-wrap">
                {statuses.map(s => (
                  <button
                    key={s.id}
                    onClick={() => setFilterStatus(s.id as ResultCode | 'all')}
                    className={`min-h-9 rounded-full px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15 ${
                      filterStatus === s.id
                        ? 'bg-blue-600 text-white'
                        : 'bg-slate-50 border border-slate-200 text-slate-600 hover:border-slate-300'
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
              <div className="h-4 w-px bg-slate-200" />
              <select
                value={filterCategory}
                onChange={e => setFilterCategory(e.target.value)}
                className="min-h-9 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600 outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-500/10"
              >
                {categories.map(c => <option key={c}>{c}</option>)}
              </select>
              {hasFilter && (
                <button onClick={resetFilters} className="ml-auto flex min-h-9 items-center gap-1 rounded-lg px-2 text-xs text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15">
                  <RotateCcw className="w-3 h-3" />
                  필터 초기화
                </button>
              )}
            </div>
          </div>

          {/* Clause cards */}
          {filtered.length > 0 ? (
            <div className="space-y-3">
              {filtered.map(c => {
                const visual = CLAUSE_VISUALS[c.status]
            
                return (
                  <article
                    key={c.id}
                    className={`
                      group relative overflow-hidden rounded-2xl border border-slate-200/80
                      bg-white p-5
                      transition-[border-color,box-shadow,background-color] duration-200
                      before:absolute before:inset-y-0 before:left-0 before:w-1
                      ${visual.accent} ${visual.hover}
                      motion-safe:hover:-translate-y-px
                      hover:shadow-sm
                      sm:p-6
                    `}
                  >
                    {/* Subtle status gradient */}
                    <div
                      className={`
                        pointer-events-none absolute inset-0
                        bg-gradient-to-r ${visual.gradient} via-transparent to-transparent
                        opacity-40 transition-opacity duration-200 group-hover:opacity-60
                      `}
                      aria-hidden="true"
                    />
            
                    <div className="relative">
                      {/* Status row */}
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge code={c.status} label={getMetadataLabel(resultCodeDetails, c.status, '검토 결과')} />
            
                          <span className="
                            rounded-md border border-slate-200 bg-white/75
                            px-2 py-0.5 text-xs font-medium text-slate-500
                            backdrop-blur-sm
                          ">
                            {c.category}
                          </span>
            
                          {c.toxic_patterns && c.toxic_patterns.length > 0 && (
                            <span className="
                              rounded-full border border-rose-200 bg-rose-50
                              px-2.5 py-0.5 text-xs font-semibold text-rose-700
                            ">
                              🚨 주의 신호 포함
                            </span>
                          )}
                        </div>
                      </div>
            
                      {/* Clause title */}
                      <h3 className="
                        mt-4 text-[15px] font-semibold leading-6
                        tracking-[-0.015em] text-slate-950
                      ">
                        {c.article}
                      </h3>
            
                      {/* Original clause */}
                      <blockquote className="mt-2 line-clamp-2 text-sm leading-6 tracking-[-0.005em] text-slate-500">
                        "{c.excerpt}"
                      </blockquote>
            
                      {/* Analysis */}
                      <p className="mt-3 break-keep text-sm leading-6 tracking-[-0.005em] text-slate-700">
                        {c.summary}
                      </p>
            
                      {/* Action */}
                      <div className="mt-4 flex justify-end">
                        <button
                          onClick={() => onClauseClick(c)}
                          className="
                            inline-flex items-center gap-1 rounded-lg px-2 py-1
                            text-sm font-semibold text-blue-600
                            transition-colors hover:bg-blue-50 hover:text-blue-700
                            focus-visible:outline-none focus-visible:ring-4
                            focus-visible:ring-blue-500/15
                          "
                        >
                          상세 분석 보기
                          <ChevronRight className="size-4" />
                        </button>
                      </div>
                    </div>
                  </article>
                )
              })}
            </div>
          ) : (
            <div className="bg-white border border-slate-200 rounded-xl p-12 text-center">
              <p className="text-sm font-medium text-slate-600 mb-1">현재 비교 결과가 생성되지 않았습니다</p>
              <p className="text-xs text-slate-500">필터를 변경하거나 초기화해 보세요</p>
              <button onClick={resetFilters} className="mt-4 min-h-9 rounded-lg px-3 text-xs font-medium text-blue-600 hover:bg-blue-50 hover:underline focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15">
                필터 초기화
              </button>
            </div>
          )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white" aria-label="추가 확인 항목">
        <button type="button" onClick={() => setNotesOpen(open => !open)} aria-expanded={notesOpen} className="flex min-h-14 w-full items-center justify-between px-5 text-left focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-blue-500/15">
          <span><span className="block text-sm font-semibold text-slate-900">추가 확인 항목</span><span className="mt-0.5 block text-xs text-slate-500">주의 문구 후보와 포함 여부 체크리스트</span></span>
          {notesOpen ? <ChevronUp className="size-5 text-slate-500" /> : <ChevronDown className="size-5 text-slate-500" />}
        </button>
        {notesOpen && <div className="space-y-6 border-t border-slate-200 p-5">
          <div>
            <div className="mb-4 flex items-center gap-2">
              <AlertTriangle className="size-4 text-amber-500" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-slate-900">주의 문구 후보</h2>
              <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
                {toxicCandidates.length}건
              </span>
            </div>
            {toxicCandidates.length > 0 ? (
              <div className="space-y-2">
                {toxicCandidates.map(({ clause, pattern }) => (
                  <button
                    type="button"
                    key={`${clause.id}-${pattern.code}`}
                    onClick={() => onClauseClick(clause)}
                    className="flex min-h-11 w-full items-center justify-between rounded-xl border border-amber-200 bg-amber-50/40 px-4 py-3 text-left hover:bg-amber-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-amber-500/15"
                  >
                    <span>
                      <span className="block text-sm font-semibold text-amber-900">{pattern.label}</span>
                      <span className="mt-0.5 block text-xs text-slate-600">{clause.article} · {clause.category}</span>
                    </span>
                    <ChevronRight className="size-4 text-amber-600" />
                  </button>
                ))}
              </div>
            ) : (
              <p className="rounded-xl border border-slate-200 bg-white p-4 text-xs text-slate-500">
                탐지된 주의 문구 후보가 없습니다. 이 결과만으로 계약이 안전하다고 판단할 수는 없습니다.
              </p>
            )}
          </div>
          {/* Missing checklist */}
          <div>
            <div className="flex items-center gap-2 mb-4">
              <CheckSquare className="w-4 h-4 text-slate-500" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-slate-900">포함 여부 체크리스트</h2>
              <span className="text-xs text-slate-600 bg-blue-50 border border-slate-300 text-slate-600 px-2 py-0.5 rounded-full font-medium">
                {resultsData.missing_standard_clauses.length}건
              </span>
            </div>
            <p className="text-xs text-slate-600 mb-4 leading-relaxed">
              표준계약서에서 확인해 볼 항목을 체크리스트로 정리했습니다. 문서에 포함되어 있는지 직접 확인해 주세요.
            </p>
            <div className="space-y-2">
              {resultsData.missing_standard_clauses.map((item, index) => {
                const missingKey = `${item.standard.category.code}:${item.standard.title}:${index}`
                const open = expandedMissing === missingKey
                return (
                  <div key={missingKey} className="bg-slate-50 border border-slate-300 rounded-xl overflow-hidden">
                    <button
                      onClick={() => setExpandedMissing(open ? null : missingKey)}
                      className="flex min-h-11 w-full items-center gap-3 px-5 py-4 text-left transition-colors hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-blue-500/15"
                      aria-expanded={open}
                    >
                      <div className="w-4 h-4 rounded border-2 border-[#94A3B8] shrink-0 flex items-center justify-center" aria-hidden="true" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-slate-900">{item.standard.title}</p>
                        <p className="mt-1 text-xs text-slate-600">{getStandardContractLabel(item.standard.standard_contract_label)}</p>
                      </div>
                      {open ? <ChevronUp className="w-4 h-4 text-slate-500 shrink-0" /> : <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />}
                    </button>
                    {open && (
                      <div className="px-5 pb-5 border-t border-slate-200">
                        <p className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wider text-slate-600">표준조항 원문</p>
                        <p className="text-xs text-slate-600 leading-relaxed bg-white border border-slate-200 rounded-lg px-4 py-3 font-mono">
                          {item.standard.text}
                        </p>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </div>}
      </section>
      {showDiscardConfirm && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4" role="dialog" aria-modal="true" aria-labelledby="discard-title">
          <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl">
            <h2 id="discard-title" className="text-lg font-bold text-slate-950">검토 결과를 폐기할까요?</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              검토 결과와 임시 계약서 파일이 삭제되며 되돌릴 수 없습니다.
            </p>
            {discardError && <p className="mt-3 text-sm text-rose-600" role="alert">{discardError}</p>}
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowDiscardConfirm(false)}
                disabled={isDiscarding}
                className="min-h-10 rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15 disabled:opacity-50"
              >
                취소
              </button>
              <button
                type="button"
                onClick={discardReview}
                disabled={isDiscarding}
                className="inline-flex min-h-10 items-center gap-2 rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-rose-500/20 disabled:opacity-50"
              >
                {isDiscarding && <Loader2 className="size-4 animate-spin" />}
                {isDiscarding ? '폐기 중' : '폐기'}
              </button>
            </div>
          </div>
        </div>)}
    </div>
  )
}
