import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, ChevronUp, Copy, RotateCcw, Send, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../api/api'
import { useMetadata } from '../contexts/MetadataContext'
import { getMetadataLabel, getStatusPresentation } from '../utils/metadata'
import { getErrorMessage } from '../utils/apiErrors'
import SourceReferences, { type SourceReference } from '../components/SourceReferences'
import { getChatHistoryStorageKey } from '../config'
import { createClientId } from '../utils/clientId'
import type { ChatSource, ChatStreamContinuation, ChatStreamProgressEvent, MetadataData } from '../types'

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

interface AnswerPreparation {
  stage?: string
  message: string
  questionCategory?: string | null
  contextUsed?: boolean
  segment?: ChatStreamProgressEvent['segment']
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
  refusalReason?: 'OUT_OF_SCOPE' | 'INSUFFICIENT_GROUNDING' | null
  questionCategory?: string | null
  toolStatus?: string
  retryable?: boolean | null
  retryPrompt?: string
  conversationToken?: string | null
  isStreaming?: boolean
  preparationHistory?: AnswerPreparation[]
  continuation?: ChatStreamContinuation | null
}

function MarkdownContent({ children }: { children: string }) {
  return <ReactMarkdown
    remarkPlugins={[remarkGfm]}
    skipHtml
    components={{
      h1: ({ children: heading }) => <h1 className="mb-2 text-base font-bold">{heading}</h1>,
      h2: ({ children: heading }) => <h2 className="mb-2 text-sm font-bold">{heading}</h2>,
      h3: ({ children: heading }) => <h3 className="mb-1 text-sm font-semibold">{heading}</h3>,
      p: ({ children: paragraph }) => <p className="mb-2 last:mb-0 leading-6">{paragraph}</p>,
      ul: ({ children: list }) => <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{list}</ul>,
      ol: ({ children: list }) => <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{list}</ol>,
      blockquote: ({ children: quote }) => <blockquote className="mb-2 border-l-2 border-slate-300 pl-3 text-slate-600">{quote}</blockquote>,
      table: ({ children: table }) => <div className="mb-2 overflow-x-auto"><table className="min-w-full border-collapse text-left text-xs">{table}</table></div>,
      th: ({ children: cell }) => <th className="border border-slate-300 bg-slate-100 px-2 py-1 font-semibold">{cell}</th>,
      td: ({ children: cell }) => <td className="border border-slate-300 px-2 py-1 align-top">{cell}</td>,
      a: ({ href, children: link }) => {
        const safeHref = href && /^https?:\/\//i.test(href) ? href : undefined
        return safeHref
          ? <a href={safeHref} target="_blank" rel="noopener noreferrer" className="text-blue-700 underline">{link}</a>
          : <span>{link}</span>
      },
    }}
  >{children}</ReactMarkdown>
}

function PreparationPanel({
  message,
  expanded,
  onToggle,
  isStreaming,
  metadata,
}: {
  message: Message
  expanded: boolean
  onToggle: () => void
  isStreaming: boolean
  metadata: MetadataData | null
}) {
  const history = message.preparationHistory ?? []
  const latest = history.at(-1)
  if (!latest) return null
  const latestMessage = latest.message || '답변을 준비하고 있습니다.'
  return <section className="max-w-[90%] rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-600" aria-label="답변 준비 상태" role={isStreaming ? 'status' : undefined}>
    {!expanded ? <button type="button" onClick={onToggle} aria-expanded="false" className="flex w-full items-center justify-between gap-3 text-left font-semibold text-slate-700">
      <span>답변 준비 상태 · {latestMessage}</span><ChevronDown className="size-4 shrink-0" aria-hidden="true" />
    </button> : <>
      <button type="button" onClick={onToggle} aria-expanded="true" aria-label="답변 준비 상태 닫기" className="ml-auto flex rounded p-0.5 text-slate-500 hover:bg-slate-100"><ChevronUp className="size-4" aria-hidden="true" /></button>
      <ol className="space-y-2 border-l border-slate-200 pl-3">
        {history.map((entry, index) => <li key={`${entry.stage ?? 'preparing'}-${index}`} className="relative"><span className="absolute -left-[17px] top-1.5 size-2 rounded-full bg-blue-500" /><p>{entry.message}</p>{entry.stage && <p className="mt-0.5 text-slate-500">단계: {getMetadataLabel(metadata?.chat_progress_stage_details, entry.stage, entry.stage)}</p>}{entry.questionCategory && <p className="mt-0.5 text-slate-500">질문 유형: {getMetadataLabel(metadata?.chat_question_category_details, entry.questionCategory, entry.questionCategory)}</p>}{entry.contextUsed != null && <p className="mt-0.5 text-slate-500">검토 근거 {entry.contextUsed ? '확인 중' : '준비 중'}</p>}{entry.segment && <p className="mt-0.5 text-slate-500">답변 묶음 {entry.segment.index}/{entry.segment.total}</p>}</li>)}
      </ol>
    </>}
  </section>
}

