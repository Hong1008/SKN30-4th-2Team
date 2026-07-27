import { useState, useRef } from 'react'
import {
  UploadCloud, FileText, CheckCircle2, X, ChevronRight, BriefcaseBusiness, Handshake
} from 'lucide-react'
import { mockApi } from '../api/mockApi'
import { TEMP_FILE_MAX_SIZE, SESSION_ID_KEY, REVIEW_ID_KEY } from '../config'

interface Props { 
  sessionId: string | null;
  setSessionId: (id: string | null) => void;
  setReviewId: (id: string | null) => void;
  onNext: () => void;
  onOutOfScope: () => void;
}

type UploadState = 'idle' | 'uploading' | 'success'

const FORMATS = ['HWP', 'HWPX', 'PDF', 'DOCX']

const CONTRACT_TYPES = [
  { id: 'SI_SUBCONTRACT', name: 'SI 하도급', sub: 'SI 구축 하도급 계약 비교 기준입니다.' },
  { id: 'SW_FREELANCE', name: 'SW 프리랜서 용역', sub: 'SW 프리랜서 도급·용역 계약 비교 기준입니다.' },
  { id: 'SM_SUBCONTRACT', name: 'SM 하도급', sub: 'SM 운영·유지보수 하도급 계약 비교 기준입니다.' },
]

