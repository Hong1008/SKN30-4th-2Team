import { useEffect, useState, useRef } from 'react'
import {
  UploadCloud, FileText, CheckCircle2, X, ChevronRight, AlertCircle
} from 'lucide-react'
import { api } from '../api/api'
import { TEMP_FILE_MAX_SIZE, SESSION_ID_KEY, REVIEW_ID_KEY } from '../config'
import { useMetadata } from '../contexts/MetadataContext'
import { useToast } from '../contexts/ToastContext'
import type { SelectionSource } from '../types'
import { getErrorMessage, getNextAction } from '../utils/apiErrors'

interface Props { 
  sessionId: string | null;
  setSessionId: (id: string | null) => void;
  setReviewId: (id: string | null) => void;
  onNext: (reviewId: string) => void;
  onOutOfScope: () => void;
  setSessionExpiresAt: (expiresAt: string | null) => void;
}

type UploadState = 'idle' | 'uploading' | 'success'

export default function UploadAndTypeScreen({ sessionId, setSessionId, setReviewId, onNext, onOutOfScope, setSessionExpiresAt }: Props) {
  const { metadata } = useMetadata()
  const { showToast } = useToast()
  const formats = metadata?.file_policy.extensions.map(e => e.toUpperCase()) || []
  const maxSizeBytes = metadata?.file_policy.max_size_bytes || TEMP_FILE_MAX_SIZE
  const contractTypes = metadata?.contract_types.filter(t => t.enabled_for_mvp) || []

  const [uploadState, setUploadState] = useState<UploadState>('idle')
  const [isDragging, setIsDragging]   = useState(false)
  const [fileName, setFileName]        = useState('')
  const [fileSizeStr, setFileSizeStr]  = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const startRequestKey = useRef<string | null>(null)
  
  const [selectedType, setSelectedType] = useState('')
  const [suggestedType, setSuggestedType] = useState<string | null>(null)
  const [candidateTypes, setCandidateTypes] = useState<string[]>([])
  const [errorMsg, setErrorMsg] = useState('')
  const [emptyDocError, setEmptyDocError] = useState(false)

  useEffect(() => {
    if (!sessionId || uploadState !== 'idle') return
    const controller = new AbortController()

    api.getSession(sessionId, controller.signal)
      .then(({ data }) => {
        if (!data.upload) return
        setFileName(data.upload.file_name)
        setFileSizeStr(`${(data.upload.size_bytes / 1024).toFixed(1)} KB`)
        setSelectedType(data.selected_contract_type || '')
        setSuggestedType(data.suggested_contract_type)
        setCandidateTypes(data.candidates.map(candidate => candidate.contract_type))
        setSessionExpiresAt(data.expires_at)
        setUploadState('success')
        if (data.review_state === 'OUT_OF_SCOPE_CONFIRMATION_REQUIRED' && data.selected_contract_type) {
          onOutOfScope()
        }
      })
      .catch((error) => {
        if (error?.name === 'AbortError') return
        if (error?.status === 404 || error?.status === 410) {
          setSessionId(null)
          localStorage.removeItem(SESSION_ID_KEY)
        } else {
          setErrorMsg(getErrorMessage(error, '이전 검토 세션을 불러오지 못했습니다.'))
        }
      })

    return () => controller.abort()
  }, [sessionId, uploadState, onOutOfScope, setSessionExpiresAt, setSessionId])

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    processFile(file)
  }

  const processFile = async (file: File) => {
    setErrorMsg('')
    setEmptyDocError(false)
    if (file.size > maxSizeBytes) {
      setErrorMsg(`파일 크기가 제한(${(maxSizeBytes / 1024 / 1024).toFixed(1)}MB)을 초과합니다. (현재: ${(file.size / 1024 / 1024).toFixed(1)}MB)`)
      return
    }

    const extension = file.name.split('.').pop()?.toUpperCase() || ''
    if (!formats.includes(extension)) {
      setErrorMsg(`지원하지 않는 파일 형식입니다. (.${extension.toLowerCase()})`)
      return
    }

    setFileName(file.name)
    setFileSizeStr((file.size / 1024).toFixed(1) + ' KB')
    setUploadState('uploading')

    try {
      const response = await api.uploadContract(file)
      
      // [4] EMPTY_DOCUMENT 처리: 파일은 올라갔으나 조항이 없는 경우
      if (response.data.can_start_review === false && response.data.allowed_actions?.includes('REUPLOAD')) {
        setUploadState('idle')
        setEmptyDocError(true)
        return
      }

      setUploadState('success')
      setSelectedType('')
      setSuggestedType(response.data.suggested_contract_type)
      setCandidateTypes(response.data.candidates.map(candidate => candidate.contract_type))
      setSessionExpiresAt(response.data.expires_at)
      
      const newSessionId = response.data.session_id
      setSessionId(newSessionId)
      localStorage.setItem(SESSION_ID_KEY, newSessionId)

      showToast('파일 업로드가 완료되었습니다.', 'success')
    } catch (err: any) {
      setUploadState('idle')
      const nextAction = getNextAction(err)
      
      // [4] 업로드 정밀 에러 및 세션 에러 분기
      const status = err?.response?.status || err?.status
      if (status === 413) setErrorMsg('파일 용량이 서버 허용 제한(10MB)을 초과했습니다.')
      else if (status === 415) setErrorMsg('지원하지 않는 파일 형식이거나 실제 파일 타입이 불일치합니다.')
      else if (status === 422) setErrorMsg('파일이 암호화되어 있거나 손상되어 읽을 수 없습니다.')
      else if (status === 404 || status === 410) {
        showToast('유효하지 않거나 만료된 세션입니다. 처음부터 다시 시작합니다.', 'error')
        reset()
      } else if (nextAction === 'REUPLOAD') {
        setErrorMsg(getErrorMessage(err, '파일을 확인한 후 다시 업로드해 주세요.'))
      } else if (nextAction === 'CONTACT_SUPPORT') {
        setErrorMsg(getErrorMessage(err, '서비스 설정을 확인할 수 없습니다. 관리자에게 문의해 주세요.'))
      } else {
        setErrorMsg('업로드에 실패했습니다. 다시 시도해주세요.')
      }
    }
  }

  const handleNext = async () => {
    if (!sessionId) return
    try {
      // 1. Confirm contract type
      const selectionSource: SelectionSource = selectedType === suggestedType
        ? 'SUGGESTED'
        : candidateTypes.includes(selectedType)
          ? 'CANDIDATE'
          : 'MANUAL'
      const scopeRes = await api.selectContractType(sessionId, selectedType, selectionSource)
      setSessionExpiresAt(scopeRes.data.expires_at)
      
      // [3] 범위 외 확인(OUT_OF_SCOPE_CONFIRMATION_REQUIRED) 처리
      if (scopeRes.data.review_state === 'OUT_OF_SCOPE_CONFIRMATION_REQUIRED') {
        onOutOfScope()
        return
      }

      if (!scopeRes.data.can_start_review && !scopeRes.data.allowed_actions?.includes('START_REVIEW')) {
        setErrorMsg('현재 계약 유형으로 검토를 시작할 수 없습니다.')
        return
      }

      // 2. Start review (with Idempotency-Key)
      const idempotencyKey = startRequestKey.current ?? crypto.randomUUID()
      startRequestKey.current = idempotencyKey
      const reviewRes = await api.startReview(sessionId, idempotencyKey)
      startRequestKey.current = null
      setReviewId(reviewRes.data.review_id)
      localStorage.setItem(REVIEW_ID_KEY, reviewRes.data.review_id)
      
      // 3. Move to processing screen
      onNext(reviewRes.data.review_id)
    } catch (err: any) {
      const status = err?.status
      const nextAction = getNextAction(err)
      const existingReviewId = err?.details?.review_id
      if (status === 409 && existingReviewId) {
        startRequestKey.current = null
        setReviewId(existingReviewId)
        localStorage.setItem(REVIEW_ID_KEY, existingReviewId)
        onNext(existingReviewId)
      } else if (status === 409) {
        setErrorMsg(getErrorMessage(err, '동일 요청이 이미 처리 중입니다. 잠시 후 다시 확인해 주세요.'))
      } else if (status === 404 || status === 410) {
        showToast('유효하지 않거나 만료된 세션입니다. 처음부터 다시 시작합니다.', 'error')
        reset()
      } else if (nextAction === 'SELECT_CONTRACT_TYPE') {
        setErrorMsg(getErrorMessage(err, '계약 유형을 다시 선택해 주세요.'))
      } else if (nextAction === 'CONFIRM_OUT_OF_SCOPE') {
        onOutOfScope()
      } else if (nextAction === 'START_NEW_REVIEW') {
        reset()
      } else {
        setErrorMsg('검토 시작 요청에 실패했습니다.')
      }
    }
  }

  const reset = () => { 
    setUploadState('idle')
    setErrorMsg('')
    setEmptyDocError(false)
    setSessionId(null)
    setReviewId(null)
    setSessionExpiresAt(null)
    startRequestKey.current = null
    localStorage.removeItem(SESSION_ID_KEY)
    localStorage.removeItem(REVIEW_ID_KEY)
    if (fileRef.current) fileRef.current.value = ''
  }

  return (
    <div className="mx-auto w-full max-w-[760px] space-y-8 pb-24">
      {/* ── 1. Upload & Type Section ── */}
      <section className="
        space-y-7 rounded-2xl border border-slate-200/80 bg-white
        p-6 shadow-[0_1px_2px_rgba(15,23,42,0.03)] sm:p-8
      ">
        <div className="mb-7">
          <h1 className="
            text-xl font-semibold leading-tight
            tracking-[-0.02em] text-slate-950 sm:text-2xl
          ">
            검토할 계약서를 업로드해 주세요
          </h1>

          <p className="mt-2 max-w-2xl break-keep text-sm leading-6 text-slate-500">
            업로드한 문서는 계약서 검토 목적으로만 처리됩니다.
          </p>
        </div>

        {errorMsg && (
          <div className="flex items-center gap-3 rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3.5 text-sm font-medium text-rose-700 animate-fade-up">
            <AlertCircle className="w-5 h-5 shrink-0" />
            <p>{errorMsg}</p>
          </div>
        )}

        {emptyDocError && (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 rounded-2xl border border-amber-200 bg-amber-50/70 p-5 animate-fade-up">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <h4 className="text-sm font-bold text-amber-900 mb-1">검토 가능한 조항이 없습니다</h4>
                <p className="text-xs text-amber-700/90 break-keep">
                  파일 검증은 통과했으나, 문서 내에서 비교 가능한 표준 계약 조항을 추출하지 못했습니다. 글자가 포함된 정상적인 계약서인지 확인 후 다시 업로드해 주세요.
                </p>
              </div>
            </div>
            <button
              onClick={() => fileRef.current?.click()}
              className="shrink-0 inline-flex items-center justify-center rounded-xl bg-amber-600 px-4 py-2.5 text-xs font-semibold text-white shadow-sm hover:bg-amber-700 transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-amber-500/20"
            >
              새 문서 업로드
            </button>
          </div>
        )}

        {uploadState === 'idle' && (
          <div
            role="button"
            tabIndex={0}
            onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={e => { 
              e.preventDefault(); 
              setIsDragging(false); 
              const file = e.dataTransfer.files?.[0]
              if (file) processFile(file)
            }}
            onClick={() => {
              fileRef.current?.click()
            }}
            className={`group relative flex min-h-[200px] cursor-pointer flex-col items-center justify-center overflow-hidden rounded-2xl border-2 border-dashed px-6 py-6 text-center transition-all duration-200 ease-out focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15 ${
              isDragging
                ? 'scale-[1.01] border-blue-500 bg-blue-50 shadow-lg shadow-blue-500/10'
                : 'border-slate-300 bg-slate-50/60 hover:border-blue-400 hover:bg-blue-50/50'
            }`}
          >
            <input ref={fileRef} type="file" className="hidden" accept={formats.map(f => `.${f.toLowerCase()}`).join(',')} onChange={handleFileChange} />
            
            <div className="flex w-full flex-col items-center justify-center px-4 py-6">
              <div className={`mb-3 flex size-12 items-center justify-center rounded-xl transition-all duration-200 group-hover:-translate-y-0.5 ${
                isDragging
                  ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/25'
                  : 'bg-white text-blue-600 shadow-sm ring-1 ring-slate-200'
              }`}>
                <UploadCloud className={`size-6 transition-colors ${isDragging ? 'text-white' : 'text-blue-600'}`} />
              </div>
              <p className="mb-2 text-[15px] font-semibold leading-6 tracking-[-0.01em] text-slate-900">
                파일을 이곳에 드래그하거나 직접 선택하세요
              </p>
              
              <p className="mb-4 text-xs font-medium tracking-[0.08em] text-slate-500">
                {formats.join(' · ')}
              </p>

              <button
                onClick={e => { e.stopPropagation(); fileRef.current?.click() }}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-xs font-semibold text-slate-700 transition-colors duration-150 hover:border-blue-400 hover:bg-blue-50 hover:text-blue-700 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15"
              >
                파일 선택
              </button>
            </div>
            
            <div className="absolute bottom-5 left-0 right-0 text-center">
              <p className="text-xs text-slate-500 font-medium">최대 {(maxSizeBytes / 1024 / 1024).toFixed(1)}MB까지 업로드 가능합니다</p>
            </div>
          </div>
        )}

        {/* Uploading */}
        {uploadState === 'uploading' && (
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center shrink-0">
                <FileText className="w-5 h-5 text-blue-600" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-medium text-slate-950 truncate pr-4">{fileName}</p>
                  <span className="text-xs text-slate-600 shrink-0">{fileSizeStr}</span>
                </div>
                <div className="flex items-center gap-3 mb-1.5">
                  <div className="flex-1 h-2 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="h-full w-full animate-pulse rounded-full bg-gradient-to-r from-blue-600 to-cyan-500"
                    />
                  </div>
                  <span className="text-xs font-medium text-slate-600 shrink-0">업로드·분석 중</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Success */}
        {uploadState === 'success' && (
          <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-emerald-500">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 bg-emerald-50 rounded-xl flex items-center justify-center shrink-0">
                <CheckCircle2 className="w-5 h-5 text-emerald-500" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-slate-950 truncate">{fileName}</p>
                <p className="text-xs text-slate-600 mt-0.5">{fileSizeStr} · 업로드 완료</p>
              </div>
              <button onClick={reset} aria-label="파일 제거" className="text-slate-400 hover:text-rose-500 transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
        {/* ── 2. Contract Type Section ── */}
        <div className="space-y-4 border-t border-slate-100 pt-6">

        <div className="grid md:grid-cols-3 gap-3">
          {contractTypes.map((type) => {
            const active = selectedType === type.code
            return (
              <button 
                key={type.code} 
                onClick={() => {
                  setSelectedType(type.code)
                  startRequestKey.current = null
                }}
                aria-pressed={active}
                className={`relative min-h-20 rounded-xl border px-4 py-3.5 text-left transition-all duration-200 ease-out focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/15 ${
                  active 
                    ? 'border-blue-500 bg-blue-50/30 shadow-sm ring-2 ring-blue-500/10'
                    : 'border-slate-200 bg-white hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-sm'
                }`}
              >
                <div className="flex w-full items-center justify-between gap-2">
                  <h3 className={`text-sm font-semibold ${active ? 'text-blue-700' : 'text-slate-900'}`}>{type.label}</h3>
                  {active && (
                    <CheckCircle2 className="w-5 h-5 text-blue-600" />
                  )}
                </div>
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{type.description}</p>
              </button>
            )
          })}

        </div>

        <div className="rounded-xl bg-slate-50/70 px-5 py-4">
          <p className="text-xs text-slate-600 leading-relaxed flex-1">
            현재 지원 범위: {contractTypes.map(type => type.label).join(', ')}
            <br />
            선택한 계약 유형과 문서 내용이 일치하지 않는 경우, 검토 전에 확인 안내가 표시됩니다.
          </p>
        </div>
        <div className="flex justify-end">
          <p className="text-xs text-slate-500 italic">
            * 그 외의 계약서 지원 서비스는 추후 확장 예정입니다.
          </p>
        </div>
        </div>
      </section>

      {/* ── 3. Bottom Controls & Help ── */}
      <div className="sticky bottom-4 z-20 flex flex-col-reverse gap-3 rounded-2xl border border-slate-200/80 bg-white/95 p-3 shadow-[0_8px_24px_rgba(15,23,42,0.07)] backdrop-blur-xl sm:flex-row sm:items-center sm:justify-end">
        <button
          onClick={handleNext}
          disabled={uploadState !== 'success' || !selectedType}
          className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold transition-[background-color,box-shadow,transform] duration-150 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/20 ${
            uploadState === 'success' && selectedType
              ? 'bg-blue-600 text-white shadow-[0_1px_2px_rgba(37,99,235,0.2),0_6px_16px_rgba(37,99,235,0.16)] hover:-translate-y-px hover:bg-blue-700 hover:shadow-md active:translate-y-0 active:bg-blue-800'
              : 'cursor-not-allowed bg-slate-200 text-slate-500'
          }`}
        >
          선택한 유형으로 검토 시작 <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

