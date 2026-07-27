import { useState, useRef, useEffect } from 'react'
import { ArrowLeft, Send, BookOpen, Scale, Copy, Check, AlertCircle, ChevronDown } from 'lucide-react'
import { api } from '../api/api'

interface Props { onBack: () => void; reviewId: string }

interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  sources?: { label: string; type: 'clause' | 'law' }[]
  outOfScope?: boolean
}

const INITIAL_MESSAGES: Message[] = [
  {
    id: 'a0',
    role: 'assistant',
    text: '안녕하세요. 검토 결과를 바탕으로 궁금한 점을 질문해 주세요. 조항이나 표준계약서 내용을 근거로 답변을 드립니다.',
    sources: [],
  },
  {
    id: 'u1',
    role: 'user',
    text: '제5조 연장근로 한도에 대해 더 자세히 설명해 주세요.',
  },
  {
    id: 'a1',
    role: 'assistant',
    text: '업로드하신 계약서의 제5조에는 연장근로를 "당사자 합의에 따라 실시할 수 있다"라고만 명시되어 있습니다.\n\n표준근로계약서 기준으로는 연장근로 한도(1주 12시간 이내)와 가산수당(통상임금의 50% 이상)이 함께 명시되어 있습니다. 해당 내용이 포함되어 있지 않은 경우 근로기준법 제53조 및 제56조 기준과 비교 검토가 필요할 수 있습니다.',
    sources: [
      { label: '제5조 (근로시간 및 휴게)', type: 'clause' },
      { label: '근로기준법 제53조', type: 'law' },
      { label: '근로기준법 제56조', type: 'law' },
    ],
  },
]

const SUGGESTIONS = [
  '제11조 경업금지 기간이 일반적으로 어느 정도인가요?',
  '제5조에 대한 협의 문구 제안을 보여주세요.',
  '표준계약서에서 퇴직금 조항은 어떻게 명시되나요?',
]

const PROPOSAL = {
  title: '제5조 협의 문구 제안',
  purpose: '연장근로 한도 및 가산수당 기준을 표준계약서 수준으로 명확히 하기 위한 검토용 제안입니다.',
  diff: '기존 문구에서 연장근로 한도(1주 12시간)와 가산수당 비율(50%)을 명시적으로 추가하는 방향으로 수정하였습니다.',
  reference: '표준근로계약서 제5조 (고용노동부), 근로기준법 제53조·제56조',
  text: `제5조 (근로시간 및 휴게)

① 소정 근로시간은 휴게시간을 제외하고 1일 8시간, 1주 40시간으로 한다.

② 연장근로는 1주간 12시간을 초과하지 않는 범위에서 당사자 합의에 따라 실시할 수 있으며, 연장근로에 대하여는 통상임금의 100분의 50 이상을 가산하여 지급한다.

③ 사용자는 근로자에게 근로시간 도중에 다음 기준에 따른 휴게시간을 부여하여야 한다.
   - 4시간 근무 시 30분 이상
   - 8시간 근무 시 1시간 이상`,
}

