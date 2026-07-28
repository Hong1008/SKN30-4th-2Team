import type { MetaCodeLabel } from '../types'

export function getMetadataLabel(
  items: readonly MetaCodeLabel[] | null | undefined,
  code: string | null | undefined,
  fallback: string,
): string {
  if (!code) return fallback
  return items?.find((item) => item.code === code)?.label || fallback
}
