import type { ResultCode } from '../types'

interface Props {
  code: ResultCode
  label: string
  size?: 'sm' | 'md'
}

const CONFIG: Record<ResultCode, { dot: string; bg: string; text: string; border: string }> = {
  NONE: {
    dot: 'bg-emerald-500',
    bg: 'bg-white',
    text: 'text-slate-700',
    border: 'border-slate-200',
  },
  EXTRA: {
    dot: 'bg-amber-500',
    bg: 'bg-amber-50',
    text: 'text-amber-700',
    border: 'border-amber-200',
  },
  NO_MATCH: {
    dot: 'bg-rose-400',
    bg: 'bg-white',
    text: 'text-slate-700',
    border: 'border-slate-200',
  },
  MISSING: {
    dot: 'bg-slate-400',
    bg: 'bg-slate-100',
    text: 'text-slate-600',
    border: 'border-slate-200',
  },
}

export default function Badge({ code, label, size = 'md' }: Props) {
  const c = CONFIG[code]
  return (
    <span
      className={`inline-flex items-center gap-1.5 font-medium border rounded-full ${c.bg} ${c.text} ${c.border} ${
        size === 'sm' ? 'text-[11px] px-2 py-0.5' : 'text-xs px-2.5 py-1'
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${c.dot}`} aria-hidden="true" />
      {label}
    </span>
  )
}