export default function ChatbotScreen({ onBack, reviewId }: Props) {
  const [messages, setMessages]         = useState<Message[]>(INITIAL_MESSAGES)
  const [input, setInput]               = useState('')
  const [showProposal, setShowProposal] = useState(false)
  const [copiedProp, setCopiedProp]     = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = (text: string) => {
    if (!text.trim()) return
    const userMsg: Message = { id: `u${Date.now()}`, role: 'user', text }
    setMessages(prev => [...prev, userMsg])
    setInput('')

    const isOutOfScope = text.includes('세금') || text.includes('보험') || text.includes('판결')
    
    // 멱등성 키 생성 (Idempotency-Key)
    const idempotencyKey = crypto.randomUUID()
    
    // 실제 API 호출 시 멱등성 키 전달
    api.chat(reviewId, text, idempotencyKey).then(res => {
      const reply: Message = isOutOfScope
        ? {
            id: `a${Date.now()}`,
            role: 'assistant',
            text: '',
            outOfScope: true,
          }
        : {
            id: `a${Date.now()}`,
            role: 'assistant',
            text: '해당 질문은 검토 결과 내 조항 범위에서 확인 가능한 내용을 바탕으로 답변드립니다. 더 구체적인 사항은 법률 전문가에게 확인하시기 바랍니다.',
            sources: [{ label: '제5조 (근로시간 및 휴게)', type: 'clause' }],
          }
      setMessages(prev => [...prev, reply])
    })
  }

  const copyProposal = () => {
    navigator.clipboard.writeText(PROPOSAL.text).catch(() => {})
    setCopiedProp(true)
    setTimeout(() => setCopiedProp(false), 1800)
  }

  return (
    <div className="animate-fade-up">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={onBack} className="flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900 transition-colors">
          <ArrowLeft className="w-4 h-4" />
          검토 결과로
        </button>
      </div>

      <div className="grid lg:grid-cols-[1fr_380px] gap-6">
        {/* Chat panel */}
        <div className="bg-white border border-slate-200 rounded-2xl flex flex-col" style={{ height: 620 }}>
          {/* Header */}
          <div className="px-5 py-4 border-b border-slate-200">
            <h2 className="text-sm font-semibold text-slate-900">검토 결과 기반 질의응답</h2>
            <p className="text-xs text-slate-600 mt-0.5">
              이 챗봇은 검토 결과 내 조항 및 표준계약서를 근거로 답변합니다.
            </p>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5">
            {messages.map(msg => (
              <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {msg.role === 'assistant' && (
                  <div className="flex flex-col gap-2 max-w-[85%]">
                    {msg.outOfScope ? (
                      <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 flex items-start gap-3">
                        <AlertCircle className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" aria-hidden="true" />
                        <div>
                          <p className="text-xs font-semibold text-slate-600 mb-1">답변 범위 외 질문입니다</p>
                          <p className="text-xs text-slate-500 leading-relaxed">
                            이 챗봇은 업로드한 계약서 검토 결과와 표준계약서 내용을 근거로만 답변합니다.
                            해당 질문은 현재 검토 범위를 벗어나 있어 답변을 제공하기 어렵습니다.
                          </p>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="bg-slate-50 border border-slate-200 rounded-xl rounded-tl-sm px-4 py-3">
                          <p className="text-sm text-slate-900 leading-relaxed whitespace-pre-line">{msg.text}</p>
                        </div>
                        {msg.sources && msg.sources.length > 0 && (
                          <div className="flex flex-wrap gap-1.5">
                            {msg.sources.map((s, i) => (
                              <span
                                key={i}
                                className={`inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full border ${
                                  s.type === 'law'
                                    ? 'bg-blue-50 border-blue-200 text-blue-600'
                                    : 'bg-slate-50 border-slate-200 text-slate-600'
                                }`}
                              >
                                {s.type === 'law' ? <Scale className="w-2.5 h-2.5" /> : <BookOpen className="w-2.5 h-2.5" />}
                                {s.label}
                              </span>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
                {msg.role === 'user' && (
                  <div className="bg-blue-600 text-white rounded-xl rounded-tr-sm px-4 py-3 max-w-[80%]">
                    <p className="text-sm leading-relaxed">{msg.text}</p>
                  </div>
                )}
              </div>
            ))}
            <div ref={bottomRef} />
          </div>

          {/* Suggestions */}
          <div className="px-5 pb-3">
            <div className="flex gap-2 overflow-x-auto pb-1">
              {SUGGESTIONS.map((s, i) => (
                <button
                  key={i}
                  onClick={() => send(s)}
                  className="shrink-0 px-3 py-1.5 text-[11px] text-blue-600 bg-blue-50 border border-blue-200 rounded-full hover:bg-blue-200/40 transition-colors whitespace-nowrap"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Input */}
          <div className="px-5 pb-5">
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), send(input))}
                placeholder="검토 결과에 대해 질문해 주세요"
                className="flex-1 px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-900 placeholder:text-slate-500 focus:outline-none focus:border-blue-600 focus:ring-1 focus:ring-blue-600"
              />
              <button
                onClick={() => send(input)}
                disabled={!input.trim()}
                className="w-10 h-10 bg-blue-600 text-white rounded-xl flex items-center justify-center hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-500 transition-colors shrink-0"
                aria-label="전송"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Proposal panel */}
        <div className="space-y-4">
          <button
            onClick={() => setShowProposal(!showProposal)}
            className="w-full flex items-center justify-between px-5 py-4 bg-white border border-slate-200 rounded-xl hover:border-blue-200 transition-colors"
          >
            <div className="text-left">
              <p className="text-sm font-semibold text-slate-900">협의 문구 제안</p>
              <p className="text-xs text-slate-600 mt-0.5">제5조 (근로시간 및 휴게)</p>
            </div>
            <ChevronDown className={`w-4 h-4 text-slate-600 transition-transform ${showProposal ? 'rotate-180' : ''}`} />
          </button>

          {showProposal && (
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              {/* Disclaimer */}
              <div className="bg-amber-50 border-b border-amber-200 px-4 py-3">
                <p className="text-[11px] text-amber-700 leading-relaxed">
                  <strong>계약서 수정본이 아닌 검토를 위한 참고 제안 문구</strong>입니다.
                  법적 효력이나 적절성을 보장하지 않으며, 실제 사용 전 전문가 확인을 권장합니다.
                </p>
              </div>

              <div className="p-5 space-y-4">
                {/* Meta */}
                <div className="space-y-2">
                  <div>
                    <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">생성 목적</p>
                    <p className="text-xs text-slate-600 leading-relaxed">{PROPOSAL.purpose}</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">주요 변경 내용</p>
                    <p className="text-xs text-slate-600 leading-relaxed">{PROPOSAL.diff}</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">참고 표준조항</p>
                    <p className="text-xs text-blue-600">{PROPOSAL.reference}</p>
                  </div>
                </div>

                {/* Proposed text */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">제안 문구</p>
                    <button
                      onClick={copyProposal}
                      className="flex items-center gap-1 text-[11px] text-slate-600 hover:text-slate-900 transition-colors"
                    >
                      {copiedProp ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
                      {copiedProp ? '복사됨' : '복사'}
                    </button>
                  </div>
                  <pre className="bg-slate-50 border border-slate-200 rounded-lg px-4 py-4 text-[11px] text-slate-900 font-mono leading-relaxed whitespace-pre-wrap break-words">
                    {PROPOSAL.text}
                  </pre>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
