import { createClientId } from '../utils/clientId'
import { useEffect, useRef, useState } from 'react'
import { RotateCcw, Send, X } from 'lucide-react'
import { api } from '../api/api'
import { useMetadata } from '../contexts/MetadataContext'
import { getStatusPresentation } from '../utils/metadata'
import { getErrorMessage } from '../utils/apiErrors'
import SourceReferences, { type SourceReference } from '../components/SourceReferences'

interface Props {
  reviewId: string
  focusClauseId?: string
  focusClauseName?: string
  focusClauseTitle?: string
  focusClauseStatus?: string
  focusClauseCategory?: string
  onClose: () => void
  onClearFocus?: () => void
  onReviewUnavailable?: () => void
  isOpen: boolean
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  refused?: boolean
  disclaimer?: string
  limitations?: string[]
  sources?: SourceReference[]
  outcome?: string
  toolStatus?: string
  retryable?: boolean | null
  retryPrompt?: string
}

export default function ChatbotScreen({ reviewId, focusClauseId, focusClauseName, focusClauseTitle, focusClauseStatus, focusClauseCategory, onClose, onClearFocus, onReviewUnavailable, isOpen }: Props) {
  const { metadata } = useMetadata()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState('')
  const [errorRetryable, setErrorRetryable] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setMessages([])
    setInput('')
    setIsSending(false)
    setError('')
    setErrorRetryable(false)
  }, [reviewId])
  useEffect(() => { if (isOpen) inputRef.current?.focus() }, [isOpen])
  // scrollIntoView의 반환값(Promise일 수 있음)이 React effect의 cleanup으로 전달되지 않게 한다.
  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }, [messages])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    if (!isOpen) return
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isOpen, onClose])

  const send = async (retryText?: string) => {
    const text = (retryText ?? input).trim()
    if (!text || isSending) return
    setError('')
    setErrorRetryable(false)
    const history = messages
      .map(({ role, text }) => ({ role, content: text.slice(0, 2000) }))
      // 본문 없는 제한 응답은 API의 history 최소 길이 검증(1자 이상)에 실패하므로 제외한다.
      .filter(({ content }) => content.trim().length > 0)
      .slice(-10)
    setMessages(previous => [...previous, { id: createClientId(), role: 'user', text }])
    setInput(''); setIsSending(true)
    try {
      const { data } = await api.chat(reviewId, text, createClientId(), focusClauseId, history)
      setMessages(previous => [...previous, {
        id: createClientId(), role: 'assistant', text: data.answer ?? data.limitations.join('\n'),
        refused: data.refused, disclaimer: data.disclaimer, limitations: data.limitations,
        outcome: data.outcome, toolStatus: data.tool_status, retryable: data.retryable, retryPrompt: text,
        sources: data.sources.map(source => ({
          type: source.type,
          display_label: source.display_label,
          clause_number: source.clause_number,
          title: source.title,
          category: source.category,
          law_name: source.law_name,
          article: source.article,
          source_url: source.source_url,
        })),
      }])
    } catch (requestError: any) {
      setMessages(previous => previous.slice(0, -1))
      setInput(text)
      if (requestError?.status === 404 || requestError?.status === 410) {
        onReviewUnavailable?.()
        return
      }
      setError(getErrorMessage(requestError, '답변 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.'))
      setErrorRetryable(requestError?.retryable === true)
    } finally { setIsSending(false) }
  }

  return <aside className={`fixed inset-y-0 right-0 z-50 flex w-full max-w-[480px] flex-col border-l border-slate-200 bg-white shadow-2xl transition-transform sm:w-[440px] ${isOpen ? 'translate-x-0' : 'translate-x-full pointer-events-none'}`} role="dialog" aria-modal="false" aria-hidden={!isOpen} aria-labelledby="chat-panel-title">
    <header className="border-b border-slate-200 p-4">
      <div className="flex items-start justify-between gap-3"><div><h2 id="chat-panel-title" className="font-semibold text-slate-900">결과 기반 질의응답</h2>{focusClauseId ? <div className="mt-1 text-xs text-slate-500"><p>현재 질문 대상: {focusClauseName || focusClauseId}{focusClauseTitle ? ` · ${focusClauseTitle}` : ''}</p><p>{[focusClauseStatus, focusClauseCategory].filter(Boolean).join(' · ')}</p></div> : <p className="mt-1 text-xs text-slate-500">현재 질문 대상: 전체 검토 결과</p>}</div><button type="button" onClick={onClose} aria-label="챗봇 패널 닫기" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><X className="size-5" /></button></div>
      {focusClauseId && <button type="button" onClick={onClearFocus} className="mt-3 text-xs font-semibold text-blue-700">전체 검토 결과 질문으로 전환</button>}
    </header>
    <div className="flex-1 space-y-4 overflow-y-auto p-4" aria-label="챗봇 대화 내용" aria-live="polite">
      {messages.length === 0 && <p className="text-sm text-slate-500">검토 결과에 관해 질문해 주세요.</p>}
      {messages.map(message => {
        const outcomePresentation = getStatusPresentation(metadata?.chat_outcome_details, message.outcome)
        const toolPresentation = getStatusPresentation(metadata?.grounding_status_details, message.toolStatus)
        return <div key={message.id} className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}><div className={message.role === 'user' ? 'max-w-[85%] rounded-xl bg-blue-600 px-3 py-2.5 text-sm text-white' : 'max-w-[90%] rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800'}>
        {message.refused && <p className="mb-2 text-xs font-semibold text-amber-700">{outcomePresentation?.message || '현재 검토 근거로는 답변이 제한됩니다. 질문 범위를 조정해 주세요.'}</p>}
        <p className="whitespace-pre-line leading-6">{message.text}</p>
        {message.toolStatus && message.toolStatus !== 'OK' && <p className="mt-2 text-xs text-amber-700">법령 조회: {toolPresentation?.message || '법령 원문을 확인하지 못했습니다. 법령이 존재하지 않는다는 의미는 아닙니다.'}</p>}
        {message.role === 'assistant' && message.retryable && message.retryPrompt && <button type="button" onClick={() => void send(message.retryPrompt)} disabled={isSending} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-blue-700 disabled:text-slate-400"><RotateCcw className="size-3" />같은 질문 다시 시도</button>}
        {message.sources?.length ? <SourceReferences sources={message.sources} title="답변 출처" /> : null}
        {message.limitations?.length ? <p className="mt-2 text-xs text-slate-500">제한: {message.limitations.join(', ')}</p> : null}
        {message.disclaimer && <p className="mt-2 text-xs text-slate-500">{message.disclaimer}</p>}
      </div></div>})}
      {isSending && <div className="flex justify-start" role="status" aria-live="polite"><div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-600">답변을 작성하고 있습니다<span className="inline-block min-w-5 animate-pulse">…</span></div></div>}
      <div ref={bottomRef} />
    </div>
    {error && <div className="mx-4 mb-2 rounded-lg bg-rose-50 p-3 text-xs text-rose-700" role="alert">{error}{errorRetryable && <button type="button" onClick={() => void send()} className="ml-2 inline-flex items-center gap-1 font-semibold underline"><RotateCcw className="size-3" />재시도</button>}</div>}
    <div className="flex gap-2 border-t border-slate-200 p-3"><input ref={inputRef} value={input} disabled={isSending} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') void send() }} placeholder="검토 결과에 대해 질문해 주세요" className="min-h-11 min-w-0 flex-1 rounded-xl border border-slate-200 px-3 text-sm disabled:bg-slate-100" /><button type="button" onClick={() => void send()} disabled={!input.trim() || isSending} aria-label="질문 전송" className="rounded-xl bg-blue-600 px-4 text-white disabled:bg-slate-300"><Send className="size-4" /></button></div>
  </aside>
}
