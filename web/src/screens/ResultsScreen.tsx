import { useState, useEffect } from 'react'
import { Search, SlidersHorizontal, MessageSquare, ChevronRight, RotateCcw, ChevronDown, ChevronUp, AlertTriangle, CheckSquare, Loader2 } from 'lucide-react'
import Badge from '../components/Badge'
import type { ResultCode, ClauseResult, ResultsData } from '../types'
import { api } from '../api/api'
import { useMetadata } from '../contexts/MetadataContext'

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
}

export default function ResultsScreen({ reviewId, onClauseClick, onChatbot }: Props) {
  const { metadata } = useMetadata()
  const categories = ['전체', ...(metadata?.categories.map(c => c.label) || [])]
  const statuses: { id: ResultCode | 'all'; label: string }[] = [
    { id: 'all', label: '전체' },
    ...(metadata?.result_codes.map(r => ({ id: r.code as ResultCode, label: r.label })) || [])
  ]
  const [filterStatus, setFilterStatus]     = useState<ResultCode | 'all'>('all')
  const [filterCategory, setFilterCategory] = useState('전체')
  const [search, setSearch]                 = useState('')
  const [expandedMissing, setExpandedMissing] = useState<string | null>(null)
  const [expandedNote, setExpandedNote]     = useState<string | null>(null)
  const [activeTab, setActiveTab]           = useState<'results' | 'notes'>('results')

  const [isLoading, setIsLoading] = useState(true)
  const [resultsData, setResultsData] = useState<ResultsData | null>(null)
  const [clauses, setClauses] = useState<ClauseResult[]>([])

  useEffect(() => {
    let isSubscribed = true
    setIsLoading(true)

    if (!reviewId) {
      setIsLoading(false)
      return
    }

    api.getResults(reviewId).then(res => {
      if (!isSubscribed) return
      setResultsData(res.data)
      
      // Map API response to UI ClauseResult format
      const mappedClauses: ClauseResult[] = res.data.clause_results.map((c: any) => {
        let status: ResultCode = 'NO_MATCH'
        if (c.deviation.code === 'NONE') status = 'NONE'
        if (c.deviation.code === 'EXTRA') status = 'EXTRA'
        if (c.deviation.code === 'NO_MATCH') status = 'NO_MATCH'
        if (c.deviation.code === 'MISSING') status = 'MISSING'

        return {
          id: c.user_clause_id,
          article: c.user_clause.split(' ')[0] || '조항', // e.g. "제1조"
          excerpt: c.user_clause, // full text as excerpt for now
          status,
          category: c.match?.standard?.category?.label || '기타',
          categoryCode: c.match?.standard?.category?.code,
          summary: c.explanation,
          toxic_patterns: c.toxic_patterns || [],
          standardTitle: c.match?.standard?.title,
          standardText: c.match?.standard?.text,
          standardSource: c.match?.standard?.source
        }
      })
      
      setClauses(mappedClauses)
      setIsLoading(false)
    }).catch(() => {
      if (!isSubscribed) return
      setIsLoading(false)
      // Error handling can be added
    })

    return () => { isSubscribed = false }
  }, [reviewId])

  const filtered = clauses.filter(c => {
    const matchStatus = filterStatus === 'all' || c.status === filterStatus
    const matchCat    = filterCategory === '전체' || c.category === filterCategory
    const matchSearch = !search || c.article.includes(search) || c.excerpt.includes(search) || c.summary.includes(search)
    return matchStatus && matchCat && matchSearch
  })

  const resetFilters = () => { setFilterStatus('all'); setFilterCategory('전체'); setSearch('') }
  const hasFilter = filterStatus !== 'all' || filterCategory !== '전체' || search !== ''

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
      <div className="text-center py-20">
        <p className="text-slate-600">검토 결과를 불러올 수 없습니다.</p>
      </div>
    )
  }

  // Generate SUMMARY based on actual data
  const summaryCounts = resultsData.summary.clause_results
  const uiSummary = [
    { status: 'NONE' as ResultCode,  count: summaryCounts.NONE || 0,  label: metadata?.result_codes.find(r => r.code === 'NONE')?.label || '대응 표준조항 있음',   text: 'text-emerald-700', dot: 'bg-emerald-500' },
    { status: 'EXTRA' as ResultCode, count: summaryCounts.EXTRA || 0,  label: metadata?.result_codes.find(r => r.code === 'EXTRA')?.label || '추가·변형 내용 확인',  text: 'text-amber-700',   dot: 'bg-amber-500' },
    { status: 'NO_MATCH' as ResultCode,   count: summaryCounts.NO_MATCH || 0,  label: metadata?.result_codes.find(r => r.code === 'NO_MATCH')?.label || '대응 조항 확인 필요',  text: 'text-rose-700',    dot: 'bg-rose-500' },
    { status: 'MISSING' as ResultCode,  count: resultsData.summary.missing_standard_clauses || 0,  label: metadata?.result_codes.find(r => r.code === 'MISSING')?.label || '포함 여부 확인 필요',  text: 'text-slate-600',   dot: 'bg-slate-400' },
  ]

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

          <p className="mt-2 text-sm font-normal text-slate-400">
            근로계약서 ({resultsData.review.contract_type}) 기준
            <span className="mx-1.5 text-slate-300">·</span>
            {new Date(resultsData.review.completed_at).toLocaleDateString()}
          </p>
        </div>

        <button
          type="button"
          onClick={onChatbot}
          className="
            inline-flex h-10 shrink-0 items-center justify-center gap-2 self-start
            rounded-full border border-slate-200 bg-transparent px-4
            text-sm font-medium text-slate-600
            transition-colors duration-150
            hover:border-blue-200 hover:bg-blue-50/60 hover:text-blue-700
            focus-visible:outline-none focus-visible:ring-4
            focus-visible:ring-blue-500/15
            sm:self-auto
          "
        >
          <MessageSquare className="size-4" aria-hidden="true" />
          결과 기반 질의응답
        </button>
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

        <p className="text-xs leading-5 text-slate-400">
          표준계약서 대비 검토 후보이며
          <span className="ml-1 font-semibold text-slate-600">
            법률 자문이 아닙니다.
          </span>
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {uiSummary.map(s => (
          <button
            key={s.status}
            onClick={() => setFilterStatus(s.status)}
            className={`group relative min-h-36 overflow-hidden rounded-2xl border bg-white/90 p-5 text-left shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.04)] backdrop-blur-xl transition-all duration-200 hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-[0_12px_32px_rgba(37,99,235,0.10)] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15 ${
              filterStatus === s.status
                ? 'border-blue-500 bg-blue-50/40 ring-1 ring-blue-500/20 before:absolute before:inset-y-4 before:left-0 before:w-1 before:rounded-r-full before:bg-blue-600'
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

            <div className="mt-5 flex items-end justify-between">
              <p className="tabular-nums text-[34px] font-bold leading-none tracking-[-0.04em] text-slate-950">
                {s.count}
              </p>

              <span className="text-[11px] font-medium text-slate-400 mb-1">
                조항
              </span>
            </div>
          </button>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-200">
        {([['results', '조항별 검토 결과'], ['notes', '주의 문구 후보 및 누락 체크리스트']] as const).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
              activeTab === id
                ? 'border-blue-600 text-slate-900'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'results' && (
        <>
          {/* Filter bar */}
          <div className="sticky top-[84px] z-20 space-y-3 rounded-2xl border border-slate-200/80 bg-white/90 p-4 shadow-sm backdrop-blur-xl">
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
                    className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
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
                className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-slate-50 text-slate-600 focus:outline-none focus:border-blue-600"
              >
                {categories.map(c => <option key={c}>{c}</option>)}
              </select>
              {hasFilter && (
                <button onClick={resetFilters} className="flex items-center gap-1 text-xs text-slate-600 hover:text-slate-900 transition-colors ml-auto">
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
                      bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03)]
                      transition-[border-color,box-shadow,background-color] duration-200
                      before:absolute before:inset-y-0 before:left-0 before:w-1
                      ${visual.accent} ${visual.hover}
                      motion-safe:hover:-translate-y-px
                      hover:shadow-[0_8px_24px_rgba(15,23,42,0.06)]
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
                          <Badge code={c.status} label={metadata?.result_codes.find(r => r.code === c.status)?.label || ''} />
            
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
                      <blockquote className="
                        my-4 rounded-xl border border-slate-200/80 bg-white/65
                        px-4 py-3 text-sm leading-6 tracking-[-0.005em]
                        text-slate-600 backdrop-blur-sm line-clamp-3
                      ">
                        "{c.excerpt}"
                      </blockquote>
            
                      {/* Analysis */}
                      <p className="
                        break-keep text-sm leading-6
                        tracking-[-0.005em] text-slate-600
                      ">
                        {c.summary}
                      </p>
            
                      {/* Action */}
                      <div className="mt-5 flex justify-end border-t border-slate-200/70 pt-4">
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
              <button onClick={resetFilters} className="mt-4 text-xs font-medium text-blue-600 hover:underline">
                필터 초기화
              </button>
            </div>
          )}
        </>
      )}

      {activeTab === 'notes' && (
        <div className="space-y-6">
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
              {resultsData.missing_standard_clauses.map((item: any) => {
                const open = expandedMissing === item.standard.clause_id
                return (
                  <div key={item.standard.clause_id} className="bg-slate-50 border border-slate-300 rounded-xl overflow-hidden">
                    <button
                      onClick={() => setExpandedMissing(open ? null : item.standard.clause_id)}
                      className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-blue-50 transition-colors"
                      aria-expanded={open}
                    >
                      <div className="w-4 h-4 rounded border-2 border-[#94A3B8] shrink-0 flex items-center justify-center" aria-hidden="true" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-slate-900">{item.standard.title}</p>
                        <p className="text-[11px] text-slate-600 mt-0.5">{item.standard.source}</p>
                      </div>
                      {open ? <ChevronUp className="w-4 h-4 text-slate-500 shrink-0" /> : <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />}
                    </button>
                    {open && (
                      <div className="px-5 pb-5 border-t border-slate-200">
                        <p className="text-[11px] font-semibold text-slate-600 uppercase tracking-wider mt-4 mb-2">표준조항 원문</p>
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
        </div>
      )}
    </div>
  )
}
