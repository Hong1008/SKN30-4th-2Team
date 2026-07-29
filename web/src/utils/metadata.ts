import type { MetaCodeLabel, StatusPresentation } from '../types'

export function getMetadataLabel(
  items: readonly MetaCodeLabel[] | null | undefined,
  code: string | null | undefined,
  fallback: string,
): string {
  if (!code) return fallback
  return items?.find((item) => item.code === code)?.label || fallback
}

export function getStatusPresentation(
  items: readonly StatusPresentation[] | null | undefined,
  code: string | null | undefined,
): StatusPresentation | undefined {
  if (!code) return undefined
  return items?.find((item) => item.code === code)
}