const toSourceReferences = (sources: ChatSource[]): SourceReference[] => sources.map(source => ({
  type: source.type,
  display_label: source.display_label,
  clause_number: source.clause_number,
  title: source.title,
  category: source.category,
  standard_contract_label: source.standard_contract_label,
  law_name: source.law_name,
  article: source.article,
}))

const mergeSourceReferences = (
  current: SourceReference[],
  incoming: SourceReference[],
) => {
  const seen = new Set(current.map(source => [source.type, source.display_label, source.law_name, source.article].join('|')))
  return [...current, ...incoming.filter(source => {
    const key = [source.type, source.display_label, source.law_name, source.article].join('|')
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })]
}

const LEGACY_META_HEADER = /^\s*(?:\[(?:상태|카테고리|답변)\s*:\s*[^\]\n]+\]\s*)+(?:\n+)?/m
const EMPTY_ANSWER = '제공된 문서에서 관련 정보를 찾을 수 없습니다.'

const normalizeGeneratedText = (value: string) => {
  const text = value.replace(LEGACY_META_HEADER, '').trim()
  const paragraphs = text.split(/\n\s*\n/).map(item => item.trim()).filter(Boolean)
  return (paragraphs.length > 1 ? paragraphs.filter(item => item !== EMPTY_ANSWER) : paragraphs).join('\n\n')
}

const refusalDetail = (metadata: MetadataData | null, reason?: Message['refusalReason']) => {
  const detail = metadata?.chat_refusal_reason_details?.find(item => item.code === reason)
  if (detail) return detail
  if (reason === 'OUT_OF_SCOPE') return { code: reason, label: '검토 자료 범위 밖 질문', description: '현재 질문은 계약 검토 결과·표준조항·법령 참고자료 범위를 벗어났습니다.' }
  if (reason === 'INSUFFICIENT_GROUNDING') return { code: reason, label: '검토 근거 부족', description: '현재 검토 결과에서 답변 근거를 찾지 못했습니다.' }
  return null
}

const readMessages = (reviewId: string): Message[] => {
  try {
    const raw = sessionStorage.getItem(getChatHistoryStorageKey(reviewId))
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item): item is Message => (
      typeof item === 'object' && item !== null
      && typeof item.id === 'string'
      && (item.role === 'user' || item.role === 'assistant')
      && typeof item.text === 'string'
    ))
  } catch {
    return []
  }
}

