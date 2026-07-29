import { Plus, ShieldCheck } from 'lucide-react'
import { useState, useEffect } from 'react'
import type { Screen } from '../types'

interface Props {
  currentScreen: Screen
  onNavigate: (s: Screen) => void
  expiresAt: string | null
  canStartNewReview: boolean
  onStartNewReview: () => void
  isStartingNewReview: boolean
  navigationLocked?: boolean
}

export default function Header({
  currentScreen,
  onNavigate,
  expiresAt,
  canStartNewReview,
  onStartNewReview,
  isStartingNewReview,
  navigationLocked = false,
}: Props) {
  const isReview = ['upload-and-type', 'out-of-scope', 'processing'].includes(currentScreen)
  const isResult = ['results', 'clause-detail', 'chatbot'].includes(currentScreen)

  const secondsUntilExpiry = () => expiresAt
    ? Math.max(0, Math.ceil((new Date(expiresAt).getTime() - Date.now()) / 1000))
    : null
  const [timeLeft, setTimeLeft] = useState<number | null>(secondsUntilExpiry)

  useEffect(() => {
    setTimeLeft(secondsUntilExpiry())
    const interval = setInterval(() => {
      setTimeLeft(secondsUntilExpiry())
    }, 1000)

    return () => clearInterval(interval)
  }, [expiresAt])

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/90 backdrop-blur-xl">
      <div className="mx-auto flex h-[68px] max-w-[1280px] items-center px-4 sm:px-6 lg:px-8">
        {/* Logo */}
        <button
          onClick={() => onNavigate('upload-and-type')}
          disabled={navigationLocked}
          className="
            group flex shrink-0 items-center gap-2.5 rounded-xl px-1 py-1
            focus-visible:outline-none
            focus-visible:ring-4 focus-visible:ring-blue-500/15
          "
        >
          <span className="
            grid size-9 place-items-center rounded-[10px]
            bg-gradient-to-br from-blue-500 to-blue-700 text-white
            shadow-[0_4px_12px_rgba(37,99,235,0.22)]
            ring-1 ring-inset ring-white/15
            transition-transform duration-150 group-hover:-translate-y-px
          ">
            <ShieldCheck
              className="size-5 text-white"
              strokeWidth={2.15}
            />
          </span>

          <span className="flex items-baseline">
            <span className="
              text-[18px] font-bold leading-5
              tracking-[-0.035em] text-slate-950
            ">
              Work<span className="font-semibold text-blue-600">Shield</span>
            </span>
          </span>
        </button>

        {/* Nav links */}
        <nav className="ml-10 hidden items-center gap-1 md:flex">
          <button
            onClick={() => onNavigate('upload-and-type')}
            disabled={navigationLocked}
            className={`flex h-9 items-center rounded-lg px-3.5 text-[13px] font-semibold transition-colors ${
              isReview
                ? 'border border-blue-200/80 bg-blue-50 text-blue-700'
                : 'border border-transparent text-slate-600 hover:bg-slate-50 hover:text-slate-950'
            }`}
          >
            계약서 검토
          </button>
          <button
            onClick={() => onNavigate('results')}
            disabled={navigationLocked}
            className={`flex h-9 items-center rounded-lg px-3.5 text-[13px] font-semibold transition-colors ${
              isResult
                ? 'border border-blue-200/80 bg-blue-50 text-blue-700'
                : 'border border-transparent text-slate-600 hover:bg-slate-50 hover:text-slate-950'
            }`}
          >
            검토 결과
          </button>
        </nav>

        {/* Right: session */}
        <div className="ml-auto flex items-center gap-4">
          {canStartNewReview && (
            <button
              type="button"
              onClick={onStartNewReview}
              disabled={isStartingNewReview}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              <Plus className="size-4" />
              {isStartingNewReview ? '정리 중' : '새 검토'}
            </button>
          )}
          {timeLeft !== null && <div className="hidden items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 sm:flex">
            <span className={`size-1.5 rounded-full ${timeLeft > 300 ? 'bg-emerald-500' : 'bg-red-500 animate-pulse'}`} />
            <span className="text-[11px] font-medium text-slate-600 font-mono tracking-tight">
              {timeLeft > 0 ? '세션 유지 중' : '세션 만료'}
              <span className="ml-0.5">{formatTime(timeLeft)}</span>
            </span>
          </div>}
        </div>
      </div>
    </header>
  )
}
