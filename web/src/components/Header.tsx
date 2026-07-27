import { ShieldCheck } from 'lucide-react'
import { useState, useEffect } from 'react'
import type { Screen } from '../types'

interface Props {
  currentScreen: Screen
  onNavigate: (s: Screen) => void
}

export default function Header({ currentScreen, onNavigate }: Props) {
  const isReview = ['upload', 'contract-type', 'out-of-scope', 'processing'].includes(currentScreen)
  const isResult = ['results', 'clause-detail', 'chatbot'].includes(currentScreen)

  const [timeLeft, setTimeLeft] = useState(1800) // 30 minutes in seconds

  useEffect(() => {
    // throttle the reset to avoid excessive state updates
    let timeoutId: number | null = null;
    const resetTimer = () => {
      if (!timeoutId) {
        setTimeLeft(1800)
        timeoutId = window.setTimeout(() => { timeoutId = null }, 1000)
      }
    }
    
    window.addEventListener('keydown', resetTimer)
    window.addEventListener('click', resetTimer)

    const interval = setInterval(() => {
      setTimeLeft(prev => (prev > 0 ? prev - 1 : 0))
    }, 1000)

    return () => {
      window.removeEventListener('keydown', resetTimer)
      window.removeEventListener('click', resetTimer)
      clearInterval(interval)
      if (timeoutId) clearTimeout(timeoutId)
    }
  }, [])

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
          className="
            group flex shrink-0 items-center gap-2.5 rounded-xl
            focus-visible:outline-none
            focus-visible:ring-4 focus-visible:ring-blue-500/15
          "
        >
          <span className="
            grid size-9 place-items-center rounded-[11px]
            bg-gradient-to-br from-blue-500 to-blue-700
            shadow-[0_4px_12px_rgba(37,99,235,0.24)]
            ring-1 ring-blue-700/10
          ">
            <ShieldCheck
              className="size-[19px] text-white"
              strokeWidth={2.25}
            />
          </span>

          <span className="flex flex-col items-start">
            <span className="
              text-[17px] font-semibold leading-[19px]
              tracking-[-0.025em] text-slate-950
            ">
              Work<span className="text-blue-600">shield</span>
            </span>

            <span className="
              mt-[3px] text-[8px] font-medium leading-none
              tracking-[0.16em] text-slate-400/80
            ">
              CONTRACT REVIEW
            </span>
          </span>
        </button>

        {/* Nav links */}
        <nav className="ml-10 hidden items-center gap-1 md:flex">
          <button
            onClick={() => onNavigate('upload-and-type')}
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
          <div className="hidden items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 sm:flex">
            <span className={`size-1.5 rounded-full ${timeLeft > 300 ? 'bg-emerald-500' : 'bg-red-500 animate-pulse'}`} />
            <span className="text-[11px] font-medium text-slate-600 font-mono tracking-tight">
              세션 유지 중 <span className="ml-0.5">{formatTime(timeLeft)}</span>
            </span>
          </div>
        </div>
      </div>
    </header>
  )
}
