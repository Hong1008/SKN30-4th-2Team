import { Check } from 'lucide-react'
import type { Screen } from '../types'

const STEPS = [
  { id: 1, label: '업로드 및 유형 선택', sub: '계약서 업로드 및 기준 설정', nav: 'upload-and-type' as Screen },
  { id: 2, label: '검토 진행',       sub: 'AI 표준조항 비교',        nav: 'processing' as Screen },
  { id: 3, label: '결과 확인',       sub: '조항별 검토 내용 확인',   nav: 'results' as Screen },
]

const STEP_FOR: Record<Screen, number> = {
  'upload-and-type': 1,
  'out-of-scope': 1,
  processing: 2,
  results: 3,
  'clause-detail': 3,
  chatbot: 3,
}

interface Props {
  currentScreen: Screen
  onNavigate: (s: Screen) => void
}

export default function HorizontalStepper({ currentScreen, onNavigate }: Props) {
  const currentStep = STEP_FOR[currentScreen]

  return (
    <section className="border-b border-slate-200/80 bg-white">
      <div className="mx-auto max-w-[1280px] px-4 sm:px-6 lg:px-8">
        <nav
          aria-label="계약서 검토 진행 단계"
          className="grid h-20 grid-cols-3 sm:h-[88px]"
        >
          {STEPS.map((step, index) => {
            const done = step.id < currentStep
            const current = step.id === currentStep
            const ahead = step.id > currentStep

            return (
              <button
                key={step.id}
                disabled={ahead}
                onClick={() => !ahead && onNavigate(step.nav)}
                className={`
                  group relative flex min-w-0 flex-col items-center justify-center gap-2 px-1 text-center sm:flex-row sm:justify-start sm:gap-3 sm:px-4 sm:text-left
                  focus-visible:z-10 focus-visible:outline-none
                  focus-visible:ring-4 focus-visible:ring-inset
                  focus-visible:ring-blue-500/15
                  ${ahead ? 'cursor-default' : 'hover:bg-slate-50/80'}
                `}
              >
                {index < STEPS.length - 1 && (
                  <span
                    aria-hidden="true"
                    className={`absolute left-1/2 right-[-50%] top-[24px] h-px sm:left-[52px] sm:right-[-12px] sm:top-1/2
                      ${done ? 'bg-blue-300' : 'bg-slate-200'}`}
                  />
                )}

                <span
                  className={`
                    relative z-10 grid size-8 shrink-0 place-items-center
                    rounded-full text-xs font-semibold
                    ${done
                      ? 'bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200'
                      : current
                      ? 'bg-blue-600 text-white ring-4 ring-blue-100'
                      : 'border border-slate-300 bg-white text-slate-400'
                    }
                  `}
                >
                  {done ? <Check className="size-4" strokeWidth={2.5} /> : step.id}
                </span>

                <span className="relative z-10 min-w-0 bg-white px-1 sm:pr-3">
                  <span
                    className={`block truncate text-[11px] leading-4 sm:text-[13px] sm:leading-5
                      ${current
                        ? 'font-semibold text-blue-700'
                        : done
                        ? 'font-medium text-slate-600'
                        : 'font-medium text-slate-400'
                      }`}
                  >
                    {step.label}
                  </span>

                  <span className="mt-0.5 hidden truncate text-xs leading-4 text-slate-400 sm:block">
                    {step.sub}
                  </span>
                </span>

                {current && (
                  <span className="absolute inset-x-3 bottom-0 h-[2px] rounded-full bg-blue-600 sm:inset-x-5" />
                )}
              </button>
            )
          })}
        </nav>
      </div>
    </section>
  )
}
