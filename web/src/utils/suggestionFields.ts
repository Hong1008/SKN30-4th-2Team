const SUGGESTION_FIELD_LABELS: Record<string, string> = {
  law_grounding: '법령 근거 확인',
  user_clause_id: '검토 대상 조항',
  liability_limit: '책임 한도',
}

export function getSuggestionFieldLabel(field: string): string {
  return SUGGESTION_FIELD_LABELS[field] || '추가 확인 정보'
}