export default function ChatbotScreen({ reviewId, focusClauseId, focusClauseName, focusClauseTitle, focusClauseStatus, focusClauseCategory, onClose, onClearFocus, onReviewUnavailable, isOpen }: Props) {
  const { metadata } = useMetadata()
  const [messages, setMessages] = useState<Message[]>(() => readMessages(reviewId))
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState('')
  const [errorRetryable, setErrorRetryable] = useState(false)
  const [expandedPreparationIds, setExpandedPreparationIds] = useState<Set<string>>(new Set())
  const [typingDots, setTypingDots] = useState('.')
  const [copiedAnswerId, setCopiedAnswerId] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const loadedReviewId = useRef(reviewId)
  const restoringReviewId = useRef<string | null>(null)

  useEffect(() => {
    if (loadedReviewId.current === reviewId) return
    loadedReviewId.current = reviewId
    restoringReviewId.current = reviewId
    setMessages(readMessages(reviewId))
    setInput('')
    setIsSending(false)
    setError('')
    setErrorRetryable(false)
    setExpandedPreparationIds(new Set())
    setCopiedAnswerId(null)
  }, [reviewId])
  useEffect(() => {
    if (restoringReviewId.current === reviewId) {
      restoringReviewId.current = null
      return
    }
    const key = getChatHistoryStorageKey(reviewId)
    if (messages.length === 0) {
      sessionStorage.removeItem(key)
      return
    }
    sessionStorage.setItem(key, JSON.stringify(messages))
  }, [messages, reviewId])
  useEffect(() => { if (isOpen) inputRef.current?.focus() }, [isOpen])
  useEffect(() => { bottomRef.current?.scrollIntoView?.({ behavior: 'smooth' }) }, [messages])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    if (!isOpen) return
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isOpen, onClose])
  useEffect(() => {
    if (!isSending) {
      setTypingDots('.')
      return
    }
    const intervalId = window.setInterval(() => setTypingDots(previous => previous === '...' ? '.' : `${previous}.`), 350)
    return () => window.clearInterval(intervalId)
  }, [isSending])

  const togglePreparation = (messageId: string) => {
    setExpandedPreparationIds(previous => {
      const next = new Set(previous)
      if (next.has(messageId)) next.delete(messageId)
      else next.add(messageId)
      return next
    })
  }

  const copyAnswer = async (messageId: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedAnswerId(messageId)
      window.setTimeout(() => {
        setCopiedAnswerId(current => current === messageId ? null : current)
      }, 2_000)
    } catch {
      setCopiedAnswerId(null)
    }
  }

  const send = async (retryText?: string) => {
    const text = (retryText ?? input).trim()
    if (!text || isSending) return
    setError('')
    setErrorRetryable(false)
    const conversationToken = [...messages].reverse().find(message => message.role === 'assistant')?.conversationToken
    const userMessageId = createClientId()
    const assistantMessageId = createClientId()
    const initialPreparation: AnswerPreparation = { message: '답변 준비를 시작하고 있습니다.' }
    let streamedText = ''
    let streamedSources: SourceReference[] = []
    setMessages(previous => [
      ...previous.map(message => (
        retryText === '이어서 답변해줘' && message.continuation && message.conversationToken === conversationToken
          ? { ...message, continuation: null }
          : message
      )),
      { id: userMessageId, role: 'user', text },
      { id: assistantMessageId, role: 'assistant', text: '', isStreaming: true, preparationHistory: [initialPreparation] },
    ])
    setInput(''); setIsSending(true)
    try {
      const data = await api.chatStream(reviewId, text, createClientId(), {
        onProgress: event => {
          const nextPreparation: AnswerPreparation = {
            stage: event.stage,
            message: event.message,
            questionCategory: event.question_category,
            contextUsed: event.context_used,
            segment: event.segment,
          }
          setMessages(previous => previous.map(message => {
            if (message.id !== assistantMessageId) return message
            const currentHistory = message.preparationHistory ?? []
            const latest = currentHistory.at(-1)
            const unchanged = latest?.stage === nextPreparation.stage && latest?.message === nextPreparation.message
            return { ...message, preparationHistory: unchanged ? currentHistory : [...currentHistory, nextPreparation] }
          }))
        },
        onDelta: event => {
          streamedText += event.text
          setMessages(previous => previous.map(message => message.id === assistantMessageId ? { ...message, text: normalizeGeneratedText(streamedText) } : message))
        },
        onSegmentComplete: event => {
          streamedSources = mergeSourceReferences(streamedSources, toSourceReferences(event.sources))
          setMessages(previous => previous.map(message => message.id === assistantMessageId ? { ...message, sources: streamedSources } : message))
        },
        onCompleted: event => {
          setMessages(previous => previous.map(message => message.id === assistantMessageId
            ? { ...message, continuation: event.continuation ?? null }
            : message))
        },
        onFailed: event => {
          setMessages(previous => previous.map(message => message.id === assistantMessageId
            ? {
                ...message,
                continuation: event.continuation ?? null,
                conversationToken: event.conversation_token ?? message.conversationToken,
              }
            : message))
        },
      }, focusClauseId, [], conversationToken ?? undefined)
      const finalSources = toSourceReferences(data.sources)
      const finalText = data.refusal_reason
        ? ''
        : normalizeGeneratedText((data.answer ?? streamedText) || data.limitations.join('\n'))
      setMessages(previous => previous.map(message => message.id === assistantMessageId ? {
        ...message,
        text: finalText,
        refused: data.refused,
        refusalReason: data.refusal_reason,
        disclaimer: data.disclaimer,
        limitations: data.limitations,
        outcome: data.outcome,
        toolStatus: data.tool_status,
        retryable: data.retryable,
        retryPrompt: text,
        conversationToken: data.conversation_token,
        questionCategory: data.question_category,
        sources: finalSources.length ? mergeSourceReferences(streamedSources, finalSources) : streamedSources,
        isStreaming: false,
      } : message))
    } catch (requestError: any) {
      setMessages(previous => previous.map(message => message.id === assistantMessageId ? { ...message, isStreaming: false } : message))
      setInput(text)
      if (requestError?.status === 404 || requestError?.status === 410) {
        onReviewUnavailable?.()
        return
      }
      setError(getErrorMessage(requestError, '답변 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.'))
      setErrorRetryable(requestError?.retryable === true)
    } finally {
      setIsSending(false)
    }
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
        const expanded = expandedPreparationIds.has(message.id)
        const limitDetail = refusalDetail(metadata, message.refusalReason)
        const bubble = <div className={message.role === 'user' ? 'max-w-[85%] rounded-xl bg-blue-600 px-3 py-2.5 text-sm text-white' : 'max-w-[90%] rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800'}>
          {limitDetail && <p className="mb-2 text-xs font-semibold text-amber-700">답변 제한 사유: {limitDetail.label}<span className="mt-1 block font-normal">{limitDetail.description}</span></p>}
          {message.refused && !message.text && !limitDetail && <p className="mb-2 text-xs font-semibold text-amber-700">{outcomePresentation?.message || '현재 검토 근거로는 답변이 제한됩니다. 질문 범위를 조정해 주세요.'}</p>}
          {message.text && (message.role === 'assistant' ? <MarkdownContent>{message.text}</MarkdownContent> : <p className="whitespace-pre-line leading-6">{message.text}</p>)}
          {message.toolStatus && !['OK', 'NOT_REQUESTED', 'LLM_OUTPUT_INVALID'].includes(message.toolStatus) && <p className="mt-2 text-xs text-amber-700">법령 조회: {toolPresentation?.message || '법령 원문을 확인하지 못했습니다. 법령이 존재하지 않는다는 의미는 아닙니다.'}</p>}
          {message.role === 'assistant' && message.retryable && message.retryPrompt && <button type="button" onClick={() => void send(message.retryPrompt)} disabled={isSending} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-blue-700 disabled:text-slate-400"><RotateCcw className="size-3" />같은 질문 다시 시도</button>}
          {message.role === 'assistant' && message.continuation && message.conversationToken && <button type="button" onClick={() => void send('이어서 답변해줘')} disabled={isSending} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-blue-700 disabled:text-slate-400"><RotateCcw className="size-3" />이어서 답변 ({message.continuation.remaining_segments}개 묶음)</button>}
          {message.sources?.length ? <SourceReferences sources={message.sources} title="답변 출처" /> : null}
          {message.limitations?.length && !limitDetail ? <p className="mt-2 text-xs text-slate-500">제한: {message.limitations.join(', ')}</p> : null}
          {message.disclaimer && <p className="mt-2 text-xs text-slate-500">{message.disclaimer}</p>}
          {message.role === 'assistant' && message.questionCategory && <p className="mt-2 border-t border-slate-200 pt-2 text-xs text-slate-500">생각한 근거: {getMetadataLabel(metadata?.chat_question_category_details, message.questionCategory, message.questionCategory)}</p>}
          {message.role === 'assistant' && !message.isStreaming && message.text && <div className="mt-2 flex justify-end border-t border-slate-200 pt-2"><button type="button" onClick={() => void copyAnswer(message.id, message.text)} className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200 hover:text-slate-900" aria-label="답변 복사">{copiedAnswerId === message.id ? <Check className="size-3.5" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}{copiedAnswerId === message.id ? '복사됨' : '답변 복사'}</button></div>}
        </div>
        if (message.role === 'user') return <div key={message.id} className="flex justify-end">{bubble}</div>
        return <div key={message.id} className="space-y-2"><PreparationPanel message={message} expanded={expanded} onToggle={() => togglePreparation(message.id)} isStreaming={message.isStreaming === true} metadata={metadata} />{message.isStreaming && !message.text && <p data-testid="typing-dots" className="pl-2 font-mono font-semibold tracking-[0.2em] text-slate-500" aria-label="답변을 작성하고 있습니다">{typingDots}</p>}<div className="flex justify-start">{bubble}</div></div>
      })}
      <div ref={bottomRef} />
    </div>
    {error && <div className="mx-4 mb-2 rounded-lg bg-rose-50 p-3 text-xs text-rose-700" role="alert">{error}{errorRetryable && <button type="button" onClick={() => void send()} className="ml-2 inline-flex items-center gap-1 font-semibold underline"><RotateCcw className="size-3" />재시도</button>}</div>}
    <div className="flex gap-2 border-t border-slate-200 p-3"><input ref={inputRef} value={input} disabled={isSending} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) void send() }} placeholder="검토 결과에 대해 질문해 주세요" className="min-h-11 min-w-0 flex-1 rounded-xl border border-slate-200 px-3 text-sm disabled:bg-slate-100" /><button type="button" onClick={() => void send()} disabled={!input.trim() || isSending} aria-label="질문 전송" className="rounded-xl bg-blue-600 px-4 text-white disabled:bg-slate-300"><Send className="size-4" /></button></div>
  </aside>
}
