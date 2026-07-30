export const DEFAULT_STANDARD_CONTRACT_LABEL = '표준계약서'

export function getStandardContractLabel(value: string | null | undefined): string {
  const normalized = value?.trim()
  return normalized || DEFAULT_STANDARD_CONTRACT_LABEL
}