export default function UploadAndTypeScreen({ sessionId, setSessionId, setReviewId, onNext, onOutOfScope }: Props) {
  const [uploadState, setUploadState] = useState<UploadState>('idle')
  const [isDragging, setIsDragging]   = useState(false)
  const [progress, setProgress]        = useState(0)
  const [fileName, setFileName]        = useState('')
  const [fileSizeStr, setFileSizeStr]  = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  
  const [selectedType, setSelectedType] = useState('')
  const [suggestedType, setSuggestedType] = useState('')
  const [errorMsg, setErrorMsg] = useState('')

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    processFile(file)
  }

  const processFile = async (file: File) => {
    setErrorMsg('')
    if (file.size > TEMP_FILE_MAX_SIZE) {
      setErrorMsg(`파일 크기가 10MB를 초과합니다. (현재: ${(file.size / 1024 / 1024).toFixed(1)}MB)`)
      return
    }

    const extension = file.name.split('.').pop()?.toUpperCase() || ''
    if (!FORMATS.includes(extension)) {
      setErrorMsg(`지원하지 않는 파일 형식입니다. (.${extension.toLowerCase()})`)
      return
    }

    setFileName(file.name)
    setFileSizeStr((file.size / 1024).toFixed(1) + ' KB')
    setUploadState('uploading')
    setProgress(0)

    // Simulate progress while API is called
    const id = setInterval(() => {
      setProgress(p => Math.min(p + Math.random() * 20, 90))
    }, 200)

    try {
      const response = await mockApi.uploadContract(file)
      clearInterval(id)
      
      // [4] EMPTY_DOCUMENT 처리: 파일은 올라갔으나 조항이 없는 경우
      if (response.data.can_start_review === false && response.data.allowed_actions?.includes('REUPLOAD')) {
        setUploadState('idle')
        setErrorMsg('문서 내에 추출 가능한 계약 조항이 없습니다. (EMPTY_DOCUMENT)')
        return
      }

      setProgress(100)
      setUploadState('success')
      
      const newSessionId = response.data.session_id
      setSessionId(newSessionId)
      localStorage.setItem(SESSION_ID_KEY, newSessionId)

      if (response.data.suggested_contract_type) {
        setSelectedType(response.data.suggested_contract_type)
        setSuggestedType(response.data.suggested_contract_type)
      }
    } catch (err: any) {
      clearInterval(id)
      setUploadState('idle')
      
      // [4] 업로드 정밀 에러 및 세션 에러 분기
      const status = err?.response?.status || err?.status
      if (status === 413) setErrorMsg('파일 용량이 서버 허용 제한(10MB)을 초과했습니다.')
      else if (status === 415) setErrorMsg('지원하지 않는 파일 형식이거나 실제 파일 타입이 불일치합니다.')
      else if (status === 422) setErrorMsg('파일이 암호화되어 있거나 손상되어 읽을 수 없습니다.')
      else if (status === 404 || status === 410) {
        alert('유효하지 않거나 만료된 세션입니다. 처음부터 다시 시작합니다.')
        localStorage.clear()
        window.location.reload()
      } else {
        setErrorMsg('업로드에 실패했습니다. 다시 시도해주세요.')
      }
    }
  }

  const handleNext = async () => {
    if (!sessionId) return
    try {
      // 1. Confirm contract type
      const scopeRes = await mockApi.selectContractType(sessionId, selectedType)
      
      // [3] 범위 외 확인(OUT_OF_SCOPE_CONFIRMATION_REQUIRED) 처리
      if (scopeRes.data.scope_status === 'OUT_OF_SCOPE_CONFIRMATION_REQUIRED') {
        onOutOfScope()
        return
      }

      // 2. Start review (with Idempotency-Key)
      const idempotencyKey = crypto.randomUUID()
      const reviewRes = await mockApi.startReview(sessionId, idempotencyKey)
      setReviewId(reviewRes.data.review_id)
      localStorage.setItem(REVIEW_ID_KEY, reviewRes.data.review_id)
      
      // 3. Move to processing screen
      onNext()
    } catch (err: any) {
      const status = err?.response?.status || err?.status
      if (status === 409) {
        // [4] 409 IDEMPOTENCY_KEY_REUSED 처리
        console.warn('이미 처리 중인 검토 요청입니다.')
        onNext() // 기존 처리 내역이 있다고 가정하고 넘어감
      } else if (status === 404 || status === 410) {
        alert('유효하지 않거나 만료된 세션입니다. 처음부터 다시 시작합니다.')
        localStorage.clear()
        window.location.reload()
      } else {
        setErrorMsg('검토 시작 요청에 실패했습니다.')
      }
    }
  }

  const reset = () => { 
    setUploadState('idle')
    setProgress(0)
    setErrorMsg('')
    setSessionId(null)
    setReviewId(null)
    localStorage.removeItem(SESSION_ID_KEY)
    localStorage.removeItem(REVIEW_ID_KEY)
  }

  return (
    <div className="space-y-10 animate-fade-up">
      {/* ── 1. Upload Section ── */}
      <section className="space-y-6">
        <div>
          <p className="text-xs font-semibold tracking-[.14em] text-[#6366F1] mb-3">1단계 · 파일 업로드</p>
          <h1 className="text-[22px] font-semibold text-[#1E293B] tracking-tight mb-2">
            검토할 계약서를 업로드해 주세요
          </h1>
          <p className="text-sm text-[#475569] leading-relaxed">
            업로드한 문서는 검토 목적으로만 일시적으로 처리되며, 완료 후 서버에서 자동 삭제됩니다.
          </p>
        </div>

        {errorMsg && (
          <div className="bg-red-50 border border-red-200 text-red-600 text-sm px-4 py-3 rounded-lg">
            {errorMsg}
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
              if (uploadState === 'uploading') return;
              setIsDragging(false); 
              const file = e.dataTransfer.files?.[0]
              if (file) processFile(file)
            }}
            onClick={() => {
              if (uploadState !== 'uploading') fileRef.current?.click()
            }}
            className={`relative min-h-[340px] border-2 border-dashed rounded-2xl flex flex-col items-center justify-center text-center transition-all duration-200 ${
              isDragging
                ? 'border-[#6366F1] bg-[#EEF2FF]'
                : 'border-[#CBD5E1] bg-white hover:border-[#6366F1] hover:bg-[#EEF2FF]/40'
            }`}
          >
            <input ref={fileRef} type="file" className="hidden" accept=".hwp,.hwpx,.hwpml,.pdf,.xls,.xlsx,.docx" onChange={handleFileChange} disabled={uploadState === 'uploading'} />
            
            <div className="flex-1 flex flex-col items-center justify-center w-full px-6 py-12">
              <div className={`w-24 h-24 rounded-3xl flex items-center justify-center mb-6 transition-colors shadow-sm ${
                isDragging ? 'bg-[#6366F1]' : 'bg-[#EEF2FF]'
              }`}>
                <UploadCloud className={`w-14 h-14 transition-colors ${isDragging ? 'text-white' : 'text-[#6366F1]'}`} />
              </div>
              <p className="text-[17px] font-semibold text-[#1E293B] mb-2 tracking-tight">
                파일을 이곳에 드래그하거나 직접 선택하세요
              </p>
              
              <p className="text-xs font-medium text-[#94A3B8] tracking-[0.2em] mb-8">
                {FORMATS.join(' · ')}
              </p>

              <button
                onClick={e => { e.stopPropagation(); fileRef.current?.click() }}
                className="px-6 py-3 bg-[#6366F1] text-white rounded-xl text-sm font-medium hover:bg-[#4F46E5] transition-colors shadow-sm"
              >
                파일 선택
              </button>
            </div>
            
            <div className="absolute bottom-5 left-0 right-0 text-center">
              <p className="text-xs text-[#64748B] font-medium">최대 10MB까지 업로드 가능합니다</p>
            </div>
          </div>
        )}

        {/* Uploading */}
        {uploadState === 'uploading' && (
          <div className="bg-white border border-[#E2E8F0] rounded-2xl p-6 shadow-sm">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 bg-[#EEF2FF] rounded-xl flex items-center justify-center shrink-0">
                <FileText className="w-5 h-5 text-[#6366F1]" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-medium text-[#1E293B] truncate pr-4">{fileName}</p>
                  <span className="text-xs text-[#475569] shrink-0">{fileSizeStr}</span>
                </div>
                <div className="flex items-center gap-3 mb-1.5">
                  <div className="flex-1 h-1.5 bg-[#E2E8F0] rounded-full overflow-hidden">
                    <div
                      className="h-full bg-[#6366F1] rounded-full transition-all duration-300"
                      style={{ width: `${Math.min(progress, 100)}%` }}
                    />
                  </div>
                  <span className="text-xs font-medium text-[#475569] shrink-0">전송 중</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Success */}
        {uploadState === 'success' && (
          <div className="bg-white border border-emerald-200 rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 bg-emerald-50 rounded-xl flex items-center justify-center shrink-0">
                <CheckCircle2 className="w-5 h-5 text-emerald-500" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-[#1E293B] truncate">{fileName}</p>
                <p className="text-xs text-[#475569] mt-0.5">{fileSizeStr} · 업로드 완료</p>
              </div>
              <button onClick={reset} aria-label="파일 제거" className="text-[#64748B] hover:text-[#475569] transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </section>

      <hr className="border-[#E2E8F0]" />

      {/* ── 2. Contract Type Section ── */}
      <section className="space-y-6">
        <div>
          <p className="text-xs font-semibold tracking-[.14em] text-[#6366F1] mb-3">2단계 · 비교 기준</p>
          <h2 className="text-[22px] font-semibold text-[#1E293B] tracking-tight mb-2">계약 유형 선택</h2>
          <p className="text-sm text-[#475569] leading-relaxed mb-1">
            실제 계약 관계에 가장 가까운 유형을 선택해 주세요.
          </p>
          <p className="text-xs text-[#64748B] italic">
            * 그 외의 계약서 지원 서비스는 추후 확장 예정입니다.
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-3">
          {CONTRACT_TYPES.map((type) => {
            const active = selectedType === type.id
            return (
              <button 
                key={type.id} 
                onClick={() => setSelectedType(type.id)} 
                aria-pressed={active}
                className={`relative min-h-[80px] py-3 px-2 rounded-xl border-2 transition-all flex flex-col items-center justify-center text-center ${
                  active 
                    ? 'border-[#6366F1] bg-[#EEF2FF]/40 shadow-sm' 
                    : 'border-[#E2E8F0] bg-white hover:border-[#93C5FD] hover:bg-slate-50'
                }`}
              >
                {suggestedType === type.id && (
                  <span className="absolute -top-3 right-2 bg-rose-500 text-white text-[10px] font-bold px-2 py-0.5 rounded-full shadow-sm">
                    AI 추천
                  </span>
                )}
                <div className="flex items-center justify-center gap-1.5 w-full">
                  <h3 className={`text-[14px] font-semibold ${active ? 'text-[#6366F1]' : 'text-[#1E293B]'}`}>{type.name}</h3>
                  {active && (
                    <CheckCircle2 className="w-4 h-4 text-[#6366F1]" />
                  )}
                </div>
                <p className="text-[11px] text-[#64748B] mt-1 leading-relaxed break-keep">{type.sub}</p>
              </button>
            )
          })}
        </div>

        <div className="rounded-xl border border-[#E2E8F0] bg-white px-5 py-4 flex flex-col sm:flex-row sm:items-center gap-3">
          <p className="text-xs text-[#475569] leading-relaxed flex-1">
            해당하는 계약 유형이 없다면, 제공 범위를 먼저 확인해 주세요.
          </p>
          <button onClick={onOutOfScope} className="text-sm font-semibold text-[#6366F1] hover:text-[#4F46E5]">
            제공 범위 확인
          </button>
        </div>
      </section>

      {/* ── 3. Bottom Controls & Help ── */}
      <div className="flex flex-col-reverse sm:flex-row sm:items-center justify-between pt-4 gap-6">
        <div className="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3 border-dashed">
          <p className="text-xs font-medium text-slate-500">
            [도움이 필요하신가요?] 임시 영역 (팀 논의 후 삭제 또는 유지)
          </p>
        </div>

        <button
          onClick={handleNext}
          disabled={uploadState !== 'success' || !selectedType}
          className={`inline-flex items-center justify-center gap-2 rounded-xl px-8 py-3.5 text-sm font-semibold transition-all ${
            uploadState === 'success' && selectedType
              ? 'bg-[#6366F1] text-white hover:bg-[#4F46E5] shadow-md shadow-blue-500/20'
              : 'bg-[#E2E8F0] text-[#94A3B8] cursor-not-allowed'
          }`}
        >
          선택한 유형으로 검토 시작 <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

