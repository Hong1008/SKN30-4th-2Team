import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, BookOpen, Send } from 'lucide-react'
import { api } from '../api/api'

interface Props {
  onBack: () => void
  reviewId: string
  focusClauseId?: string
  onStartNewReview: () => void
}
interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  refused?: boolean
  disclaimer?: string
  limitations?: string[]
  sources?: Array<{ label: string; type: string }>
  outcome?: string
  toolStatus?: string
}

export default function ChatbotScreen({ onBack, reviewId, focusClauseId, onStartNewReview }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState('')
  const [expired, setExpired] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const pendingRequest = useRef<{ message: string; key: string } | null>(null)

  useEffect(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), [messages])

  const send = async () => {
    const text = input.trim()
    if (!text || isSending) return
    setError('')
    const history = messages
      .map(({ role, text }) => ({ role, content: text.slice(0, 2000) }))
      .slice(-10)
    const request = pendingRequest.current?.message === text
      ? pendingRequest.current
      : { message: text, key: crypto.randomUUID() }
    pendingRequest.current = request
    setMessages((previous) => [...previous, { id: crypto.randomUUID(), role: 'user', text }])
    setInput('')
    setIsSending(true)
    try {
      const response = await api.chat(reviewId, text, request.key, focusClauseId, history)
      const data = response.data
      setMessages((previous) => [...previous, {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: data.answer ?? (data.limitations.join('\n') || '답변을 생성하지 못했습니다.'),
        refused: data.refused,
        disclaimer: data.disclaimer,
        limitations: data.limitations,
        outcome: data.outcome,
        toolStatus: data.tool_status,
        sources: data.sources.map((source) => ({
          label: [source.law_name, source.article].filter(Boolean).join(' ')
            || source.id
            || '참고 자료',
          type: source.type,
        })),
      }])
      pendingRequest.current = null
    } catch (error: any) {
      setMessages((previous) => previous.slice(0, -1))
      if (error?.status === 404 || error?.status === 410) {
        setExpired(true)
        setError('검토 세션이 만료되었거나 접근할 수 없습니다.')
      } else {
        setError(error?.message || '답변 요청에 실패했습니다.')
      }
      setInput(text)
    } finally {
      setIsSending(false)
    }
  }

  return <div className="mx-auto max-w-3xl space-y-5">
    <button onClick={onBack} className="inline-flex items-center gap-1 text-sm text-slate-600"><ArrowLeft className="size-4" />결과로 돌아가기</button>
    <section className="flex h-[620px] flex-col rounded-2xl border border-slate-200 bg-white">
      <header className="border-b border-slate-200 p-5"><h1 className="font-semibold text-slate-900">검토 결과 기반 질의응답</h1><p className="mt-1 text-xs text-slate-500">답변은 검토 결과와 제공된 근거를 바탕으로 합니다.</p></header>
      <div className="flex-1 space-y-4 overflow-y-auto p-5">
        {messages.length === 0 && <p className="text-sm text-slate-500">검토 결과에 관해 질문해 주세요.</p>}
        {messages.map((message) => <div key={message.id} className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
          <div className={message.role === 'user' ? 'max-w-[80%] rounded-xl bg-blue-600 px-4 py-3 text-sm text-white' : 'max-w-[85%] rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-800'}>
            {message.refused && <p className="mb-2 font-semibold text-amber-700">답변 범위 제한</p>}
            {message.outcome && message.outcome !== 'ANSWERED' && !message.refused && (
              <p className="mb-2 font-semibold text-amber-700">
                {message.outcome === 'INSUFFICIENT_GROUNDING' ? '근거 부족' : '답변 생성 확인 필요'}
              </p>
            )}
            <p className="whitespace-pre-line leading-6">{message.text}</p>
            {message.sources?.length ? <div className="mt-3 flex flex-wrap gap-1.5">{message.sources.map((source, index) => <span key={`${source.label}-${index}`} className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600"><BookOpen className="size-3" />{source.label}</span>)}</div> : null}
            {message.limitations?.length ? <p className="mt-3 text-xs text-slate-500">제한: {message.limitations.join(', ')}</p> : null}
            {message.toolStatus && message.toolStatus !== 'OK' ? (
              <p className="mt-2 text-xs text-amber-700">근거 도구 상태: {message.toolStatus}</p>
            ) : null}
            {message.disclaimer ? <p className="mt-2 text-xs text-slate-500">{message.disclaimer}</p> : null}
          </div>
        </div>)}
        <div ref={bottomRef} />
      </div>
      {error && <div className="px-4 text-xs text-rose-600" role="alert">
        <p>{error}</p>
        {expired && <button type="button" onClick={onStartNewReview} className="mt-2 font-semibold underline">새 검토 시작</button>}
      </div>}
      <div className="flex gap-2 border-t border-slate-200 p-4"><input value={input} maxLength={2000} disabled={expired} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void send() }} placeholder={expired ? '세션이 만료되었습니다' : '검토 결과에 대해 질문해 주세요'} className="min-w-0 flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-100" /><button onClick={() => void send()} disabled={expired || !input.trim() || isSending} className="rounded-xl bg-blue-600 px-4 text-white disabled:bg-slate-300"><Send className="size-4" /></button></div>
    </section>
  </div>
}
