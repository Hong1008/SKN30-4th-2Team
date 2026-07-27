import { useState, useEffect } from 'react'
import { Search, SlidersHorizontal, MessageSquare, ChevronRight, RotateCcw, ChevronDown, ChevronUp, AlertTriangle, CheckSquare, Loader2 } from 'lucide-react'
import Badge from '../components/Badge'
import type { BadgeStatus, ClauseResult } from '../types'
import { mockApi } from '../api/mockApi'
import { ResultsData } from '../types'

interface Props {
  reviewId: string | null;
  onClauseClick: () => void
  onChatbot: () => void
}

const CATEGORIES = ['전체', '계약 기간', '근무조건', '임금', '휴가·휴일', '비밀유지·경업', '손해배상']
const STATUSES: { id: BadgeStatus | 'all'; label: string }[] = [
  { id: 'all', label: '전체' },
  { id: 'matched', label: '대응 조항 있음' },
  { id: 'modified', label: '추가·변형 확인' },
  { id: 'review', label: '조항 확인 필요' },
  { id: 'missing', label: '포함 여부 확인' },
]

export default function ResultsScreen({ reviewId, onClauseClick, onChatbot }: Props) {
  const [filterStatus, setFilterStatus]     = useState<BadgeStatus | 'all'>('all')
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

    // Fallback ID for demo nav when no actual review process was run
    const activeReviewId = reviewId || 'rev_mock_456'

    mockApi.getResults(activeReviewId).then(res => {
      if (!isSubscribed) return
      setResultsData(res.data)
      
      // Map API response to UI ClauseResult format
      const mappedClauses: ClauseResult[] = res.data.clause_results.map((c: any) => {
        let status: BadgeStatus = 'review'
        if (c.deviation.code === 'NONE') status = 'matched'
        if (c.deviation.code === 'EXTRA') status = 'modified'
        if (c.deviation.code === 'NO_MATCH') status = 'review'

        return {
          id: c.user_clause_id,
          article: c.user_clause.split(' ')[0] || '조항', // e.g. "제1조"
          excerpt: c.user_clause, // full text as excerpt for now
          status,
          category: c.match?.standard?.category?.label || '기타',
          summary: c.explanation,
          toxic_patterns: c.toxic_patterns || []
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
      <div className="flex flex-col items-center justify-center py-20 space-y-4">
        <Loader2 className="w-8 h-8 text-[#6366F1] animate-spin" />
        <p className="text-sm font-medium text-[#475569]">결과를 불러오는 중입니다...</p>
      </div>
    )
  }

  if (!resultsData) {
    return (
      <div className="text-center py-20">
        <p className="text-[#475569]">검토 결과를 불러올 수 없습니다.</p>
      </div>
    )
  }

  // Generate SUMMARY based on actual data
  const summaryCounts = resultsData.summary.clause_results
  const uiSummary = [
    { status: 'matched' as BadgeStatus,  count: summaryCounts.NONE || 0,  label: '대응 표준조항 있음',   bg: 'bg-emerald-50',  border: 'border-emerald-200', text: 'text-emerald-700', num: 'text-emerald-600' },
    { status: 'modified' as BadgeStatus, count: summaryCounts.EXTRA || 0,  label: '추가·변형 내용 확인',  bg: 'bg-amber-50',    border: 'border-amber-200',   text: 'text-amber-700',   num: 'text-amber-600' },
    { status: 'review' as BadgeStatus,   count: summaryCounts.NO_MATCH || 0,  label: '대응 조항 확인 필요',  bg: 'bg-rose-50',     border: 'border-rose-200',    text: 'text-rose-700',    num: 'text-rose-600' },
    { status: 'missing' as BadgeStatus,  count: resultsData.summary.missing_standard_clauses || 0,  label: '포함 여부 확인 필요',  bg: 'bg-slate-100',   border: 'border-slate-200',   text: 'text-[#475569]',   num: 'text-[#475569]' },
  ]

  return (
    <div className="space-y-6 animate-fade-up">
      {/* Title row */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-[22px] font-semibold text-[#1E293B] tracking-tight mb-1">계약서 검토 결과</h1>
          <p className="text-sm text-[#475569]">근로계약서 ({resultsData.review.contract_type}) 기준 · {new Date(resultsData.review.completed_at).toLocaleDateString()}</p>
        </div>
        <button
          onClick={onChatbot}
          className="flex items-center gap-2 px-4 py-2.5 bg-[#EEF2FF] text-[#6366F1] border border-[#C7D2FE] rounded-xl text-sm font-medium hover:bg-[#E0E7FF] transition-colors shrink-0"
        >
          <MessageSquare className="w-4 h-4" />
          결과 기반 질의응답
        </button>
      </div>

      {/* Disclaimer banner */}
      <div className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl px-5 py-4 flex items-start gap-3">
        <AlertTriangle className="w-4 h-4 text-[#475569] shrink-0 mt-0.5" aria-hidden="true" />
        <p className="text-xs text-[#475569] leading-relaxed">
          {resultsData.review.disclaimer}
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {uiSummary.map(s => (
          <button
            key={s.status}
            onClick={() => setFilterStatus(s.status)}
            className={`text-left p-4 rounded-xl border transition-all hover:shadow-sm ${s.bg} ${s.border} ${
              filterStatus === s.status ? 'ring-2 ring-[#6366F1]/40' : ''
            }`}
          >
            <p className={`text-3xl font-bold tracking-tight mb-1 ${s.num}`}>{s.count}</p>
            <p className={`text-xs font-medium leading-tight ${s.text}`}>{s.label}</p>
          </button>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[#E2E8F0]">
        {([['results', '조항별 검토 결과'], ['notes', '주의 문구 후보 및 누락 체크리스트']] as const).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
              activeTab === id
                ? 'border-[#6366F1] text-[#1E293B]'
                : 'border-transparent text-[#475569] hover:text-[#1E293B]'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'results' && (
        <>
          {/* Filter bar */}
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-4 space-y-3">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#64748B]" />
              <input
                type="text"
                placeholder="조항명, 키워드로 검색"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full pl-9 pr-4 py-2.5 bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg text-sm text-[#1E293B] placeholder:text-[#64748B] focus:outline-none focus:border-[#6366F1] focus:ring-1 focus:ring-[#6366F1]"
              />
            </div>
            {/* Filters row */}
            <div className="flex items-center gap-3 flex-wrap">
              <SlidersHorizontal className="w-3.5 h-3.5 text-[#475569] shrink-0" />
              <div className="flex gap-1.5 flex-wrap">
                {STATUSES.map(s => (
                  <button
                    key={s.id}
                    onClick={() => setFilterStatus(s.id as BadgeStatus | 'all')}
                    className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                      filterStatus === s.id
                        ? 'bg-[#6366F1] text-white'
                        : 'bg-[#F8FAFC] border border-[#E2E8F0] text-[#475569] hover:border-[#CBD5E1]'
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
              <div className="h-4 w-px bg-[#E2E8F0]" />
              <select
                value={filterCategory}
                onChange={e => setFilterCategory(e.target.value)}
                className="text-xs border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 bg-[#F8FAFC] text-[#475569] focus:outline-none focus:border-[#6366F1]"
              >
                {CATEGORIES.map(c => <option key={c}>{c}</option>)}
              </select>
              {hasFilter && (
                <button onClick={resetFilters} className="flex items-center gap-1 text-xs text-[#475569] hover:text-[#1E293B] transition-colors ml-auto">
                  <RotateCcw className="w-3 h-3" />
                  필터 초기화
                </button>
              )}
            </div>
          </div>

          {/* Clause cards */}
          {filtered.length > 0 ? (
            <div className="space-y-3">
              {filtered.map(c => (
                <div key={c.id} className="bg-white border border-[#E2E8F0] rounded-xl p-5 hover:border-[#C7D2FE] hover:shadow-sm transition-all">
                  <div className="flex items-start gap-3 justify-between flex-wrap">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge status={c.status} />
                      <span className="text-xs text-[#64748B] bg-[#F8FAFC] border border-[#E2E8F0] px-2 py-0.5 rounded">{c.category}</span>
                      {c.toxic_patterns && c.toxic_patterns.length > 0 && (
                        <span className="text-xs font-semibold text-rose-600 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded">
                          주의 신호 포함
                        </span>
                      )}
                    </div>
                    <button
                      onClick={onClauseClick}
                      className="flex items-center gap-1 text-xs font-medium text-[#6366F1] hover:text-[#1E293B] transition-colors shrink-0"
                    >
                      상세 보기 <ChevronRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <p className="text-sm font-semibold text-[#1E293B] mt-3 mb-1">{c.article}</p>
                  <p className="text-xs text-[#475569] line-clamp-2 leading-relaxed mb-3 bg-[#F8FAFC] rounded-lg px-3 py-2 border border-[#E2E8F0] font-mono">
                    "{c.excerpt}"
                  </p>
                  <p className="text-xs text-[#475569] leading-relaxed">{c.summary}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="bg-white border border-[#E2E8F0] rounded-xl p-12 text-center">
              <p className="text-sm font-medium text-[#475569] mb-1">현재 비교 결과가 생성되지 않았습니다</p>
              <p className="text-xs text-[#64748B]">필터를 변경하거나 초기화해 보세요</p>
              <button onClick={resetFilters} className="mt-4 text-xs font-medium text-[#6366F1] hover:underline">
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
              <CheckSquare className="w-4 h-4 text-[#64748B]" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-[#1E293B]">포함 여부 체크리스트</h2>
              <span className="text-xs text-[#475569] bg-[#EEF2FF] border border-[#CBD5E1] text-[#475569] px-2 py-0.5 rounded-full font-medium">
                {resultsData.missing_standard_clauses.length}건
              </span>
            </div>
            <p className="text-xs text-[#475569] mb-4 leading-relaxed">
              표준계약서에서 확인해 볼 항목을 체크리스트로 정리했습니다. 문서에 포함되어 있는지 직접 확인해 주세요.
            </p>
            <div className="space-y-2">
              {resultsData.missing_standard_clauses.map((item: any) => {
                const open = expandedMissing === item.standard.clause_id
                return (
                  <div key={item.standard.clause_id} className="bg-[#F8FAFC] border border-[#CBD5E1] rounded-xl overflow-hidden">
                    <button
                      onClick={() => setExpandedMissing(open ? null : item.standard.clause_id)}
                      className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-[#EEF2FF] transition-colors"
                      aria-expanded={open}
                    >
                      <div className="w-4 h-4 rounded border-2 border-[#94A3B8] shrink-0 flex items-center justify-center" aria-hidden="true" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-[#1E293B]">{item.standard.title}</p>
                        <p className="text-[11px] text-[#475569] mt-0.5">{item.standard.source}</p>
                      </div>
                      {open ? <ChevronUp className="w-4 h-4 text-[#64748B] shrink-0" /> : <ChevronDown className="w-4 h-4 text-[#64748B] shrink-0" />}
                    </button>
                    {open && (
                      <div className="px-5 pb-5 border-t border-[#E2E8F0]">
                        <p className="text-[11px] font-semibold text-[#475569] uppercase tracking-wider mt-4 mb-2">표준조항 원문</p>
                        <p className="text-xs text-[#475569] leading-relaxed bg-white border border-[#E2E8F0] rounded-lg px-4 py-3 font-mono">
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
