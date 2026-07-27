import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, BookOpen, Send } from 'lucide-react'
import { api } from '../api/api'

interface Props { onBack: () => void; reviewId: string }
interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  refused?: boolean
  disclaimer?: string
  limitations?: string[]
  sources?: Array<{ label: string; type: string }>
}

export default function ChatbotScreen({ onBack, reviewId }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), [messages])

  const send = async () => {
    const text = input.trim()
    if (!text || isSending) return
    setMessages((previous) => [...previous, { id: crypto.randomUUID(), role: 'user', text }])
    setInput('')
    setIsSending(true)
    try {
      const response = await api.chat(reviewId, text, crypto.randomUUID())
      const data = response.data
      setMessages((previous) => [...previous, {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: data.answer ?? (data.limitations.join('\n') || '답변을 생성하지 못했습니다.'),
        refused: data.refused,
        disclaimer: data.disclaimer,
        limitations: data.limitations,
        sources: data.sources.map((source) => ({
          label: source.label ?? source.title ?? source.source_id ?? '참고 자료',
          type: source.source_type ?? 'source',
        })),
      }])
    } catch (error: any) {
      setMessages((previous) => [...previous, { id: crypto.randomUUID(), role: 'assistant', text: error?.message || '답변 요청에 실패했습니다.' }])
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
            <p className="whitespace-pre-line leading-6">{message.text}</p>
            {message.sources?.length ? <div className="mt-3 flex flex-wrap gap-1.5">{message.sources.map((source, index) => <span key={`${source.label}-${index}`} className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600"><BookOpen className="size-3" />{source.label}</span>)}</div> : null}
            {message.limitations?.length ? <p className="mt-3 text-xs text-slate-500">제한: {message.limitations.join(', ')}</p> : null}
            {message.disclaimer ? <p className="mt-2 text-xs text-slate-500">{message.disclaimer}</p> : null}
          </div>
        </div>)}
        <div ref={bottomRef} />
      </div>
      <div className="flex gap-2 border-t border-slate-200 p-4"><input value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void send() }} placeholder="검토 결과에 대해 질문해 주세요" className="min-w-0 flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm" /><button onClick={() => void send()} disabled={!input.trim() || isSending} className="rounded-xl bg-blue-600 px-4 text-white disabled:bg-slate-300"><Send className="size-4" /></button></div>
    </section>
  </div>
}
