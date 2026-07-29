import { BookOpen } from 'lucide-react'

export type SourceReferenceType = 'USER_CLAUSE' | 'STANDARD_CLAUSE' | 'LAW'

export interface SourceReference {
  type: SourceReferenceType
  display_label?: string | null
  clause_number?: string | null
  title?: string | null
  category?: string | null
  standard_contract_label?: string | null
  law_name?: string | null
  article?: string | null
}

function safeText(value: string | null | undefined): string | null {
  const normalized = value?.trim()
  return normalized || null
}

export function getSourceLabel(source: SourceReference): string {
  const displayLabel = safeText(source.display_label)
  if (source.type === 'LAW') {
    const lawLabel = [safeText(source.law_name), safeText(source.article)].filter(Boolean).join(' ')
    return lawLabel || '법령 근거'
  }
  if (source.type === 'STANDARD_CLAUSE' && displayLabel) {
    return [safeText(source.standard_contract_label), displayLabel].filter(Boolean).join(' · ')
  }
  if (displayLabel) return displayLabel
  const clauseLabel = [
    safeText(source.clause_number),
    safeText(source.title),
    safeText(source.category),
  ].filter(Boolean).join(' · ')
  if (clauseLabel) return clauseLabel
  return source.type === 'USER_CLAUSE' ? '현재 검토 조항' : '대응 표준조항'
}

export default function SourceReferences({ sources, title = '출처' }: { sources: SourceReference[]; title?: string }) {
  if (sources.length === 0) return null
  return (
    <div className="mt-3 border-t border-slate-200 pt-2">
      <p className="mb-1 text-xs font-semibold text-slate-500">{title}</p>
      <div className="flex flex-wrap gap-1.5">
        {sources.map((source, index) => {
          const label = getSourceLabel(source)
          return <span key={`${source.type}-${index}`} className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600"><BookOpen className="size-3" aria-hidden="true" />{label}</span>
        })}
      </div>
    </div>
  )
}
